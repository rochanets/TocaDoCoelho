# -*- coding: utf-8 -*-
"""Fase 3 (PR 3.2): fluxo SSO Microsoft — login/callback/logout/me + allowlist.

As chamadas de rede à Microsoft (troca do code e Graph /me) são mockadas nos
pontos outlook_graph_exchange_login_code / outlook_graph_fetch_user_claims
(resolvidos no namespace de app.py). O foco é a lógica das rotas: state/PKCE,
casamento por email, preenchimento de entra_object_id e a política de allowlist.
"""
import urllib.parse

import app as toca


def _seed_user(email='founder@corp.com', role='admin', entra=None):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO organizations (name) SELECT 'Org Teste' "
              "WHERE NOT EXISTS (SELECT 1 FROM organizations)")
    c.execute(
        "INSERT INTO users (org_id, entra_object_id, email, full_name, role) "
        "VALUES ((SELECT MIN(id) FROM organizations), ?, ?, ?, ?)",
        (entra, email, '', role),
    )
    conn.commit()
    c.execute('SELECT id FROM users WHERE email = ? ORDER BY id DESC LIMIT 1', (email,))
    uid = c.fetchone()['id']
    conn.close()
    return uid


def _users_count():
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) AS n FROM users')
    n = c.fetchone()['n']
    conn.close()
    return n


def _entra_of(uid):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT entra_object_id FROM users WHERE id = ?', (uid,))
    v = c.fetchone()['entra_object_id']
    conn.close()
    return v


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _mock_ms(monkeypatch, email, oid, name='Fulano'):
    monkeypatch.setattr(toca, 'outlook_graph_exchange_login_code',
                        lambda code, verifier, settings: {'access_token': 'AT'})
    monkeypatch.setattr(toca, 'outlook_graph_fetch_user_claims',
                        lambda access_token: {'oid': oid, 'email': email, 'name': name})


# ── /api/auth/login ─────────────────────────────────────────────────────────

