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


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_migracao_17_recria_tabelas_derrubadas_em_banco_existente(db_path):
    """Reproduz um banco já migrado que perdeu a hierarquia iAta.

    A fixture db_path já roda o baseline (init_db atual, que já contém o
    schema novo), então as duas primeiras asserções por si só não provam que
    a migração 17 funciona isoladamente sobre um banco existente — é preciso
    apagar as tabelas e desmarcar a versão 17, como em
    test_banco_antigo_sem_a_tabela_de_oauth_e_curado (tests/test_schema_migrations.py).
    """
    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE iata_opportunities')
    conn.execute('DROP TABLE iata_accounts')
    conn.execute('DROP TABLE iata_managers')
    conn.execute('DELETE FROM schema_version WHERE version = 17')
    conn.commit()
    conn.close()

    assert not ({'iata_managers', 'iata_accounts', 'iata_opportunities'} & _tables(db_path))

    toca._run_schema_migrations()

    assert {'iata_managers', 'iata_accounts', 'iata_opportunities'} <= _tables(db_path)


def test_iata_add_record_columns_adiciona_o_que_falta(tmp_path):
    """SQLite não recria colunas sem recriar a tabela — exercita a função
    direto sobre um iata_records "cru" (sem as colunas novas), em vez de
    forçar a remoção artificial de colunas num banco real."""
    path = tmp_path / 'cru.db'
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE iata_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL
    )''')
    conn.commit()

    cols_antes = {r[1] for r in conn.execute('PRAGMA table_info(iata_records)')}
    assert 'format_version' not in cols_antes

    toca._iata_add_record_columns(conn)
    conn.commit()

    cols_depois = {r[1] for r in conn.execute('PRAGMA table_info(iata_records)')}
    conn.close()
    assert {'previous_record_id', 'body_markdown', 'body_edited',
            'reparse_failed', 'format_version'} <= cols_depois


def test_iata_add_record_columns_tolera_tabela_ausente(tmp_path):
    """Bancos sintéticos de teste que pulam a baseline não têm iata_records
    ainda — a função não deve estourar OperationalError nesse caso."""
    path = tmp_path / 'sem_tabela.db'
    conn = sqlite3.connect(path)
    toca._iata_add_record_columns(conn)  # não deve lançar
    conn.close()
