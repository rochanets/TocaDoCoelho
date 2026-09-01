# WikiToca — submódulos + novo módulo Capacitação — Design

**Data:** 2026-08-28
**Status:** Aprovado pelo usuário

## Objetivo

Reorganizar o WikiToca — hoje uma tela única com duas colunas lado a lado
(Conhecimentos registrados e Documentos) — em **três submódulos** no mesmo padrão
visual do AutoToca, adicionar **busca por conteúdo** no submódulo de Documentos e
criar o submódulo **Capacitação**: instâncias independentes (estilo Google
NotebookLM) onde o usuário anexa documentos e conversa com a IA sobre eles.

## Decisões tomadas (com o usuário)

1. **Navegação igual ao AutoToca** — linha de botões `.btn-auto-mapping` no topo,
   um painel visível por vez. Reaproveita CSS existente.
2. **Submódulo padrão ao abrir a aba:** Conhecimentos (comportamento atual).
3. **Busca de Documentos:** nome/título **+ conteúdo extraído do arquivo**, com
   texto cacheado em coluna nova (`extracted_text`).
4. **Documentos de Capacitação são isolados** por instância: não aparecem no
   submódulo Documentos nem entram na base do iToca.
5. **Sidebar direita da Capacitação:** uma caixinha por instância; cada instância
   tem **uma conversa contínua**.
6. **Título da instância:** gerado por IA após o processamento do **primeiro**
   documento; renomeável a qualquer momento pelo usuário.
7. **Origem da resposta:** cascata automática, com **selo na resposta** indicando
   de onde veio (documentos / base WikiToca / web).
8. **Contexto para o LLM:** chunking + pontuação por relevância (técnica já usada
   pelo iToca), não texto completo truncado.
9. **Imagens:** OCR via Tesseract (`pytesseract`, já dependência). Sem o binário
   instalado, o arquivo sobe mas fica marcado como "sem texto extraído".
10. **Sem PPT:** apresentações ficam fora desta versão. A Capacitação aceita
    PDF, Word e imagens; o submódulo Documentos e a base do iToca continuam
    aceitando só PDF/Excel/Word.
11. **Indexação:** no upload (assíncrona, com barra + coelho) e botão
    **"Reindexar documentos"** para o backfill dos arquivos já existentes.
12. **Escalada para os passos seguintes da cascata:** quem decide relevância é a
    IA, sinalizando `INSUFICIENTE`. Há também um corte antes da chamada, mas ele
    é deliberadamente permissivo — ver "Sobre o corte por score", adiante.
13. **"Limpar conversa"** por instância (via `uiConfirm`), preservando os arquivos.
    Efeito colateral aceito pelo usuário em 31/08/2026: como o `updated_at` é
    tocado e o histórico vira vazio, a instância **salta para o topo da sidebar**
    ao ser limpa. É surpreendente mas foi decidido manter — não "corrigir" depois.
14. **Fora de escopo nesta versão:** export/import `.zip` de instâncias de
    Capacitação.

## Estado atual (ponto de partida)

| Peça | Onde está |
|---|---|
| Markup do WikiToca | `public/index.html:455` (`#wikitoca`, `.wiki-grid` com 2 `.wiki-card`) |
| JS do WikiToca | `public/js/itoca-autotoca.js:3914` em diante (`loadWikiTocaData`, `loadWikiEntries`, `loadWikiDocuments`, modais) |
| Backend | `routes/wikitoca.py` (entries CRUD, documents CRUD, export/import xlsx e zip) |
| Tabelas | `wiki_entries`, `wiki_documents` (`app.py:547` e `app.py:557`) |
| Padrão de submódulo | `toggleAutoTocaAutomation()` em `public/js/core.js:1666` |
| Extração de texto | `_itoca_extract_text_from_file()` em `app.py:4701` (PDF → pdfplumber → pdftotext → OCR; DOCX; XLSX; TXT) |
| Tarefas assíncronas | `_bg_task_set/_bg_task_get/_bg_task_cleanup` (`app.py:9599`) + `GET /api/tasks/<task_id>` (`app.py:9841`) |
| Padrão de chat com histórico | `POST /api/itoca/ask` em `routes/itoca.py`, tabela `itoca_chat_history` |

