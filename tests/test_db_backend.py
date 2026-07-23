"""Testes da camada de acesso ao banco (Fase 2 — sub-PR 1).

Cobre o seam de configuração (DATABASE_URL → backend) e a fábrica de conexões.
Sem DATABASE_URL, o backend é SQLite e tudo funciona como antes.
"""
import sqlite3

import pytest

import app as toca


# ------------------------------------------------------- resolução de backend

def test_default_backend_is_sqlite():
    assert toca.DB_BACKEND == 'sqlite'


@pytest.mark.parametrize('url,expected', [
    (None, 'sqlite'),
    ('', 'sqlite'),
    ('sqlite:///foo.db', 'sqlite'),
    ('sqlite3:///foo.db', 'sqlite'),
    ('file:///foo.db', 'sqlite'),
    ('postgres://u:p@host/db', 'postgresql'),
    ('postgresql://u:p@host:5432/db', 'postgresql'),
])
def test_resolve_db_backend(url, expected):
    assert toca._resolve_db_backend(url) == expected


# ------------------------------------------------------------ _open_sqlite

def test_open_sqlite_defaults(tmp_path):
    conn = toca._open_sqlite(tmp_path / 'x.db')
    try:
        assert conn.row_factory is None
        # foreign_keys OFF por padrão
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 0
    finally:
        conn.close()


def test_open_sqlite_row_factory_and_fk(tmp_path):
    conn = toca._open_sqlite(tmp_path / 'x.db', row_factory=True, foreign_keys=True)
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        # busy_timeout derivado do timeout (15s -> 15000ms)
        assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == 15000
    finally:
        conn.close()


# ------------------------------------------------------------ _open_main_db

def test_open_main_db_uses_sqlite_by_default(db_path):
    conn = toca._open_main_db(row_factory=True)
    try:
        assert conn.row_factory is sqlite3.Row
        # consegue consultar o schema já migrado
        v = conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
        assert v >= 14
    finally:
        conn.close()


def test_open_main_db_rejects_unimplemented_backend(monkeypatch):
    monkeypatch.setattr(toca, 'DB_BACKEND', 'postgresql')
    with pytest.raises(NotImplementedError):
        toca._open_main_db()


def test_get_db_still_works_through_factory(db_path):
    """get_db() deve continuar entregando conexão com Row + foreign_keys ON."""
    conn = toca.get_db()
    try:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    finally:
        conn.close()
