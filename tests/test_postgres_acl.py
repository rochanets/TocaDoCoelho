"""ACL/visibilidade (Fase 4) contra PostgreSQL.

Valida que as cláusulas de visibilidade introduzidas na Fase 4 — EXISTS sobre
`shares`, COALESCE(owner_id, (SELECT MIN(id) FROM users)) e o IN-subquery do
admin org-scoped — são traduzidas pelo wrapper SQLite→PG e rodam de fato no
Postgres (o smoke da Fase 2 só exercita o caminho login-off, onde a cláusula é
'1=1'). Roda só no CI com serviço Postgres; pulado localmente sem DATABASE_URL.
"""
import os
import uuid

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


@pytest.fixture(scope='module')
def client():
    toca.app.config['TESTING'] = True
    toca.app.config['SESSION_COOKIE_SECURE'] = False
    with toca.app.test_client() as c:
        yield c


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES (?)", (f'OrgACL-{uuid.uuid4().hex[:8]}',))
    org_id = c.lastrowid

    def _mk(role):
        email = f'{role}-{uuid.uuid4().hex[:10]}@ex.com'
        c.execute("INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
                  (org_id, email, email, role))
        return c.lastrowid

    admin_id, a_id, b_id = _mk('admin'), _mk('member'), _mk('member')
    conn.commit(); conn.close()
    return org_id, admin_id, a_id, b_id


