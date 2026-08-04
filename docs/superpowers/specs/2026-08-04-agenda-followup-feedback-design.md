# Follow-up de compromisso na Agenda + Módulo de Feedback

**Data:** 2026-08-04
**Branch:** `claude/agenda-followup-feedback-module-231922`

Duas entregas independentes, agrupadas por terem sido pedidas juntas:

1. Registrar uma atividade de follow-up a partir de um compromisso da agenda.
2. Um módulo de Feedback que envia a mensagem do usuário — com o log técnico
   anexado — para o e-mail do administrador.

---

## Parte 1 — Follow-up do compromisso

### Problema

A agenda mostra os compromissos, mas depois da reunião não há caminho direto
para registrar o que aconteceu. O usuário precisa sair da agenda, ir em
Atividades, abrir "Nova Atividade" e reencontrar o contato na lista.

### Modelo de dados

Nova coluna em `commitments`:

```sql
ALTER TABLE commitments ADD COLUMN followup_activity_id INTEGER
```

Aplicada pela migração idempotente em `init_db()`, no mesmo bloco
`PRAGMA table_info(commitments)` que já cuida de `due_time` e `source_type`.

A coluna guarda o **último** follow-up registrado. Registrar um segundo
follow-up sobrescreve o vínculo; as atividades anteriores continuam
existindo normalmente no histórico do contato.

### Backend (`routes/activities_agenda.py`)

- `GET /api/agenda` passa a selecionar `cm.followup_activity_id`. O braço do
  `UNION ALL` que traz `account_renewal_events` devolve `NULL` nessa posição,
  mantendo as duas metades da união com o mesmo número de colunas.

- Nova rota `POST /api/agenda/<int:commitment_id>/followup`:
  - corpo: `{"activity_id": <int>}`
  - `404` se o compromisso não existir
  - `400` se a atividade não existir ou pertencer a outro `client_id`
    (evita vincular a atividade errada por corrida de UI)
  - grava `followup_activity_id` e devolve `{"message": ..., "followup_activity_id": ...}`

Nenhuma rota nova para *criar* a atividade: o follow-up usa o
`POST /api/atividades` que já existe, herdando a detecção automática de novos
compromissos no texto (`create_commitments_from_activity`) e a atualização de
`clients.last_activity_date`.

### Frontend

**Reuso deliberado do `#activityModal`.** Em vez de um modal novo, o follow-up
abre o modal de atividade que já existe, pré-configurado:

```
openFollowupModal(commitmentId)
  → localiza o compromisso em agendaMapByDay / lista corrente
  → openQuickActivityModal(client_id, client_name, client_company)   // trava o contato
  → título vira "Follow-up — <nome>"
  → contact_type = "Reunião"
  → textarea pré-preenchida: Follow-up do compromisso "<título>" (dd/mm):
  → _pendingFollowupCommitmentId = commitmentId
```

Herda de graça: ditado por voz, validação, detecção de compromissos no texto e
o refresh de dashboard/ficha do contato.

`saveActivity()` ganha um passo no caminho de sucesso: lê o `id` da resposta e,
se `_pendingFollowupCommitmentId` estiver setado, chama a rota de vínculo e
recarrega a agenda. A flag é limpa em `closeActivityModal()` para que um
cancelamento não contamine a próxima atividade avulsa.

**Onde o botão aparece:**

| Local | Elemento |
|---|---|
| Lista mensal da agenda (`loadAgenda`) | botão "Follow-up" ao lado de "Briefing" |
| Modal do dia (`openDayActivitiesModal`) | botão "Follow-up" acima de "Excluir evento" |

Compromisso com `followup_activity_id` preenchido exibe o selo
`✓ Follow-up registrado` e o botão passa a se chamar "Novo follow-up".

Eventos de renovação de conta (`id` prefixado com `acc-`, `source_type =
account_presence`) **não** recebem o botão: não têm contato associado.

---

## Parte 2 — Módulo de Feedback

### Decisão de canal

Envio por **e-mail via Microsoft Graph** (`_outlook_send_mail`), o mesmo
caminho já usado pelo briefing matinal, com destino padrão
`hfnetto@stefanini.com`.

Alternativas descartadas e por quê:

- **Issue no GitHub:** exigiria um token com permissão de escrita embarcado em
  cada instalação. Como o Toca roda na máquina do usuário, o token ficaria
  legível no `app_settings` e não seria rotacionável sem atualizar toda a base
  instalada. Some-se o limite de 65 mil caracteres no corpo da issue, que
  obrigaria a truncar o log.
- **Microsoft Forms embarcado em iframe:** impossível anexar o log (iframe é
  cross-origin, e query string não comporta centenas de KB) e o conteúdo do
  iframe não acompanha o tema do sistema.

O e-mail não distribui nenhum segredo novo — usa o Outlook que o próprio
usuário já autenticou — e identifica o remetente automaticamente.

