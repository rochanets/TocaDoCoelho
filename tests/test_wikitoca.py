import html
import io
import sqlite3
import time

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


def _espera_task(client, task_id, timeout=15.0, esperar_erro=False):
    """Faz polling em /api/tasks/<id> até a task terminar.

    Por padrão exige status == 'done': se a task terminar em 'error', o teste
    falha aqui com a mensagem completa da task, em vez de seguir e falhar
    depois num assert de conteúdo com uma mensagem confusa. Passe
    `esperar_erro=True` nos poucos testes em que o erro é o resultado esperado.
    """
    limite = time.time() + timeout
    while time.time() < limite:
        payload = client.get(f'/api/tasks/{task_id}').get_json()
        if payload.get('status') in ('done', 'error'):
            if not esperar_erro:
                assert payload.get('status') == 'done', payload
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


def _extracted_text(doc_id):
    """Lê extracted_text direto do banco — a listagem HTTP não traz mais essa
    coluna (ver _WIKI_DOC_LIST_COLUMNS em routes/wikitoca.py), de propósito."""
    conn = toca.get_db()
    row = conn.execute('SELECT extracted_text FROM wiki_documents WHERE id=?', (doc_id,)).fetchone()
    conn.close()
    return row[0] if row else None


def _espera_reindex_lock_livre(timeout=5.0):
    """Espera o lock de reindexação concorrente (_wiki_reindex_lock) ficar livre.

    Entre a task de reindex virar 'done' (visível via polling) e a thread
    efetivamente liberar o lock há uma janela mínima (o release acontece
    alguns bytecodes depois do último _bg_task_set). Testes que disparam
    duas reindexações em sequência esperam aqui para não flakar pegando
    'already_running' por essa corrida — não é o que M2 está testando.
    """
    limite = time.time() + timeout
    while toca._wiki_reindex_lock.locked() and time.time() < limite:
        time.sleep(0.02)


