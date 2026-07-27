# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.10): ACL no Mapeamento de Ambiente (environment).

Decisão do produto: os CARDS são um catálogo COMPARTILHADO do time (sem filtro
por dono); as RESPOSTAS seguem a visibilidade do CONTATO a que pertencem
(environment_responses.client_id → filha de clients). Login off → tudo global.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Env')")
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


def _seed_card(title='Pergunta'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO environment_cards (title, description) VALUES (?, 'd')", (title,))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_client(owner_id, name, company='Co'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, 'C', ?)",
              (name, company, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_response(card_id, client_id, text='resp'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO environment_responses (card_id, client_id, response) VALUES (?, ?, ?)",
              (card_id, client_id, text))
    conn.commit(); conn.close()


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── cards: catálogo compartilhado ───────────────────────────────────────────

def test_cards_are_shared(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_card('Q compartilhada')
    _login(client, a_id)
    titles_a = {c['title'] for c in client.get('/api/environment/cards').get_json()}
    _login(client, b_id)
    titles_b = {c['title'] for c in client.get('/api/environment/cards').get_json()}
    assert 'Q compartilhada' in titles_a and 'Q compartilhada' in titles_b


# ── respostas: seguem a visibilidade do contato ─────────────────────────────

def test_responses_all_scoped_by_client(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    card = _seed_card()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_response(card, ca, 'da'); _seed_response(card, cb, 'db')
    _login(client, a_id)
    rows = client.get('/api/environment/responses').get_json()
    names = {r.get('client_name') for r in rows}
    assert 'CliA' in names and 'CliB' not in names


def test_responses_by_client_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    card = _seed_card()
    cb = _seed_client(b_id, 'CliB')
    _seed_response(card, cb, 'db')
    _login(client, a_id)
    rows = client.get(f'/api/environment/responses?client_id={cb}').get_json()
    assert rows == []                          # contato de B → nenhuma resposta


def test_response_post_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    card = _seed_card()
    cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/environment/responses',
                    json={'card_id': card, 'client_id': cb, 'response': 'x'})
    assert r.status_code == 404                 # não grava resposta em contato de B


def test_all_responses_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    card = _seed_card()
    _seed_client(a_id, 'CliA', 'AcmeA'); _seed_client(b_id, 'CliB', 'AcmeB')
    _login(client, a_id)
    data = client.get(f'/api/environment/card/{card}/all-responses').get_json()
    companies = {r['company'] for r in data['responses']}
    assert 'AcmeA' in companies and 'AcmeB' not in companies


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_responses_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    card = _seed_card()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_response(card, ca); _seed_response(card, cb)
    names = {r.get('client_name') for r in client.get('/api/environment/responses').get_json()}
    assert 'CliA' in names and 'CliB' in names      # desktop: tudo
