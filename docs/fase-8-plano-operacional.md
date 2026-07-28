# Fase 8 - plano operacional de produção

## Escopo e sequência

A Fase 8 preserva o TocaDoCoelho como CRM interno `single-org`. Multi-org,
SaaS, billing e onboarding continuam fora do escopo (Fase 9, dependente de
decisão de produto).

O inventário da `Live` incorporando a F7.5 (`5581f95`) definiu **cinco
subetapas**, executadas em ordem:

| Etapa | Entrega | Critério de saída |
|---|---|---|
| F8.1 | Runtime e configuração segura de produção | Caminho versionado para PostgreSQL + Gunicorn + Nginx/TLS; produção falha fechada sem banco, SSO, cookie e chave corretos; liveness/readiness separados; nenhum segredo real em exemplos |
| F8.2 | Jobs multi-worker e liderança | Escolha técnica documentada; jobs periódicos executam uma única vez com N workers; estados importantes são persistentes; concorrência, idempotência e recuperação após reinício testadas |
| F8.3 | WAHA sidecar e persistência | Um único sidecar suportado, sem porta pública desnecessária; API protegida, sessão persistida, healthcheck e webhook interno validados |
| F8.4 | Migrations, backup/restore e observabilidade | Migration de deploy serializada; backup PostgreSQL automatizado; restore descartável comprovado; logs estruturados, correlação e endpoints operacionais documentados |
| F8.5 | Ensaio, rollback e fechamento | Build e smoke do stack; N workers; SSO/Graph e WAHA validados no ambiente autorizado; deploy/rollback ensaiados; checklist de prontidão assinado |

Não haverá avanço automático para a Fase 9.

## Inventário real da base

### Runtime, banco e autenticação

- `Dockerfile` já executava Gunicorn como usuário não-root e possuía
  `/healthz`, mas `docker-compose.web.yml` era um smoke local de um worker com
  SQLite.
- `gunicorn.conf.py` já expunha concorrência e timeouts por ambiente, porém o
  próprio comentário reconhecia duplicação de jobs com mais de um worker.
- `DATABASE_URL` já seleciona PostgreSQL; o wrapper `psycopg` + `sqlglot`
  mantém as rotas compatíveis com SQLite, e a CI já exercita migrations, ETL,
  ACL e rotas contra PostgreSQL 16.
- As migrations são incrementais e registradas em `schema_version`, mas rodam
  durante o import de `app.py`. Com mais de um processo isso ainda precisa de
  serialização/etapa dedicada (F8.4).
- SSO Microsoft usa Authorization Code + PKCE como cliente público. Login e
  Outlook Graph usam redirects distintos; tokens de mailbox são por usuário e
  protegidos por DPAPI/Fernet. Não existe `client_secret` no fluxo atual.
- O desktop continua sem login quando `TOCA_AUTH_ENABLED=0`, com SQLite e
  chave de sessão local. Antes da F8.1, a produção também podia cair nesse
  fallback por configuração incompleta.

### Jobs e estado entre workers

Foram encontrados os seguintes executores iniciados por processo:

- agendador de 30 minutos com briefing matinal, gatilhos de contexto e revisão
  semanal;
- poller de inbound/WAHA com intervalo configurável;
- worker de envios agendados com tick de um minuto;
- diversas threads iniciadas por requisição para IA, documentos, campanhas,
  Outlook, WhatsApp e pesquisa.

`background_tasks` espelha parte do progresso no banco, e o contrato do
Companion já é persistente, idempotente e baseado em lease. Entretanto,
`_portfolio_tasks`, `_iata_tasks`, `_outlook_confirm_tasks` e
`_forms_robot_tasks` ainda usam dicionários locais. Isso impede habilitar
`WEB_CONCURRENCY>1` antes da F8.2.

Alternativas a avaliar formalmente na F8.2:

