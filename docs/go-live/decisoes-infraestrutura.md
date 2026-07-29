# G2 — decisões de infraestrutura para o go-live

Status: **decisões parcialmente aprovadas; pendências corporativas registradas**

Data: 29/07/2026

Base avaliada: `Live` em `58dcdd3` (G1 integrada)

Este documento não contém credenciais, IDs de tenant, números de telefone ou
strings de conexão. O domínio e o email operacional aqui registrados são dados
corporativos fornecidos pelo responsável. Nenhum recurso externo foi criado.

## 1. Resumo executivo

A arquitetura recomendada preserva o stack já ensaiado na Fase 8:

- o servidor Linux corporativo `soalv3tcd01` (`10.161.75.33`) executa Docker
  Compose, Nginx, web, WAHA e os volumes de arquivos/sessão;
- a borda corporativa publica HTTPS pelo IP `69.41.39.34`, via WAF/proxy/NAT a
  ser confirmado por Redes e Segurança;
- o usuário acessa somente uma URL HTTPS; a porta 3000 do Gunicorn permanece
  exclusiva da rede Docker;
- PostgreSQL 16 usa rede privada. A preferência é serviço corporativo
  gerenciado com HA; se ele não existir, o fallback é PostgreSQL autogerido,
  sem alegação de HA, acompanhado de backup externo e recuperação comprovada;
- backups são copiados para armazenamento corporativo fora do host;
- segredos e observabilidade usam os serviços corporativos disponíveis, ainda
  a confirmar;
- Microsoft Entra e Graph continuam usando Authorization Code + PKCE, sem
  `client_secret` no Toca;
- apenas HTTPS fica disponível ao usuário; administração ocorre por VPN/SSH.

Azure/Brazil South não será usado para hospedar a aplicação. A proposta Azure
anterior existia porque ainda não havia informação sobre o servidor
corporativo. O uso do Microsoft Entra para identidade não obriga que a
aplicação seja hospedada no Azure.

## 2. Estado dos acessos

| Acesso/autoridade | Estado em 29/07/2026 | Necessário para |
|---|---|---|
| Repositório GitHub | disponível | documentação e futuras PRs |
| Servidor corporativo | disponível; preparação em conversa separada | runtime candidato |
| VPN/SSH | disponível segundo o responsável | administração privada do host |
| Portal Azure | acesso informado; não será usado para hospedagem | Entra/App Registration, se aplicável |
| Zona DNS/domínio | acesso/canal informado; publicação em andamento | candidato e domínio final |
| Administrador Entra | acesso administrativo informado; identidade do executor a confirmar | App Registration, consentimento e allowlist |
| Mailbox de teste | disponível; identificador não registrado no Git | Graph/E2E |
| Telefone WAHA de teste | disponível; número não registrado no Git | QR, envio e recebimento |
| Canal de alertas | `hfnetto@stefanini.com` | alertas e incidentes |
| Orçamento Azure | não aplicável à hospedagem | custos incrementais corporativos a confirmar |

## 3. Hospedagem, região e rede

Decisão:
fornecedor, região, capacidade inicial, rede e acesso administrativo.

Opções consideradas:

1. servidor Linux corporativo;
2. Azure VM + serviços gerenciados Azure;
3. VPS de outro fornecedor.

Escolha aprovada:
**opção 1**, servidor corporativo `soalv3tcd01`, IP privado `10.161.75.33`.
Arquitetura, CPU, memória e discos ainda serão inventariados antes da G3. A
primeira implantação deve usar x86-64, pois as dependências atuais foram
validadas nessa arquitetura.

Rede proposta:

- administração por VPN/SSH, sem SSH público;
- PostgreSQL sem endpoint público;
- IP público `69.41.39.34` terminado/encaminhado pela borda corporativa;
- entrada pública somente HTTPS/TCP 443; eventual TCP 80 apenas para
  redirecionamento ou validação de certificado, se Segurança aprovar;
