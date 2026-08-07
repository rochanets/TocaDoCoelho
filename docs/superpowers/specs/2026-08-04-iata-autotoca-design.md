# iAta no AutoToca — ata estruturada por Gerente → Conta → Oportunidade

**Data:** 2026-08-04
**Status:** aprovado (design)

## Problema

O iAta hoje vive como sub-aba do Portfolio e gera uma ata genérica de reunião
(objetivo, resumo, pauta, pontos-chave, decisões, próximos passos). Isso não
serve para o uso real: as reuniões são de pipeline comercial, e a ata precisa
sair organizada por **gerente comercial → conta → oportunidade**, com o status
da ata anterior carregado em cada oportunidade e o update novo por cima.

Também não há continuidade entre atas: cada ata é um documento isolado, então o
"o que ficou combinado na semana passada" se perde.

## Objetivo

1. Mover o iAta para o módulo AutoToca.
2. Trocar o formato da ata pela estrutura hierárquica de pipeline.
3. Dar continuidade entre atas (status anterior carregado, oportunidade não
   citada vira "sem update").
4. Permitir editar a ata como texto e enviá-la por e-mail com formatação
   íntegra.

## Fora de escopo

- Transcrição de áudio/vídeo de reunião. A entrada continua sendo texto
  (PDF, DOCX, VTT, SRT, TXT ou colado).
- Chunking por gerente para transcrições que estourem o contexto do modelo.
  Se aparecer na prática, entra depois (ver "Riscos").

## Estado atual (mapeamento)

| Peça | Onde está hoje |
|---|---|
| Sub-aba no Portfolio | `public/index.html:736`, `public/index.html:754-758` |
| `switchPortfolioSubmodule('iata')` | `public/js/itoca-autotoca.js:3517-3528` |
| `loadIAta()` / `openIAtaModal()` | `public/js/itoca-autotoca.js:3915`, `:4305` |
| Helpers `_iata_*` | `app.py:9575-9965` |
| Rotas `/api/portfolio/iata*` | `routes/portfolio.py:301-380` |
| Tabela `iata_records` | `app.py:688` (init_db) |
| Envio de e-mail | `_outlook_send_mail` (`app.py:7539`) → `integrations/outlook_graph.py:602` |
| Contas do CRM | tabela `accounts` (`app.py:587`) |

## Arquitetura

### Decisão central: extração por IA, reconciliação em Python

A geração acontece em duas fases:

**Fase 1 — extração (IA).** Uma chamada `_llm_prompt()` recebe a transcrição da
reunião nova e devolve JSON com a hierarquia
`managers[] → accounts[] → opportunities[] {name, update, responsible}`, mais o
cabeçalho (título, data, hora, participantes, tema).

**Fase 2 — reconciliação (Python).** O código casa cada oportunidade extraída
com as oportunidades da ata anterior por **nome normalizado** (minúsculo, sem
acento, pontuação virando espaço, espaços colapsados). Regras:

- Match exato normalizado → mesma oportunidade; `previous_status` recebe o
  `update_text` da ata anterior; `prev_opportunity_id` aponta para a linha
  anterior.
- Nenhum candidato → oportunidade nova; `previous_status = NULL`.
- Mais de um candidato parecido (mesma conta, nomes próximos) → **uma** chamada
  de IA curta, em lote, resolvendo todos os ambíguos de uma vez: "estes pares
  são a mesma oportunidade?". Sem resposta utilizável, trata como nova e marca
  `match_confidence = 'baixa'` para revisão do usuário.
- Oportunidade que existia na ata anterior e **não** apareceu na nova → entra na
  ata com `carried_over = 1`, `previous_status` preenchido e
  `update_text = 'Sem update nesta reunião'`.

Por que assim: a garantia de "nada da ata anterior some" precisa ser código, não
promessa do modelo. Isso é o mesmo princípio já validado no robô de formulário
(CLAUDE.md): a IA resolve linguagem, o código resolve regra.

### Fase 0 — base da ata

Antes de processar, o usuário escolhe a base:

- **(a) Ata do histórico** — combo com as atas salvas (padrão).
- **(b) Upload da ata anterior** — arquivo; o texto passa por uma extração IA
  no mesmo schema hierárquico, para virar a "ata anterior" da reconciliação.
- **(c) Do zero** — sem ata anterior; toda oportunidade é nova.

### Vínculo com o CRM

Para cada conta extraída, a IA sugere a conta correspondente em `accounts`
(comparação por nome normalizado + desempate por IA quando ambíguo). A tela de
revisão mostra a sugestão; o vínculo só é gravado (`iata_accounts.account_id`,
`match_confirmed = 1`) após clique do usuário. Sem confirmação, a conta fica
como texto livre.

