# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.5): ACL em campaigns — raiz + cadeia de filhas de 4 níveis.

campaigns é entidade-raiz (owner_id). As filhas herdam a visibilidade da
campanha via a cadeia campaign_action_logs → campaign_actions →
campaign_accounts → campaigns. Modelo privado-por-dono (visible_where + shares +
admin). Login off = no-op.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Camp')")
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


def _new_campaign(owner_id, title='Camp'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO campaigns (title, objective_text, status, owner_id) VALUES (?, 'obj', 'Ativo', ?)",
              (title, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _new_account(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (name, owner_id))
    aid = c.lastrowid
    conn.commit(); conn.close()
    return aid


def _new_action_chain(campaign_id, account_id):
    """campaign_account → campaign_action → campaign_action_log. Retorna (ca, action, log)."""
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO campaign_accounts (campaign_id, account_id, account_name) VALUES (?, ?, 'X')",
              (campaign_id, account_id))
    ca = c.lastrowid
    c.execute("INSERT INTO campaign_actions (campaign_account_id, title) VALUES (?, 'Ação')", (ca,))
    action = c.lastrowid
    c.execute("INSERT INTO campaign_action_logs (action_id, log_text, log_type) VALUES (?, 'log', 'user')", (action,))
    log = c.lastrowid
    conn.commit(); conn.close()
    return ca, action, log


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── lista / detalhe ─────────────────────────────────────────────────────────

def test_campaigns_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_campaign(a_id, 'CampA'); _new_campaign(b_id, 'CampB')
    _login(client, a_id)
    titles = {c['title'] for c in client.get('/api/campaigns').get_json()}
    assert 'CampA' in titles and 'CampB' not in titles


def test_campaign_detail_of_others_is_404(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_campaign(b_id, 'CampB')
    _login(client, a_id)
    assert client.get(f'/api/campaigns/{cb}').status_code == 404


def test_admin_sees_all_campaigns(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_campaign(a_id, 'CampA'); _new_campaign(b_id, 'CampB')
    _login(client, admin_id)
    titles = {c['title'] for c in client.get('/api/campaigns').get_json()}
    assert {'CampA', 'CampB'} <= titles


# ── escrita na raiz ─────────────────────────────────────────────────────────

def test_cannot_edit_or_delete_others_campaign(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_campaign(b_id, 'CampB')
    _login(client, a_id)
    assert client.put(f'/api/campaigns/{cb}', json={'title': 'X'}).status_code == 404
    assert client.delete(f'/api/campaigns/{cb}').status_code == 404
    assert client.post(f'/api/campaigns/{cb}/regenerate').status_code == 404


# ── cadeia de filhas (herança 4 níveis) ─────────────────────────────────────

def test_child_chain_inheritance(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    camp_a = _new_campaign(a_id, 'CampA')
    acc_a = _new_account(a_id, 'AccA')
    ca, action, log = _new_action_chain(camp_a, acc_a)
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.can_write('campaign_action_logs', log) is True   # log → action → ca → campaign(A)
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.can_read('campaign_action_logs', log) is False
        assert toca.can_write('campaign_actions', action) is False


def test_cannot_touch_others_action_or_log(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    camp_b = _new_campaign(b_id, 'CampB')
    acc_b = _new_account(b_id, 'AccB')
    ca, action, log = _new_action_chain(camp_b, acc_b)
    _login(client, a_id)
    assert client.patch(f'/api/campaigns/actions/{action}', json={'status': 'done'}).status_code == 404
    assert client.post(f'/api/campaigns/actions/{action}/logs', json={'log_text': 'x'}).status_code == 404
    assert client.patch(f'/api/campaigns/logs/{log}', json={'log_text': 'x'}).status_code == 404
    assert client.delete(f'/api/campaigns/logs/{log}').status_code == 404


def test_owner_can_touch_own_action(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    camp_a = _new_campaign(a_id, 'CampA')
    acc_a = _new_account(a_id, 'AccA')
    ca, action, log = _new_action_chain(camp_a, acc_a)
    _login(client, a_id)
    assert client.patch(f'/api/campaigns/actions/{action}', json={'status': 'done'}).status_code == 200


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_sees_all_campaigns(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_campaign(a_id, 'CampA'); _new_campaign(b_id, 'CampB')
    titles = {c['title'] for c in client.get('/api/campaigns').get_json()}
    assert {'CampA', 'CampB'} <= titles