- porta 3000 somente na rede Docker, sem publicação no host;
- saída HTTPS permitida para Entra, Graph, WhatsApp, monitoramento, registro de
  imagens e dependências já autorizadas;
- atualização crítica/de segurança pelo mecanismo corporativo, em janela
  controlada e com healthcheck após reboot.

Perfil de carga informado:
15 usuários cadastrados e até 6 simultâneos. Dois workers Gunicorn são o ponto
de partida, sujeitos a teste de carga e observação de CPU, memória, disco e p95.

Responsável:
Henrique Netto — dono técnico e responsável pelo servidor/aplicação.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `docker-compose.production.yml`
- `docs/fase-8-runtime-producao.md`

Risco:
o WAHA usa Chromium e `shm_size: 1gb`; processamento de documentos e
transcrição também podem pressionar CPU/RAM. O tamanho inicial só pode ser
aceito após teste de carga e observação de CPU, memória, disco e p95.

Plano alternativo:
solicitar expansão de CPU/RAM/disco ou outro host corporativo se o inventário e
o teste de capacidade não atenderem aos gates.

## 4. PostgreSQL

Decisão:
modelo, major, capacidade, TLS, rede, HA, manutenção e papéis.

Opções consideradas:

1. PostgreSQL 16 corporativo gerenciado, com HA;
2. PostgreSQL 16 autogerido em host/nó separado, com réplica e failover;
3. PostgreSQL 16 no mesmo servidor da aplicação.

Escolha:
**preferência aprovada — opção 1**, caso a empresa ofereça o serviço. Henrique
Netto confirmará com Infraestrutura/DBA a disponibilidade, endpoint privado,
capacidade, TLS, manutenção, backups e failover. A opção 2 é aceitável se
operada pela infraestrutura corporativa.

A opção 3 pode atender à carga de 15/6, mas é fallback e **não constitui HA**:
uma falha do host derruba simultaneamente aplicação e banco. Se for a única
opção corporativa disponível, o risco precisa ser aceito explicitamente antes
da produção, com recuperação externa capaz de cumprir RPO/RTO. A manutenção
deve ficar fora da janela operacional.

Papéis separados:

- `toca_app`: conexão do runtime, sem criação de roles/schema;
- `toca_migrate`: dono dos objetos e executor de migrations;
- `toca_etl`: temporário, somente no ensaio/cutover e removido depois;
- administrador do servidor: somente para provisionamento e recuperação.

Revogar criação no schema `public` para `PUBLIC` e conceder somente os
privilégios necessários a cada papel.

Responsável:
Henrique Netto — responsável técnico/PostgreSQL e coordenador com
Infraestrutura/DBA.

Data:
29/07/2026, proposta.

Evidência/contrato:

- a CI do Toca usa PostgreSQL 16.

Risco:
HA exige pelo menos outro nó/domínio de falha ou um serviço gerenciado; ela não
pode ser obtida apenas configurando o PostgreSQL no mesmo servidor. O endpoint
de banco deve permanecer privado e o TLS deve seguir a política corporativa.

Plano alternativo:
PostgreSQL 16 autogerido no host, com disco adequado, monitoramento, backup
externo, arquivamento contínuo de WAL/PITR e restore comprovado. Essa opção
prioriza recuperação, não disponibilidade, e requer aceite formal do risco.

## 5. Estratégia de privilégio do ETL

Decisão:
como executar a carga SQLite → PostgreSQL sem depender de superuser.

Opções consideradas:

1. manter `SET session_replication_role='replica'`;
2. conceder `SET` específico ao papel temporário, se o fornecedor permitir;
3. adaptar o ETL para ordenar tabelas por dependências e manter FKs ativas.

Escolha aprovada:
**opção 3 antes da G5**. Não depender de superuser nem de desativação global de
integridade referencial. O schema atual possui 57 tabelas, 60 relações de FK e
nenhum ciclo no grafo gerado a partir das migrations de `Live`; portanto, uma
ordenação topológica é tecnicamente viável. O ETL adaptado deve:

- recusar destino não vazio;
- executar `TRUNCATE ... CASCADE` somente no banco descartável/autorizado;
- inserir tabelas em ordem de dependência, com FKs ativas;
- reajustar sequences;
- validar FKs, contagens e amostras antes de commit;
- rodar duas vezes em bancos descartáveis durante a G5;
- remover/revogar `toca_etl` após o uso.

O PostgreSQL permite alterar `session_replication_role` somente a superuser ou
a quem recebeu privilégio `SET`. Mesmo em banco autogerido, reduzir esse
privilégio torna o processo mais seguro e portátil.

Responsável:
Henrique Netto — dono técnico da aplicação.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [PostgreSQL 16 — `session_replication_role`](https://www.postgresql.org/docs/16/runtime-config-client.html#GUC-SESSION-REPLICATION-ROLE)
- `scripts/etl_sqlite_to_postgres.py`

Risco:
o ETL atual depende de privilégio elevado e desativa controles de integridade.
A adaptação é uma mudança de código e precisa de PR/testes próprios antes da G5.

Plano alternativo:
se o fornecedor comprovar e auditar `GRANT SET ON PARAMETER
session_replication_role TO toca_etl`, usar o papel somente em banco vazio,
revogá-lo imediatamente e ainda executar validação integral de FKs.

## 6. Backup externo e recuperação

Decisão:
destino, criptografia, retenção, RPO/RTO, alerta e restore.

Opções consideradas:

1. PITR do serviço PostgreSQL corporativo + dumps lógicos externos;
2. arquivamento contínuo de WAL/PITR autogerido + dumps lógicos externos;
3. volume de backup somente no mesmo host.

Escolha aprovada:
**opção 1 se houver PostgreSQL corporativo gerenciado; caso contrário, opção
2**. A opção 3 isolada é proibida para produção.

- PITR/arquivamento de WAL: retenção mínima de 14 dias;
- dumps `pg_dump` + SHA-256: a cada 24 horas;
- destino: armazenamento corporativo criptografado e separado do servidor;
- retenção lógica: 35 backups diários; retenção mensal/longa depende de
  política corporativa ainda não informada;
- imutabilidade, versionamento ou proteção contra exclusão, se disponível;
- expiração automatizada conforme retenção;
- credencial de mínimo acesso;
- envio/arquivamento de WAL monitorado para limitar a perda a 15 minutos;
- alerta quando o último dump externo tiver mais de 26 horas;
- restore lógico em banco descartável mensal e antes de cada go-live.

Objetivos propostos:

- RPO operacional aprovado: 15 minutos usando PITR/WAL;
- RPO do backup externo independente: 24 horas;
- RTO aprovado: 4 horas para restaurar, reconciliar e redirecionar a aplicação.

Responsável:
Henrique Netto — dono técnico e responsável por continuidade.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `deploy/postgres/backup-once.sh`
- `deploy/postgres/restore-verify.sh`

Risco:
o repositório hoje só grava dumps no volume `postgres_backups`, que pode estar
no mesmo host. O destino corporativo externo, o arquivamento de WAL e seus
alertas ainda precisam ser definidos e provados na G3. Snapshot do host não
substitui backup de banco e teste de restore.

Plano alternativo:
storage S3 compatível ou compartilhamento corporativo protegido, com
criptografia, versionamento/imutabilidade, retenção e restore comprovado.

## 7. DNS, TLS e segredos

Decisão:
subdomínios, certificado, renovação e secret store.

Opções consideradas:

1. publicação pela borda/WAF corporativa e DNS existente;
2. certificado público diretamente no Nginx;
3. migração da zona para outro provedor.

Escolha aprovada:
**opção 1**. Não mover a zona DNS nesta migração.

- candidato recomendado: `toca-candidato.stefanini.com`;
- produção confirmada: `toca.stefanini.com`;
- IP público informado: `69.41.39.34`;
- certificado publicamente confiável, preferencialmente gerenciado na borda
  corporativa, com renovação e alerta de expiração;
- fonte corporativa de segredos a confirmar;
- materialização do arquivo de ambiente fora do checkout, com permissão `0600`;
- certificados montados no Nginx por caminho fora do Git.

Responsável:
Henrique Netto — coordenador técnico; execução da publicação pela equipe
corporativa de Redes/Segurança.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `.env.production.example`
- `deploy/nginx/toca.conf`

Risco:
o nome candidato ainda precisa ser confirmado e o chamado corporativo precisa
confirmar TLS, WAF/proxy, healthcheck e o backend. A porta 3000 não deve ser
exposta.

Plano alternativo:
certificado público no Nginx somente se a arquitetura corporativa exigir,
mantendo cookies, redirects Entra e `ProxyFix` validados.

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

- `https://toca-candidato.stefanini.com/api/auth/callback`;
- `https://toca-candidato.stefanini.com/api/outlook/oauth/callback`;
- redirects equivalentes em `https://toca.stefanini.com` somente quando a G7
  autorizar.

Permissões delegadas:
`openid profile email offline_access User.Read Mail.Read Mail.Send`.

Allowlist inicial:
administrador, usuário comum proprietário, usuário comum isolado e identidade
negada, todos de teste/autorizados. Mailbox de teste deve poder ler e enviar
uma mensagem controlada.

Responsável:
**pendente de nome** — pessoa/equipe com permissão administrativa no Microsoft
Entra para criar/alterar o App Registration, cadastrar redirects, revisar
permissões Graph e conceder consentimento administrativo. Henrique Netto
coordena a solicitação; ele pode assumir também este papel somente se possuir
essas permissões no tenant.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [configurar redirect URI no Entra](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri)
- `docs/fase-8-runtime-producao.md`

Risco:
o acesso e a mailbox de teste foram informados como disponíveis, mas ainda
faltam o executor Entra, a política de consentimento e a confirmação dos
usuários de teste. IDs e contas não devem ser registrados neste documento.

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

- telefone/número dedicado ao teste, informado como disponível;
- janela de QR de 30 minutos com responsável disponível;
- volume `waha_sessions` em disco criptografado do servidor;
- porta privada e Dashboard/Swagger desligados;
- snapshot frio semanal do volume, com WAHA parado e acesso restrito;
- perda da sessão: tentar restore; novo QR somente com autorização;
- limite candidato: 5 envios/dia;
- limite produtivo inicial: 45 envios/dia, sujeito à política interna e ao
  consentimento dos destinatários;
- nenhuma mensagem em massa no candidato.

Responsável:
**pendente de confirmação — custodiante do telefone**. É a pessoa que mantém
posse/controle do aparelho e SIM, consegue abrir o WhatsApp, escanear o QR e
recuperar ou autorizar nova sessão. Henrique Netto pode assumir o papel se o
telefone estiver sob seu controle.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `docs/fase-8-waha-sidecar.md`
- `docker-compose.production.yml`

Risco:
o telefone foi informado como disponível, mas seu custodiante ainda precisa
ser confirmado. Snapshot de sessão contém credenciais de pareamento e deve ser
tratado como segredo.

Plano alternativo:
refazer QR com o mesmo número de teste. Não usar mocks como prova da G6.

## 10. Observabilidade e alertas

Decisão:
coletor, métricas, probes, retenção, alertas e canal.

Opções consideradas:

1. plataforma corporativa de monitoramento/logs;
2. stack Prometheus/Loki/Grafana autogerida;
3. serviço externo de uptime/logs.

Escolha:
**preferência — opção 1**, a confirmar com a equipe do servidor.

- métricas de CPU, memória, disco e rede;
- métricas do PostgreSQL;
- coleta estruturada dos logs Docker, preservando `request_id` e descartando
  payloads não permitidos;
- retenção inicial de logs: 30 dias;
- probes externos ou corporativos em `/healthz` e `/readyz`;
- alertas para `hfnetto@stefanini.com`; segundo canal rápido recomendado;
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
Henrique Netto — plantonista/dono operacional e destinatário dos alertas.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `docs/fase-8-operacao-duravel.md`

Risco:
o serviço corporativo ainda não foi identificado. Não enviar bodies, headers
de autenticação, mensagens ou documentos aos logs. Email é o canal registrado,
mas um segundo canal rápido reduz o risco de atraso fora do expediente.

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
- soak do candidato aprovado: 72 horas;
- indisponibilidade máxima aprovada para o cutover: 2 horas, com meta interna
  de conclusão em até 60 minutos;
- RTO aprovado: 4 horas; RPO aprovado: 15 minutos;
- hypercare aprovada: 5 dias úteis;
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

- dono técnico: Henrique Netto;
- aprovador do go-live: Henrique Netto;
- responsável técnico pelo servidor/PostgreSQL: Henrique Netto;
- administrador Entra: **pendente**;
- custodiante WAHA: **pendente**;
- plantonista/hypercare: Henrique Netto.

Janela:
é o período reservado para congelar gravações no desktop, fazer backup final,
executar o ETL, validar os dados, ativar a URL e, se necessário, fazer rollback.
Proposta de referência: 2 horas fora do expediente comercial,
19:00–21:00 em `America/Sao_Paulo`. A data e o horário serão aprovados na G7.

Canal de incidente:
`hfnetto@stefanini.com`. Recomenda-se adicionar um canal síncrono corporativo
(Teams/telefone) antes do go-live.

Evidência/contrato:
`docs/plano-acao-pos-fase-8-go-live.md`.

Risco:
Entra e WAHA ainda não têm responsáveis nominalmente confirmados. Uma janela
base foi proposta, mas data e horário só serão fechados na G7.

Plano alternativo:
adiar G3 até os responsáveis aceitarem explicitamente seus papéis.

## 12. Orçamento e aprovação

Não haverá contratação de VM Azure para hospedar o Toca: será usado o servidor
corporativo existente. Portanto, não se aplica um teto mensal Azure para o
runtime.

Ainda devem ser identificados eventuais custos/chargeback corporativos de:

- PostgreSQL gerenciado ou segundo nó para HA;
- armazenamento externo de backups;
- monitoramento e retenção de logs;
- WAF/proxy, certificado e DNS;
- expansão de CPU, memória ou disco do servidor.

Teto mensal:
**não aplicável à hospedagem Azure; custos incrementais corporativos pendentes
de identificação**.

Aprovador de custo:
Henrique Netto para custos sob sua alçada; contratação ou chargeback
corporativo segue a aprovação interna aplicável.

## 13. Aprovações necessárias para concluir a G2

- [x] substituir Azure/Brazil South pelo servidor corporativo;
- [x] registrar que não há teto mensal Azure para hospedagem;
- [ ] confirmar capacidade e armazenamento do servidor;
- [ ] confirmar `toca-candidato.stefanini.com` para candidato;
- [x] confirmar `toca.stefanini.com` para produção;
- [ ] confirmar tenant e nome do administrador Entra;
- [x] confirmar disponibilidade da mailbox de teste;
- [x] confirmar disponibilidade do telefone/número WAHA de teste;
- [ ] confirmar custodiante WAHA;
- [ ] confirmar serviço corporativo PostgreSQL/HA ou aceitar formalmente o
  fallback sem HA;
- [ ] confirmar destino corporativo externo de backup e monitoramento;
- [x] confirmar responsáveis técnico, PostgreSQL, go-live e hypercare;
- [ ] confirmar responsáveis Entra e WAHA;
- [x] registrar janela de referência, canal de incidente e canal de alertas;
- [x] confirmar carga esperada de 15 cadastrados/6 simultâneos;
- [x] aprovar RPO 15 min, RTO 4 h, soak 72 h, downtime 2 h e hypercare 5 dias;
- [x] aprovar HA no PostgreSQL produtivo, condicionada a serviço/nó que a
  implemente de fato;
- [x] aprovar adaptação do ETL antes da G5.

Enquanto algum item permanecer aberto, a G2 está **parcial** e a G3 não está
liberada.
