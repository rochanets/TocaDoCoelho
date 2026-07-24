"""Teste do transporte PostgreSQL na fábrica de conexão (Fase 2 — sub-PR 2a).

Roda SOMENTE quando há um PostgreSQL disponível via DATABASE_URL — ou seja, no
CI (job com serviço Postgres). Localmente, sem DATABASE_URL Postgres, é pulado.

Valida apenas o TRANSPORTE (conectar + executar um statement trivial). O SQL
dialetal da aplicação (migrations e queries) ainda não roda neste backend —
isso chega nas sub-PRs 2b/2c.
"""
import os

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


def test_backend_detected_as_postgres():
    # Com DATABASE_URL Postgres no ambiente, o app importa já em modo postgresql.
    assert toca.DB_BACKEND == 'postgresql'


def test_open_main_db_postgres_select_1():
    conn = toca._open_main_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1')
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_open_main_db_postgres_row_factory():
    conn = toca._open_main_db(row_factory=True)
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1 AS n')
        row = cur.fetchone()
        # dict_row → acesso por nome de coluna
        assert row['n'] == 1
    finally:
        conn.close()
