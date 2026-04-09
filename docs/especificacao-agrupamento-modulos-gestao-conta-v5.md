# Especificação Funcional e Técnica — Agrupamento de Módulos em “Gestão de Conta” (base código version5)

## 1) Contexto e objetivo

## 1.1 Contexto atual observado no código
Atualmente, os módulos abaixo aparecem como entradas independentes na barra lateral esquerda:

- **Mapeamento de Ambiente** (`tab: mapeamento`)
- **Mapeamento Organizacional** (`tab: mapeamento-organizacional`)
- **Gestão de Conta** (`tab: gestao-conta`)

Além disso, o sistema já possui um padrão de módulo “mãe” com funções internas em botões, exemplificado em **AutoToca** (`tab: autotoca`), que exibe botões para alternar entre automações internas (ex.: Chamado Jurídico e Preparar Reunião).

## 1.2 Objetivo da solicitação
Consolidar os módulos:

1. Mapeamento de Ambiente
2. Mapeamento Organizacional
3. Gestão de Conta

em um único módulo mãe chamado **Gestão de Conta**, com navegação interna por botões (padrão semelhante ao AutoToca), **sem alterar regras funcionais existentes** dos três módulos.

## 1.3 Premissas mandatórias
- Não alterar contratos de API existentes.
- Não alterar semântica de dados, validações e comportamento de negócio já vigente.
- Preservar integrações indiretas com outros módulos (Clientes, Atividades, Agenda, Sugestões, Kanban, etc.).
- Evitar que links/calls legadas que ainda referenciam tabs antigas quebrem o fluxo.

---

## 2) Escopo

## 2.1 Em escopo
- Reorganização de **navegação e composição de UI** dos três módulos citados.
- Definição de novo **container funcional “Gestão de Conta (mãe)”**.
- Definição de **submódulos internos**:
  - Visão de Contas (atual Gestão de Conta)
  - Mapeamento de Ambiente
  - Mapeamento Organizacional
- Compatibilização de chamadas internas para não romper fluxos existentes.
- Plano de regressão abrangente.

## 2.2 Fora de escopo
- Mudanças de regra de negócio de cadastro/edição/exclusão.
- Mudanças de schema de banco.
- Refatoração de endpoints backend além do necessário para compatibilidade de navegação.
- Redesign visual amplo fora do agrupamento.

---

## 3) Diagnóstico técnico do estado atual (AS-IS)

## 3.1 Navegação e tabs
Hoje cada módulo é uma tab independente com ativação via `switchTab`:

- `switchTab(..., 'mapeamento')` → `loadMapeamento()`
- `switchTab(..., 'mapeamento-organizacional')` → `loadOrganizationalMapping()`
- `switchTab(..., 'gestao-conta')` → `loadAccounts()`

## 3.2 Funcionalidades de Mapeamento de Ambiente (AS-IS)
- Carrega cards de ambiente por `GET /api/environment/cards`.
- Carrega empresas/clientes por `GET /api/empresas` + `GET /api/clientes`.
- Exibe respostas por empresa selecionada via `GET /api/environment/responses?client_id=...`.
- Permite CRUD de cards (`POST/PUT/DELETE /api/environment/cards`), salvar resposta (`POST /api/environment/responses`) e abrir modal com respostas consolidadas (`GET /api/environment/card/{id}/all-responses`).
- Possui integração com AutoMapping (histórico e execução) e pontos de recarga de tela após operações.

## 3.3 Funcionalidades de Mapeamento Organizacional (AS-IS)
- Carrega dados com `GET /api/clientes` + `GET /api/accounts`.
- Cruza dados por empresa (normalização por nome) para compor tabela empresa × cargo.
- Permite abrir ficha do contato e criar contato no contexto do “+” da grade.
- Exporta visão para planilha (fluxo front-end com modal e geração de arquivo).

## 3.4 Funcionalidades de Gestão de Conta (AS-IS)
- Lista contas por `GET /api/accounts`.
- Detalha conta por `GET /api/accounts/{id}`.
- Cria/edita conta por `POST/PUT /api/accounts`.
- Gerencia presenças por `POST/PUT/DELETE /api/accounts/{id}/presences...`.
- Gerencia atividades de conta por `GET/POST/DELETE /api/accounts/{id}/activities...`.
- Usa dados de suporte por `GET /api/accounts/support-data`.

