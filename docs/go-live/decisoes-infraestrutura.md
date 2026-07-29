# G2 — decisões de infraestrutura para o go-live

Status: **proposta técnica aguardando aprovações humanas**

Data: 29/07/2026

Base avaliada: `Live` em `58dcdd3` (G1 integrada)

Este documento não contém credenciais, IDs de tenant, emails, telefones,
domínios reais ou strings de conexão. Nenhum recurso externo foi criado.

## 1. Resumo executivo

A arquitetura recomendada preserva o stack já ensaiado na Fase 8:

- uma VM Linux x86-64 no Azure, na região Brazil South, executa Docker Compose,
  Nginx, web, WAHA e os volumes de arquivos/sessão;
- Azure Database for PostgreSQL Flexible Server 16 substitui o container
  PostgreSQL no ambiente online;
- PostgreSQL e armazenamento de backup usam acesso privado pela VNet;
- Azure Blob Storage recebe os dumps lógicos e checksums fora da VM;
- Azure Key Vault é a fonte autoritativa dos segredos;
- Azure Monitor, Log Analytics e Application Insights recebem métricas, logs,
  probes e alertas;
- Microsoft Entra e Graph continuam usando Authorization Code + PKCE, sem
  `client_secret` no Toca;
- apenas 80/443 ficam públicos; administração ocorre por caminho privado.

Essa escolha minimiza mudanças no runtime já testado e mantém host, banco,
backup, identidade e observabilidade no mesmo fornecedor. Ela não está aprovada
até o responsável confirmar orçamento, assinatura Azure, domínio, tenant,
telefone e donos operacionais.

## 2. Estado dos acessos

| Acesso/autoridade | Estado em 29/07/2026 | Necessário para |
|---|---|---|
| Repositório GitHub | disponível | documentação e futuras PRs |
| Assinatura/CLI Azure | não disponível ou não autenticada neste ambiente | cotação, G3 e recursos |
| Zona DNS/domínio | não informado | subdomínio candidato e domínio final |
| Administrador Entra | não informado | App Registration, consentimento e allowlist |
| Mailbox de teste | não informada | Graph/E2E |
| Telefone WAHA de teste | não informado | QR, envio e recebimento |
| Canal de alertas | não informado | Action Group e incidentes |
| Orçamento aprovado | não informado | contratação/provisionamento |

## 3. Hospedagem, região e rede

Decisão:
fornecedor, região, capacidade inicial, rede e acesso administrativo.

Opções consideradas:

1. Azure VM + serviços gerenciados Azure;
2. VPS de outro fornecedor + banco/backup de fornecedores separados;
3. host único com PostgreSQL autogerido.

Escolha:
**proposta — opção 1**, Azure em Brazil South. Usar VM Linux x86-64 de uso
geral com 4 vCPU e 16 GiB de RAM (família D, SKU exato condicionado à
disponibilidade e cota), disco de sistema de 64 GiB e disco de dados Premium
SSD de 128 GiB para `/data`, volumes Docker e staging de backups. Não usar ARM
na primeira implantação, pois todas as dependências atuais foram validadas em
x86-64.

Rede proposta:

- VNet dedicada ao candidato;
- subnet da VM separada da subnet delegada do PostgreSQL;
- PostgreSQL sem endpoint público;
- IP público estático somente no Nginx;
- NSG público permitindo apenas TCP 80/443;
- administração via Azure Bastion ou VPN, sem SSH público permanente;
- saída HTTPS permitida para Entra, Graph, WhatsApp, Azure Monitor, registro de
  imagens e dependências já autorizadas;
- atualização crítica/de segurança pelo Azure Update Manager, em janela
  controlada e com healthcheck após reboot.

Perfil de carga de partida:
até 25 usuários cadastrados, 10 simultâneos, dois workers Gunicorn e até
5 requisições por segundo sustentadas. Essa hipótese precisa ser substituída
pelos números reais antes do teste de capacidade.

