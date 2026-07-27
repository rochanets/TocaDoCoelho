# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.11): ACL nos templates de mensagem (message_templates).

Decisão do produto: privados por-dono, com opção de compartilhar (shares) —
mesmo modelo de wiki/portfolio (visible_where). Migração 18 adicionou owner_id.
Login off → tudo global (desktop).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Tpl')")
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


def _seed_template(owner_id, title='T'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO message_templates (title, description, owner_id) VALUES (?, 'd', ?)",
              (title, owner_id))
    tid = c.lastrowid; conn.commit(); conn.close()
    return tid


def _share(record_type, record_id, user_id, permission='read'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO shares (record_type, record_id, shared_with_user_id, permission) "
              "VALUES (?, ?, ?, ?)", (record_type, record_id, user_id, permission))
    conn.commit(); conn.close()


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def test_migration_added_owner_id(client):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("PRAGMA table_info(message_templates)")
    cols = {row[1] for row in c.fetchall()}
    conn.close()
    assert 'owner_id' in cols


def test_templates_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_template(a_id, 'TplA'); _seed_template(b_id, 'TplB')
    _login(client, a_id)
    titles = {t['title'] for t in client.get('/api/config/templates').get_json()}
    assert 'TplA' in titles and 'TplB' not in titles


def test_template_write_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tb = _seed_template(b_id, 'TplB')
    _login(client, a_id)
    assert client.put(f'/api/config/templates/{tb}',
                      json={'title': 'X', 'description': 'y'}).status_code == 404
    assert client.delete(f'/api/config/templates/{tb}').status_code == 404


def test_template_create_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = client.post('/api/config/templates', json={'title': 'Nova', 'description': 'd'})
    assert r.status_code == 201
    assert r.get_json()['owner_id'] == a_id


def test_template_read_share_grants_visibility(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tb = _seed_template(b_id, 'TplShared')
    _share('message_templates', tb, a_id, 'read')
    _login(client, a_id)
    titles = {t['title'] for t in client.get('/api/config/templates').get_json()}
    assert 'TplShared' in titles                                                 # via share
    assert client.put(f'/api/config/templates/{tb}',
                      json={'title': 'X', 'description': 'y'}).status_code == 403  # só leitura


def test_auth_off_templates_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_template(a_id, 'TplA'); _seed_template(b_id, 'TplB')
    titles = {t['title'] for t in client.get('/api/config/templates').get_json()}
    assert {'TplA', 'TplB'} <= titles
