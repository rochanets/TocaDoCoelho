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
- PostgreSQL 16 será inicialmente autogerido no servidor corporativo, sem HA;
- backups locais automatizados são a proteção inicial. A ausência temporária
  de cópia externa é um risco aceito e impede garantir recuperação se o host ou
  seu armazenamento forem perdidos;
- não haverá plataforma de monitoramento nesta etapa; healthchecks, logs locais
  e verificações manuais permanecem obrigatórios;
- Microsoft Entra e Graph continuam usando Authorization Code + PKCE, sem
  `client_secret` no Toca;
- cada usuário autenticado terá sua própria sessão WAHA e fará o pareamento por
  QR com o próprio telefone;
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
| Administrador Entra | Henrique Netto | App Registration, consentimento e allowlist |
| Mailbox de teste | disponível; identificador não registrado no Git | Graph/E2E |
| Telefones WAHA | cada usuário utilizará o próprio aparelho/número | QR, envio e recebimento por sessão individual |
| Canal de incidentes | `hfnetto@stefanini.com` | comunicação manual nesta etapa |
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

Escolha aprovada:
**opção 3**, PostgreSQL 16 autogerido no mesmo servidor da aplicação. Para a
carga inicial de 15 usuários cadastrados e 6 simultâneos, HA não é requisito
funcional nem de capacidade. A manutenção deve ficar fora da janela
operacional.

HA reduziria a indisponibilidade causada pela falha do banco ou do host, mas
exigiria pelo menos outro nó/domínio de falha, replicação, failover e operação
adicional. Foi adiada nesta etapa. Uma falha do servidor derrubará aplicação e
banco até a restauração, e esse risco foi aceito pelo aprovador do go-live.

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
PostgreSQL no mesmo servidor não oferece HA. Perda do host ou do armazenamento
pode exceder o RTO e, enquanto não houver cópia externa, causar perda total dos
dados. O endpoint de banco deve permanecer privado.

Evolução futura:
migrar para PostgreSQL corporativo gerenciado ou segundo nó com replicação e
failover quando disponibilidade, criticidade ou quantidade de usuários
justificarem.

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
3. backup automatizado somente no servidor corporativo.

Escolha aprovada como etapa inicial:
**opção 3**, com risco explicitamente aceito e evolução posterior para cópia
externa. Backup no mesmo servidor ajuda contra erro lógico ou exclusão
acidental, mas não protege contra perda do host, disco ou volume.

- dump completo `pg_dump` + SHA-256 a cada 24 horas;
- retenção local: 14 backups diários;
- destino preferencial: filesystem/volume dedicado do servidor, fora do volume
  de dados do PostgreSQL;
- permissões restritas e expiração automatizada;
- arquivamento local de WAL/PITR com `archive_timeout` máximo de 15 minutos, se
  o espaço e a configuração do host permitirem;
- log local do resultado de cada execução;
- restore lógico em banco descartável mensal e antes de cada go-live.

Objetivos propostos:

- RPO alvo para erro lógico: 15 minutos, condicionado ao WAL/PITR local íntegro;
- RPO somente com dump: até 24 horas;
- perda do host/armazenamento: sem RPO garantido enquanto não houver cópia
  externa;
- RTO alvo: 4 horas somente se o servidor e o backup local estiverem
  disponíveis; desastre do host fica sem RTO garantido nesta etapa.

Responsável:
Henrique Netto — dono técnico e responsável por continuidade.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `deploy/postgres/backup-once.sh`
- `deploy/postgres/restore-verify.sh`

Risco aceito:
o repositório hoje grava dumps no volume `postgres_backups`, no mesmo host. A
rotina precisa ser automatizada e o restore comprovado na G3. Sem cópia
externa, falha física, perda do host, ransomware ou exclusão ampla pode eliminar
banco e backup simultaneamente.

Evolução futura:
copiar os backups para storage corporativo, S3 compatível ou compartilhamento
protegido, com criptografia, versionamento/imutabilidade, retenção e restore
comprovado.

## 7. DNS, TLS e segredos

Decisão:
subdomínios, certificado, renovação e secret store.