def _new_client(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, ?, ?)",
              (name, 'CoACL', 'Cargo', owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _share(record_type, record_id, user_id, permission='read'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO shares (record_type, record_id, shared_with_user_id, permission) "
              "VALUES (?, ?, ?, ?)", (record_type, record_id, user_id, permission))
    conn.commit(); conn.close()


def test_pg_member_visibility_and_shares(client, monkeypatch):
    """Exercita EXISTS(shares) + COALESCE owner no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    own = _new_client(a_id, f'own-{tag}')
    shared = _new_client(b_id, f'shared-{tag}')
    hidden = _new_client(b_id, f'hidden-{tag}')
    _share('clients', shared, a_id, 'read')

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.get('/api/clients')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    names = {c['name'] for c in r.get_json()}
    assert f'own-{tag}' in names            # dono
    assert f'shared-{tag}' in names         # compartilhado (read)
    assert f'hidden-{tag}' not in names     # de outro dono, sem share


def test_pg_admin_org_scope(client, monkeypatch):
    """Exercita o IN-subquery org-scoped do admin no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    _new_client(a_id, f'adm-a-{tag}')
    _new_client(b_id, f'adm-b-{tag}')

    with client.session_transaction() as s:
        s['user_id'] = admin_id
    r = client.get('/api/clients')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    names = {c['name'] for c in r.get_json()}
    assert f'adm-a-{tag}' in names and f'adm-b-{tag}' in names


def test_pg_write_guard(client, monkeypatch):
    """can_write no Postgres: escrita em registro de outro dono é negada."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    cb = _new_client(b_id, f'wg-{tag}')

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.put(f'/api/clients/{cb}', data={'name': 'X', 'company': 'Y', 'position': 'Z'})
    assert r.status_code == 404  # nem visível → 404 (sem vazar existência)


def test_pg_create_sets_owner(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.post('/api/clients', data={'name': f'c-{uuid.uuid4().hex[:8]}',
                                          'company': 'Co', 'position': 'P'})
    assert r.status_code == 201, r.get_data(as_text=True)[:300]
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT owner_id FROM clients WHERE id = ?', (r.get_json()['id'],))
    owner = c.fetchone()['owner_id']; conn.close()
    assert owner == a_id


# ── Kanban por-usuário: exercita owned_where + EXISTS(pai) no Postgres ───────

def test_pg_kanban_board_isolated(client, monkeypatch):
    """Quadro por-usuário no PG: A e B têm quadros distintos; B não vê/mexe no
    card de A (valida owned_where raiz + filha traduzidos)."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    with client.session_transaction() as s:
        s['user_id'] = a_id
    assert client.get('/api/kanban/columns').status_code == 200   # semeia quadro de A
    r = client.post('/api/kanban/cards', json={'title': f'A-{tag}', 'description': 'd'})
    assert r.status_code == 201, r.get_data(as_text=True)[:300]
    card_a = r.get_json()['id']
    assert f'A-{tag}' in {c['title'] for c in client.get('/api/kanban/cards').get_json()}

    with client.session_transaction() as s:
        s['user_id'] = b_id
    assert client.get('/api/kanban/columns').status_code == 200   # quadro próprio de B
    assert all(c['title'] != f'A-{tag}' for c in client.get('/api/kanban/cards').get_json())
    assert client.delete(f'/api/kanban/cards/{card_a}').status_code == 404


def test_pg_kanban_child_activity_recursion(client, monkeypatch):
    """kanban_card_activities → kanban_cards → kanban_columns (EXISTS aninhado
    em 2 níveis) traduzido e executado no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    with client.session_transaction() as s:
        s['user_id'] = a_id
    client.get('/api/kanban/columns')
    card = client.post('/api/kanban/cards', json={'title': f'AC-{tag}', 'description': 'd'}).get_json()['id']
    assert client.post(f'/api/kanban/cards/{card}/activities', json={'content': 'oi'}).status_code == 201

    with client.session_transaction() as s:
        s['user_id'] = b_id
    client.get('/api/kanban/columns')
    assert client.post(f'/api/kanban/cards/{card}/activities', json={'content': 'x'}).status_code == 404


# ── Agenda: UNION (commitments + account_renewal_events filha) + DATE() no PG ─

def test_pg_agenda_union_filtered(client, monkeypatch):
    """A visão unificada da agenda cruza commitments (raiz) e
    account_renewal_events (filha de accounts) com DATE() e visible_where —
    valida a tradução do UNION + EXISTS(pai) + funções de data no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()
    ca = _new_client(a_id, f'ca-{tag}'); cb = _new_client(b_id, f'cb-{tag}')
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, ?, ?, '2026-08-01', 'manual', ?)", (ca, f'CA-{tag}', 'x', a_id))
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, ?, ?, '2026-08-01', 'manual', ?)", (cb, f'CB-{tag}', 'x', b_id))
    # evento de renovação (filho de accounts) do A
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (f'accR-{tag}', a_id))
    acc = c.lastrowid
    c.execute("INSERT INTO account_presences (account_id, delivery_name) VALUES (?, 'D')", (acc,))
    pres = c.lastrowid
    c.execute("INSERT INTO account_renewal_events (account_id, presence_id, title, due_date) "
              "VALUES (?, ?, 'Renovação', '2026-08-02')", (acc, pres))
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.get('/api/agenda')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    items = r.get_json()
    titles = {i['title'] for i in items}
    companies = {i.get('client_company') for i in items}
    assert f'CA-{tag}' in titles and f'CB-{tag}' not in titles    # commitments filtrados
    assert f'accR-{tag}' in companies                              # renovação (filha) do A visível


