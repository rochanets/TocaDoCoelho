"""Regressão: emulação de lastrowid (RETURNING id) com cursor dict-row no PG.

Guarda o bug em que o PRIMEIRO INSERT de runtime de um processo, contra um banco
JÁ migrado (cache _PG_ID_TABLES ainda None), estourava `KeyError: 0` — porque
_pg_id_tables lia a linha por índice posicional (`r[0]`) num cursor dict-row
(get_db usa row_factory=True). No CI as migrations rodam do zero e populam o
cache antes, mascarando o problema; aqui forçamos o cache frio de propósito.

Roda só no CI com Postgres (skip sem DATABASE_URL Postgres).
"""
import os

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


def test_first_runtime_insert_with_cold_id_cache(monkeypatch):
    # Simula processo novo contra banco já migrado: cache frio + cursor dict-row.
    monkeypatch.setattr(toca, '_PG_ID_TABLES', None)
    conn = toca.get_db()  # row_factory=True → dict rows
    try:
        c = conn.cursor()
        # Antes da correção, este INSERT estourava KeyError: 0 ao montar o cache
        # de tabelas com coluna id para anexar RETURNING id.
        c.execute(
            "INSERT INTO clients (name, company, position) VALUES (?, ?, ?)",
            ('Regressao lastrowid', 'Empresa Teste', 'Gerente'),
        )
        assert c.lastrowid, 'INSERT não emulou lastrowid (RETURNING id)'
        conn.commit()
    finally:
        conn.close()
