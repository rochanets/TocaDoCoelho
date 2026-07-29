# Plano de ação pós-Fase 8 — ambiente online, E2E e go-live

Status do documento: **aprovado para execução faseada**

Data-base: 29/07/2026

Branch de referência da aplicação web: `Live`

Branch da aplicação desktop atualmente distribuída aos usuários: `main`

## 1. Objetivo

Este plano conduz o TocaDoCoelho do fechamento técnico da Fase 8 até um
go-live controlado, com validação end-to-end em ambiente online, migração de
dados, observabilidade, recuperação e decisão explícita sobre branches.

O plano preserva o contrato atual:

- `main` continua sendo a linha estável do aplicativo desktop e alimenta o
  mecanismo de atualização dos usuários atuais;
- `Live` continua sendo a linha candidata da aplicação web;
- `Live` **não** será transformada em branch principal e **não** será mesclada
  integralmente em `main` antes de o ambiente online passar no E2E;
- as PRs antigas `#249` e `#244` estão deliberadamente fora do escopo e não
  devem ser analisadas, alteradas, fechadas ou integradas durante este plano;
- a Fase 9 (multi-org/SaaS, billing e onboarding) não começa automaticamente.

## 2. Estado inicial confirmado

- F8.1 a F8.5 estão integradas em `Live`.
- O PR `#298` foi mergeado e os workflows pós-merge ficaram verdes.
- `main` e `Live` têm funções diferentes e estão intencionalmente separadas
  até o gate de E2E.
- Três correções do PR `#251` existem em `main`, mas não possuem patch
  equivalente em `Live`:
  - `a648f8d` — identificação de chat e feedback de tarefa;
  - `2a4a058` — busca por `getChats()` para compatibilidade com LID;
  - `d27cbe8` — versão estável do WhatsApp Web persistida no repositório.
- Os gates externos do checklist de prontidão continuam abertos.

Os SHAs acima servem para identificar o conteúdo observado em 29/07/2026.
Todo chat executor deve fazer `git fetch origin` e confirmar os SHAs antes de
agir.

## 3. Regras invariáveis para todos os próximos chats

1. Ler este documento e os runbooks indicados pela fase antes de alterar o
   repositório ou qualquer ambiente.
2. Trabalhar em uma única fase por chat, salvo autorização explícita para
   continuar.
3. Criar branches de trabalho com prefixo `codex/`.
4. Usar `Live` como base para mudanças da aplicação web.
5. Não fazer merge de `main` em `Live`, nem de `Live` em `main`, antes da Fase
   G7.
6. Na Fase G1, portar somente o conteúdo dos três commits do PR `#251`; não
   trazer outros commits exclusivos de `main`.
7. Não alterar a branch padrão do GitHub antes da Fase G7.
8. Não alterar o mecanismo de atualização desktop antes da Fase G7.
9. Não executar ações em PRs `#249` e `#244`.
10. Nunca versionar `.env`, tokens, dumps, bancos, certificados, QR, sessões
    WAHA ou chaves.
11. Nunca imprimir segredos, dados pessoais, conteúdo de mensagens ou strings
    de conexão completas em logs, comentários ou relatórios.
12. Nunca executar `docker compose down -v` em ambiente persistente.
13. Nunca rodar o ETL contra um PostgreSQL que contenha dados que não possam ser
    descartados: o ETL atual executa `TRUNCATE ... CASCADE`.
14. Toda escrita em DNS, Entra, banco gerenciado, secret store, observabilidade
    ou conta WhatsApp exige autorização e acesso explícitos no chat executor.
15. Toda mudança deve ter teste proporcional ao risco, revisão do diff, CI
    verde e registro de evidência.
16. Um chat não pode declarar uma fase concluída apenas porque produziu
    documentação; os critérios de aceite da fase precisam estar comprovados.

## 4. Protocolo padrão de execução por chat

Antes de iniciar qualquer fase:

```powershell
git status --short --branch
git fetch origin
git log -1 --oneline origin/main
git log -1 --oneline origin/Live
```

O executor deve:

1. confirmar que não há alterações locais não relacionadas;
2. informar qual fase será executada;
3. listar acessos externos disponíveis e ausentes;
4. registrar o SHA inicial de `main` e `Live`;
5. criar a branch a partir da base indicada;
6. executar somente ações autorizadas;
7. rodar testes e checks;
8. revisar o diff e eventuais comentários da PR;
9. atualizar a seção **Registro de execução** deste documento ou produzir um
   handoff com as mesmas informações;
10. parar diante de qualquer condição de bloqueio definida na fase.

### Modelo obrigatório de handoff

Todo chat deve terminar com:

```text
Fase executada:
Status: concluída | parcial | bloqueada
Branch e SHA:
PR:
Alterações realizadas:
Validações executadas:
Evidências/URLs:
Segredos ou ambientes alterados: não | sim, quais (sem valores)
Riscos residuais:
Rollback disponível:
Próxima fase liberada:
Instrução exata para o próximo chat:
```

