"""Valida que as migrations rodam por inteiro no PostgreSQL (Fase 2 — sub-PR 2b).

Roda SOMENTE no CI (job com serviço Postgres via DATABASE_URL). Ao importar o
app com DATABASE_URL Postgres, as migrations já rodam; aqui garantimos (de forma
idempotente) e conferimos o resultado.
"""
import os

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


def test_schema_version_reaches_16():
    toca._run_schema_migrations()  # idempotente (version gate)
    conn = toca._open_main_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT MAX(version) FROM schema_version')
        assert cur.fetchone()[0] == 16
    finally:
        conn.close()


def test_founding_org_seeded_on_postgres():
    conn = toca._open_main_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM organizations')
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_core_tables_queryable_on_postgres():
    conn = toca._open_main_db()
    try:
        cur = conn.cursor()
        # Se a tabela/coluna não existir, o SELECT levanta erro → teste falha.
        for stmt in (
            'SELECT id FROM users LIMIT 1',
            'SELECT id FROM shares LIMIT 1',
            'SELECT owner_id FROM clients LIMIT 1',
            'SELECT owner_id FROM accounts LIMIT 1',
        ):
            cur.execute(stmt)
            cur.fetchall()
    finally:
        conn.close()
