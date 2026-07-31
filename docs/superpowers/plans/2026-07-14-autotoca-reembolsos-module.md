# AutoToca — Submódulo "Reembolsos" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar ao AutoToca um submódulo "Reembolsos" que lê comprovantes fiscais via IA de visão e preenche automaticamente (sem enviar sozinho) o portal `https://ereembolso.stefanini.com.br`, nos fluxos "Deslocamento & Estacionamento" e "Almoço com Cliente".

**Architecture:** Segue exatamente os padrões já usados pelo Chamado Jurídico: rota Flask em `routes/reembolsos.py` (executada no namespace de `app.py`), tabela de histórico + dict de tasks em memória com polling assíncrono (`_reembolso_task_set/get/cleanup`), robô Playwright em `integrations/reembolso_robot.py` com perfil de navegador persistente e navegador visível (nunca clica em Enviar sozinho), extração de dados dos comprovantes via `_reembolso_extract_receipt()` (OpenRouter com visão, mesmo padrão de `_portfolio_generate_offer_from_llm`), e frontend em `public/index.html` + `public/js/core.js` reaproveitando o `BgTaskManager` e a barra de progresso com o coelho verde.

**Tech Stack:** Flask, SQLite, Playwright (sync API), OpenRouter (visão), pytest + Flask test client, vanilla JS.

---

## Contexto para quem for implementar (leia antes de começar)

- Referência viva de padrão a copiar: `routes/autotoca.py` (rotas do Chamado Jurídico, linhas 303–740) e `integrations/forms_robot.py` (robô Playwright do Chamado Jurídico). **Leia os dois arquivos inteiros antes da Tarefa 6.**
- O portal e-Reembolso **não é** Microsoft Forms — é ASP.NET com campos nomeados e combos (alguns nativos `<select>`, alguns tipo Select2/autocomplete). O robô do Chamado Jurídico faz matching de "perguntas" (`_MATCH_JS`), o que **não se aplica** aqui. Este plano usa localização de campo por **texto do label mais próximo**, que é mais frágil neste site do que era no Forms — por isso o spec (`docs/superpowers/specs/2026-07-14-autotoca-reembolsos-design.md`, seção "Itens a confirmar ao vivo") documenta 4 pontos que só serão confirmados rodando o robô de verdade, logado, com o usuário observando. **Isso é esperado, não é uma falha do plano.** A Tarefa 15 é dedicada a essa sessão de ajuste ao vivo.
- Não existe suíte de testes automatizados para `forms_robot.py` neste projeto (confirmado: `tests/` não tem nenhum arquivo relacionado) — a interação real com o navegador não é testável sem a sessão logada do usuário. Este plano só aplica TDD às partes determinísticas (agregação de valores/datas, extração via IA mockada, rotas Flask, helpers puros). O robô Playwright em si é validado manualmente na Tarefa 15, como o Chamado Jurídico sempre foi.
- Rode os testes com: `python -m pytest tests/ -v` (a partir da raiz do repo).

---

## Mapa de arquivos

- **Modificar** `app.py`:
  - Novas constantes de diretório de upload (perto da linha 193)
  - Três novas tabelas no `init_db()` (perto da linha 832)
  - Novo helper `_reembolso_extract_receipt()` perto de `_portfolio_generate_offer_from_llm` (linha ~8828)
  - Adicionar `'reembolsos'` em `ROUTE_MODULES` (linha ~11779)
- **Criar** `routes/reembolsos.py` — todas as rotas HTTP do submódulo
- **Criar** `integrations/reembolso_robot.py` — robô Playwright (perfil persistente, overlay, preenchimento por label, gerador de arquivo corrompido)
- **Criar** `tests/test_reembolsos.py` — testes das partes determinísticas (agregação, rotas, extração mockada)
- **Modificar** `public/index.html` — botão + painel do submódulo (perto da linha 863, junto aos outros botões do AutoToca)
- **Modificar** `public/js/core.js` — funções de UI, upload, polling (perto das funções `_cj*`/`runChamadoJuridicoRobot`)

---

### Task 1: Schema do banco — 3 novas tabelas

**Files:**
- Modify: `app.py:193` (constantes de diretório)
- Modify: `app.py:832` (dentro de `init_db()`, logo após o índice do Chamado Jurídico)
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_reembolsos.py`:

```python
"""Testes do submódulo AutoToca Reembolsos."""
import app as toca


def test_schema_reembolsos_tabelas_existem(db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row['name'] for row in c.fetchall()}
    conn.close()
    assert 'reembolso_origem_historico' in tables
    assert 'account_reembolso_enderecos' in tables
    assert 'reembolsos_history' in tables


def test_account_reembolso_enderecos_um_por_conta(db_path, sample_client_id):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Teste')")
    account_id = c.lastrowid
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?)",
        (account_id, 'Rua A, 100, São Paulo, SP')
    )
    conn.commit()
    # UNIQUE(account_id) — um segundo INSERT com ON CONFLICT deve substituir, não duplicar
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?) "
        "ON CONFLICT(account_id) DO UPDATE SET endereco = excluded.endereco",
        (account_id, 'Rua B, 200, São Paulo, SP')
    )
    conn.commit()
    c.execute("SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?", (account_id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]['endereco'] == 'Rua B, 200, São Paulo, SP'
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v`
Expected: `FAIL` — `sqlite3.OperationalError: no such table: reembolso_origem_historico` (ou equivalente).

- [ ] **Step 3: Adicionar as constantes de diretório**

Em `app.py`, logo após a linha 194 (`CHAMADO_JURIDICO_UPLOAD_DIR.mkdir(...)`):

```python
REEMBOLSOS_UPLOAD_DIR = AUTOTOCA_UPLOAD_DIR / 'reembolsos'
REEMBOLSOS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Adicionar as 3 tabelas em `init_db()`**

Em `app.py`, logo após a linha 832 (`c.execute('CREATE INDEX IF NOT EXISTS idx_chamado_juridico_history_created_at ...')`), antes de `outlook_graph_ensure_schema(conn)`:

```python
    # Reembolsos — histórico de endereços de Origem digitados (dropdown de
    # reaproveitamento) e endereço de Destino salvo por conta.
    c.execute('''CREATE TABLE IF NOT EXISTS reembolso_origem_historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        texto TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS account_reembolso_enderecos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        endereco TEXT NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
        UNIQUE(account_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reembolsos_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        files_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_reembolsos_history_created_at ON reembolsos_history(created_at)')
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v`
Expected: `PASS` (2 testes).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona schema do submódulo Reembolsos"
```

---

### Task 2: Helper puro de agregação (soma de valores, período min/max)

**Files:**
- Modify: `app.py` (perto de `parse_currency_to_cents`/`format_currency_br`, ver `tests/test_helpers.py:9-14` para localizar)
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_aggregate_receipts_soma_e_periodo():
    extracted = [
        {'data': '2026-06-10', 'valor_cents': 1500},
        {'data': '2026-06-08', 'valor_cents': 2000},
        {'data': '2026-06-12', 'valor_cents': 999},
    ]
    result = toca._reembolso_aggregate_receipts(extracted)
    assert result['valor_total_cents'] == 4499
    assert result['periodo_inicio'] == '2026-06-08'
    assert result['periodo_fim'] == '2026-06-12'
    assert result['quantidade'] == 3


def test_aggregate_receipts_ignora_entradas_invalidas():
    extracted = [
        {'data': '2026-06-10', 'valor_cents': 1500},
        {'data': None, 'valor_cents': None},
    ]
    result = toca._reembolso_aggregate_receipts(extracted)
    assert result['valor_total_cents'] == 1500
    assert result['periodo_inicio'] == '2026-06-10'
    assert result['periodo_fim'] == '2026-06-10'
    assert result['quantidade'] == 2  # conta todos os arquivos anexados, válidos ou não


def test_aggregate_receipts_lista_vazia():
    result = toca._reembolso_aggregate_receipts([])
    assert result == {'valor_total_cents': 0, 'periodo_inicio': None, 'periodo_fim': None, 'quantidade': 0}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k aggregate`
Expected: `FAIL` com `AttributeError: module 'app' has no attribute '_reembolso_aggregate_receipts'`.

- [ ] **Step 3: Implementar**

Adicionar em `app.py`, logo abaixo de `format_currency_br`:

```python
def _reembolso_aggregate_receipts(extracted):
    """Soma valores e calcula período min/max de uma lista de comprovantes
    já extraídos via IA. Cada item: {'data': 'YYYY-MM-DD'|None, 'valor_cents': int|None}.
    Entradas sem data/valor não contam na soma/período, mas contam na quantidade
    (o usuário anexou o arquivo, mesmo que a IA não tenha lido)."""
    valido = [e for e in extracted if e.get('data') and e.get('valor_cents') is not None]
    datas = sorted(e['data'] for e in valido)
    return {
        'valor_total_cents': sum(e['valor_cents'] for e in valido),
        'periodo_inicio': datas[0] if datas else None,
        'periodo_fim': datas[-1] if datas else None,
        'quantidade': len(extracted),
    }
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k aggregate`
Expected: `PASS` (3 testes).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona agregação de valor/período dos comprovantes"
```

---

### Task 3: Extração de comprovante via IA de visão

**Files:**
- Modify: `app.py` (perto de `_portfolio_generate_offer_from_llm`, linha 8828)
- Test: `tests/test_reembolsos.py`

Reaproveita o padrão de `_portfolio_generate_offer_from_llm` (`app.py:8828-8897`): OpenRouter com `image_url` em base64 primeiro (o template SAI de prompt simples só aceita texto), sem fallback de visão para SAI.

- [ ] **Step 1: Escrever o teste que falha (mock do OpenRouter)**

Adicionar a `tests/test_reembolsos.py`:

```python
import json as _json
from unittest.mock import patch, MagicMock


def test_extract_receipt_parseia_resposta_openrouter(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': '{"data": "2026-06-10", "valor": 45.90}'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': '2026-06-10', 'valor_cents': 4590}


def test_extract_receipt_sem_openrouter_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: None)
    result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')
    assert result == {'data': None, 'valor_cents': None}


