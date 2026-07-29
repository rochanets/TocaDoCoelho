import json
import logging
from pathlib import Path

import yaml

import app as toca
import manage


def test_production_migrations_are_explicit_but_local_default_is_preserved():
    assert toca._startup_migrations_enabled({}) is True
    assert toca._startup_migrations_enabled({'TOCA_ENV': 'development'}) is True
    assert toca._startup_migrations_enabled({'TOCA_ENV': 'production'}) is False
    assert toca._startup_migrations_enabled({
        'TOCA_ENV': 'production',
        'TOCA_RUN_MIGRATIONS_ON_STARTUP': '1',
    }) is True
    assert toca._startup_migrations_enabled({
        'TOCA_RUN_MIGRATIONS_ON_STARTUP': '0',
    }) is False


def test_management_command_reports_current_schema(db_path):
    status = manage.migration_status()

    assert status['backend'] == 'sqlite'
    assert status['current'] is True
    assert status['applied_version'] == status['expected_version']


def test_readyz_rejects_schema_behind_deployed_code(client):
    conn = toca.get_db()
    latest = max(version for version, _, _ in toca.SCHEMA_MIGRATIONS)
    conn.execute('DELETE FROM schema_version WHERE version = ?', (latest,))
    conn.commit()
    conn.close()

    response = client.get('/readyz')

    assert response.status_code == 503
    assert response.get_json() == {
        'status': 'not_ready',
        'reason': 'schema_outdated',
    }


def test_readyz_accepts_schema_ahead_for_expand_contract_rollback(
    client,
    monkeypatch,
):
    latest = max(version for version, _, _ in toca.SCHEMA_MIGRATIONS)
    conn = toca.get_db()
    conn.execute(
        '''INSERT INTO schema_version (version, name, applied_at)
           VALUES (?, ?, CURRENT_TIMESTAMP)''',
        (latest + 1, 'future_expand_contract'),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        toca,
        '_operations_waha_status',
        lambda: {'status': 'ready', 'http_status': 200},
    )

    readiness = client.get('/readyz')
    operations = client.get('/api/admin/operations/status')

    assert readiness.status_code == 200
    assert readiness.get_json() == {'status': 'ready'}
    assert operations.status_code == 200
    payload = operations.get_json()
    assert payload['status'] == 'ready'
    assert payload['database']['migrations_current'] is False
    assert payload['database']['migrations_compatible'] is True
    assert payload['database']['schema_ahead'] is True


def test_production_compose_orders_migration_and_backup_services():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (root / 'docker-compose.production.yml').read_text(encoding='utf-8')
    )
    services = compose['services']

    migrate = services['migrate']
    assert migrate['command'] == ['python', 'manage.py', 'migrate']
    assert migrate['restart'] == 'no'
    assert migrate['environment']['TOCA_PROCESS_ROLE'] == 'migrate'
    assert migrate['environment']['TOCA_DISABLE_BG_JOBS'] == '1'
    assert migrate['environment']['TOCA_RUN_MIGRATIONS_ON_STARTUP'] == '0'
    assert 'WAHA_API_KEY' not in migrate['environment']
    assert services['web']['depends_on']['migrate'] == {
        'condition': 'service_completed_successfully',
    }

    backup = services['postgres-backup']
    assert backup['image'] == 'postgres:16-alpine'
    assert backup['restart'] == 'unless-stopped'
    assert 'postgres_backups:/backups' in backup['volumes']
    assert backup['healthcheck']['test'] == [
        'CMD-SHELL',
        'test -s /backups/.last-success',
    ]
    assert 'ports' not in backup
    assert 'postgres_backups' in compose['volumes']


def test_migration_process_role_requires_only_core_production_secrets():
    env = {
        'TOCA_ENV': 'production',
        'TOCA_PROCESS_ROLE': 'migrate',
        'SECRET_KEY': 'm' * 48,
        'DATABASE_URL': 'postgresql://toca:password@postgres:5432/toca',
    }

    assert toca._production_configuration_errors(env) == []


def test_postgres_backup_scripts_are_safe_and_verifiable():
    root = Path(__file__).resolve().parents[1]
    backup = (root / 'deploy/postgres/backup-once.sh').read_text(encoding='utf-8')
    restore = (
        root / 'deploy/postgres/restore-verify.sh'
    ).read_text(encoding='utf-8')

    assert 'pg_dump' in backup
    assert '--format=custom' in backup
    assert 'pg_restore --list' in backup
    assert 'sha256sum' in backup
    assert 'BACKUP_RETENTION_DAYS' in backup
    assert 'PGPASSWORD=' not in backup

    assert 'pg_restore' in restore
    assert '--exit-on-error' in restore
    assert 'sha256sum -c' in restore
    assert 'if [ \"$target_database\" = \"$PGDATABASE\" ]' in restore
    assert 'dropdb --if-exists \"$target_database\"' in restore


def test_ci_exercises_explicit_migration_and_disposable_restore():
    root = Path(__file__).resolve().parents[1]
    docker_workflow = (
        root / '.github/workflows/docker.yml'
    ).read_text(encoding='utf-8')
    operations_path = root / '.github/workflows/operations.yml'
    operations_workflow = operations_path.read_text(encoding='utf-8')

    assert 'python manage.py migrate' in docker_workflow
    assert 'TOCA_RUN_MIGRATIONS_ON_STARTUP=0' in docker_workflow
    assert 'restore-verify.sh' in operations_workflow
    assert 'toca_restore_ci' in operations_workflow
    assert 'backup-restore' in yaml.safe_load(operations_workflow)['jobs']


def test_json_logs_redact_secrets_and_include_request_id():
    formatter = toca._JsonLogFormatter()
    record = logging.LogRecord(
        'toca-test',
        logging.ERROR,
        __file__,
        1,
        (
            'authorization=Bearer-real-secret '
            'password=hunter2 '
            'https://login.invalid/callback?code=oauth-code&state=oauth-state'
        ),
        (),
        None,
    )
    record.request_id = 'request-12345678'

    payload = json.loads(formatter.format(record))

    assert payload['request_id'] == 'request-12345678'
    assert 'Bearer-real-secret' not in payload['message']
    assert 'hunter2' not in payload['message']
    assert 'oauth-code' not in payload['message']
    assert 'oauth-state' not in payload['message']
    assert payload['message'].count('[REDACTED]') == 4


def test_request_id_is_propagated_or_replaced(client):
    supplied = client.get(
        '/healthz',
        headers={'X-Request-ID': 'edge-request-12345'},
    )
    generated = client.get(
        '/healthz',
        headers={'X-Request-ID': 'bad id'},
    )

    assert supplied.headers['X-Request-ID'] == 'edge-request-12345'
    assert len(generated.headers['X-Request-ID']) == 32
    assert generated.headers['X-Request-ID'].isalnum()


def test_admin_operations_status_is_read_only_and_secret_free(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        toca,
        '_operations_waha_status',
        lambda: {'status': 'ready', 'http_status': 200},
    )

    response = client.get('/api/admin/operations/status')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'ready'
    assert payload['database']['migrations_current'] is True
    assert payload['database']['migrations_compatible'] is True
    assert payload['database']['schema_ahead'] is False
    assert payload['database']['backend'] == 'sqlite'
    assert payload['waha'] == {'status': 'ready', 'http_status': 200}
    assert 'DATABASE_URL' not in json.dumps(payload)
    assert 'api_key' not in json.dumps(payload).lower()
