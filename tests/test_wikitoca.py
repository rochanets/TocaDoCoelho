import io
import json
import sqlite3
import time
import zipfile

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


def _espera_task(client, task_id, timeout=15.0):
    limite = time.time() + timeout
    while time.time() < limite:
        payload = client.get(f'/api/tasks/{task_id}').get_json()
        if payload.get('status') in ('done', 'error'):
            return payload
        time.sleep(0.1)
    raise AssertionError(f'Task {task_id} não terminou em {timeout}s')


def _sobe_documento(client, nome='manual.docx', texto='Prazo de aprovacao e de cinco dias uteis'):
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(texto)
    doc.save(buf)
    buf.seek(0)
    resp = client.post('/api/wikitoca/documents',
                       data={'files': (buf, nome)},
                       content_type='multipart/form-data')
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def test_upload_de_documento_indexa_o_texto(client):
    payload = _sobe_documento(client)
    assert payload['task_id']
    assert payload['documents'][0]['extract_status'] == 'pending'

    _espera_task(client, payload['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (doc['extracted_text'] or '')


def test_import_zip_indexa_documento_reimportado(client, db_path):
    """Documento apagado, reimportado via .zip, precisa terminar indexado —
    sem isso ele fica com extract_status NULL para sempre (selo 'Indexando...'
    que nunca sai do lugar, e ausente da busca por conteúdo da Task 4)."""
    payload = _sobe_documento(client)
    _espera_task(client, payload['task_id'])
    doc = client.get('/api/wikitoca/documents').get_json()[0]
    file_bytes = (toca.WIKI_UPLOAD_DIR / doc['file_name']).read_bytes()

    del_resp = client.delete(f"/api/wikitoca/documents/{doc['id']}")
    assert del_resp.status_code == 200, del_resp.get_json()

    manifest = [{
        'title': doc['title'],
        'file_name': doc['file_name'],
        'original_name': doc['original_name'],
        'file_ext': doc['file_ext'],
    }]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
        zf.writestr(f"files/{doc['file_name']}", file_bytes)
    buf.seek(0)

    resp = client.post('/api/wikitoca/documents/import-zip',
                       data={'file': (buf, 'wikitoca-documentos.zip')},
                       content_type='multipart/form-data')
    assert resp.status_code == 201, resp.get_json()
    import_payload = resp.get_json()
    assert import_payload['imported'] == 1
    assert import_payload['task_id']

    _espera_task(client, import_payload['task_id'])

    doc2 = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc2['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (doc2['extracted_text'] or '')


def test_reindex_processa_documentos_sem_texto(client, db_path):
    payload = _sobe_documento(client)
    _espera_task(client, payload['task_id'])

    conn = toca.get_db()
    conn.execute("UPDATE wiki_documents SET extracted_text=NULL, extract_status=NULL")
    conn.commit()
    conn.close()

    resp = client.post('/api/wikitoca/documents/reindex', json={})
    assert resp.status_code == 202, resp.get_json()
    _espera_task(client, resp.get_json()['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (doc['extracted_text'] or '')
