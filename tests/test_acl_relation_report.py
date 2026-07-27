# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.15): ACL no relatório de relacionamento.

Decisão do produto: o relatório é NÍVEL-CONTA — quem enxerga a CONTA recebe o 360°
completo (contatos/atividades/kanban/mapeamento daquela conta). O único gate é a
visibilidade da conta (visible_where('accounts')); as consultas filhas seguem
account-wide. Login off → tudo global (desktop, regra de ouro).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Report')")
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


def _seed_contact(owner_id, name, company):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, 'C', ?)",
              (name, company, owner_id))
    cid = c.lastrowid
    c.execute("INSERT INTO activities (client_id, contact_type, information, activity_date, owner_id) "
              "VALUES (?, 'Email', 'oi', '2026-01-10T09:00', ?)", (cid, owner_id))
    conn.commit(); conn.close()
    return cid


def _no_narrative(monkeypatch):
    monkeypatch.setattr(toca, '_relation_report_generate_narrative',
                        lambda data: {'highlights': [], 'narrative': ''})


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── gate: só quem enxerga a conta gera o relatório ──────────────────────────

def test_report_account_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    acct_b = _seed_account(b_id, 'AcctB')
    _login(client, a_id)
    r = client.get(f'/api/report/relation/preview?account_id={acct_b}&full_period=true')
    assert r.status_code == 404                                    # conta de B → invisível


def test_report_pdf_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    acct_b = _seed_account(b_id, 'AcctB')
    _login(client, a_id)
    r = client.get(f'/api/report/relation?account_id={acct_b}&full_period=true')
    assert r.status_code == 404


# ── conta visível → 360° completo (inclui contato de outro dono) ────────────

def test_report_visible_is_account_level(client, monkeypatch):
    _auth_on(monkeypatch); _no_narrative(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    acct_a = _seed_account(a_id, 'AcmeA')
    _seed_contact(b_id, 'ContatoDeB', 'AcmeA')     # contato da conta, mas de OUTRO dono
    _login(client, a_id)
    r = client.get(f'/api/report/relation/preview?account_id={acct_a}&full_period=true')
    assert r.status_code == 200
    data = r.get_json()
    names = {rc['contact']['name'] for rc in data.get('relationship_cards', [])}
    assert 'ContatoDeB' in names                                   # 360°: conta-wide, não fatiado


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_report_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _no_narrative(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    acct_b = _seed_account(b_id, 'AcctB')
    r = client.get(f'/api/report/relation/preview?account_id={acct_b}&full_period=true')
    assert r.status_code == 200                                    # desktop: qualquer conta