def test_pg_briefing_child_of_commitment(client, monkeypatch):
    """meeting_briefings → commitments (EXISTS filha) traduzido no Postgres, via
    a rota de briefing e via can_read direto."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()
    ca = _new_client(a_id, f'bca-{tag}'); cb = _new_client(b_id, f'bcb-{tag}')
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, 'R', 'R', '2026-08-01', 'manual', ?)", (ca, a_id))
    comm_a = c.lastrowid
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, 'R', 'R', '2026-08-01', 'manual', ?)", (cb, b_id))
    comm_b = c.lastrowid
    c.execute("INSERT INTO meeting_briefings (commitment_id, content_md, generated_at) "
              "VALUES (?, 'brief', CURRENT_TIMESTAMP)", (comm_a,))
    c.execute("INSERT INTO meeting_briefings (commitment_id, content_md, generated_at) "
              "VALUES (?, 'brief', CURRENT_TIMESTAMP)", (comm_b,))
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    assert client.get(f'/api/commitments/{comm_a}/briefing').status_code == 200
    assert client.get(f'/api/commitments/{comm_b}/briefing').status_code == 404


# ── Campaigns: cadeia de filhas de 4 níveis (EXISTS aninhado) no Postgres ────

def test_pg_campaign_child_chain(client, monkeypatch):
    """campaign_action_logs → campaign_actions → campaign_accounts → campaigns:
    EXISTS aninhado em 3 níveis traduzido e executado no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()

    def _chain(owner):
        c.execute("INSERT INTO campaigns (title, objective_text, status, owner_id) "
                  "VALUES (?, 'o', 'Ativo', ?)", (f'camp-{owner}-{tag}', owner))
        camp = c.lastrowid
        c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (f'acc-{owner}-{tag}', owner))
        acc = c.lastrowid
        c.execute("INSERT INTO campaign_accounts (campaign_id, account_id, account_name) VALUES (?, ?, 'X')",
                  (camp, acc))
        ca = c.lastrowid
        c.execute("INSERT INTO campaign_actions (campaign_account_id, title) VALUES (?, 'A')", (ca,))
        return camp, c.lastrowid

    camp_a, action_a = _chain(a_id)
    camp_b, action_b = _chain(b_id)
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    titles = {c['title'] for c in client.get('/api/campaigns').get_json()}
    assert f'camp-{a_id}-{tag}' in titles and f'camp-{b_id}-{tag}' not in titles
    # ação própria (via cadeia) editável; a de outro dono → 404
    assert client.patch(f'/api/campaigns/actions/{action_a}', json={'status': 'done'}).status_code == 200
    assert client.patch(f'/api/campaigns/actions/{action_b}', json={'status': 'done'}).status_code == 404


# ── Portfolio: oferta (raiz) + item (filha) + iata (raiz) no Postgres ────────

def test_pg_portfolio_offer_item_and_iata(client, monkeypatch):
    """portfolio_offers (raiz, visible_where) + portfolio_offer_items → offers
    (EXISTS filha) + iata_records (raiz) traduzidos e executados no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()

    def _offer(owner):
        c.execute("INSERT INTO portfolio_offers (title, summary, owner_id) VALUES (?, 's', ?)",
                  (f'off-{owner}-{tag}', owner))
        oid = c.lastrowid
        c.execute("INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order) "
                  "VALUES (?, 'p', 's', 0)", (oid,))
        return oid, c.lastrowid

    off_a, item_a = _offer(a_id)
    off_b, item_b = _offer(b_id)
    c.execute("INSERT INTO iata_records (title, owner_id) VALUES (?, ?)", (f'ata-a-{tag}', a_id))
    c.execute("INSERT INTO iata_records (title, owner_id) VALUES (?, ?)", (f'ata-b-{tag}', b_id))
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    # oferta raiz filtrada
    otitles = {o['title'] for o in client.get('/api/portfolio/offers').get_json()}
    assert f'off-{a_id}-{tag}' in otitles and f'off-{b_id}-{tag}' not in otitles
    # item filha via EXISTS(offer): edição da própria ok, da de outro dono → 404
    assert client.put(f'/api/portfolio/offers/{off_a}/items/{item_a}',
                      json={'pain': 'p2'}).status_code == 200
    assert client.put(f'/api/portfolio/offers/{off_b}/items/{item_b}',
                      json={'pain': 'p2'}).status_code == 404
    # herança filha (portfolio_offer_items → portfolio_offers) direto no helper:
    # exercita o EXISTS(pai) traduzido no Postgres
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.can_write('portfolio_offer_items', item_a) is True
        assert toca.can_read('portfolio_offer_items', item_b) is False
    # iata raiz filtrada
    ititles = {r['title'] for r in client.get('/api/portfolio/iata').get_json()}
    assert f'ata-a-{tag}' in ititles and f'ata-b-{tag}' not in ititles


# ── Wikitoca: entries + documents (raízes, visible_where) no Postgres ────────

def test_pg_wiki_entries_and_documents(client, monkeypatch):
    """wiki_entries e wiki_documents (raízes, privadas-por-dono) filtradas por
    visible_where traduzido no Postgres; guard de escrita (404) e o filtro do
    ramo de busca `q` (OR parentetizada + AND visible) também exercitados."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO wiki_entries (title, content, owner_id) VALUES (?, ?, ?)",
              (f'we-a-{tag}', 'texto termo comum', a_id))
    ea = c.lastrowid
    c.execute("INSERT INTO wiki_entries (title, content, owner_id) VALUES (?, ?, ?)",
              (f'we-b-{tag}', 'texto termo comum', b_id))
    eb = c.lastrowid
    c.execute("INSERT INTO wiki_documents (title, file_name, original_name, file_url, owner_id) "
              "VALUES (?, ?, ?, ?, ?)",
              (f'wd-a-{tag}', f'fa-{tag}.pdf', 'a.pdf', f'/uploads/wikitoca/fa-{tag}.pdf', a_id))
    c.execute("INSERT INTO wiki_documents (title, file_name, original_name, file_url, owner_id) "
              "VALUES (?, ?, ?, ?, ?)",
              (f'wd-b-{tag}', f'fb-{tag}.pdf', 'b.pdf', f'/uploads/wikitoca/fb-{tag}.pdf', b_id))
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    # lista de entries filtrada
    etitles = {e['title'] for e in client.get('/api/wikitoca/entries').get_json()}
    assert f'we-a-{tag}' in etitles and f'we-b-{tag}' not in etitles
    # ramo de busca `q` (OR + AND visible) também filtrado
    qrows = client.get('/api/wikitoca/entries?q=comum').get_json()
    assert {r['title'] for r in qrows} == {f'we-a-{tag}'}
    # guard de escrita: entry de outro dono → 404
    assert client.put(f'/api/wikitoca/entries/{eb}',
                      json={'title': 'X', 'content': 'y'}).status_code == 404
    assert client.put(f'/api/wikitoca/entries/{ea}',
                      json={'title': 'ok', 'content': 'y'}).status_code == 200
    # lista de documents filtrada
    dtitles = {d['title'] for d in client.get('/api/wikitoca/documents').get_json()}
    assert f'wd-a-{tag}' in dtitles and f'wd-b-{tag}' not in dtitles


