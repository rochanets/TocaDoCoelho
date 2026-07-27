# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.9b): ACL nos agregados de leitura do Home (overview + cobertura).

Dashboard por-usuário (decisão do produto): membro vê a SUA fatia, admin vê a
org — via visible_where embutido (_acl_visible_sql) no client_filter/account_
filter e nas demais queries. Login off → totais globais (desktop).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org OV')")
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


def _seed_client(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, 'Co', 'C', ?)",
              (name, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _seed_world():
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_account(a_id, 'AccA1'); _seed_account(a_id, 'AccA2')          # A: 2 contas
    _seed_account(b_id, 'AccB1'); _seed_account(b_id, 'AccB2'); _seed_account(b_id, 'AccB3')  # B: 3
    _seed_client(a_id, 'CliA')                                          # A: 1 contato
    _seed_client(b_id, 'CliB1'); _seed_client(b_id, 'CliB2')            # B: 2
    return org_id, admin_id, a_id, b_id


# ── overview KPIs por-usuário ───────────────────────────────────────────────

def test_overview_kpis_member_sees_own_slice(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_world()
    _login(client, a_id)
    kpis = client.get('/api/home/overview').get_json()['kpis']
    assert kpis['total_accounts'] == 2 and kpis['total_contacts'] == 1


def test_overview_kpis_admin_sees_org(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_world()
    _login(client, admin_id)
    kpis = client.get('/api/home/overview').get_json()['kpis']
    assert kpis['total_accounts'] == 5 and kpis['total_contacts'] == 3


# ── cobertura-detail por-usuário ────────────────────────────────────────────

def test_cobertura_detail_member_sees_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_world()
    _login(client, a_id)
    data = client.get('/api/home/cobertura-detail').get_json()
    names = {r['name'] for r in (data['covered'] + data['uncovered'])}
    assert data['total'] == 2
    assert names == {'AccA1', 'AccA2'}       # nenhuma conta de B


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_overview_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_world()
    kpis = client.get('/api/home/overview').get_json()['kpis']
    assert kpis['total_accounts'] == 5 and kpis['total_contacts'] == 3     # desktop: tudo
