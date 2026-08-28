import sqlite3

import pytest

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


_SEM_OCR = not (getattr(toca, 'PYTESSERACT_AVAILABLE', False) and getattr(toca, 'PIL_AVAILABLE', False))


def _cria_imagem(tmp_path, ext='.png'):
    from PIL import Image
    destino = tmp_path / f'captura{ext}'
    Image.new('RGB', (40, 20), color='white').save(str(destino))
    return destino


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
@pytest.mark.parametrize('ext', ['.png', '.jpg', '.jpeg'])
def test_extrai_texto_de_imagem_via_ocr(tmp_path, monkeypatch, ext):
    """Com o Tesseract disponível, o texto lido da imagem entra na extração.

    Este é o teste que dirige o TDD: sem o ramo de imagem a função cai fora de
    todos os `elif` e devolve '' — não porque o OCR falhou, mas porque o formato
    nem é tratado. Parametrizado pelas três extensões aceitas para pegar um
    erro de digitação na tupla de despacho (`.jpg`/`.jpeg` não caindo no mesmo
    ramo que `.png`).
    """
    destino = _cria_imagem(tmp_path, ext)
    # setattr via monkeypatch garante a restauração mesmo com o código de
    # produção reatribuindo tesseract_cmd durante a chamada.
    monkeypatch.setattr(toca.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: 'tesseract-falso')
    monkeypatch.setattr(toca.pytesseract, 'image_to_string', lambda *a, **k: 'Fluxo de aprovacao')

    assert 'Fluxo de aprovacao' in toca._itoca_extract_text_from_file(str(destino))


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_extrai_texto_de_imagem_sem_tesseract_retorna_vazio(tmp_path, monkeypatch):
    """Sem o binário do Tesseract a extração não pode explodir — devolve vazio."""
    destino = _cria_imagem(tmp_path)
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: None)

    assert toca._itoca_extract_text_from_file(str(destino)) == ''


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_ocr_de_imagem_que_falha_nao_propaga_excecao(tmp_path, monkeypatch):
    """Imagem corrompida/OCR quebrado vira string vazia, não exceção — quem chama
    marca extract_status='error' pelo resultado, sem derrubar o lote de upload."""
    destino = _cria_imagem(tmp_path)

    def _explode(*a, **k):
        raise RuntimeError('tesseract morreu')

    monkeypatch.setattr(toca.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: 'tesseract-falso')
    monkeypatch.setattr(toca.pytesseract, 'image_to_string', _explode)

    assert toca._itoca_extract_text_from_file(str(destino)) == ''


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_ocr_cai_para_ingles_quando_o_pacote_portugues_falta(tmp_path, monkeypatch):
    """Sem o por.traineddata, o OCR não pode falhar — cai para lang='eng'."""
    destino = _cria_imagem(tmp_path)

    def _so_ingles(img, lang=None, timeout=None, **k):
        if lang != 'eng':
            raise RuntimeError('por.traineddata ausente')
        return 'Approval flow'

    monkeypatch.setattr(toca.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: 'tesseract-falso')
    monkeypatch.setattr(toca.pytesseract, 'image_to_string', _so_ingles)

    assert 'Approval flow' in toca._itoca_extract_text_from_file(str(destino))
