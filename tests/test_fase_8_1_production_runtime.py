import hashlib
from pathlib import Path

import app as toca


def _valid_production_env():
    waha_key = 'w' * 48
    return {
        'TOCA_ENV': 'production',
        'SECRET_KEY': 'a' * 48,
        'DATABASE_URL': 'postgresql://toca:password@postgres:5432/toca',
        'TOCA_AUTH_ENABLED': '1',
        'TOCA_COOKIE_SECURE': '1',
        'TOCA_COOKIE_SAMESITE': 'Lax',
        'TOCA_TRUST_PROXY': '1',
        'WEB_CONCURRENCY': '1',
        'WAHA_API_URL': 'http://waha:3000',
        'WAHA_API_KEY': waha_key,
        'WAHA_API_KEY_HASH': (
            'sha512:' + hashlib.sha512(waha_key.encode('utf-8')).hexdigest()
        ),
        'WAHA_WEBHOOK_HMAC_KEY': 'h' * 48,
        'WAHA_SESSION_NAME': 'default',
        'OUTLOOK_GRAPH_TENANT_ID': 'tenant.example.com',
        'OUTLOOK_GRAPH_CLIENT_ID': '00000000-0000-0000-0000-000000000001',
        'OUTLOOK_GRAPH_LOGIN_REDIRECT_URI': 'https://toca.empresa.com.br/api/auth/callback',
        'OUTLOOK_GRAPH_REDIRECT_URI': 'https://toca.empresa.com.br/api/outlook/oauth/callback',
    }


def test_non_production_preserves_local_defaults():
    assert toca._production_configuration_errors({}) == []
    assert toca._production_configuration_errors({'TOCA_ENV': 'development'}) == []


def test_valid_production_contract_has_no_errors():
    assert toca._production_configuration_errors(_valid_production_env()) == []


def test_production_contract_fails_closed_for_unsafe_runtime():
    env = _valid_production_env()
    env.update({
        'SECRET_KEY': 'CHANGE_ME_WITH_A_LONG_PLACEHOLDER_VALUE',
        'DATABASE_URL': 'sqlite:///data/toca.db',
        'TOCA_AUTH_ENABLED': '0',
        'TOCA_COOKIE_SECURE': '0',
        'TOCA_TRUST_PROXY': '0',
        'WEB_CONCURRENCY': '3',
        'WAHA_API_URL': 'http://localhost:3000',
        'WAHA_API_KEY': 'short',
        'WAHA_API_KEY_HASH': 'not-a-sha512-hash',
        'WAHA_WEBHOOK_HMAC_KEY': 'short',
        'WAHA_SESSION_NAME': 'invalid session name',
        'OUTLOOK_GRAPH_LOGIN_REDIRECT_URI': 'http://toca.example.com/api/auth/callback',
        'OUTLOOK_GRAPH_TENANT_ID': 'REPLACE_ME_TENANT_ID',
        'OUTLOOK_GRAPH_CLIENT_ID': '00000000-0000-0000-0000-000000000000',
    })

    errors = toca._production_configuration_errors(env)

    assert any('SECRET_KEY' in error for error in errors)
    assert any('PostgreSQL' in error for error in errors)
    assert any('TOCA_AUTH_ENABLED' in error for error in errors)
    assert any('TOCA_COOKIE_SECURE' in error for error in errors)
    assert any('TOCA_TRUST_PROXY' in error for error in errors)
    assert any('TOCA_MULTIWORKER_JOBS_ENABLED' in error for error in errors)
    assert any('WAHA_API_URL' in error for error in errors)
    assert any('WAHA_API_KEY deve' in error for error in errors)
    assert any('WAHA_API_KEY_HASH' in error for error in errors)
    assert any('WAHA_WEBHOOK_HMAC_KEY' in error for error in errors)
    assert any('WAHA_SESSION_NAME' in error for error in errors)
    assert any('OUTLOOK_GRAPH_TENANT_ID' in error for error in errors)
    assert any('OUTLOOK_GRAPH_CLIENT_ID' in error for error in errors)
    assert any('OUTLOOK_GRAPH_LOGIN_REDIRECT_URI' in error for error in errors)


def test_production_validation_never_echoes_secret():
    env = _valid_production_env()
    env['SECRET_KEY'] = 'sensitive-but-too-short'

    try:
        toca._validate_production_configuration(env)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError('Configuração insegura deveria falhar.')

    assert env['SECRET_KEY'] not in message


def test_production_contract_accepts_coordinated_postgres_workers():
    env = _valid_production_env()
    env.update({
        'WEB_CONCURRENCY': '3',
        'TOCA_MULTIWORKER_JOBS_ENABLED': '1',
    })
    assert toca._production_configuration_errors(env) == []


def test_readyz_checks_database_and_is_public_with_auth(client, monkeypatch):
    monkeypatch.setattr(toca, '_auth_enabled', lambda: True)
    response = client.get('/readyz')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'ready'}


def test_readyz_returns_503_when_database_is_unavailable(client, monkeypatch):
    def _unavailable(*args, **kwargs):
        raise OSError('database unavailable')

    monkeypatch.setattr(toca, '_open_main_db', _unavailable)
    response = client.get('/readyz')
    assert response.status_code == 503
    assert response.get_json() == {'status': 'not_ready'}


def test_repository_examples_do_not_restore_removed_default_credentials():
    root = Path(__file__).resolve().parents[1]
    contents = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in (
            root / 'app.py',
            root / 'docker-compose.production.yml',
            root / 'launcher.py',
            root / 'scripts' / 'testar_whatsapp_update.bat',
        )
    )
    assert 'fuBoUPGL+UmrErevVE6VWQ' not in contents
    assert 'RuWKlxg1Sk+/3PpzUKof+w' not in contents
    assert 'toca-test-key-2024' not in contents
