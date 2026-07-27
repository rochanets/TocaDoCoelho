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


def test_schema_version_reaches_29():
    toca._run_schema_migrations()  # idempotente (version gate)
    conn = toca._open_main_db()
    try:
        cur = conn.cursor()
        cur.execute('SELECT MAX(version) FROM schema_version')
        assert cur.fetchone()[0] == 29
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
            'SELECT used_ms FROM transcription_monthly_usage LIMIT 1',
        ):
            cur.execute(stmt)
            cur.fetchall()
    finally:
        conn.close()


def test_transcription_monthly_quota_is_atomic_on_postgres(monkeypatch):
    monkeypatch.setenv('TOCA_TRANSCRIPTION_MONTHLY_MINUTES', '1')
    period_key = toca._transcription_period_key()
    conn = toca._open_main_db()
    try:
        conn.execute(
            'DELETE FROM transcription_monthly_usage WHERE period_key = ?',
            (period_key,),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        quota = toca._transcription_reserve_monthly_quota(30_000)
        assert quota == {'used_seconds': 30, 'limit_seconds': 60}
        with pytest.raises(toca.TranscriptionError) as raised:
            toca._transcription_reserve_monthly_quota(31_000)
        assert raised.value.code == 'TRANSCRIPTION_MONTHLY_QUOTA_REACHED'
        assert toca._transcription_monthly_usage() == 30_000
    finally:
        conn = toca._open_main_db()
        try:
            conn.execute(
                'DELETE FROM transcription_monthly_usage WHERE period_key = ?',
                (period_key,),
            )
            conn.commit()
        finally:
            conn.close()