| Alternativa | Pontos fortes | Limitações neste produto |
|---|---|---|
| PostgreSQL advisory locks + tabelas persistentes | Reutiliza a infraestrutura obrigatória; menor custo operacional; bom para eleição de líder e ticks curtos | Não é uma fila completa; tarefas longas exigem modelagem de claim/lease/retry |
| Redis + RQ | Fila simples, workers separados e progresso compartilhado | Introduz serviço, backup/monitoramento e custo operacional adicionais |
| Redis + Celery | Recursos maduros de agenda, retry e roteamento | Maior complexidade para o tamanho atual e também exige Redis/broker |

A decisão será tomada por adequação ao inventário, testes de falha/reinício e
custo operacional, sem antecipá-la na F8.1.

### WAHA

- Há dois arquivos Compose legados com topologias diferentes e um `WAHA-lite`
  iniciado/reiniciado pelo runtime desktop.
- Uma variante expõe a porta 3000; outra expõe 3001 e continha chave de teste
  versionada. A sessão usa volume/host path, mas não há um stack produtivo
  único com rede privada e healthcheck integrado.
- O web já lê URL, API key e nome da sessão, envia mensagens, recebe webhook e
  faz polling. A consolidação como sidecar pertence à F8.3.

### Operação e observabilidade

- O backup automático atual é orientado ao arquivo SQLite; não cobre
  PostgreSQL.
- `/healthz` era apenas liveness. Não havia readiness do banco.
- Logs vão para stdout e `TOCA_DATA_DIR/logs/app.log`, em texto, sem ID de
  correlação estruturado.
- A CI possui suíte geral, smoke da imagem web e testes PostgreSQL, mas ainda
  não ensaia o stack produtivo, restore, concorrência de jobs ou rollback.

## Matriz de execução F8.x

### F8.1 - runtime e configuração segura

- adicionar stack de referência com PostgreSQL, web e Nginx/TLS;
- não publicar PostgreSQL nem o web diretamente;
- exigir `SECRET_KEY`, PostgreSQL, SSO, cookies Secure e proxy confiável no
  modo de produção explícito;
- preservar o fallback desktop/local fora do modo de produção;
- adicionar `/readyz` com consulta real ao banco;
- documentar os dois redirect URIs do Entra e o modelo público PKCE;
- remover credenciais default versionadas e proteger `.env`, certificados e
  sessões locais;
- manter um worker por guarda explícita até a F8.2.

### F8.2 - jobs multi-worker e liderança

Implementada em `docs/fase-8-jobs-multiworker.md` com PostgreSQL advisory
locks, claims duráveis, task store compartilhado e recuperação fail-safe de
envios. Redis/RQ e Celery permanecem alternativas condicionais, não
dependências atuais.

### F8.3 - WAHA sidecar

Implementada em `docs/fase-8-waha-sidecar.md`: os Compose legados foram
consolidados no stack produtivo, com imagem fixada, API privada protegida por
chave, webhook HMAC, volume de sessão, healthcheck e política de restart. O CI
valida rede web -> WAHA, webhook assinado e persistência do volume sem conectar
uma conta real.

### F8.4 - operação durável

- retirar migrations concorrentes do import ou serializá-las com lock
  PostgreSQL e comando de deploy;
- adicionar backup `pg_dump`, retenção, verificação e restore descartável;
- definir ordem de deploy e compatibilidade progressiva das migrations;
- adicionar logs JSON, `request_id`/correlação e proteção de dados sensíveis;
- definir métricas/alertas mínimos e runbooks de deploy, rollback, incidente,
  indisponibilidade de dependência e recuperação.

### F8.5 - ensaio e prontidão

- construir imagens a partir do commit entregue;
- subir stack descartável com TLS e PostgreSQL;
- executar migrations, smoke, suíte PostgreSQL e teste multi-worker;
- validar SSO, logout, renovação de sessão, Outlook Graph e WAHA somente no
  ambiente autorizado;
- executar backup/restore e rollback documentados;
- verificar ausência de segredos e fechar o checklist de produção.

DNS, certificado público, host, fornecedor de PostgreSQL e qualquer alteração
no Entra ou em serviços externos exigem acesso/autorização explícitos e não são
executados por este plano local.
