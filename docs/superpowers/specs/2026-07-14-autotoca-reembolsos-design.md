# AutoToca — Submódulo "Reembolsos"

Data: 2026-07-14

## Objetivo

Novo submódulo dentro do AutoToca que lê comprovantes fiscais (foto/PDF) e
preenche automaticamente o portal de reembolsos da Stefanini
(`https://ereembolso.stefanini.com.br`), deixando o envio final para o
usuário revisar e confirmar — mesmo padrão de "robô visível" já usado no
Chamado Jurídico (`integrations/forms_robot.py`).

## Descoberta de campo real (inspeção ao vivo do portal)

O portal foi inspecionado ao vivo, logado na sessão do usuário via extensão
Chrome conectada (não Microsoft Forms — ASP.NET com campos próprios). Isso
corrigiu premissas do pedido original:

- **Não existem 3 páginas, existem 2.** `/Reembolso/Deslocamentos.aspx` é
  uma ÚNICA página com dois blocos: "Deslocamento com combustível e
  pedágio" (Origem/Destino/Data/Tipo de Transporte/Ida e volta — Km e Valor
  são calculados automaticamente pelo sistema) e, logo abaixo, "Outros
  deslocamentos" (Tipo do Deslocamento = Estacionamento / Pedágio / Táxi /
  Transporte público, com Quantidade/Período/Valor Total/Comprovante(s)/
  Descrição). **Estacionamento é preenchido nessa mesma página**, não em
  `default.aspx`.
- `/Reembolso/OutrasDespesas.aspx` é a página do Almoço com Cliente. O
  campo "Tipo de Despesa" tem a opção exata `Gasto com cliente`
  (`value="MKT;HAPPY;False"`).
- Não foi localizado um checkbox "possui pedágio" dentro do bloco de KM —
  o pedágio parece ser uma segunda entrada no widget "Outros
  deslocamentos" (Tipo = Pedágio), usando os mesmos campos
  Quantidade/Período/Valor/Comprovante(s)/Descrição descritos no pedido
  original. **Isso precisa de confirmação ao vivo na primeira execução
  real do robô** — ver seção "Itens a confirmar ao vivo".
- Célula Custo / Cliente / Serviço são combos (aparentam ser Select2) no
  topo de ambas as páginas, com Célula Custo tendo uma lista extensa (~300
  opções) e Cliente/Serviço aparentando depender da Célula Custo
  selecionada (cascata) — a confirmar ao vivo.
- Em `OutrasDespesas.aspx`, "Tipo de Despesa" e "Quantidade" são
  `<select>` nativos (não Select2); "Período" tem dois campos de data.

Decisão do usuário: mesmo sendo tecnicamente o mesmo formulário/robô,
**Estacionamento continua modelado como parte do mesmo fluxo no Toca**,
sob o nome **"Deslocamento & Estacionamento"**.

## Fluxos no Toca

### 1. Deslocamento & Estacionamento

Tela única no submódulo Reembolsos com um seletor de tipo de gasto dentro
do próprio fluxo:

**Campos comuns** (preenchidos pelo usuário, sempre presentes):
- Célula custo (texto livre digitado pelo usuário)
- Descrição da Despesa (texto livre)

**Campos fixos** (preenchidos automaticamente, não editáveis pelo
usuário — igual ao "Empresa do Grupo Stefanini" do Chamado Jurídico):
- Cliente = `Stefanini - Sao Paulo`
- Serviço = `Prospecção`

**Sub-fluxo "Deslocamento" (KM):**
- Origem: campo com dropdown de histórico (tabela nova
  `reembolso_origem_historico`, ver seção Dados) + opção "outro" para
  digitar um endereço novo
- Destino: dropdown "Contas" (reaproveita a tabela `accounts` existente,
  com opção "OUTRO" para digitar um nome não cadastrado — mesmo padrão de
  `GET /api/autotoca/accounts`), com endereço vindo de
  `account_reembolso_enderecos` se já existir, editável, e com botão "✦
  Buscar endereço com IA" (`_llm_prompt(..., web=True)`) quando não há
  endereço salvo