### Identificação do gerente

A IA identifica o gerente comercial responsável por cada bloco a partir do
texto. Não identificando, o bloco sai como literal `Gerente não identificado` —
nunca um nome inventado. O responsável default de uma oportunidade sem
responsável explícito é o gerente daquele bloco (inclusive o rótulo de não
identificado).

## Modelo de dados

Alterações em `iata_records`:

| Coluna nova | Tipo | Uso |
|---|---|---|
| `previous_record_id` | INTEGER NULL | ata usada como base |
| `body_markdown` | TEXT | corpo renderizado/editável |
| `body_edited` | INTEGER DEFAULT 0 | 1 se o usuário editou o texto |
| `reparse_failed` | INTEGER DEFAULT 0 | 1 se o re-parse pós-edição falhou |
| `format_version` | INTEGER DEFAULT 2 | 1 = formato antigo, 2 = hierárquico |

Tabelas novas:

```sql
CREATE TABLE iata_managers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    display_order INTEGER DEFAULT 0,
    FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE
);

CREATE TABLE iata_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    manager_id INTEGER NOT NULL,
    account_id INTEGER,              -- FK opcional para accounts
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    match_confidence TEXT,           -- alta | media | baixa
    match_confirmed INTEGER DEFAULT 0,
    display_order INTEGER DEFAULT 0,
    FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
    FOREIGN KEY(manager_id) REFERENCES iata_managers(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
);

CREATE TABLE iata_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL,
    iata_account_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    previous_status TEXT,
    update_text TEXT,
    responsible TEXT,
    carried_over INTEGER DEFAULT 0,
    prev_opportunity_id INTEGER,     -- encadeia com a ata anterior
    display_order INTEGER DEFAULT 0,
    FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
    FOREIGN KEY(iata_account_id) REFERENCES iata_accounts(id) ON DELETE CASCADE,
    FOREIGN KEY(prev_opportunity_id) REFERENCES iata_opportunities(id) ON DELETE SET NULL
);
```

Índices: `idx_iata_acc_record(record_id)`, `idx_iata_opp_record(record_id)`,
`idx_iata_opp_prev(prev_opportunity_id)`, `idx_iata_opp_norm(name_norm)`.

`prev_opportunity_id` é o que permite a timeline de uma oportunidade ao longo
de várias atas.

**Migração:** as tabelas e as colunas novas entram como
`SCHEMA_MIGRATIONS` versão 17 (`app.py:1222`) **e** no `init_db` (`app.py:688`).
As duas linhagens convivem no mesmo `.db`; criar só em um dos lugares deixa
bases existentes sem as tabelas.

Registros antigos ficam com `format_version = 1` e continuam abrindo no
renderizador antigo. Nada é convertido retroativamente.

## Backend

- Helpers `_iata_*` saem de `app.py` para `integrations/iata.py`
  (extração de arquivo, prompts, parsing, reconciliação, render markdown,
  render HTML de e-mail). O `app.py` já passa de 12k linhas e esse bloco é
  autocontido.
