# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.9c): ACL no drilldown + week-review do Home.

Fecha o Home: dashboard por-usuário (visible_where via _acl_visible_sql) no
drilldown e na "Minha Semana"; o rascunho do Radar e as sugestões pendentes
seguem o dono (owned). Login off → global (desktop).
"""

from datetime import datetime

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org DD')")
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


def _seed_account(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (name, owner_id))
    aid = c.lastrowid; conn.commit(); conn.close()
    return aid


def _seed_client(owner_id, name, company='Co'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, 'C', ?)",
              (name, company, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_activity(owner_id, client_id):
    conn = toca.get_db(); c = conn.cursor()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT INTO activities (client_id, contact_type, information, activity_date, owner_id) "
              "VALUES (?, 'Call', 'x', ?, ?)", (client_id, now, owner_id))
    conn.commit(); conn.close()


def _seed_suggestion(owner_id):
    conn = toca.get_db(); c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("INSERT INTO daily_suggestions (date, suggestion_type, title, target_data, owner_id) "
              "VALUES (?, 'test', 'T', '{}', ?)", (today, owner_id))
    sid = c.lastrowid; conn.commit(); conn.close()
    return sid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── drilldown ───────────────────────────────────────────────────────────────

def test_drilldown_accounts_per_user(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_account(a_id, 'AccA'); _seed_account(b_id, 'AccB')
    _login(client, a_id)
    data = client.get('/api/home/drilldown?type=accounts').get_json()
    names = {i['name'] for i in data['items']}
    assert 'AccA' in names and 'AccB' not in names


def test_drilldown_contacts_per_user(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA'); _seed_client(b_id, 'CliB')
    _login(client, a_id)
    data = client.get('/api/home/drilldown?type=contacts').get_json()
    names = {i['name'] for i in data['items']}
    assert 'CliA' in names and 'CliB' not in names


def test_drilldown_account_detail_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ab = _seed_account(b_id, 'AccB')
    _login(client, a_id)
    r = client.get(f'/api/home/drilldown?type=account&account_id={ab}')
    assert r.status_code == 404       # conta de B não é visível a A


# ── week-review ─────────────────────────────────────────────────────────────

def test_week_review_touches_per_user(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_activity(a_id, ca); _seed_activity(b_id, cb)
    _login(client, a_id)
    data = client.get('/api/week-review').get_json()
    assert data['touches'] == 1       # só a atividade de A


# ── draft ───────────────────────────────────────────────────────────────────

def test_draft_suggestion_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    sb = _seed_suggestion(b_id)
    _login(client, a_id)
    r = client.post(f'/api/suggestions/{sb}/draft')
    assert r.status_code == 404       # sugestão de B → invisível (não gera rascunho)


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_drilldown_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_account(a_id, 'AccA'); _seed_account(b_id, 'AccB')
    data = client.get('/api/home/drilldown?type=accounts').get_json()
    names = {i['name'] for i in data['items']}
    assert 'AccA' in names and 'AccB' in names      # desktop: tudo