## Arquitetura

### Frontend — arquivo novo

Todo o JS do WikiToca migra de `public/js/itoca-autotoca.js` (4364 linhas, hoje
misturando iToca + AutoToca + WikiToca) para **`public/js/wikitoca.js`**, incluído
no `index.html` junto dos demais módulos. Sem essa separação os três submódulos
levariam o arquivo a ~5.500 linhas.

O que migra sem alteração de comportamento: `loadWikiEntries`, `openWikiEntryModal`,
`closeWikiEntryModal`, `saveWikiEntry`, `deleteWikiEntry`, `toggleWikiEntry`,
`toggleWikiEntriesSort`, `updateWikiSortButtonLabel`, `exportWikiEntries`,
`openWikiImportModal`/`closeWikiImportModal`/`onWikiXlsxSelected`/`confirmWikiXlsxImport`,
`loadWikiDocuments`, `onWikiFileSelected`, `clearWikiFileSelection`,
`uploadWikiDocument`, `deleteWikiDocument`, `exportWikiDocuments`,
`openWikiDocImportModal`/`closeWikiDocImportModal`/`onWikiDocZipSelected`/`confirmWikiDocZipImport`,
`getWikiApiErrorDetails`, `renderWikiErrorBlock`, e a variável de ordenação
`wikiEntriesSortOrder`.

### Navegação entre submódulos

```
[📚 Conhecimentos]  [📄 Documentos]  [✦ Capacitação]
```

- Nova `toggleWikiSubmodule(key)` em `core.js`, espelhando `toggleAutoTocaAutomation()`:
  esconde todos os painéis, mostra o alvo, aplica a classe `active` no botão correspondente.
  Ao contrário do AutoToca, **nunca fica sem painel** — clicar no botão já ativo não fecha.
- `switchTab(..., 'wikitoca')` chama `loadWikiTocaData()`, que agora abre o submódulo
  **Conhecimentos** e carrega **somente** os dados dele. Cada submódulo carrega os seus
  dados na primeira vez que é aberto.
- A barra de busca global (`#wikiSearchInput` + botões Buscar/Limpar) é removida do
  cabeçalho; cada submódulo passa a ter a sua própria caixa de busca no topo do painel.
  Conhecimentos mantém exatamente o comportamento de busca de hoje (título, categoria,
  conteúdo, tags via query string em `GET /api/wikitoca/entries`).

## Submódulo Documentos — busca por conteúdo

### Schema (migração 33)

`wiki_documents` ganha:

| Coluna | Tipo | Uso |
|---|---|---|
| `extracted_text` | TEXT | Texto extraído do arquivo, cacheado |
| `extracted_at` | TIMESTAMP | Quando a extração terminou |
| `extract_status` | TEXT | `pending` \| `ok` \| `empty` \| `error` |

### Fluxo de indexação

- **No upload:** `POST /api/wikitoca/documents` grava a linha com
  `extract_status='pending'` e responde imediatamente; uma thread extrai o texto de
  cada arquivo com `_itoca_extract_text_from_file()` e atualiza a linha. O progresso
  vai por `_bg_task_set` e o frontend faz polling em `GET /api/tasks/<task_id>` a cada
  800ms, com a barra verde e o WebP `/images/coelho-correndo.webp` (classe `.coelho-run`).
  O documento aparece na lista na hora, com selo "Indexando…".
- **Backfill:** botão **"Reindexar documentos"** no cabeçalho do submódulo dispara
  `POST /api/wikitoca/documents/reindex` → 202 + `task_id`. Processa todos os
  documentos com `extract_status` nulo/`pending`/`error`, reportando
  "Processando X de Y — nome-do-arquivo.pdf". Aceita `{"force": true}` para
  reprocessar também os já indexados.
- `empty` = extração rodou e não achou texto (ex.: PDF escaneado sem Tesseract).
  `error` = a extração lançou exceção. Ambos aparecem como selo discreto no item da
  lista, com o motivo no `title` do elemento.

### Busca

