# Documentação Funcional e Técnica
## Módulo: Report & Backup
## Funcionalidade: Importar/Exportar Banco

## 1) Objetivo
Substituir a nomenclatura da funcionalidade **"Backup do Banco de Dados"** para **"Importar/Exportar Banco"** no módulo **Report & Backup**, mantendo as ações de exportação e importação e adicionando governança na importação com análise de conflitos e revisão linha a linha.

Também incluir uma decisão explícita de estratégia de importação:
- **Substituir tudo** (com confirmação reforçada), ou
- **Fundir bancos** (merge assistido com comparação de semelhança).

---

## 2) Escopo Funcional

### 2.1. Alteração de nomenclatura
- Onde hoje aparece **"Backup do Banco de Dados"**, deverá aparecer **"Importar/Exportar Banco"**.
- O comportamento de exportação/importação continua disponível, apenas com novo rótulo funcional.

### 2.2. Novos comportamentos no fluxo de importação
Antes de persistir dados importados no banco, o sistema deverá executar duas etapas obrigatórias:

1. **Detecção de conflitos**
   - Comparar dados de entrada com dados já existentes.
   - Identificar possíveis conflitos por registro/campo (ex.: mesma chave de negócio com conteúdo divergente).
   - Exibir conflitos ao usuário para decisão individual por linha.

2. **Pré-visualização de alterações (diff de importação)**
   - Mostrar todas as alterações que serão aplicadas.
   - Evidenciar para cada item: valor atual x valor importado x status (novo, alterado, sem mudança, conflito).
   - Permitir decisão **um a um** (seguir/pular) antes da gravação final.

### 2.3. Escolha do modo de importação
Ao selecionar o arquivo, o sistema deve perguntar:
- **Deseja substituir tudo ou fundir os bancos?**

Regras:
- **Substituir tudo**: mantém o comportamento de restauração total, porém com confirmação dupla.
- **Fundir bancos**: não substitui o banco atual; executa reconciliação por semelhança para decidir inserções/atualizações.

---

## 3) Regras de Negócio

### 3.1. Classificação por linha importada
Cada linha importada deve receber um status:
- **NOVO**: não existe no banco.
- **SEM_ALTERACAO**: existe e não altera conteúdo relevante.
- **ALTERADO**: existe e há mudança sem conflito bloqueante.
- **CONFLITO**: existe e há divergência crítica que exige decisão explícita.

### 3.1.1. Chave de comparação para fusão (prioridade definida)
No modo **Fundir bancos**, a busca de similaridade deve seguir esta prioridade:
1. **Nome do Contato**
2. **Email**
3. **Telefone**

Observações:
- A comparação deve ser normalizada (trim, case-insensitive e limpeza de máscara de telefone).
- Se Nome coincidir, mas Email/Telefone divergirem, classificar como potencial conflito para confirmação do usuário.
- Se Email ou Telefone coincidirem, priorizar sugestão de merge no mesmo registro.

### 3.2. Política de decisão do usuário
Para cada linha com **ALTERADO** ou **CONFLITO**:
- **Importar linha**: aplica atualização/inserção.
- **Pular linha**: não aplica alteração.

Para linha **NOVO**:
- opção padrão sugerida: **Importar linha**.

Para linha **SEM_ALTERACAO**:
- opção padrão sugerida: **Pular linha** (sem efeito prático).

### 3.3. Integridade e atomicidade
- A aplicação deve validar estrutura do arquivo antes da etapa de revisão.
- A gravação deve ocorrer em transação.
- Em falha grave durante persistência, realizar rollback do lote pendente.

### 3.4. Regras específicas por modo
- **Substituir tudo**
  - Exigir confirmação textual do usuário (ex.: digitar `SUBSTITUIR`).
  - Criar backup pré-operação de banco e uploads.
  - Substituir base completa apenas após validação do arquivo.

- **Fundir bancos**
  - Nunca apagar banco atual.
  - Processar por lote com decisões do usuário e trilha de auditoria.
  - Aplicar somente registros aprovados (insert/update), mantendo os demais intactos.

---

## 4) Fluxo Funcional Proposto (UX)

1. Usuário acessa **Report & Backup > Importar/Exportar Banco**.
2. Usuário seleciona arquivo de importação.
3. Sistema pergunta o modo: **Substituir tudo** ou **Fundir bancos**.
4. Sistema valida arquivo (formato, schema mínimo, tabelas suportadas).
5. Se **Fundir bancos**, sistema executa comparação com base atual usando prioridade **Nome > Email > Telefone**.
6. Sistema abre tela de revisão com:
   - resumo geral (totais por status),
   - lista linha a linha,
   - destaque de campos alterados,
   - ação por linha (**Importar** / **Pular**).
