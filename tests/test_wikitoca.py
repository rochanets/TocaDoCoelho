import sqlite3

import app as toca


def _tables(path):
    conn = sqlite3.connect(str(path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _columns(path, table):
    conn = sqlite3.connect(str(path))
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    finally:
        conn.close()


def test_migracao_19_cria_tabelas_de_capacitacao(db_path):
    assert {
        'wiki_training_sessions',
        'wiki_training_documents',
        'wiki_training_messages',
    } <= _tables(db_path)


def test_migracao_19_adiciona_colunas_de_extracao_em_wiki_documents(db_path):
    cols = _columns(db_path, 'wiki_documents')
    assert {'extracted_text', 'extracted_at', 'extract_status'} <= cols


def test_migracao_19_roda_em_banco_legado_sem_as_colunas(tmp_path, monkeypatch):
    """Banco antigo com wiki_documents no formato original precisa ser curado."""
    legado = tmp_path / 'legado.db'
    conn = sqlite3.connect(str(legado))
    conn.execute('''CREATE TABLE wiki_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        file_name TEXT NOT NULL,
        original_name TEXT NOT NULL,
        file_url TEXT NOT NULL,
        file_ext TEXT,
        file_size INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT, applied_at TIMESTAMP)')
    for v in range(1, 19):
        conn.execute('INSERT INTO schema_version (version, name) VALUES (?, ?)', (v, f'legado_{v}'))
    conn.commit()
    conn.close()

    monkeypatch.setattr(toca, 'DB_PATH', legado)
    toca._run_schema_migrations()

    assert {'extracted_text', 'extracted_at', 'extract_status'} <= _columns(legado, 'wiki_documents')
    assert 'wiki_training_sessions' in _tables(legado)


def test_migracao_19_e_idempotente(db_path):
    """Se a linha da 19 sumir do schema_version, rodar de novo não pode quebrar."""
    conn = sqlite3.connect(str(db_path))
    conn.execute('DELETE FROM schema_version WHERE version = 19')
    conn.commit()
    conn.close()

    toca._run_schema_migrations()

    assert {'extracted_text', 'extracted_at', 'extract_status'} <= _columns(db_path, 'wiki_documents')
    assert 'wiki_training_sessions' in _tables(db_path)
