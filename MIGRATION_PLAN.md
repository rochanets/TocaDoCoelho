# Plano de Migração — TocaDoCoelho Desktop → Web Multiusuário

> Documento de planejamento da migração da aplicação desktop mono-usuário para
> uma aplicação web multiusuário hospedada em servidor da empresa, com
> compartilhamento seletivo de dados e autenticação corporativa.

## Decisões de arquitetura (definidas)

1. **Desktop será aposentado.** A versão desktop deixa de ser a aplicação
   principal e passa a existir apenas como **"Toca Companion"** — um app local
   enxuto responsável somente pelas automações que precisam do **navegador do
   próprio usuário** (robô de formulários Playwright e afins). Todo o resto vira web.
2. **Gestão de código e testes 100% via GitHub** — mesmo repositório, branch de
   evolução, CI (GitHub Actions) rodando testes e migrations, PRs como unidade
   de entrega.
3. **Autenticação via SSO Microsoft (Azure AD / Entra ID)** — sem senhas
   próprias. Reaproveita o *app registration* já usado pelo Outlook Graph.

---

## 1. Diagnóstico da base atual

| Aspecto | Hoje | Ação |
|---|---|---|
| Autenticação | Nenhuma (sem `secret_key`, login ou sessão) | Construir SSO Microsoft |
| Multi-tenant | Nenhum; `user_profile` é singleton (`CHECK id=1`) | `users`/`orgs` + `owner_id` nas tabelas |
| Banco | SQLite arquivo único, acesso com `timeout` | Migrar para PostgreSQL |
| Servidor | `app.run(host='localhost')` (dev server) | Gunicorn + Nginx + TLS |
| Tarefas longas | dict `_tasks` em memória + `threading.Thread` | Store compartilhado (Redis/DB) |
| Uploads | Diretórios locais (`UPLOAD_DIR`...) | Object storage (S3/MinIO) |
| Empacotamento | `launcher.py`, `installer.nsi`, `pywin32`, bandeja | Vai para o Toca Companion |
| Robô Playwright | `integrations/forms_robot.py`, navegador visível | Vai para o Toca Companion |

### Trunfos já existentes na base (reaproveitáveis)

- **Framework de migrations versionadas**: `SCHEMA_MIGRATIONS` + tabela
  `schema_version` (`app.py`) — base para toda a evolução de schema.
- **OAuth Microsoft já implementado**: `integrations/outlook_graph.py`
  (`build_authorize_url`, `exchange_code_and_store`, refresh de token).
- **Tabela `user_integrations`** com chave `(user_id, provider)` — armazenamento
  de tokens **por usuário** já modelado (hoje com `user_id=1` fixo).
- **Rotas já modularizadas** em `routes/` (accounts, clients, campaigns, kanban,
  portfolio, wikitoca...) — facilita aplicar a camada de acesso de forma central.
- **Base de testes** em `BD_teste/` — ideal para dry-run da migração de dados.

---

## 2. Arquitetura alvo

```
┌─────────────────────────────┐         ┌──────────────────────────────┐
│   Navegador do usuário       │         │   Toca Companion (local)     │
│   (SPA: public/index.html)   │         │   - Playwright / forms_robot │
│   + tela de login SSO        │         │   - usa navegador do usuário │
└──────────────┬──────────────┘         │   - autentica na API via SSO │
               │ HTTPS                    └───────────────┬──────────────┘
               ▼                                          │ HTTPS (API + token)
┌─────────────────────────────────────────────────────────▼───────────────┐
│  Servidor da empresa                                                      │
│  Nginx (TLS) → Gunicorn (N workers) → Flask app                           │
│    - SSO Microsoft (Entra ID)  - camada de ACL/visibilidade               │
│    - Celery/RQ + Redis (tarefas longas)                                   │
│  PostgreSQL   │   Object storage (S3/MinIO)   │   Redis                   │
└───────────────────────────────────────────────────────────────────────────┘
```

