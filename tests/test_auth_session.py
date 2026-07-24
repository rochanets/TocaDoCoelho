# -*- coding: utf-8 -*-
"""Fase 3 (PR 3.1): sessão, gate @login_required e identidade da requisição.

Garante a REGRA DE OURO: com TOCA_AUTH_ENABLED desligado (padrão), nada muda —
o gate é no-op e current_user_id() devolve o fundador. Ligado, as rotas de API
exigem sessão válida (401 JSON), enquanto assets estáticos, /healthz e o fluxo
de auth (/api/auth/*) seguem públicos.
"""

import app as toca


def _seed_user(email='founder@example.com', role='admin'):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO organizations (name) SELECT 'Org Teste' "
              "WHERE NOT EXISTS (SELECT 1 FROM organizations)")
    c.execute(
        "INSERT INTO users (org_id, email, full_name, role) "
        "VALUES ((SELECT MIN(id) FROM organizations), ?, 'Fundador Teste', ?)",
        (email, role),
    )
    conn.commit()
    c.execute('SELECT id FROM users WHERE email = ? ORDER BY id DESC LIMIT 1', (email,))
    uid = c.fetchone()['id']
    conn.close()
    return uid


def _min_user_id():
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT MIN(id) AS m FROM users')
    m = c.fetchone()['m']
    conn.close()
    return m


# ── Flag e identidade da requisição ─────────────────────────────────────────

def test_auth_disabled_by_default(monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    assert toca._auth_enabled() is False


def test_auth_enabled_via_env(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    assert toca._auth_enabled() is True


def test_current_user_id_auth_off_is_founder(db_path, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _seed_user()
    founder = _min_user_id()
    with toca.app.test_request_context('/'):
        assert toca.current_user_id() == founder


def test_current_user_id_no_users_falls_back_to_1(db_path, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    # DB migrado, porém sem linha em users (sem user_profile semeado): o
    # fallback defensivo é 1, preservando o comportamento histórico do desktop.
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('DELETE FROM users')
    conn.commit()
    conn.close()
    with toca.app.test_request_context('/'):
        assert toca.current_user_id() == 1


def test_current_user_none_outside_request_context(monkeypatch):
    # Threads de background não têm contexto de request: current_user() é None
    # (chamadores caem no fundador via current_user_id()).
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    assert toca.current_user() is None


# ── Gate de autenticação (before_request) ───────────────────────────────────

def test_gate_off_allows_api(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    r = client.get('/api/outlook/graph-config')
    assert r.status_code == 200


def test_gate_off_graph_status_ok(client, monkeypatch):
    # Exercita o caminho com current_user_id() já trocado (era user_id=1 fixo).
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    r = client.get('/api/outlook/graph-status')
    assert r.status_code == 200
    assert r.get_json().get('connected') is False


def test_gate_on_blocks_api_without_session(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    r = client.get('/api/outlook/graph-config')
    assert r.status_code == 401
    assert r.get_json().get('error_type') == 'auth_required'


def test_gate_on_allows_healthz(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    assert client.get('/healthz').status_code == 200


def test_gate_on_allows_spa_shell(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    # Página (não-API) carrega mesmo sem sessão — o SPA decide via /api/auth/me.
    r = client.get('/')
    assert r.status_code == 200


def test_gate_on_auth_prefix_is_public(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    # /api/auth/* ainda não existe (chega na PR 3.2), mas o gate deve deixar
    # passar: 404 do Flask, e não 401 do gate.
    r = client.get('/api/auth/whoami')
    assert r.status_code == 404


def test_gate_on_blocks_uploads(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    # Arquivos de negócio (/uploads/*) não são assets públicos da SPA: sem
    # sessão o gate responde 401 ANTES da rota (não vaza como 404 do arquivo).
    r = client.get('/uploads/accounts/qualquer.png')
    assert r.status_code == 401
    assert r.get_json().get('error_type') == 'auth_required'


def test_gate_on_with_session_allows_api(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    # Test client roda em http; o cookie Secure não voltaria — desliga p/ o teste.
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)
    uid = _seed_user()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/outlook/graph-config')
    assert r.status_code == 200


def test_gate_on_stale_session_blocked(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)
    # Sessão aponta para um usuário inexistente → tratado como não autenticado.
    with client.session_transaction() as sess:
        sess['user_id'] = 999999
    r = client.get('/api/outlook/graph-config')
    assert r.status_code == 401