- Rotas saem de `routes/portfolio.py` para `routes/autotoca_iata.py`, sob
  `/api/autotoca/iata*`, **sem alias** para os caminhos antigos — o único
  consumidor é o front do próprio app.

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/autotoca/iata` | lista atas |
| GET | `/api/autotoca/iata/<id>` | ata completa (hierarquia + markdown) |
| POST | `/api/autotoca/iata` | inicia geração → `202 {task_id}` |
| GET | `/api/autotoca/iata/tasks/<id>` | polling de progresso |
| PUT | `/api/autotoca/iata/<id>/body` | salva o texto editado |
| POST | `/api/autotoca/iata/<id>/accounts/<acc_id>/link` | confirma vínculo com o CRM |
| POST | `/api/autotoca/iata/<id>/email` | envia por e-mail |
| GET | `/api/autotoca/iata/<id>/email/preview` | HTML do e-mail |
| DELETE | `/api/autotoca/iata/<id>` | remove |

Toda chamada de LLM usa `_llm_prompt()` (SAI → OpenRouter), sem `web=True`.

Processamento assíncrono no padrão do projeto (thread + task store + polling),
com etapas: extrair texto (15%) → extrair hierarquia (35%) → casar contas
(55%) → reconciliar com a anterior (70%) → insights STF opcionais (85%) →
salvar (95%) → concluído (100%).

## Edição e sincronização

O corpo da ata é editável como texto na tela. Ao salvar (`PUT .../body`):

1. Grava `body_markdown` e `body_edited = 1` — o texto do usuário nunca se
   perde, aconteça o que acontecer no passo 2.
2. Roda um re-parse (IA) do texto editado de volta para a hierarquia e
   reescreve `iata_managers` / `iata_accounts` / `iata_opportunities`,
   preservando `prev_opportunity_id` e `account_id` das linhas que continuam
   casando por `name_norm`.
3. Se o re-parse falhar, mantém a estrutura anterior, marca
   `iata_records.reparse_failed = 1` e a tela avisa: "texto salvo, mas a
   estrutura não pôde ser atualizada — a próxima ata pode não carregar os
   status corretamente".

Exibição e e-mail sempre usam `body_markdown`. A hierarquia relacional é a
fonte para a continuidade da próxima ata.

## E-mail

Assunto: `Ata — {título} — {data}`.

Corpo em HTML com **estilos inline** e `<ul>` aninhado de verdade — clientes de
e-mail descartam `<style>` no `<head>`, e indentação por espaços/markdown cru
quebra em Outlook e Gmail. Sem CSS externo, sem classes.

Envio via `_outlook_send_mail`. O `send_mail` do Graph valida **um** endereço
(`integrations/outlook_graph.py:608`), então múltiplos destinatários viram um
envio por endereço, com relatório de sucesso/falha por destinatário na resposta.
Preview obrigatório antes do envio.

## Frontend

- Botão `autoTocaBtn_iata` na fileira do AutoToca (`public/index.html:866-870`),
  no padrão `btn-auto-mapping` com `<span class="ai-star-icon">✦</span>`,
  abrindo o painel `autoTocaIAta` com a lista de atas + "Nova Ata".
- Remoção da sub-aba iAta do Portfolio: botão (`index.html:736`), painel
  (`:754-758`) e o branch `'iata'` de `switchPortfolioSubmodule`
  (`itoca-autotoca.js:3528`).
- Código do iAta migra para `public/js/autotoca-iata.js`, carregado junto dos
  demais.
- Modal: passo "base da ata" → passo "reunião nova" → `#progressArea` com a
  barra verde e `/images/coelho-correndo.webp` (classe `.coelho-run`).
- Tela da ata: cabeçalho, hierarquia renderizada, blocos opcionais no fim,
  botões "Editar texto", "Enviar por e-mail", "Excluir".
- Confirmações com `await uiConfirm(...)` — nunca `confirm()` nativo.

## Formato de saída

```
Título da Reunião: <título>
Data e horário: <data> <hora>
Participantes: <nomes>
Tema: <tema>

Gerente Comercial: <nome ou "Gerente não identificado">

  • <Conta 1>
      • <Oportunidade 1>: <status carregado da ata anterior>
          • Update: <update desta reunião>
          • Responsável: <responsável ou o gerente do bloco>
      • <Oportunidade 2>: ...
```

Um gerente pode ter N contas; uma conta, N oportunidades. Seções opcionais
(pauta, decisões, próximos passos e insights STF) entram depois da hierarquia,
com toggle no modal de criação.

## Erros

| Situação | Comportamento |
|---|---|
| LLM indisponível (SAI e OpenRouter) | task `error` com mensagem clara; nada gravado |
| JSON inválido da IA | uma nova tentativa; persistindo, erro explícito |
| Hierarquia vazia (nenhum gerente/conta) | grava a ata só com cabeçalho e avisa que nada de pipeline foi identificado |
| Ata anterior ilegível | segue como "ata do zero", avisando na tela |
| Re-parse do texto editado falha | texto preservado, aviso de estrutura desatualizada |
| Falha no envio de e-mail | reporta por destinatário; ata intacta |

Todo erro de geração vai para `app.log` via `logger.exception`, com o `task_id`.

## Testes

- Normalização de nomes: acento, pontuação, caixa, espaços.
- Reconciliação: match exato, sem match, ambíguo, e o caso central de
  oportunidade ausente na reunião nova virando "Sem update nesta reunião".
- Parsing do JSON hierárquico da IA, incluindo resposta em bloco ```json.
- Render markdown e render HTML do e-mail (aninhamento e estilos inline).
- Migração 17 no `tests/test_schema_migrations.py`: base antiga sobe com as
  tabelas novas.
- Round-trip de edição: texto editado → re-parse → hierarquia equivalente.

## Riscos

- **Transcrição longa** estourando o contexto do modelo. Mitigação inicial:
  truncar como hoje (30k chars) e registrar no log quando houver truncamento —
  se acontecer de verdade, chunking por gerente vira o próximo passo.
- **Re-parse do texto editado** é o ponto mais frágil do desenho; por isso o
  texto é gravado antes e a falha é visível, nunca silenciosa.
