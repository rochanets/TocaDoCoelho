# Unificação AutoToca + Reports e enriquecimento do Preparar Reunião

Data: 2026-06-30

## Objetivo

1. Unificar os módulos **Reports** e **AutoToca**: mover as subfunções de Reports
   (Preparar Reunião e Relationship Report) para dentro de AutoToca, remover o item
   de menu "Reports" e mover o item de menu "AutoToca" para logo abaixo de "Dashboard".
2. Enriquecer a subfunção **Preparar Reunião** com uma nova seção de "Contexto da Conta"
   que aparece quando o contato está vinculado a uma conta mapeada no sistema.

Restrição do usuário: **manter o nome do módulo "AutoToca"** e o header/subtítulo atuais
sem alteração.

## Contexto atual (código existente)

- Frontend SPA único em `public/index.html` (~18k linhas). Backend Flask em `app.py`.
- Menu lateral em `public/index.html` (~linha 3351). Ordem atual:
  Home · iToca · Dashboard · Reports · WikiToca · Kanban · Gestão de Conta ·
  Portifólio · AutoToca · Atividades · Agenda · Gestão de Contatos.
- Aba `#reports` (~linha 3987) contém dois painéis:
  - `reportsPanel_preparar-reuniao` (Preparar Reunião via LinkedIn)
  - `reportsPanel_relationship-report` (`reportsRelationshipContent`)
  - Botões alternam painéis via `toggleReportsPanel('preparar-reuniao'|'relationship-report')`.
  - Maps de painéis/botões em ~linha 6445.
- Aba `#autotoca` (~linha 4085) contém botões: Chamado Jurídico, Mala Direta,
  WhatsApp Update, Sync Outlook (padrão `btn-auto-mapping` com ícone `✦`).
- Preparar Reunião:
  - Frontend `gerarResumoLinkedIn()` (~linha 17473) → `POST /api/linkedin/summarize`.
  - Backend `linkedin_summarize()` (`app.py` ~13144) inicia thread
    `_linkedin_process_async(task_id, linkedin_url, profile_text, meeting_context, extension_photo_url)`
    (~13076), com barra de progresso/polling (coelhinho 🐇) já implementada.
  - Resultado renderizado por `_renderLinkedInResult` / `_renderLinkedInSummary`.
- Vinculação contato→conta: `LOWER(TRIM(clients.company)) = LOWER(TRIM(accounts.name))`
  (ver `_relation_report_collect_data`, `app.py` ~1592).
- `clients` tem colunas `company`, `linkedin`, `photo_url`.
- Peças reaproveitáveis:
  - `_relation_report_fetch_market_context(account_name)` (`app.py` ~1922) — momento de mercado (1 parágrafo).
  - `account_presences` (Serviços Stefanini mapeados por conta).
  - `_sai_simple_prompt()` → fallback OpenRouter para resumo com IA (ver CLAUDE.md).

## Parte 1 — Unificação de módulos

### Menu lateral (`public/index.html` ~3351)
- Remover o botão `nav-reports`.
- Mover o botão `nav-autotoca` para imediatamente abaixo de `nav-dashboard`.
- Nova ordem: Home · iToca · Dashboard · **AutoToca** · WikiToca · Kanban ·
  Gestão de Conta · Portifólio · Atividades · Agenda · Gestão de Contatos.

### Conteúdo
- A aba `#autotoca` passa a hospedar os botões e painéis de Reports.
- Barra de botões da aba AutoToca (ordem): **Preparar Reunião**, **Relationship Report**,
  Chamado Jurídico, Mala Direta, WhatsApp Update, Sync Outlook.
  (ex-Reports primeiro por serem analíticos/alta frequência.)
- Mover os painéis `reportsPanel_preparar-reuniao` e `reportsPanel_relationship-report`
  (incluindo `reportsRelationshipContent`) para dentro de `#autotoca`; remover a aba `#reports`.
