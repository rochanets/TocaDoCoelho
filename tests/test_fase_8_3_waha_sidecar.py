import hashlib
import hmac
import json
from pathlib import Path

import requests
import yaml

import app as toca


def test_waha_environment_upserts_qualify_postgres_conflict_columns():
    class RecordingCursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params):
            self.calls.append((sql, params))

    cursor = RecordingCursor()
    toca._seed_waha_settings_from_environment(
        cursor,
        {
            'WAHA_API_URL': 'http://waha:3000',
            'WAHA_API_KEY': 'api-key',
            'WAHA_SESSION_NAME': 'default',
        },
    )

    assert [params[0] for _, params in cursor.calls] == [
        'waha_api_url',
        'waha_api_key',
        'waha_session_name',
    ]
    assert all('WHERE app_settings.value' in sql for sql, _ in cursor.calls)
    assert all('WHERE value' not in sql for sql, _ in cursor.calls)


def test_production_compose_has_one_private_persistent_waha_sidecar():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (root / 'docker-compose.production.yml').read_text(encoding='utf-8')
    )
    waha = compose['services']['waha']
    web = compose['services']['web']

    assert waha['image'] == 'devlikeapro/waha:latest-2026.7.1'
    assert 'ports' not in waha
    assert waha['expose'] == ['3000']
    assert waha['restart'] == 'unless-stopped'
    assert waha['volumes'] == ['waha_sessions:/app/.sessions']
    assert set(waha['networks']) == {'backend', 'waha_egress'}
    assert compose['networks']['backend']['internal'] is True
    assert 'waha_sessions' in compose['volumes']

    env = waha['environment']
    assert env['WHATSAPP_DEFAULT_ENGINE'] == 'WEBJS'
    assert env['WAHA_DASHBOARD_ENABLED'] == 'false'
    assert env['WHATSAPP_SWAGGER_ENABLED'] == 'false'
    assert env['WAHA_LOCAL_STORE_BASE_DIR'] == '/app/.sessions'
    assert env['WHATSAPP_RESTART_ALL_SESSIONS'] == 'true'
    assert env['WHATSAPP_HOOK_URL'] == (
        'http://web:3000/api/whatsapp/webhook'
    )
    assert env['WHATSAPP_HOOK_EVENTS'] == 'message.any'
    assert env['WHATSAPP_HOOK_HMAC_KEY'].startswith('${WAHA_WEBHOOK_HMAC_KEY:')
    assert web['environment']['WAHA_API_URL'] == 'http://waha:3000'

    assert not (root / 'docker-compose.waha.yml').exists()
    assert not (root / 'docker-compose.whatsapp.yml').exists()


def test_waha_production_configuration_is_fail_closed():
    env = {
        'TOCA_ENV': 'production',
        'SECRET_KEY': 's' * 48,
        'DATABASE_URL': 'postgresql://toca:password@postgres:5432/toca',
        'TOCA_AUTH_ENABLED': '1',
        'TOCA_COOKIE_SECURE': '1',
        'TOCA_TRUST_PROXY': '1',
        'WEB_CONCURRENCY': '1',
        'OUTLOOK_GRAPH_TENANT_ID': 'tenant.example.com',
        'OUTLOOK_GRAPH_CLIENT_ID': '00000000-0000-0000-0000-000000000001',
        'OUTLOOK_GRAPH_LOGIN_REDIRECT_URI': (
            'https://toca.empresa.com.br/api/auth/callback'
        ),
        'OUTLOOK_GRAPH_REDIRECT_URI': (
            'https://toca.empresa.com.br/api/outlook/oauth/callback'
        ),
    }

    errors = toca._production_configuration_errors(env)

    assert any('WAHA_API_URL' in error for error in errors)
    assert any('WAHA_API_KEY deve' in error for error in errors)
    assert any('WAHA_API_KEY_HASH' in error for error in errors)
    assert any('WAHA_WEBHOOK_HMAC_KEY' in error for error in errors)


