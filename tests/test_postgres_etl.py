"""Dry-run do ETL SQLite → PostgreSQL contra o banco fictício (Fase 2).

Roda só no CI com serviço Postgres. Prepara uma cópia do BD_teste migrada até a
versão atual (subprocesso com backend SQLite), roda o ETL para o Postgres e
valida COUNT(*) por tabela + spot-check de IDs preservados.

Observação: este teste TRUNCA e recarrega o banco Postgres compartilhado do job,
por isso deve ser o ÚLTIMO a rodar (ver .github/workflows/postgres.yml).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)

_ROOT = Path(__file__).resolve().parents[1]
_BD_TESTE = _ROOT / 'BD_teste' / 'toca-do-coelho-ficticio-reduzido.db'


def _migrate_sqlite_copy(tmp_path):
    """Copia o BD_teste e migra até a versão atual num subprocesso (SQLite)."""
    data_dir = tmp_path / 'sqlitehome'
    data_dir.mkdir()
    dst = data_dir / 'toca-do-coelho.db'
    shutil.copy(_BD_TESTE, dst)
    env = {k: v for k, v in os.environ.items() if k != 'DATABASE_URL'}
    env['TOCA_DATA_DIR'] = str(data_dir)
    env['TOCA_DISABLE_BG_JOBS'] = '1'
    subprocess.run([sys.executable, '-c', 'import app'],
                   env=env, cwd=str(_ROOT), check=True)
    return dst


def test_etl_bd_teste_counts_and_ids(tmp_path):
    sys.path.insert(0, str(_ROOT))
    from scripts.etl_sqlite_to_postgres import run_etl

    src = _migrate_sqlite_copy(tmp_path)
    result = run_etl(src, os.environ['DATABASE_URL'], log=lambda *a, **k: None)

    assert result['mismatches'] == [], f'divergências COUNT(*): {result["mismatches"]}'
    assert sum(result['tables'].values()) > 0, 'nada foi migrado'

    import psycopg
    import sqlite3
    pg = psycopg.connect(os.environ['DATABASE_URL'])
    sq = sqlite3.connect(str(src))
    try:
        # spot-check: clientes copiados com os mesmos ids/nomes
        s = sq.execute('SELECT id, name FROM clients ORDER BY id').fetchall()
        p = pg.execute('SELECT id, name FROM clients ORDER BY id').fetchall()
        assert s == p, 'linhas de clients divergem entre origem e destino'
        # sequence reajustada: novo insert não colide com ids existentes
        maxid = pg.execute('SELECT MAX(id) FROM clients').fetchone()[0]
        cur = pg.cursor()
        cur.execute("INSERT INTO clients (name, company, position) "
                    "VALUES ('seq check', 'x', 'y') RETURNING id")
        new_id = cur.fetchone()[0]
        pg.rollback()
        assert new_id > maxid, f'sequence não reajustada (novo id {new_id} <= max {maxid})'
    finally:
        pg.close()
        sq.close()