- **Manter** o header/subtítulo atuais de AutoToca (sem alteração de texto nem nome).
- Ajustes JS:
  - Unificar a lógica de toggle de painéis: os botões de Preparar Reunião e
    Relationship Report passam a conviver com `toggleAutoTocaAutomation`. Reaproveitar
    `toggleReportsPanel` apontando para os painéis já movidos, OU integrar ao
    mecanismo de toggle do AutoToca — escolher a abordagem que minimize regressões,
    garantindo que abrir um painel feche os demais.
  - A inicialização do Relationship Report (hoje disparada ao abrir a aba `reports`)
    passa a ocorrer ao abrir/usar a aba `autotoca`.
  - Remover/redirecionar qualquer referência a `switchTab(..., 'reports')` e às
    entradas de `reports` nos maps de tabs/painéis.

## Parte 2 — Nova seção "Contexto da Conta" no Preparar Reunião

Anexada após o resumo executivo atual, **quando uma conta mapeada é identificada**.

### Detecção da conta (automática + confirmação)
- Backend localiza o contato em `clients`:
  1. por `linkedin` (URL normalizada — minúsculas, sem querystring/trailing slash);
  2. fallback pelo nome extraído do perfil (`parsed['nome']`).
- Com o contato, usa `clients.company` para casar com `accounts.name`
  (`LOWER(TRIM(...))`). A conta detectada é retornada ao front.
- Front exibe a conta detectada com um **dropdown de contas** permitindo
  trocar/limpar. Se o usuário escolher/forçar uma conta, uma nova chamada
  re-gera os blocos a) e c) para a conta selecionada.

### Blocos da seção
- **a) Momento de mercado da conta** — `_relation_report_fetch_market_context(account_name)`,
  gerado **fresco a cada execução** (1 parágrafo). Depende apenas da conta.
- **b) Resumo do relacionamento com o contato** — resumo via IA
  (`_sai_simple_prompt` → fallback OpenRouter) das atividades do contato
  (`activities` ligadas ao `client_id`); quando houver pouco registro do contato
  isolado, complementar com o panorama da conta (`account_activities`).
  **Só aparece se o contato existir no sistema.**
- **c) O que temos na conta** — lista dos Serviços Stefanini (`account_presences`)
  da conta. Depende apenas da conta.

### Comportamento sem mapeamento completo
- Conta mapeada + contato não cadastrado → mostra a) e c), oculta b), e exibe
  **aviso curto** (ex.: "Contato não vinculado a um contato cadastrado no sistema").
- Nenhuma conta detectada → seção de contexto fica oculta (resumo idêntico ao atual);
  o usuário ainda pode escolher uma conta no dropdown para forçar a) e c).

### d) Fallback de foto
- Se a foto do LinkedIn não for resolvida por nenhuma das fontes atuais
  (extensão, og:image, busca web), localizar o contato por `linkedin`
  (depois por nome) e usar `clients.photo_url` se existir.

### Backend
- Estender `linkedin_summarize()` / `_linkedin_process_async` para aceitar um
  `account_id` opcional (confirmado/forçado pelo usuário).
- Novo helper para montar o contexto da conta retornando:
  `account_context = { account: {id, name}, market_moment, relationship_summary,
  stefanini_services: [...], contact_found: bool, contact_photo_url }`.
- Incluir `account_context` no `result` do task store.
- Novos steps na barra de progresso: "Analisando conta mapeada...",
  "Resumindo relacionamento...".
- Fallback de foto integrado ao fluxo de resolução de `photo_url` existente.

### Frontend
- `_renderLinkedInSummary` (ou `_renderLinkedInResult`) renderiza a nova seção
  "Contexto da Conta" abaixo do resumo, com os blocos a/b/c condicionais e o aviso curto.
- Dropdown de conta detectada com ação de trocar/limpar → re-busca contexto.
- Manter padrão visual existente (cards, cores verdes `#065f46`, etc.).

## Fora de escopo (YAGNI)
- Sem cache do momento de mercado (gerado fresco sempre).
- Sem alteração no schema do banco.
- Sem refatoração de partes não relacionadas do `index.html`.
- Sem alteração do nome/header do módulo AutoToca.

## Critérios de sucesso
- Menu sem "Reports"; "AutoToca" abaixo de "Dashboard"; Preparar Reunião e
  Relationship Report funcionando dentro de AutoToca sem regressão.
- Preparar Reunião exibe a seção de Contexto da Conta quando há conta mapeada,
  com os blocos corretos e o comportamento condicional descrito.
- Fallback de foto usa a foto do contato cadastrado quando o LinkedIn não carrega.