def test_production_waha_settings_are_environment_authoritative(
    db_path,
    monkeypatch,
):
    conn = toca.get_db()
    conn.execute(
        "UPDATE app_settings SET value = 'http://legacy.invalid:3001' "
        "WHERE key = 'waha_api_url'"
    )
    conn.execute(
        "UPDATE app_settings SET value = 'legacy-key' "
        "WHERE key = 'waha_api_key'"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv('TOCA_ENV', 'production')
    monkeypatch.setenv('WAHA_API_URL', 'http://waha:3000')
    monkeypatch.setenv('WAHA_API_KEY', 'production-key')
    monkeypatch.setenv('WAHA_SESSION_NAME', 'production-session')

    assert toca._waha_settings() == (
        'http://waha:3000',
        'production-key',
        'production-session',
    )


def test_production_rejects_runtime_waha_config_mutation(client, monkeypatch):
    monkeypatch.setenv('TOCA_ENV', 'production')

    response = client.put(
        '/api/whatsapp/config',
        json={'waha_api_url': 'http://other-waha:3000'},
    )

    assert response.status_code == 409
    assert 'variáveis de ambiente' in response.get_json()['error']


def test_waha_webhook_hmac_is_public_but_authenticated(
    client,
    db_path,
    monkeypatch,
):
    secret = 'webhook-secret-with-at-least-32-characters'
    monkeypatch.setenv('WAHA_WEBHOOK_HMAC_KEY', secret)
    monkeypatch.setattr(toca, '_auth_enabled', lambda: True)
    monkeypatch.setattr(toca, 'current_user', lambda: None)
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES ('Org webhook WAHA')")
    org_id = cur.lastrowid
    cur.execute(
        '''INSERT INTO users (org_id, email, full_name, role, is_active)
           VALUES (?, 'webhook-waha@corp.com', 'Webhook WAHA', 'member', 1)''',
        (org_id,),
    )
    user_id = cur.lastrowid
    conn.execute(
        '''INSERT INTO user_waha_sessions (user_id, session_name)
           VALUES (?, 'default')''',
        (user_id,),
    )
    conn.commit()
    conn.close()
    raw = json.dumps(
        {
            'event': 'message.any',
            'session': 'default',
            'payload': {
                'from': '5511000000000@c.us',
                'fromMe': False,
                'body': 'mensagem assinada',
                'timestamp': 1750000000,
            },
        },
        separators=(',', ':'),
    ).encode('utf-8')
    signature = hmac.new(
        secret.encode('utf-8'),
        raw,
        hashlib.sha512,
    ).hexdigest()

    invalid = client.post(
        '/api/whatsapp/webhook',
        data=raw,
        content_type='application/json',
        headers={
            'X-Webhook-Hmac': '0' * 128,
            'X-Webhook-Hmac-Algorithm': 'sha512',
        },
    )
    valid = client.post(
        '/api/whatsapp/webhook',
        data=raw,
        content_type='application/json',
        headers={
            'X-Webhook-Hmac': signature,
            'X-Webhook-Hmac-Algorithm': 'sha512',
        },
    )

    assert invalid.status_code == 401
    assert valid.status_code == 200
    assert valid.get_json() == {'ok': True, 'ignored': 'nao_cliente'}


def test_production_does_not_restart_desktop_waha_lite(
    client,
    monkeypatch,
):
    monkeypatch.setenv('TOCA_ENV', 'production')
    monkeypatch.setenv('WAHA_API_URL', 'http://waha:3000')
    monkeypatch.setenv('WAHA_API_KEY', 'production-key')
    monkeypatch.setenv('WAHA_SESSION_NAME', 'default')

    def _offline(*args, **kwargs):
        raise requests.exceptions.ConnectionError('offline')

    monkeypatch.setattr(toca.requests, 'get', _offline)
    monkeypatch.setattr(
        toca,
        '_restart_waha_lite',
        lambda: (_ for _ in ()).throw(AssertionError('não deve reiniciar')),
    )

    response = client.get('/api/whatsapp/status')

    assert response.status_code == 200
    assert response.get_json()['state'] == 'offline'
    assert 'Sidecar WAHA' in response.get_json()['error']
