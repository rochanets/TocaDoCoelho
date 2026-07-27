"""Testes unitários da tradução SQLite → PostgreSQL (Fase 2 — sub-PR 2b).

Rodam onde o sqlglot está instalado (local, imagem web, job Postgres). São
pulados no job de testes desktop, que não instala o sqlglot.
"""
import importlib.util

import pytest

import app as toca

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec('sqlglot') is None,
    reason='sqlglot não instalado (backend SQLite não precisa dele)',
)


def test_placeholders_qmark_to_pyformat():
    out = toca._transpile_to_postgres('INSERT INTO t (a, b) VALUES (?, ?)')
    assert '%s' in out
    assert '?' not in out


def test_autoincrement_becomes_identity():
    out = toca._transpile_to_postgres(
        'CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, n TEXT)'
    ).upper()
    assert 'IDENTITY' in out
    assert 'AUTOINCREMENT' not in out


def test_foreign_key_and_check_preserved():
    out = toca._transpile_to_postgres(
        'CREATE TABLE t (id INTEGER PRIMARY KEY CHECK (id = 1), '
        'c INTEGER, FOREIGN KEY(c) REFERENCES x(id) ON DELETE CASCADE)'
    ).upper()
    assert 'CHECK' in out
    assert 'REFERENCES' in out
    assert 'ON DELETE CASCADE' in out


def test_select_passthrough():
    sql = 'SELECT id FROM clients WHERE owner_id IS NULL'
    out = toca._transpile_to_postgres(sql)
    assert 'clients' in out.lower()
    assert 'owner_id' in out.lower()


def test_result_is_cached():
    sql = 'SELECT 42'
    first = toca._transpile_to_postgres(sql)
    assert sql in toca._TRANSPILE_CACHE
    assert toca._transpile_to_postgres(sql) == first


def test_insert_or_ignore_becomes_on_conflict():
    out = toca._transpile_to_postgres(
        'INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)'
    ).upper()
    assert 'OR IGNORE' not in out
    assert 'ON CONFLICT' in out and 'DO NOTHING' in out


def test_pragma_table_info_maps_to_information_schema():
    out = toca._pragma_table_info_to_pg('clients')
    assert 'information_schema.columns' in out
    assert "column_name::text AS name" in out


def test_shares_upsert_transpiles_to_postgres():
    out = toca._transpile_to_postgres(
        '''INSERT INTO shares
              (record_type, record_id, shared_with_user_id, permission, created_by)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(record_type, record_id, shared_with_user_id)
           DO UPDATE SET
              permission = excluded.permission,
              created_by = COALESCE(shares.created_by, excluded.created_by)'''
    ).upper()
    assert 'ON CONFLICT' in out
    assert 'DO UPDATE SET' in out
    assert 'EXCLUDED.PERMISSION' in out
    assert 'COALESCE(SHARES.CREATED_BY, EXCLUDED.CREATED_BY)' in out
    assert '?' not in out