# ── iToca: histórico de chat por-usuário (owned_where) no Postgres ───────────

def test_pg_itoca_history_owned(client, monkeypatch):
    """itoca_chat_history é por-usuário (owned_where, sem shares/admin): a lista
    de sessões (alias h + subquery correlata + purge DELETE com datetime()) e o
    get por sessão traduzidos e executados no Postgres, escopados ao dono."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO itoca_chat_history (session_id, role, content, owner_id) "
              "VALUES (?, 'user', 'qa', ?)", (f'sa-{tag}', a_id))
    c.execute("INSERT INTO itoca_chat_history (session_id, role, content, owner_id) "
              "VALUES (?, 'user', 'qb', ?)", (f'sb-{tag}', b_id))
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    ids = {r['session_id'] for r in client.get('/api/itoca/history').get_json()}
    assert f'sa-{tag}' in ids and f'sb-{tag}' not in ids
    # get da sessão de outro dono → vazio (escopado por owned_where)
    assert client.get(f'/api/itoca/history/sb-{tag}').get_json() == []


# ── iToca executor: owner nos inserts + lookups escopados no Postgres ────────

def test_pg_itoca_executor_scoped(client, monkeypatch):
    """/execute-action no Postgres: visible_where('clients') no lookup de contato,
    owned_where('kanban_columns') na escolha da coluna e o acesso por dict
    (dict_from_row) traduzidos — o antigo row[0] quebraria com as dict-rows do PG."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    ca = _new_client(a_id, f'Maria-{tag}')
    _new_client(b_id, f'Bruno-{tag}')

    with client.session_transaction() as s:
        s['user_id'] = a_id
    # activity: contato visível → 201 com owner = A
    r = client.post('/api/itoca/execute-action',
                    json={'action_type': 'activity',
                          'fields': {'contact_name': f'Maria-{tag}', 'description': 'ligou'}})
    assert r.status_code == 201, r.get_data(as_text=True)[:300]
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT owner_id FROM activities WHERE id = ?', (r.get_json()['created_id'],))
    assert c.fetchone()['owner_id'] == a_id
    # contato de outro dono → 404 (lookup escopado)
    r404 = client.post('/api/itoca/execute-action',
                       json={'action_type': 'activity',
                             'fields': {'contact_name': f'Bruno-{tag}', 'description': 'x'}})
    assert r404.status_code == 404
    # kanban_card: cai numa coluna do quadro DE A (owned_where + dict access)
    rk = client.post('/api/itoca/execute-action',
                     json={'action_type': 'kanban_card', 'fields': {'title': f'Card-{tag}'}})
    assert rk.status_code == 201, rk.get_data(as_text=True)[:300]
    c.execute('SELECT column_id FROM kanban_cards WHERE id = ?', (rk.get_json()['created_id'],))
    col_id = c.fetchone()['column_id']
    c.execute('SELECT COALESCE(owner_id, (SELECT MIN(id) FROM users)) AS eo FROM kanban_columns WHERE id = ?', (col_id,))
    assert c.fetchone()['eo'] == a_id
    conn.close()