`GET /api/wikitoca/documents?q=<termo>&ext=<pdf|word|excel>`:

- Casa `q` (case-insensitive, sem acento) contra `original_name`, `title` e
  `extracted_text`.
- Filtro `ext` mapeia: `pdf` → `.pdf`; `word` → `.doc`/`.docx`; `excel` → `.xls`/`.xlsx`.
  Valor desconhecido (`?ext=lixo`, ou `?ext=docx` em vez de `word`) é **ignorado em
  silêncio** e devolve o acervo inteiro, em vez de 400. Decisão consciente
  (31/08/2026): é o comportamento comum em APIs de listagem, e o `<select>` da UI só
  emite os três valores válidos. A revisão da Task 4 argumentou por 400 citando
  precedente no próprio repositório — se um dia algo passar a montar essa URL na mão,
  vale reconsiderar.
- Para cada resultado com match no conteúdo, retorna `snippet`: ~200 caracteres em
  volta da primeira ocorrência, com o termo envolto em `<mark>`. O frontend renderiza
  o snippet abaixo dos metadados do documento (o restante do texto é escapado com
  `escapeHtml`; só o `<mark>` é inserido pelo backend em posição conhecida).
- Sem `q`, o comportamento é o atual (lista completa).

## Submódulo Capacitação

### Schema (migração 33)

```sql
CREATE TABLE IF NOT EXISTS wiki_training_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    title_source TEXT DEFAULT 'ai',       -- 'ai' = a IA pode (re)escrever; 'manual' = usuário nomeou
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wiki_training_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    file_url TEXT NOT NULL,
    file_ext TEXT,
    file_size INTEGER,
    extracted_text TEXT,
    extract_status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wiki_training_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    source_kind TEXT,        -- 'documents' | 'wiki' | 'web' | NULL (mensagem do usuário)
    source_refs TEXT,        -- JSON: nomes dos arquivos/itens que embasaram
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wiki_training_docs_session ON wiki_training_documents(session_id);
CREATE INDEX IF NOT EXISTS idx_wiki_training_msgs_session ON wiki_training_messages(session_id, created_at);
```

Arquivos gravados em `uploads/wikitoca/capacitacao/<session_id>/`, servidos por
`/uploads/wikitoca/capacitacao/<session_id>/<file_name>`. Nenhuma dessas tabelas
entra na indexação do iToca (`_itoca_*`).

### Layout (2 colunas)

```
┌ Capacitação ─────────────────────────────────┬──────────────────┐
│ Onboarding Comercial 2026        ✏️ 🧹 🗑     │ CAPACITAÇÕES     │
│ [📄 manual.pdf ×] [🖼 fluxo.png ×] [+ Anexar]  │ [+ Nova]         │
│ ───────────────────────────────────────────── │ ┌──────────────┐ │
│ 🧑 Qual o prazo de aprovação?                │ │Onboarding…   │◀│
│ 🐇 Segundo o manual, 5 dias úteis…           │ │3 docs · hoje │ │
│    📄 Documentos desta capacitação            │ └──────────────┘ │
│       manual.pdf                              │ ┌──────────────┐ │
│ ┌─────────────────────────────────┐ [Enviar] │ │Compliance…   │ │
│ │ Pergunte sobre os documentos…   │           │ └──────────────┘ │
└───────────────────────────────────────────────┴──────────────────┘
```

- **Chips de documento** numa faixa horizontal acima do chat: ícone por tipo, nome
  truncado, `×` para remover (com `uiConfirm`). Clicar no chip abre o arquivo em nova
  aba. Chip em processamento mostra spinner; chip sem texto extraído mostra `⚠` com
  tooltip explicando.
- **Sidebar direita** com uma caixinha por instância (título, contagem de documentos,
  data da última mensagem). A instância ativa fica destacada. Botão `+ Nova` no topo.
- **Cabeçalho:** título editável inline (✏️), 🧹 "Limpar conversa" (`uiConfirm`, apaga
  as mensagens e mantém os arquivos), 🗑 "Excluir capacitação" (`uiConfirm`, apaga
  mensagens, registros de documento e os arquivos em disco).