Responsável:
**pendente — dono técnico e administrador da assinatura Azure**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [VMs Azure série D](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/d-family)
- [patching automático de VMs](https://learn.microsoft.com/en-us/azure/virtual-machines/automatic-vm-guest-patching)
- `docker-compose.production.yml`
- `docs/fase-8-runtime-producao.md`

Risco:
o WAHA usa Chromium e `shm_size: 1gb`; processamento de documentos e
transcrição também podem pressionar CPU/RAM. O tamanho inicial só pode ser
aceito após teste de carga e observação de CPU, memória, disco e p95.

Plano alternativo:
subir a VM para 8 vCPU/32 GiB sem mudar o desenho; se Azure não for aprovado,
usar VPS x86-64 com capacidade equivalente e manter banco/backup gerenciados,
desde que os mesmos gates de rede, TLS e restore sejam comprovados.

## 4. PostgreSQL

Decisão:
modelo, major, capacidade, TLS, rede, HA, manutenção e papéis.

Opções consideradas:

1. Azure Database for PostgreSQL Flexible Server;
2. PostgreSQL 16 em container na VM;
3. PostgreSQL gerenciado por outro fornecedor.

Escolha:
**proposta — opção 1**, PostgreSQL Flexible Server 16, acesso privado na mesma
VNet, TLS obrigatório com validação de certificado, armazenamento inicial de
64 GiB com crescimento automático e tier General Purpose de 2 vCore/8 GiB.

Para o candidato, HA fica desabilitada para reduzir custo. Para produção, a
proposta é habilitar HA com redundância de zona; se a região/SKU não tiver
capacidade, usar HA na mesma zona e registrar o risco. A manutenção deve ficar
fora da janela operacional aprovada.

Papéis separados:

- `toca_app`: conexão do runtime, sem criação de roles/schema;
- `toca_migrate`: dono dos objetos e executor de migrations;
- `toca_etl`: temporário, somente no ensaio/cutover e removido depois;
- administrador do servidor: somente para provisionamento e recuperação.

Revogar criação no schema `public` para `PUBLIC` e conceder somente os
privilégios necessários a cada papel.

Responsável:
**pendente — administrador de banco/assinatura**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [controle de acesso do Flexible Server](https://learn.microsoft.com/en-us/azure/postgresql/security/security-access-control)
- [rede privada do Flexible Server](https://learn.microsoft.com/en-us/azure/postgresql/network/concepts-networking-private)
- [TLS do Flexible Server](https://learn.microsoft.com/en-us/azure/postgresql/security/security-tls-how-to-connect)
- [opções de computação](https://learn.microsoft.com/pt-br/azure/postgresql/flexible-server/concepts-compute)
- a CI do Toca usa PostgreSQL 16.

Risco:
conexões da aplicação precisam usar `sslmode=verify-full` e a CA recomendada.
HA aproximadamente duplica a parcela de compute do banco e depende de cota e
capacidade regional.

Plano alternativo:
PostgreSQL 16 autogerido somente se custo impedir o serviço gerenciado, com
disco dedicado, TLS, monitoramento, backup externo, PITR equivalente e dono
operacional explícito. Não é a recomendação.

## 5. Estratégia de privilégio do ETL

Decisão:
como executar a carga SQLite → PostgreSQL sem depender de superuser.

Opções consideradas:

1. manter `SET session_replication_role='replica'`;
2. conceder `SET` específico ao papel temporário, se o fornecedor permitir;
3. adaptar o ETL para ordenar tabelas por dependências e manter FKs ativas.

Escolha:
**proposta — opção 3 antes da G5**. Não depender de superuser no ambiente
gerenciado. O schema atual possui 57 tabelas, 60 relações de FK e nenhum ciclo
no grafo gerado a partir das migrations de `Live`; portanto, uma ordenação
topológica é tecnicamente viável. O ETL adaptado deve:

- recusar destino não vazio;
- executar `TRUNCATE ... CASCADE` somente no banco descartável/autorizado;
- inserir tabelas em ordem de dependência, com FKs ativas;
- reajustar sequences;
- validar FKs, contagens e amostras antes de commit;
- rodar duas vezes em bancos descartáveis durante a G5;
- remover/revogar `toca_etl` após o uso.

O PostgreSQL permite alterar `session_replication_role` somente a superuser ou
a quem recebeu privilégio `SET`. O Azure não entrega superuser ao cliente; por
isso a opção 2 pode ser testada no candidato, mas não é o caminho principal.

Responsável:
**pendente — dono técnico da aplicação**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [PostgreSQL 16 — `session_replication_role`](https://www.postgresql.org/docs/16/runtime-config-client.html#GUC-SESSION-REPLICATION-ROLE)
- [restrição de superuser no Azure](https://learn.microsoft.com/en-us/azure/postgresql/security/security-access-control)
- `scripts/etl_sqlite_to_postgres.py`

Risco:
o ETL atual é bloqueante para Azure enquanto depender de superuser. A adaptação
é uma mudança de código e precisa de PR/testes próprios antes da G5.

Plano alternativo:
se o fornecedor comprovar e auditar `GRANT SET ON PARAMETER
session_replication_role TO toca_etl`, usar o papel somente em banco vazio,
revogá-lo imediatamente e ainda executar validação integral de FKs.

## 6. Backup externo e recuperação

Decisão:
destino, criptografia, retenção, RPO/RTO, alerta e restore.

Opções consideradas:

1. somente backup gerenciado do PostgreSQL;
2. PITR gerenciado + dumps lógicos em Azure Blob Storage;
3. volume de backup somente na VM.

Escolha:
**proposta — opção 2**.

- PITR do PostgreSQL: retenção de 14 dias;
- dumps `pg_dump` + SHA-256: a cada 24 horas;
- destino: container privado em Storage Account separado da VM;
- redundância proposta: GRS para produção e LRS/ZRS para candidato;
- retenção lógica: 35 backups diários; retenção mensal/longa depende de
  política corporativa ainda não informada;
- soft delete/versionamento habilitados;
- lifecycle policy para expiração;
- credencial de mínimo acesso via identidade gerenciada;
- alerta quando o último dump externo tiver mais de 26 horas;
- restore lógico em banco descartável mensal e antes de cada go-live.

Objetivos propostos:

- RPO operacional: 15 minutos usando PITR;
- RPO do backup externo independente: 24 horas;
- RTO: 4 horas para restaurar, reconciliar e redirecionar a aplicação.

Responsável:
**pendente — dono técnico e responsável por continuidade**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [backup/PITR do Flexible Server](https://learn.microsoft.com/en-us/azure/postgresql/backup-restore/concepts-backup-restore)
- [lifecycle do Azure Blob Storage](https://learn.microsoft.com/en-us/azure/storage/blobs/lifecycle-management-overview)
- `deploy/postgres/backup-once.sh`
- `deploy/postgres/restore-verify.sh`

Risco:
o repositório hoje só grava dumps no volume `postgres_backups`; a cópia para
Blob e seu alerta ainda precisam ser implementados/provados na G3. Backups
gerenciados não são exportáveis, então não substituem o dump lógico externo.

Plano alternativo:
storage S3 compatível em conta/fornecedor separado, com criptografia,
versionamento, lifecycle e restore comprovado.

## 7. DNS, TLS e segredos

Decisão:
subdomínios, certificado, renovação e secret store.

Opções consideradas:

1. manter o provedor DNS atual e usar Let's Encrypt/Certbot no Nginx;
2. mover a zona para Azure DNS;
3. usar proxy/CDN gerenciado na borda.

Escolha:
**proposta — opção 1**. Não mover a zona DNS nesta migração.

- candidato: `toca-candidato.<dominio-a-confirmar>`;
- produção: `toca.<dominio-a-confirmar>`;
- certificado Let's Encrypt separado para o candidato;
- renovação automática por timer e alerta de expiração;
- Azure Key Vault como fonte dos segredos;
- identidade gerenciada da VM com RBAC mínimo;
- materialização do arquivo de ambiente fora do checkout, com permissão `0600`;
- certificados montados no Nginx por caminho fora do Git.

Responsável:
**pendente — dono do domínio/DNS e administrador Azure**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [Key Vault para VM Linux](https://learn.microsoft.com/en-us/azure/virtual-machines/extensions/key-vault-linux)
- `.env.production.example`
- `deploy/nginx/toca.conf`

Risco:
o domínio e seu provedor não foram informados. Sem acesso DNS não há G3.

Plano alternativo:
Azure DNS se o responsável decidir delegar a zona; certificado gerenciado por
um proxy de borda somente após validar cookies, redirects Entra e `ProxyFix`.

## 8. Microsoft Entra e Outlook Graph

Decisão:
tenant, App Registration, redirects, consentimento, allowlist e contas de
teste.

Opções consideradas:

1. App Registration de produção dedicado;
2. reutilizar o registro de desenvolvimento;
3. alterar para confidential client.

Escolha:
**proposta — opção 1**. App Registration de produção single-tenant,
Authorization Code + PKCE, sem `client_secret` no Toca, com redirects exatos:

- `https://toca-candidato.<dominio>/api/auth/callback`;
- `https://toca-candidato.<dominio>/api/outlook/oauth/callback`;
- redirects equivalentes do domínio final somente quando a G7 autorizar.

Permissões delegadas:
`openid profile email offline_access User.Read Mail.Read Mail.Send`.

Allowlist inicial:
administrador, usuário comum proprietário, usuário comum isolado e identidade
negada, todos de teste/autorizados. Mailbox de teste deve poder ler e enviar
uma mensagem controlada.

Responsável:
**pendente — administrador do tenant e aprovador de consentimento**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [configurar redirect URI no Entra](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri)
- `docs/fase-8-runtime-producao.md`

Risco:
tenant, administrador, política de consentimento, mailbox e usuários de teste
não foram informados.

Plano alternativo:
confidential client/certificado somente se a política do tenant exigir; isso
demanda decisão e implementação separadas antes da G3.

## 9. WAHA

Decisão:
número de teste, QR, persistência, backup, recuperação e limites.

Opções consideradas:

1. sessão/número dedicado de teste;
2. usar número real já operacional;
3. validar apenas com mocks.

Escolha:
**proposta — opção 1** na G3–G6.

- telefone e responsável dedicados ao teste;
- janela de QR de 30 minutos com responsável disponível;
- volume `waha_sessions` no disco de dados criptografado da VM;
- porta privada e Dashboard/Swagger desligados;
- snapshot frio semanal do volume, com WAHA parado e acesso restrito;
- perda da sessão: tentar restore; novo QR somente com autorização;
- limite candidato: 5 envios/dia;
- limite produtivo inicial: 45 envios/dia, sujeito à política interna e ao
  consentimento dos destinatários;
- nenhuma mensagem em massa no candidato.

Responsável:
**pendente — custodiante do telefone e dono operacional**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `docs/fase-8-waha-sidecar.md`
- `docker-compose.production.yml`

Risco:
telefone, custodiante e janela de QR não foram informados. Snapshot de sessão
contém credenciais de pareamento e deve ser tratado como segredo.

Plano alternativo:
refazer QR com o mesmo número de teste. Não usar mocks como prova da G6.

## 10. Observabilidade e alertas

Decisão:
coletor, métricas, probes, retenção, alertas e canal.

Opções consideradas:

1. Azure Monitor + Log Analytics + Application Insights;
2. stack Prometheus/Loki/Grafana autogerida;
3. serviço externo de uptime/logs.

Escolha:
**proposta — opção 1**.

- VM Insights para CPU, memória, disco e rede;
- métricas nativas do Flexible Server;
- Azure Monitor Agent e DCR para coletar JSON do Docker, com transformação que
  preserve `request_id` e descarte payloads não permitidos;
- retenção inicial de logs: 30 dias;
- Application Insights Availability Tests externos em `/healthz` e `/readyz`;
- Action Group com email e um segundo canal a confirmar;
- teste de alerta obrigatório antes do aceite da G3.

Limiares iniciais:

- probes falhando por 3 minutos;
- HTTP 5xx acima de 2% por 5 minutos;
- p95 acima de 2 segundos por 10 minutos;
- disco livre abaixo de 20%;
- backup externo acima de 26 horas;
- heartbeat/claim vencido;
- WAHA indisponível por 5 minutos.

Responsável:
**pendente — plantonista/dono operacional e destinatários do Action Group**.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [VM Insights](https://learn.microsoft.com/en-us/azure/azure-monitor/vm/vminsights-performance)
- [coleta de JSON de VM](https://learn.microsoft.com/en-us/azure/azure-monitor/vm/data-collection-log-json)
- [Availability Tests](https://learn.microsoft.com/en-us/azure/azure-monitor/app/availability)
- [Action Groups](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups)
- `docs/fase-8-operacao-duravel.md`

Risco:
logs de container precisam de DCR/transformação testada; não enviar bodies,
headers de autenticação, mensagens ou documentos. O canal de alerta ainda não
foi definido.

Plano alternativo:
serviço externo de uptime mais coletor gerenciado de logs, mantendo os mesmos
limites, redaction e retenção.

## 11. Operação, SLO e cutover

Decisão:
donos, janela, soak, indisponibilidade, hypercare e critérios de no-go.

Escolha:
proposta operacional:

- disponibilidade mensal alvo: 99,5% no primeiro mês;
- p95 alvo: abaixo de 2 segundos;
- taxa de 5xx: abaixo de 2%;
- soak do candidato: 72 horas;
- indisponibilidade máxima do cutover: 2 horas;
- RTO: 4 horas; RPO: 15 minutos;
- hypercare: 5 dias úteis;
- desktop é fonte autoritativa até o congelamento formal da G8;
- após copiar fontes, calcular checksums e iniciar o ETL final, não reabrir
  escritas no desktop sem decisão de rollback;
- ponto de não retorno: validação final dos dados e mudança do domínio/DNS;
- rollback antes desse ponto volta ao desktop congelado;
- depois desse ponto, qualquer divergência exige congelar os dois lados e
  decidir a fonte autoritativa antes de escrever.

Critérios de no-go:
qualquer P0/P1, falha de restore/rollback, divergência de dados, ACL incorreta,
duplicação de efeito externo, SSO/Graph/WAHA indisponível, alerta sem dono ou
desktop/updater não protegido.

Responsáveis:

- dono técnico: **pendente**;
- aprovador do go-live: **pendente**;
- administrador Azure/PostgreSQL: **pendente**;
- administrador Entra: **pendente**;
- custodiante WAHA: **pendente**;
- plantonista/hypercare: **pendente**.

Janela:
**pendente — data, horário e timezone America/Sao_Paulo**.

Canal de incidente:
**pendente**.

Evidência/contrato:
`docs/plano-acao-pos-fase-8-go-live.md`.

Risco:
sem nomes, janela e canal, alertas e rollback não têm executor.

Plano alternativo:
adiar G3 até os responsáveis aceitarem explicitamente seus papéis.

## 12. Orçamento e aprovação

O orçamento não foi aprovado nesta execução. A cotação deve incluir:

- VM 4 vCPU/16 GiB, discos, IP e tráfego;
- Bastion ou VPN;
- Flexible Server 2 vCore/8 GiB, 64 GiB, backup e HA;
- Storage Account/Blob e operações;
- Key Vault;
- Log Analytics, Application Insights e alertas;
- DNS, se migrado;
- margem de 30% para logs, crescimento e restore temporário.

Usar a [Calculadora de Preços do Azure](https://azure.microsoft.com/pricing/calculator/)
na assinatura e moeda aprovadas. Guardar a URL/estimativa sem dados financeiros
sensíveis no PR ou sistema de compras.

Teto mensal:
**pendente**.

Aprovador de custo:
**pendente**.

## 13. Aprovações necessárias para concluir a G2

- [ ] confirmar Azure e Brazil South;
- [ ] confirmar teto mensal e aprovador de custo;
- [ ] confirmar domínio e os dois subdomínios;
- [ ] confirmar tenant, administrador Entra e mailbox de teste;
- [ ] confirmar número/custodiante WAHA;
- [ ] confirmar os seis responsáveis operacionais;
- [ ] confirmar janela, canal de incidente e canal de alertas;
- [ ] confirmar carga esperada ou substituir a hipótese 25/10;
- [ ] aprovar RPO 15 min, RTO 4 h, soak 72 h, downtime 2 h e hypercare 5 dias;
- [ ] aprovar HA no PostgreSQL produtivo;
- [ ] aprovar adaptação do ETL antes da G5;
- [ ] anexar cotação aprovada.

Enquanto algum item permanecer aberto, a G2 está **parcial** e a G3 não está
liberada.