O **Companion** não tem banco próprio nem lógica de negócio: recebe uma tarefa
da API web (ex.: "preencher este Forms"), executa no navegador do usuário e
reporta o resultado de volta para o servidor.

---

## 3. Modelo de dados multiusuário

### 3.1 Novas tabelas

```
organizations (id, name, entra_tenant_id, created_at)
users (id, org_id, entra_object_id UNIQUE, email, full_name, nickname,
       position, photo_url, role, created_at, updated_at)   -- substitui user_profile
memberships (id, user_id, org_id, role)                     -- se houver multi-org
shares (id, record_type, record_id, shared_with_user_id|team_id,
        permission, created_by, created_at)                 -- compartilhamento seletivo
teams (id, org_id, name)                                    -- opcional, para compartilhar por grupo
team_members (team_id, user_id)
```

### 3.2 Colunas de propriedade

Toda tabela de negócio ganha `owner_id` (FK `users.id`) e, quando aplicável,
`org_id`. Tabelas afetadas (não exaustivo): `clients`, `accounts`, `campaigns`,
`commitments`, `activities`, `kanban_columns`, `kanban_cards`, `wiki_entries`,
`wiki_documents`, `portfolio_offers`, `iata_records`, `environment_cards`, etc.

### 3.3 Camada de controle de acesso (crítica)

Um **ponto único** de aplicação de visibilidade — nenhuma rota consulta o banco
sem passar por ele:

```python
def visible_filter(user, record_type):
    # Retorna cláusula WHERE: dono OR compartilhado comigo OR do meu time OR (regra org)
    ...
def can_write(user, record_type, record_id) -> bool: ...
```

Regra padrão: **privado do dono**; visível a terceiros apenas via `shares`
explícito (compartilhamento seletivo) ou papel administrativo na org.

---

## 4. Autenticação — SSO Microsoft

- Reaproveitar o *app registration* do Azure AD já usado no Outlook Graph
  (mesmos `tenant`/`client_id`; adicionar scope `openid profile email User.Read`
  e o redirect URI da web).
- Fluxo OAuth Authorization Code (com PKCE) — a lógica de `authorize_url` /
  `exchange_code` de `outlook_graph.py` serve de base.
- No primeiro login, criar/atualizar a linha em `users` a partir do
  `entra_object_id` + claims (email, nome). O `user_profile` (id=1) atual é
  migrado para o usuário fundador.
- Sessão via cookie assinado (`app.secret_key`, `Secure`, `HttpOnly`,
  `SameSite`). Decorator `@login_required` populando `g.user` em toda request.
- **Companion** autentica com o mesmo SSO (device code flow ou token repassado),
  chamando a API web como o usuário.

---

## 5. Infraestrutura e concorrência

- **WSGI de produção**: Gunicorn (N workers) atrás de Nginx com TLS. Substitui
  `app.run(host='localhost')`.
- **Tarefas longas**: o `_tasks` em memória + `threading.Thread` **não sobrevive
  a múltiplos workers**. Migrar para Celery ou RQ com Redis (ou, no mínimo, um
  task store no Postgres). A barra de progresso do frontend continua igual — só
  muda a origem do estado da task.
- **Arquivos**: uploads locais → S3/MinIO, com chave escopada por `org_id/user_id`.
- **Segredos**: chaves de API (SAI, OpenRouter, Graph) saem do `app_settings`
  para variáveis de ambiente / secret manager; distinguir segredo **global do app**
  de credencial **por usuário** (esta fica em `user_integrations`).
- **Empacotamento em Docker**; migrations rodam automaticamente no deploy.

---

## 6. Migração de dados — SEM perda

Estratégia incremental, cada passo validável isoladamente.

### Fase A — Ainda em SQLite (aditivo e reversível)
1. Backup completo (usar o export `.db` existente).
2. Migration aditiva: criar `users`/`organizations`/`shares`; adicionar
   `owner_id`/`org_id` (nullable) nas tabelas de negócio.
