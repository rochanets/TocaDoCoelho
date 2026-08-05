# -*- coding: utf-8 -*-
import sqlite3

import app as toca


def _cols(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    finally:
        conn.close()


def test_migracao_cria_tabelas_da_hierarquia(db_path):
    conn = sqlite3.connect(db_path)
    try:
        tabelas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {'iata_managers', 'iata_accounts', 'iata_opportunities'} <= tabelas


def test_migracao_adiciona_colunas_em_iata_records(db_path):
    cols = _cols(db_path, 'iata_records')
    assert {'previous_record_id', 'body_markdown', 'body_edited',
            'reparse_failed', 'format_version'} <= cols