## 3.5 Dependências cruzadas relevantes
- **Clientes (`/api/clientes`)** alimenta tanto Mapeamento de Ambiente quanto Organizacional e também composição de contatos em Gestão de Conta.
- **Contas (`/api/accounts`)** alimenta Gestão de Conta e também prioridade/ordenação/branding no Organizacional.
- **Sincronização implícita contas↔clientes** no backend (`sync_accounts_from_clients`) impacta diretamente as três frentes ao mesmo tempo.
- Há chamadas legadas explícitas para `switchTab(null, 'mapeamento')` em fluxos de sugestões; remoção abrupta da tab antiga pode quebrar navegação contextual.

---

## 4) Arquitetura funcional proposta (TO-BE)

## 4.1 Modelo de navegação
### 4.1.1 Sidebar (nível 1)
- Manter **apenas um item** na barra lateral para este domínio: **Gestão de Conta**.
- Remover da barra lateral as entradas independentes:
  - Mapeamento de Ambiente
  - Mapeamento Organizacional

### 4.1.2 Navegação interna (nível 2)
Dentro da tab `gestao-conta`, criar barra de botões internos (estilo AutoToca):

- **Contas** (default)
- **Mapeamento de Ambiente**
- **Mapeamento Organizacional**

Cada botão ativa uma sub-view com show/hide de container específico, sem perda de estado desnecessária.

## 4.2 Requisito de não regressão funcional
Cada submódulo deve reutilizar as mesmas funções atuais (`loadAccounts`, `loadMapeamento`, `loadOrganizationalMapping` e respectivos handlers), evitando retrabalho e minimizando risco de regressão.

## 4.3 Compatibilidade retroativa obrigatória
- Chamadas existentes que ainda executam `switchTab(null, 'mapeamento')` ou `switchTab(null, 'mapeamento-organizacional')` devem continuar funcionais por compatibilidade.
- Estratégia recomendada:
  - Redirecionar internamente tabs antigas para `gestao-conta` + submódulo correspondente.
  - Não expor tabs antigas na sidebar, mas manter aliases lógicos no roteamento front-end.

---

## 5) Especificação funcional detalhada

## 5.1 Experiência do usuário

### 5.1.1 Entrada no módulo
Ao clicar em **Gestão de Conta** na sidebar:
- abre tab mãe;
- submódulo padrão = **Contas**;
- executa `loadAccounts()`.

### 5.1.2 Alternância entre submódulos
- Botões internos mudam visual de ativo.
- Acionam loader correspondente:
  - Contas → `loadAccounts()`
  - Mapeamento de Ambiente → `loadMapeamento()`
  - Mapeamento Organizacional → `loadOrganizationalMapping()`
- Cada submódulo mantém suas ações originais (botões, filtros, modais e exportações).

### 5.1.3 Persistência de contexto (desejável)
- Manter último submódulo aberto em memória local (`localStorage` ou estado em variável global) para melhorar continuidade.

## 5.2 Regras de negócio preservadas (sem alteração)

### 5.2.1 Mapeamento de Ambiente
- Limite de resposta (400 chars) permanece no backend.
- Critério de associação card↔cliente permanece idêntico.
- Fluxo de AutoMapping e histórico (20 dias) permanece.

### 5.2.2 Mapeamento Organizacional
- Lógica de ordenação por target e importância de cargo permanece.
- Lógica de botão “+” para cadastro contextual permanece.
- Exportação continua com as mesmas colunas e comportamento atual.

### 5.2.3 Gestão de Conta
- CRUD de contas, presenças e atividades sem alteração contratual.
- AutoFill e upload de logo sem alteração.
- Relação com contatos e principais pontos focais preservada.

---

## 6) Especificação técnica detalhada

## 6.1 Front-end (composição)

### 6.1.1 Estrutura de containers
Criar container da tab mãe com três painéis internos:
- `#gestaoContaSub_accounts`
- `#gestaoContaSub_environment`
- `#gestaoContaSub_org`

Obs.: IDs são referência de especificação; podem variar desde que mantenham legibilidade.

### 6.1.2 Controlador interno de submódulo
Criar função controladora (ex.: `switchGestaoContaSubmodule(subTab)`):
- remove classe active dos botões internos;
- aplica active no botão selecionado;
- esconde/mostra painel correspondente;
- dispara loader específico.