7. Usuário confirma decisões.
8. Sistema persiste conforme o modo escolhido.
9. Sistema exibe resultado final (importadas, puladas, erros).

---

## 5) Critérios de Aceite

1. O título funcional no módulo deve exibir **Importar/Exportar Banco**.
2. Importação deve solicitar modo: **Substituir tudo** ou **Fundir bancos**.
3. No modo **Fundir bancos**, não pode gravar dados sem passar por comparação prévia.
4. No modo **Fundir bancos**, conflitos devem ser listados antes da gravação.
5. Usuário deve conseguir decidir linha a linha no modo **Fundir bancos**.
6. Deve haver visualização clara do "antes x depois" por registro.
7. Resultado final da importação deve informar quantitativos por status.
8. No modo **Fundir bancos**, matching deve seguir prioridade: **Nome do Contato > Email > Telefone**.

---

## 6) Especificação Técnica

### 6.1. Camadas impactadas
- **Frontend (SPA / `public/index.html`)**
  - ajuste de rótulos e textos da seção,
  - modal inicial para escolha do modo de importação,
  - inclusão de modal/etapa de revisão com grid de comparação,
  - ações por linha (importar/pular),
  - envio de payload com decisões do usuário.

- **Backend (Flask / `app.py`)**
  - endpoint de **pré-validação e comparação** (não persistente),
  - endpoint de **confirmação da importação** (persistente),
  - suporte aos dois modos: `replace_all` e `merge`,
  - rotina de classificação por status,
  - transação e rollback.

### 6.2. Contrato sugerido de API

#### `POST /api/database/import/preview`
Entrada:
- arquivo de importação (multipart)
- `mode`: `replace_all` | `merge`

Saída (exemplo):
- `summary`: `{ novo, sem_alteracao, alterado, conflito }`
- `rows`: lista com:
  - `row_id` (identificador temporário)
  - `entity/table`
  - `key` (chave lógica)
  - `status`
  - `diff`: campos com `{ field, current_value, incoming_value }`
  - `default_action` (`import` ou `skip`)
  - `match_basis` (`name` | `email` | `phone` | `none`)

#### `POST /api/database/import/commit`
Entrada:
- `import_session_id` (ou hash do preview)
- `mode`: `replace_all` | `merge`
- decisões por linha: `[{ row_id, action }]`

Saída:
- `result`: `{ imported, skipped, failed }`
- `errors`: lista opcional por linha

### 6.3. Estratégia de comparação (resumo)
1. Normalizar dados de entrada (tipos, trim, datas).
2. No modo `merge`, tentar associação na ordem: **Nome do Contato -> Email -> Telefone**.
3. Buscar registro atual no banco.
4. Comparar campos relevantes.
5. Classificar status e montar diff.

### 6.4. Persistência
- No modo `merge`, executar commit apenas das linhas com `action=import`.
- No modo `replace_all`, substituir base inteira após confirmação reforçada.
- Ordem sugerida: tabelas-mãe antes de tabelas-filha.
- Registrar log de auditoria da importação (quem, quando, arquivo, totais, decisões).

### 6.5. Segurança e observabilidade
- Validar extensão e assinatura do arquivo.
- Limitar tamanho máximo de upload.
- Sanitizar conteúdo textual antes de persistir.
- Log estruturado com `import_session_id` para rastreabilidade.

---

## 7) Riscos e Mitigações
- **Risco:** excesso de decisões manuais em arquivos grandes.  
  **Mitigação:** filtros por status e ação em lote (ex.: "importar todos os NOVO").

- **Risco:** ambiguidade de chave de negócio.  
  **Mitigação:** explicitar chaves por entidade e bloquear commit sem chave válida.

- **Risco:** importação parcial inconsistente.  
  **Mitigação:** transação por lote e rollback em erro crítico.

---

## 8) Fora de Escopo (nesta solicitação)
- Mudança de layout ampla fora do módulo Report & Backup.
- Suporte a novos formatos de arquivo além dos já aceitos.
- Motor avançado de merge automático por prioridade de fonte.

---

## 9) Resumo Executivo
A funcionalidade passa a se chamar **Importar/Exportar Banco** e a importação passa a ter dois modos explícitos: **Substituir tudo** ou **Fundir bancos**. No modo de fusão, a comparação usa prioridade **Nome do Contato > Email > Telefone**, com revisão de conflitos e confirmação granular linha a linha, elevando segurança operacional, transparência e controle do usuário.