3. **Backfill**: criar o usuário fundador a partir de `user_profile` e
   `UPDATE ... SET owner_id = <fundador>` em todas as linhas existentes.
4. Rodar a app e validar funcionamento com as colunas novas.

### Fase B — SQLite → PostgreSQL (ETL único)
5. Script tabela-a-tabela **preservando IDs**, tratando tipos (TIMESTAMP,
   boolean, sequences). Ferramenta: `pgloader` ou script Python.
6. Dry-run contra cópia (usar `BD_teste/`).
7. **Validação**: `COUNT(*)` origem vs. destino por tabela + spot-checks.
8. Manter SQLite como fallback read-only por um período.

### Fase C — Auth + ACL por cima
9. Ligar SSO, `@login_required`, camada de visibilidade e UI de compartilhamento,
   já com os dados íntegros no Postgres.

**Ordem inegociável:** dar dono aos dados (SQLite) → trocar engine (Postgres) →
ligar login/compartilhamento. Nenhum passo coloca os dados em risco.

---

## 7. Roadmap por fases (entregas via PR no GitHub)

| Fase | Entrega | Depende de |
|---|---|---|
| 0 | Setup CI (Actions: testes + lint + migrations em Postgres efêmero); Dockerfile; separar código desktop-only atrás de flag | — |
| 1 | Migration aditiva `users`/`orgs`/`shares` + `owner_id` + backfill (Fase A) | 0 |
| 2 | Camada de acesso ao banco (pool/abstração) e ETL SQLite→Postgres (Fase B) | 1 |
| 3 | SSO Microsoft + sessão + `@login_required` | 2 |
| 4 | Camada de ACL/visibilidade aplicada a todas as rotas de `routes/` | 3 |
| 5 | UI de login e de compartilhamento seletivo no SPA | 4 |
| 6 | Tarefas longas → Celery/RQ + Redis; uploads → object storage | 2 |
| 7 | Extrair **Toca Companion** (robô Playwright) + protocolo web↔companion | 3 |
| 8 | Deploy no servidor (Nginx/TLS), backups, monitoramento | 2–6 |

---

## 8. Estratégia de repositório e GitHub

- **Mesmo repositório** — não criar projeto novo, não clonar.
- Branch de evolução (`claude/app-online-migration-plan-spjcor` inicia esta
  linha; consolidar futuramente numa `v6-web` que vira `main`).
- Código **desktop-only** (`launcher.py`, `installer.nsi`, `pywin32`, bandeja,
  paths `C:/toca-do-coelho`) isolado atrás de flag/config e progressivamente
  movido para o pacote do Toca Companion.
- **GitHub Actions**: pipeline com testes (`tests/`), lint e execução das
  migrations contra um Postgres de serviço, exigido em todo PR.
- Cada fase do roadmap = um ou mais PRs revisáveis.

---

## 9. Riscos e pontos de atenção

- **Robô Playwright no servidor não funciona** como hoje (depende de navegador
  visível + perfil + registro do Windows). Por isso vira Companion local — decisão
  já tomada, mas o protocolo web↔companion precisa de desenho cuidadoso.
- **Concorrência de escrita** é o motivo real da troca para Postgres; subestimar
  isso reabre o problema de "database is locked".
- **Tokens por usuário**: Graph/Outlook/WhatsApp deixam de ser globais; revisar
  todo ponto que assume `user_id=1`.
- **Segurança**: com dados de múltiplos usuários, toda query sem filtro de
  visibilidade é um vazamento potencial — a camada de ACL é obrigatória, não opcional.

---

## 10. Próximo passo sugerido

Iniciar a **Fase 0/1**: pipeline mínimo de CI + a migration aditiva de
`users`/`owner_id` com backfill (ainda em SQLite, totalmente reversível), para
validar a fundação multiusuário sem risco aos dados atuais.