- **Estado vazio:** sem nenhuma instância, o painel central mostra um convite
  ("Crie sua primeira capacitação") com o botão de criação.
- **Responsivo:** abaixo de 1100px a sidebar vira um botão "Capacitações (N)" que abre
  uma gaveta deslizante pela direita.
- Bolhas de chat reaproveitam o CSS do chat do iToca; nada de `confirm()`/`prompt()`
  nativos.

### Ingestão de documentos

Extensões aceitas: `.pdf`, `.doc`, `.docx`, `.png`, `.jpg`, `.jpeg`.
(`.doc` legado entra por consistência com o submódulo Documentos, mas `python-docx`
não o lê — cai em `extract_status='empty'`, exatamente como já acontece hoje.)

`_itoca_extract_text_from_file()` (`app.py:4701`) ganha um ramo novo, no mesmo
estilo defensivo dos existentes:

- **`.png`/`.jpg`/`.jpeg`** → `pytesseract.image_to_string(img, lang='por+eng')` com
  fallback para `lang='eng'`, localizando o binário via `_itoca_find_tesseract_cmd()`.
  Sem binário: retorna vazio e o documento fica `extract_status='empty'`; o chip
  mostra "sem texto extraído" com link para
  `https://github.com/UB-Mannheim/tesseract/wiki`.

Instâncias novas nascem com o título placeholder "Nova capacitação" e
`title_source='ai'`. Quando o **primeiro** documento de uma instância com
`title_source='ai'` termina com `extract_status='ok'`, o backend chama `_llm_prompt()`
pedindo um título curto (máx. ~6 palavras) a partir dos primeiros ~3000 caracteres e
grava mantendo `title_source='ai'`. Renomear pelo ✏️ grava `title_source='manual'` e a
IA nunca mais sobrescreve.

O upload é assíncrono com barra + coelho, igual ao submódulo Documentos.

### Cascata de resposta

`POST /api/wikitoca/capacitacao/<session_id>/ask` grava a mensagem do usuário,
retorna `202 {task_id}` e processa em thread; o frontend faz polling em
`GET /api/tasks/<task_id>`.

**Chunking e score** (helper novo `_wiki_rank_chunks(text_items, question, top_n)`,
reaproveitando a técnica de pontuação por palavras-chave já usada pelo iToca):
quebra cada `extracted_text` em blocos de ~1200 caracteres com sobreposição de ~150,
normaliza (minúsculas, sem acento) e pontua cada bloco pela quantidade de termos da
pergunta que ele contém, ponderada pela raridade do termo no conjunto.

**Passo 1 — documentos da instância.** Se nenhum bloco atingir o score mínimo, pula
direto ao passo 2 sem gastar chamada de LLM. Na prática esse atalho só dispara
quando os documentos **não têm nenhum termo significativo em comum** com a
pergunta — ver "Sobre o corte por score". Caso contrário, monta a pergunta com os
melhores blocos (limite de ~12000 caracteres), os nomes dos arquivos e as **últimas 6
mensagens** da instância (para follow-up), e instrui explicitamente: *responder
somente `INSUFICIENTE` se os trechos não cobrirem a pergunta*. Chama `_llm_prompt()`
(SAI primeiro, OpenRouter como fallback — regra do CLAUDE.md).

**Passo 2 — base WikiToca.** Mesmo procedimento sobre `wiki_entries` (título +
categoria + conteúdo) e `wiki_documents.extracted_text`. Mesma instrução de
`INSUFICIENTE`.

**Passo 3 — web.** `_llm_prompt(..., web=True)` (OpenRouter com plugin de web,
única exceção prevista no CLAUDE.md à ordem SAI-primeiro). Se também falhar, a
resposta gravada informa que não foi possível encontrar a informação.

A mensagem do assistente é gravada com `source_kind` e `source_refs`, e a UI mostra
o selo correspondente:

| `source_kind` | Selo |
|---|---|
| `documents` | 📄 Documentos desta capacitação + lista dos arquivos citados |
| `wiki` | 📚 Base WikiToca |
| `web` | 🌐 Pesquisa na web |