## 5. Visão geral

| Fase | Resultado | Base | Gate para avançar |
|---|---|---|---|
| G0 | Plano e contrato de branches registrados | `Live` | documento revisado |
| G1 | Correções do PR `#251` portadas para web | `Live` | PR e CI verdes |
| G2 | Arquitetura e fornecedores de produção decididos | nenhuma mudança de código obrigatória | decisões e responsáveis aprovados |
| G3 | Ambiente online não produtivo provisionado e seguro | infraestrutura | probes, TLS, DB e observabilidade |
| G4 | Candidato de `Live` implantado online | `Live` | stack saudável e SHA conferido |
| G5 | Migração de dados ensaiada e reconciliada | cópias descartáveis | contagens, FKs, arquivos e usuários |
| G6 | E2E online concluído | ambiente candidato | matriz E2E integralmente aprovada |
| G7 | Go/no-go e estratégia de branches aprovados | decisão humana | autorização formal |
| G8 | Cutover produtivo executado | imagem já testada | smoke real e monitoramento |
| G9 | Hypercare encerrado e operação transferida | produção | estabilidade e runbooks aceitos |

---

## Fase G0 — registrar o plano e congelar o contrato de branches

### Objetivo

Tornar este documento a referência operacional pós-Fase 8 e impedir que um
chat futuro trate a divergência entre `main` e `Live` como um erro a ser
resolvido por merge automático.

### Ações

- [x] Revisar este plano com o responsável pelo produto.
- [x] Confirmar por escrito:
  - `main` = desktop distribuído e canal atual de updates;
  - `Live` = candidato web;
  - nenhuma troca de default branch antes do E2E;
  - nenhuma fusão integral entre as branches antes da Fase G7.
- [x] Vincular este plano ao checklist da Fase 8.
- [x] Confirmar que PRs de web futuras usam `Live` como base.
- [x] Confirmar que correções urgentes de desktop continuam usando `main`.

Confirmação do contrato de branches registrada pelo responsável pelo produto
em 29/07/2026.

### Critérios de aceite

- Documento versionado e acessível em `Live`.
- Contrato de branches explícito e sem ambiguidade.
- Nenhuma configuração de branch ou updater alterada.

### Condições de parada

- O papel de alguma branch não estiver confirmado pelo responsável.
- Houver mudanças não relacionadas no worktree.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md por inteiro e execute somente a
Fase G1. main é o desktop distribuído; Live é a candidata web. Não faça merge
entre as branches e ignore completamente as PRs #249 e #244. Porte para uma
branch criada de Live somente os três commits do PR #251 identificados no
plano, resolva conflitos manualmente, rode os testes focados e a suíte
completa, abra PR contra Live, revise o diff e acompanhe a CI.
```

---

## Fase G1 — portar as correções de WhatsApp de `main` para `Live`

### Objetivo

Evitar que a aplicação web perca as correções de identificação de chats,
compatibilidade LID e fixação da versão estável do WhatsApp Web, sem misturar
as histórias das duas branches.

### Base e escopo permitido

Base: `origin/Live`.

Commits de origem:

```text
a648f8dd3fdd3b07256ed50d20fb1adeaeacf43b
2a4a0589d1ebb753cbcae4fb4e02980a7811a6b1
d27cbe831b4736587cf70b7a8d539df16006b197
```

Arquivos esperados no conteúdo original:

- `app.py`
- `public/js/core.js`
- `public/js/init.js`
- `waha-lite/waha-lite.js`
- `waha-lite/web-version.txt`

### Procedimento

```powershell
git fetch origin
git switch Live
git pull --ff-only origin Live
git switch -c codex/live-port-whatsapp-251
git show --stat a648f8d
git show --stat 2a4a058
git show --stat d27cbe8
git cherry-pick a648f8d 2a4a058 d27cbe8
```

Se houver conflito:

1. não aceitar automaticamente a versão inteira de nenhuma branch;
2. comparar o objetivo de cada hunk com a implementação atual de `Live`;
3. preservar ACL, persistência multiworker, logs estruturados e contratos
   web introduzidos depois do PR `#251`;
4. aplicar manualmente apenas o comportamento funcional necessário;
5. se não for possível provar equivalência, executar
   `git cherry-pick --abort`, documentar o conflito e propor uma
   reimplementação isolada.

### Validação mínima

```powershell
$env:TOCA_DATA_DIR = Join-Path $env:TEMP "toca-g1-tests-$PID"
$env:TOCA_DISABLE_BG_JOBS = '1'
python -m pytest tests/test_waha_send.py `
  tests/test_whatsapp_dedup.py `
  tests/test_acl_whatsapp_inbound.py `
  tests/test_acl_whatsapp_outbound.py `
  tests/test_fase_8_3_waha_sidecar.py -q
python scripts/check_no_secrets.py
python -m pytest -q
git diff origin/Live...HEAD --check
```

Também validar:

- [ ] `web-version.txt` é empacotado pelo instalador desktop sem interferir no
  sidecar WAHA produtivo.
- [ ] nenhum endpoint ou porta nova foi publicado.
- [ ] logs adicionais não expõem telefone completo, conteúdo de mensagem,
  token, cookie ou chave.
- [ ] o feedback de tarefas continua isolado por usuário.
- [ ] os workflows Docker, PostgreSQL, backup/restore e ensaio de produção
  passam.

### Entrega

- PR com base `Live`.
- Descrição deixando explícito que não é merge de branches.
- Relação dos conflitos e de como foram resolvidos.
- Revisão sem achados bloqueantes.

### Critérios de aceite

- Os três comportamentos do PR `#251` existem em `Live`.
- Suíte completa e CI verdes.
- `main` permanece inalterada.
- Branch padrão permanece `main`.

### Condições de parada

- O cherry-pick trouxer arquivos fora do escopo esperado.
- Houver incompatibilidade entre WAHA-lite desktop e WAHA sidecar web.
- Testes indicarem vazamento entre usuários ou duplicação de mensagens.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G2.
Confirme primeiro que a Fase G1 está mergeada em Live e verde. Não altere
main, Live, default branch, updater, DNS ou serviços. Conduza e documente as
decisões de host, PostgreSQL, backup externo, DNS/TLS, Entra, WAHA,
observabilidade, responsáveis e orçamento. Não invente fornecedor nem
credencial: registre opções, decisão, dono e evidência; pare nas decisões que
dependem do usuário.
```

---

## Fase G2 — decidir arquitetura, fornecedores, acessos e responsáveis

### Objetivo

Eliminar decisões pendentes antes de provisionar recursos e impedir que
infraestrutura seja criada de forma improvisada.

### Decisões obrigatórias

#### Hospedagem e rede

- [ ] fornecedor/host e região;
- [ ] capacidade inicial de CPU, RAM e disco;
- [ ] perfil de carga esperado, margem de capacidade e método de validação;
- [ ] IP e política de firewall;
- [ ] acesso administrativo, MFA e lista de operadores;
- [ ] estratégia de atualização do host e Docker;
- [ ] subdomínio de candidato e domínio final.

#### PostgreSQL

- [ ] gerenciado ou container autogerido;
- [ ] PostgreSQL major compatível;
- [ ] TLS em trânsito e criptografia em repouso;
- [ ] capacidade, limites de conexão, HA e manutenção;
- [ ] função de aplicação, função de migration e função temporária de ETL;
- [ ] política de snapshots e Point-in-Time Recovery, se disponível.

O ETL atual usa `SET session_replication_role = 'replica'`, normalmente
restrito a superuser. O fornecedor precisa permitir uma função temporária
adequada ou o ETL deve ser adaptado e testado antes da Fase G5.

#### Backup externo

- [ ] destino criptografado fora do host;
- [ ] credencial de acesso mínimo;
- [ ] retenção e expiração;
- [ ] RPO, RTO e prazo máximo comprovado para restore;
- [ ] alerta para backup atrasado;
- [ ] frequência do teste de restore.

#### Microsoft Entra e Graph

- [ ] tenant e administrador responsáveis;
- [ ] App Registration de produção;
- [ ] redirects do domínio candidato/final;
- [ ] allowlist inicial de usuários;
- [ ] mailbox e identidade de teste autorizadas;
- [ ] consentimento das permissões delegadas.

#### WAHA

- [ ] número/sessão de teste;
- [ ] responsável pelo telefone;
- [ ] janela de QR e política de recuperação;
- [ ] armazenamento e backup do volume de sessão;
- [ ] limites operacionais e política de envio.

#### Observabilidade

- [ ] coletor de logs;
- [ ] métricas e healthchecks externos;
- [ ] limites numéricos de disponibilidade, taxa de 5xx e latência p95;
- [ ] canal de alertas;
- [ ] retenção sem conteúdo sensível;
- [ ] responsável por responder a alertas.

#### Operação

- [ ] dono técnico;
- [ ] aprovador de go-live;
- [ ] janela de deploy e rollback;
- [ ] indisponibilidade máxima e duração do soak;
- [ ] fonte autoritativa antes, durante e depois do cutover;
- [ ] ponto de não retorno e regra para congelamento de escritas;
- [ ] duração de hypercare;
- [ ] canal de incidente;
- [ ] critérios de no-go.

### Artefato esperado

Criar `docs/go-live/decisoes-infraestrutura.md`, sem segredos, contendo:

```text
Decisão:
Opções consideradas:
Escolha:
Responsável:
Data:
Evidência/contrato:
Risco:
Plano alternativo:
```

### Critérios de aceite

- Todos os itens têm decisão e responsável.
- Custos e acessos foram aprovados.
- Nenhum segredo foi versionado.
- A estratégia de privilégio do ETL está definida.

### Condições de parada

- Falta de autorização para custos ou serviços.
- Tenant, domínio ou telefone sem responsável.
- PostgreSQL sem estratégia viável de ETL, backup e restore.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e
docs/go-live/decisoes-infraestrutura.md. Execute somente a Fase G3.
Antes de qualquer criação externa, confirme os acessos e autorizações
disponíveis. Provisione um ambiente online não produtivo para a candidata
Live, sem mudar DNS final, main, default branch ou updater. Mantenha segredos
fora do Git, publique apenas 80/443, configure PostgreSQL, backup externo,
TLS, logs, métricas e alertas e entregue evidências sem dados sensíveis.
```

