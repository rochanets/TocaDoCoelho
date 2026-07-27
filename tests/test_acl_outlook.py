# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.14a): ACL no outlook em contexto de request.

- /outlook/diagnose conta só os contatos VISÍVEIS (o match é contra os do usuário).
- _outlook_match_emails (addon-preview / ingest-from-addon) casa e-mails e monta a
  lista de seleção só com contatos visíveis.
- /outlook/apply-suggestions só aplica em contato que o usuário pode ESCREVER e em
  card que é DELE (kanban pessoal).
Login off → tudo global (desktop, regra de ouro). O import assíncrono
(_outlook_confirm_async) fica para a 4.14b.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Outlook')")
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


def _seed_client(owner_id, name, email=None):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, email, owner_id) "
              "VALUES (?, 'Co', 'C', ?, ?)", (name, email, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_column_and_card(owner_id, title='Col'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO kanban_columns (title, display_order, owner_id) VALUES (?, 1, ?)", (title, owner_id))
    col = c.lastrowid
    c.execute("INSERT INTO kanban_cards (title, description, column_id) VALUES ('c', '', ?)", (col,))
    card = c.lastrowid
    conn.commit(); conn.close()
    return col, card


def _client_stage(client_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT relationship_stage FROM clients WHERE id = ?", (client_id,))
    row = toca.dict_from_row(c.fetchone()); conn.close()
    return row['relationship_stage'] if row else None


def _card_column(card_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT column_id FROM kanban_cards WHERE id = ?", (card_id,))
    row = toca.dict_from_row(c.fetchone()); conn.close()
    return row['column_id'] if row else None


def _email(sender_email, date='2026-01-15T10:00'):
    return {'subject': 'Oi', 'date': date, 'direction': 'received',
            'sender': {'email': sender_email, 'name': 'Contato'}, 'recipients': [], 'body_preview': 'b'}


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── diagnose: contagem escopada ─────────────────────────────────────────────

def test_diagnose_counts_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA1', 'a1@acme.com'); _seed_client(a_id, 'CliA2', None)
    _seed_client(b_id, 'CliB1', 'b1@beta.com'); _seed_client(b_id, 'CliB2', 'b2@beta.com')
    _login(client, a_id)
    data = client.get('/api/outlook/diagnose').get_json()
    assert data['total_clients'] == 2 and data['clients_with_email'] == 1        # só os de A


# ── match: casa/seleciona só contra visíveis ────────────────────────────────

def test_match_emails_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    _login(client, a_id)
    r = client.post('/api/outlook/addon-preview',
                    json={'emails': [_email('a@acme.com'), _email('b@beta.com')]})
    body = r.get_json()
    assert body['matched'] == 1 and body['unmatched'] == 1        # b@beta (de B) não casa


def test_ingest_all_clients_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    _login(client, a_id)
    client.post('/api/outlook/ingest-from-addon', json={'emails': [_email('x@nada.com')]})
    pending = client.get('/api/outlook/addon-pending').get_json()
    names = {cl['name'] for cl in pending.get('all_clients', [])}
    assert 'CliA' in names and 'CliB' not in names               # seleção manual só com visíveis


# ── apply-suggestions: guardas de escrita ───────────────────────────────────

def test_apply_status_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/outlook/apply-suggestions', json={'status_updates': [
        {'client_id': ca, 'stage': 'Avançado'},      # dele → aplica
        {'client_id': cb, 'stage': 'Hackeado'},       # de B → pulado
    ]})
    assert r.get_json()['applied'] == 1
    assert _client_stage(ca) == 'Avançado'
    assert _client_stage(cb) != 'Hackeado'


def test_apply_kanban_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    a_col, a_card = _seed_column_and_card(a_id, 'ColA')
    a_col2, _ = _seed_column_and_card(a_id, 'ColA2')
    b_col, b_card = _seed_column_and_card(b_id, 'ColB')
    _login(client, a_id)
    r = client.post('/api/outlook/apply-suggestions', json={'kanban_moves': [
        {'card_id': a_card, 'column_id': a_col2},      # card dele → move
        {'card_id': b_card, 'column_id': a_col2},      # card de B → pulado
    ]})
    assert r.get_json()['applied'] == 1
    assert _card_column(a_card) == a_col2
    assert _card_column(b_card) == b_col                # inalterado


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_outlook_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    data = client.get('/api/outlook/diagnose').get_json()
    assert data['total_clients'] == 2 and data['clients_with_email'] == 2        # desktop: todos
    r = client.post('/api/outlook/addon-preview',
                    json={'emails': [_email('a@acme.com'), _email('b@beta.com')]})
    assert r.get_json()['matched'] == 2                          # casa contra todos