def test_extract_receipt_resposta_invalida_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': 'não é json'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': None, 'valor_cents': None}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k extract_receipt`
Expected: `FAIL` com `AttributeError: module 'app' has no attribute '_reembolso_extract_receipt'`.

- [ ] **Step 3: Implementar**

Adicionar em `app.py`, logo abaixo de `_reembolso_aggregate_receipts` (Task 2):

```python
def _reembolso_extract_receipt(file_bytes, mime):
    """Lê um comprovante (imagem) via IA de visão e extrai {data, valor_cents}.
    Usa OpenRouter com image_url em base64 — o template SAI de prompt simples só
    aceita texto, então não há fallback de visão para SAI (mesma exceção documentada
    em _portfolio_generate_offer_from_llm)."""
    or_key = _resolve_setting('openrouter_api_key', 'OPENROUTER_API_KEY')
    if not or_key:
        return {'data': None, 'valor_cents': None}

    or_settings = _load_app_settings_map(['openrouter_model', 'openrouter_site_url', 'openrouter_app_name'])
    model = (or_settings.get('openrouter_model') or os.environ.get('OPENROUTER_MODEL', 'stepfun/step-3.5-flash:free')).strip() or 'stepfun/step-3.5-flash:free'
    site_url = (or_settings.get('openrouter_site_url') or os.environ.get('OPENROUTER_SITE_URL', 'http://localhost')).strip() or 'http://localhost'
    app_name = (or_settings.get('openrouter_app_name') or os.environ.get('OPENROUTER_APP_NAME', 'TocaDoCoelho')).strip() or 'TocaDoCoelho'

    image_data = base64.b64encode(file_bytes).decode('utf-8')
    prompt = (
        "Você está lendo um comprovante fiscal brasileiro (nota fiscal, recibo ou "
        "cupom). Extraia a data da despesa e o valor total pago. "
        'Retorne EXCLUSIVAMENTE um objeto JSON válido no formato exato: '
        '{"data":"YYYY-MM-DD","valor":123.45}. '
        "Se não conseguir identificar a data ou o valor com confiança, use null "
        "no campo correspondente. Não inclua markdown nem texto fora do JSON."
    )
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'Você é um leitor de comprovantes fiscais. Responda SEMPRE e SOMENTE com JSON válido.'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{image_data}'}}
            ]}
        ],
        'temperature': 0.1
    }
    try:
        req = urllib.request.Request(
            'https://openrouter.ai/api/v1/chat/completions',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {or_key}',
                'HTTP-Referer': site_url,
                'X-Title': app_name
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        choices = data.get('choices') or []
        raw = (choices[0].get('message') or {}).get('content', '') if choices else ''
        parsed = json.loads(raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
        data_str = parsed.get('data')
        valor = parsed.get('valor')
        valor_cents = round(float(valor) * 100) if isinstance(valor, (int, float)) else None
        return {'data': data_str if isinstance(data_str, str) else None, 'valor_cents': valor_cents}
    except Exception as e:
        logger.warning(f'[Reembolsos][OpenRouter] Falha ao extrair comprovante: {e}')
        return {'data': None, 'valor_cents': None}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k extract_receipt`
Expected: `PASS` (3 testes).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona extração de comprovante via IA de visão"
```

---

### Task 4: Gerador de arquivo de imagem corrompido

**Files:**
- Create: `integrations/reembolso_robot.py`
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_gerar_arquivo_corrompido(tmp_path):
    from integrations.reembolso_robot import gerar_comprovante_corrompido
    target_dir = tmp_path / 'pedagio'
    target_dir.mkdir()
    path = gerar_comprovante_corrompido(target_dir)
    assert path.exists()
    assert path.suffix == '.jpg'
    content = path.read_bytes()
    assert len(content) > 0
    # Não é um JPEG válido: não começa com a assinatura JPEG (FF D8 FF)
    assert content[:3] != b'\xff\xd8\xff'
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k corrompido`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'integrations.reembolso_robot'`.

- [ ] **Step 3: Implementar**

Criar `integrations/reembolso_robot.py`:

```python
# -*- coding: utf-8 -*-
"""Robô visual do submódulo Reembolsos.

Abre o portal e-Reembolso (https://ereembolso.stefanini.com.br) num navegador
controlado (Playwright) visível na máquina do usuário, preenche os campos dos
fluxos "Deslocamento & Estacionamento" (/Reembolso/Deslocamentos.aspx) e
"Almoço com Cliente" (/Reembolso/OutrasDespesas.aspx), e para no botão final
para o usuário revisar e enviar manualmente — o robô nunca envia sozinho.

Diferente do robô do Chamado Jurídico (Microsoft Forms, perguntas numeradas),
este portal é ASP.NET com campos nomeados. Os campos são localizados por
texto do label mais próximo, com fallback documentado quando o seletor não
bate — os seletores exatos (id/name dos combos) foram parcialmente
inspecionados e serão ajustados na primeira execução real junto com o
usuário (ver docs/superpowers/specs/2026-07-14-autotoca-reembolsos-design.md,
seção "Itens a confirmar ao vivo").
"""

import os
import sys
import threading
import uuid
from pathlib import Path

_ROBOT_LOCK = threading.Lock()

LOGIN_TIMEOUT_SECONDS = 300
REVIEW_TIMEOUT_SECONDS = 900
TYPE_DELAY_MS = 30

DESLOCAMENTOS_URL = 'https://ereembolso.stefanini.com.br/Reembolso/Deslocamentos.aspx'
OUTRAS_DESPESAS_URL = 'https://ereembolso.stefanini.com.br/Reembolso/OutrasDespesas.aspx'


class ReembolsoRobotError(Exception):
    pass


def _profile_dir():
    base = (
        Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
        if sys.platform == 'win32'
        else Path.home() / '.toca-do-coelho'
    )
    path = base / 'reembolso-robot-profile'
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def gerar_comprovante_corrompido(target_dir):
    """Gera um arquivo de imagem propositalmente inválido (não é um JPEG real),
    usado como anexo quando o campo de pedágio é exigido pelo site mas o
    usuário não anexou nenhum comprovante próprio."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f'sem-comprovante-{uuid.uuid4().hex[:8]}.jpg'
    path.write_bytes(b'\x00\x00\x00 nao-e-um-jpeg-valido \x00\x00\x00')
    return path
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k corrompido`
Expected: `PASS`.

- [ ] **Step 5: Commit**

```bash
git add integrations/reembolso_robot.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): cria módulo do robô com gerador de comprovante corrompido"
```

---

### Task 5: Rotas de apoio — histórico de Origem e endereço por Conta

**Files:**
- Create: `routes/reembolsos.py`
- Modify: `app.py:11779` (adicionar `'reembolsos'` a `ROUTE_MODULES`)
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_origem_historico_vazio_por_padrao(client):
    resp = client.get('/api/autotoca/reembolsos/origem-historico')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_origem_historico_lista_mais_recentes_primeiro(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reembolso_origem_historico (texto) VALUES ('Rua A, 1, São Paulo, SP')")
    c.execute("INSERT INTO reembolso_origem_historico (texto) VALUES ('Rua B, 2, São Paulo, SP')")
    conn.commit()
    conn.close()
    resp = client.get('/api/autotoca/reembolsos/origem-historico')
    assert resp.status_code == 200
    textos = [r['texto'] for r in resp.get_json()]
    assert textos == ['Rua B, 2, São Paulo, SP', 'Rua A, 1, São Paulo, SP']


def test_conta_endereco_nao_encontrado_retorna_null(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Sem Endereco')")
    account_id = c.lastrowid
    conn.commit()
    conn.close()
    resp = client.get(f'/api/autotoca/reembolsos/conta-endereco/{account_id}')
    assert resp.status_code == 200
    assert resp.get_json() == {'endereco': None}


def test_conta_endereco_encontrado(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Com Endereco')")
    account_id = c.lastrowid
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?)",
        (account_id, 'Av. Paulista, 1000, São Paulo, SP')
    )
    conn.commit()
    conn.close()
    resp = client.get(f'/api/autotoca/reembolsos/conta-endereco/{account_id}')
    assert resp.status_code == 200
    assert resp.get_json() == {'endereco': 'Av. Paulista, 1000, São Paulo, SP'}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k "origem_historico or conta_endereco"`
Expected: `FAIL` — `404 NOT FOUND` (rota não existe).

- [ ] **Step 3: Implementar**

Criar `routes/reembolsos.py`:

```python
# -*- coding: utf-8 -*-
# Rotas do submódulo "reembolsos" do AutoToca (Bloco 3 — modularização).
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a todos os helpers/globals de app.py e registra as rotas no
# mesmo objeto Flask `app`.

REEMBOLSO_ROBOT_TASKS = {}
REEMBOLSO_ROBOT_TASKS_LOCK = threading.Lock()


def _reembolso_task_set(task_id, updates):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        task = REEMBOLSO_ROBOT_TASKS.get(task_id, {})
        task.update(updates)
        REEMBOLSO_ROBOT_TASKS[task_id] = task


def _reembolso_task_get(task_id):
    with REEMBOLSO_ROBOT_TASKS_LOCK:
        return dict(REEMBOLSO_ROBOT_TASKS.get(task_id) or {})


def _reembolso_task_cleanup(task_id, delay=300):
    def _cleanup():
        time.sleep(delay)
        with REEMBOLSO_ROBOT_TASKS_LOCK:
            REEMBOLSO_ROBOT_TASKS.pop(task_id, None)
    threading.Thread(target=_cleanup, daemon=True).start()


@app.route('/api/autotoca/reembolsos/origem-historico', methods=['GET'])
def reembolsos_origem_historico():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT texto FROM reembolso_origem_historico ORDER BY created_at DESC LIMIT 30')
        rows = c.fetchall()
        conn.close()
        return jsonify([{'texto': r['texto']} for r in rows])
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /origem-historico: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/conta-endereco/<int:account_id>', methods=['GET'])
def reembolsos_conta_endereco(account_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?', (account_id,))
        row = c.fetchone()
        conn.close()
        return jsonify({'endereco': row['endereco'] if row else None})
    except Exception as e:
        logger.exception(f'[Reembolsos] GET /conta-endereco/{account_id}: {e}')
        return jsonify({'error': str(e)}), 500
```

Nota: a lista de textos em `reembolsos_origem_historico` retorna `[{'texto': ...}]` (não uma lista simples de strings) para deixar espaço a metadados futuros sem quebrar o frontend — mas o teste do Step 1 já espera exatamente esse formato.

Corrigir o teste `test_origem_historico_lista_mais_recentes_primeiro` acima: como os dois `INSERT` podem cair no mesmo timestamp em SQLite (resolução de segundo), adicionar `id DESC` como desempate. Ajustar a query para:

```python
c.execute('SELECT texto FROM reembolso_origem_historico ORDER BY created_at DESC, id DESC LIMIT 30')
```

Em `app.py`, na linha 11779, adicionar `'reembolsos'` à lista:

```python
ROUTE_MODULES = ['clients', 'accounts', 'activities_agenda', 'kanban', 'campaigns',
                 'whatsapp', 'outlook', 'itoca', 'autotoca', 'wikitoca',
                 'portfolio', 'config', 'home', 'reembolsos']
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k "origem_historico or conta_endereco"`
Expected: `PASS` (4 testes).

- [ ] **Step 5: Commit**

```bash
git add routes/reembolsos.py app.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona rotas de histórico de origem e endereço por conta"
```

---

### Task 6: Rota de extração de comprovante (upload único)

**Files:**
- Modify: `routes/reembolsos.py`
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_extract_endpoint_sem_arquivo(client):
    resp = client.post('/api/autotoca/reembolsos/extract')
    assert resp.status_code == 400


def test_extract_endpoint_com_arquivo(client, monkeypatch):
    monkeypatch.setattr(toca, '_reembolso_extract_receipt', lambda b, m: {'data': '2026-06-10', 'valor_cents': 4590})
    from io import BytesIO
    resp = client.post(
        '/api/autotoca/reembolsos/extract',
        data={'file': (BytesIO(b'fake-bytes'), 'nota.jpg', 'image/jpeg')},
        content_type='multipart/form-data'
    )
    assert resp.status_code == 200
    assert resp.get_json() == {'data': '2026-06-10', 'valor_cents': 4590}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k extract_endpoint`
Expected: `FAIL` — `404 NOT FOUND`.

- [ ] **Step 3: Implementar**

Adicionar a `routes/reembolsos.py`:

```python
@app.route('/api/autotoca/reembolsos/extract', methods=['POST'])
def reembolsos_extract():
    try:
        if 'file' not in request.files or not request.files['file'].filename:
            return jsonify({'error': 'Nenhum arquivo enviado.'}), 400
        file = request.files['file']
        file_bytes = file.read()
        mime = (file.mimetype or 'image/jpeg').split(';')[0].strip() or 'image/jpeg'
        result = _reembolso_extract_receipt(file_bytes, mime)
        return jsonify(result)
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /extract: {e}')
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k extract_endpoint`
Expected: `PASS` (2 testes).

- [ ] **Step 5: Commit**

```bash
git add routes/reembolsos.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona endpoint de extração de comprovante"
```

---

### Task 7: Robô — utilitários de navegador e preenchimento por label

**Files:**
- Modify: `integrations/reembolso_robot.py`

Sem testes automatizados nesta tarefa (mesma situação de `forms_robot.py` — interação real de navegador não é testável sem sessão logada; ver nota no topo do plano). Copie os utilitários de lançamento de navegador de `integrations/forms_robot.py:163-227` (detecção de navegador padrão + perfil persistente) — são genéricos, não específicos do Forms.

- [ ] **Step 1: Copiar e adaptar o lançamento de navegador**

Em `integrations/reembolso_robot.py`, adicionar (copiado de `forms_robot.py`, trocando apenas `_profile_dir` — já definido na Task 4 — pelo nome do perfil):

```python
def _detect_default_browser_channel():
    if sys.platform != 'win32':
        return None
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id = (winreg.QueryValueEx(key, 'ProgId')[0] or '').lower()
        if 'chrome' in prog_id:
            return 'chrome'
        if 'edge' in prog_id:
            return 'msedge'
    except Exception:
        pass
    return None


def _launch_context(pw, headless):
    profile = _profile_dir()
    args = ['--disable-blink-features=AutomationControlled']
    kwargs = dict(headless=headless, args=args)
    if headless:
        kwargs['viewport'] = {'width': 1280, 'height': 920}
    else:
        kwargs['viewport'] = None
        args.append('--start-maximized')
    last_error = None

    channels = []
    detected = _detect_default_browser_channel()
    if detected:
        channels.append(detected)
    for channel in ('chrome', 'msedge'):
        if channel not in channels:
            channels.append(channel)
    channels.append(None)

    for channel in channels:
        try:
            if channel:
                return pw.chromium.launch_persistent_context(profile, channel=channel, **kwargs)
            return pw.chromium.launch_persistent_context(profile, **kwargs)
        except Exception as e:
            last_error = e
    raise ReembolsoRobotError(f'Não foi possível abrir um navegador (Chrome/Edge). Detalhe: {last_error}')
```

- [ ] **Step 2: Adicionar utilitários de preenchimento por label**

Estes helpers assumem que cada campo tem um `<label>` visível cujo texto identifica o campo, e que o input/select/combobox está no mesmo container do label (confirmado visualmente em `Deslocamentos.aspx` e `OutrasDespesas.aspx` — ambos usam blocos `<div>` com o `<label>` seguido do controle). Combos Select2-like exigem clique + digitação + clique na opção; `<select>` nativos aceitam `select_option` direto.

```python
def _field_container(page, label_text):
    """Encontra o container do campo a partir do texto do label — sobe até o
    ancestral mais próximo que também contenha um input/select/div de combo."""
    label = page.get_by_text(label_text, exact=False).first
    return label.locator(
        'xpath=ancestor::*[.//input or .//select or .//textarea][1]'
    ).first


def fill_text_field(page, label_text, value):
    container = _field_container(page, label_text)
    target = container.locator('input[type="text"], textarea').first
    target.click(timeout=8000)
    target.fill('')
    target.type(str(value), delay=TYPE_DELAY_MS)
    actual = (target.input_value(timeout=4000) or '').strip()
    if actual != str(value).strip():
        raise ReembolsoRobotError(f'campo "{label_text}" não reteve o valor digitado (esperado "{value}", ficou "{actual}")')


def select_native_option(page, label_text, option_text):
    container = _field_container(page, label_text)
    select = container.locator('select').first
    select.select_option(label=option_text, timeout=8000)


def choose_select2_option(page, label_text, option_text):
    """Para combos Select2-like: clica para abrir, digita para filtrar,
    clica na primeira opção visível que contenha o texto."""
    container = _field_container(page, label_text)
    container.locator('.select2-selection, [role="combobox"]').first.click(timeout=8000)
    page.keyboard.type(option_text, delay=TYPE_DELAY_MS)
    page.wait_for_timeout(400)
    option = page.get_by_role('option', name=option_text).first
    if option.count() == 0:
        option = page.get_by_text(option_text, exact=False).first
    option.click(timeout=8000)


def upload_files(page, label_text, file_paths):
    container = _field_container(page, label_text)
    file_input = container.locator('input[type="file"]').first
    file_input.set_input_files(file_paths, timeout=20000)
```

- [ ] **Step 3: Commit**

```bash
git add integrations/reembolso_robot.py
git commit -m "feat(reembolsos): adiciona utilitários de navegador e preenchimento por label"
```

---

### Task 8: Robô — fluxo "Deslocamento & Estacionamento"

**Files:**
- Modify: `integrations/reembolso_robot.py`

- [ ] **Step 1: Implementar `run_deslocamento_robot`**

```python
def run_deslocamento_robot(payload, file_paths, on_progress):
    """payload esperado:
      {
        'celula_custo': str, 'descricao_despesa': str,
        'sub_fluxo': 'deslocamento' | 'estacionamento',
        # sub_fluxo == 'deslocamento':
        'origem': str, 'destino': str, 'data_deslocamento': 'YYYY-MM-DD',
        'tipo_transporte': 'Carro da Empresa ou Alugado' | 'Carro Próprio',
        'ida_e_volta': bool, 'conta': str,
        'pedagio_valor_total': float | None,
        # sub_fluxo == 'estacionamento':
        'quantidade': int, 'periodo_inicio': 'YYYY-MM-DD', 'periodo_fim': 'YYYY-MM-DD',
        'valor_total': float, 'descricao_estacionamento': str,
      }
    file_paths: {'data_deslocamento_comprovante': [str], 'pedagio_comprovantes': [str],
                 'estacionamento_comprovantes': [str]}
    on_progress(pct, step) alimenta a barra de progresso.
    Retorna {'submitted': bool}.
    """
    if not _ROBOT_LOCK.acquire(blocking=False):
        raise ReembolsoRobotError('Já existe um robô de Reembolsos em execução. Aguarde ele terminar.')
    try:
        return _run_deslocamento_locked(payload, file_paths, on_progress)
    finally:
        _ROBOT_LOCK.release()


def _run_deslocamento_locked(payload, file_paths, on_progress):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ReembolsoRobotError('Playwright não está instalado neste ambiente (pip install playwright).') from e

    on_progress(8, 'Abrindo o navegador do robô...')
    headless = os.environ.get('TOCA_ROBOT_HEADLESS') == '1'
    pw = sync_playwright().start()
    context = None
    try:
        context = _launch_context(pw, headless)
        page = context.pages[0] if context.pages else context.new_page()

        on_progress(15, 'Carregando o portal e-Reembolso...')
        page.goto(DESLOCAMENTOS_URL, wait_until='domcontentloaded', timeout=60000)
        _wait_for_login(page, 'ereembolso.stefanini.com.br')

        on_progress(30, 'Preenchendo Célula Custo...')
        choose_select2_option(page, 'CÉLULA CUSTO', payload['celula_custo'])
        page.wait_for_timeout(800)  # possível cascata Célula Custo -> Cliente

        on_progress(38, 'Preenchendo Cliente e Serviço...')
        choose_select2_option(page, 'CLIENTE', 'Stefanini - Sao Paulo')
        choose_select2_option(page, 'SERVIÇO', 'Prospecção')
        fill_text_field(page, 'DESCRIÇÃO DA DESPESA', payload['descricao_despesa'])

        if payload['sub_fluxo'] == 'deslocamento':
            on_progress(50, 'Preenchendo Origem e Destino...')
            fill_text_field(page, 'ORIGEM', payload['origem'])
            fill_text_field(page, 'DESTINO', payload['destino'])
            fill_text_field(page, 'DATA DO DESLOCAMENTO', _br_date(payload['data_deslocamento']))
            choose_select2_option(page, 'TIPO DO TRANSPORTE', payload['tipo_transporte'])
            if payload.get('ida_e_volta'):
                page.get_by_text('DESLOCAMENTO IDA E VOLTA', exact=False).first.click(timeout=8000)
            descricao_deslocamento = (
                f"Visita ao cliente {payload['conta']}, de {payload['origem']} à {payload['destino']}"
            )
            fill_text_field(page, 'DESCRIÇÃO DO DESLOCAMENTO', descricao_deslocamento)
            on_progress(65, 'Adicionando deslocamento...')
            page.get_by_role('button', name='adicionar').first.click(timeout=8000)
            page.wait_for_timeout(500)

            pedagio_paths = file_paths.get('pedagio_comprovantes') or []
            if payload.get('pedagio_valor_total'):
                on_progress(75, 'Preenchendo Pedágio...')
                choose_select2_option(page, 'TIPO DO DESLOCAMENTO', 'Pedágio')
                _fill_outros_deslocamentos_common(
                    page, quantidade=len(pedagio_paths) or 1,
                    periodo_inicio=payload['data_deslocamento'], periodo_fim=payload['data_deslocamento'],
                    valor_total=payload['pedagio_valor_total'],
                    comprovantes=pedagio_paths,
                    descricao=f"Deslocamento para visitar cliente {payload['conta']}",
                )
                page.get_by_role('button', name='adicionar').first.click(timeout=8000)
        else:  # estacionamento
            on_progress(55, 'Preenchendo Estacionamento...')
            choose_select2_option(page, 'TIPO DO DESLOCAMENTO', 'Estacionamento')
            _fill_outros_deslocamentos_common(
                page, quantidade=payload['quantidade'],
                periodo_inicio=payload['periodo_inicio'], periodo_fim=payload['periodo_fim'],
                valor_total=payload['valor_total'],
                comprovantes=file_paths.get('estacionamento_comprovantes') or [],
                descricao=payload['descricao_estacionamento'],
            )
            page.get_by_role('button', name='adicionar').first.click(timeout=8000)

        return _finish_and_wait_submit(page, context, pw, on_progress)
    except ReembolsoRobotError:
        _cleanup(pw, context)
        raise
    except Exception as e:
        _cleanup(pw, context)
        raise ReembolsoRobotError(f'Falha no robô de Deslocamento: {e}') from e


def _fill_outros_deslocamentos_common(page, quantidade, periodo_inicio, periodo_fim, valor_total, comprovantes, descricao):
    select_native_option(page, 'QUANTIDADE', str(quantidade).zfill(2))
    container = _field_container(page, 'PERIODO')
    dates = container.locator('input').all()
    if len(dates) >= 2:
        dates[0].fill(_br_date(periodo_inicio))
        dates[1].fill(_br_date(periodo_fim))
    fill_text_field(page, 'VALOR TOTAL EM R$', f'{valor_total:.2f}'.replace('.', ','))
    upload_files(page, 'COMPROVANTE', comprovantes)
    fill_text_field(page, 'DESCRIÇÃO', descricao)


def _br_date(iso_value):
    from datetime import datetime
    return datetime.strptime(iso_value, '%Y-%m-%d').strftime('%d/%m/%Y')


def _wait_for_login(page, host):
    import time as _time
    deadline = _time.time() + LOGIN_TIMEOUT_SECONDS
    while True:
        if page.is_closed():
            raise ReembolsoRobotError('A janela do robô foi fechada antes do preenchimento.')
        try:
            if host in (page.url or '') and page.locator('label').first.count() > 0:
                return
        except Exception:
            pass
        if _time.time() > deadline:
            raise ReembolsoRobotError('Tempo esgotado aguardando o portal carregar (login pendente?).')
        _time.sleep(1.0)


def _finish_and_wait_submit(page, context, pw, on_progress):
    import time as _time
    on_progress(88, 'Campos preenchidos. Revise e clique em Enviar na janela do robô.')
    submitted = False
    try:
        submit = page.get_by_role('button', name='Enviar').first
        if submit.count() > 0:
            submit.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        pass
    review_deadline = _time.time() + REVIEW_TIMEOUT_SECONDS
    while _time.time() < review_deadline:
        if page.is_closed():
            break
        _time.sleep(1.5)
    # O robô não detecta confirmação de envio automaticamente neste site
    # (sem uma "thank you page" fixa como no Forms) — fica com o usuário
    # fechar a janela após confirmar visualmente que enviou.
    return {'submitted': submitted}


def _cleanup(pw, context):
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass
```

Nota importante para quem for testar ao vivo (Tarefa 15): `_wait_for_login` e a detecção de "Enviar" são propositalmente simples/genéricas — ajuste-as com o comportamento real observado.

- [ ] **Step 2: Commit**

```bash
git add integrations/reembolso_robot.py
git commit -m "feat(reembolsos): implementa fluxo do robô Deslocamento & Estacionamento"
```

---

### Task 9: Robô — fluxo "Almoço com Cliente"

**Files:**
- Modify: `integrations/reembolso_robot.py`

- [ ] **Step 1: Implementar `run_almoco_robot`**

```python
def run_almoco_robot(payload, comprovantes, on_progress):
    """payload: {'celula_custo', 'descricao_despesa', 'quantidade',
                 'periodo_inicio', 'periodo_fim', 'valor_total', 'descricao'}
    comprovantes: [str] caminhos dos arquivos.
    """
    if not _ROBOT_LOCK.acquire(blocking=False):
        raise ReembolsoRobotError('Já existe um robô de Reembolsos em execução. Aguarde ele terminar.')
    try:
        return _run_almoco_locked(payload, comprovantes, on_progress)
    finally:
        _ROBOT_LOCK.release()


def _run_almoco_locked(payload, comprovantes, on_progress):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ReembolsoRobotError('Playwright não está instalado neste ambiente (pip install playwright).') from e

    on_progress(8, 'Abrindo o navegador do robô...')
    headless = os.environ.get('TOCA_ROBOT_HEADLESS') == '1'
    pw = sync_playwright().start()
    context = None
    try:
        context = _launch_context(pw, headless)
        page = context.pages[0] if context.pages else context.new_page()

        on_progress(15, 'Carregando o portal e-Reembolso...')
        page.goto(OUTRAS_DESPESAS_URL, wait_until='domcontentloaded', timeout=60000)
        _wait_for_login(page, 'ereembolso.stefanini.com.br')

        on_progress(30, 'Preenchendo Célula Custo...')
        choose_select2_option(page, 'CÉLULA CUSTO', payload['celula_custo'])
        page.wait_for_timeout(800)

        on_progress(38, 'Preenchendo Cliente e Serviço...')
        choose_select2_option(page, 'CLIENTE', 'Stefanini - Sao Paulo')
        choose_select2_option(page, 'SERVIÇO', 'Prospecção')
        fill_text_field(page, 'DESCRIÇÃO DA DESPESA', payload['descricao_despesa'])

        on_progress(55, 'Preenchendo despesa de Almoço com Cliente...')
        select_native_option(page, 'TIPO DE DESPESA', 'Gasto com cliente')
        select_native_option(page, 'QUANTIDADE', str(payload['quantidade']).zfill(2))
        container = _field_container(page, 'PERIODO')
        dates = container.locator('input').all()
        if len(dates) >= 2:
            dates[0].fill(_br_date(payload['periodo_inicio']))
            dates[1].fill(_br_date(payload['periodo_fim']))
        fill_text_field(page, 'VALOR TOTAL EM R$', f"{payload['valor_total']:.2f}".replace('.', ','))
        upload_files(page, 'COMPROVANTE', comprovantes)
        fill_text_field(page, 'DESCRIÇÃO', payload['descricao'])

        on_progress(75, 'Adicionando despesa...')
        page.get_by_role('button', name='adicionar').first.click(timeout=8000)

        return _finish_and_wait_submit(page, context, pw, on_progress)
    except ReembolsoRobotError:
        _cleanup(pw, context)
        raise
    except Exception as e:
        _cleanup(pw, context)
        raise ReembolsoRobotError(f'Falha no robô de Almoço com Cliente: {e}') from e
```

- [ ] **Step 2: Commit**

```bash
git add integrations/reembolso_robot.py
git commit -m "feat(reembolsos): implementa fluxo do robô Almoço com Cliente"
```

---

### Task 10: Rota — disparo e polling do robô "Deslocamento & Estacionamento"

**Files:**
- Modify: `routes/reembolsos.py`
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_deslocamento_robot_sem_celula_custo_400(client):
    resp = client.post('/api/autotoca/reembolsos/deslocamento/robot', data={'sub_fluxo': 'deslocamento'})
    assert resp.status_code == 400


def test_deslocamento_robot_dispara_task(client, monkeypatch, db_path):
    monkeypatch.setattr(
        'routes.reembolsos._reembolso_process_deslocamento_async'
        if False else 'app._reembolso_process_deslocamento_async',
        lambda *a, **k: None,
        raising=False,
    )
    # threading.Thread real é usado pela rota — substitui por execução síncrona
    # no próprio teste para não depender de timing.
    monkeypatch.setattr(toca.threading, 'Thread', lambda target, args=(), daemon=True: type('T', (), {'start': lambda self: target(*args)})())

    resp = client.post('/api/autotoca/reembolsos/deslocamento/robot', data={
        'celula_custo': '19 - DBD PEDROSO',
        'descricao_despesa': 'Visita comercial',
        'sub_fluxo': 'estacionamento',
        'conta': 'Conta Teste',
        'quantidade': '2',
        'periodo_inicio': '2026-06-01',
        'periodo_fim': '2026-06-05',
        'valor_total': '45.90',
        'descricao_estacionamento': 'Estacionamento na visita',
    })
    assert resp.status_code == 202
    assert 'task_id' in resp.get_json()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k deslocamento_robot`
Expected: `FAIL` — `404 NOT FOUND`.

- [ ] **Step 3: Implementar**

Adicionar a `routes/reembolsos.py`:

```python
def _reembolso_save_uploaded_files(history_id, field_key, file_storages):
    saved = []
    field_dir = REEMBOLSOS_UPLOAD_DIR / str(history_id) / field_key
    field_dir.mkdir(parents=True, exist_ok=True)
    for f in file_storages:
        if not f or not f.filename:
            continue
        safe_name = secure_filename(f.filename) or f'arquivo_{uuid.uuid4().hex}'
        target = field_dir / safe_name
        counter = 1
        while target.exists():
            target = field_dir / f'{target.stem}_{counter}{target.suffix}'
            counter += 1
        f.save(str(target))
        saved.append(str(target))
    return saved


def _reembolso_process_deslocamento_async(task_id, history_id, payload, file_paths):
    from integrations.reembolso_robot import run_deslocamento_robot, ReembolsoRobotError

    def on_progress(pct, step):
        _reembolso_task_set(task_id, {'progress': pct, 'step': step})

    try:
        result = run_deslocamento_robot(payload, file_paths, on_progress)
        if payload.get('destino') and payload.get('account_id'):
            conn = get_db()
            c = conn.cursor()
            c.execute(
                'INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?) '
                'ON CONFLICT(account_id) DO UPDATE SET endereco = excluded.endereco, updated_at = CURRENT_TIMESTAMP',
                (payload['account_id'], payload['destino'])
            )
            conn.commit()
            conn.close()
        if payload.get('origem'):
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO reembolso_origem_historico (texto) VALUES (?)', (payload['origem'],))
            conn.commit()
            conn.close()
        _reembolso_task_set(task_id, {
            'status': 'done', 'progress': 100,
            'step': 'Preenchimento concluído — revise e envie na janela do robô.',
            'result': result,
        })
    except ReembolsoRobotError as e:
        logger.warning(f'[Reembolsos][Robot] {e}')
        _reembolso_task_set(task_id, {'status': 'error', 'error': str(e)})
    except Exception as e:
        logger.exception('[Reembolsos][Robot] Falha inesperada')
        _reembolso_task_set(task_id, {'status': 'error', 'error': f'Falha inesperada no robô: {e}'})
    finally:
        _reembolso_task_cleanup(task_id)


@app.route('/api/autotoca/reembolsos/deslocamento/robot', methods=['POST'])
def reembolsos_deslocamento_robot():
    try:
        form = request.form
        celula_custo = (form.get('celula_custo') or '').strip()
        descricao_despesa = (form.get('descricao_despesa') or '').strip()
        sub_fluxo = (form.get('sub_fluxo') or '').strip()

        errors = []
        if not celula_custo:
            errors.append('Célula custo é obrigatória.')
        if not descricao_despesa:
            errors.append('Descrição da despesa é obrigatória.')
        if sub_fluxo not in ('deslocamento', 'estacionamento'):
            errors.append('sub_fluxo deve ser "deslocamento" ou "estacionamento".')
        if errors:
            return jsonify({'error': ' '.join(errors)}), 400

        payload = {'celula_custo': celula_custo, 'descricao_despesa': descricao_despesa, 'sub_fluxo': sub_fluxo}
        if sub_fluxo == 'deslocamento':
            payload.update({
                'origem': (form.get('origem') or '').strip(),
                'destino': (form.get('destino') or '').strip(),
                'account_id': int(form['account_id']) if form.get('account_id') else None,
                'conta': (form.get('conta') or '').strip(),
                'data_deslocamento': (form.get('data_deslocamento') or '').strip(),
                'tipo_transporte': (form.get('tipo_transporte') or '').strip(),
                'ida_e_volta': (form.get('ida_e_volta') or '').lower() == 'true',
                'pedagio_valor_total': float(form['pedagio_valor_total']) if form.get('pedagio_valor_total') else None,
            })
        else:
            payload.update({
                'quantidade': int(form.get('quantidade') or 0),
                'periodo_inicio': (form.get('periodo_inicio') or '').strip(),
                'periodo_fim': (form.get('periodo_fim') or '').strip(),
                'valor_total': float(form.get('valor_total') or 0),
                'descricao_estacionamento': (form.get('descricao_estacionamento') or '').strip(),
            })

        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO reembolsos_history (tipo, payload_json, files_json) VALUES (?, ?, ?)',
            (f'deslocamento:{sub_fluxo}', json.dumps(payload, ensure_ascii=False), '{}')
        )
        conn.commit()
        history_id = c.lastrowid

        file_paths = {}
        if sub_fluxo == 'deslocamento':
            comprovante_data = [f for f in request.files.getlist('data_deslocamento_comprovante') if f and f.filename]
            file_paths['data_deslocamento_comprovante'] = _reembolso_save_uploaded_files(history_id, 'data_deslocamento_comprovante', comprovante_data)
            pedagio_files = [f for f in request.files.getlist('pedagio_comprovantes') if f and f.filename]
            if payload.get('pedagio_valor_total') and not pedagio_files:
                from integrations.reembolso_robot import gerar_comprovante_corrompido
                corrompido = gerar_comprovante_corrompido(REEMBOLSOS_UPLOAD_DIR / str(history_id) / 'pedagio_comprovantes')
                file_paths['pedagio_comprovantes'] = [str(corrompido)]
            else:
                file_paths['pedagio_comprovantes'] = _reembolso_save_uploaded_files(history_id, 'pedagio_comprovantes', pedagio_files)
        else:
            estac_files = [f for f in request.files.getlist('estacionamento_comprovantes') if f and f.filename]
            file_paths['estacionamento_comprovantes'] = _reembolso_save_uploaded_files(history_id, 'estacionamento_comprovantes', estac_files)

        c.execute('UPDATE reembolsos_history SET files_json = ? WHERE id = ?', (json.dumps(file_paths, ensure_ascii=False), history_id))
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _reembolso_task_set(task_id, {'status': 'processing', 'step': 'Iniciando o robô...', 'progress': 5})
        threading.Thread(target=_reembolso_process_deslocamento_async, args=(task_id, history_id, payload, file_paths), daemon=True).start()
        return jsonify({'task_id': task_id, 'history_id': history_id}), 202
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /deslocamento/robot: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/deslocamento/robot/tasks/<task_id>', methods=['GET'])
def reembolsos_deslocamento_robot_task(task_id):
    task = _reembolso_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k deslocamento_robot`
Expected: `PASS` (2 testes).

- [ ] **Step 5: Rodar toda a suíte para checar regressões**

Run: `python -m pytest tests/ -v`
Expected: `PASS` em todos os testes.

- [ ] **Step 6: Commit**

```bash
git add routes/reembolsos.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona rota do robô Deslocamento & Estacionamento"
```

---

### Task 11: Rota — disparo e polling do robô "Almoço com Cliente"

**Files:**
- Modify: `routes/reembolsos.py`
- Test: `tests/test_reembolsos.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_reembolsos.py`:

```python
def test_almoco_robot_sem_celula_custo_400(client):
    resp = client.post('/api/autotoca/reembolsos/almoco/robot', data={})
    assert resp.status_code == 400


def test_almoco_robot_dispara_task(client, monkeypatch, db_path):
    monkeypatch.setattr(toca.threading, 'Thread', lambda target, args=(), daemon=True: type('T', (), {'start': lambda self: target(*args)})())
    resp = client.post('/api/autotoca/reembolsos/almoco/robot', data={
        'celula_custo': '19 - DBD PEDROSO',
        'descricao_despesa': 'Almoço com cliente X',
        'quantidade': '1',
        'periodo_inicio': '2026-06-01',
        'periodo_fim': '2026-06-01',
        'valor_total': '89.90',
        'descricao': 'Almoço de negociação',
    })
    assert resp.status_code == 202
    assert 'task_id' in resp.get_json()
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `python -m pytest tests/test_reembolsos.py -v -k almoco_robot`
Expected: `FAIL` — `404 NOT FOUND`.

- [ ] **Step 3: Implementar**

Adicionar a `routes/reembolsos.py`:

```python
def _reembolso_process_almoco_async(task_id, history_id, payload, comprovantes):
    from integrations.reembolso_robot import run_almoco_robot, ReembolsoRobotError

    def on_progress(pct, step):
        _reembolso_task_set(task_id, {'progress': pct, 'step': step})

    try:
        result = run_almoco_robot(payload, comprovantes, on_progress)
        _reembolso_task_set(task_id, {
            'status': 'done', 'progress': 100,
            'step': 'Preenchimento concluído — revise e envie na janela do robô.',
            'result': result,
        })
    except ReembolsoRobotError as e:
        logger.warning(f'[Reembolsos][Robot] {e}')
        _reembolso_task_set(task_id, {'status': 'error', 'error': str(e)})
    except Exception as e:
        logger.exception('[Reembolsos][Robot] Falha inesperada')
        _reembolso_task_set(task_id, {'status': 'error', 'error': f'Falha inesperada no robô: {e}'})
    finally:
        _reembolso_task_cleanup(task_id)


@app.route('/api/autotoca/reembolsos/almoco/robot', methods=['POST'])
def reembolsos_almoco_robot():
    try:
        form = request.form
        celula_custo = (form.get('celula_custo') or '').strip()
        descricao_despesa = (form.get('descricao_despesa') or '').strip()
        descricao = (form.get('descricao') or '').strip()

        errors = []
        if not celula_custo:
            errors.append('Célula custo é obrigatória.')
        if not descricao_despesa:
            errors.append('Descrição da despesa é obrigatória.')
        if not descricao:
            errors.append('Descrição é obrigatória.')
        comprovante_files = [f for f in request.files.getlist('comprovantes') if f and f.filename]
        if not comprovante_files:
            errors.append('Anexe ao menos um comprovante.')
        if errors:
            return jsonify({'error': ' '.join(errors)}), 400

        payload = {
            'celula_custo': celula_custo,
            'descricao_despesa': descricao_despesa,
            'quantidade': int(form.get('quantidade') or len(comprovante_files)),
            'periodo_inicio': (form.get('periodo_inicio') or '').strip(),
            'periodo_fim': (form.get('periodo_fim') or '').strip(),
            'valor_total': float(form.get('valor_total') or 0),
            'descricao': descricao,
        }

        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO reembolsos_history (tipo, payload_json, files_json) VALUES (?, ?, ?)',
            ('almoco', json.dumps(payload, ensure_ascii=False), '{}')
        )
        conn.commit()
        history_id = c.lastrowid

        comprovantes = _reembolso_save_uploaded_files(history_id, 'comprovantes', comprovante_files)
        c.execute('UPDATE reembolsos_history SET files_json = ? WHERE id = ?', (json.dumps({'comprovantes': comprovantes}, ensure_ascii=False), history_id))
        conn.commit()
        conn.close()

        task_id = uuid.uuid4().hex
        _reembolso_task_set(task_id, {'status': 'processing', 'step': 'Iniciando o robô...', 'progress': 5})
        threading.Thread(target=_reembolso_process_almoco_async, args=(task_id, history_id, payload, comprovantes), daemon=True).start()
        return jsonify({'task_id': task_id, 'history_id': history_id}), 202
    except Exception as e:
        logger.exception(f'[Reembolsos] POST /almoco/robot: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/reembolsos/almoco/robot/tasks/<task_id>', methods=['GET'])
def reembolsos_almoco_robot_task(task_id):
    task = _reembolso_task_get(task_id)
    if not task:
        return jsonify({'error': 'Tarefa não encontrada.'}), 404
    return jsonify(task)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `python -m pytest tests/test_reembolsos.py -v -k almoco_robot`
Expected: `PASS` (2 testes).

- [ ] **Step 5: Rodar toda a suíte**

Run: `python -m pytest tests/ -v`
Expected: `PASS` em todos os testes.

- [ ] **Step 6: Commit**

```bash
git add routes/reembolsos.py tests/test_reembolsos.py
git commit -m "feat(reembolsos): adiciona rota do robô Almoço com Cliente"
```

---

### Task 12: Frontend — botão e painel HTML do submódulo

**Files:**
- Modify: `public/index.html:863` (linha do último botão AutoToca, `Sync Outlook`)

- [ ] **Step 1: Adicionar o botão do submódulo**

Em `public/index.html`, na linha 866 (logo após o botão `Sync Outlook`), adicionar:

```html
                <button id="autoTocaBtn_reembolsos" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('reembolsos')"><span class="ai-star-icon">✦</span> Reembolsos</button>
```

- [ ] **Step 2: Adicionar o painel**

Logo após o fechamento do painel `autoTocaSyncOutlook` (o painel que vem depois do Chamado Jurídico — localizar buscando por `id="autoTocaSyncOutlook"` e inserir o novo painel imediatamente depois do seu `</div>` de fechamento), adicionar:

```html
            <div id="autoTocaReembolsos" style="display:none; background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:16px;">
                <h3 style="margin-bottom:8px; color:#065f46;">Reembolsos</h3>
                <p style="margin-bottom:14px; color:#4b5563; font-size:13px;">Anexe os comprovantes e deixe o robô 🐇 preencher o e-Reembolso para você revisar e enviar.</p>

                <div class="form-group" style="max-width:320px; margin-bottom:18px;">
                    <label>Tipo de reembolso</label>
                    <select id="reembTipo" onchange="onReembTipoChange()">
                        <option value="deslocamento">Deslocamento & Estacionamento</option>
                        <option value="almoco">Almoço com Cliente</option>
                    </select>
                </div>

                <form id="reembFormDeslocamento" onsubmit="return false;">
                    <div style="display:grid; grid-template-columns:repeat(3,minmax(200px,1fr)); gap:14px; margin-bottom:16px;">
                        <div class="form-group">
                            <label>Célula custo <span style="color:#dc2626;">*</span></label>
                            <input id="reembCelulaCusto" type="text" required>
                        </div>
                        <div class="form-group" style="grid-column: span 2;">
                            <label>Descrição da Despesa <span style="color:#dc2626;">*</span></label>
                            <input id="reembDescricaoDespesa" type="text" required>
                        </div>
                        <div class="form-group">
                            <label>Sub-fluxo <span style="color:#dc2626;">*</span></label>
                            <select id="reembSubFluxo" required onchange="onReembSubFluxoChange()">
                                <option value="deslocamento">Deslocamento (KM)</option>
                                <option value="estacionamento">Estacionamento</option>
                            </select>
                        </div>
                    </div>

                    <div id="reembBlocoDeslocamento" style="display:grid; grid-template-columns:repeat(3,minmax(200px,1fr)); gap:14px; margin-bottom:16px;">
                        <div class="form-group">
                            <label>Conta (destino) <span style="color:#dc2626;">*</span></label>
                            <select id="reembConta" required onchange="onReembContaChange()"></select>
                        </div>
                        <div class="form-group" id="reembDestinoOutroWrap" style="display:none;">
                            <label>Destino (endereço)</label>
                            <input id="reembDestinoOutro" type="text" placeholder="Endereço completo">
                        </div>
                        <div class="form-group">
                            <label>Destino salvo <span style="color:#dc2626;">*</span></label>
                            <input id="reembDestino" type="text" required placeholder="Endereço completo do cliente">
                            <button type="button" class="btn btn-auto-mapping btn-small" onclick="reembBuscarEnderecoIA()" style="margin-top:6px; padding:4px 10px; font-size:11px;">
                                <span class="ai-star-icon">✦</span> Buscar endereço com IA
                            </button>
                        </div>
                        <div class="form-group">
                            <label>Origem <span style="color:#dc2626;">*</span></label>
                            <input id="reembOrigem" list="reembOrigemHistorico" type="text" required placeholder="Endereço de partida">
                            <datalist id="reembOrigemHistorico"></datalist>
                        </div>
                        <div class="form-group">
                            <label>Comprovante (para ler a data) <span style="color:#dc2626;">*</span></label>
                            <input id="reembDataComprovante" type="file" accept="image/*" onchange="reembOnDataComprovanteChange()">
                        </div>
                        <div class="form-group">
                            <label>Data do Deslocamento <span style="color:#dc2626;">*</span></label>
                            <input id="reembDataDeslocamento" type="date" required>
                        </div>
                        <div class="form-group">
                            <label>Tipo de transporte <span style="color:#dc2626;">*</span></label>
                            <select id="reembTipoTransporte" required>
                                <option value="Carro da Empresa ou Alugado">Carro da Empresa ou Alugado</option>
                                <option value="Carro Próprio">Carro Próprio</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label><input id="reembIdaVolta" type="checkbox"> Deslocamento ida e volta</label>
                        </div>
                        <div class="form-group" style="grid-column: span 3;">
                            <label>Caso tenha pedágio, subir comprovante(s)</label>
                            <input id="reembPedagioComprovantes" type="file" accept="image/*" multiple onchange="reembOnPedagioChange()">
                            <div id="reembPedagioValor" style="margin-top:6px; font-size:12px; color:#6b7280;"></div>
                        </div>
                    </div>

                    <div id="reembBlocoEstacionamento" style="display:none; grid-template-columns:repeat(3,minmax(200px,1fr)); gap:14px; margin-bottom:16px;">
                        <div class="form-group" style="grid-column: span 3;">
                            <label>Comprovantes <span style="color:#dc2626;">*</span></label>
                            <input id="reembEstacComprovantes" type="file" accept="image/*" multiple onchange="reembOnEstacComprovantesChange()">
                            <div id="reembEstacResumo" style="margin-top:6px; font-size:12px; color:#6b7280;"></div>
                        </div>
                        <div class="form-group" style="grid-column: span 3;">
                            <label>Descrição <span style="color:#dc2626;">*</span></label>
                            <textarea id="reembEstacDescricao" rows="2" required></textarea>
                        </div>
                    </div>

                    <button class="btn btn-auto-mapping" type="button" id="reembRobotBtn" onclick="runReembDeslocamentoRobot(event)" style="padding:10px 16px;">
                        <span class="ai-star-icon">✦</span> Preencher com Robô 🐇
                    </button>
                    <div id="reembRobotProgress" style="display:none; padding:20px 4px 12px;">
                        <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="reembRobotStep">Iniciando o robô...</div>
                        <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                            <div id="reembRobotBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                            </div>
                        </div>
                        <div style="text-align:right; padding:0 16px; font-size:11px; color:#6b7280;" id="reembRobotPct">5%</div>
                    </div>
                </form>

                <form id="reembFormAlmoco" style="display:none;" onsubmit="return false;">
                    <div style="display:grid; grid-template-columns:repeat(3,minmax(200px,1fr)); gap:14px; margin-bottom:16px;">
                        <div class="form-group">
                            <label>Célula custo <span style="color:#dc2626;">*</span></label>
                            <input id="reembAlmCelulaCusto" type="text" required>
                        </div>
                        <div class="form-group" style="grid-column: span 2;">
                            <label>Descrição da Despesa <span style="color:#dc2626;">*</span></label>
                            <input id="reembAlmDescricaoDespesa" type="text" required>
                        </div>
                        <div class="form-group" style="grid-column: span 3;">
                            <label>Comprovantes <span style="color:#dc2626;">*</span></label>
                            <input id="reembAlmComprovantes" type="file" accept="image/*" multiple onchange="reembOnAlmComprovantesChange()">
                            <div id="reembAlmResumo" style="margin-top:6px; font-size:12px; color:#6b7280;"></div>
                        </div>
                        <div class="form-group" style="grid-column: span 3;">
                            <label>Descrição <span style="color:#dc2626;">*</span></label>
                            <textarea id="reembAlmDescricao" rows="2" required></textarea>
                        </div>
                    </div>
                    <button class="btn btn-auto-mapping" type="button" id="reembAlmRobotBtn" onclick="runReembAlmocoRobot(event)" style="padding:10px 16px;">
                        <span class="ai-star-icon">✦</span> Preencher com Robô 🐇
                    </button>
                    <div id="reembAlmRobotProgress" style="display:none; padding:20px 4px 12px;">
                        <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="reembAlmRobotStep">Iniciando o robô...</div>
                        <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                            <div id="reembAlmRobotBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                            </div>
                        </div>
                        <div style="text-align:right; padding:0 16px; font-size:11px; color:#6b7280;" id="reembAlmRobotPct">5%</div>
                    </div>
                </form>
            </div>
```

- [ ] **Step 3: Registrar o novo painel/botão em `toggleAutoTocaAutomation`**

Em `public/js/core.js`, na função `toggleAutoTocaAutomation` (linha 1540), adicionar `'reembolsos'` aos dicionários `panels` e `buttons`:

```javascript
            const panels = {
                'chamado-juridico': 'autoTocaChamadoJuridico',
                'mala-direta': 'autoTocaMalaDireta',
                'sync-outlook': 'autoTocaSyncOutlook',
                'reembolsos': 'autoTocaReembolsos'
            };
            const buttons = {
                'chamado-juridico': 'autoTocaBtn_chamado-juridico',
                'mala-direta': 'autoTocaBtn_mala-direta',
                'sync-outlook': 'autoTocaBtn_sync-outlook',
                'reembolsos': 'autoTocaBtn_reembolsos'
            };
```

- [ ] **Step 4: Commit**

```bash
git add public/index.html public/js/core.js
git commit -m "feat(reembolsos): adiciona botão e painel HTML do submódulo"
```

---

### Task 13: Frontend — JS do fluxo "Deslocamento & Estacionamento"

**Files:**
- Modify: `public/js/core.js`

- [ ] **Step 1: Adicionar funções de carregamento e alternância de sub-fluxo**

Adicionar em `public/js/core.js`, logo após a função `runChamadoJuridicoRobot` (linha ~3115):

```javascript
        let _reembPedagioValorCents = 0;
        let _reembEstacResumo = null;
        let _reembAlmResumo = null;

        function onReembTipoChange() {
            const tipo = document.getElementById('reembTipo').value;
            document.getElementById('reembFormDeslocamento').style.display = tipo === 'deslocamento' ? 'block' : 'none';
            document.getElementById('reembFormAlmoco').style.display = tipo === 'almoco' ? 'block' : 'none';
        }

        function onReembSubFluxoChange() {
            const sub = document.getElementById('reembSubFluxo').value;
            document.getElementById('reembBlocoDeslocamento').style.display = sub === 'deslocamento' ? 'grid' : 'none';
            document.getElementById('reembBlocoEstacionamento').style.display = sub === 'estacionamento' ? 'grid' : 'none';
        }

        async function loadReembContas() {
            const response = await fetch(`${API_BASE}/autotoca/accounts`);
            if (!response.ok) return;
            const contas = await response.json();
            const select = document.getElementById('reembConta');
            select.innerHTML = contas.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
        }

        async function onReembContaChange() {
            const accountId = document.getElementById('reembConta').value;
            const destinoInput = document.getElementById('reembDestino');
            if (accountId === '0') {
                destinoInput.value = '';
                return;
            }
            const response = await fetch(`${API_BASE}/autotoca/reembolsos/conta-endereco/${accountId}`);
            if (!response.ok) return;
            const data = await response.json();
            destinoInput.value = data.endereco || '';
        }

        async function loadReembOrigemHistorico() {
            const response = await fetch(`${API_BASE}/autotoca/reembolsos/origem-historico`);
            if (!response.ok) return;
            const items = await response.json();
            document.getElementById('reembOrigemHistorico').innerHTML =
                items.map(i => `<option value="${escapeHtml(i.texto)}">`).join('');
        }

        async function reembBuscarEnderecoIA() {
            const contaSelect = document.getElementById('reembConta');
            const contaNome = contaSelect.options[contaSelect.selectedIndex]?.textContent || '';
            if (!contaNome) { showError('Selecione uma conta primeiro.'); return; }
            try {
                const response = await fetch(`${API_BASE}/autotoca/account-info`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_name: contaNome })
                });
                const data = await response.json();
                if (data?.endereco) document.getElementById('reembDestino').value = data.endereco;
                else showInfo('Não encontrei um endereço automaticamente — preencha manualmente.');
            } catch (e) {
                showError('Falha ao buscar endereço com IA.');
            }
        }

        async function _reembExtractFile(file) {
            const fd = new FormData();
            fd.append('file', file);
            const response = await fetch(`${API_BASE}/autotoca/reembolsos/extract`, { method: 'POST', body: fd });
            if (!response.ok) return { data: null, valor_cents: null };
            return response.json();
        }

        async function reembOnDataComprovanteChange() {
            const input = document.getElementById('reembDataComprovante');
            const file = input.files?.[0];
            if (!file) return;
            const result = await _reembExtractFile(file);
            if (result.data) document.getElementById('reembDataDeslocamento').value = result.data;
        }

        async function reembOnPedagioChange() {
            const input = document.getElementById('reembPedagioComprovantes');
            const files = Array.from(input.files || []);
            const resumoEl = document.getElementById('reembPedagioValor');
            if (!files.length) { _reembPedagioValorCents = 0; resumoEl.textContent = ''; return; }
            resumoEl.textContent = 'Lendo comprovantes...';
            let totalCents = 0;
            for (const file of files) {
                const result = await _reembExtractFile(file);
                totalCents += result.valor_cents || 0;
            }
            _reembPedagioValorCents = totalCents;
            resumoEl.textContent = `Valor total do pedágio: R$ ${(totalCents / 100).toFixed(2).replace('.', ',')}`;
        }

        async function reembOnEstacComprovantesChange() {
            const input = document.getElementById('reembEstacComprovantes');
            const files = Array.from(input.files || []);
            const resumoEl = document.getElementById('reembEstacResumo');
            if (!files.length) { _reembEstacResumo = null; resumoEl.textContent = ''; return; }
            resumoEl.textContent = 'Lendo comprovantes...';
            const extracted = [];
            for (const file of files) extracted.push(await _reembExtractFile(file));
            const datas = extracted.map(e => e.data).filter(Boolean).sort();
            const totalCents = extracted.reduce((sum, e) => sum + (e.valor_cents || 0), 0);
            _reembEstacResumo = {
                quantidade: files.length,
                periodo_inicio: datas[0] || null,
                periodo_fim: datas[datas.length - 1] || null,
                valor_total_cents: totalCents,
            };
            resumoEl.textContent = `${files.length} comprovante(s) — total R$ ${(totalCents / 100).toFixed(2).replace('.', ',')}` +
                (datas.length ? ` — período ${datas[0]} a ${datas[datas.length - 1]}` : '');
        }

        function _reembValidateDeslocamento(sub) {
            const celula = document.getElementById('reembCelulaCusto').value.trim();
            const descricao = document.getElementById('reembDescricaoDespesa').value.trim();
            if (!celula) return 'Célula custo é obrigatória.';
            if (!descricao) return 'Descrição da despesa é obrigatória.';
            if (sub === 'deslocamento') {
                if (!document.getElementById('reembDestino').value.trim()) return 'Destino é obrigatório.';
                if (!document.getElementById('reembOrigem').value.trim()) return 'Origem é obrigatória.';
                if (!document.getElementById('reembDataDeslocamento').value) return 'Data do deslocamento é obrigatória (anexe o comprovante).';
            } else {
                if (!_reembEstacResumo || !_reembEstacResumo.quantidade) return 'Anexe ao menos um comprovante de estacionamento.';
                if (!document.getElementById('reembEstacDescricao').value.trim()) return 'Descrição é obrigatória.';
            }
            return null;
        }

        function _reembToggleRunning(running) {
            const btn = document.getElementById('reembRobotBtn');
            const area = document.getElementById('reembRobotProgress');
            if (btn) btn.disabled = running;
            if (area) area.style.display = running ? 'block' : 'none';
        }

        function _reembSetProgress(pct, step) {
            const bar = document.getElementById('reembRobotBar');
            const stepEl = document.getElementById('reembRobotStep');
            const pctEl = document.getElementById('reembRobotPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function runReembDeslocamentoRobot(event) {
            event?.preventDefault?.();
            const sub = document.getElementById('reembSubFluxo').value;
            const validationError = _reembValidateDeslocamento(sub);
            if (validationError) { showError(validationError); return; }

            const fd = new FormData();
            fd.append('celula_custo', document.getElementById('reembCelulaCusto').value.trim());
            fd.append('descricao_despesa', document.getElementById('reembDescricaoDespesa').value.trim());
            fd.append('sub_fluxo', sub);

            if (sub === 'deslocamento') {
                const contaSelect = document.getElementById('reembConta');
                fd.append('account_id', contaSelect.value);
                fd.append('conta', contaSelect.options[contaSelect.selectedIndex]?.textContent || '');
                fd.append('destino', document.getElementById('reembDestino').value.trim());
                fd.append('origem', document.getElementById('reembOrigem').value.trim());
                fd.append('data_deslocamento', document.getElementById('reembDataDeslocamento').value);
                fd.append('tipo_transporte', document.getElementById('reembTipoTransporte').value);
                fd.append('ida_e_volta', document.getElementById('reembIdaVolta').checked ? 'true' : 'false');
                if (_reembPedagioValorCents > 0) fd.append('pedagio_valor_total', (_reembPedagioValorCents / 100).toFixed(2));
                Array.from(document.getElementById('reembPedagioComprovantes').files || []).forEach(f => fd.append('pedagio_comprovantes', f));
                const dataFile = document.getElementById('reembDataComprovante').files?.[0];
                if (dataFile) fd.append('data_deslocamento_comprovante', dataFile);
            } else {
                fd.append('quantidade', String(_reembEstacResumo.quantidade));
                fd.append('periodo_inicio', _reembEstacResumo.periodo_inicio || document.getElementById('reembDataDeslocamento').value);
                fd.append('periodo_fim', _reembEstacResumo.periodo_fim || document.getElementById('reembDataDeslocamento').value);
                fd.append('valor_total', (_reembEstacResumo.valor_total_cents / 100).toFixed(2));
                fd.append('descricao_estacionamento', document.getElementById('reembEstacDescricao').value.trim());
                Array.from(document.getElementById('reembEstacComprovantes').files || []).forEach(f => fd.append('estacionamento_comprovantes', f));
            }

            _reembToggleRunning(true);
            _reembSetProgress(5, 'Iniciando o robô...');

            try {
                const response = await fetch(`${API_BASE}/autotoca/reembolsos/deslocamento/robot`, { method: 'POST', body: fd });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Erro ao iniciar o robô.');
                const taskId = data.task_id;
                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/autotoca/reembolsos/deslocamento/robot/tasks/${taskId}`,
                    'Robô de Reembolso (Deslocamento)',
                    sourceTab,
                    () => { _reembToggleRunning(false); showInfo('Preenchimento concluído. Revise e envie na janela do robô.'); loadReembOrigemHistorico(); },
                    (errMsg) => { _reembToggleRunning(false); showError(errMsg || 'Erro no robô de Reembolsos.'); },
                    (pct, step) => _reembSetProgress(pct, step)
                );
            } catch (error) {
                _reembToggleRunning(false);
                showError(error.message || 'Erro ao iniciar o robô.');
            }
        }
```

- [ ] **Step 2: Chamar os `load*` ao abrir o painel**

Em `toggleAutoTocaAutomation` (Task 12, Step 3), dentro do bloco `if (isOpening) { ... }`, adicionar:

```javascript
                if (key === 'reembolsos') { loadReembContas(); loadReembOrigemHistorico(); }
```

- [ ] **Step 3: Commit**

```bash
git add public/js/core.js
git commit -m "feat(reembolsos): adiciona JS do fluxo Deslocamento & Estacionamento"
```

---

### Task 14: Frontend — JS do fluxo "Almoço com Cliente"

**Files:**
- Modify: `public/js/core.js`

- [ ] **Step 1: Adicionar funções do fluxo Almoço**

Adicionar em `public/js/core.js`, logo após `runReembDeslocamentoRobot` (Task 13):

```javascript
        async function reembOnAlmComprovantesChange() {
            const input = document.getElementById('reembAlmComprovantes');
            const files = Array.from(input.files || []);
            const resumoEl = document.getElementById('reembAlmResumo');
            if (!files.length) { _reembAlmResumo = null; resumoEl.textContent = ''; return; }
            resumoEl.textContent = 'Lendo comprovantes...';
            const extracted = [];
            for (const file of files) extracted.push(await _reembExtractFile(file));
            const datas = extracted.map(e => e.data).filter(Boolean).sort();
            const totalCents = extracted.reduce((sum, e) => sum + (e.valor_cents || 0), 0);
            _reembAlmResumo = {
                quantidade: files.length,
                periodo_inicio: datas[0] || null,
                periodo_fim: datas[datas.length - 1] || null,
                valor_total_cents: totalCents,
            };
            resumoEl.textContent = `${files.length} comprovante(s) — total R$ ${(totalCents / 100).toFixed(2).replace('.', ',')}` +
                (datas.length ? ` — período ${datas[0]} a ${datas[datas.length - 1]}` : '');
        }

        function _reembAlmToggleRunning(running) {
            const btn = document.getElementById('reembAlmRobotBtn');
            const area = document.getElementById('reembAlmRobotProgress');
            if (btn) btn.disabled = running;
            if (area) area.style.display = running ? 'block' : 'none';
        }

        function _reembAlmSetProgress(pct, step) {
            const bar = document.getElementById('reembAlmRobotBar');
            const stepEl = document.getElementById('reembAlmRobotStep');
            const pctEl = document.getElementById('reembAlmRobotPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }

        async function runReembAlmocoRobot(event) {
            event?.preventDefault?.();
            const celula = document.getElementById('reembAlmCelulaCusto').value.trim();
            const descricaoDespesa = document.getElementById('reembAlmDescricaoDespesa').value.trim();
            const descricao = document.getElementById('reembAlmDescricao').value.trim();
            if (!celula) { showError('Célula custo é obrigatória.'); return; }
            if (!descricaoDespesa) { showError('Descrição da despesa é obrigatória.'); return; }
            if (!_reembAlmResumo || !_reembAlmResumo.quantidade) { showError('Anexe ao menos um comprovante.'); return; }
            if (!descricao) { showError('Descrição é obrigatória.'); return; }

            const fd = new FormData();
            fd.append('celula_custo', celula);
            fd.append('descricao_despesa', descricaoDespesa);
            fd.append('quantidade', String(_reembAlmResumo.quantidade));
            fd.append('periodo_inicio', _reembAlmResumo.periodo_inicio || '');
            fd.append('periodo_fim', _reembAlmResumo.periodo_fim || '');
            fd.append('valor_total', (_reembAlmResumo.valor_total_cents / 100).toFixed(2));
            fd.append('descricao', descricao);
            Array.from(document.getElementById('reembAlmComprovantes').files || []).forEach(f => fd.append('comprovantes', f));

            _reembAlmToggleRunning(true);
            _reembAlmSetProgress(5, 'Iniciando o robô...');

            try {
                const response = await fetch(`${API_BASE}/autotoca/reembolsos/almoco/robot`, { method: 'POST', body: fd });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || 'Erro ao iniciar o robô.');
                const taskId = data.task_id;
                const sourceTab = typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca';
                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/autotoca/reembolsos/almoco/robot/tasks/${taskId}`,
                    'Robô de Reembolso (Almoço)',
                    sourceTab,
                    () => { _reembAlmToggleRunning(false); showInfo('Preenchimento concluído. Revise e envie na janela do robô.'); },
                    (errMsg) => { _reembAlmToggleRunning(false); showError(errMsg || 'Erro no robô de Reembolsos.'); },
                    (pct, step) => _reembAlmSetProgress(pct, step)
                );
            } catch (error) {
                _reembAlmToggleRunning(false);
                showError(error.message || 'Erro ao iniciar o robô.');
            }
        }