---

## Fase G3 — provisionar o ambiente online não produtivo

### Objetivo

Disponibilizar uma infraestrutura online segura para receber o candidato de
`Live`, sem impacto nos usuários desktop e sem promover o domínio final.

### Pré-requisitos

- Fase G2 aprovada.
- Acessos explícitos ao host, DNS de candidato, banco, secret store e
  observabilidade.
- Subdomínio separado, por exemplo `toca-candidato.<domínio>`.
- Dados e contas de teste autorizados.

### Procedimento

#### Host

- [ ] aplicar atualizações de segurança;
- [ ] criar usuário operacional sem login compartilhado;
- [ ] exigir autenticação forte;
- [ ] limitar SSH/VPN a origens autorizadas;
- [ ] liberar somente 80/443 publicamente;
- [ ] confirmar que Docker não publica PostgreSQL, web ou WAHA;
- [ ] configurar sincronização de horário e espaço em disco.

#### Segredos

- [ ] criar arquivo/secret store fora do checkout;
- [ ] preencher o contrato de `.env.production.example`;
- [ ] gerar valores independentes para `SECRET_KEY`, senha PostgreSQL,
  `WAHA_API_KEY` e `WAHA_WEBHOOK_HMAC_KEY`;
- [ ] restringir permissões de leitura;
- [ ] confirmar que logs e histórico de shell não receberam valores.

#### DNS e TLS do candidato

- [ ] criar apenas o registro do subdomínio candidato;
- [ ] emitir certificado válido;
- [ ] configurar renovação automática;
- [ ] testar cadeia, hostname e expiração;
- [ ] não alterar o domínio usado pelos usuários atuais.

#### PostgreSQL

- [ ] criar instância/banco vazio de candidato;
- [ ] habilitar TLS e backups do fornecedor;
- [ ] restringir rede;
- [ ] criar papéis separados conforme G2;
- [ ] configurar métricas de conexão, armazenamento e disponibilidade.

#### Backup e observabilidade

- [ ] conectar a cópia externa criptografada;
- [ ] configurar alerta para último backup acima de 26 horas;
- [ ] configurar probes externos de `/healthz` e `/readyz`;
- [ ] configurar alertas iniciais do runbook F8.4;
- [ ] confirmar redaction e ausência de payloads sensíveis.

### Validação

Antes de subir a aplicação:

```bash
docker compose \
  --env-file /caminho/seguro/toca-candidato.env \
  -f docker-compose.production.yml config
```

Guardar, sem segredos:

- versão do Docker/Compose;
- hostname e região;
- domínio candidato;
- PostgreSQL major;
- IDs dos recursos;
- política de backup;
- destinos de alertas;
- resultado de firewall/port scan.

### Critérios de aceite

- Apenas 80/443 estão publicamente acessíveis.
- Certificado do candidato é válido.
- Banco aceita conexão somente pelas origens autorizadas.
- Backup externo e alertas estão configurados.
- Nenhuma alteração ocorreu em `main`, no updater ou no domínio final.

### Condições de parada