### Endpoints novos

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/wikitoca/capacitacao/sessions` | Lista instâncias (título, nº de docs, data da última mensagem) |
| POST | `/api/wikitoca/capacitacao/sessions` | Cria instância ("Nova capacitação") |
| PUT | `/api/wikitoca/capacitacao/sessions/<id>` | Renomeia (grava `title_source='manual'`) |
| DELETE | `/api/wikitoca/capacitacao/sessions/<id>` | Exclui instância, mensagens, documentos e arquivos |
| GET | `/api/wikitoca/capacitacao/sessions/<id>` | Detalhe: documentos + histórico completo |
| POST | `/api/wikitoca/capacitacao/sessions/<id>/documents` | Upload multipart → 202 + `task_id` |
| DELETE | `/api/wikitoca/capacitacao/documents/<doc_id>` | Remove documento (registro + arquivo) |
| POST | `/api/wikitoca/capacitacao/sessions/<id>/ask` | Pergunta → 202 + `task_id` |
| DELETE | `/api/wikitoca/capacitacao/sessions/<id>/messages` | Limpar conversa (mantém documentos) |
| POST | `/api/wikitoca/documents/reindex` | Backfill do `extracted_text` → 202 + `task_id` |

Todas em `routes/wikitoca.py`, seguindo o padrão do arquivo (executado no namespace
de `app.py`, com `logger.debug`/`logger.exception` por rota).

## Migração de banco

Entrada `(33, 'wikitoca_submodulos_capacitacao', [...])` em `SCHEMA_MIGRATIONS`
(`app.py:1311`) — próxima da linhagem `main`, que hoje termina em 18. Contém os
`ALTER TABLE` de `wiki_documents` (guardados por checagem de coluna existente, no
padrão do arquivo) e os três `CREATE TABLE IF NOT EXISTS` da Capacitação.
**Nada é criado apenas dentro de `init_db()`** — ele é a migração 1 e só roda uma
vez em banco novo; `tests/test_schema_migrations.py` falha se isso acontecer.

## Tratamento de erros

- **Extração falha** (arquivo corrompido, biblioteca ausente): documento fica
  `extract_status='error'`, aparece na lista com selo e é ignorado pela busca e pela
  cascata. Nunca derruba o upload dos outros arquivos do mesmo lote.
- **`_llm_prompt()` retorna `None`** (SAI e OpenRouter indisponíveis): a task vai para
  `status='error'` com mensagem explicando que nenhuma integração de IA respondeu; o
  chat mostra o erro como bolha de sistema, sem gravar resposta em branco.
- **Falha de rede no frontend:** reaproveita `getWikiApiErrorDetails()` /
  `renderWikiErrorBlock()`, que já produzem bloco de erro com causa e como corrigir.
- **Instância excluída durante uma pergunta em andamento:** o polling detecta 404 na
  task e limpa o estado do chat sem travar a UI.

## Testes

- `tests/test_schema_migrations.py` (já existente) valida que a migração 33 cria as
  tabelas em banco novo e em banco legado.
- Teste de `_itoca_extract_text_from_file()` para imagem, cobrindo o caso sem o
  binário do Tesseract instalado (não pode levantar exceção).
- Teste de `_wiki_rank_chunks()`: pergunta sem nenhum termo em comum devolve `[]`
  (garante que o passo 1 é pulado); pergunta com termos em comum devolve os trechos
  em ordem decrescente de score, truncados em `top_n`.
- Teste de rota da busca de documentos: `q` casando em `extracted_text` retorna o
  documento com `snippet`; filtro `ext` restringe corretamente.
- Teste da cascata com `_llm_prompt` mockado: `INSUFICIENTE` no passo 1 leva ao passo 2;
  `INSUFICIENTE` no passo 2 leva ao passo 3 com `web=True`.

## Fora de escopo

- Export/import `.zip` de instâncias de Capacitação.
- Múltiplas conversas dentro de uma mesma instância (uma instância = uma conversa).
- Apresentações (`.pptx`) em qualquer submódulo — exigiria a dependência nova
  `python-pptx` no instalador.
- Descrição de imagens por modelo multimodal (só OCR nesta versão).
