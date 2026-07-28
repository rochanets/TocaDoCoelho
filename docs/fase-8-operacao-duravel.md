# F8.4 - migrations, backup/restore e observabilidade

## Contrato operacional

A produção separa inicialização do web e alteração de schema:

1. `postgres` fica saudável;
2. `migrate` executa `python manage.py migrate` uma única vez;
3. o comando aplica migrations sob advisory lock PostgreSQL, confirma a versão
   esperada e termina com sucesso;
4. somente então o Compose inicia os workers `web`.

`TOCA_RUN_MIGRATIONS_ON_STARTUP=0` é obrigatório no stack produtivo. Desktop e
testes SQLite preservam a inicialização automática, salvo override explícito.
O lock continua existindo como segunda proteção para execução simultânea
acidental do comando. O processo `migrate` recebe somente `DATABASE_URL` e a
chave estável necessária ao import do app; não recebe credenciais de WAHA,
Graph ou outros serviços.

Antes de publicar uma migration, use a sequência expand/contract:

- PR/deploy A adiciona tabelas ou colunas nullable e código compatível com os
  estados antigo e novo;
- backfill é idempotente, observável e não segura transação longa;
- PR/deploy B passa a depender do novo campo;
- constraints destrutivas ou remoção só entram depois de confirmar que nenhum
  binário anterior precisa do schema antigo.

Nunca faça rollback de código para uma versão incompatível com o schema já
promovido. Nesse caso, corrija para frente ou restaure todo o ambiente em um
novo banco durante uma janela de recuperação.

## Backup PostgreSQL

O serviço `postgres-backup` usa a mesma imagem major do banco e executa:

- `pg_dump --format=custom --no-owner --no-acl`;
- `pg_restore --list` antes de promover o arquivo;
- SHA-256 ao lado do dump;
- escrita temporária seguida de rename;
- retenção por `BACKUP_RETENTION_DAYS` (14 dias por padrão);
- repetição a cada `BACKUP_INTERVAL_HOURS` (24 horas por padrão).

Os arquivos ficam no volume `postgres_backups`, com `umask 077`. O marcador
`.last-success` alimenta o healthcheck. Um volume no mesmo host não é proteção
contra perda do host: replique dumps e checksums para armazenamento externo
criptografado, com acesso mínimo e política corporativa de retenção.

Verificação manual de um dump, sempre em banco descartável:

```bash
docker compose --env-file /caminho/seguro/toca.env \
  -f docker-compose.production.yml run --rm postgres-backup \
  sh /opt/toca/restore-verify.sh \
  /backups/tocadocoelho-AAAAMMDDTHHMMSSZ.dump \
  toca_restore_verificacao
```

O script recusa o nome do banco de origem, recusa sobrescrever banco existente,
verifica checksum/archive, restaura com `--exit-on-error`, consulta
`schema_version` e remove o banco descartável ao terminar. A CI executa o ciclo
backup -> checksum -> restore -> consulta -> descarte em PostgreSQL efêmero.

Para recuperação real, crie um PostgreSQL novo/vazio, restaure nele, valide
versão, contagens e amostras sem dados sensíveis nos logs, e só então altere
`DATABASE_URL` numa janela autorizada. Nunca restaure por cima do banco ativo.

O volume `waha_sessions` contém credenciais de pareamento e deve ser tratado
como segredo. Snapshot/backup exige janela autorizada, WAHA parado e
armazenamento criptografado. Não use `docker compose down -v`.

## Logs e correlação

Produção usa `TOCA_LOG_FORMAT=json` e stdout. Cada linha do app contém, quando
aplicável:

- timestamp UTC, nível, logger e mensagem;
- `request_id`, aceito de `X-Request-ID` somente em formato seguro ou gerado;
- evento, método, caminho sem query string, status e duração;
- ID numérico do usuário, nunca email, cookie ou token.

O mesmo `request_id` volta no header da resposta. Nginx propaga o ID recebido
ou gera um. O formatter mascara credenciais, cookies, códigos OAuth, tokens,
senhas e chaves encontrados em mensagens/exceções. `TOCA_LOG_FILE_ENABLED=0`
evita duplicar logs no volume do container; o desktop mantém arquivo local.

Não envie corpo de requisição, headers de autenticação, conteúdo de mensagens,
documentos ou respostas de integrações ao coletor. A retenção do coletor deve
seguir a política interna.

## Probes, painel e alertas mínimos

- `GET /healthz`: processo vivo, sem banco;
- `GET /readyz`: consulta real ao banco e confirmação da versão esperada do
  schema;
- `GET /api/admin/operations/status`: versão do app/schema, uptime, instância,
  estado WAHA, tarefas interrompidas e envios ambíguos, sem segredos;
- `GET /api/admin/jobs/status`: liderança, heartbeat e claims da F8.2;
- healthchecks nativos de PostgreSQL, web, WAHA, Nginx e backup.

Alertas mínimos recomendados:

| Sinal | Condição inicial |
|---|---|
| Disponibilidade | `/healthz` ou `/readyz` falha por 3 minutos |
| Erros | taxa HTTP 5xx acima de 2% por 5 minutos |
| Latência | p95 acima de 2 segundos por 10 minutos |
| Banco | conexão/readiness falha ou espaço livre abaixo de 20% |
| Backup | `postgres-backup` unhealthy ou último sucesso acima de 26 horas |
| Jobs | heartbeat atrasado, claim `running` vencida ou envio ambíguo |
| WAHA | sidecar indisponível por 5 minutos ou sessão desconectada |

Os limiares devem ser ajustados após observar a carga real; esta etapa não
escolhe fornecedor de métricas/logs.

## Runbooks

### Deploy

1. Fixar commit/tag da imagem e guardar a imagem anterior.
2. Confirmar backup verificado e espaço livre.
3. Validar Compose e ausência de placeholders/segredos versionados.
4. Construir/puxar a imagem uma única vez.
5. Executar `migrate`; parar se a versão não ficar atual.
6. Subir web/WAHA/Nginx e aguardar todos os healthchecks.
7. Executar smoke de SSO, Graph e WAHA apenas no ambiente autorizado.

### Rollback de código

1. Não desfazer migrations automaticamente.
2. Confirmar compatibilidade do binário anterior com o schema atual.
3. Promover a imagem anterior fixada.
4. Validar probes e fluxos críticos.
5. Se incompatível, corrigir para frente ou recuperar em banco novo.

### Banco indisponível

1. `/healthz` vivo com `/readyz` falhando confirma dependência indisponível.
2. Verificar health, conexões, espaço e logs do PostgreSQL pelo `request_id`.
3. Não repetir migrations nem reiniciar todos os serviços em loop.
4. Se necessário, restaurar o último dump verificado em banco novo.

### WAHA indisponível

O CRM continua operacional. Verifique `/health`, rede e volume; reinicie apenas
o sidecar. Não apague volume nem faça novo QR antes de confirmar que a sessão
persistida não pode ser recuperada.

### Jobs interrompidos ou envio ambíguo

Consulte os dois endpoints administrativos. Nunca apague claim para “tentar de
novo” sem confirmar no sistema externo se o efeito ocorreu. Envios ambíguos
exigem revisão humana; repetição é uma nova ação auditável.

### Vazamento de segredo

Revogue/rotacione o valor no provedor, atualize o secret store, reinicie somente
os consumidores e procure exposição em logs/histórico Git. Não registre o valor
comprometido no incidente.