- Segredo aparecer no Git, logs ou saída compartilhada.
- PostgreSQL ou WAHA ficar publicamente acessível.
- Não houver backup externo ou responsável por alertas.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G4.
Use o ambiente candidato aprovado na G3 e o HEAD atual de Live já contendo a
G1. Construa uma imagem imutável com SHA/versão, registre seu digest, execute
migrate como one-shot e suba a stack online. Não migre dados reais, não conecte
telefone ou mailbox reais sem autorização e não altere main, default branch,
updater ou domínio final. Valide TLS, health, readiness, request_id, workers,
rede privada, backup e observabilidade.
```

---

## Fase G4 — implantar o candidato de `Live` no ambiente online

### Objetivo

Executar o primeiro deploy online da aplicação web com banco vazio/dados de
teste e provar que o ambiente real respeita o contrato já ensaiado na CI.

### Preparação

```bash
git fetch origin
git checkout --detach origin/Live
candidate_sha="$(git rev-parse HEAD)"
candidate_version="candidate-$(printf '%s' "$candidate_sha" | cut -c1-12)"
```

O diretório de dados de teste da G1 deve ser removido somente após conferir que
o caminho resolvido pertence à área temporária. O comando de versão da G4 pode
ser adaptado ao shell, mas o SHA completo deve ser guardado. Não usar `latest`.

### Deploy

1. construir uma única imagem com `TOCA_BUILD_SHA` e `TOCA_BUILD_VERSION`;
2. registrar o digest da imagem;
3. validar o Compose usando o arquivo de ambiente seguro;
4. confirmar backup do banco, mesmo vazio;
5. executar somente o serviço `migrate`;
6. confirmar `schema_version`;
7. subir web, WAHA, backup e Nginx;
8. aguardar todos os healthchecks.

### Smoke obrigatório

- [ ] HTTP redireciona para HTTPS.
- [ ] certificado e hostname são válidos.
- [ ] `/healthz` responde.
- [ ] `/readyz` responde e confirma o schema.
- [ ] `X-Request-ID` é propagado.
- [ ] API administrativa sem sessão recebe `401`.
- [ ] dois workers Gunicorn estão ativos.
- [ ] PostgreSQL, web e WAHA não publicam portas.
- [ ] backup gera dump e checksum.
- [ ] coletor recebe logs JSON sem segredos.
- [ ] alertas de teste chegam ao canal definido.
- [ ] dashboard Swagger do WAHA permanece desligado.

### Evidências

Criar `docs/go-live/evidencias-deploy-candidato.md` com:

- SHA e digest;
- data/hora e executor;
- ambiente e domínio;
- resultado dos probes;
- versão do schema;
- estado dos serviços;
- IDs de backup/alerta;
- incidentes e correções, sem dados sensíveis.

### Critérios de aceite

- Stack online estável por pelo menos o período de soak definido na G2.
- Todos os smokes passam.
- Imagem e rollback estão identificados por digest.
- Usuários desktop continuam usando `main` sem alteração.

### Condições de parada

- Readiness instável.
- Migration incompleta.
- Logs contendo segredos.
- Imagem executada diferente do digest aprovado.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G5.
Use cópias autorizadas dos bancos SQLite; nunca altere o original. Inventarie
todas as fontes de dados e arquivos, migre uma cópia até o schema atual e rode
scripts/etl_sqlite_to_postgres.py somente contra PostgreSQL descartável/vazio.
Lembre que o ETL executa TRUNCATE CASCADE e exige privilégio para
session_replication_role. Valide contagens, FKs, IDs, usuários, owners,
arquivos/anexos e amostras funcionais. Não faça cutover nem use dados reais em
logs.
```

---

## Fase G5 — ensaiar migração e reconciliação de dados

### Objetivo

Provar que os dados atuais do desktop podem chegar ao PostgreSQL com
integridade, ownership correto e arquivos associados, antes de qualquer
congelamento produtivo.

### Inventário obrigatório

- [ ] listar cada instalação/banco SQLite que pode conter dados autoritativos;
- [ ] definir qual fonte vence em caso de duplicidade;
- [ ] inventariar diretórios de documentos, anexos, imagens e artefatos fora do
  banco;
- [ ] mapear usuário desktop para email/identidade Entra;
- [ ] registrar tamanho, schema e checksum de cada fonte;
- [ ] definir janela de congelamento necessária ao cutover.

Nenhum banco original deve ser aberto por uma versão que possa migrá-lo
automaticamente. Trabalhar somente com cópias verificadas.

### Preparar a origem

1. parar/esvaziar a fila de tarefas na cópia de ensaio;
2. copiar banco e diretórios associados;
3. calcular checksum;
4. executar migrations do código `Live` somente sobre a cópia;
5. verificar `PRAGMA integrity_check`;
6. guardar contagens e totais de negócio antes do ETL.

### Preparar o destino

- PostgreSQL vazio e descartável;
- schema criado por `python manage.py migrate`;
- backup/snapshot antes do ETL;
- função temporária com privilégio necessário;
- nenhuma conexão de usuário.

### Executar o ETL

Em ambiente seguro:

```bash
export DATABASE_URL='postgresql://...'
python scripts/etl_sqlite_to_postgres.py /caminho/da/copia/origem.db
```

Restrições:

- o script trunca tabelas do destino;
- o destino deve ser descartável ou formalmente aprovado como vazio;
- a URL não pode aparecer em logs/handoff;
- o privilégio elevado deve ser removido após o ensaio.

### Reconciliação

- [ ] `COUNT(*)` por tabela origem/destino.
- [ ] `schema_version` esperado.
- [ ] sequences acima do maior ID.
- [ ] FKs sem órfãos.
- [ ] organizações e usuários esperados.
- [ ] `owner_id` e compartilhamentos corretos.
- [ ] contagens de clientes, contas, atividades, compromissos e campanhas.
- [ ] jobs e envios agendados sem execução acidental.
- [ ] documentos/anexos copiados e amostrados por checksum.
- [ ] datas, timezones e valores monetários amostrados.
- [ ] dados pessoais ausentes dos relatórios compartilhados.
- [ ] login dos usuários de teste encontra somente dados autorizados.

### Teste de repetição

Descartar o PostgreSQL de ensaio, recriar do zero e repetir o procedimento.
O resultado deve ser determinístico. Não testar repetição sobre destino já
preenchido.

### Artefatos