Opções consideradas:

1. publicação pela borda/WAF corporativa e DNS existente;
2. certificado público diretamente no Nginx;
3. migração da zona para outro provedor.

Escolha aprovada:
**opção 1**. Não mover a zona DNS nesta migração.

- domínio informado anteriormente: `toca.stefanini.com`;
- domínio informado mais recentemente: `toca.stefanin.com`;
- decisão de DNS bloqueada até confirmar qual grafia é a correta; não criar
  registros ou redirects enquanto houver divergência;
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
há divergência de grafia entre `stefanini.com` e `stefanin.com`. O chamado
corporativo também precisa confirmar TLS, WAF/proxy, healthcheck e o backend. A
porta 3000 não deve ser exposta.

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

- redirects exatos do domínio candidato, após confirmação de sua grafia;
- redirects equivalentes do domínio final somente quando a G7 autorizar.

Permissões delegadas:
`openid profile email offline_access User.Read Mail.Read Mail.Send`.

Allowlist inicial:
administrador, usuário comum proprietário, usuário comum isolado e identidade
negada, todos de teste/autorizados. Mailbox de teste deve poder ler e enviar
uma mensagem controlada.

Responsável:
Henrique Netto — administrador responsável no Microsoft Entra por
criar/alterar o App Registration, cadastrar redirects, revisar permissões
Graph e conceder consentimento administrativo.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [configurar redirect URI no Entra](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri)
- `docs/fase-8-runtime-producao.md`

Risco:
o acesso e a mailbox de teste foram informados como disponíveis. Ainda devem
ser confirmados a política de consentimento e os usuários de teste. IDs e
contas não devem ser registrados neste documento.

Plano alternativo:
confidential client/certificado somente se a política do tenant exigir; isso
demanda decisão e implementação separadas antes da G3.

## 9. WAHA

Decisão:
sessões individuais por usuário, QR, isolamento, persistência, recuperação e
limites.

Escolha aprovada:
cada usuário autenticado no Toca possui uma sessão WAHA própria no sidecar
compartilhado. Ao abrir a integração, o usuário vê apenas o QR de sua sessão e
faz o pareamento com o próprio telefone/WhatsApp.

Requisitos:

- criar uma associação persistente e única `user_id → waha_session_name`;
- usar identificador de sessão opaco, não email ou telefone;
- permitir que o usuário crie, consulte, reinicie e desconecte somente sua
  própria sessão;
- resolver a sessão do usuário autenticado em todo envio, sincronização,
  quota, job e webhook;
- usar o campo `session` recebido no webhook para identificar o proprietário e
  aplicar ACL antes de gravar dados;
- impedir enumeração ou acesso cruzado entre sessões;
- manter a API WAHA e o Dashboard/Swagger privados;
- persistir as sessões em volume protegido;
- definir o comportamento de logout/exclusão de usuário sem apagar sessão de
  outra pessoa;
- aplicar limites de envio por usuário/sessão;
- testar pelo menos dois usuários e dois telefones simultaneamente.

Constatação:
o WAHA suporta múltiplas sessões no mesmo container, mas o Toca atual usa
`WAHA_SESSION_NAME` e `app_settings.waha_session_name` globais. As rotas de
status/conexão/envio e o webhook ainda não implementam isolamento por usuário.
Essa adaptação de código é obrigatória antes do E2E e do go-live.

Responsável:
Cada usuário é custodiante do próprio telefone e da própria sessão. Henrique
Netto é o responsável técnico pelo sidecar WAHA, volume, atualização e
recuperação do serviço, sem assumir controle dos telefones dos usuários.

Data:
29/07/2026, proposta.

Evidência/contrato:

