# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.13): ACL nos dropdowns do autotoca (mala-direta + contas).

As opções de posição/área da mala-direta e a lista de contas do autotoca são
derivadas de clients/accounts — sob login, cada usuário só deve ver valores dos
contatos/contas VISÍVEIS a ele (a mala-direta em si já sai por /api/clientes,
escopado). Login off → tudo global (desktop, regra de ouro).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Auto')")
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


def _seed_client(owner_id, name, position, area):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, area_of_activity, owner_id) "
              "VALUES (?, 'Co', ?, ?, ?)", (name, position, area, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_account(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (name, owner_id))
    aid = c.lastrowid; conn.commit(); conn.close()
    return aid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── mala-direta: posições / áreas ───────────────────────────────────────────

def test_positions_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'CTO', 'Tecnologia')
    _seed_client(b_id, 'CliB', 'CFO', 'Financeiro')
    _login(client, a_id)
    positions = client.get('/api/autotoca/mala-direta/positions').get_json()
    assert 'CTO' in positions and 'CFO' not in positions


def test_areas_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'CTO', 'Tecnologia')
    _seed_client(b_id, 'CliB', 'CFO', 'Financeiro')
    _login(client, a_id)
    areas = client.get('/api/autotoca/mala-direta/areas').get_json()
    assert 'Tecnologia' in areas and 'Financeiro' not in areas


# ── contas ──────────────────────────────────────────────────────────────────

def test_accounts_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_account(a_id, 'AcctA'); _seed_account(b_id, 'AcctB')
    _login(client, a_id)
    names = {a['name'] for a in client.get('/api/autotoca/accounts').get_json()}
    assert 'AcctA' in names and 'AcctB' not in names
    assert 'OUTRO' in names                                        # sentinela sempre presente


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_autotoca_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'CTO', 'Tecnologia')
    _seed_client(b_id, 'CliB', 'CFO', 'Financeiro')
    _seed_account(a_id, 'AcctA'); _seed_account(b_id, 'AcctB')
    positions = set(client.get('/api/autotoca/mala-direta/positions').get_json())
    areas = set(client.get('/api/autotoca/mala-direta/areas').get_json())
    names = {a['name'] for a in client.get('/api/autotoca/accounts').get_json()}
    assert {'CTO', 'CFO'} <= positions                             # desktop: tudo
    assert {'Tecnologia', 'Financeiro'} <= areas
    assert {'AcctA', 'AcctB'} <= names