- `docs/go-live/inventario-migracao-dados.md`
- `docs/go-live/relatorio-ensaio-etl.md`
- script/consulta de reconciliação sem valores pessoais
- procedimento de congelamento e duração medida

### Critérios de aceite

- Duas execuções limpas produzem resultados reconciliados.
- Arquivos e banco foram cobertos.
- Tempo de cutover foi medido.
- Privilégio temporário do ETL foi removido.
- Originais permanecem intactos.

### Condições de parada

- Divergência de contagem sem explicação aprovada.
- Origem desconhecida ou múltiplas fontes sem regra de precedência.
- Arquivos fora do banco sem plano de cópia.
- Fornecedor não permite o ETL e ainda não existe implementação alternativa.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G6.
Use o ambiente candidato e dados de teste/migrados autorizados. Monte uma
matriz E2E com admin e usuário comum; valide SSO, sessão multiworker, ACL,
Graph, WAHA, jobs, documentos, Companion, backup/restore, observabilidade,
rollback e regressão desktop/updater. Não altere branches nem domínio final.
Registre evidências sem dados sensíveis e trate qualquer falha como bloqueante
até correção e novo teste.
```

---

## Fase G6 — executar E2E online

### Objetivo

Validar o produto no ambiente online realista antes de qualquer mudança de
branch principal, updater, domínio final ou tráfego de usuários.

### Matriz de identidades

Usar ao menos:

- administrador autorizado;
- usuário comum proprietário de dados;
- usuário comum sem acesso aos dados do anterior;
- identidade negada/não allowlisted;
- mailbox e telefone de teste autorizados.

### Cenários obrigatórios

#### Identidade e sessão

- [ ] login Entra com PKCE;
- [ ] rejeição de identidade não permitida;
- [ ] logout;
- [ ] expiração e renovação;
- [ ] navegação entre requisições atendidas por workers diferentes;
- [ ] cookies Secure, HttpOnly e SameSite.

#### ACL e isolamento

- [ ] proprietário cria, lê, edita e exclui/arquiva;
- [ ] outro usuário não acessa registros sem compartilhamento;
- [ ] compartilhamento concede somente o acesso previsto;
- [ ] busca, dashboards, exports e anexos respeitam ACL;
- [ ] tarefas e históricos pessoais não vazam.

#### Outlook Graph

- [ ] conexão;
- [ ] renovação de token;
- [ ] leitura autorizada;
- [ ] envio de mensagem de teste aprovada;
- [ ] revogação/logout sem token em logs.

#### WAHA

- [ ] primeiro QR;
- [ ] estado conectado;
- [ ] envio e recebimento aprovados;
- [ ] webhook HMAC;
- [ ] atualização de contatos/conversas com LID e 9º dígito;
- [ ] restart sem novo QR;
- [ ] porta continua privada.

#### Jobs e múltiplos workers

- [ ] uma execução por ciclo;
- [ ] tarefas visíveis após troca de worker;
- [ ] envio concorrente não duplica;
- [ ] estado ambíguo exige revisão humana;
- [ ] endpoints administrativos mostram heartbeat e claims.

#### Dados e arquivos

- [ ] amostras reconciliadas da G5;
- [ ] upload/download;
- [ ] documentos e imagens existentes;
- [ ] exports;
- [ ] datas, timezone e valores.

#### Companion e desktop

- [ ] contrato do Companion;
- [ ] lease e idempotência;
- [ ] desktop atual em `main` continua inicializando e usando o updater;
- [ ] nenhuma mudança web é entregue acidentalmente aos desktops;
- [ ] caminhos de automação local continuam separados da imagem web.

#### Operação

- [ ] backup real do candidato;
- [ ] restore em banco descartável;
- [ ] rollback para a imagem anterior;
- [ ] roll-forward para a candidata;
- [ ] alertas de health, readiness, backup e WAHA;
- [ ] logs correlacionáveis por `request_id`.

### Teste de soak

Manter o candidato online pelo período decidido na G2, com monitoramento. O
soak deve incluir restart controlado de web e WAHA, troca de workers e ao menos
um ciclo de backup.

### Artefato

Criar `docs/go-live/matriz-e2e.md`:

| ID | Cenário | Usuário/dado de teste | Resultado | Evidência | Incidente |
|---|---|---|---|---|---|

Não incluir email real, telefone, token, mensagem ou conteúdo de documento.

### Critérios de aceite

- Todos os cenários críticos aprovados.
- Nenhum defeito P0/P1 aberto.
- Defeitos menores têm decisão explícita.
- Soak concluído sem degradação.
- Desktop/updater não foram afetados.

### Condições de parada

- Vazamento de dados/ACL.
- Duplicação de efeito externo.
- Perda de sessão WAHA.
- Restore ou rollback falhar.
- Updater desktop apontar para conteúdo de `Live`.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G7.
Não mude branches automaticamente. Consolide as evidências G1-G6, confirme os
oito gates externos e apresente uma decisão go/no-go. Analise separadamente:
(A) manter main como desktop e Live como web; (B) tornar Live default sem
misturar o updater; (C) reconciliar branches com plano específico. Aponte o
risco de cada alternativa. Só altere default branch, proteção ou updater com
aprovação explícita do usuário após o E2E.
```