def test_login_redirects_to_microsoft(client, monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setenv('OUTLOOK_GRAPH_CLIENT_ID', '11111111-1111-1111-1111-111111111111')
    monkeypatch.setenv('OUTLOOK_GRAPH_TENANT_ID', 'common')
    monkeypatch.setenv('OUTLOOK_GRAPH_LOGIN_REDIRECT_URI', 'http://localhost/api/auth/callback')
    r = client.get('/api/auth/login', headers={'Accept': 'text/html'})
    assert r.status_code == 302
    loc = r.headers['Location']
    assert loc.startswith('https://login.microsoftonline.com/common/oauth2/v2.0/authorize')
    assert 'code_challenge=' in loc and 'state=' in loc
    # escopo de identidade presente (url-encoded)
    assert 'scope=openid+profile+email+User.Read' in loc
    with client.session_transaction() as sess:
        assert sess.get('oauth_login', {}).get('state'), 'state não guardado na sessão'


def test_login_disabled_redirects_home(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    r = client.get('/api/auth/login')
    assert r.status_code == 302
    assert r.headers['Location'].endswith('/')


def test_login_unconfigured_shows_error_not_redirect(client, monkeypatch):
    # Sem client_id configurado, login não pode iniciar. Deve mostrar página de
    # erro (não redirect para '/', que reentraria no gate → loop).
    _auth_on(monkeypatch)
    monkeypatch.delenv('OUTLOOK_GRAPH_CLIENT_ID', raising=False)
    monkeypatch.setattr(toca, '_GRAPH_DEFAULT_CLIENT_ID', '', raising=False)
    r = client.get('/api/auth/login', headers={'Accept': 'text/html'})
    assert r.status_code == 503
    assert 'text/html' in r.headers.get('Content-Type', '')


# ── /api/auth/callback ──────────────────────────────────────────────────────

def test_callback_happy_path_links_founder(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user(email='founder@corp.com', entra=None)
    _mock_ms(monkeypatch, email='founder@corp.com', oid='OID-FOUNDER', name='Founder')
    with client.session_transaction() as sess:
        sess['oauth_login'] = {'state': 'S1', 'verifier': 'V', 'nonce': 'N', 'next': '/'}
    r = client.get('/api/auth/callback?code=CODE&state=S1')
    assert r.status_code == 302 and r.headers['Location'].endswith('/')
    with client.session_transaction() as sess:
        assert sess.get('user_id') == uid
    # entra_object_id preenchido no 1º login (casou por email, estava NULL)
    assert _entra_of(uid) == 'OID-FOUNDER'


def test_callback_matches_by_entra_object_id(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user(email='old@corp.com', entra='OID-STABLE')
    # Mesmo que o email tenha mudado no Entra, casa pelo oid estável.
    _mock_ms(monkeypatch, email='new@corp.com', oid='OID-STABLE')
    with client.session_transaction() as sess:
        sess['oauth_login'] = {'state': 'S', 'verifier': 'V', 'nonce': 'N', 'next': '/'}
    r = client.get('/api/auth/callback?code=CODE&state=S')
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('user_id') == uid


def test_callback_unknown_email_denied(client, monkeypatch):
    _auth_on(monkeypatch)
    _seed_user(email='founder@corp.com')
    before = _users_count()
    _mock_ms(monkeypatch, email='stranger@other.com', oid='OID-X')
    with client.session_transaction() as sess:
        sess['oauth_login'] = {'state': 'S', 'verifier': 'V', 'nonce': 'N', 'next': '/'}
    r = client.get('/api/auth/callback?code=CODE&state=S')
    assert r.status_code == 403
    assert 'Acesso negado' in r.get_data(as_text=True)
    # allowlist: NÃO cria usuário e NÃO abre sessão
    assert _users_count() == before
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_callback_state_mismatch_rejected(client, monkeypatch):
    _auth_on(monkeypatch)
    _mock_ms(monkeypatch, email='founder@corp.com', oid='OID')
    with client.session_transaction() as sess:
        sess['oauth_login'] = {'state': 'RIGHT', 'verifier': 'V', 'nonce': 'N', 'next': '/'}
    r = client.get('/api/auth/callback?code=CODE&state=WRONG')
    assert r.status_code == 400
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_callback_without_pending_rejected(client, monkeypatch):
    _auth_on(monkeypatch)
    r = client.get('/api/auth/callback?code=CODE&state=S')
    assert r.status_code == 400


def test_callback_provider_error_shown(client, monkeypatch):
    _auth_on(monkeypatch)
    r = client.get('/api/auth/callback?error=access_denied&error_description=User+cancelou')
    assert r.status_code == 400
    assert 'User cancelou' in r.get_data(as_text=True)


# ── /api/auth/me e logout ───────────────────────────────────────────────────

def test_me_unauthenticated(client, monkeypatch):
    _auth_on(monkeypatch)
    r = client.get('/api/auth/me')
    assert r.status_code == 200
    body = r.get_json()
    assert body['authenticated'] is False and body['auth_enabled'] is True


def test_me_authenticated(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user(email='founder@corp.com')
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/auth/me')
    body = r.get_json()
    assert body['authenticated'] is True
    assert body['user']['id'] == uid and body['user']['email'] == 'founder@corp.com'


def test_logout_clears_session(client, monkeypatch):
    _auth_on(monkeypatch)
    uid = _seed_user(email='founder@corp.com')
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.post('/api/auth/logout')
    assert r.status_code == 200 and r.get_json().get('ok') is True
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


# ── Gate: navegação de página → handshake SSO ───────────────────────────────

def test_gate_html_navigation_redirects_to_login(client, monkeypatch):
    _auth_on(monkeypatch)
    r = client.get('/agenda', headers={'Accept': 'text/html'})
    assert r.status_code == 302
    loc = r.headers['Location']
    assert loc.startswith('/api/auth/login?next=')
    # o destino original é preservado (para retornar após o login)
    nxt = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query).get('next', [''])[0]
    assert nxt == '/agenda'


def test_gate_static_asset_allowed_unauthenticated(client, monkeypatch):
    _auth_on(monkeypatch)
    # Sub-recurso estático (Accept */*) passa pelo gate; 404 (arquivo ausente)
    # prova que não foi barrado (não é 401 nem redirect).
    r = client.get('/nao-existe-xyz.js', headers={'Accept': '*/*'})
    assert r.status_code == 404