- [WAHA — sessões e múltiplas sessões](https://waha.devlike.pro/docs/how-to/sessions/)
- `docs/fase-8-waha-sidecar.md`
- `docker-compose.production.yml`

Risco:
cada sessão WAHA consome recursos e contém credenciais de pareamento. O volume
deve ser tratado como segredo, e a capacidade precisa ser testada com múltiplas
sessões simultâneas. O modelo atual de sessão global causaria uso cruzado da
conta de WhatsApp e é bloqueante para o go-live multiusuário.

Plano alternativo:
o próprio usuário refaz o QR de sua sessão quando necessário. Não usar sessão
compartilhada nem mocks como prova da G6.

## 10. Observabilidade e alertas

Decisão:
coletor, métricas, probes, retenção, alertas e canal.

Opções consideradas:

1. plataforma corporativa de monitoramento/logs;
2. stack Prometheus/Loki/Grafana autogerida;
3. sem plataforma de monitoramento nesta etapa.

Escolha aprovada nesta etapa:
**opção 3**.

- healthchecks locais em `/healthz` e `/readyz`;
- logs locais com rotação e sem payloads sensíveis;
- verificação manual do estado dos containers, banco, backup e WAHA durante
  implantação e hypercare;
- sem alertas automáticos nesta etapa.

Limiares recomendados para uma futura adoção de monitoramento:

- probes falhando por 3 minutos;
- HTTP 5xx acima de 2% por 5 minutos;
- p95 acima de 2 segundos por 10 minutos;
- disco livre abaixo de 20%;
- último backup local acima de 26 horas;
- heartbeat/claim vencido;
- WAHA indisponível por 5 minutos.

Responsável:
Henrique Netto — plantonista/dono operacional e executor das verificações
manuais.

Data:
29/07/2026, proposta.

Evidência/contrato:

- `docs/fase-8-operacao-duravel.md`

Risco aceito:
falhas podem permanecer desconhecidas até um usuário ou uma verificação manual
detectá-las. Não enviar bodies, headers de autenticação, mensagens ou
documentos aos logs.

Evolução futura:
adotar a plataforma corporativa ou um serviço externo de uptime e logs,
mantendo os mesmos limites, redaction e retenção.

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
- RTO/RPO permanecem metas condicionais ao backup local; não são garantidos
  para perda do host enquanto não houver cópia externa;
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
- administrador Entra: Henrique Netto;
- custódia WAHA: cada usuário cuida do próprio telefone/sessão; Henrique Netto
  responde tecnicamente pelo serviço;
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
uma janela base foi proposta, mas data e horário só serão fechados na G7. A
ausência inicial de backup externo e monitoramento automático foi aceita e
deve ser reavaliada após a estabilização.

Plano alternativo:
adiar G3 até os responsáveis aceitarem explicitamente seus papéis.

## 12. Orçamento e aprovação

Não haverá contratação de VM Azure para hospedar o Toca: será usado o servidor
corporativo existente. Portanto, não se aplica um teto mensal Azure para o
runtime.

Ainda devem ser identificados eventuais custos/chargeback corporativos de:

- eventual PostgreSQL gerenciado ou segundo nó para HA;
- futura cópia externa de backups;
- futuro monitoramento e retenção centralizada de logs;
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
- [ ] confirmar se o domínio correto é `toca.stefanini.com` ou
  `toca.stefanin.com`;
- [ ] confirmar o tenant Entra;
- [x] confirmar disponibilidade da mailbox de teste;
- [x] confirmar Henrique Netto como administrador Entra;
- [x] confirmar uma sessão WAHA e um telefone por usuário;
- [x] registrar cada usuário como custodiante da própria sessão WAHA;
- [x] adiar HA e aceitar PostgreSQL no mesmo host;
- [x] aceitar backup somente local nesta etapa, com risco documentado;
- [x] adiar plataforma de monitoramento e alertas automáticos;
- [x] confirmar responsáveis técnico, PostgreSQL, go-live e hypercare;
- [x] registrar janela de referência, canal de incidente e canal de alertas;
- [x] confirmar carga esperada de 15 cadastrados/6 simultâneos;
- [x] aprovar RPO 15 min, RTO 4 h, soak 72 h, downtime 2 h e hypercare 5 dias;
- [x] retirar HA do escopo inicial e registrar evolução futura;
- [x] aprovar adaptação do ETL antes da G5;
- [ ] implementar e testar isolamento WAHA por usuário antes do E2E.

Enquanto algum item permanecer aberto, a G2 está **parcial** e a G3 não está
liberada.
