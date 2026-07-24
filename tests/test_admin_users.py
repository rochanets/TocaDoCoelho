# -*- coding: utf-8 -*-
"""Fase 3 (PR 3.3): endpoint admin de provisionamento da allowlist.

POST/GET /api/admin/users, guardado por @admin_required. Cobre autorização
(desligado→fundador admin; ligado→sessão de admin, member 403, anônimo 401),
validação/dedup e a integração provisionar→login (o email liberado passa a
entrar no fluxo SSO da PR 3.2).
"""
import app as toca


def _seed_user(email, role='admin', entra=None):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO organizations (name) SELECT 'Org' "
              "WHERE NOT EXISTS (SELECT 1 FROM organizations)")
    c.execute(
        "INSERT INTO users (org_id, entra_object_id, email, full_name, role) "
        "VALUES ((SELECT MIN(id) FROM organizations), ?, ?, '', ?)",
        (entra, email, role),
    )
    conn.commit()
    c.execute('SELECT id FROM users WHERE email = ? ORDER BY id DESC LIMIT 1', (email,))
    uid = c.fetchone()['id']
    conn.close()
    return uid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


# ── Login desligado (desktop): o fundador (admin) administra ─────────────────

def test_provision_user_auth_off(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _seed_user('admin@corp.com', role='admin')
    r = client.post('/api/admin/users',
                    json={'email': 'Novo@Corp.com', 'full_name': 'Novo', 'role': 'member'})
    assert r.status_code == 201, r.get_data(as_text=True)
    body = r.get_json()
    assert body['email'] == 'novo@corp.com' and body['role'] == 'member' and body['linked'] is False
    r2 = client.get('/api/admin/users')
    emails = [u['email'] for u in r2.get_json()['users']]
    assert 'novo@corp.com' in emails


def test_provision_duplicate_conflict(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _seed_user('admin@corp.com')
    _seed_user('dup@corp.com', role='member')
    # case-insensitive
    r = client.post('/api/admin/users', json={'email': 'DUP@corp.com'})
    assert r.status_code == 409


def test_provision_invalid_email(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _seed_user('admin@corp.com')
    r = client.post('/api/admin/users', json={'email': 'nao-eh-email'})
    assert r.status_code == 400


def test_provision_invalid_role(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _seed_user('admin@corp.com')
    r = client.post('/api/admin/users', json={'email': 'x@corp.com', 'role': 'superuser'})
    assert r.status_code == 400


# ── Login ligado: autorização por sessão/role ───────────────────────────────

def test_admin_requires_session(client, monkeypatch):
    _auth_on(monkeypatch)
    r = client.post('/api/admin/users', json={'email': 'x@corp.com'})
    assert r.status_code == 401  # barrado pelo gate (sem sessão)


def test_admin_forbidden_for_member(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user('member@corp.com', role='member')
    with client.session_transaction() as s:
        s['user_id'] = uid
    r = client.post('/api/admin/users', json={'email': 'x@corp.com'})
    assert r.status_code == 403


def test_admin_allowed_for_admin(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user('admin@corp.com', role='admin')
    with client.session_transaction() as s:
        s['user_id'] = uid
    r = client.post('/api/admin/users', json={'email': 'novo@corp.com', 'role': 'member'})
    assert r.status_code == 201


# ── Integração: provisionar → o email liberado passa a logar ────────────────

def test_provisioned_user_can_login(client, monkeypatch):
    _auth_on(monkeypatch)
    admin_id = _seed_user('admin@corp.com', role='admin')
    with client.session_transaction() as s:
        s['user_id'] = admin_id
    r = client.post('/api/admin/users', json={'email': 'colega@corp.com'})
    assert r.status_code == 201
    new_id = r.get_json()['id']

    # Antes: 'colega@corp.com' não existia → login seria negado. Agora entra.
    monkeypatch.setattr(toca, 'outlook_graph_exchange_login_code',
                        lambda code, verifier, settings: {'access_token': 'AT'})
    monkeypatch.setattr(toca, 'outlook_graph_fetch_user_claims',
                        lambda access_token: {'oid': 'OID-COLEGA', 'email': 'colega@corp.com', 'name': 'Colega'})
    with client.session_transaction() as s:
        s.pop('user_id', None)  # sai da sessão do admin
        s['oauth_login'] = {'state': 'S', 'verifier': 'V', 'nonce': 'N', 'next': '/'}
    r = client.get('/api/auth/callback?code=CODE&state=S')
    assert r.status_code == 302  # login concluído (não mais negado)
    with client.session_transaction() as s:
        assert s.get('user_id') == new_id