### Modelo de dados

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    user_nickname TEXT,
    app_version TEXT,
    status TEXT DEFAULT 'pending',   -- pending | sent | error
    error TEXT,
    sent_to TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
)
```

O log **não** é duplicado no banco — já vive em `data/app.log`. A tabela existe
para que nada se perca quando o envio falhar (Outlook desconectado, sem rede).

### Backend (`routes/feedback.py`, novo)

Segue o padrão de tarefa assíncrona com barra de progresso exigido pelo
CLAUDE.md, porque o envio de e-mail passa de 2 segundos.

- `POST /api/feedback` — corpo `{"message": "..."}`. Grava a linha em
  `feedback`, dispara a thread e devolve `202 {"task_id": ...}`.
- `GET /api/feedback/tasks/<task_id>` — polling a cada 800 ms.

Passos da thread (com progresso):

1. `10%` — registra o feedback no banco
2. `35%` — lê o tail do `app.log`: últimas 3000 linhas, teto de 1 MB
3. `60%` — monta o corpo HTML (mensagem + apelido + versão + SO + data)
4. `75%` — `_outlook_send_mail(destino, assunto, corpo, [app-log.txt])`
5. `100%` — marca `status='sent'`, grava `sent_at`

Assunto: `🐇 Feedback do Toca — <apelido> — v<versão>`.

Destino resolvido por `_resolve_setting('feedback_admin_email',
'TOCA_FEEDBACK_EMAIL')`, com default `hfnetto@stefanini.com` semeado em
`init_db()`.

**Erro de Outlook não conectado** é tratado à parte: o feedback permanece
`pending` e a mensagem devolvida é acionável — "Conecte o Outlook em
Configurações → Microsoft 365 e envie novamente."

### Frontend

**Botão da topbar:** `#topbarFeedbackButton`, classe `.topbar-bell` (a mesma
pílula do sino, já resolvida nos cinco temas), ícone `fas fa-tools`,
imediatamente à esquerda de `#weekCommitmentsBell` em `index.html`.

**Modal `#feedbackModal`:** estático no `index.html`, com `.modal-content` e
`.modal-header` — herda a paleta do tema sem CSS novo. Contém:

- cabeçalho "Feedback" com o coelho da placa de sugestões à esquerda
- `#feedbackFormArea`: textarea de 6 linhas, contador de caracteres, aviso de
  que o log técnico acompanha o envio, botões Cancelar / Enviar
- `#feedbackProgressArea`: barra verde com `/images/coelho-correndo.webp` e a
  classe `.coelho-run`, no padrão do `openIAtaModal()`

**Asset:** `public/coelho-sugestoes.png` tem 868 KB e 1024 px. Uma versão
reduzida vai para `public/images/coelho-sugestoes.png` (~96 px) para não baixar
o arquivo inteiro num ícone de 48 px. O original permanece onde está.

---

## Descobertas durante a implementação

Três coisas apareceram na verificação contra o app rodando e mudaram o plano:

1. **`saveActivity` é substituído em tempo de execução.** O `itoca-autotoca.js`
   redefine a função inteira (`saveActivity = async function...`), e é essa
   versão que roda. O gancho do follow-up precisou ir nas duas, com a lógica
   compartilhada em `takePendingFollowup()` + `linkFollowupActivity()`. Detalhe
   que custa um bug silencioso: a flag tem que ser lida **antes** de
   `closeActivityModal()`, que a zera.

2. **`_graph_redirect_uri()` quebrava fora de request** (bug pré-existente).
   Usava `request.scheme`/`request.host` direto, então qualquer envio de e-mail
   disparado por thread — feedback, **briefing matinal**, revisão semanal —
   morria com "Working outside of request context". Passou a persistir o
   endereço observado em `app_settings.outlook_graph_redirect_uri` durante
   requests reais e a reusá-lo quando não há contexto.

3. **`formatDateBr` mostrava um dia a menos** (bug pré-existente). `new
   Date('2026-02-10')` é meia-noite UTC; em BRT (UTC-3) voltava para 09/02.
   A lista da agenda discordava do próprio calendário, e o texto pré-preenchido
   do follow-up gravaria a data errada no histórico do contato. Datas no
   formato `YYYY-MM-DD` passaram a ser formatadas sem `Date`.

## Testes

Ambas as partes são verificadas contra o app rodando localmente:

- migração aplica em banco existente sem perder dados e é idempotente
- `GET /api/agenda` devolve `followup_activity_id` para compromissos e `NULL`
  para eventos `acc-*`
- follow-up cria a atividade, vincula ao compromisso e faz o selo aparecer
  após o reload da agenda
- vínculo com atividade de outro contato é rejeitado com `400`
- `POST /api/feedback` devolve `202` e a tarefa chega a `done` ou a um `error`
  legível quando o Outlook não está conectado
- o anexo `app-log.txt` é gerado com o tail correto e respeita o teto de 1 MB
