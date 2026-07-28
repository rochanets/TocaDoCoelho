# -*- coding: utf-8 -*-
"""Estado operacional somente leitura para administradores."""


def _operations_database_status():
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT MAX(version) AS version FROM schema_version'
        ).fetchone()
        applied_version = int(_first_column(row, 'version') or 0)
        expected_version = max(
            version for version, _, _ in SCHEMA_MIGRATIONS
        )
        interrupted = conn.execute(
            "SELECT COUNT(*) AS total FROM background_tasks "
            "WHERE status = 'interrupted'"
        ).fetchone()
        ambiguous_sends = conn.execute(
            "SELECT COUNT(*) AS total FROM scheduled_sends "
            "WHERE status = 'error' AND error LIKE "
            "'Execução interrompida após claim%'"
        ).fetchone()
        return {
            'status': 'ready',
            'backend': DB_BACKEND,
            'migration_version': applied_version,
            'expected_migration_version': expected_version,
            'migrations_current': applied_version == expected_version,
            'interrupted_tasks': int(_first_column(interrupted, 'total') or 0),
            'ambiguous_scheduled_sends': int(
                _first_column(ambiguous_sends, 'total') or 0
            ),
        }
    finally:
        conn.close()


def _operations_waha_status():
    api_url, api_key, _ = _waha_settings()
    if not api_url:
        return {'status': 'not_configured'}
    try:
        response = requests.get(
            f'{api_url}/health',
            headers=_waha_headers(api_key),
            timeout=2,
        )
        return {
            'status': 'ready' if response.status_code == 200 else 'degraded',
            'http_status': response.status_code,
        }
    except requests.RequestException:
        return {'status': 'unavailable'}


@app.route('/api/admin/operations/status', methods=['GET'])
@admin_required
def admin_operations_status():
    """Resumo sem segredos para diagnóstico e alertas operacionais."""
    database = _operations_database_status()
    waha = _operations_waha_status()
    overall = (
        'ready'
        if database['migrations_current'] and waha['status'] in {
            'ready',
            'not_configured',
        }
        else 'degraded'
    )
    return jsonify({
        'status': overall,
        'app_version': APP_VERSION,
        'instance_id': _PROCESS_INSTANCE_ID,
        'uptime_seconds': int(time.monotonic() - _PROCESS_STARTED_MONOTONIC),
        'worker_pid': os.getpid(),
        'database': database,
        'waha': waha,
    })
