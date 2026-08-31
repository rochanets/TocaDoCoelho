# WikiToca — Submódulos + Capacitação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar o WikiToca em três submódulos no padrão AutoToca (Conhecimentos, Documentos, Capacitação), adicionar busca por conteúdo nos Documentos e criar o submódulo Capacitação — instâncias tipo NotebookLM com documentos próprios e chat com IA em cascata (documentos → base WikiToca → web).

**Architecture:** Backend Flask em `routes/wikitoca.py` (executado no namespace de `app.py` por `_load_route_modules()`), tabelas novas via migração numerada 19 em `SCHEMA_MIGRATIONS`, extração de texto reaproveitando `_itoca_extract_text_from_file()`, operações longas em thread com `_bg_task_set` + polling em `GET /api/tasks/<task_id>`, e LLM sempre via `_llm_prompt()` (SAI primeiro, OpenRouter fallback). Frontend em arquivo novo `public/js/wikitoca.js`, extraído de `itoca-autotoca.js`.

**Tech Stack:** Python 3 + Flask + SQLite; pytest; Vanilla JS/HTML (SPA em `public/index.html` + `public/js/*.js`); `pdfplumber`, `python-docx`, `openpyxl`, `pytesseract` (todas já presentes — nenhuma dependência nova).

**Spec:** `docs/superpowers/specs/2026-08-28-wikitoca-submodulos-capacitacao-design.md`

**Como rodar os testes:** `pytest` a partir da raiz do repositório (o `tests/conftest.py` insere a raiz no `sys.path`).

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `app.py` | Constantes de upload, flags de dependência opcional, `_itoca_extract_text_from_file`, `SCHEMA_MIGRATIONS` | Modificar |
| `routes/wikitoca.py` | Rotas de Conhecimentos e Documentos + helpers de indexação e busca | Modificar |
| `routes/wikitoca_capacitacao.py` | Ranking de trechos, rotas da Capacitação e cascata de resposta | Criar (Task 5) |
| `public/index.html` | Markup dos 3 submódulos e da tela de Capacitação; `<script src="/js/wikitoca.js">` | Modificar |
| `public/css/app.css` | Classes `.wiki-sub-*`, `.cap-*` e o responsivo da gaveta | Modificar |
| `public/js/wikitoca.js` | **Todo** o JS do WikiToca (3 submódulos) | Criar |
| `public/js/itoca-autotoca.js` | Perde o bloco WikiToca (linhas 3914–4324) e as variáveis `wikiEntries`/`wikiDocuments` | Modificar |
| `public/js/core.js` | `switchTab` continua chamando `loadWikiTocaData()`; perde `wikiEntriesSortOrder` | Modificar |
| `tests/conftest.py` | Isolar `WIKI_UPLOAD_DIR` e `WIKI_TRAINING_UPLOAD_DIR` nos testes | Modificar |
| `tests/test_wikitoca.py` | Testes de migração, extração, ranking, busca e cascata | Criar |

---

## Task 1: Migração 19 — schema de busca e de Capacitação

**Files:**
- Modify: `app.py` (constantes de upload perto da linha 198; callable de migração antes de `SCHEMA_MIGRATIONS` na linha 1311; entrada nova no fim da lista, linha ~1527)
- Modify: `tests/conftest.py`
- Test: `tests/test_wikitoca.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_wikitoca.py`:

```python
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
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -v`
Expected: FAIL nos três testes — `wiki_training_sessions` ausente e `extracted_text` não está em `PRAGMA table_info(wiki_documents)`.

- [ ] **Step 3: Adicionar as constantes de upload**

Em `app.py`, logo depois da linha 199 (`WIKI_UPLOAD_DIR.mkdir(...)`):

```python
WIKI_TRAINING_UPLOAD_DIR = WIKI_UPLOAD_DIR / 'capacitacao'
WIKI_TRAINING_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Adicionar o callable da migração**

Em `app.py`, logo antes de `# ---------------------------------------------------------------------------` na linha 1310 (ou seja, depois de `_iata_add_opportunity_match_confidence_column`):

```python
def _wiki_add_document_extract_columns(conn):
    """Colunas de cache do texto extraído dos documentos do WikiToca, usadas
    pela busca por conteúdo. ALTER TABLE condicional, no mesmo padrão de
    `_iata_add_record_columns` — tolerante à tabela ainda não existir."""
    c = conn.cursor()
    existentes = {r[1] for r in c.execute('PRAGMA table_info(wiki_documents)')}
    if not existentes:
        return
    if 'extracted_text' not in existentes:
        c.execute('ALTER TABLE wiki_documents ADD COLUMN extracted_text TEXT')
    if 'extracted_at' not in existentes:
        c.execute('ALTER TABLE wiki_documents ADD COLUMN extracted_at TIMESTAMP')
    if 'extract_status' not in existentes:
        c.execute('ALTER TABLE wiki_documents ADD COLUMN extract_status TEXT')
```

- [ ] **Step 5: Adicionar a entrada 19 em SCHEMA_MIGRATIONS**

Em `app.py`, após a entrada `(18, 'iata_opportunity_match_confidence', [...])` e antes do `]` que fecha a lista:

```python
    # WikiToca: busca por conteúdo nos Documentos + submódulo Capacitação.
    # 19 é o próximo número da linhagem `main` (que ia até 18). A linhagem
    # `Live` ocupa 20–32 no banco de produção do usuário; como o
    # _run_schema_migrations confere cada versão individualmente, a 19 roda
    # normalmente lá. Nada aqui pode nascer só dentro do init_db().
    (19, 'wikitoca_submodulos_capacitacao', [
        _wiki_add_document_extract_columns,
        '''CREATE TABLE IF NOT EXISTS wiki_training_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            title_source TEXT DEFAULT 'ai',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''',
        '''CREATE TABLE IF NOT EXISTS wiki_training_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_url TEXT NOT NULL,
            file_ext TEXT,
            file_size INTEGER,
            extracted_text TEXT,
            extract_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES wiki_training_sessions(id) ON DELETE CASCADE
        )''',
        '''CREATE TABLE IF NOT EXISTS wiki_training_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            source_kind TEXT,
            source_refs TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES wiki_training_sessions(id) ON DELETE CASCADE
        )''',
        'CREATE INDEX IF NOT EXISTS idx_wiki_training_docs_session ON wiki_training_documents(session_id)',
        'CREATE INDEX IF NOT EXISTS idx_wiki_training_msgs_session ON wiki_training_messages(session_id, created_at)',
    ]),
```

- [ ] **Step 6: Isolar os diretórios de upload do WikiToca nos testes**

Em `tests/conftest.py`, na tupla do fixture `_isola_diretorios_de_upload`, trocar:

```python
    for nome in ('UPLOAD_DIR', 'AUTOTOCA_UPLOAD_DIR', 'REEMBOLSOS_UPLOAD_DIR',
                 'ACCOUNT_UPLOAD_DIR'):
```

por:

```python
    for nome in ('UPLOAD_DIR', 'AUTOTOCA_UPLOAD_DIR', 'REEMBOLSOS_UPLOAD_DIR',
                 'ACCOUNT_UPLOAD_DIR', 'WIKI_UPLOAD_DIR', 'WIKI_TRAINING_UPLOAD_DIR'):
```

- [ ] **Step 7: Rodar os testes**

Run: `pytest tests/test_wikitoca.py tests/test_schema_migrations.py -v`
Expected: PASS em todos. `test_schema_migrations.py` continua passando (nenhuma tabela nova foi criada dentro do `init_db()`).

- [ ] **Step 8: Commit**

```bash
git add app.py tests/conftest.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): migracao 19 com colunas de extracao e tabelas de capacitacao"
```

---

## Task 2: Extração de texto de imagens (OCR)

**Files:**
- Modify: `app.py` (`_itoca_extract_text_from_file` na linha 4701; `ALLOWED_WIKI_TRAINING_EXTENSIONS` perto da linha 10514)
- Test: `tests/test_wikitoca.py`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

Acrescentar `import pytest` junto dos imports do topo do arquivo (não no meio), e ao fim:

```python
_SEM_OCR = not (getattr(toca, 'PYTESSERACT_AVAILABLE', False) and getattr(toca, 'PIL_AVAILABLE', False))


def _cria_png(tmp_path):
    from PIL import Image
    destino = tmp_path / 'captura.png'
    Image.new('RGB', (40, 20), color='white').save(str(destino))
    return destino


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_extrai_texto_de_imagem_via_ocr(tmp_path, monkeypatch):
    """Com o Tesseract disponível, o texto lido da imagem entra na extração.

    Este é o teste que dirige o TDD: sem o ramo de imagem a função cai fora de
    todos os `elif` e devolve '' — não porque o OCR falhou, mas porque o formato
    nem é tratado.
    """
    destino = _cria_png(tmp_path)
    # setattr via monkeypatch garante a restauração mesmo com o código de
    # produção reatribuindo tesseract_cmd durante a chamada.
    monkeypatch.setattr(toca.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: 'tesseract-falso')
    monkeypatch.setattr(toca.pytesseract, 'image_to_string', lambda *a, **k: 'Fluxo de aprovacao')

    assert 'Fluxo de aprovacao' in toca._itoca_extract_text_from_file(str(destino))


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_extrai_texto_de_imagem_sem_tesseract_retorna_vazio(tmp_path, monkeypatch):
    """Sem o binário do Tesseract a extração não pode explodir — devolve vazio."""
    destino = _cria_png(tmp_path)
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: None)

    assert toca._itoca_extract_text_from_file(str(destino)) == ''


@pytest.mark.skipif(_SEM_OCR, reason='pytesseract/Pillow indisponíveis')
def test_ocr_de_imagem_que_falha_nao_propaga_excecao(tmp_path, monkeypatch):
    """Imagem corrompida/OCR quebrado vira string vazia, não exceção — quem chama
    marca extract_status='error' pelo resultado, sem derrubar o lote de upload."""
    destino = _cria_png(tmp_path)

    def _explode(*a, **k):
        raise RuntimeError('tesseract morreu')

    monkeypatch.setattr(toca.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract')
    monkeypatch.setattr(toca, '_itoca_find_tesseract_cmd', lambda: 'tesseract-falso')
    monkeypatch.setattr(toca.pytesseract, 'image_to_string', _explode)

    assert toca._itoca_extract_text_from_file(str(destino)) == ''
```

> **Por que o teste "sem tesseract" sozinho não serve de driver de TDD:** hoje a função devolve `''` para qualquer extensão sem ramo (`result_text = '\n'.join(text_parts)` com a lista vazia, `app.py:4894`), então ele já passa antes da implementação. É `test_extrai_texto_de_imagem_via_ocr` que falha de verdade. Os outros dois entram como guarda de regressão dos caminhos de erro.

- [ ] **Step 2: Rodar os testes para confirmar que o driver falha**

Run: `pytest tests/test_wikitoca.py -k imagem -v`
Expected: `test_extrai_texto_de_imagem_via_ocr` FALHA (`assert 'Fluxo de aprovacao' in ''`) — a função não tem ramo para `.png`. Os outros dois já passam; é esperado, eles guardam os caminhos de erro depois da implementação.

- [ ] **Step 3: Adicionar o ramo de imagem na extração**

Em `app.py`, dentro de `_itoca_extract_text_from_file`, inserir **antes** do ramo `elif ext == '.txt':`:

```python
        elif ext in ('.png', '.jpg', '.jpeg'):
            if PYTESSERACT_AVAILABLE and PIL_AVAILABLE:
                tess_cmd = _itoca_find_tesseract_cmd()
                if tess_cmd:
                    pytesseract.pytesseract.tesseract_cmd = tess_cmd
                    try:
                        img = PILImage.open(str(path))
                        try:
                            ocr_text = pytesseract.image_to_string(img, lang='por+eng')
                        except Exception:
                            ocr_text = pytesseract.image_to_string(img, lang='eng')
                        if ocr_text.strip():
                            text_parts.append(ocr_text.strip())
                    except Exception as e7:
                        logger.warning(f'[iToca] OCR de imagem falhou em {path.name}: {e7}')
                else:
                    logger.info(f'[iToca] Tesseract não encontrado — {path.name} ficará sem texto extraído. '
                                'Instale em https://github.com/UB-Mannheim/tesseract/wiki')
```

- [ ] **Step 4: Declarar as extensões aceitas na Capacitação**

Em `app.py`, logo depois de `ALLOWED_WIKI_EXTENSIONS = {'.pdf', '.xls', '.xlsx', '.doc', '.docx'}` (linha 10514):

```python
# A Capacitação aceita imagens (via OCR) além dos tipos de texto. `.doc` legado
# entra por consistência com o submódulo Documentos, mas o python-docx não o lê:
# nesse caso o documento fica com extract_status='empty', como já acontece hoje.
ALLOWED_WIKI_TRAINING_EXTENSIONS = {'.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg'}
```

- [ ] **Step 5: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -v`
Expected: PASS em todos.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): OCR de imagens na extracao de texto"
```

---

## Task 3: Indexação assíncrona dos documentos + endpoint de reindexação