- Data do Deslocamento: upload obrigatório de 1 comprovante (recibo de
  combustível, app de mobilidade etc.) — a data é extraída via IA de
  visão; a data extraída é editável pelo usuário antes de enviar
- Tipo de transporte: "Carro da Empresa ou Alugado" / "Carro Próprio"
  (mapeiam 1:1 para as opções reais do site, que também tem "Depreciação"
  e "Moto" — não usadas neste fluxo)
- Deslocamento ida e volta: checkbox
- Descrição do deslocamento: gerada automaticamente como `"Visita ao
  cliente <conta>, de <Origem> à <Destino>"` (não editável, igual ao
  pedido original)

**Pedágio (opcional dentro do sub-fluxo Deslocamento):**
- Campo "Caso tenha pedágio, subir comprovante" (upload múltiplo,
  opcional)
- Se houver anexo(s): valor somado via IA de visão por comprovante,
  descrição fixa `"Deslocamento para visitar cliente <conta>"`
- Se o robô encontrar o campo de pedágio aberto no site e o usuário não
  tiver anexado nada: gera um arquivo de imagem propositalmente
  corrompido (poucos bytes inválidos, extensão `.jpg`) e usa como anexo
  único, igual ao pedido original

**Sub-fluxo "Estacionamento":**
- Upload de comprovante(s) (obrigatório, 1 ou mais)
- Quantidade = número de arquivos anexados
- Período = menor e maior data extraídas dos comprovantes via IA de visão
- Valor Total = soma dos valores extraídos
- Descrição: texto livre do usuário

### 2. Almoço com Cliente

- Célula custo (texto livre)
- Cliente = `Stefanini - Sao Paulo` (fixo)
- Serviço = `Prospecção` (fixo)
- Descrição da Despesa (texto livre)
- Tipo de despesa = `Gasto com cliente` (fixo, mapeia para a opção real do
  site)
- Upload de comprovante(s) (obrigatório, 1 ou mais)
- Quantidade = número de arquivos anexados
- Período = menor e maior data extraídas via IA de visão
- Valor Total = soma dos valores extraídos via IA de visão
- Descrição (texto livre do usuário)

### Confirmação final (ambos os fluxos)

Igual ao Chamado Jurídico: o robô preenche tudo, deixa o navegador aberto,
pulsa visualmente o botão final e devolve o controle — nunca envia
sozinho. Barra de progresso obrigatória com o coelho verde correndo
(`/images/coelho-correndo.webp` + classe `.coelho-run`), polling
assíncrono a cada 800ms.

## Extração por IA dos comprovantes

Segue o padrão já usado em `_portfolio_generate_offer_from_llm`: quando há
imagem, **OpenRouter com `image_url` em base64 primeiro** (o template SAI
de prompt simples só aceita texto puro, não é uma inversão da regra do
CLAUDE.md — é a mesma exceção documentada e já usada no Portfolio).
Fallback: se OpenRouter não estiver configurado, tenta SAI só com o texto
(sem OCR de imagem, resposta necessariamente pior).

Prompt por comprovante extrai um JSON `{"data": "YYYY-MM-DD", "valor":
123.45}`. Para múltiplos comprovantes (Pedágio, Estacionamento, Almoço), a
chamada é feita **um arquivo por vez** e a soma/min/max é calculada em
código Python — não se pede ao LLM para somar vários arquivos numa única
chamada (menos confiável).

## Dados novos