### 6.1.3 Reuso de funções existentes
- **Não duplicar** implementações de carregamento já consolidadas.
- Encapsular apenas a troca de contexto visual, chamando as mesmas funções operacionais.

### 6.1.4 Ajuste no `switchTab`
No dispatcher principal:
- `tabName === 'gestao-conta'` abre tab mãe e subtab padrão ou última subtab.
- `tabName === 'mapeamento'` e `tabName === 'mapeamento-organizacional'` passam a atuar como aliases de compatibilidade:
  - `gestao-conta + subtab ambiente`
  - `gestao-conta + subtab organizacional`

### 6.1.5 Gestão de estado e race conditions
- Garantir que chamadas assíncronas de loaders não sobrescrevam DOM oculto de outro submódulo de forma inválida.
- Recomendado: guarda de “submódulo ativo no momento da resposta” antes de render final para evitar render tardio em aba não ativa.

## 6.2 Backend (impacto esperado)

### 6.2.1 Endpoints
Nenhum endpoint precisa mudar. Todos continuam atendendo aos mesmos contratos:
- `/api/environment/*`
- `/api/clientes`, `/api/empresas`
- `/api/accounts*`
- `/api/automapping*`

### 6.2.2 Banco de dados
Nenhuma mudança de schema necessária.

### 6.2.3 Risco de backend
Baixo, desde que o front-end preserve payloads e sequência de chamadas.

---

## 7) Varredura completa de integração (impact analysis)

## 7.1 Matriz de dependências

| Domínio | Depende de | Tipo de dependência | Risco com agrupamento |
|---|---|---|---|
| Mapeamento Ambiente | clientes/empresas/environment | dados + UI | médio |
| Mapeamento Organizacional | clientes/accounts | dados + navegação para modal cliente | médio |
| Gestão de Conta | accounts + clients + activities | dados + relacionamento | médio |
| Sugestões diárias | navegação direta para `mapeamento` | roteamento | **alto** |
| Atividades/Agenda | dados de clients/accounts | indireto | baixo |

## 7.2 Pontos críticos identificados
1. **Chamadas legadas de navegação** para tabs antigas podem quebrar se tabs forem removidas sem alias.
2. **Renderização condicionada por IDs de containers**: mover HTML exige preservar IDs esperados por funções existentes.
3. **Ordem de carregamento assíncrono**: alternância rápida de subtabs pode deixar estado visual inconsistente sem guardas.
4. **Dependência de `sync_accounts_from_clients`**: qualquer quebra na leitura de contas reflete em dois submódulos simultaneamente.

## 7.3 Contramedidas obrigatórias
- Manter aliases no `switchTab`.
- Preservar IDs consumidos por loaders atuais (`accountsContent`, `mapeamentoContent`, `organizationalContent`, etc.) mesmo que reposicionados.
- Validar cenários de alternância rápida entre subtabs.
- Executar suíte de regressão funcional manual orientada por fluxo.

---

## 8) Requisitos não funcionais

## 8.1 Performance
- Agrupamento não deve aumentar latência perceptível de troca de módulos.
- Evitar recarregamentos desnecessários em alternância interna quando dados já estiverem em cache local (otimização opcional).

## 8.2 Usabilidade
- Clareza visual de qual submódulo está ativo.
- Acesso em no máximo 2 cliques para qualquer função antes disponível na sidebar.

## 8.3 Confiabilidade
- Não ocorrer perda de dados em formulários/modais durante alternância de submódulo.

---

## 9) Critérios de aceite (Definition of Done)

1. Sidebar exibe apenas **Gestão de Conta** para esse domínio consolidado.
2. Dentro de Gestão de Conta há botões internos para as 3 funcionalidades.
3. Todas as operações pré-existentes dos três módulos funcionam sem alteração de regra.
4. Chamadas de navegação legadas para `mapeamento` e `mapeamento-organizacional` continuam funcionando via redirecionamento interno.
5. Nenhum endpoint backend foi quebrado (status/payload esperados).
6. Fluxos de integração com clientes/contas/atividades/sugestões continuam íntegros.

---

## 10) Plano de testes de regressão (extremamente detalhado)