**Files:**
- Modify: `routes/wikitoca.py` (helpers no topo do arquivo; `upload_wiki_documents` na linha 152; rota nova)
- Test: `tests/test_wikitoca.py`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
import io
import time


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
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k "indexa or reindex" -v`
Expected: FAIL — `KeyError: 'task_id'` no primeiro (o upload devolve uma lista, não um dict) e 404 no `POST /api/wikitoca/documents/reindex`.

- [ ] **Step 3: Adicionar os helpers de indexação**

Em `routes/wikitoca.py`, logo abaixo do cabeçalho de comentário do arquivo (antes da primeira `@app.route`):

```python
def _wiki_index_document(table, row_id, file_path):
    """Extrai o texto de um arquivo e grava no cache da linha indicada.
    `table` é 'wiki_documents' ou 'wiki_training_documents'.
    Nunca levanta: falha vira extract_status='error' para aparecer na UI."""
    status = 'error'
    texto = ''
    try:
        texto = _itoca_extract_text_from_file(str(file_path)) or ''
        status = 'ok' if texto.strip() else 'empty'
    except Exception as e:
        logger.warning(f'[WikiToca] Falha ao extrair texto de {file_path}: {e}')
    try:
        conn = get_db()
        c = conn.cursor()
        if table == 'wiki_documents':
            c.execute('UPDATE wiki_documents SET extracted_text=?, extract_status=?, '
                      'extracted_at=CURRENT_TIMESTAMP WHERE id=?', (texto, status, row_id))
        else:
            c.execute('UPDATE wiki_training_documents SET extracted_text=?, extract_status=? '
                      'WHERE id=?', (texto, status, row_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.exception(f'[WikiToca] Falha ao gravar texto extraído ({table} id={row_id}): {e}')
    return status


def _wiki_index_documents_async(task_id, doc_ids):
    """Indexa uma lista de wiki_documents em background, reportando progresso."""
    try:
        total = len(doc_ids)
        if not total:
            _bg_task_set(task_id, {'status': 'done', 'step': 'Nada a indexar.',
                                   'progress': 100, 'result': {'indexed': 0}})
            _bg_task_cleanup(task_id)
            return
        indexados = 0
        for pos, doc_id in enumerate(doc_ids, start=1):
            conn = get_db()
            row = dict_from_row(conn.execute(
                'SELECT file_name, original_name FROM wiki_documents WHERE id=?', (doc_id,)).fetchone())
            conn.close()
            if not row:
                continue
            nome = row.get('original_name') or row.get('file_name')
            _bg_task_set(task_id, {
                'step': f'Processando {pos} de {total} — {nome}',
                'progress': int(5 + (pos - 1) * 90 / total),
            })
            if _wiki_index_document('wiki_documents', doc_id, WIKI_UPLOAD_DIR / row['file_name']) == 'ok':
                indexados += 1
        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100,
                               'result': {'indexed': indexados, 'total': total}})
    except Exception as e:
        logger.exception(f'[WikiToca] _wiki_index_documents_async: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 100})
    finally:
        _bg_task_cleanup(task_id)
```

- [ ] **Step 4: Fazer o upload disparar a indexação**

Em `routes/wikitoca.py`, dentro de `upload_wiki_documents`, trocar o `INSERT` para gravar `extract_status='pending'` e trocar o `return` final. Substituir:

```python
            c.execute(
                '''INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, file_size,
                                              created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (doc_title, safe_name, original_name, file_url, ext, file_size)
            )
```

por:

```python
            c.execute(
                '''INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, file_size,
                                              extract_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                (doc_title, safe_name, original_name, file_url, ext, file_size)
            )
```

E substituir:

```python
        if not created:
            return api_error(400, 'WIKI_DOC_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, XLS, XLSX, DOC, DOCX.')
        return jsonify(created), 201
```

por:

```python
        if not created:
            return api_error(400, 'WIKI_DOC_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, XLS, XLSX, DOC, DOCX.')
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Indexando documentos...', 'progress': 5})
        threading.Thread(target=_wiki_index_documents_async,
                         args=(task_id, [d['id'] for d in created]), daemon=True).start()
        return jsonify({'documents': created, 'task_id': task_id}), 201
```

- [ ] **Step 5: Adicionar a rota de reindexação**

Em `routes/wikitoca.py`, logo depois de `upload_wiki_documents`:

```python
@app.route('/api/wikitoca/documents/reindex', methods=['POST'])
def reindex_wiki_documents():
    """Backfill do texto extraído dos documentos já existentes.
    Body opcional: {"force": true} para reprocessar também os já indexados."""
    logger.debug('[DEBUG] POST /api/wikitoca/documents/reindex chamado')
    try:
        force = bool((request.get_json(silent=True) or {}).get('force'))
        conn = get_db()
        c = conn.cursor()
        if force:
            c.execute('SELECT id FROM wiki_documents ORDER BY id')
        else:
            c.execute("SELECT id FROM wiki_documents "
                      "WHERE extract_status IS NULL OR extract_status IN ('pending', 'error') "
                      "ORDER BY id")
        doc_ids = [r[0] for r in c.fetchall()]
        conn.close()
        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(target=_wiki_index_documents_async, args=(task_id, doc_ids), daemon=True).start()
        logger.info(f'[WikiToca] Reindexação iniciada para {len(doc_ids)} documento(s)')
        return jsonify({'task_id': task_id, 'total': len(doc_ids)}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/documents/reindex: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOC_REINDEX_ERROR', 'Erro ao reindexar documentos.', details=str(e))
```

- [ ] **Step 6: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -v`
Expected: PASS em todos.

- [ ] **Step 7: Commit**

```bash
git add routes/wikitoca.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): indexacao assincrona de documentos e endpoint de reindexacao"
```

---

## Task 4: Busca por conteúdo no submódulo Documentos

**Files:**
- Modify: `routes/wikitoca.py` (`list_wiki_documents`, linha 125)
- Test: `tests/test_wikitoca.py`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
def test_busca_de_documentos_casa_no_conteudo_e_devolve_snippet(client):
    payload = _sobe_documento(client, nome='manual.docx',
                              texto='O prazo de aprovacao do contrato e de cinco dias uteis.')
    _espera_task(client, payload['task_id'])

    rows = client.get('/api/wikitoca/documents?q=cinco dias').get_json()

    assert len(rows) == 1
    assert '<mark>cinco dias</mark>' in rows[0]['snippet']


def test_busca_de_documentos_ignora_acento_e_caixa(client):
    payload = _sobe_documento(client, nome='politica.docx',
                              texto='Politica de reembolso para viagens internacionais.')
    _espera_task(client, payload['task_id'])

    assert len(client.get('/api/wikitoca/documents?q=POLÍTICA').get_json()) == 1


def test_filtro_por_tipo_de_arquivo(client):
    payload = _sobe_documento(client, nome='manual.docx', texto='Conteudo qualquer')
    _espera_task(client, payload['task_id'])

    assert len(client.get('/api/wikitoca/documents?ext=word').get_json()) == 1
    assert client.get('/api/wikitoca/documents?ext=pdf').get_json() == []
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k "busca or filtro" -v`
Expected: FAIL — a busca atual só olha `title`/`original_name`, então `?q=cinco dias` devolve lista vazia e `snippet` não existe; `?ext=pdf` devolve o documento .docx.

- [ ] **Step 3: Implementar a busca**

Em `routes/wikitoca.py`, substituir o corpo inteiro de `list_wiki_documents` por:

```python
_WIKI_EXT_FILTERS = {
    'pdf': ('.pdf',),
    'word': ('.doc', '.docx'),
    'excel': ('.xls', '.xlsx'),
}


def _wiki_norm(texto):
    """Minúsculas e sem acento, para casar 'POLÍTICA' com 'politica'."""
    base = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(ch for ch in base if not unicodedata.combining(ch)).lower()


def _wiki_snippet(texto, termo, janela=200):
    """Trecho em volta da primeira ocorrência do termo, com <mark> no termo.
    Tudo que veio do arquivo é escapado; só o <mark> é inserido por nós, em
    posição conhecida — é isso que permite o frontend renderizar sem escapar de
    novo. Devolve '' se o termo não aparecer no texto."""
    if not texto or not termo:
        return ''
    pos = _wiki_norm(texto).find(_wiki_norm(termo))
    if pos < 0:
        return ''
    ini = max(0, pos - janela // 2)
    fim = min(len(texto), pos + len(termo) + janela // 2)
    antes = html.escape(texto[ini:pos])
    match = html.escape(texto[pos:pos + len(termo)])
    depois = html.escape(texto[pos + len(termo):fim])
    prefixo = '…' if ini > 0 else ''
    sufixo = '…' if fim < len(texto) else ''
    return f'{prefixo}{antes}<mark>{match}</mark>{depois}{sufixo}'.replace('\n', ' ')


@app.route('/api/wikitoca/documents', methods=['GET'])
def list_wiki_documents():
    logger.debug('[DEBUG] GET /api/wikitoca/documents chamado')
    try:
        q = (request.args.get('q') or '').strip()
        ext_filtro = (request.args.get('ext') or '').strip().lower()
        conn = get_db()
        c = conn.cursor()
        # Sem busca, o texto extraído nem sai do banco: um DOCX/XLSX grande gera
        # dezenas de MB e esta rota é chamada a cada troca de aba. Só a busca
        # precisa do texto, e ainda assim ele não volta na resposta.
        colunas = _WIKI_DOC_LIST_COLUMNS + (', extracted_text' if q else '')
        c.execute(f'SELECT {colunas} FROM wiki_documents ORDER BY updated_at DESC')
        rows = [dict_from_row(r) for r in c.fetchall()]
        conn.close()

        if ext_filtro in _WIKI_EXT_FILTERS:
            aceitos = _WIKI_EXT_FILTERS[ext_filtro]
            rows = [r for r in rows if (r.get('file_ext') or '').lower() in aceitos]

        if q:
            alvo = _wiki_norm(q)
            filtrados = []
            for r in rows:
                em_nome = alvo in _wiki_norm(r.get('original_name')) or alvo in _wiki_norm(r.get('title'))
                snippet = _wiki_snippet(r.get('extracted_text'), q)
                if em_nome or snippet:
                    r['snippet'] = snippet
                    filtrados.append(r)
            rows = filtrados
        else:
            for r in rows:
                r['snippet'] = ''

        # O texto só foi buscado para calcular o snippet; a UI nunca usa o
        # conteúdo integral, então ele não volta na resposta.
        for r in rows:
            r.pop('extracted_text', None)

        logger.debug(f'[DEBUG] GET /api/wikitoca/documents retornando {len(rows)} documentos')
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_DOCS_LIST_ERROR', 'Erro ao listar documentos.', details=str(e))
```

> `_WIKI_DOC_LIST_COLUMNS` é a constante com a lista explícita de colunas
> **sem** `extracted_text`, criada na Task 3 ao substituir o `SELECT *`. Se o
> nome que ficou lá for outro, use o nome real — não recrie a constante.
>
> Os testes da Task 3 já leem o `extracted_text` direto do banco via
> `toca.get_db()`, não da listagem, então nenhum deles precisa de ajuste aqui.

- [ ] **Step 4: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add routes/wikitoca.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): busca por conteudo e filtro por tipo nos documentos"
```

---

## Task 5: Ranking de trechos por relevância

**Files:**
- Create: `routes/wikitoca_capacitacao.py`
- Modify: `app.py` (`ROUTE_MODULES`, linha ~12618)
- Test: `tests/test_wikitoca.py`

> **Esta task cria o arquivo de rotas da Capacitação.** O ranking de trechos só é
> consumido pela cascata de resposta (Task 8), então pertence ao domínio da
> Capacitação, não ao de Documentos. `routes/wikitoca.py` já está em 764 linhas com
> Conhecimentos + Documentos, e as Tasks 6, 7 e 8 somam plausivelmente 400–800
> linhas de um domínio genuinamente diferente — juntar tudo daria um arquivo de
> 1200–1500 linhas com dois submódulos não relacionados.
>
> O custo de separar é quase nulo: `_load_route_modules()` (`app.py:12623`) só faz
> `exec(code, globals())` para cada nome de `ROUTE_MODULES`, **na ordem da lista**.
> Acrescente `'wikitoca_capacitacao'` **depois** de `'wikitoca'` — a ordem garante
> que `_wiki_norm`, `_wiki_index_document` e `_wiki_track_thread` já estejam no
> `globals()` compartilhado quando este arquivo for executado. Sem blueprints, sem
> imports, sem mudança de URL.
>
> O cabeçalho do arquivo novo deve seguir o de `routes/wikitoca.py`, explicando que
> ele roda no namespace de `app.py`. As Tasks 6, 7 e 8 continuam neste arquivo.

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
def test_rank_chunks_prioriza_o_trecho_com_os_termos(db_path):
    fontes = [
        {'label': 'manual.pdf', 'text': 'Capitulo 1. Sobre ferias e recesso da empresa.'},
        {'label': 'politica.pdf', 'text': 'O prazo de aprovacao do contrato e de cinco dias uteis.'},
    ]
    melhores = toca._wiki_rank_chunks(fontes, 'qual o prazo de aprovacao do contrato?', top_n=1)

    assert len(melhores) == 1
    assert melhores[0]['label'] == 'politica.pdf'
    assert 'cinco dias uteis' in melhores[0]['chunk']


def test_rank_chunks_devolve_vazio_quando_nada_e_relevante(db_path):
    fontes = [{'label': 'manual.pdf', 'text': 'Sobre ferias e recesso da empresa.'}]
    assert toca._wiki_rank_chunks(fontes, 'qual a cotacao do dolar hoje?', top_n=3) == []


def test_rank_chunks_ignora_fontes_sem_texto(db_path):
    fontes = [{'label': 'vazio.png', 'text': ''}, {'label': 'nulo.pdf', 'text': None}]
    assert toca._wiki_rank_chunks(fontes, 'prazo de aprovacao', top_n=3) == []


def test_rank_chunks_aceita_fonte_unica_com_um_termo_casado(db_path):
    """Guarda-corpo da fórmula: com poucos blocos o bônus de raridade é pequeno,
    então o piso de 1 ponto por termo é o que mantém o trecho certo acima do
    limiar. Sem ele, a cascata pulava os documentos e ia direto para a web."""
    fontes = [{'label': 'politica.pdf', 'text': 'O prazo de rescisao do contrato e de trinta dias.'}]
    melhores = toca._wiki_rank_chunks(fontes, 'qual o prazo de rescisao?', top_n=3)
    assert len(melhores) == 1
    assert melhores[0]['score'] >= 1.0
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k rank_chunks -v`
Expected: FAIL com `AttributeError: module 'app' has no attribute '_wiki_rank_chunks'`.

- [ ] **Step 3: Implementar o ranking**

Em `routes/wikitoca_capacitacao.py` (arquivo novo), depois do cabeçalho de comentário:

```python
# Palavras curtas e conectivos não distinguem trecho relevante de irrelevante.
_WIKI_STOPWORDS = {
    'a', 'ao', 'aos', 'as', 'com', 'como', 'da', 'das', 'de', 'do', 'dos', 'e', 'em',
    'na', 'nas', 'no', 'nos', 'o', 'os', 'ou', 'para', 'pela', 'pelo', 'por', 'qual',
    'quais', 'que', 'quem', 'se', 'sobre', 'um', 'uma', 'the', 'of', 'and', 'to',
}

WIKI_CHUNK_SIZE = 1200
WIKI_CHUNK_OVERLAP = 150
WIKI_MIN_CHUNK_SCORE = 1.0


def _wiki_tokens(texto):
    """Termos significativos de um texto, normalizados.

    `_wiki_norm` (definida em routes/wikitoca.py, disponível aqui pelo namespace
    compartilhado) já derruba acento, caixa e caracteres de formatação, então o
    split por `[^a-z0-9]+` basta.
    """
    brutos = re.split(r'[^a-z0-9]+', _wiki_norm(texto))
    return [t for t in brutos if len(t) >= 3 and t not in _WIKI_STOPWORDS]


def _wiki_split_chunks(texto):
    """Quebra o texto em blocos com sobreposição, para não cortar uma frase ao meio."""
    texto = (texto or '').strip()
    if not texto:
        return []
    if len(texto) <= WIKI_CHUNK_SIZE:
        return [texto]
    blocos = []
    passo = WIKI_CHUNK_SIZE - WIKI_CHUNK_OVERLAP
    for ini in range(0, len(texto), passo):
        bloco = texto[ini:ini + WIKI_CHUNK_SIZE].strip()
        if bloco:
            blocos.append(bloco)
    return blocos


def _wiki_rank_chunks(sources, question, top_n=6, min_score=WIKI_MIN_CHUNK_SCORE):
    """Seleciona os trechos mais relevantes para a pergunta.

    `sources` é uma lista de {'label': str, 'text': str}. Cada termo distinto da
    pergunta presente no bloco vale 1 ponto, mais um bônus pela raridade do termo
    no conjunto (um termo presente em quase todo bloco distingue pouco). O piso
    de 1 ponto por termo é o que faz `min_score=1.0` significar "casou pelo menos
    um termo significativo": só com o bônus de raridade, um conjunto de poucos
    blocos daria pontuação abaixo de 1 mesmo para o bloco certo.

    Devolve [{'label', 'chunk', 'score'}] ordenado, ou [] se nenhum bloco atingir
    `min_score` — o chamador usa isso para pular o passo da cascata sem gastar
    chamada de LLM.
    """
    termos = set(_wiki_tokens(question))
    if not termos:
        return []

    blocos = []
    for src in sources or []:
        label = (src.get('label') or 'documento')
        for chunk in _wiki_split_chunks(src.get('text')):
            blocos.append({'label': label, 'chunk': chunk, 'tokens': set(_wiki_tokens(chunk))})
    if not blocos:
        return []

    total = len(blocos)
    freq = {t: sum(1 for b in blocos if t in b['tokens']) for t in termos}

    import math
    pontuados = []
    for b in blocos:
        score = 0.0
        for t in termos:
            if t in b['tokens']:
                # 1 ponto por termo casado + bônus de raridade. Os +1 evitam
                # divisão por zero e amortecem termos onipresentes.
                score += 1.0 + math.log(1 + total / (1 + freq[t]))
        if score >= min_score:
            pontuados.append({'label': b['label'], 'chunk': b['chunk'], 'score': round(score, 4)})

    pontuados.sort(key=lambda x: x['score'], reverse=True)
    return pontuados[:top_n]
```

- [ ] **Step 4: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -k rank_chunks -v`
Expected: PASS nos quatro.

- [ ] **Step 5: Commit**

```bash
git add routes/wikitoca_capacitacao.py app.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): ranking de trechos por relevancia para o contexto da IA"
```

---

## Task 6: CRUD das instâncias de Capacitação

**Files:**
- Modify: `routes/wikitoca_capacitacao.py` (criado na Task 5; rotas novas depois do helper de ranking)
- Test: `tests/test_wikitoca.py`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
def test_cria_lista_renomeia_e_exclui_instancia(client):
    criada = client.post('/api/wikitoca/capacitacao/sessions', json={})
    assert criada.status_code == 201, criada.get_json()
    sess = criada.get_json()
    assert sess['title'] == 'Nova capacitação'
    assert sess['title_source'] == 'ai'

    listagem = client.get('/api/wikitoca/capacitacao/sessions').get_json()
    assert len(listagem) == 1
    assert listagem[0]['documents_count'] == 0

    renomeada = client.put(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}',
                           json={'title': 'Onboarding Comercial'})
    assert renomeada.status_code == 200
    assert renomeada.get_json()['title'] == 'Onboarding Comercial'
    assert renomeada.get_json()['title_source'] == 'manual'

    detalhe = client.get(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').get_json()
    assert detalhe['session']['title'] == 'Onboarding Comercial'
    assert detalhe['documents'] == []
    assert detalhe['messages'] == []

    assert client.delete(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').status_code == 200
    assert client.get('/api/wikitoca/capacitacao/sessions').get_json() == []


def test_renomear_com_titulo_vazio_e_rejeitado(client):
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()
    resp = client.put(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}', json={'title': '   '})
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'WIKI_CAP_TITLE_REQUIRED'


def test_detalhe_de_instancia_inexistente_retorna_404(client):
    assert client.get('/api/wikitoca/capacitacao/sessions/999').status_code == 404
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k instancia -v`
Expected: FAIL com 404 em todas as rotas — elas ainda não existem.

- [ ] **Step 3: Implementar o CRUD**

Em `routes/wikitoca_capacitacao.py`, no fim do arquivo:

```python
# ═══════════════════════════════════════════════════════════════════════════
# CAPACITAÇÃO — instâncias com documentos próprios e chat com IA sobre eles.
# Isolado do resto: estes documentos não entram no submódulo Documentos nem na
# base do iToca.
# ═══════════════════════════════════════════════════════════════════════════

WIKI_CAP_DEFAULT_TITLE = 'Nova capacitação'


def _wiki_cap_session_row(session_id):
    conn = get_db()
    row = dict_from_row(conn.execute(
        'SELECT * FROM wiki_training_sessions WHERE id=?', (session_id,)).fetchone())
    conn.close()
    return row


@app.route('/api/wikitoca/capacitacao/sessions', methods=['GET'])
def list_wiki_capacitacao_sessions():
    logger.debug('[DEBUG] GET /api/wikitoca/capacitacao/sessions chamado')
    try:
        conn = get_db()
        rows = [dict_from_row(r) for r in conn.execute('''
            SELECT s.*,
                   (SELECT COUNT(*) FROM wiki_training_documents d WHERE d.session_id = s.id) AS documents_count,
                   (SELECT MAX(created_at) FROM wiki_training_messages m WHERE m.session_id = s.id) AS last_message_at
            FROM wiki_training_sessions s
            ORDER BY COALESCE(
                (SELECT MAX(created_at) FROM wiki_training_messages m WHERE m.session_id = s.id),
                s.updated_at
            ) DESC
        ''').fetchall()]
        conn.close()
        return jsonify(rows)
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/capacitacao/sessions: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_LIST_ERROR', 'Erro ao listar capacitações.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions', methods=['POST'])
def create_wiki_capacitacao_session():
    logger.debug('[DEBUG] POST /api/wikitoca/capacitacao/sessions chamado')
    try:
        data = request.get_json(silent=True) or {}
        titulo = (data.get('title') or '').strip()
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO wiki_training_sessions (title, title_source, created_at, updated_at)
                     VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
                  (titulo or WIKI_CAP_DEFAULT_TITLE, 'manual' if titulo else 'ai'))
        conn.commit()
        session_id = c.lastrowid
        row = dict_from_row(c.execute('SELECT * FROM wiki_training_sessions WHERE id=?', (session_id,)).fetchone())
        conn.close()
        row['documents_count'] = 0
        row['last_message_at'] = None
        logger.info(f'[WikiToca] Capacitação criada id={session_id}')
        return jsonify(row), 201
    except Exception as e:
        logger.exception(f'[ERROR] POST /api/wikitoca/capacitacao/sessions: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_CREATE_ERROR', 'Erro ao criar capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['PUT'])
def rename_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] PUT /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        titulo = ((request.get_json(silent=True) or {}).get('title') or '').strip()
        if not titulo:
            return api_error(400, 'WIKI_CAP_TITLE_REQUIRED', 'O título é obrigatório.')
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        c = conn.cursor()
        c.execute('''UPDATE wiki_training_sessions
                     SET title=?, title_source='manual', updated_at=CURRENT_TIMESTAMP
                     WHERE id=?''', (titulo, session_id))
        conn.commit()
        conn.close()
        return jsonify(_wiki_cap_session_row(session_id))
    except Exception as e:
        logger.exception(f'[ERROR] PUT /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_RENAME_ERROR', 'Erro ao renomear capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['GET'])
def get_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] GET /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        sess = _wiki_cap_session_row(session_id)
        if not sess:
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        docs = [dict_from_row(r) for r in conn.execute(
            '''SELECT id, session_id, file_name, original_name, file_url, file_ext,
                      file_size, extract_status, created_at
               FROM wiki_training_documents WHERE session_id=? ORDER BY id''', (session_id,)).fetchall()]
        msgs = [dict_from_row(r) for r in conn.execute(
            '''SELECT id, role, content, source_kind, source_refs, created_at
               FROM wiki_training_messages WHERE session_id=? ORDER BY created_at, id''', (session_id,)).fetchall()]
        conn.close()
        for m in msgs:
            try:
                m['source_refs'] = json.loads(m['source_refs']) if m.get('source_refs') else []
            except Exception:
                m['source_refs'] = []
        return jsonify({'session': sess, 'documents': docs, 'messages': msgs})
    except Exception as e:
        logger.exception(f'[ERROR] GET /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DETAIL_ERROR', 'Erro ao carregar capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>', methods=['DELETE'])
def delete_wiki_capacitacao_session(session_id):
    logger.debug(f'[DEBUG] DELETE /api/wikitoca/capacitacao/sessions/{session_id} chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM wiki_training_messages WHERE session_id=?', (session_id,))
        c.execute('DELETE FROM wiki_training_documents WHERE session_id=?', (session_id,))
        c.execute('DELETE FROM wiki_training_sessions WHERE id=?', (session_id,))
        conn.commit()
        conn.close()
        # Os arquivos ficam num diretório por instância — apagar a pasta inteira
        # evita deixar órfãos em disco.
        import shutil
        pasta = WIKI_TRAINING_UPLOAD_DIR / str(session_id)
        if pasta.exists():
            shutil.rmtree(pasta, ignore_errors=True)
        logger.info(f'[WikiToca] Capacitação removida id={session_id}')
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE /api/wikitoca/capacitacao/sessions/{session_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DELETE_ERROR', 'Erro ao excluir capacitação.', details=str(e))


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/messages', methods=['DELETE'])
def clear_wiki_capacitacao_messages(session_id):
    """Limpar conversa: apaga o histórico e mantém os documentos anexados."""
    logger.debug(f'[DEBUG] DELETE .../capacitacao/sessions/{session_id}/messages chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM wiki_training_messages WHERE session_id=?', (session_id,))
        c.execute('UPDATE wiki_training_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (session_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE .../capacitacao/sessions/{session_id}/messages: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_CLEAR_ERROR', 'Erro ao limpar a conversa.', details=str(e))


@app.route('/uploads/wikitoca/capacitacao/<path:filename>')
def serve_wikitoca_training_upload(filename):
    return send_from_directory(str(WIKI_TRAINING_UPLOAD_DIR), filename)
```

- [ ] **Step 4: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add routes/wikitoca_capacitacao.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): CRUD das instancias de capacitacao"
```

---

## Task 7: Upload de documentos da Capacitação + título por IA

**Files:**
- Modify: `routes/wikitoca_capacitacao.py` (rotas e worker novos, depois do CRUD)
- Test: `tests/test_wikitoca.py`

> **Corrida exclusão × indexação — confirmada empiricamente na revisão da Task 6.**
> Se o usuário excluir a instância enquanto a thread de indexação roda, acontecem
> duas coisas, ambas medidas:
>
> 1. O `INSERT`/`UPDATE` em `wiki_training_documents` é **rejeitado** pela FK
>    (`FOREIGN KEY constraint failed`, porque `PRAGMA foreign_keys=ON` está ativo).
>    Não gera linha órfã, mas a thread morre com `IntegrityError` — e num daemon
>    thread sem `try/except` isso é uma exceção **invisível** e uma barra de
>    progresso travada para sempre na tela do usuário.
> 2. Se o `rmtree` da exclusão roda **antes** de a thread gravar o arquivo, a
>    thread **recria a pasta** — órfão permanente em disco que nenhuma exclusão
>    futura alcança.
>
> Trate os dois: reconfira a existência da sessão dentro da própria transação do
> worker (ou trate `IntegrityError` como "sessão excluída — aborta limpo, apaga o
> arquivo recém-gravado e encerra a task com um passo explicativo"), e registre as
> threads em `_wiki_indexing_threads` (o mecanismo da Task 3, em
> `routes/wikitoca.py`) para que a exclusão possa dar `join` antes do `rmtree`.

> **Restrição de projeto — não reaproveite `wiki_documents` aqui.** Os materiais
> de treinamento vão para `wiki_training_documents`, tabela própria. Os laços de
> snapshot do RAG do iToca em `app.py:5039` e `app.py:5463` (este já comentado
> como "pode ser lento por OCR") iteram **todos** os `wiki_documents` e chamam a
> extração em cada rebuild. Gravar material de capacitação lá violaria o
> isolamento exigido pelo spec ("não aparecem no submódulo Documentos nem entram
> na base do iToca") **e** faria o OCR de todas as imagens rodar a cada snapshot.
>
> **Momento certo de extrair o helper de OCR.** Existem hoje três sites com o
> núcleo "localizar tesseract → atribuir o global `tesseract_cmd` → `por+eng` com
> fallback `eng`": `app.py:2337` (reembolsos), `app.py:4819` (PDF escaneado) e
> `app.py:4885` (imagem). Com o consumidor em lote desta task, vale extrair um
> `_itoca_ocr_image(img) -> str` estreito cobrindo **só os dois ramos dentro de
> `_itoca_extract_text_from_file`** — deixando reembolsos como está, porque o
> entorno dele (4 variantes de pré-processamento × 2 modos `--psm` com scoring)
> diverge demais. O ganho não é economizar linhas: é ter um lugar único para a
> mutação do global e para o `lru_cache` em `_itoca_find_tesseract_cmd()` (hoje
> cada chamada dispara um `subprocess.run(['tesseract', '--version'])`, o que num
> lote de N imagens vira N subprocessos).

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
def _sobe_doc_capacitacao(client, session_id, nome='manual.docx',
                          texto='Prazo de aprovacao e de cinco dias uteis'):
    from docx import Document
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(texto)
    doc.save(buf)
    buf.seek(0)
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{session_id}/documents',
                       data={'files': (buf, nome)},
                       content_type='multipart/form-data')
    assert resp.status_code == 202, resp.get_json()
    return resp.get_json()


def test_upload_de_documento_da_capacitacao_indexa_e_gera_titulo(client, monkeypatch):
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'Politica de Aprovacao de Contratos')
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()

    payload = _sobe_doc_capacitacao(client, sess['id'])
    _espera_task(client, payload['task_id'])

    detalhe = client.get(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').get_json()
    assert detalhe['documents'][0]['extract_status'] == 'ok'
    assert detalhe['session']['title'] == 'Politica de Aprovacao de Contratos'
    assert detalhe['session']['title_source'] == 'ai'


def test_titulo_manual_nao_e_sobrescrito_pela_ia(client, monkeypatch):
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'Titulo Gerado Pela IA')
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={'title': 'Meu Nome'}).get_json()

    payload = _sobe_doc_capacitacao(client, sess['id'])
    _espera_task(client, payload['task_id'])

    detalhe = client.get(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').get_json()
    assert detalhe['session']['title'] == 'Meu Nome'


def test_extensao_nao_aceita_na_capacitacao_e_rejeitada(client):
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}/documents',
                       data={'files': (io.BytesIO(b'a,b\n1,2\n'), 'planilha.xlsx')},
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'WIKI_CAP_INVALID_TYPE'


def test_exclui_documento_da_capacitacao(client, monkeypatch):
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'Titulo')
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()
    payload = _sobe_doc_capacitacao(client, sess['id'])
    _espera_task(client, payload['task_id'])

    doc_id = client.get(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').get_json()['documents'][0]['id']
    assert client.delete(f'/api/wikitoca/capacitacao/documents/{doc_id}').status_code == 200
    assert client.get(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}').get_json()['documents'] == []
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k capacitacao -v`
Expected: FAIL com 404 nas rotas de documento da capacitação.

- [ ] **Step 3: Implementar upload, indexação e título**

Em `routes/wikitoca_capacitacao.py`, no fim do arquivo:

```python
def _wiki_cap_generate_title(session_id):
    """Gera o título da instância a partir do primeiro documento indexado.
    Só age quando title_source ainda é 'ai' — renomear pelo usuário trava isso."""
    sess = _wiki_cap_session_row(session_id)
    if not sess or (sess.get('title_source') or 'ai') != 'ai':
        return
    conn = get_db()
    row = dict_from_row(conn.execute(
        '''SELECT original_name, extracted_text FROM wiki_training_documents
           WHERE session_id=? AND extract_status='ok' ORDER BY id LIMIT 1''', (session_id,)).fetchone())
    conn.close()
    if not row or not (row.get('extracted_text') or '').strip():
        return
    trecho = (row['extracted_text'] or '')[:3000]
    bruto = _llm_prompt(
        'Você recebe o início de um documento de treinamento corporativo. '
        'Responda SOMENTE com um título curto em português do Brasil, no máximo 6 palavras, '
        'sem aspas, sem ponto final e sem nenhum texto além do título.\n\n'
        f'Arquivo: {row["original_name"]}\n\nConteúdo:\n{trecho}',
        log_tag='WikiCapacitacao'
    )
    titulo = (bruto or '').strip().strip('"').splitlines()[0].strip() if bruto else ''
    if not titulo:
        logger.info(f'[WikiToca] Nenhum LLM respondeu o título da capacitação {session_id}; mantendo o padrão.')
        return
    titulo = titulo[:120]
    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE wiki_training_sessions SET title=?, title_source='ai',
                 updated_at=CURRENT_TIMESTAMP WHERE id=? AND title_source='ai' ''', (titulo, session_id))
    conn.commit()
    conn.close()
    logger.info(f'[WikiToca] Título da capacitação {session_id} definido pela IA: {titulo}')


def _wiki_cap_index_async(task_id, session_id, doc_ids):
    try:
        total = len(doc_ids)
        for pos, doc_id in enumerate(doc_ids, start=1):
            conn = get_db()
            row = dict_from_row(conn.execute(
                'SELECT file_name, original_name FROM wiki_training_documents WHERE id=?',
                (doc_id,)).fetchone())
            conn.close()
            if not row:
                continue
            _bg_task_set(task_id, {
                'step': f'Lendo {pos} de {total} — {row["original_name"]}',
                'progress': int(5 + (pos - 1) * 80 / max(1, total)),
            })
            caminho = WIKI_TRAINING_UPLOAD_DIR / str(session_id) / row['file_name']
            _wiki_index_document('wiki_training_documents', doc_id, caminho)

        _bg_task_set(task_id, {'step': 'Definindo o título da capacitação...', 'progress': 90})
        _wiki_cap_generate_title(session_id)

        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100,
                               'result': {'session_id': session_id}})
    except Exception as e:
        logger.exception(f'[WikiToca] _wiki_cap_index_async: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 100})
    finally:
        _bg_task_cleanup(task_id)


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/documents', methods=['POST'])
def upload_wiki_capacitacao_documents(session_id):
    logger.debug(f'[DEBUG] POST .../capacitacao/sessions/{session_id}/documents chamado')
    try:
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')
        files = request.files.getlist('files')
        if not files or all(not f.filename for f in files):
            return api_error(400, 'WIKI_CAP_NO_FILE', 'Nenhum arquivo enviado.')

        pasta = WIKI_TRAINING_UPLOAD_DIR / str(session_id)
        pasta.mkdir(parents=True, exist_ok=True)
        conn = get_db()
        c = conn.cursor()
        created = []
        for f in files:
            if not f.filename:
                continue
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED_WIKI_TRAINING_EXTENSIONS:
                logger.warning(f'[WikiToca] Extensão rejeitada na capacitação: {ext}')
                continue
            original_name = f.filename
            safe_name = secure_filename(f'cap_{int(datetime.now().timestamp())}_{original_name}')
            save_path = pasta / safe_name
            f.save(str(save_path))
            c.execute(
                '''INSERT INTO wiki_training_documents
                   (session_id, file_name, original_name, file_url, file_ext, file_size,
                    extract_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)''',
                (session_id, safe_name, original_name,
                 f'/uploads/wikitoca/capacitacao/{session_id}/{safe_name}',
                 ext, save_path.stat().st_size)
            )
            conn.commit()
            created.append(dict_from_row(c.execute(
                'SELECT id, session_id, file_name, original_name, file_url, file_ext, '
                'file_size, extract_status, created_at FROM wiki_training_documents WHERE id=?',
                (c.lastrowid,)).fetchone()))
        conn.close()

        if not created:
            return api_error(400, 'WIKI_CAP_INVALID_TYPE',
                             'Nenhum arquivo válido enviado. Tipos aceitos: PDF, DOC, DOCX, PNG, JPG.')

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Enviando arquivos...', 'progress': 5})
        threading.Thread(target=_wiki_cap_index_async,
                         args=(task_id, session_id, [d['id'] for d in created]), daemon=True).start()
        return jsonify({'documents': created, 'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST .../capacitacao/sessions/{session_id}/documents: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_UPLOAD_ERROR', 'Erro ao enviar documentos.', details=str(e))


@app.route('/api/wikitoca/capacitacao/documents/<int:document_id>', methods=['DELETE'])
def delete_wiki_capacitacao_document(document_id):
    logger.debug(f'[DEBUG] DELETE .../capacitacao/documents/{document_id} chamado')
    try:
        conn = get_db()
        c = conn.cursor()
        row = dict_from_row(c.execute(
            'SELECT session_id, file_name FROM wiki_training_documents WHERE id=?', (document_id,)).fetchone())
        if not row:
            conn.close()
            return api_error(404, 'WIKI_CAP_DOC_NOT_FOUND', 'Documento não encontrado.')
        c.execute('DELETE FROM wiki_training_documents WHERE id=?', (document_id,))
        conn.commit()
        conn.close()
        caminho = WIKI_TRAINING_UPLOAD_DIR / str(row['session_id']) / row['file_name']
        if caminho.exists():
            caminho.unlink()
        return jsonify({'success': True})
    except Exception as e:
        logger.exception(f'[ERROR] DELETE .../capacitacao/documents/{document_id}: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_DOC_DELETE_ERROR', 'Erro ao excluir documento.', details=str(e))
```

- [ ] **Step 4: Rodar os testes**

Run: `pytest tests/test_wikitoca.py -v`
Expected: PASS em todos.

- [ ] **Step 5: Commit**

```bash
git add routes/wikitoca_capacitacao.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): upload de documentos da capacitacao com titulo gerado por IA"
```

---

## Task 8: Cascata de resposta (documentos → base WikiToca → web)

**Files:**
- Modify: `routes/wikitoca_capacitacao.py` (worker e rota novos, no fim do arquivo)
- Test: `tests/test_wikitoca.py`

> **Requisito de performance: memoize a tokenização do acervo.** Medido na Task 5,
> com 50 documentos de 100 KB (4.800 blocos) e pergunta de 8 termos,
> `_wiki_rank_chunks` leva **~1,66 s** — e **~1,63 s** disso é a tokenização
> (`_wiki_tokens` uma vez por bloco), não o laço de pontuação. O passo 1 da cascata
> (documentos da instância) é barato, porque são poucos arquivos; o problema é o
> passo 2, que varre `wiki_entries` + todos os `wiki_documents`. Sem cache, **toda
> mensagem de chat** paga esse custo antes de sequer chamar o LLM.
>
> Memoize em processo os blocos tokenizados do passo 2, com chave que inclua a
> identidade e a versão de cada documento (`id` + `extracted_at` para
> `wiki_documents`, `id` + `updated_at` para `wiki_entries`), invalidando quando
> algum documento muda. Assim só a primeira pergunta depois de uma alteração paga
> o custo.
>
> **Não** replique aqui o padrão do iToca (`_itoca_get_cached_base`, `app.py:5673`),
> que serializa um snapshot pré-normalizado em `app_settings` e depende de uma ação
> explícita de "Base Update" do usuário — é pesado demais para este caso e
> introduziria um botão que o spec da Capacitação não prevê. Um dicionário de
> módulo protegido por lock basta.
>
> **Antes de escrever a cascata, separe o núcleo puro das rotas.** Depois da Task 7
> o arquivo passa de 700 linhas misturando duas coisas: helpers puros sem Flask
> (`_wiki_rank_chunks`, `_wiki_split_chunks`, `_wiki_tokens`) e handlers HTTP. A
> lógica de valor desta task — montagem de contexto, prompts, decisão de escalar —
> é justamente o que dá para testar **sem** `client`, direto por função. Extraia os
> helpers puros e as funções novas de montagem de prompt para um bloco claramente
> separado no topo do arquivo (ou, se ficar grande, para um módulo próprio que não
> registre rotas), e mantenha os handlers finos. Isso é o que permite testar a
> cascata com `_llm_prompt` mockado sem subir requisição HTTP.
>
> **Não conte com o corte por score para discriminar relevância.** Medido na revisão
> da Task 5: o menor score possível para um bloco que casa pelo menos um termo
> significativo é **1,4055**, e `_WIKI_MIN_CHUNK_SCORE` é 1.0 — o limiar é
> matematicamente inerte. Na prática, `_wiki_rank_chunks` devolve `[]` apenas quando
> as fontes **não têm nenhum termo significativo em comum** com a pergunta. Quem
> julga relevância é o `INSUFICIENTE` da IA; o corte economiza a chamada só no caso
> extremo. Isso é a direção segura: o falso positivo custa uma chamada de LLM, o
> falso negativo mandaria o usuário para a web tendo a resposta nos próprios
> documentos. Se você quiser um limiar que discrimine de verdade, saiba que o IDF é
> **local à chamada** — o mesmo match perfeito mediu 27,34 num acervo de 6.667 blocos
> e 4,22 num de 1 bloco —, então nenhum valor absoluto funciona sem normalizar o
> score primeiro. Não faça isso nesta task.
- [ ] **Step 1: Escrever o teste que falha**

Acrescentar em `tests/test_wikitoca.py`:

```python
def _prepara_capacitacao_com_doc(client, monkeypatch, texto):
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'Titulo')
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()
    payload = _sobe_doc_capacitacao(client, sess['id'], texto=texto)
    _espera_task(client, payload['task_id'])
    return sess['id']


def test_resposta_vem_dos_documentos_da_instancia(client, monkeypatch):
    session_id = _prepara_capacitacao_com_doc(
        client, monkeypatch, 'O prazo de aprovacao do contrato e de cinco dias uteis.')

    chamadas = []

    def fake_llm(question, log_tag='llm', temperature=0.1, web=False):
        chamadas.append({'web': web, 'question': question})
        return 'O prazo e de cinco dias uteis.'

    monkeypatch.setattr(toca, '_llm_prompt', fake_llm)
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{session_id}/ask',
                       json={'question': 'Qual o prazo de aprovacao do contrato?'})
    assert resp.status_code == 202, resp.get_json()
    _espera_task(client, resp.get_json()['task_id'])

    msgs = client.get(f'/api/wikitoca/capacitacao/sessions/{session_id}').get_json()['messages']
    assert msgs[0]['role'] == 'user'
    assert msgs[1]['source_kind'] == 'documents'
    assert 'manual.docx' in msgs[1]['source_refs']
    assert len(chamadas) == 1 and chamadas[0]['web'] is False


def test_insuficiente_nos_documentos_escala_para_a_base_wikitoca(client, monkeypatch):
    session_id = _prepara_capacitacao_com_doc(
        client, monkeypatch, 'O prazo de aprovacao do contrato e de cinco dias uteis.')
    client.post('/api/wikitoca/entries', json={
        'title': 'Politica de contrato', 'content': 'O prazo de rescisao do contrato e de trinta dias.'})

    respostas = ['INSUFICIENTE', 'O prazo de rescisao e de trinta dias.']

    def fake_llm(question, log_tag='llm', temperature=0.1, web=False):
        return respostas.pop(0)

    monkeypatch.setattr(toca, '_llm_prompt', fake_llm)
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{session_id}/ask',
                       json={'question': 'Qual o prazo de rescisao do contrato?'})
    _espera_task(client, resp.get_json()['task_id'])

    msgs = client.get(f'/api/wikitoca/capacitacao/sessions/{session_id}').get_json()['messages']
    assert msgs[-1]['source_kind'] == 'wiki'
    assert 'trinta dias' in msgs[-1]['content']


def test_pergunta_sem_relacao_nenhuma_vai_para_a_web(client, monkeypatch):
    session_id = _prepara_capacitacao_com_doc(
        client, monkeypatch, 'O prazo de aprovacao do contrato e de cinco dias uteis.')

    chamadas = []

    def fake_llm(question, log_tag='llm', temperature=0.1, web=False):
        chamadas.append(web)
        return 'Resposta encontrada na internet.' if web else 'INSUFICIENTE'

    monkeypatch.setattr(toca, '_llm_prompt', fake_llm)
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{session_id}/ask',
                       json={'question': 'Qual a cotacao do dolar hoje?'})
    _espera_task(client, resp.get_json()['task_id'])

    msgs = client.get(f'/api/wikitoca/capacitacao/sessions/{session_id}').get_json()['messages']
    assert msgs[-1]['source_kind'] == 'web'
    # Nenhum trecho relevante nos documentos nem na base: os dois primeiros
    # passos são pulados sem gastar chamada de LLM.
    assert chamadas == [True]


def test_sem_nenhum_llm_disponivel_a_task_vira_erro(client, monkeypatch):
    session_id = _prepara_capacitacao_com_doc(
        client, monkeypatch, 'O prazo de aprovacao do contrato e de cinco dias uteis.')
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: None)

    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{session_id}/ask',
                       json={'question': 'Qual o prazo de aprovacao do contrato?'})
    payload = _espera_task(client, resp.get_json()['task_id'])
    assert payload['status'] == 'error'
    assert 'IA' in payload['error']


def test_pergunta_vazia_e_rejeitada(client):
    sess = client.post('/api/wikitoca/capacitacao/sessions', json={}).get_json()
    resp = client.post(f'/api/wikitoca/capacitacao/sessions/{sess["id"]}/ask', json={'question': '  '})
    assert resp.status_code == 400
    assert resp.get_json()['error_code'] == 'WIKI_CAP_QUESTION_REQUIRED'
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

Run: `pytest tests/test_wikitoca.py -k "resposta or insuficiente or web or llm_disponivel or pergunta_vazia" -v`
Expected: FAIL com 404 em `POST .../ask`.

- [ ] **Step 3: Implementar a cascata**

Em `routes/wikitoca_capacitacao.py`, no fim do arquivo:

```python
WIKI_CAP_MAX_CONTEXT_CHARS = 12000
WIKI_CAP_HISTORY_MESSAGES = 6


def _wiki_cap_history_text(session_id):
    """Últimas mensagens da instância, para o follow-up fazer sentido."""
    conn = get_db()
    rows = [dict_from_row(r) for r in conn.execute(
        '''SELECT role, content FROM wiki_training_messages
           WHERE session_id=? ORDER BY created_at DESC, id DESC LIMIT ?''',
        (session_id, WIKI_CAP_HISTORY_MESSAGES)).fetchall()]
    conn.close()
    if not rows:
        return ''
    linhas = [f'{"Usuário" if r["role"] == "user" else "Assistente"}: {r["content"]}'
              for r in reversed(rows)]
    return 'Histórico recente desta conversa:\n' + '\n'.join(linhas) + '\n\n'


def _wiki_cap_ask_llm(trechos, question, history, origem_label):
    """Monta o prompt com os trechos selecionados e chama o LLM.
    Devolve (resposta, labels_usados) ou (None, []) se vier INSUFICIENTE/nada."""
    contexto, usados, tamanho = [], [], 0
    for t in trechos:
        bloco = f'[{t["label"]}]\n{t["chunk"]}'
        if tamanho + len(bloco) > WIKI_CAP_MAX_CONTEXT_CHARS:
            break
        contexto.append(bloco)
        tamanho += len(bloco)
        if t['label'] not in usados:
            usados.append(t['label'])
    if not contexto:
        return None, []

    bruto = _llm_prompt(
        f'{history}'
        f'Você responde perguntas usando EXCLUSIVAMENTE os trechos abaixo, extraídos de {origem_label}.\n'
        'Se os trechos não contiverem a informação necessária para responder, '
        'responda SOMENTE a palavra INSUFICIENTE, sem mais nada.\n'
        'Caso contrário, responda em português do Brasil, de forma direta e objetiva.\n\n'
        'TRECHOS:\n' + '\n\n'.join(contexto) + f'\n\nPERGUNTA: {question}',
        log_tag='WikiCapacitacao'
    )
    if not bruto or not str(bruto).strip():
        return None, []
    resposta = str(bruto).strip()
    if resposta.upper().replace('.', '').strip() == 'INSUFICIENTE':
        return None, []
    return resposta, usados


def _wiki_cap_answer_async(task_id, session_id, question):
    try:
        history = _wiki_cap_history_text(session_id)
        houve_llm = False

        # ── Passo 1: documentos desta capacitação ──────────────────────────
        _bg_task_set(task_id, {'step': 'Consultando os documentos desta capacitação...', 'progress': 20})
        conn = get_db()
        docs = [dict_from_row(r) for r in conn.execute(
            '''SELECT original_name, extracted_text FROM wiki_training_documents
               WHERE session_id=? AND extract_status='ok' ''', (session_id,)).fetchall()]
        conn.close()
        trechos = _wiki_rank_chunks(
            [{'label': d['original_name'], 'text': d['extracted_text']} for d in docs], question)
        resposta, refs, origem = None, [], None
        if trechos:
            houve_llm = True
            resposta, refs = _wiki_cap_ask_llm(trechos, question, history, 'documentos anexados a esta capacitação')
            if resposta:
                origem = 'documents'

        # ── Passo 2: base do WikiToca ──────────────────────────────────────
        if not resposta:
            _bg_task_set(task_id, {'step': 'Consultando a base do WikiToca...', 'progress': 50})
            conn = get_db()
            fontes = [{'label': f'Conhecimento: {r[0]}', 'text': f'{r[0]}\n{r[1] or ""}\n{r[2] or ""}'}
                      for r in conn.execute('SELECT title, category, content FROM wiki_entries')]
            fontes += [{'label': r[0], 'text': r[1]} for r in conn.execute(
                "SELECT original_name, extracted_text FROM wiki_documents WHERE extract_status='ok'")]
            conn.close()
            trechos = _wiki_rank_chunks(fontes, question)
            if trechos:
                houve_llm = True
                resposta, refs = _wiki_cap_ask_llm(trechos, question, history, 'a base de conhecimento do WikiToca')
                if resposta:
                    origem = 'wiki'

        # ── Passo 3: web ───────────────────────────────────────────────────
        if not resposta:
            _bg_task_set(task_id, {'step': 'Pesquisando na web...', 'progress': 75})
            houve_llm = True
            bruto = _llm_prompt(
                f'{history}Responda em português do Brasil, de forma direta e objetiva, '
                f'usando informações atuais da internet.\n\nPERGUNTA: {question}',
                log_tag='WikiCapacitacao', web=True)
            if bruto and str(bruto).strip():
                resposta, refs, origem = str(bruto).strip(), [], 'web'

        if not resposta:
            # Chegar aqui com houve_llm=True significa que nenhum provider de IA
            # respondeu — é erro de integração, não "não encontrei".
            msg = ('Nenhuma integração de IA respondeu (SAI e OpenRouter indisponíveis). '
                   'Verifique as chaves em Configurações.') if houve_llm else \
                  ('Não encontrei essa informação nos documentos, na base do WikiToca nem na web.')
            if houve_llm:
                _bg_task_set(task_id, {'status': 'error', 'error': msg, 'progress': 100})
                return
            resposta, refs, origem = msg, [], 'web'

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO wiki_training_messages
                     (session_id, role, content, source_kind, source_refs, created_at)
                     VALUES (?, 'assistant', ?, ?, ?, CURRENT_TIMESTAMP)''',
                  (session_id, resposta, origem, json.dumps(refs, ensure_ascii=False)))
        c.execute('UPDATE wiki_training_sessions SET updated_at=CURRENT_TIMESTAMP WHERE id=?', (session_id,))
        conn.commit()
        conn.close()

        logger.info(f'[WikiToca] Capacitação {session_id} respondeu via "{origem}" (refs={refs})')
        _bg_task_set(task_id, {'status': 'done', 'step': 'Concluído!', 'progress': 100,
                               'result': {'answer': resposta, 'source_kind': origem, 'source_refs': refs}})
    except Exception as e:
        logger.exception(f'[WikiToca] _wiki_cap_answer_async: {e}')
        _bg_task_set(task_id, {'status': 'error', 'error': str(e), 'progress': 100})
    finally:
        _bg_task_cleanup(task_id)


@app.route('/api/wikitoca/capacitacao/sessions/<int:session_id>/ask', methods=['POST'])
def ask_wiki_capacitacao(session_id):
    logger.debug(f'[DEBUG] POST .../capacitacao/sessions/{session_id}/ask chamado')
    try:
        question = ((request.get_json(silent=True) or {}).get('question') or '').strip()
        if not question:
            return api_error(400, 'WIKI_CAP_QUESTION_REQUIRED', 'A pergunta é obrigatória.')
        if not _wiki_cap_session_row(session_id):
            return api_error(404, 'WIKI_CAP_NOT_FOUND', 'Capacitação não encontrada.')

        # Grava a pergunta antes do LLM: se o processamento falhar, o usuário
        # ainda vê o que perguntou no histórico.
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO wiki_training_messages (session_id, role, content, created_at)
                     VALUES (?, 'user', ?, CURRENT_TIMESTAMP)''', (session_id, question))
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _bg_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(target=_wiki_cap_answer_async,
                         args=(task_id, session_id, question), daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[ERROR] POST .../capacitacao/sessions/{session_id}/ask: {e}')
        traceback.print_exc()
        return api_error(500, 'WIKI_CAP_ASK_ERROR', 'Erro ao processar a pergunta.', details=str(e))
```

- [ ] **Step 4: Rodar a suíte inteira**

Run: `pytest tests/ -v`
Expected: PASS em tudo (nenhuma regressão nos módulos existentes).

- [ ] **Step 5: Commit**

```bash
git add routes/wikitoca_capacitacao.py tests/test_wikitoca.py
git commit -m "feat(wikitoca): cascata de resposta documentos->base->web na capacitacao"
```

---

## Task 9: Extrair o JS do WikiToca para `public/js/wikitoca.js`

Refatoração pura — **nenhuma mudança de comportamento**. Isolar isso num commit próprio faz o diff das Tasks 10-14 ficar legível.

**Files:**
- Create: `public/js/wikitoca.js`
- Modify: `public/js/itoca-autotoca.js` (remover linhas 3914–4324 e as variáveis nas linhas 1490-1491 e os listeners wiki do `DOMContentLoaded`)
- Modify: `public/js/core.js` (remover `let wikiEntriesSortOrder = "az";` da linha 377)
- Modify: `public/index.html` (novo `<script>`)

- [ ] **Step 1: Criar o arquivo novo com o bloco WikiToca**

Criar `public/js/wikitoca.js` com este cabeçalho, seguido do conteúdo **exato** das linhas 3914–4324 de `public/js/itoca-autotoca.js`:

```javascript
        // =====================================================
        // WikiToca — Conhecimentos, Documentos e Capacitação
        // Extraído de itoca-autotoca.js. Scripts clássicos compartilham o
        // escopo global, então as funções daqui continuam visíveis para o
        // resto do app (e vice-versa: escapeHtml, showError, uiConfirm e
        // formatFileSize seguem vindo dos outros arquivos).
        // =====================================================
        let wikiEntries = [];
        let wikiDocuments = [];
        let wikiEntriesSortOrder = "az";

        // <<< colar aqui as linhas 3914-4324 de itoca-autotoca.js, sem alterações >>>

        window.addEventListener('DOMContentLoaded', () => {
            const wikiSearchInput = document.getElementById('wikiSearchInput');
            if (wikiSearchInput) {
                wikiSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        loadWikiTocaData();
                    }
                });
            }
            const wikiTitle = document.getElementById('wikiEntryTitle');
            const wikiContent = document.getElementById('wikiEntryContent');
            if (wikiTitle) wikiTitle.addEventListener('blur', autoFillWikiTags);
            if (wikiContent) wikiContent.addEventListener('blur', autoFillWikiTags);
        });
```

Comando para extrair o bloco exato:

```bash
sed -n '3914,4324p' public/js/itoca-autotoca.js > /tmp/wiki-bloco.js
```

- [ ] **Step 2: Remover o bloco do arquivo antigo**

Em `public/js/itoca-autotoca.js`:
- Apagar as linhas 3914–4324 (do `async function loadWikiTocaData() {` até a linha em branco antes de `function formatFileSize(bytes) {`). **`formatFileSize` fica** — é helper genérico usado por outros módulos.
- Apagar `let wikiEntries = [];` e `let wikiDocuments = [];` (linhas 1490-1491).
- No `DOMContentLoaded` do fim do arquivo, apagar o bloco `const wikiSearchInput = ...` até `if (wikiContent) wikiContent.addEventListener('blur', autoFillWikiTags);` (agora vive em `wikitoca.js`).

- [ ] **Step 3: Remover a variável de ordenação do core.js**

Em `public/js/core.js`, apagar a linha 377: `let wikiEntriesSortOrder = "az";`

- [ ] **Step 4: Incluir o script novo**

Em `public/index.html`, depois da linha 2053 (`<script src="/js/relatorio-semanal.js"></script>`):

```html
    <script src="/js/wikitoca.js"></script>
```

- [ ] **Step 5: Verificar que nada ficou duplicado nem faltando**

```bash
grep -c "function loadWikiTocaData" public/js/itoca-autotoca.js public/js/wikitoca.js
grep -rn "wikiEntriesSortOrder\|let wikiEntries\|let wikiDocuments" public/js/
```

Expected: `itoca-autotoca.js:0` e `wikitoca.js:1`; as três variáveis aparecem **apenas** em `wikitoca.js`.

- [ ] **Step 6: Verificar no navegador**

Rodar o app (`python app.py`), abrir `http://localhost:3000`, ir na aba WikiToca e confirmar, com o console do navegador aberto:
- Nenhum erro de `is not defined` no console.
- A lista de conhecimentos e a de documentos carregam.
- Busca, ordenação A-Z/Z-A, novo conhecimento, upload e os dois modais de importação funcionam como antes.

- [ ] **Step 7: Commit**

```bash
git add public/js/wikitoca.js public/js/itoca-autotoca.js public/js/core.js public/index.html
git commit -m "refactor(wikitoca): extrai o JS do WikiToca para wikitoca.js"
```

---

## Task 10: Markup e navegação dos três submódulos

**Files:**
- Modify: `public/index.html` (bloco `#wikitoca`, linhas 455–507)
- Modify: `public/js/wikitoca.js` (`toggleWikiSubmodule`, `loadWikiTocaData`)
- Modify: `public/css/app.css`

- [ ] **Step 1: Reescrever o cabeçalho e os painéis**

Em `public/index.html`, substituir todo o conteúdo entre `<div id="wikitoca" class="tab-content">` e o `</div>` que fecha esse bloco (linhas 455–507) por:

```html
        <div id="wikitoca" class="tab-content">
            <div class="page-header wiki-header">
                <div style="display:flex; align-items:center; gap:14px;">
                    <img src="/coelho_wiki.png" alt="WikiToca" style="width:56px; height:56px; object-fit:contain;">
                    <div>
                        <h1>WikiToca</h1>
                        <p>Base de conhecimento interna para registros rápidos, consulta diária e arquivos de apoio.</p>
                    </div>
                </div>
            </div>

            <div class="wiki-submodule-bar">
                <button id="wikiSubBtn_conhecimentos" class="btn btn-auto-mapping" onclick="toggleWikiSubmodule('conhecimentos')"><i class="fas fa-book"></i> Conhecimentos</button>
                <button id="wikiSubBtn_documentos" class="btn btn-secondary" onclick="toggleWikiSubmodule('documentos')"><i class="fas fa-file-lines"></i> Documentos</button>
                <button id="wikiSubBtn_capacitacao" class="btn btn-secondary" onclick="toggleWikiSubmodule('capacitacao')"><span class="ai-star-icon">✦</span> Capacitação</button>
            </div>

            <!-- ── Submódulo: Conhecimentos ───────────────────────────────── -->
            <section id="wikiSubConhecimentos" class="wiki-card">
                <div class="wiki-section-header">
                    <h3 class="wiki-section-title">Conhecimentos registrados</h3>
                    <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                        <button id="wikiSortToggleBtn" type="button" class="wiki-sort-toggle" onclick="toggleWikiEntriesSort()">A-Z</button>
                        <div class="wiki-import-export">
                            <button class="btn btn-secondary btn-small wiki-action-btn" onclick="exportWikiEntries()" title="Exportar conhecimentos"><i class="fas fa-file-export"></i> Exportar</button>
                            <button class="btn btn-secondary btn-small wiki-action-btn" onclick="openWikiImportModal()" title="Importar conhecimentos"><i class="fas fa-file-import"></i> Importar</button>
                        </div>
                        <button class="btn btn-primary btn-small wiki-action-btn" onclick="openWikiEntryModal()"><i class="fas fa-plus"></i> Novo conhecimento</button>
                    </div>
                </div>
                <div class="wiki-toolbar-search">
                    <input id="wikiSearchInput" class="wiki-search-input" placeholder="Pesquisar nos conhecimentos">
                    <button class="btn btn-primary wiki-action-btn" onclick="loadWikiEntriesFromSearch()"><i class="fas fa-search"></i> Buscar</button>
                    <button class="btn btn-secondary wiki-action-btn" onclick="clearWikiSearch()" title="Limpar pesquisa"><i class="fas fa-times"></i> Limpar</button>
                </div>
                <div id="wikiEntriesList"></div>
            </section>

            <!-- ── Submódulo: Documentos ──────────────────────────────────── -->
            <section id="wikiSubDocumentos" class="wiki-card" style="display:none;">
                <div class="wiki-section-header">
                    <h3 class="wiki-section-title" style="margin-bottom:0;">Documentos (PDF, Excel, Word)</h3>
                    <div class="wiki-import-export">
                        <button class="btn btn-secondary btn-small wiki-action-btn" onclick="reindexWikiDocuments()" title="Reprocessar o texto dos documentos pendentes para a busca por conteúdo"><i class="fas fa-rotate"></i> Reindexar documentos</button>
                        <button class="btn btn-secondary btn-small wiki-action-btn" onclick="reindexWikiDocuments(true)" title="Reprocessar TODOS os documentos, inclusive os já indexados — use depois de instalar o Tesseract"><i class="fas fa-rotate-right"></i> Reindexar tudo</button>
                        <button class="btn btn-secondary btn-small wiki-action-btn" onclick="exportWikiDocuments()" title="Exportar documentos"><i class="fas fa-file-export"></i> Exportar</button>
                        <button class="btn btn-secondary btn-small wiki-action-btn" onclick="openWikiDocImportModal()" title="Importar documentos"><i class="fas fa-file-import"></i> Importar</button>
                    </div>
                </div>
                <div class="wiki-toolbar-search">
                    <input id="wikiDocSearchInput" class="wiki-search-input" placeholder="Pesquisar por nome ou pelo conteúdo do arquivo">
                    <select id="wikiDocExtFilter" class="wiki-search-input" style="flex:0 0 150px; min-width:0;" onchange="searchWikiDocuments()">
                        <option value="">Todos os tipos</option>
                        <option value="pdf">PDF</option>
                        <option value="word">Word</option>
                        <option value="excel">Excel</option>
                    </select>
                    <button class="btn btn-primary wiki-action-btn" onclick="searchWikiDocuments()"><i class="fas fa-search"></i> Buscar</button>
                    <button class="btn btn-secondary wiki-action-btn" onclick="clearWikiDocSearch()" title="Limpar pesquisa"><i class="fas fa-times"></i> Limpar</button>
                </div>
                <div class="wiki-doc-upload-row">
                    <div class="wiki-doc-upload-main">
                        <input id="wikiDocumentFile" type="file" accept=".pdf,.xls,.xlsx,.doc,.docx" multiple style="display:none;" onchange="onWikiFileSelected(event)">
                        <button type="button" class="btn btn-primary wiki-action-btn" onclick="document.getElementById('wikiDocumentFile').click()"><i class="fas fa-paperclip"></i> Escolher arquivo(s)</button>
                    </div>
                    <span id="wikiFileName" class="wiki-file-name"></span>
                    <button id="wikiFileClearBtn" type="button" onclick="clearWikiFileSelection()" title="Cancelar seleção" style="display:none; background:none; border:none; cursor:pointer; color:#ef4444; font-size:15px; padding:0 2px; line-height:1; vertical-align:middle;"><i class="fas fa-times-circle"></i></button>
                    <div class="wiki-upload-actions">
                        <button id="wikiUploadBtn" class="btn btn-primary wiki-action-btn" onclick="uploadWikiDocument()"><i class="fas fa-upload"></i> Enviar</button>
                    </div>
                </div>
                <div id="wikiDocProgressWrap" style="display:none; margin-bottom:12px;">
                    <div style="font-size:12px; color:#6b7280; margin-bottom:6px;" id="wikiDocProgressStep">Iniciando...</div>
                    <div style="position:relative; background:#d1fae5; border-radius:99px; height:8px; overflow:visible; margin:0 2px;">
                        <div id="wikiDocProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                            <img src="/images/coelho-correndo.webp" class="coelho-run" alt="" style="height:18px;right:-14px;">
                        </div>
                    </div>
                </div>
                <div id="wikiDocumentsList"></div>
            </section>

            <!-- ── Submódulo: Capacitação (markup na Task 12) ─────────────── -->
            <div id="wikiSubCapacitacao" style="display:none;"></div>
        </div>
```

- [ ] **Step 2: Adicionar o CSS da barra de submódulos**

Em `public/css/app.css`, logo depois da linha `.wiki-action-btn { border-radius:10px; }`:

```css
        .wiki-submodule-bar { display:flex; gap:10px; flex-wrap:wrap; margin:16px 0; }
        .wiki-submodule-bar .btn { border-radius:10px; }
```

- [ ] **Step 3: Implementar a navegação no wikitoca.js**

Em `public/js/wikitoca.js`, substituir a função `loadWikiTocaData` inteira por:

```javascript
        const WIKI_SUBMODULES = {
            conhecimentos: { panel: 'wikiSubConhecimentos', btn: 'wikiSubBtn_conhecimentos' },
            documentos:    { panel: 'wikiSubDocumentos',    btn: 'wikiSubBtn_documentos' },
            capacitacao:   { panel: 'wikiSubCapacitacao',   btn: 'wikiSubBtn_capacitacao' },
        };
        let wikiActiveSubmodule = null;

        // Ao contrário do AutoToca, o WikiToca nunca fica sem painel: clicar no
        // botão já ativo não fecha nada.
        function toggleWikiSubmodule(key) {
            const alvo = WIKI_SUBMODULES[key];
            if (!alvo) return;
            Object.values(WIKI_SUBMODULES).forEach(({ panel, btn }) => {
                const el = document.getElementById(panel);
                if (el) el.style.display = 'none';
                const b = document.getElementById(btn);
                if (b) { b.classList.remove('btn-auto-mapping'); b.classList.add('btn-secondary'); }
            });
            const painel = document.getElementById(alvo.panel);
            if (painel) painel.style.display = 'block';
            const botao = document.getElementById(alvo.btn);
            if (botao) { botao.classList.remove('btn-secondary'); botao.classList.add('btn-auto-mapping'); }

            wikiActiveSubmodule = key;
            if (key === 'conhecimentos') loadWikiEntriesFromSearch();
            if (key === 'documentos') searchWikiDocuments();
            if (key === 'capacitacao') loadCapacitacaoSessions();
        }

        async function loadWikiTocaData() {
            toggleWikiSubmodule(wikiActiveSubmodule || 'conhecimentos');
        }

        async function loadWikiEntriesFromSearch() {
            const query = (document.getElementById('wikiSearchInput')?.value || '').trim();
            try {
                await loadWikiEntries(query ? `?q=${encodeURIComponent(query)}` : '');
            } catch (err) {
                showError('Não foi possível carregar os conhecimentos do WikiToca.');
            }
        }
```

E substituir `clearWikiSearch` por:

```javascript
        function clearWikiSearch() {
            const input = document.getElementById('wikiSearchInput');
            if (input) input.value = '';
            loadWikiEntriesFromSearch();
        }
```

- [ ] **Step 4: Corrigir o listener de Enter da busca de Conhecimentos**

No `DOMContentLoaded` de `public/js/wikitoca.js`, o handler do `wikiSearchInput` ainda chama `loadWikiTocaData()`, que agora recarrega o submódulo inteiro. Trocar por `loadWikiEntriesFromSearch()`, e acrescentar o mesmo para a busca de documentos:

```javascript
            const wikiSearchInput = document.getElementById('wikiSearchInput');
            if (wikiSearchInput) {
                wikiSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        loadWikiEntriesFromSearch();
                    }
                });
            }
            const wikiDocSearchInput = document.getElementById('wikiDocSearchInput');
            if (wikiDocSearchInput) {
                wikiDocSearchInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        searchWikiDocuments();
                    }
                });
            }
```

- [ ] **Step 5: Verificar no navegador**

Rodar o app, abrir a aba WikiToca e confirmar:
- Abre em **Conhecimentos**, com o botão correspondente em verde (`btn-auto-mapping`) e os outros dois em cinza.
- Clicar em Documentos troca o painel e destaca o botão; clicar de novo no botão ativo **não** fecha o painel.
- A busca de Conhecimentos filtra a lista; "Limpar" restaura.
- Nenhum erro no console (`loadCapacitacaoSessions` ainda não existe — por isso a Task 12 vem antes de qualquer clique em Capacitação; se clicar agora, o console acusa `is not defined`, o que é esperado nesta etapa).

- [ ] **Step 6: Commit**

```bash
git add public/index.html public/css/app.css public/js/wikitoca.js
git commit -m "feat(wikitoca): tres submodulos no padrao AutoToca com busca por submodulo"
```

---

## Task 11: UI da busca por conteúdo e da reindexação

**Files:**
- Modify: `public/js/wikitoca.js` (`loadWikiDocuments`, `uploadWikiDocument`, funções novas)

- [ ] **Step 1: Adicionar os helpers de progresso e a busca**

Em `public/js/wikitoca.js`, logo antes de `async function loadWikiDocuments`:

```javascript
        function _wikiDocSetProgress(pct, step) {
            const wrap = document.getElementById('wikiDocProgressWrap');
            const bar = document.getElementById('wikiDocProgressBar');
            const label = document.getElementById('wikiDocProgressStep');
            if (wrap) wrap.style.display = 'block';
            if (bar) bar.style.width = `${Math.max(5, Math.min(100, pct))}%`;
            if (label) label.textContent = step || '';
        }

        function _wikiDocHideProgress() {
            const wrap = document.getElementById('wikiDocProgressWrap');
            if (wrap) wrap.style.display = 'none';
        }

        // Acompanha uma task de background até done/error, atualizando a barra.
        async function _wikiFollowTask(taskId, onStep) {
            while (true) {
                await new Promise(r => setTimeout(r, 800));
                const resp = await fetch(`${API_BASE}/tasks/${taskId}`);
                if (resp.status === 404) throw new Error('A tarefa expirou ou foi cancelada.');
                const task = await resp.json();
                if (onStep) onStep(task.progress || 5, task.step || '');
                if (task.status === 'done') return task;
                if (task.status === 'error') throw new Error(task.error || 'Falha no processamento.');
            }
        }

        function searchWikiDocuments() {
            const q = (document.getElementById('wikiDocSearchInput')?.value || '').trim();
            const ext = (document.getElementById('wikiDocExtFilter')?.value || '').trim();
            const params = new URLSearchParams();
            if (q) params.set('q', q);
            if (ext) params.set('ext', ext);
            const query = params.toString();
            return loadWikiDocuments(query ? `?${query}` : '');
        }

        function clearWikiDocSearch() {
            const input = document.getElementById('wikiDocSearchInput');
            const filtro = document.getElementById('wikiDocExtFilter');
            if (input) input.value = '';
            if (filtro) filtro.value = '';
            searchWikiDocuments();
        }

        // `force` reprocessa também os documentos já marcados como 'ok' e 'empty'.
        // Sem esse caminho, quem instala o Tesseract DEPOIS de subir um PDF
        // escaneado fica preso: o documento ficou 'empty', e o reindex normal
        // (que só pega NULL/pending/error) nunca mais o alcança.
        async function reindexWikiDocuments(force = false) {
            const pergunta = force
                ? 'Reprocessar o texto de TODOS os documentos, inclusive os já indexados? '
                  + 'Use isto depois de instalar o Tesseract. Pode levar vários minutos.'
                : 'Reprocessar o texto dos documentos pendentes? Isso pode levar alguns minutos.';
            if (!await uiConfirm(pergunta, 'Reindexar documentos')) return;
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/documents/reindex`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível iniciar a reindexação.');
                if (!payload.total) { showSuccess('Todos os documentos já estão indexados.'); return; }
                _wikiDocSetProgress(5, 'Iniciando...');
                await _wikiFollowTask(payload.task_id, _wikiDocSetProgress);
                _wikiDocHideProgress();
                showSuccess('Documentos reindexados.');
                searchWikiDocuments();
            } catch (err) {
                _wikiDocHideProgress();
                showError(err.message || 'Erro ao reindexar documentos.');
            }
        }
```

- [ ] **Step 2: Renderizar selo de indexação e snippet**

Em `public/js/wikitoca.js`, substituir o `el.innerHTML = wikiDocuments.map(...)` dentro de `loadWikiDocuments` por:

```javascript
            el.innerHTML = wikiDocuments.map(doc => {
                const status = doc.extract_status || 'pending';
                const selo = {
                    pending: '<span class="wiki-index-badge" title="O texto deste arquivo ainda está sendo processado."><i class="fas fa-spinner fa-spin"></i> Indexando…</span>',
                    empty: '<span class="wiki-index-badge warn" title="Nenhum texto foi extraído deste arquivo. Se for um PDF escaneado, instale o Tesseract e use Reindexar documentos."><i class="fas fa-triangle-exclamation"></i> Sem texto extraído</span>',
                    error: '<span class="wiki-index-badge warn" title="A extração de texto falhou. Use Reindexar documentos para tentar de novo."><i class="fas fa-circle-exclamation"></i> Falha na indexação</span>',
                    ok: ''
                }[status] || '';
                return `
                <div class="wiki-doc-item">
                    <h4>${escapeHtml(doc.original_name || doc.title || '')}</h4>
                    <div class="wiki-meta">${formatFileSize(doc.file_size)} • ${formatDateBr(doc.updated_at)} ${selo}</div>
                    ${doc.snippet ? `<div class="wiki-doc-snippet">${doc.snippet}</div>` : ''}
                    <div style="display:flex; gap:8px;">
                        <a class="btn btn-secondary btn-small" href="${doc.file_url}" target="_blank" rel="noopener"><i class="fas fa-up-right-from-square"></i> Abrir</a>
                        <button class="btn btn-danger btn-small" onclick="deleteWikiDocument(${doc.id})"><i class="fas fa-trash"></i></button>
                    </div>
                </div>`;
            }).join('');
```

> O `doc.snippet` já vem escapado pelo backend (`_wiki_snippet` usa `escape` e só insere `<mark>` em posição conhecida), por isso entra sem `escapeHtml` — que destruiria o destaque.

- [ ] **Step 3: Acompanhar a indexação no upload**

Em `public/js/wikitoca.js`, substituir a função `uploadWikiDocument` **inteira** por:

```javascript
        async function uploadWikiDocument() {
            const fileInput = document.getElementById('wikiDocumentFile');
            const files = Array.from(fileInput?.files || []);
            if (!files.length) return showError('Selecione ao menos um arquivo para upload.');
            const formData = new FormData();
            files.forEach((file) => formData.append('files', file));
            formData.append('title', '');
            const response = await fetch(`${API_BASE}/wikitoca/documents`, { method: 'POST', body: formData });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) return showError(payload.error || 'Falha ao enviar documento(s).');

            clearWikiFileSelection();
            // Antes esta linha limpava #wikiSearchInput, que agora é a busca de
            // Conhecimentos — limpar a busca do próprio submódulo é o correto.
            const docSearch = document.getElementById('wikiDocSearchInput');
            if (docSearch) docSearch.value = '';
            await searchWikiDocuments();

            if (payload.task_id) {
                _wikiDocSetProgress(5, 'Indexando documentos...');
                try {
                    await _wikiFollowTask(payload.task_id, _wikiDocSetProgress);
                } catch (err) {
                    showError(`Arquivo enviado, mas a indexação falhou: ${err.message}`);
                }
                _wikiDocHideProgress();
                await searchWikiDocuments();
            }
            showSuccess(files.length > 1 ? 'Documentos enviados com sucesso!' : 'Documento enviado com sucesso!');
        }
```

> `clearWikiFileSelection()` já zera o `<input type=file>`, o rótulo `#wikiFileName`, o botão de limpar e a classe `wiki-upload-btn-pending` — por isso as quatro linhas manuais que a versão antiga tinha somem.

- [ ] **Step 4: Adicionar o CSS do selo e do snippet**

Em `public/css/app.css`, depois de `.wiki-submodule-bar .btn { border-radius:10px; }`:

```css
        .wiki-index-badge { display:inline-flex; align-items:center; gap:4px; margin-left:8px; font-size:11px; color:#047857; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:99px; padding:1px 8px; }
        .wiki-index-badge.warn { color:#92400e; background:#fffbeb; border-color:#fde68a; }
        .wiki-doc-snippet { font-size:12px; color:#374151; background:#f9fafb; border-left:3px solid #a7f3d0; border-radius:0 6px 6px 0; padding:6px 10px; margin:6px 0 8px; line-height:1.5; }
        .wiki-doc-snippet mark { background:#fde68a; color:#78350f; border-radius:3px; padding:0 2px; }
```

- [ ] **Step 5: Verificar no navegador**

Rodar o app, ir em WikiToca → Documentos e confirmar:
- Subir um `.docx` com uma frase distinta: aparece com selo "Indexando…", a barra verde com o coelho corre e ao terminar o selo some.
- Buscar por uma palavra que só existe **dentro** do arquivo: o documento aparece com o snippet e o termo em destaque amarelo.
- Filtro "PDF" esconde o `.docx`; "Limpar" restaura tudo.
- "Reindexar documentos" pede confirmação no modal temático (não no `confirm()` do sistema) e mostra a barra com o nome do arquivo em processamento.

- [ ] **Step 6: Commit**

```bash
git add public/js/wikitoca.js public/css/app.css
git commit -m "feat(wikitoca): UI da busca por conteudo, selos de indexacao e reindexacao"
```

---

## Task 12: Capacitação — markup, sidebar e ciclo de vida das instâncias

**Files:**
- Modify: `public/index.html` (`#wikiSubCapacitacao`)
- Modify: `public/js/wikitoca.js`
- Modify: `public/css/app.css`

- [ ] **Step 1: Escrever o markup**

Em `public/index.html`, substituir `<div id="wikiSubCapacitacao" style="display:none;"></div>` por:

```html
            <div id="wikiSubCapacitacao" class="cap-layout" style="display:none;">
                <section class="wiki-card cap-main">
                    <div id="capEmptyState" class="cap-empty">
                        <img src="/coelho_wiki.png" alt="" style="width:64px; height:64px; object-fit:contain; opacity:.8;">
                        <h3>Crie sua primeira capacitação</h3>
                        <p>Anexe PDFs, documentos Word ou imagens e converse com a IA sobre eles.</p>
                        <button class="btn btn-auto-mapping" onclick="createCapacitacaoSession()"><i class="fas fa-plus"></i> Nova capacitação</button>
                    </div>

                    <div id="capWorkspace" style="display:none;">
                        <div class="cap-header">
                            <h3 class="wiki-section-title" id="capSessionTitle">—</h3>
                            <div class="cap-header-actions">
                                <button class="btn btn-secondary btn-small" onclick="renameCapacitacaoSession()" title="Renomear capacitação"><i class="fas fa-pen"></i></button>
                                <button class="btn btn-secondary btn-small" onclick="clearCapacitacaoConversation()" title="Limpar conversa (mantém os documentos)"><i class="fas fa-broom"></i></button>
                                <button class="btn btn-danger btn-small" onclick="deleteCapacitacaoSession()" title="Excluir capacitação"><i class="fas fa-trash"></i></button>
                                <button class="btn btn-secondary btn-small cap-drawer-toggle" onclick="toggleCapacitacaoDrawer()"><i class="fas fa-layer-group"></i> <span id="capDrawerCount">Capacitações</span></button>
                            </div>
                        </div>

                        <div class="cap-chips" id="capDocChips"></div>
                        <input id="capFileInput" type="file" accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" multiple style="display:none;" onchange="uploadCapacitacaoDocuments(event)">

                        <div id="capProgressWrap" style="display:none; margin:10px 0;">
                            <div style="font-size:12px; color:#6b7280; margin-bottom:6px;" id="capProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:8px; overflow:visible; margin:0 2px;">
                                <div id="capProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="" style="height:18px;right:-14px;">
                                </div>
                            </div>
                        </div>

                        <div class="itoca-chat-messages cap-messages" id="capMessages"></div>

                        <div class="cap-composer">
                            <textarea id="capQuestionInput" rows="2" placeholder="Pergunte sobre os documentos desta capacitação..."></textarea>
                            <button class="btn btn-auto-mapping" id="capAskBtn" onclick="askCapacitacao()"><i class="fas fa-paper-plane"></i> Enviar</button>
                        </div>
                    </div>
                </section>

                <aside class="cap-sidebar" id="capSidebar">
                    <div class="cap-sidebar-header">
                        <span>Capacitações</span>
                        <button class="btn btn-auto-mapping btn-small" onclick="createCapacitacaoSession()"><i class="fas fa-plus"></i> Nova</button>
                    </div>
                    <div id="capSessionList" class="cap-session-list"></div>
                </aside>
            </div>
```

- [ ] **Step 2: Escrever o CSS**

Em `public/css/app.css`, depois do bloco `.wiki-doc-snippet mark { ... }`:

```css
        /* ---- WikiToca › Capacitação ---- */
        .cap-layout { display:grid; grid-template-columns: 1fr 260px; gap:16px; align-items:start; }
        .cap-main { min-width:0; }
        .cap-header { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
        .cap-header-actions { display:flex; gap:6px; }
        .cap-drawer-toggle { display:none; }
        .cap-empty { text-align:center; padding:36px 16px; color:#4b5563; }
        .cap-empty h3 { color:#065f46; margin:12px 0 6px; }
        .cap-empty p { font-size:13px; margin-bottom:16px; }

        .cap-chips { display:flex; gap:8px; flex-wrap:wrap; padding-bottom:12px; border-bottom:1px solid #d1fae5; margin-bottom:12px; }
        .cap-chip { display:inline-flex; align-items:center; gap:6px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:99px; padding:4px 10px; font-size:12px; color:#065f46; max-width:220px; }
        .cap-chip a { color:inherit; text-decoration:none; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .cap-chip button { background:none; border:none; cursor:pointer; color:#ef4444; font-size:12px; padding:0; line-height:1; }
        .cap-chip.warn { background:#fffbeb; border-color:#fde68a; color:#92400e; }

        .cap-messages { max-height:460px; }
        .cap-source-badge { display:inline-flex; align-items:center; gap:5px; margin-top:8px; font-size:11px; color:#047857; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:99px; padding:2px 9px; }
        .cap-source-badge.web { color:#1e40af; background:#eff6ff; border-color:#bfdbfe; }
        .cap-source-refs { font-size:11px; color:#6b7280; margin-top:4px; }

        .cap-composer { display:flex; gap:8px; align-items:flex-end; margin-top:12px; }
        .cap-composer textarea { flex:1; border:1px solid #bbf7d0; border-radius:10px; padding:10px 12px; font-family:inherit; font-size:14px; resize:vertical; }
        .cap-composer textarea:focus { outline:none; border-color:#10b981; box-shadow:0 0 0 3px rgba(16,185,129,.15); }

        .cap-sidebar { background:#fff; border:1px solid rgba(15,118,110,.15); border-radius:16px; padding:12px; box-shadow:0 6px 18px rgba(15,118,110,.08); }
        .cap-sidebar-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; font-size:12px; font-weight:700; color:#047857; text-transform:uppercase; letter-spacing:.5px; }
        .cap-session-list { display:flex; flex-direction:column; gap:8px; max-height:520px; overflow-y:auto; }
        .cap-session-card { border:1px solid #d1fae5; border-radius:10px; padding:10px; cursor:pointer; transition:background .15s, border-color .15s; }
        .cap-session-card:hover { background:#f0fdf4; }
        .cap-session-card.active { background:#ecfdf5; border-color:#10b981; }
        .cap-session-card h5 { margin:0 0 4px; font-size:13px; color:#065f46; }
        .cap-session-card .cap-session-meta { font-size:11px; color:#6b7280; }

        @media (max-width: 1100px) {
            .cap-layout { grid-template-columns: 1fr; }
            .cap-drawer-toggle { display:inline-flex; }
            .cap-sidebar { position:fixed; top:0; right:0; height:100vh; width:280px; border-radius:0; z-index:1100;
                           transform:translateX(105%); transition:transform .25s ease; overflow-y:auto; }
            .cap-sidebar.open { transform:translateX(0); }
        }
```

- [ ] **Step 3: Implementar o ciclo de vida das instâncias**

Em `public/js/wikitoca.js`, no fim do arquivo (antes do `DOMContentLoaded`):

```javascript
        // =====================================================
        // WikiToca › Capacitação
        // =====================================================
        let capSessions = [];
        let capCurrentSession = null;   // { session, documents, messages }

        async function loadCapacitacaoSessions(keepSelection = true) {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions`);
                if (!resp.ok) throw new Error('Falha ao carregar as capacitações.');
                capSessions = await resp.json();
            } catch (err) {
                showError(err.message || 'Não foi possível carregar as capacitações.');
                capSessions = [];
            }
            renderCapacitacaoSidebar();

            const empty = document.getElementById('capEmptyState');
            const workspace = document.getElementById('capWorkspace');
            if (!capSessions.length) {
                if (empty) empty.style.display = 'block';
                if (workspace) workspace.style.display = 'none';
                capCurrentSession = null;
                return;
            }
            if (empty) empty.style.display = 'none';
            if (workspace) workspace.style.display = 'block';

            const atual = keepSelection && capCurrentSession
                ? capSessions.find(s => s.id === capCurrentSession.session.id)
                : null;
            await selectCapacitacaoSession((atual || capSessions[0]).id);
        }

        function renderCapacitacaoSidebar() {
            const el = document.getElementById('capSessionList');
            if (!el) return;
            const contador = document.getElementById('capDrawerCount');
            if (contador) contador.textContent = `Capacitações (${capSessions.length})`;
            if (!capSessions.length) {
                el.innerHTML = '<div class="wiki-meta">Nenhuma capacitação ainda.</div>';
                return;
            }
            const ativa = capCurrentSession?.session?.id;
            // O título vem do banco sem sanitização — o backend aceita HTML cru
            // (verificado na revisão da Task 6: '<img src=x onerror=alert(1)>' é
            // armazenado literal). Todo campo do WikiToca já passa por escapeHtml;
            // aqui não é exceção.
            el.innerHTML = capSessions.map(s => `
                <div class="cap-session-card${s.id === ativa ? ' active' : ''}" onclick="selectCapacitacaoSession(${s.id})">
                    <h5>${escapeHtml(s.title || 'Nova capacitação')}</h5>
                    <div class="cap-session-meta">${s.documents_count || 0} doc(s) • ${formatDateBr(s.last_message_at || s.updated_at)}</div>
                </div>`).join('');
        }

        async function selectCapacitacaoSession(sessionId) {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${sessionId}`);
                if (!resp.ok) throw new Error('Capacitação não encontrada.');
                capCurrentSession = await resp.json();
            } catch (err) {
                showError(err.message || 'Não foi possível abrir a capacitação.');
                return;
            }
            const titulo = document.getElementById('capSessionTitle');
            if (titulo) titulo.textContent = capCurrentSession.session.title || 'Nova capacitação';
            renderCapacitacaoSidebar();
            renderCapacitacaoChips();
            renderCapacitacaoMessages();
            closeCapacitacaoDrawer();
        }

        async function createCapacitacaoSession() {
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível criar a capacitação.');
                capCurrentSession = { session: payload, documents: [], messages: [] };
                await loadCapacitacaoSessions();
                document.getElementById('capFileInput')?.click();
            } catch (err) {
                showError(err.message || 'Erro ao criar capacitação.');
            }
        }

        async function renameCapacitacaoSession() {
            if (!capCurrentSession) return;
            const novo = await uiPrompt('Novo nome da capacitação:',
                capCurrentSession.session.title || '', 'Renomear capacitação');
            // openSystemDialog resolve `false` no botão Cancelar e `null` no
            // clique fora do modal — sem checar os dois, um cancelamento
            // renomearia a capacitação para "false".
            if (novo === null || novo === false) return;
            const titulo = String(novo).trim();
            if (!titulo) { showError('O título não pode ficar vazio.'); return; }
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: titulo })
                });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível renomear.');
                await loadCapacitacaoSessions();
                showSuccess('Capacitação renomeada.');
            } catch (err) {
                showError(err.message || 'Erro ao renomear capacitação.');
            }
        }

        async function deleteCapacitacaoSession() {
            if (!capCurrentSession) return;
            const nome = capCurrentSession.session.title || 'esta capacitação';
            if (!await uiConfirm(`Excluir "${nome}"? Os documentos anexados e todo o histórico da conversa serão apagados.`,
                'Excluir capacitação')) return;
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}`,
                    { method: 'DELETE' });
                if (!resp.ok) throw new Error('Não foi possível excluir a capacitação.');
                capCurrentSession = null;
                await loadCapacitacaoSessions(false);
                showSuccess('Capacitação excluída.');
            } catch (err) {
                showError(err.message || 'Erro ao excluir capacitação.');
            }
        }

        async function clearCapacitacaoConversation() {
            if (!capCurrentSession) return;
            if (!await uiConfirm('Apagar todo o histórico desta conversa? Os documentos anexados serão mantidos.',
                'Limpar conversa')) return;
            try {
                const resp = await fetch(
                    `${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}/messages`,
                    { method: 'DELETE' });
                if (!resp.ok) throw new Error('Não foi possível limpar a conversa.');
                await selectCapacitacaoSession(capCurrentSession.session.id);
                showSuccess('Conversa limpa.');
            } catch (err) {
                showError(err.message || 'Erro ao limpar a conversa.');
            }
        }

        function toggleCapacitacaoDrawer() {
            document.getElementById('capSidebar')?.classList.toggle('open');
        }

        function closeCapacitacaoDrawer() {
            document.getElementById('capSidebar')?.classList.remove('open');
        }
```

- [ ] **Step 4: Verificar no navegador**

Rodar o app, ir em WikiToca → Capacitação e confirmar:
- Sem instâncias, aparece o estado vazio com o botão "Nova capacitação".
- Criar uma instância abre o seletor de arquivos (cancelar é aceitável nesta etapa) e a caixinha aparece na sidebar, destacada.
- Renomear usa o modal temático `uiPrompt` (não o `prompt()` do sistema); "Limpar conversa" e "Excluir" usam `uiConfirm`.
- Reduzir a janela abaixo de 1100px: a sidebar some, o botão "Capacitações (N)" aparece e abre a gaveta pela direita.
- O console acusa `renderCapacitacaoChips is not defined` / `renderCapacitacaoMessages is not defined` — esperado até a Task 13/14.

- [ ] **Step 5: Commit**

```bash
git add public/index.html public/css/app.css public/js/wikitoca.js
git commit -m "feat(wikitoca): tela da capacitacao com sidebar de instancias"
```

---

## Task 13: Capacitação — chips de documentos e upload

**Files:**
- Modify: `public/js/wikitoca.js`

- [ ] **Step 1: Implementar os chips e o upload**

Em `public/js/wikitoca.js`, depois de `closeCapacitacaoDrawer`:

```javascript
        const CAP_EXT_ICONS = {
            '.pdf': 'fa-file-pdf', '.doc': 'fa-file-word', '.docx': 'fa-file-word',
            '.png': 'fa-file-image', '.jpg': 'fa-file-image', '.jpeg': 'fa-file-image',
        };

        function renderCapacitacaoChips() {
            const el = document.getElementById('capDocChips');
            if (!el || !capCurrentSession) return;
            const chips = (capCurrentSession.documents || []).map(doc => {
                const icone = CAP_EXT_ICONS[(doc.file_ext || '').toLowerCase()] || 'fa-file';
                const status = doc.extract_status || 'pending';
                const aviso = status === 'pending'
                    ? '<i class="fas fa-spinner fa-spin" title="Processando o texto deste arquivo..."></i>'
                    : (status === 'ok' ? '' :
                       '<i class="fas fa-triangle-exclamation" title="Sem texto extraído — a IA não consegue consultar este arquivo. Para imagens e PDFs escaneados, instale o Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"></i>');
                const classe = (status === 'empty' || status === 'error') ? 'cap-chip warn' : 'cap-chip';
                return `
                    <span class="${classe}">
                        <i class="fas ${icone}"></i>
                        <a href="${doc.file_url}" target="_blank" rel="noopener" title="${escapeHtml(doc.original_name)}">${escapeHtml(doc.original_name)}</a>
                        ${aviso}
                        <button onclick="deleteCapacitacaoDocument(${doc.id})" title="Remover documento">&times;</button>
                    </span>`;
            }).join('');
            el.innerHTML = chips + `
                <button class="btn btn-secondary btn-small" onclick="document.getElementById('capFileInput').click()">
                    <i class="fas fa-paperclip"></i> Anexar
                </button>`;
        }

        function _capSetProgress(pct, step) {
            const wrap = document.getElementById('capProgressWrap');
            const bar = document.getElementById('capProgressBar');
            const label = document.getElementById('capProgressStep');
            if (wrap) wrap.style.display = 'block';
            if (bar) bar.style.width = `${Math.max(5, Math.min(100, pct))}%`;
            if (label) label.textContent = step || '';
        }

        function _capHideProgress() {
            const wrap = document.getElementById('capProgressWrap');
            if (wrap) wrap.style.display = 'none';
        }

        async function uploadCapacitacaoDocuments(event) {
            const input = event?.target;
            const files = Array.from(input?.files || []);
            if (!capCurrentSession || !files.length) { if (input) input.value = ''; return; }
            const formData = new FormData();
            files.forEach(f => formData.append('files', f));
            try {
                _capSetProgress(5, 'Enviando arquivos...');
                const resp = await fetch(
                    `${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}/documents`,
                    { method: 'POST', body: formData });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível enviar os arquivos.');
                await _wikiFollowTask(payload.task_id, _capSetProgress);
                _capHideProgress();
                await loadCapacitacaoSessions();
                showSuccess('Documento(s) adicionado(s) à capacitação.');
            } catch (err) {
                _capHideProgress();
                showError(err.message || 'Erro ao enviar documentos.');
                await selectCapacitacaoSession(capCurrentSession.session.id);
            } finally {
                if (input) input.value = '';
            }
        }

        async function deleteCapacitacaoDocument(documentId) {
            if (!await uiConfirm('Remover este documento da capacitação?', 'Remover documento')) return;
            try {
                const resp = await fetch(`${API_BASE}/wikitoca/capacitacao/documents/${documentId}`,
                    { method: 'DELETE' });
                if (!resp.ok) throw new Error('Não foi possível remover o documento.');
                await loadCapacitacaoSessions();
            } catch (err) {
                showError(err.message || 'Erro ao remover documento.');
            }
        }
```

- [ ] **Step 2: Verificar no navegador**

Rodar o app, ir em WikiToca → Capacitação e confirmar:
- Anexar um `.pdf` ou `.docx`: a barra verde com o coelho corre com os passos "Enviando arquivos…" → "Lendo 1 de 1 — nome" → "Definindo o título da capacitação…".
- Ao terminar, o título da instância na sidebar e no cabeçalho muda para um nome gerado pela IA (se SAI/OpenRouter estiverem configurados; senão continua "Nova capacitação" e o `app.log` registra o motivo).
- O chip aparece com o ícone do tipo; clicar no nome abre o arquivo; o `×` pede confirmação e remove.
- Anexar um `.png` sem Tesseract instalado: o chip fica amarelo com o `⚠` e o tooltip com o link de instalação.

- [ ] **Step 3: Commit**

```bash
git add public/js/wikitoca.js
git commit -m "feat(wikitoca): chips de documentos e upload na capacitacao"
```

---

## Task 14: Capacitação — chat e selos de origem

**Files:**
- Modify: `public/js/wikitoca.js`

- [ ] **Step 1: Implementar o chat**

Em `public/js/wikitoca.js`, depois de `deleteCapacitacaoDocument`:

```javascript
        // `source_kind` tem QUATRO valores. O quarto, 'none', foi criado na Task 8
        // para a resposta "não encontrei em lugar nenhum": marcar essa mensagem
        // como 'web' acenderia um selo de "resposta da internet" numa mensagem que
        // diz exatamente o contrário. Ausência da chave aqui = sem selo, que é o
        // comportamento desejado — o `CAP_SOURCE_BADGES[m.source_kind]` devolve
        // undefined e o template já testa por isso.
        const CAP_SOURCE_BADGES = {
            documents: { icon: '📄', label: 'Documentos desta capacitação', cls: '' },
            wiki:      { icon: '📚', label: 'Base WikiToca', cls: '' },
            web:       { icon: '🌐', label: 'Pesquisa na web', cls: 'web' },
        };

        function renderCapacitacaoMessages(pendente = null) {
            const el = document.getElementById('capMessages');
            if (!el || !capCurrentSession) return;
            const msgs = capCurrentSession.messages || [];
            if (!msgs.length && !pendente) {
                el.innerHTML = '<div class="wiki-meta">Anexe documentos e faça a primeira pergunta.</div>';
                return;
            }
            const bolhas = msgs.map(m => {
                if (m.role === 'user') {
                    return `
                        <div class="itoca-msg user">
                            <div class="itoca-msg-avatar"><span class="itoca-avatar-initial">🧑</span></div>
                            <div class="itoca-msg-bubble">${escapeHtml(m.content)}</div>
                        </div>`;
                }
                const badge = CAP_SOURCE_BADGES[m.source_kind];
                const refs = (m.source_refs || []).map(r => escapeHtml(r)).join(', ');
                return `
                    <div class="itoca-msg assistant">
                        <div class="itoca-msg-avatar"><img src="/images/itoca-avatar.png" alt=""></div>
                        <div class="itoca-msg-bubble itoca-markdown">
                            ${_itocaRenderMarkdown(m.content)}
                            ${badge ? `<div class="cap-source-badge ${badge.cls}">${badge.icon} ${badge.label}</div>` : ''}
                            ${refs ? `<div class="cap-source-refs">${refs}</div>` : ''}
                        </div>
                    </div>`;
            }).join('');

            const digitando = pendente ? `
                <div class="itoca-msg assistant">
                    <div class="itoca-msg-avatar"><img src="/images/itoca-avatar.png" alt=""></div>
                    <div class="itoca-msg-bubble"><i class="fas fa-spinner fa-spin"></i> ${escapeHtml(pendente)}</div>
                </div>` : '';

            el.innerHTML = bolhas + digitando;
            el.scrollTop = el.scrollHeight;
        }

        async function askCapacitacao() {
            if (!capCurrentSession) return;
            const input = document.getElementById('capQuestionInput');
            const botao = document.getElementById('capAskBtn');
            const pergunta = (input?.value || '').trim();
            if (!pergunta) { showError('Digite uma pergunta.'); return; }

            capCurrentSession.messages.push({ role: 'user', content: pergunta, source_refs: [] });
            if (input) input.value = '';
            if (botao) botao.disabled = true;
            renderCapacitacaoMessages('Consultando os documentos...');

            try {
                const resp = await fetch(
                    `${API_BASE}/wikitoca/capacitacao/sessions/${capCurrentSession.session.id}/ask`,
                    {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ question: pergunta })
                    });
                const payload = await resp.json().catch(() => ({}));
                if (!resp.ok) throw new Error(payload.error || 'Não foi possível enviar a pergunta.');
                await _wikiFollowTask(payload.task_id,
                    (_pct, step) => renderCapacitacaoMessages(step || 'Processando...'));
                await selectCapacitacaoSession(capCurrentSession.session.id);
            } catch (err) {
                showError(err.message || 'Erro ao consultar a IA.');
                // Recarrega o histórico real: a pergunta já foi gravada no banco,
                // mas a resposta não veio.
                if (capCurrentSession) await selectCapacitacaoSession(capCurrentSession.session.id);
            } finally {
                if (botao) botao.disabled = false;
            }
        }
```

- [ ] **Step 2: Enviar com Enter**

No `DOMContentLoaded` de `public/js/wikitoca.js`, acrescentar:

```javascript
            const capInput = document.getElementById('capQuestionInput');
            if (capInput) {
                capInput.addEventListener('keydown', (event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                        event.preventDefault();
                        askCapacitacao();
                    }
                });
            }
```

- [ ] **Step 3: Verificar no navegador**

Com uma capacitação já contendo um documento indexado:
- Perguntar algo respondido pelo documento: a resposta vem com o selo verde "📄 Documentos desta capacitação" e o nome do arquivo abaixo.
- Perguntar algo que só existe num conhecimento registrado do WikiToca: selo "📚 Base WikiToca".
- Perguntar algo totalmente fora (ex.: "qual a cotação do dólar hoje?"): selo azul "🌐 Pesquisa na web".
- Enter envia, Shift+Enter quebra linha; o botão fica desabilitado durante o processamento.
- Fazer uma pergunta de follow-up ("e no caso de férias?") e confirmar que a resposta considera o contexto anterior.
- Trocar de instância na sidebar e voltar: o histórico de cada uma é o seu.

- [ ] **Step 4: Commit**

```bash
git add public/js/wikitoca.js
git commit -m "feat(wikitoca): chat da capacitacao com selos de origem da resposta"
```

---

## Task 15: Verificação final e documentação

**Files:**
- Modify: `CLAUDE.md`
- Test: suíte completa

- [ ] **Step 1: Rodar a suíte inteira**

Run: `pytest tests/ -v`
Expected: PASS em tudo, sem skips inesperados.

- [ ] **Step 2: Passar o app inteiro no navegador**

Rodar `python app.py`, abrir `http://localhost:3000` e percorrer, com o console aberto e **zero erros**:
1. WikiToca → Conhecimentos: listar, buscar, criar, editar, excluir, ordenar A-Z/Z-A, exportar e importar `.xlsx`.
2. WikiToca → Documentos: subir, buscar por nome, buscar por conteúdo, filtrar por tipo, reindexar, exportar e importar `.zip`, excluir.
3. WikiToca → Capacitação: criar, anexar PDF/Word/imagem, título por IA, perguntar (as três origens), follow-up, limpar conversa, renomear, excluir, gaveta abaixo de 1100px.
4. iToca e AutoToca: abrir as duas abas e confirmar que continuam funcionando (a Task 9 mexeu no `itoca-autotoca.js`).

- [ ] **Step 3: Documentar o padrão no CLAUDE.md**

Em `CLAUDE.md`, na seção "Padrões do projeto", acrescentar:

```markdown
### WikiToca — submódulos

O WikiToca segue o mesmo padrão de submódulo do AutoToca: uma barra de botões
(`.wiki-submodule-bar`) alterna painéis via `toggleWikiSubmodule(key)` em
`public/js/wikitoca.js`. Diferença: o WikiToca **nunca fica sem painel** — clicar
no botão já ativo não fecha nada. Todo o JS do módulo vive em
`public/js/wikitoca.js` (não em `itoca-autotoca.js`).

O texto extraído dos documentos fica cacheado em `wiki_documents.extracted_text`
(`extract_status`: `pending`/`ok`/`empty`/`error`). Qualquer feature que precise
buscar dentro de arquivos deve usar esse cache, não reprocessar o arquivo.

Os documentos da Capacitação (`wiki_training_documents`) são **isolados por
instância**: não aparecem no submódulo Documentos nem entram na base do iToca.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: documenta o padrao de submodulos do WikiToca"
```

- [ ] **Step 5: Abrir o PR**

```bash
git push -u origin claude/wikitoca-module-redesign-60cc7e
```

```bash
gh pr create --title "feat(wikitoca): submodulos + modulo Capacitacao" --body "Reorganiza o WikiToca em tres submodulos no padrao AutoToca (Conhecimentos, Documentos, Capacitacao), adiciona busca por conteudo nos documentos e cria a Capacitacao — instancias com documentos proprios e chat com IA em cascata (documentos -> base WikiToca -> web).

Spec: docs/superpowers/specs/2026-08-28-wikitoca-submodulos-capacitacao-design.md
Plano: docs/superpowers/plans/2026-08-28-wikitoca-submodulos-capacitacao.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