```sql
CREATE TABLE reembolso_origem_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texto TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE account_reembolso_enderecos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    endereco TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    UNIQUE(account_id)
);

CREATE TABLE reembolsos_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,               -- 'deslocamento' | 'almoco'
    payload_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

`account_reembolso_enderecos` é `UPSERT` (um endereço por conta, editável)
— gravado somente quando o usuário efetivamente envia o formulário
(robô concluído ou clique manual confirmado), nunca antes, para não
poluir o histórico com tentativas abandonadas. O mesmo vale para
`reembolso_origem_historico`: só grava ao enviar.

## Backend

Mesmo padrão de `routes/autotoca.py` / Chamado Jurídico:
- `_reembolso_tasks` / `_reembolso_task_set/get/cleanup` (dict +
  threading.Lock, igual a `_forms_robot_tasks`)
- Upload por campo em
  `uploads/autotoca/reembolsos/<history_id>/<campo>/`
- `POST /api/autotoca/reembolsos/deslocamento/robot` e
  `POST /api/autotoca/reembolsos/almoco/robot` → cria linha em
  `reembolsos_history`, salva arquivos, dispara thread, retorna
  `task_id` (202)
- `GET /api/autotoca/reembolsos/<tipo>/robot/tasks/<task_id>` → polling
- `GET /api/autotoca/reembolsos/origem-historico` → lista para dropdown
- `GET /api/autotoca/reembolsos/conta-endereco/<account_id>` → endereço
  salvo, se houver
- `POST /api/autotoca/reembolsos/extract` → recebe 1 arquivo, retorna
  `{data, valor}` via IA de visão (usado pelo frontend para pré-preencher
  antes do envio, editável pelo usuário)

## Robô (`integrations/reembolso_robot.py`, novo módulo)

Reaproveita de `forms_robot.py`: perfil persistente
(`_profile_dir`/`_launch_context`/detecção de navegador padrão), overlay
de cursor animado + badge, lock de execução única
(`_ROBOT_LOCK`)em novo módulo próprio. **Não reaproveita** o matching por
texto de pergunta do Forms (`_MATCH_JS`/`QUESTION_SELECTOR`) porque o
e-Reembolso não tem essa estrutura de "perguntas" — em vez disso, os
campos são localizados por **label visível mais próxima + fallback de
posição/id**, documentando cada seletor tentado (mesmo princípio do
Chamado Jurídico: texto primeiro, fallback posicional reportado
separadamente ao usuário).

Fluxo `Deslocamento & Estacionamento`:
1. Abrir `/Reembolso/Deslocamentos.aspx`
2. Preencher Célula Custo → aguardar Cliente popular (cascata, a
   confirmar) → Cliente → Serviço → Descrição da Despesa
3. Se sub-fluxo Deslocamento: preencher bloco de KM (Origem/Destino/
   Data/Tipo/Ida-volta/Descrição) → clicar "adicionar" → se houver
   pedágio, preencher bloco "Outros deslocamentos" com Tipo=Pedágio →
   "adicionar"
4. Se sub-fluxo Estacionamento: preencher bloco "Outros deslocamentos"
   com Tipo=Estacionamento diretamente → "adicionar"
5. Pulsar botão final, aguardar revisão do usuário

Fluxo `Almoço com Cliente`:
1. Abrir `/Reembolso/OutrasDespesas.aspx`
2. Preencher campos comuns + Tipo de Despesa=Gasto com cliente +
   Quantidade/Período/Valor/Comprovantes/Descrição
3. Pulsar botão final, aguardar revisão do usuário

## Itens a confirmar ao vivo na primeira execução real

Documentados aqui para não serem esquecidos — não são bloqueadores do
plano de implementação, mas vão exigir 1-2 rodadas de ajuste junto com o
usuário rodando o robô de verdade, seguindo a mesma estratégia usada no
Chamado Jurídico ("teste contra uma réplica local, ajuste ao vivo depois"):

1. Cliente/Serviço dependem de Célula Custo selecionada (cascata)? Em
   caso positivo, o robô precisa esperar o postback/carregamento antes de
   tentar selecionar Cliente.
2. Como o campo de pedágio realmente se comporta: é sempre uma segunda
   entrada manual em "Outros deslocamentos", ou o sistema abre campos
   extra automaticamente ao detectar pedágio na rota calculada entre
   Origem e Destino?
3. Confirmar os seletores exatos (id/name) de cada combo Select2 (Célula
   Custo, Cliente, Serviço, Tipo do Transporte, Tipo do Deslocamento) —
   inspecionados visualmente mas não capturados via DOM completo.
4. Confirmar que "Km Rodado" e "Valor Total em R$" do bloco de KM são
   preenchidos automaticamente pelo sistema (parecem campos calculados/
   somente leitura) e não precisam ser preenchidos pelo robô.

## Fora de escopo

- Reembolso Certificação, Adiantamento e Painel Gerente (menus vistos no
  portal mas não pedidos)
- Qualquer submissão automática sem revisão humana
