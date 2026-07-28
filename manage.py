#!/usr/bin/env python3
"""Comandos operacionais seguros do TocaDoCoelho."""

import argparse
import json
import os

# O processo de management nunca inicia loops nem aplica migrations durante o
# import. O comando explícito abaixo mantém a ordem do deploy auditável mesmo
# se o ambiente do host contiver defaults inadequados para um processo web.
os.environ['TOCA_DISABLE_BG_JOBS'] = '1'
os.environ['TOCA_RUN_MIGRATIONS_ON_STARTUP'] = '0'
os.environ['TOCA_PROCESS_ROLE'] = 'migrate'

import app as toca  # noqa: E402


def migration_status():
    conn = toca._open_main_db(timeout=5.0)
    try:
        try:
            row = conn.execute(
                'SELECT MAX(version) AS version FROM schema_version'
            ).fetchone()
            applied = toca._first_column(row, 'version') or 0
        except Exception:
            applied = 0
    finally:
        conn.close()
    expected = max(version for version, _, _ in toca.SCHEMA_MIGRATIONS)
    return {
        'backend': toca.DB_BACKEND,
        'applied_version': int(applied),
        'expected_version': int(expected),
        'current': int(applied) == int(expected),
    }


def run_migrations():
    if toca._is_production_environment() and toca.DB_BACKEND != 'postgresql':
        raise RuntimeError('Migrations de produção exigem PostgreSQL.')
    before = migration_status()
    toca._run_schema_migrations()
    after = migration_status()
    if not after['current']:
        raise RuntimeError(
            'Migrations incompletas: '
            f"{after['applied_version']}/{after['expected_version']}."
        )
    return {'before': before, 'after': after}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='manage.py')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('migrate', help='Aplica migrations e verifica a versão.')
    subparsers.add_parser('migration-status', help='Exibe a versão do schema.')
    args = parser.parse_args(argv)

    result = run_migrations() if args.command == 'migrate' else migration_status()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