---

## Fase G7 — decisão de go-live e estratégia de branches

### Objetivo

Tomar a decisão que o usuário reservou para depois do ambiente online e do E2E.
Esta é a primeira fase em que uma mudança de branch principal pode ser
considerada.

### Pré-condições

- G1 a G6 concluídas.
- Matriz E2E aprovada.
- Oito gates externos fechados.
- Imagem/digest candidato e rollback identificados.
- Janela, responsáveis e comunicação aprovados.

### Gate de go/no-go

Responder formalmente:

- [ ] há algum defeito P0/P1?
- [ ] restore e rollback funcionam?
- [ ] os dados reconciliam?
- [ ] SSO, Graph e WAHA funcionam com contas autorizadas?
- [ ] alertas têm responsável?
- [ ] desktop e updater estão protegidos?
- [ ] existe capacidade de voltar ao desktop durante a janela?

Qualquer resposta negativa resulta em **no-go**.

### Alternativas de branch

#### Alternativa A — manter duas linhas explícitas

- `main`: desktop/update;
- `Live`: web/produção web;
- definir regras de PR e backport;
- opcionalmente manter `main` como default enquanto desktop for dominante.

É a alternativa de menor risco para o updater, mas exige disciplina de
backports.

#### Alternativa B — tornar `Live` a default branch

- não mesclar automaticamente em `main`;
- configurar PRs web para `Live`;
- preservar `main` como branch de manutenção desktop;
- auditar workflows, releases e updater para garantir que continuam lendo
  `main`.

Só é segura se nenhum fluxo desktop assumir que a default branch é a origem do
update.

#### Alternativa C — reconciliar `Live` e `main`

Exige plano específico, porque `main` alimenta clientes instalados. Antes:

- inventariar workflows, releases, instalador e manifestos de update;
- simular o que um merge distribuiria;
- classificar arquivos web-only e desktop;
- criar release canário do updater;
- testar upgrade e downgrade em máquina descartável.

Não usar merge direto como atalho.

### Decisão obrigatória

Registrar:

```text
GO ou NO-GO:
Estratégia de branches escolhida:
Impacto no updater:
Mudanças autorizadas:
Mudanças proibidas:
Responsável:
Janela:
Rollback:
```

### Critérios de aceite

- Aprovação explícita do usuário.
- Estratégia de branches e updater testada.
- Regras de proteção/base de PR documentadas.
- Nenhuma mudança implícita ou automática.

### Condições de parada