# ── iToca busca RAG (/ask): filtro por visibilidade + painel escopado no PG ──

def test_pg_itoca_search_scoped(client, monkeypatch):
    """/ask no Postgres: o filtro de linhas por can_read(user) e o painel
    analítico com COUNTs escopados por visible_where (+ EXISTS de
    account_presences + date()) traduzidos — o usuário só 'conversa' sobre o que
    vê. _itoca_ask_async é chamado direto (síncrono) com LLM/buscas stubadas."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    ca = _new_client(a_id, f'ca-{tag}')
    cb = _new_client(b_id, f'cb-{tag}')
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, is_target, owner_id) VALUES (?, 0, ?)", (f'acc-a-{tag}', a_id))
    c.execute("INSERT INTO accounts (name, is_target, owner_id) VALUES (?, 0, ?)", (f'acc-b1-{tag}', b_id))
    c.execute("INSERT INTO accounts (name, is_target, owner_id) VALUES (?, 0, ?)", (f'acc-b2-{tag}', b_id))
    conn.commit(); conn.close()

    captured = {}
    def fake_llm(question, context_rows, history_rows=None):
        captured['rows'] = context_rows
        return {'answer': 'ok', 'confidence_percent': 50, 'needs_refinement': False,
                'refinement_hint': '', 'llm_used': False}
    monkeypatch.setattr(toca, '_itoca_call_sai_llm', fake_llm)
    monkeypatch.setattr(toca, '_itoca_search_context', lambda q, limit=18: [
        {'table': 'clients', 'id': ca, 'snippet': 'A', 'search_text': 'a'},
        {'table': 'clients', 'id': cb, 'snippet': 'B', 'search_text': 'b'},
    ])
    monkeypatch.setattr(toca, '_itoca_search_in_cached_snapshot', lambda q, items, limit=18: [])
    a_user = {'id': a_id, 'org_id': org_id, 'role': 'member'}
    toca._itoca_ask_async('tpg', 'resumo geral', '', [], 'now', [], owner_id=a_id, user=a_user)

    keys = {(r['table'], r.get('id')) for r in captured['rows']}
    assert ('clients', ca) in keys and ('clients', cb) not in keys       # filtro por can_read
    panel = next((r for r in captured['rows'] if str(r.get('snippet', '')).startswith('PAINEL_GERAL')), None)
    assert panel is not None and 'total_contas: 1' in panel['snippet']   # só a conta de A


# ── Home: Radar do Dia por-usuário (owned_where + filha job_change) no PG ────

def test_pg_home_radar_scoped(client, monkeypatch):
    """/api/suggestions/today no Postgres: o radar gera só sobre o que o usuário
    vê (visible_where em clients/accounts/commitments, owned_where no kanban e no
    daily_suggestions) e job_change_events herda a visibilidade do contato —
    tudo traduzido pelo wrapper (inclui julianday/strftime emulados)."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    ca = _new_client(a_id, f'Alice-{tag}')
    _new_client(b_id, f'Bob-{tag}')
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO job_change_events (client_id, empresa_nova, status) VALUES (?, 'X', 'pendente')", (ca,))
    jc = c.lastrowid
    conn.commit(); conn.close()

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.get('/api/suggestions/today')
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    titles = ' | '.join(x['title'] for x in r.get_json())
    assert f'Alice-{tag}' in titles and f'Bob-{tag}' not in titles
    # filha job_change_events → clients (EXISTS) traduzida: B não vê a de A
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.can_read('job_change_events', jc) is False