## 10.1 Bloco A — Navegação
- A1: abrir Gestão de Conta pela sidebar → subtab Contas ativa.
- A2: alternar para Mapeamento de Ambiente → tela e ações carregam.
- A3: alternar para Mapeamento Organizacional → grade renderiza.
- A4: voltar para Contas → lista de contas renderiza.
- A5: executar `switchTab(null, 'mapeamento')` por console/fluxo indireto → redireciona corretamente para Gestão de Conta/subtab Ambiente.
- A6: executar `switchTab(null, 'mapeamento-organizacional')` → redireciona para subtab Organizacional.

## 10.2 Bloco B — Mapeamento de Ambiente
- B1: listar cards.
- B2: criar card.
- B3: editar card.
- B4: excluir card.
- B5: selecionar cliente no filtro e validar resposta inline.
- B6: abrir modal de card sem cliente selecionado.
- B7: salvar resposta com <= 400 chars.
- B8: validar erro com > 400 chars.
- B9: abrir histórico AutoMapping (20 dias).

## 10.3 Bloco C — Mapeamento Organizacional
- C1: carregar tabela completa empresa × cargo.
- C2: validar priorização de contas target.
- C3: abrir perfil de contato pela célula ocupada.
- C4: usar botão “+” em célula vazia e abrir modal com empresa/cargo pré-preenchidos.
- C5: exportar com subset de colunas.
- C6: exportar com todas as colunas.

## 10.4 Bloco D — Gestão de Conta
- D1: listar contas.
- D2: abrir modal de nova conta.
- D3: salvar conta com dados obrigatórios.
- D4: editar conta existente.
- D5: usar AutoFill da conta.
- D6: cadastrar/editar/excluir presença.
- D7: registrar atividade de conta.
- D8: excluir atividade de conta.
- D9: validar vínculo de contatos principais.

## 10.5 Bloco E — Integrações cruzadas
- E1: criar novo cliente em contexto organizacional e verificar presença em Ambiente/Contas.
- E2: alterar nome de empresa em cliente e validar reflexo de sincronização de contas.
- E3: validar sugestão que redireciona para mapeamento (compatibilidade de alias).
- E4: validar que Kanban/Atividades continuam carregando sem regressão (sanidade geral).

## 10.6 Bloco F — Testes negativos
- F1: resposta 500 em `/api/environment/cards` mostra feedback e não quebra módulo mãe.
- F2: resposta 500 em `/api/accounts` não derruba subtabs irmãs.
- F3: ausência de dados (listas vazias) apresenta empty states corretos.

---

## 11) Riscos e mitigação

## 11.1 Riscos altos
- Quebra de fluxos que navegam por IDs antigos de tab.
- Quebra por alteração inadvertida de IDs de elementos usados em JS legado.

## 11.2 Mitigação
- Fase 1: introduzir módulo mãe + subtabs mantendo aliases.
- Fase 2: monitorar uso dos aliases por telemetria/log (se disponível).
- Fase 3: só depois considerar remoção técnica interna dos aliases.

---

## 12) Estratégia de rollout recomendada

1. **Feature flag interna** (opcional) para ativar novo agrupamento.
2. Homologação com massa real de dados.
3. Validação com usuários-chave (operações comerciais).
4. Publicação em produção.
5. Janela de observação com checklist de regressão rápida.

---

## 13) Plano de rollback

Se houver regressão crítica:
- Restaurar menu antigo com três entradas separadas.
- Manter código de subtabs isolado para reativação futura.
- Não há necessidade de rollback de banco (sem migração schema).

---

## 14) Entregáveis de documentação para execução

1. **Documento funcional** (este arquivo).
2. **Checklist de QA de regressão** (pode derivar da seção 10).
3. **Plano técnico de implementação em tarefas** (backlog sugerido):
   - T1: Estruturar subnavegação interna em Gestão de Conta.
   - T2: Reposicionar containers HTML mantendo IDs funcionais.
   - T3: Ajustar `switchTab` com aliases de compatibilidade.
   - T4: Ajustar estado visual e persistência de subtab.
   - T5: Executar regressão completa e corrigir desvios.

---

## 15) Conclusão técnica
A consolidação proposta é **viável com baixo impacto de backend** e **médio impacto de front-end**, desde que o trabalho seja orientado por compatibilidade e preservação de IDs/contratos. O maior risco não está em regra de negócio, mas em **roteamento/navegação legada** e em **integrações cruzadas que assumem tabs antigas**. Com alias de navegação, manutenção dos loaders atuais e regressão abrangente, a mudança pode ser aplicada sem quebra funcional.