- E2E incompleto.
- Updater não inventariado.
- Não houver aprovação explícita.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e a decisão registrada na Fase G7.
Execute somente a Fase G8 e respeite exatamente a estratégia de branches
aprovada. Faça o cutover com a imagem/digest já testado, backup verificado,
congelamento das fontes desktop, ETL final em PostgreSQL vazio, reconciliação,
DNS/domínio final, smoke e monitoramento. Não introduza código novo na janela.
Em qualquer critério de rollback, pare e execute o runbook aprovado.
```

---

## Fase G8 — cutover produtivo

### Objetivo

Promover exatamente o artefato testado, migrar os dados finais e liberar o
acesso de forma reversível.

### Antes da janela

- [ ] comunicar usuários e responsáveis;
- [ ] congelar deploys;
- [ ] confirmar SHA e digest;
- [ ] confirmar imagem anterior;
- [ ] testar acesso operacional;
- [ ] confirmar backup externo recente;
- [ ] confirmar banco produtivo vazio/estado aprovado;
- [ ] confirmar DNS TTL reduzido conforme plano;
- [ ] abrir canal de incidente.

### Sequência

1. colocar fontes desktop em modo de congelamento conforme plano;
2. aguardar tarefas/envios em andamento ou classificá-los;
3. copiar banco(s) e arquivos finais;
4. calcular checksums;
5. executar migrations na cópia/fonte conforme procedimento aprovado;
6. executar ETL final no PostgreSQL produtivo vazio;
7. copiar arquivos e verificar checksums;
8. reconciliar contagens e amostras;
9. promover a imagem/digest testado;
10. executar migration one-shot;
11. subir a stack;
12. validar health/readiness;
13. alterar DNS/entrada final;
14. executar smoke de SSO, Graph, WAHA, ACL e Companion;
15. iniciar monitoramento intensivo.

Não incluir correções de código durante a janela. Defeito de código exige
rollback ou nova release completa.

### Critérios de rollback

- readiness indisponível além do limite aprovado;
- falha de login para usuários autorizados;
- divergência de dados;
- vazamento de ACL;
- duplicação de mensagem/envio;
- WAHA sem recuperação;
- taxa de erro/latência acima do limite;
- logs ou segredos expostos.

### Rollback

- reverter DNS/entrada conforme plano;
- promover imagem anterior somente se compatível com o schema;
- não desfazer migration automaticamente;
- manter fontes desktop congeladas até decidir qual lado contém dados
  autoritativos;
- se necessário, restaurar em banco novo;
- preservar logs/evidências e abrir incidente.

### Critérios de aceite

- Domínio final funcional.
- Dados reconciliados.
- Smokes reais aprovados.
- Alertas e dashboards normais.
- Responsável declara início da hypercare.

### Mensagem para o próximo chat

```text
Leia docs/plano-acao-pos-fase-8-go-live.md e execute somente a Fase G9.
Monitore a produção durante a hypercare aprovada, acompanhe health/readiness,
5xx, p95, PostgreSQL, backup, jobs e WAHA, valide restore periódico e registre
incidentes. Não desative imediatamente o desktop/updater nem apague fontes.
Proponha o encerramento apenas após estabilidade, aceite operacional e plano
de retenção/decomissionamento aprovado.
```

---

## Fase G9 — hypercare, transferência operacional e encerramento

### Objetivo

Confirmar estabilidade após o cutover e transferir o sistema para operação
rotineira sem perder o caminho de recuperação.

### Monitoramento

- [ ] `/healthz` e `/readyz`;
- [ ] taxa de 5xx;
- [ ] latência p95;
- [ ] conexões, CPU, memória e disco do PostgreSQL;
- [ ] idade e restore dos backups;
- [ ] heartbeat/claims dos jobs;
- [ ] conexão e webhook WAHA;
- [ ] erros de Graph;
- [ ] falhas de login;
- [ ] incidentes de ACL;
- [ ] volume de suporte dos usuários.

### Operação

- [ ] revisar alertas e ajustar limiares com evidência;
- [ ] executar restore em banco descartável;
- [ ] revisar claims ambíguas;
- [ ] rotacionar credenciais temporárias;
- [ ] remover privilégios temporários de ETL;
- [ ] confirmar contatos de incidente;
- [ ] treinar responsável nos runbooks.

### Desktop e updater

Não desativar automaticamente. Definir:

- período de convivência;
- mensagem/versão final para usuários desktop;
- política para dados produzidos após o cutover;
- suporte e rollback;
- retenção criptografada dos bancos originais;
- critérios de desinstalação/decomissionamento.

### Encerramento

- [ ] nenhuma falha crítica durante o período de hypercare;
- [ ] backup e restore comprovados;
- [ ] operação aceita pelo responsável;
- [ ] documentação atualizada;
- [ ] decisão sobre desktop/updater registrada;
- [ ] checklist de prontidão totalmente fechado.

### Próximo passo após G9

A Fase 9 continua separada. Antes de iniciá-la, abrir um novo documento de
decisão de produto para avaliar multi-org, isolamento entre organizações,
billing, onboarding, suporte e obrigações legais. Não reutilizar este plano
como autorização implícita.

### Mensagem para um futuro chat de Fase 9

```text
O go-live single-org foi concluído e a hypercare encerrada. Não implemente
Fase 9 ainda. Primeiro leia o roadmap vigente e produza uma decisão de produto
separada para multi-org/SaaS, billing e onboarding, com riscos de segurança,
isolamento de dados, operação, custos e critérios de aprovação. Só programe
após autorização explícita.
```

---

## 6. Mapeamento dos gates externos

| Gate | Fase que prepara | Fase que comprova |
|---|---|---|
| Host, firewall, DNS e certificado | G2/G3 | G4/G8 |
| PostgreSQL, criptografia, capacidade e HA | G2/G3 | G4/G5/G8 |
| Backup externo e alerta de atraso | G2/G3 | G4/G6/G9 |
| Entra login/logout/renovação | G2/G3 | G6/G8 |
| Outlook Graph | G2/G3 | G6/G8 |
| WAHA com telefone autorizado | G2/G3 | G6/G8 |
| Logs, métricas e alertas | G2/G3 | G4/G6/G9 |
| Dono operacional e janela de rollback | G2 | G7/G8/G9 |

## 7. Registro de execução

Adicionar uma linha após cada fase. Não incluir segredos ou dados pessoais.

| Fase | Status | Data | Branch/SHA | PR/evidência | Próxima ação |
|---|---|---|---|---|---|
| G0 | concluída | 29/07/2026 | `codex/plano-acao-go-live` | PR `#299`; contrato confirmado | executar G1 |
| G1 | pendente | — | — | — | portar PR `#251` para `Live` |
| G2 | pendente | — | — | — | decisões de infraestrutura |
| G3 | pendente | — | — | — | provisionar candidato |
| G4 | pendente | — | — | — | deploy online |
| G5 | pendente | — | — | — | ensaio de dados |
| G6 | pendente | — | — | — | E2E |
| G7 | pendente | — | — | — | go/no-go e branches |
| G8 | pendente | — | — | — | cutover |
| G9 | pendente | — | — | — | hypercare |