def test_upload_de_documento_indexa_o_texto(client):
    payload = _sobe_documento(client)
    assert payload['task_id']
    assert payload['documents'][0]['extract_status'] == 'pending'
    doc_id = payload['documents'][0]['id']

    _espera_task(client, payload['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    # Listagem não traz mais o texto extraído — DOCX/XLSX não têm teto de
    # tamanho na extração, e essa rota é chamada a cada troca para a aba.
    assert 'extracted_text' not in doc
    assert 'cinco dias uteis' in (_extracted_text(doc_id) or '')


def test_documento_sem_texto_vira_empty(client):
    """Um arquivo válido mas sem nenhum texto extraível vira extract_status
    'empty' — diferente de 'error', reservado para quando algo deu errado
    de verdade (arquivo sumido, biblioteca ausente, extração explodiu)."""
    payload = _sobe_documento(client, texto='')
    doc_id = payload['documents'][0]['id']

    _espera_task(client, payload['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'empty'
    assert not (_extracted_text(doc_id) or '').strip()


def test_arquivo_sumido_do_disco_vira_error(client):
    """Se o arquivo já não existir mais no disco quando a indexação roda, o
    resultado tem que ser 'error' — não 'empty', que sugeriria "documento sem
    texto" quando na verdade o arquivo nem existe mais e nenhuma ação de UI
    recupera isso sozinha."""
    payload = _sobe_documento(client)
    doc_id = payload['documents'][0]['id']
    file_name = payload['documents'][0]['file_name']
    _espera_task(client, payload['task_id'])

    file_path = toca.WIKI_UPLOAD_DIR / file_name
    file_path.unlink()

    status = toca._wiki_index_document('wiki_documents', doc_id, file_path)

    assert status == 'error'
    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'error'
    assert not (_extracted_text(doc_id) or '')


def test_import_zip_indexa_documento_reimportado(client, db_path):
    """Documento apagado, reimportado via .zip, precisa terminar indexado —
    sem isso ele fica com extract_status NULL para sempre (selo 'Indexando...'
    que nunca sai do lugar, e ausente da busca por conteúdo da Task 4).

    O .zip usado aqui é o round-trip real de GET /export-zip, não um formato
    remontado à mão: se o formato de exportação mudar, este teste quebra
    junto com o comportamento real, em vez de continuar verde sozinho.
    """
    payload = _sobe_documento(client)
    _espera_task(client, payload['task_id'])
    doc_id = payload['documents'][0]['id']

    export_resp = client.get('/api/wikitoca/documents/export-zip')
    assert export_resp.status_code == 200
    zip_bytes = export_resp.data

    del_resp = client.delete(f'/api/wikitoca/documents/{doc_id}')
    assert del_resp.status_code == 200, del_resp.get_json()

    resp = client.post('/api/wikitoca/documents/import-zip',
                       data={'file': (io.BytesIO(zip_bytes), 'wikitoca-documentos.zip')},
                       content_type='multipart/form-data')
    assert resp.status_code == 201, resp.get_json()
    import_payload = resp.get_json()
    assert import_payload['imported'] == 1
    assert import_payload['task_id']

    _espera_task(client, import_payload['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (_extracted_text(doc['id']) or '')


def test_reindex_processa_documentos_sem_texto(client, db_path):
    payload = _sobe_documento(client)
    _espera_task(client, payload['task_id'])
    doc_id = payload['documents'][0]['id']

    conn = toca.get_db()
    conn.execute("UPDATE wiki_documents SET extracted_text=NULL, extract_status=NULL")
    conn.commit()
    conn.close()

    resp = client.post('/api/wikitoca/documents/reindex', json={})
    assert resp.status_code == 202, resp.get_json()
    _espera_task(client, resp.get_json()['task_id'])

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (_extracted_text(doc_id) or '')


def test_reindex_com_lista_vazia_termina_sem_erro(client, db_path):
    """Reindexar uma base sem nenhum documento não pode travar nem propagar
    exceção — a task tem que terminar 'done' com indexed=0/total=0, sem a UI
    da Task 11 precisar de defensiva para um shape de resultado diferente."""
    resp = client.post('/api/wikitoca/documents/reindex', json={})
    assert resp.status_code == 202, resp.get_json()
    payload = resp.get_json()
    assert payload['total'] == 0

    task = _espera_task(client, payload['task_id'])
    assert task['result'] == {'indexed': 0, 'total': 0}


def test_reindex_force_reprocessa_documento_ja_ok(client, db_path):
    """Sem `force`, um documento já 'ok' não entra no backfill (o backfill é só
    para quem ficou para trás). Com `force: true`, todo mundo é reprocessado."""
    payload = _sobe_documento(client)
    _espera_task(client, payload['task_id'])
    doc_id = payload['documents'][0]['id']

    resp_sem_force = client.post('/api/wikitoca/documents/reindex', json={})
    assert resp_sem_force.status_code == 202, resp_sem_force.get_json()
    sem_force_payload = resp_sem_force.get_json()
    assert sem_force_payload['total'] == 0
    _espera_task(client, sem_force_payload['task_id'])
    _espera_reindex_lock_livre()

    resp_force = client.post('/api/wikitoca/documents/reindex', json={'force': True})
    assert resp_force.status_code == 202, resp_force.get_json()
    force_payload = resp_force.get_json()
    assert force_payload['total'] == 1
    task = _espera_task(client, force_payload['task_id'])
    assert task['result'] == {'indexed': 1, 'total': 1}

    doc = client.get('/api/wikitoca/documents').get_json()[0]
    assert doc['extract_status'] == 'ok'
    assert 'cinco dias uteis' in (_extracted_text(doc_id) or '')


def test_busca_de_documentos_casa_no_conteudo_e_devolve_snippet(client):
    payload = _sobe_documento(client, nome='manual.docx',
                              texto='O prazo de aprovacao do contrato e de cinco dias uteis.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=cinco dias').get_json()

    assert len(rows) == 1
    assert '<mark>cinco dias</mark>' in rows[0]['snippet']


def test_busca_de_documentos_ignora_acento_e_caixa(client):
    """Nome de arquivo neutro de propósito: se o nome contivesse 'politica',
    `em_nome` bateria sozinho e o teste passaria mesmo com a busca por
    conteúdo completamente quebrada, sem afirmar nada sobre o `snippet`."""
    payload = _sobe_documento(client, nome='arquivo-x.docx',
                              texto='Politica de reembolso para viagens internacionais.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=POLÍTICA').get_json()

    assert len(rows) == 1
    assert '<mark>Politica</mark>' in rows[0]['snippet']


def test_busca_nao_devolve_o_texto_extraido_na_resposta(client):
    """A Task 3 já trava essa invariante na listagem SEM busca (a coluna nem
    entra no SELECT nesse caminho). Aqui é o caminho perigoso: COM `q`, a
    coluna é lida do banco e a única proteção é o `r.pop('extracted_text',
    None)` -- sem esse teste, apagar o pop deixa tudo verde e a busca passa a
    devolver o conteúdo integral de cada documento."""
    payload = _sobe_documento(client, texto='Prazo de cinco dias uteis')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert rows and 'extracted_text' not in rows[0]


def test_filtro_por_tipo_de_arquivo(client):
    payload = _sobe_documento(client, nome='manual.docx', texto='Conteudo qualquer')
    _espera_task(client, payload['task_id'])

    assert len(client.get('/api/wikitoca/documents?ext=word').get_json()) == 1
    assert client.get('/api/wikitoca/documents?ext=pdf').get_json() == []


@pytest.mark.parametrize('nome, texto, termo_busca, termo_destacado', [
    # Tag de script clássica.
    ('script.docx', 'Antes <script>alert(1)</script> depois do trecho perigoso.',
     'alert', 'alert'),
    # Atributo de evento num elemento sem fechamento explícito de tag.
    ('img.docx', 'Clique aqui: <img src=x onerror=alert(1)> para testar.',
     'onerror', 'onerror'),
    # Aspas simples e duplas -- html.escape com quote=True (padrão) escapa as duas.
    ('aspas.docx', 'Ela disse: "cinco dias" ou \'cinco dias\' uteis, tanto faz.',
     "'cinco dias'", "'cinco dias'"),
    # O próprio texto "<mark>" aparece literalmente dentro do documento --
    # tem que ser escapado igual a qualquer outra tag, mesmo coincidindo com
    # a tag que a busca insere.
    ('mark-literal.docx', 'O manual usa <mark>negrito</mark> como convencao de estilo.',
     'mark', 'mark'),
    # O termo de busca em si contém HTML.
    ('termo-com-html.docx', 'Config: <b>importante</b> revisar antes de aprovar.',
     '<b>', '<b>'),
])
def test_busca_escapa_conteudo_malicioso_no_snippet(client, nome, texto, termo_busca, termo_destacado):
    """O snippet é a única string HTML que a API devolve, e a Task 11 vai
    injetá-lo sem escapar de novo -- é a invariante mais crítica desta task.
    Fora do próprio `<mark>` que a busca insere, nenhum '<' ou '>' cru pode
    sobrar no snippet, não importa o que o documento (ou o termo buscado)
    contenha."""
    payload = _sobe_documento(client, nome=nome, texto=texto)
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents', query_string={'q': termo_busca}).get_json()

    assert len(rows) == 1
    snippet = rows[0]['snippet']
    marcado = f'<mark>{html.escape(termo_destacado)}</mark>'
    assert marcado in snippet
    resto = snippet.replace(marcado, '')
    assert '<' not in resto and '>' not in resto


def test_snippet_com_ligadura_antes_do_termo_nao_desloca_o_destaque(client):
    """NFKD e decomposicao de COMPATIBILIDADE, nao so de acentos: a ligadura
    'ﬁ' (U+FB01), comum em texto extraido de PDF, normaliza para 2 caracteres
    ('fi'). Se _wiki_snippet usar a posicao achada no texto normalizado para
    fatiar o texto original sem corrigir esse deslocamento, o <mark> cai
    caracteres a frente do termo real."""
    payload = _sobe_documento(
        client, nome='config.docx',
        texto='A conﬁguração define o prazo de cinco dias.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert len(rows) == 1
    assert '<mark>prazo</mark>' in rows[0]['snippet']


def test_snippet_com_acento_antes_do_termo_continua_correto(client):
    """Acento (NFKD decompoe em letra base + combining mark, que e removida)
    preserva o tamanho do texto -- esse caso já funcionava e não pode
    regredir com a correção do deslocamento por ligadura/compatibilidade."""
    payload = _sobe_documento(
        client, nome='aprovacao.docx',
        texto='A situação está resolvida: o prazo é de cinco dias.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert len(rows) == 1
    assert '<mark>prazo</mark>' in rows[0]['snippet']


def test_snippet_com_termo_no_final_do_texto(client):
    """Exercita a borda do índice final: quando o termo casado termina no
    último caractere do texto, o índice de fim não pode estourar a lista de
    índices do mapa normalizado -> original."""
    payload = _sobe_documento(
        client, nome='final.docx',
        texto='Documento sem nenhuma observacao alem do prazo')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert len(rows) == 1
    assert '<mark>prazo</mark>' in rows[0]['snippet']


def test_snippet_com_termo_que_normaliza_para_vazio_nao_quebra():
    """Termo só com caracteres combinantes normaliza para '' — `find('')` daria 0
    e o mapa de índices seria acessado fora do range, virando 500 na busca."""
    assert toca._wiki_snippet('qualquer texto aqui', '́') == ''
    assert toca._wiki_snippet('́́', '́') == ''


def test_wiki_norm_e_wiki_norm_indexado_produzem_a_mesma_string_normalizada():
    """_wiki_norm compara o termo, _wiki_norm_indexado mapeia o texto -- se as
    duas divergissem em algum caractere, a posição achada por uma não bateria
    mais com o texto mapeado pela outra e o casamento (ou o destaque) sairia
    errado. Cobre acento, ligadura, fração, CJK de largura completa e
    caracteres combinantes -- a mesma família de casos que já quebrou o
    destaque uma vez (ver commit da correção de ligadura)."""
    amostras = [
        'Texto simples em ASCII puro.',
        'Acentuação: ação, café, õ, ü, à.',
        'Ligaduras: eﬁcio (ex.: escritório com ligaduras fi/fl).',
        'Frações: 1½ ¼ ¾.',
        'CJK largura completa: ＡＢＣ １２３.',
        'Combinantes: e\u0301 a\u0300 o\u0302 (acento combinado).',
        'Formatação invisível: pra\u200bzo e pra\u00adzo.',
        'Mix tudo: ﬁnal\u200bmente ½ café ＡＢ\u0301.',
    ]
    for texto in amostras:
        normal = toca._wiki_norm(texto)
        indexado, indices = toca._wiki_norm_indexado(texto)
        assert normal == indexado, texto
        assert len(indexado) == len(indices)


def test_snippet_ignora_espaco_de_largura_zero_no_meio_do_termo(client):
    """U+200B (espaço de largura zero) aparece de verdade em texto extraído
    de PDF com quebra automática de linha -- mesma família do problema de
    ligadura já corrigido: sem ignorá-lo na normalização, um caractere
    invisível no meio da palavra quebra o casamento por completo."""
    payload = _sobe_documento(
        client, nome='zwsp.docx',
        texto='O documento define o pra\u200bzo de entrega, que e de cinco dias.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert len(rows) == 1
    assert '<mark>pra\u200bzo</mark>' in rows[0]['snippet']


def test_snippet_ignora_hifen_suave_no_meio_do_termo(client):
    """U+00AD (hífen suave) marca onde uma palavra PODE ser hifenizada e é
    comum em texto extraído de PDF com hifenização -- mesmo raciocínio do
    espaço de largura zero acima."""
    payload = _sobe_documento(
        client, nome='hifen-suave.docx',
        texto='O documento define o pra\u00adzo de entrega, que e de cinco dias.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=prazo').get_json()

    assert len(rows) == 1
    assert '<mark>pra\u00adzo</mark>' in rows[0]['snippet']


def test_snippet_limita_o_tamanho_do_match_mesmo_com_muitos_combinantes():
    """Caracteres combinantes entre dois caracteres normalizados adjacentes
    somem do texto normalizado mas continuam ocupando espaço no texto
    original -- um acúmulo patológico deles (algo que acontece de verdade em
    extração malformada de PDF, não depende do usuário) faz o trecho casado
    no texto ORIGINAL ficar enorme mesmo para um termo de busca curto. Sem o
    teto em `janela`, o <mark> -- que vai inteiro para innerHTML -- fica do
    tamanho desse acúmulo."""
    texto = 'p' + '\u0301' * 20000 + 'razo e o resto do texto aqui.'
    snippet = toca._wiki_snippet(texto, 'prazo')
    assert '<mark>' in snippet
    assert len(snippet) < 1000


def test_busca_com_termo_gigantesco_nao_trava_a_rota(client):
    """O termo de busca é truncado antes de usar: sem isso, um `q` de dezenas
    de milhares de caracteres tornaria o custo de `_wiki_norm(texto)` sobre
    cada documento proporcional a esse tamanho, a cada request."""
    payload = _sobe_documento(client, texto='Prazo de cinco dias uteis')
    _espera_task(client, payload['task_id'])

    resp = client.get('/api/wikitoca/documents', query_string={'q': 'a' * 50000})

    assert resp.status_code == 200
    assert resp.get_json() == []