```

- [ ] **Step 2: Commit**

```bash
git add public/js/core.js
git commit -m "feat(reembolsos): adiciona JS do fluxo Almoço com Cliente"
```

---

### Task 15: Verificação manual — preview do formulário + ajuste ao vivo do robô

**Files:** nenhum (apenas verificação)

Esta tarefa não modifica código por padrão — só existe código a mudar se a verificação encontrar um problema, e nesse caso os ajustes voltam para os arquivos das Tarefas 7–11.

- [ ] **Step 1: Rodar a suíte completa de testes**

Run: `python -m pytest tests/ -v`
Expected: `PASS` em todos os testes (incluindo os já existentes antes deste plano).

- [ ] **Step 2: Subir o app e abrir o submódulo no navegador**

Suba o servidor Flask local (`python app.py` ou o comando de dev já usado no projeto) e abra o Toca no navegador. Vá em AutoToca → clique em "Reembolsos". Confirme visualmente:
- O painel abre e fecha corretamente junto com os outros módulos do AutoToca (Chamado Jurídico, Mala Direta, Sync Outlook)
- Trocar "Tipo de reembolso" alterna entre os dois formulários
- Trocar "Sub-fluxo" (Deslocamento/Estacionamento) alterna os blocos de campos
- O dropdown de Conta carrega (usa `/api/autotoca/accounts`, já existente)
- Anexar um comprovante de imagem no campo "Comprovante (para ler a data)" preenche a Data do Deslocamento automaticamente (requer `openrouter_api_key` configurada em Configurações > Integrações — se não estiver configurada, o campo de data fica em branco e precisa ser preenchido manualmente, comportamento esperado)

- [ ] **Step 3: Sessão de ajuste ao vivo do robô com o usuário**

Com o usuário logado no e-Reembolso (mesmo navegador/perfil que o robô vai reutilizar), rodar um teste real de cada sub-fluxo (Deslocamento, Estacionamento, Almoço com Cliente) **sem clicar em Enviar no final** — o objetivo é confirmar/corrigir, junto com o usuário observando a janela do robô:
1. Se `choose_select2_option` localiza e seleciona corretamente Célula Custo, Cliente, Serviço, Tipo do Transporte e Tipo do Deslocamento — ajustar o seletor em `integrations/reembolso_robot.py` (`_field_container`/`choose_select2_option`) se não bater.
2. Se Cliente/Serviço realmente dependem de Célula Custo estar selecionada antes de aparecerem populados (cascata) — se sim, considerar aumentar o `page.wait_for_timeout(800)` ou trocar por uma espera explícita (`page.wait_for_selector` num elemento que só aparece após a cascata).
3. Como o campo de pedágio realmente se comporta no fluxo de Deslocamento — se a implementação atual (segunda entrada em "Outros deslocamentos" com Tipo=Pedágio) bate com o que o usuário observa no site, ou se precisa mudar para preencher campos que abrem dentro do próprio bloco de KM.
4. Se "Km Rodado" e "Valor Total em R$" do bloco de KM realmente são calculados automaticamente pelo site (sem exigir preenchimento do robô) — confirmar que nenhum erro aparece por esses campos ficarem vazios.

Registrar qualquer ajuste necessário como um novo commit em cima da Tarefa 8/9 (não é preciso reabrir tarefas antigas — trate como uma tarefa de correção pontual):

```bash
git add integrations/reembolso_robot.py
git commit -m "fix(reembolsos): ajusta seletores do robô após teste ao vivo"
```

- [ ] **Step 4: Confirmar o botão final nunca envia sozinho**

Em todos os testes da Step 3, confirmar visualmente que o robô parou antes do clique de envio e que foi o usuário quem decidiu enviar (ou fechar sem enviar). Este é um requisito não-negociável do design (mesma regra do Chamado Jurídico).

---

## Self-review do plano

**Cobertura do spec:** Célula Custo/Cliente/Serviço/Descrição comuns (Task 8/9), Origem+histórico (Task 5, 13), Destino+Contas+IA (Task 5, 13), Data via OCR (Task 3, 13), Tipo de transporte/Ida-volta/Descrição gerada (Task 8), Pedágio com soma e arquivo corrompido (Task 3, 4, 8, 10), Estacionamento com Quantidade/Período/Valor (Task 8, 13), Almoço com Cliente completo (Task 9, 11, 14), confirmação manual final (Task 8/9 `_finish_and_wait_submit`, Task 15). Sem lacunas identificadas.

**Placeholders:** nenhum "TBD"/"implementar depois" no plano — os únicos pontos deliberadamente abertos (seletores exatos do Select2, comportamento do pedágio) estão documentados como itens de ajuste ao vivo na Task 15, com um roteiro concreto do que checar, não um placeholder genérico.

**Consistência de tipos:** `payload['sub_fluxo']` usado com os mesmos valores `'deslocamento'`/`'estacionamento'` em Task 8 (robô) e Task 10 (rota) e Task 13 (frontend); `file_paths` com as mesmas chaves (`data_deslocamento_comprovante`, `pedagio_comprovantes`, `estacionamento_comprovantes`) em Task 8 e Task 10; `_reembolso_aggregate_receipts` (Task 2) não é chamado diretamente pela rota — a agregação equivalente é feita no frontend (Task 13/14, via `_reembExtractFile` chamado por arquivo) para permitir preview antes do envio; o helper Python fica disponível para eventual reuso/teste mas o cálculo que efetivamente vai para o robô vem do payload montado no frontend. Isso é intencional (o usuário precisa ver o valor somado antes de confirmar o envio), documentado aqui para não parecer código morto.
