# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.8b): ACL no executor de ações do iToca (/api/itoca/execute-action).

O executor cria registros em vários domínios já com ACL (clients, activities,
wiki_entries, commitments) e no Kanban por-usuário. Aqui garantimos que:
- os INSERTs nascem com owner_id = usuário atual;
- os lookups de contato só resolvem contatos VISÍVEIS (não anexa ao de outro);
- o card do Kanban cai na coluna do quadro DO usuário (não a primeira global);
- a duplicidade de contato é por-dono;
- login off cria como antes (regra de ouro).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Exec')")
    org_id = c.lastrowid

    def _mk(email, role):
        c.execute("INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
                  (org_id, email, email, role))
        return c.lastrowid

    admin_id = _mk('founder@ex.com', 'admin')
    a_id = _mk('a@ex.com', 'member')
    b_id = _mk('b@ex.com', 'member')
    conn.commit(); conn.close()
    return org_id, admin_id, a_id, b_id


def _seed_client(owner_id, name, company='Acme'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, 'Cargo', ?)",
              (name, company, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _exec(client, action_type, fields):
    return client.post('/api/itoca/execute-action',
                       json={'action_type': action_type, 'fields': fields})


def _owner_of(table, record_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute(f'SELECT owner_id FROM {table} WHERE id = ?', (record_id,))
    row = c.fetchone(); conn.close()
    return toca.dict_from_row(row)['owner_id'] if row else None


# ── new_contact ─────────────────────────────────────────────────────────────

def test_new_contact_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = _exec(client, 'new_contact', {'name': 'Novo', 'company': 'Acme', 'position': 'CTO'})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    assert _owner_of('clients', r.get_json()['created_id']) == a_id


def test_new_contact_duplicate_is_per_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(b_id, 'João', 'Acme')          # contato de B
    _login(client, a_id)
    # A não é bloqueado pela duplicata de B — cria o seu próprio
    r1 = _exec(client, 'new_contact', {'name': 'João', 'company': 'Acme', 'position': 'Dir'})
    assert r1.status_code == 201
    assert _owner_of('clients', r1.get_json()['created_id']) == a_id
    # agora A tem o seu → segunda tentativa de A é duplicata (409)
    r2 = _exec(client, 'new_contact', {'name': 'João', 'company': 'Acme', 'position': 'Dir'})
    assert r2.status_code == 409


# ── activity ────────────────────────────────────────────────────────────────

def test_activity_owner_and_scoped_lookup(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'Maria Silva', 'AcmeA')
    _login(client, a_id)
    r = _exec(client, 'activity', {'contact_name': 'Maria', 'description': 'ligou hoje'})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    assert _owner_of('activities', r.get_json()['created_id']) == a_id


def test_activity_lookup_ignores_others_contact(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(b_id, 'Bruno Costa', 'AcmeB')      # contato de B
    _login(client, a_id)
    # A não enxerga o contato de B → 404 (não registra atividade no contato alheio)
    r = _exec(client, 'activity', {'contact_name': 'Bruno', 'description': 'x'})
    assert r.status_code == 404


# ── commitment ──────────────────────────────────────────────────────────────

def test_commitment_owner_and_scoped_lookup(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'Carla Dias', 'AcmeA')
    _seed_client(b_id, 'Diego Reis', 'AcmeB')
    _login(client, a_id)
    ok = _exec(client, 'commitment', {'contact_name': 'Carla', 'due_date': '2026-09-01', 'title': 'Reunião'})
    assert ok.status_code == 201, ok.get_data(as_text=True)[:200]
    assert _owner_of('commitments', ok.get_json()['created_id']) == a_id
    # contato de outro dono → 404
    assert _exec(client, 'commitment', {'contact_name': 'Diego', 'due_date': '2026-09-01'}).status_code == 404


# ── wiki_entry ──────────────────────────────────────────────────────────────

def test_wiki_entry_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = _exec(client, 'wiki_entry', {'title': 'Dica', 'content': 'conteúdo'})
    assert r.status_code == 201
    assert _owner_of('wiki_entries', r.get_json()['created_id']) == a_id


# ── kanban_card: cai no quadro DO usuário ───────────────────────────────────

def test_kanban_card_lands_on_own_board(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = _exec(client, 'kanban_card', {'title': 'Card do A'})
    assert r.status_code == 201, r.get_data(as_text=True)[:200]
    card_id = r.get_json()['created_id']
    # a coluna do card pertence a A (quadro por-usuário)
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT column_id FROM kanban_cards WHERE id = ?', (card_id,))
    col_id = toca.dict_from_row(c.fetchone())['column_id']
    conn.close()
    assert _owner_of('kanban_columns', col_id) == a_id
    # B não enxerga o card de A na sua lista (owned_where do Kanban)
    _login(client, b_id)
    titles = {c['title'] for c in client.get('/api/kanban/cards').get_json()}
    assert 'Card do A' not in titles


def test_kanban_card_contact_lookup_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(b_id, 'Contato B', 'AcmeB')
    _login(client, a_id)
    r = _exec(client, 'kanban_card', {'title': 'Card', 'contact_name': 'Contato B'})
    assert r.status_code == 201
    # o contato de B NÃO foi anexado (contact_id fica NULL)
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT contact_id FROM kanban_cards WHERE id = ?', (r.get_json()['created_id'],))
    assert toca.dict_from_row(c.fetchone())['contact_id'] is None
    conn.close()


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_executor_creates(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    r = _exec(client, 'new_contact', {'name': 'Desk', 'company': 'DeskCo', 'position': 'P'})
    assert r.status_code == 201        # desktop: cria normalmente
