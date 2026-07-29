import json
from pathlib import Path

import yaml

import app as toca
from integrations import outlook_graph
from scripts import check_no_secrets


def _seed_user(email='f85@corp.invalid'):
    conn = toca.get_db()
    conn.execute(
        "INSERT INTO organizations (name) SELECT 'F8.5' "
        "WHERE NOT EXISTS (SELECT 1 FROM organizations)"
    )
    conn.execute(
        "INSERT INTO users (org_id, email, full_name, role) "
        "VALUES ((SELECT MIN(id) FROM organizations), ?, 'F8.5', 'admin')",
        (email,),
    )
    conn.commit()
    row = conn.execute(
        'SELECT id FROM users WHERE email = ? ORDER BY id DESC LIMIT 1',
        (email,),
    ).fetchone()
    user_id = row['id']
    conn.close()
    return user_id


def test_production_image_has_immutable_build_provenance():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
    compose = yaml.safe_load(
        (root / 'docker-compose.production.yml').read_text(encoding='utf-8')
    )

    assert 'ARG TOCA_BUILD_SHA=unknown' in dockerfile
    assert 'org.opencontainers.image.revision="${TOCA_BUILD_SHA}"' in dockerfile
    assert 'TOCA_APP_VERSION=${TOCA_BUILD_VERSION}' in dockerfile
    assert compose['services']['web']['build']['args'] == {
        'TOCA_BUILD_SHA': '${TOCA_BUILD_SHA:-unknown}',
        'TOCA_BUILD_VERSION': '${TOCA_BUILD_VERSION:-dev}',
    }
    assert compose['services']['nginx']['ports'] == [
        '${TOCA_HTTP_PORT:-80}:80',
        '${TOCA_HTTPS_PORT:-443}:443',
    ]


def test_rehearsal_covers_stack_auth_waha_backup_and_image_rollback():
    root = Path(__file__).resolve().parents[1]
    script = (
        root / 'deploy/rehearsal/run-production-rehearsal.sh'
    ).read_text(encoding='utf-8')
    workflow = (
        root / '.github/workflows/production-rehearsal.yml'
    ).read_text(encoding='utf-8')

    for expected in (
        'openssl req -x509',
        'compose up -d --no-build',
        'Booting worker with pid',
        '/api/auth/login',
        '/api/auth/logout',
        'code_challenge=',
        '.HostConfig.PortBindings',
        'X-Webhook-Hmac',
        '/backups/.last-success',
        'export TOCA_IMAGE_TAG="$PREVIOUS_TAG"',
        "docker inspect --format '{{.Image}}'",
        'compose down --volumes --remove-orphans',
    ):
        assert expected in script

    parsed = yaml.safe_load(workflow)
    assert 'production-rehearsal' in parsed['jobs']
    assert 'scripts/check_no_secrets.py' in workflow
    assert 'git worktree add --detach' in workflow


def test_secret_scanner_detects_tokens_and_allows_disposable_values():
    github = check_no_secrets.TOKEN_PATTERNS['github_token']
    assignment = check_no_secrets.LITERAL_ASSIGNMENT

    assert github.search('ghp_' + ('A' * 36))
    assert assignment.search('password="a-real-looking-password-value"')
    disposable = assignment.search(
        'password="f85-disposable-postgres-password"'
    )
    assert disposable
    assert any(
        marker in disposable.group(2).lower()
        for marker in check_no_secrets.ALLOWED_LITERAL_MARKERS
    )
    assert check_no_secrets.ENV_LITERAL_ASSIGNMENT.search(
        'SECRET_KEY=f85-disposable-session-secret-with-more-than-32-characters'
    )


def test_secure_permanent_session_is_refreshed_and_logout_clears_it(
    client,
    monkeypatch,
):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', True)
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_HTTPONLY', True)
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SAMESITE', 'Lax')
    monkeypatch.setitem(toca.app.config, 'SESSION_REFRESH_EACH_REQUEST', True)
    user_id = _seed_user()
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess.permanent = True

    me = client.get('/api/auth/me', base_url='https://localhost')
    cookie_headers = me.headers.getlist('Set-Cookie')

    assert me.get_json()['authenticated'] is True
    assert any('Secure' in value for value in cookie_headers)
    assert any('HttpOnly' in value for value in cookie_headers)
    assert any('SameSite=Lax' in value for value in cookie_headers)
    assert any('Expires=' in value for value in cookie_headers)

    logout = client.post('/api/auth/logout', base_url='https://localhost')
    after = client.get('/api/auth/me', base_url='https://localhost')
    assert logout.get_json() == {'ok': True}
    assert after.get_json()['authenticated'] is False


def test_expired_graph_token_is_refreshed_without_exposing_refresh_token(
    db_path,
    monkeypatch,
):
    user_id = _seed_user('graph-f85@corp.invalid')
    conn = toca.get_db()
    outlook_graph._upsert_tokens(
        conn,
        user_id,
        {
            'access_token': 'expired-access',
            'refresh_token': 'protected-refresh',
            'expires_in': -3600,
            'scope': 'Mail.Read',
        },
    )
    observed = {}

    def _refresh(conn_arg, user_id_arg, refresh_token, settings=None):
        observed['user_id'] = user_id_arg
        observed['refresh_token'] = refresh_token
        return {'access_token': 'renewed-access'}

    monkeypatch.setattr(outlook_graph, '_refresh_tokens', _refresh)

    access_token = outlook_graph.get_valid_access_token(conn, user_id)
    conn.close()

    assert access_token == 'renewed-access'
    assert observed == {
        'user_id': user_id,
        'refresh_token': 'protected-refresh',
    }
    assert 'protected-refresh' not in json.dumps(
        {'result': access_token}
    )
