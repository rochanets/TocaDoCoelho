# iAta no AutoToca — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover o iAta do Portfolio para o AutoToca e trocar o formato da ata por uma estrutura hierárquica Gerente Comercial → Conta → Oportunidade, com continuidade entre atas, edição do texto e envio por e-mail.

**Architecture:** A extração da hierarquia é feita por IA (`_llm_prompt`, SAI → OpenRouter); a reconciliação com a ata anterior é feita em Python puro, para que a garantia "nada da ata anterior some" seja código e não promessa do modelo. A lógica pura (normalização, parsing, reconciliação, renderização) vive no pacote `integrations/iata/` (`reconcile.py`, `llm.py`, `render.py`, reexportados por `__init__.py` — ver "Estrutura de arquivos" abaixo), testável sem Flask e sem banco. A orquestração (thread, banco, rotas) vive em `routes/autotoca_iata.py`, que é executado no namespace do `app.py` por `_load_route_modules()` e portanto enxerga `get_db`, `logger`, `_llm_prompt` e `_outlook_send_mail`. Todo o resto do projeto continua importando `from integrations import iata as iata_lib` e chamando `iata_lib.reconcile`/`iata_lib.parse_hierarchy`/etc. num namespace só — dividir em pacote (Task 3) não muda esse contrato.

**Tech Stack:** Python 3 + Flask, SQLite (`get_db()`), pytest, JS vanilla no `public/js/`.

**Spec:** `docs/superpowers/specs/2026-08-04-iata-autotoca-design.md`

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `integrations/iata/` (criar, pacote — dividido a partir da Task 3) | Lógica pura: normalização, prompts, parsing do JSON da IA, reconciliação com a ata anterior, render markdown, render HTML de e-mail. Sem Flask, sem SQLite, sem chamadas de rede. `__init__.py` reexporta tudo, então `from integrations import iata as iata_lib` continua funcionando sem mudança em quem consome. Ver detalhe dos arquivos internos na Task 3. |
| `routes/autotoca_iata.py` (criar) | Rotas `/api/autotoca/iata*`, persistência da hierarquia, task assíncrona, envio de e-mail. |
| `public/js/autotoca-iata.js` (criar) | Painel, modal, visualização, edição e envio no frontend. |
| `tests/test_iata.py` (criar) | Testes da lógica pura + testes de rota. |
| `app.py` (modificar) | Migração 17, tabelas no `init_db`, `ROUTE_MODULES`, remoção dos helpers `_iata_*` antigos. |
| `routes/portfolio.py` (modificar) | Remoção das rotas `/api/portfolio/iata*`. |
| `public/index.html` (modificar) | Botão/painel no AutoToca; remoção da sub-aba do Portfolio; `<script>` novo. |
| `public/js/itoca-autotoca.js` (modificar) | Remoção do código iAta antigo. |
| `tests/test_schema_migrations.py` (modificar) | Registro das tabelas novas. |

**Ordem:** Tasks 1–5 são fundação testável sem UI. 6–10 são backend. 11–13 são frontend. 14 é limpeza. Cada task termina em commit.

---

### Task 1: Schema — migração 17 e tabelas no init_db

**Files:**
- Modify: `app.py:688` (bloco `iata_records` no `init_db`)
- Modify: `app.py:1222` (`SCHEMA_MIGRATIONS`, adicionar entrada 17 ao final da lista)
- Test: `tests/test_iata.py` (criar)

O `.db` do usuário tem duas linhagens: bancos novos nascem pelo `init_db`, bancos existentes só recebem o que estiver em `SCHEMA_MIGRATIONS`. O DDL precisa estar nos dois lugares ou bases antigas sobem sem as tabelas.

- [ ] **Step 1: Write the failing test**

Criar `tests/test_iata.py`:

```python
# -*- coding: utf-8 -*-
import sqlite3

import app as toca


def _cols(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    finally:
        conn.close()


def test_migracao_cria_tabelas_da_hierarquia(db_path):
    conn = sqlite3.connect(db_path)
    try:
        tabelas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {'iata_managers', 'iata_accounts', 'iata_opportunities'} <= tabelas


def test_migracao_adiciona_colunas_em_iata_records(db_path):
    cols = _cols(db_path, 'iata_records')
    assert {'previous_record_id', 'body_markdown', 'body_edited',
            'reparse_failed', 'format_version'} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -v`
Expected: FAIL — as duas asserções falham (tabelas e colunas não existem).

- [ ] **Step 3: Adicionar o DDL ao init_db**

Em `app.py`, logo depois do bloco `CREATE TABLE IF NOT EXISTS iata_records (...)` (`app.py:688`), inserir:

```python
    c.execute('''CREATE TABLE IF NOT EXISTS iata_managers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        display_order INTEGER DEFAULT 0,
        FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS iata_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        manager_id INTEGER NOT NULL,
        account_id INTEGER,
        name TEXT NOT NULL,
        name_norm TEXT NOT NULL,
        match_confidence TEXT,
        match_confirmed INTEGER DEFAULT 0,
        display_order INTEGER DEFAULT 0,
        FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
        FOREIGN KEY(manager_id) REFERENCES iata_managers(id) ON DELETE CASCADE,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS iata_opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_id INTEGER NOT NULL,
        iata_account_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        name_norm TEXT NOT NULL,
        previous_status TEXT,
        update_text TEXT,
        responsible TEXT,
        carried_over INTEGER DEFAULT 0,
        prev_opportunity_id INTEGER,
        display_order INTEGER DEFAULT 0,
        FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
        FOREIGN KEY(iata_account_id) REFERENCES iata_accounts(id) ON DELETE CASCADE,
        FOREIGN KEY(prev_opportunity_id) REFERENCES iata_opportunities(id) ON DELETE SET NULL
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_iata_acc_record ON iata_accounts(record_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_iata_opp_record ON iata_opportunities(record_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_iata_opp_prev ON iata_opportunities(prev_opportunity_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_iata_opp_norm ON iata_opportunities(name_norm)')

    for _col, _ddl in (
        ('previous_record_id', 'INTEGER'),
        ('body_markdown', 'TEXT'),
        ('body_edited', 'INTEGER DEFAULT 0'),
        ('reparse_failed', 'INTEGER DEFAULT 0'),
        ('format_version', 'INTEGER DEFAULT 1'),
    ):
        try:
            c.execute(f'ALTER TABLE iata_records ADD COLUMN {_col} {_ddl}')
        except sqlite3.OperationalError:
            pass  # coluna já existe
```

`format_version` nasce como 1 (default do banco) para que atas antigas continuem no renderizador antigo; a ata nova grava 2 explicitamente na inserção.

- [ ] **Step 4: Adicionar a migração 17**

No fim da lista `SCHEMA_MIGRATIONS` (`app.py:1222`), depois da entrada `(16, 'feedback', [...])`, acrescentar:

```python
    (17, 'iata_hierarquia', [
        '''CREATE TABLE IF NOT EXISTS iata_managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE
        )''',
        '''CREATE TABLE IF NOT EXISTS iata_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            manager_id INTEGER NOT NULL,
            account_id INTEGER,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            match_confidence TEXT,
            match_confirmed INTEGER DEFAULT 0,
            display_order INTEGER DEFAULT 0,
            FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
            FOREIGN KEY(manager_id) REFERENCES iata_managers(id) ON DELETE CASCADE,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
        )''',
        '''CREATE TABLE IF NOT EXISTS iata_opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            iata_account_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            name_norm TEXT NOT NULL,
            previous_status TEXT,
            update_text TEXT,
            responsible TEXT,
            carried_over INTEGER DEFAULT 0,
            prev_opportunity_id INTEGER,
            display_order INTEGER DEFAULT 0,
            FOREIGN KEY(record_id) REFERENCES iata_records(id) ON DELETE CASCADE,
            FOREIGN KEY(iata_account_id) REFERENCES iata_accounts(id) ON DELETE CASCADE,
            FOREIGN KEY(prev_opportunity_id) REFERENCES iata_opportunities(id) ON DELETE SET NULL
        )''',
        'CREATE INDEX IF NOT EXISTS idx_iata_acc_record ON iata_accounts(record_id)',
        'CREATE INDEX IF NOT EXISTS idx_iata_opp_record ON iata_opportunities(record_id)',
        'CREATE INDEX IF NOT EXISTS idx_iata_opp_prev ON iata_opportunities(prev_opportunity_id)',
        'CREATE INDEX IF NOT EXISTS idx_iata_opp_norm ON iata_opportunities(name_norm)',
        _iata_add_record_columns,
    ]),
```

`ALTER TABLE ADD COLUMN` não tem `IF NOT EXISTS` no SQLite, então a adição de colunas entra como callable. Definir a função **antes** da lista `SCHEMA_MIGRATIONS` (logo acima da linha `SCHEMA_MIGRATIONS = [`, `app.py:1222`):

```python
def _iata_add_record_columns(conn):
    """Colunas novas de iata_records (ALTER TABLE não aceita IF NOT EXISTS)."""
    c = conn.cursor()
    existentes = {r[1] for r in c.execute('PRAGMA table_info(iata_records)')}
    for col, ddl in (
        ('previous_record_id', 'INTEGER'),
        ('body_markdown', 'TEXT'),
        ('body_edited', 'INTEGER DEFAULT 0'),
        ('reparse_failed', 'INTEGER DEFAULT 0'),
        ('format_version', 'INTEGER DEFAULT 1'),
    ):
        if col not in existentes:
            c.execute(f'ALTER TABLE iata_records ADD COLUMN {col} {ddl}')
```

Antes de escrever, ler `_run_schema_migrations` (`app.py:1416`) e confirmar como itens callable dentro da lista de statements são tratados. Se o executor só aceitar strings, adaptar: aplicar o mesmo padrão já usado por outra migração que precise de lógica (procurar por `callable(` no executor). Se nenhum padrão existir, estender o executor com duas linhas:

```python
                for stmt in (statements or []):
                    if callable(stmt):
                        stmt(conn)
                    else:
                        c.execute(stmt)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS (2 testes).

- [ ] **Step 6: Registrar as tabelas no guard de migrações**

`tests/test_schema_migrations.py` tem um teste que exige que toda tabela nova esteja nas migrações numeradas. Rodar a suíte inteira:

Run: `python -m pytest tests/test_schema_migrations.py -v`
Expected: PASS. Se falhar por "tabela criada no init_db sem migração", o problema é a entrada 17 — as três tabelas precisam constar tanto no `init_db` quanto na migração, e é exatamente isso que o teste verifica.

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_iata.py && git commit -m "feat(iata): schema da hierarquia gerente/conta/oportunidade"
```

---

### Task 2: Normalização e reconciliação com a ata anterior

**Files:**
- Create: `integrations/iata.py`
- Test: `tests/test_iata.py`

Esta é a peça central do desenho: garante que oportunidade da ata anterior não some.

Formato canônico da hierarquia usado em todo o módulo:

```python
{
  'header': {'title': str, 'meeting_date': str|None, 'meeting_time': str|None,
             'topic': str, 'participants': [{'name': str, 'role': str}]},
  'managers': [
    {'name': str,
     'accounts': [
       {'name': str, 'account_id': int|None, 'match_confidence': str|None,
        'opportunities': [
          {'name': str, 'update_text': str, 'responsible': str,
           'previous_status': str|None, 'carried_over': bool,
           'prev_opportunity_id': int|None}
        ]}
     ]}
  ]
}
```

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/test_iata.py`:

```python
from integrations import iata as iata_lib


def test_normalize_name_remove_acento_caixa_e_pontuacao():
    assert iata_lib.normalize_name('Comercial - Pedroso') == 'comercial pedroso'
    assert iata_lib.normalize_name('Migração  S/4HANA') == iata_lib.normalize_name('migracao s 4hana')
    assert iata_lib.normalize_name(None) == ''


def _hierarquia(opps):
    return [{'name': 'Ana', 'accounts': [
        {'name': 'Ambev', 'opportunities': opps}]}]


def test_reconcile_carrega_status_anterior_em_oportunidade_repetida():
    anterior = _hierarquia([{'id': 7, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}])
    atual = _hierarquia([{'name': 'migracao sap', 'update_text': 'Cliente pediu desconto',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['previous_status'] == 'Proposta enviada'
    assert opp['update_text'] == 'Cliente pediu desconto'
    assert opp['prev_opportunity_id'] == 7
    assert opp['carried_over'] is False


def test_reconcile_traz_oportunidade_ausente_como_sem_update():
    anterior = _hierarquia([
        {'id': 7, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'},
        {'id': 8, 'name': 'Observabilidade', 'update_text': 'Aguardando budget'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    nomes = [o['name'] for o in result[0]['accounts'][0]['opportunities']]
    assert 'Observabilidade' in nomes
    ausente = [o for o in result[0]['accounts'][0]['opportunities']
               if o['name'] == 'Observabilidade'][0]
    assert ausente['carried_over'] is True
    assert ausente['previous_status'] == 'Aguardando budget'
    assert ausente['update_text'] == iata_lib.SEM_UPDATE
    assert ausente['prev_opportunity_id'] == 8


def test_reconcile_traz_conta_inteira_ausente_na_reuniao_nova():
    anterior = [{'name': 'Ana', 'accounts': [
        {'name': 'Vale', 'opportunities': [
            {'id': 9, 'name': 'Data Lake', 'update_text': 'POC em andamento'}]}]}]
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    contas = {a['name'] for m in result for a in m['accounts']}
    assert 'Vale' in contas
    vale = [a for m in result for a in m['accounts'] if a['name'] == 'Vale'][0]
    assert vale['opportunities'][0]['update_text'] == iata_lib.SEM_UPDATE


def test_reconcile_oportunidade_nova_nao_tem_status_anterior():
    anterior = _hierarquia([{'id': 7, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}])
    atual = _hierarquia([{'name': 'Programa de IA', 'update_text': 'Kickoff marcado',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    nova = [o for o in result[0]['accounts'][0]['opportunities']
            if o['name'] == 'Programa de IA'][0]
    assert nova['previous_status'] is None
    assert nova['prev_opportunity_id'] is None
    assert nova['carried_over'] is False


def test_reconcile_sem_ata_anterior_mantem_tudo_como_novo():
    atual = _hierarquia([{'name': 'Programa de IA', 'update_text': 'Kickoff', 'responsible': 'Ana'}])
    result = iata_lib.reconcile(atual, [])
    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['previous_status'] is None and opp['carried_over'] is False


def test_reconcile_usa_resolver_quando_nome_e_ambiguo():
    anterior = _hierarquia([
        {'id': 7, 'name': 'Migração SAP Fase 1', 'update_text': 'Fase 1 fechada'},
        {'id': 8, 'name': 'Migração SAP Fase 2', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP fase II', 'update_text': 'Proposta revisada',
                          'responsible': 'Ana'}])
    chamadas = []

    def resolver(pares):
        chamadas.append(pares)
        return {0: 8}

    result = iata_lib.reconcile(atual, anterior, resolver=resolver)

    assert len(chamadas) == 1, 'o resolver deve ser chamado uma única vez, em lote'
    casada = [o for o in result[0]['accounts'][0]['opportunities']
              if o['name'] == 'Migração SAP fase II'][0]
    assert casada['prev_opportunity_id'] == 8
    assert casada['previous_status'] == 'Em análise'


def test_reconcile_sem_resolver_trata_ambiguo_como_novo_com_confianca_baixa():
    anterior = _hierarquia([
        {'id': 7, 'name': 'Migração SAP Fase 1', 'update_text': 'Fase 1 fechada'},
        {'id': 8, 'name': 'Migração SAP Fase 2', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP fase II', 'update_text': 'x', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior, resolver=None)

    casada = [o for o in result[0]['accounts'][0]['opportunities']
              if o['name'] == 'Migração SAP fase II'][0]
    assert casada['prev_opportunity_id'] is None
    assert casada['match_confidence'] == 'baixa'


def test_reconcile_responsavel_vazio_recebe_o_gerente_do_bloco():
    atual = _hierarquia([{'name': 'Programa de IA', 'update_text': 'Kickoff', 'responsible': ''}])
    result = iata_lib.reconcile(atual, [])
    assert result[0]['accounts'][0]['opportunities'][0]['responsible'] == 'Ana'


# --- Casos de borda que violariam a garantia de não perder dado ----------
# (encontrados em revisão de qualidade sobre a primeira versão desta task;
# cada um é uma violação de suposição de unicidade que causava perda ou
# fusão silenciosa de oportunidades/contas/gerentes — ver implementação.)


def test_reconcile_conta_repetida_sob_dois_gerentes_mescla_oportunidades_anteriores():
    """A mesma conta pode aparecer sob gerentes diferentes na ata anterior
    (trocou de dono entre reuniões) — as oportunidades do segundo bloco não
    podem desaparecer silenciosamente."""
    anterior = [
        {'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'id': 1, 'name': 'Renovação A', 'update_text': 'Em negociação'}]}]},
        {'name': 'Bruno', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'id': 2, 'name': 'Expansão B', 'update_text': 'Proposta enviada'}]}]},
    ]
    atual = _hierarquia([{'name': 'Renovação A', 'update_text': 'Fechado', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    todas_opps = [o for m in result for a in m['accounts'] for o in a['opportunities']]
    expansao = [o for o in todas_opps if o['name'] == 'Expansão B']
    assert len(expansao) == 1
    assert expansao[0]['carried_over'] is True
    assert expansao[0]['prev_opportunity_id'] == 2


def test_reconcile_duas_oportunidades_homonimas_na_mesma_conta_nao_se_fundem():
    """Nomes repetidos na mesma conta são plausíveis (dois contratos
    homônimos) — casar a nova com uma delas não pode apagar a outra."""
    anterior = _hierarquia([
        {'id': 1, 'name': 'Renovação', 'update_text': 'Contrato A em análise'},
        {'id': 2, 'name': 'Renovação', 'update_text': 'Contrato B assinado'},
    ])
    atual = _hierarquia([{'name': 'Renovação', 'update_text': 'Follow-up feito',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    opps = result[0]['accounts'][0]['opportunities']
    casada = [o for o in opps if o['update_text'] == 'Follow-up feito'][0]
    assert casada['prev_opportunity_id'] == 1
    sobrando = [o for o in opps if o.get('carried_over')]
    assert len(sobrando) == 1
    assert sobrando[0]['prev_opportunity_id'] == 2


def test_reconcile_conta_anterior_com_nome_vazio_nao_e_descartada():
    """Extração ruidosa da IA pode devolver conta sem nome — perder a conta
    inteira é pior do que exibi-la sem nome."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': '   ', 'opportunities': [
        {'id': 5, 'name': 'Piloto', 'update_text': 'Em teste'}]}]}]
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    piloto = [o for m in result for a in m['accounts'] for o in a['opportunities']
              if o['name'] == 'Piloto']
    assert len(piloto) == 1
    assert piloto[0]['carried_over'] is True


def test_reconcile_gerentes_com_grafia_de_caixa_diferente_nao_duplicam_bloco():
    """Gerentes são casados por nome normalizado — 'ANA PAULA' e
    'Ana Paula' são a mesma pessoa, não dois blocos na ata."""
    anterior = [{'name': 'ANA PAULA', 'accounts': [{'name': 'Vale', 'opportunities': [
        {'id': 3, 'name': 'Data Lake', 'update_text': 'POC em andamento'}]}]}]
    atual = [{'name': 'Ana Paula', 'accounts': [
        {'name': 'Ambev', 'opportunities': [
            {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana Paula'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    assert len(result) == 1


def test_reconcile_conta_com_grafia_levemente_diferente_nao_duplica():
    """Grafia levemente diferente de conta (typo) não pode gerar dois
    blocos contraditórios — um novo e um 'sem update' — para o mesmo
    negócio."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': 'Comercial Pedroso', 'opportunities': [
        {'id': 1, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}]}]}]
    atual = [{'name': 'Ana', 'accounts': [{'name': 'Comercial Pedrozo', 'opportunities': [
        {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    contas = [a['name'] for m in result for a in m['accounts']]
    assert contas == ['Comercial Pedrozo']
    assert result[0]['accounts'][0]['opportunities'][0]['prev_opportunity_id'] == 1


def test_reconcile_conta_com_sufixo_de_forma_juridica_nao_duplica():
    """Variação de forma jurídica ('Ambev S.A.' vs 'Ambev') não é erro de
    digitação — o SequenceMatcher penaliza diferença de comprimento (ratio
    0.71, abaixo do cutoff de fuzzy de conta) e nunca casaria via fuzzy sem
    afrouxar o cutoff a ponto de arriscar fundir contas diferentes. É um
    mecanismo à parte: remover o sufixo jurídico do fim do nome antes de
    comparar — determinístico, não fuzzy."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': 'Ambev S.A.', 'opportunities': [
        {'id': 1, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}]}]}]
    atual = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    contas = [a['name'] for m in result for a in m['accounts']]
    assert contas == ['Ambev']
    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['prev_opportunity_id'] == 1
    assert opp['match_confidence'] == 'alta'


def test_reconcile_contas_com_nome_parecido_por_conter_uma_a_outra_continuam_distintas():
    """Contraexemplo do sufixo jurídico: 'Vale' e 'Vale Verde' são contas
    diferentes. A regra de sufixo é restrita a formas jurídicas conhecidas
    e não pode virar um subset match genérico que as funda."""
    anterior = [{'name': 'Ana', 'accounts': [
        {'name': 'Vale', 'opportunities': [
            {'id': 1, 'name': 'Data Lake', 'update_text': 'POC em andamento'}]},
        {'name': 'Vale Verde', 'opportunities': [
            {'id': 2, 'name': 'Consultoria ESG', 'update_text': 'Proposta enviada'}]},
    ]}]
    atual = [{'name': 'Ana', 'accounts': [
        {'name': 'Vale', 'opportunities': [
            {'name': 'Data Lake', 'update_text': 'Fechado', 'responsible': 'Ana'}]},
    ]}]

    result = iata_lib.reconcile(atual, anterior)

    contas = {a['name'] for m in result for a in m['accounts']}
    assert contas == {'Vale', 'Vale Verde'}


def test_reconcile_resolver_com_id_none_no_candidato_nao_casa_sem_decisao_explicita():
    """{} do resolver ('sem decisão') não pode casar com um candidato cujo
    id também é None — são coisas diferentes."""
    anterior = _hierarquia([
        {'id': None, 'name': 'Migração SAP Fase 1', 'update_text': 'Fase 1 fechada'},
        {'id': None, 'name': 'Migração SAP Fase 2', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP fase II', 'update_text': 'x',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior, resolver=lambda pares: {})

    casada = [o for o in result[0]['accounts'][0]['opportunities']
              if o['name'] == 'Migração SAP fase II'][0]
    assert casada['prev_opportunity_id'] is None
    assert casada['match_confidence'] == 'baixa'


def test_reconcile_resolver_nao_pode_atribuir_o_mesmo_id_a_dois_pares():
    """Um LLM respondendo em lote pode devolver o mesmo id para dois
    índices distintos — só o primeiro pode reivindicar."""
    anterior = _hierarquia([
        {'id': 9, 'name': 'Migração SAP Fase 1', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([
        {'name': 'Migração SAP fase I', 'update_text': 'a', 'responsible': 'Ana'},
        {'name': 'Migração SAP fase Um', 'update_text': 'b', 'responsible': 'Ana'},
    ])

    result = iata_lib.reconcile(atual, anterior, resolver=lambda pares: {0: 9, 1: 9})

    opps = result[0]['accounts'][0]['opportunities']
    assert len([o for o in opps if o['prev_opportunity_id'] == 9]) == 1
    assert len([o for o in opps if o['match_confidence'] == 'baixa']) == 1


def test_reconcile_resolver_com_chaves_string_no_retorno_e_normalizado():
    """Um resolver que parseia JSON devolve índices como string; sem
    normalizar, todo par ambíguo cairia em 'baixa' em silêncio."""
    anterior = _hierarquia([
        {'id': 7, 'name': 'Migração SAP Fase 1', 'update_text': 'Fase 1 fechada'},
        {'id': 8, 'name': 'Migração SAP Fase 2', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP fase II', 'update_text': 'x',
                          'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior, resolver=lambda pares: {'0': 8})

    casada = [o for o in result[0]['accounts'][0]['opportunities']
              if o['name'] == 'Migração SAP fase II'][0]
    assert casada['prev_opportunity_id'] == 8
    assert casada['match_confidence'] == 'media'  # julgamento do resolver, não match exato


def test_reconcile_resolver_que_lanca_excecao_nao_propaga_e_e_registrado(caplog):
    """Uma falha do resolver não pode derrubar a reconciliação nem ficar
    indistinguível de 'sem match' — precisa deixar rastro no log."""
    anterior = _hierarquia([
        {'id': 7, 'name': 'Migração SAP Fase 1', 'update_text': 'Fase 1 fechada'},
        {'id': 8, 'name': 'Migração SAP Fase 2', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([{'name': 'Migração SAP fase II', 'update_text': 'x',
                          'responsible': 'Ana'}])

    def resolver_com_falha(pares):
        raise RuntimeError('LLM indisponível')

    with caplog.at_level('WARNING'):
        result = iata_lib.reconcile(atual, anterior, resolver=resolver_com_falha)

    casada = [o for o in result[0]['accounts'][0]['opportunities']
              if o['name'] == 'Migração SAP fase II'][0]
    assert casada['prev_opportunity_id'] is None
    assert any('resolver' in rec.message.lower() for rec in caplog.records)


def test_reconcile_match_exato_recebe_confianca_alta():
    anterior = _hierarquia([{'id': 7, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}])
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}])
    result = iata_lib.reconcile(atual, anterior)
    assert result[0]['accounts'][0]['opportunities'][0]['match_confidence'] == 'alta'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -v`
Expected: FAIL com `ModuleNotFoundError` / `ImportError: cannot import name 'iata'`.

- [ ] **Step 3: Implementar `integrations/iata.py`**

```python
# -*- coding: utf-8 -*-
"""Lógica pura do iAta: normalização de nomes e reconciliação da hierarquia
extraída de uma reunião com a da ata anterior. Sem Flask, sem SQLite, sem
rede — tudo aqui é testável isoladamente. Parsing da resposta da IA e
renderização (texto/e-mail) chegam em tasks futuras e vão crescer neste mesmo
arquivo."""

import difflib
import logging
import re
import unicodedata

SEM_UPDATE = 'Sem update nesta reunião'
GERENTE_NAO_IDENTIFICADO = 'Gerente não identificado'

# Acima deste ponto de similaridade dois nomes de OPORTUNIDADE são
# considerados candidatos ao mesmo negócio — mas não match automático: quem
# decide é o resolver.
_LIMIAR_AMBIGUIDADE = 0.75

# Cutoff para casar CONTA anterior por similaridade quando não há match exato
# de nome normalizado nem match por sufixo de forma jurídica. Deliberadamente
# alto: um falso positivo aqui funde duas contas de fato diferentes no mesmo
# bloco da ata, o que é pior do que exibi-las duplicadas — preferimos perder
# alguns matches de grafia muito distinta a arriscar fundir contas distintas.
_LIMIAR_CONTA = 0.85

# Prefixo de chave sintética para contas cujo nome não normaliza para nada
# (nome vazio/só pontuação vindo de uma extração ruidosa da IA). Cada
# ocorrência recebe uma chave própria — nunca colide com uma conta nomeada —
# para que a conta ainda seja recuperada como carried over em vez de
# simplesmente descartada.
_SYNTHETIC_ACCOUNT_PREFIX = '\x00__conta_sem_nome__'

# Tokens de forma jurídica removidos do FIM do nome normalizado de uma conta
# para casamento por sufixo (ex.: "Ambev S.A." == "Ambev"). Isto é
# deliberadamente restrito a forma jurídica — não é um subset match genérico:
# "Vale" e "Vale Verde" continuam contas diferentes porque nenhuma delas
# termina com um destes tokens. Ordenado por número de tokens, do maior para
# o menor, para que "s a s" seja tentado antes de "s a".
_SUFIXOS_FORMA_JURIDICA = (
    ('s', 'a', 's'),
    ('s', 'a'),
    ('sa',),
    ('ltda',),
    ('me',),
    ('eireli',),
    ('epp',),
)

_logger = logging.getLogger(__name__)


def _strip_legal_suffix(conta_norm):
    """Remove um único token/sequência de forma jurídica do fim do nome
    normalizado, se houver — nunca deixa o resultado ficar vazio (se o nome
    inteiro for o sufixo, a regra é ignorada e o nome original é devolvido)."""
    if not conta_norm:
        return conta_norm
    tokens = conta_norm.split(' ')
    for sufixo in _SUFIXOS_FORMA_JURIDICA:
        n = len(sufixo)
        if len(tokens) > n and tuple(tokens[-n:]) == sufixo:
            return ' '.join(tokens[:-n])
    return conta_norm


def normalize_name(value):
    """Minúsculo, sem acento, pontuação virando espaço, espaços colapsados."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def _index_anterior(previous_managers):
    """Indexa a ata anterior para consulta durante a reconciliação.

    Retorna `(por_opp, por_conta)`:
    - `por_conta`: chave de conta -> {'manager', 'name', 'account_id',
      'opportunities': [{'idx': int, 'data': opp}, ...]}. A chave é o nome de
      conta normalizado, ou uma chave sintética para contas sem nome.
    - `por_opp`: (chave_conta, nome_opp_normalizado) -> lista de
      `{'idx': int, 'data': opp}` — lista, não item único, porque duas
      oportunidades homônimas na mesma conta são um cenário real e não podem
      se fundir numa só.

    Cada oportunidade anterior recebe um `idx` sequencial único (não é o
    `id` do banco, que pode ser `None`) — é essa identidade interna, e não o
    nome, que controla o que já foi "consumido" durante a reconciliação.
    """
    por_opp, por_conta = {}, {}
    idx_counter = 0
    contador_sem_nome = 0
    for manager in (previous_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            if conta_norm:
                conta_key = conta_norm
            else:
                conta_key = f'{_SYNTHETIC_ACCOUNT_PREFIX}{contador_sem_nome}'
                contador_sem_nome += 1

            entry = por_conta.get(conta_key)
            if entry is None:
                # A mesma conta pode aparecer sob gerentes diferentes na ata
                # anterior (ela pode ter trocado de dono entre reuniões).
                # Mesclamos as oportunidades de todas as ocorrências em vez
                # de perder as do segundo bloco — mantendo o primeiro
                # gerente visto como dono "de fato" só para fins de
                # posicionamento de itens carried over.
                entry = {
                    'manager': gerente,
                    'name': (account.get('name') or '').strip(),
                    'account_id': account.get('account_id'),
                    'opportunities': [],
                }
                por_conta[conta_key] = entry
            elif not entry.get('account_id') and account.get('account_id'):
                entry['account_id'] = account.get('account_id')

            for opp in (account.get('opportunities') or []):
                item = {'idx': idx_counter, 'data': opp}
                idx_counter += 1
                entry['opportunities'].append(item)
                chave = (conta_key, normalize_name(opp.get('name')))
                por_opp.setdefault(chave, []).append(item)
    return por_opp, por_conta


def _match_previous_account_key(conta_norm, por_conta, contas_nomeadas_norms, indice_sem_sufixo):
    """Acha a chave, em `por_conta`, da conta anterior correspondente à
    conta atual `conta_norm`, em ordem de confiança decrescente:

    (a) nome normalizado idêntico;
    (b) nome sem sufixo de forma jurídica idêntico (determinístico — não é
        fuzzy, é remover um token conhecido como "s a"/"ltda"/etc. do fim);
    (c) similaridade com cutoff conservador — ver `_LIMIAR_CONTA`.
    """
    if not conta_norm:
        return None
    if conta_norm in por_conta:
        return conta_norm
    sem_sufixo_atual = _strip_legal_suffix(conta_norm)
    if sem_sufixo_atual in indice_sem_sufixo:
        return indice_sem_sufixo[sem_sufixo_atual]
    matches = difflib.get_close_matches(
        conta_norm, contas_nomeadas_norms, n=1, cutoff=_LIMIAR_CONTA)
    return matches[0] if matches else None


def reconcile(current_managers, previous_managers, resolver=None):
    """Casa a hierarquia extraída da reunião nova com a da ata anterior.

    - match exato por nome normalizado (conta + oportunidade) -> carrega
      status, `match_confidence='alta'`;
    - nenhum candidato -> oportunidade nova;
    - mais de um candidato parecido -> delega ao `resolver`, chamado UMA vez
      com a lista de pares ambíguos; sem resolver (ou sem decisão para um
      par), vira nova com confiança 'baixa';
    - o que estava na anterior e não apareceu -> entra com `carried_over` e
      `update_text = SEM_UPDATE`, na mesma conta/gerente que foi casada (ou
      recriando o bloco, se a conta inteira sumiu da reunião nova).

    `resolver(pares) -> {indice_do_par: id_da_oportunidade_anterior | None}`.
    Índices podem vir como string (ex.: de um JSON parseado) — são
    normalizados para `int`. `None` (ou índice ausente do retorno) significa
    "sem decisão", não "casou com uma oportunidade sem id". Se o resolver
    devolver o mesmo id para dois pares diferentes, só o primeiro é aceito —
    o segundo vira 'baixa'. Uma exceção do resolver é registrada via
    `logging` e tratada como "sem decisão para nenhum par", nunca propagada.
    Um match confirmado pelo resolver recebe `match_confidence='media'` —
    diferente do match exato ('alta'), é julgamento de um LLM sobre nomes
    que não bateram sozinhos.
    """
    por_opp, por_conta = _index_anterior(previous_managers)
    contas_nomeadas_norms = [
        k for k in por_conta if not k.startswith(_SYNTHETIC_ACCOUNT_PREFIX)]
    # Índice auxiliar para o passo (b) do casamento de conta: nome sem
    # sufixo de forma jurídica -> chave original em por_conta. Primeira
    # ocorrência vence em caso de colisão (duas contas anteriores distintas
    # que colapsam para o mesmo nome sem sufixo é um cenário raro demais
    # para justificar mais mecanismo aqui).
    indice_sem_sufixo = {}
    for k in contas_nomeadas_norms:
        indice_sem_sufixo.setdefault(_strip_legal_suffix(k), k)

    usados_idx = set()
    ids_reivindicados = set()
    pendentes_ambiguos = []  # (opp_saida, candidatos)
    matched_accounts = {}  # conta_key anterior -> dict de saída já criado
    resultado = []

    for manager in (current_managers or []):
        gerente = (manager.get('name') or '').strip() or GERENTE_NAO_IDENTIFICADO
        contas_saida = []
        for account in (manager.get('accounts') or []):
            conta_norm = normalize_name(account.get('name'))
            conta_key = _match_previous_account_key(
                conta_norm, por_conta, contas_nomeadas_norms, indice_sem_sufixo)
            anterior_conta = por_conta.get(conta_key) if conta_key else None

            opps_saida = []
            for opp in (account.get('opportunities') or []):
                nome = (opp.get('name') or '').strip()
                saida = {
                    'name': nome,
                    'update_text': (opp.get('update_text') or '').strip(),
                    'responsible': (opp.get('responsible') or '').strip() or gerente,
                    'previous_status': None,
                    'carried_over': False,
                    'prev_opportunity_id': None,
                    'match_confidence': None,
                }
                itens_candidatos = por_opp.get((conta_key, normalize_name(nome)), []) if conta_key else []
                exato = next((it for it in itens_candidatos if it['idx'] not in usados_idx), None)
                if exato is not None:
                    usados_idx.add(exato['idx'])
                    saida['previous_status'] = (exato['data'].get('update_text') or '').strip() or None
                    saida['prev_opportunity_id'] = exato['data'].get('id')
                    saida['match_confidence'] = 'alta'
                else:
                    disponiveis = [
                        it for it in (anterior_conta['opportunities'] if anterior_conta else [])
                        if it['idx'] not in usados_idx
                    ]
                    candidatos = _candidatos_proximos(nome, disponiveis)
                    if candidatos:
                        pendentes_ambiguos.append((saida, candidatos))
                opps_saida.append(saida)

            conta_saida = {
                'name': (account.get('name') or '').strip(),
                'account_id': account.get('account_id') or (anterior_conta.get('account_id') if anterior_conta else None),
                'match_confidence': account.get('match_confidence'),
                'opportunities': opps_saida,
            }
            contas_saida.append(conta_saida)
            if conta_key:
                matched_accounts.setdefault(conta_key, conta_saida)
        resultado.append({'name': gerente, 'accounts': contas_saida})

    _resolver_ambiguos(pendentes_ambiguos, resolver, usados_idx, ids_reivindicados)
    _anexar_nao_citados(resultado, por_conta, usados_idx, matched_accounts)
    return resultado


def _candidatos_proximos(nome, itens_anteriores):
    alvo = normalize_name(nome)
    if not alvo:
        return []
    achados = []
    for it in itens_anteriores:
        ratio = difflib.SequenceMatcher(None, alvo, normalize_name(it['data'].get('name'))).ratio()
        if ratio >= _LIMIAR_AMBIGUIDADE:
            achados.append(it)
    return achados


def _resolver_ambiguos(pendentes, resolver, usados_idx, ids_reivindicados):
    if not pendentes:
        return
    if resolver is None:
        for saida, _itens in pendentes:
            saida['match_confidence'] = 'baixa'
        return

    pares = [
        {'index': i, 'nome_novo': saida['name'],
         'candidatos': [{'id': it['data'].get('id'), 'nome': it['data'].get('name')} for it in itens]}
        for i, (saida, itens) in enumerate(pendentes)
    ]
    try:
        decisoes = resolver(pares) or {}
    except Exception:
        # Uma queda do resolver (ex.: chamada de LLM) não pode ficar
        # indistinguível de "não havia match" — registra o rastro e segue
        # tratando todos os pares como sem decisão.
        _logger.warning('resolver de reconciliação do iAta falhou; tratando '
                         'pares ambíguos como novos', exc_info=True)
        decisoes = {}

    # Um resolver que parseia JSON devolve chaves string ("0"); sem essa
    # normalização todos os pares cairiam em "sem decisão" silenciosamente.
    decisoes_norm = {}
    for k, v in decisoes.items():
        try:
            decisoes_norm[int(k)] = v
        except (TypeError, ValueError):
            continue

    for i, (saida, itens) in enumerate(pendentes):
        # Índice ausente ou valor None é "não decidi" — não deve ser
        # tratado como "decidi casar com um candidato sem id".
        if i not in decisoes_norm or decisoes_norm[i] is None:
            saida['match_confidence'] = 'baixa'
            continue
        escolhido = decisoes_norm[i]
        # O mesmo id não pode ser reivindicado por dois pares — o segundo a
        # chegar vira 'baixa' em vez de duplicar o carregamento.
        if escolhido in ids_reivindicados:
            saida['match_confidence'] = 'baixa'
            continue
        item = next((it for it in itens
                     if it['data'].get('id') == escolhido and it['idx'] not in usados_idx), None)
        if item is None:
            saida['match_confidence'] = 'baixa'
            continue
        usados_idx.add(item['idx'])
        ids_reivindicados.add(escolhido)
        saida['prev_opportunity_id'] = item['data'].get('id')
        saida['previous_status'] = (item['data'].get('update_text') or '').strip() or None
        # 'media', não 'alta': é julgamento de um LLM sobre nomes que não
        # bateram sozinhos, diferente do match exato/determinístico acima.
        saida['match_confidence'] = 'media'


def _anexar_nao_citados(resultado, por_conta, usados_idx, matched_accounts):
    """Tudo que estava na ata anterior e não apareceu na reunião nova entra
    como carried_over — garantido por código, não pelo modelo."""
    # Gerentes são casados por nome normalizado, não por string exata —
    # "ANA PAULA" e "Ana Paula" são a mesma pessoa. Duas pessoas distintas
    # que por acaso normalizam para o mesmo nome colapsam no mesmo bloco;
    # essa é uma decisão deliberada (o dado de entrada não nos dá como
    # diferenciá-las de outra forma), não um efeito colateral de dict.
    por_gerente = {}
    for m in resultado:
        por_gerente.setdefault(normalize_name(m['name']), m)

    for conta_key, dados in por_conta.items():
        faltantes = [it for it in dados['opportunities'] if it['idx'] not in usados_idx]
        if not faltantes:
            continue

        destino = matched_accounts.get(conta_key)
        if destino is None:
            gerente_norm = normalize_name(dados['manager'])
            gerente = por_gerente.get(gerente_norm)
            if gerente is None:
                gerente = {'name': dados['manager'], 'accounts': []}
                por_gerente[gerente_norm] = gerente
                resultado.append(gerente)
            destino = {
                'name': dados['name'],
                'account_id': dados.get('account_id'),
                'match_confidence': None,
                'opportunities': [],
            }
            gerente['accounts'].append(destino)
            matched_accounts[conta_key] = destino

        for it in faltantes:
            opp = it['data']
            destino['opportunities'].append({
                'name': (opp.get('name') or '').strip(),
                'update_text': SEM_UPDATE,
                'responsible': (opp.get('responsible') or '').strip() or dados['manager'],
                'previous_status': (opp.get('update_text') or '').strip() or None,
                'carried_over': True,
                'prev_opportunity_id': opp.get('id'),
                'match_confidence': None,
            })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS (todos os testes de normalização e reconciliação).

- [ ] **Step 5: Commit**

```bash
git add integrations/iata.py tests/test_iata.py && git commit -m "feat(iata): reconciliacao com a ata anterior"
```

---

### Task 3: Prompt e parsing da hierarquia

**Files:**
- Modify: `integrations/iata.py`
- Test: `tests/test_iata.py`

- [ ] **Step 1: Write the failing test**

```python
import json


def test_parse_hierarchy_aceita_json_em_bloco_markdown():
    payload = {
        'title': 'Pipeline Semanal', 'meeting_date': '04/08/2026',
        'meeting_time': '10:00', 'topic': 'Revisão de funil',
        'participants': [{'name': 'Ana', 'role': 'Gerente'}],
        'managers': [{'name': 'Ana', 'accounts': [
            {'name': 'Ambev', 'opportunities': [
                {'name': 'Migração SAP', 'update': 'Proposta enviada', 'responsible': 'Bruno'}]}]}],
    }
    raw = '```json\n' + json.dumps(payload, ensure_ascii=False) + '\n```'

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed['header']['title'] == 'Pipeline Semanal'
    assert parsed['header']['participants'] == [{'name': 'Ana', 'role': 'Gerente'}]
    opp = parsed['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['update_text'] == 'Proposta enviada'
    assert opp['responsible'] == 'Bruno'


def test_parse_hierarchy_gerente_vazio_vira_nao_identificado():
    raw = json.dumps({'title': 'X', 'managers': [
        {'name': '', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Op', 'update': 'algo'}]}]}]})
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed['managers'][0]['name'] == iata_lib.GERENTE_NAO_IDENTIFICADO


def test_parse_hierarchy_sem_titulo_retorna_none():
    assert iata_lib.parse_hierarchy('{"managers": []}') is None
    assert iata_lib.parse_hierarchy('') is None
    assert iata_lib.parse_hierarchy('desculpe, não consegui') is None


def test_parse_hierarchy_participantes_em_lista_de_strings():
    raw = json.dumps({'title': 'X', 'participants': ['Ana', 'Bruno'], 'managers': []})
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed['header']['participants'] == [
        {'name': 'Ana', 'role': ''}, {'name': 'Bruno', 'role': ''}]


def test_build_extraction_prompt_inclui_texto_e_pede_json():
    prompt = iata_lib.build_extraction_prompt('Ana falou da Ambev')
    assert 'Ana falou da Ambev' in prompt
    assert 'JSON' in prompt
    assert 'managers' in prompt


def test_build_extraction_prompt_trunca_texto_gigante():
    prompt = iata_lib.build_extraction_prompt('x' * 60000)
    assert len(prompt) < 45000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k "hierarchy or extraction" -v`
Expected: FAIL com `AttributeError: module 'integrations.iata' has no attribute 'parse_hierarchy'`.

- [ ] **Step 3: Implementar**

**A versão abaixo já corrige três descartes silenciosos que a primeira
implementação de referência tinha** (achados na auto-revisão da Task 3, com
testes próprios em `tests/test_iata.py`) — não reintroduza nas tasks
seguintes:

1. **Conta com `name` vazio era descartada com `continue`** — apagava
   também as oportunidades reais daquele bloco. Corrigido: a conta é mantida
   com `name: ''` (mesmo espírito de `reconcile()`, que já preserva conta
   anterior sem nome — ver C3 na Task 2).
2. **Oportunidade sem `name` era descartada** — apagava `update`/
   `responsible` reais só porque o nome não veio. Corrigido: mantida com
   `name: ''`.
3. **`managers` (ou `accounts`/`opportunities`) vindo como objeto único em
   vez de lista de um elemento apagava a ata inteira em silêncio** — iterar
   um `dict` cru percorre suas *chaves* como strings, que o filtro
   `isinstance(x, dict)` seguinte descarta todas. Corrigido com
   `_as_item_list()`, que também aceita string solta num item de lista
   (`["Ambev"]` → `[{"name": "Ambev"}]`) em vez de descartá-la.

Também adicionados por robustez contra desvio real de LLM (sem inventar
feature nova, só evitando perda de dado): aceitar chaves em português como
fallback (`titulo`/`gerentes`/`contas`/`oportunidades`/`nome`/`atualizacao`/
`responsavel` — via `_field()`), reparo de aspas tipográficas como última
tentativa de parse, e tratar `participants` como string única
(`"Ana, Bruno"`) sem iterar caractere a caractere.

Acrescentar a `integrations/iata.py` (ver arquivo real para a versão
completa e comentada — este bloco é o resumo funcional):

```python
import json

MAX_TRANSCRICAO_CHARS = 30000


def build_extraction_prompt(raw_text):
    return (
        "Você é um analista comercial. Leia a transcrição de uma reunião de pipeline "
        "e extraia a estrutura Gerente Comercial → Conta → Oportunidade.\n"
        "Retorne EXCLUSIVAMENTE um objeto JSON válido, sem markdown, sem comentários:\n"
        '{"title":"Título da reunião",'
        '"meeting_date":"DD/MM/AAAA ou null","meeting_time":"HH:MM ou null",'
        '"topic":"Tema central em uma frase",'
        '"participants":[{"name":"Nome","role":"Cargo/empresa se mencionado"}],'
        '"managers":[{"name":"Nome do gerente comercial",'
        '"accounts":[{"name":"Nome da conta/cliente",'
        '"opportunities":[{"name":"Nome da oportunidade",'
        '"update":"O que foi dito sobre ela NESTA reunião",'
        '"responsible":"Quem ficou responsável pela ação"}]}]}]}\n'
        "REGRAS OBRIGATÓRIAS:\n"
        "- Um gerente pode ter N contas; uma conta pode ter N oportunidades;\n"
        "- Se o gerente responsável por um bloco não for identificável, use "
        f'"{GERENTE_NAO_IDENTIFICADO}";\n'
        "- responsible: se ninguém for citado, deixe string vazia — o sistema "
        "atribui ao gerente do bloco;\n"
        "- update: apenas o que foi dito NESTA reunião, sem repetir histórico;\n"
        "- Não invente contas, oportunidades ou nomes que não estejam no texto;\n"
        "- Preserve nomes próprios como aparecem no texto.\n\n"
        f"TRANSCRIÇÃO DA REUNIÃO:\n{(raw_text or '')[:MAX_TRANSCRICAO_CHARS]}"
    )


def _strip_code_fence(raw):
    texto = str(raw or '').strip()
    if texto.startswith('```'):
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', texto, flags=re.IGNORECASE)
        if m:
            texto = m.group(1).strip()
    return texto


_ASPAS_CURVAS = str.maketrans({
    '\u201c': '"', '\u201d': '"', '\u2018': "'", '\u2019': "'",
})


def _tentar_json(texto):
    try:
        return json.loads(texto)
    except Exception:
        return None


def _loads_tolerante(raw):
    """Bloco de código markdown, texto explicativo antes/depois do objeto, e
    aspas tipográficas como delimitador — tudo tolerado. JSON truncado não é
    recuperado: devolve None (falha de extração, não dado inventado)."""
    texto = _strip_code_fence(raw)
    if not texto:
        return None
    resultado = _tentar_json(texto)
    if resultado is not None:
        return resultado
    inicio, fim = texto.find('{'), texto.rfind('}')
    trecho = texto[inicio:fim + 1] if inicio != -1 and fim > inicio else texto
    resultado = _tentar_json(trecho)
    if resultado is not None:
        return resultado
    return _tentar_json(trecho.translate(_ASPAS_CURVAS))


def _clean_null(value):
    v = str(value or '').strip()
    return None if not v or v.lower() in ('null', 'none', 'n/a', '-') else v


def _field(d, *keys):
    """Primeiro valor não vazio dentre `keys` — tolera chave em português."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ''):
            return v
    return None


def _as_item_list(value, name_key='name'):
    """Normaliza para lista de dicts: dict único -> [dict]; item string
    solta -> {name_key: item}; None/tipo inesperado -> []. Ver nota acima —
    sem isso um `managers` devolvido como objeto único apaga a ata inteira."""
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    saida = []
    for item in value:
        if isinstance(item, dict):
            saida.append(item)
        else:
            texto = str(item or '').strip()
            if texto:
                saida.append({name_key: texto})
    return saida


def _parse_participants(raw_participants):
    saida = []
    if isinstance(raw_participants, str):
        nomes = [n.strip() for n in re.split(r'[,;/]', raw_participants) if n.strip()]
        return [{'name': n, 'role': ''} for n in nomes]
    for p in _as_item_list(raw_participants):
        nome = str(_field(p, 'name', 'nome') or '').strip()
        papel = str(_field(p, 'role', 'cargo', 'papel', 'empresa') or '').strip()
        if nome:
            saida.append({'name': nome, 'role': papel})
    return saida


def parse_hierarchy(raw):
    """Converte a resposta da IA no formato canônico. None se inutilizável
    (sem título — recusa, texto livre, JSON truncado)."""
    parsed = _loads_tolerante(raw)
    if not isinstance(parsed, dict):
        return None
    titulo = str(_field(parsed, 'title', 'titulo', 'título') or '').strip()
    if not titulo:
        return None

    managers = []
    for manager in _as_item_list(_field(parsed, 'managers', 'gerentes')):
        contas = []
        for account in _as_item_list(_field(manager, 'accounts', 'contas')):
            # Conta sem nome é mantida (name: '') — não descartada — para
            # não apagar oportunidades reais junto com ela.
            nome_conta = str(_field(account, 'name', 'nome') or '').strip()
            opps = []
            for opp in _as_item_list(_field(account, 'opportunities', 'oportunidades')):
                opps.append({
                    'name': str(_field(opp, 'name', 'nome') or '').strip(),
                    'update_text': str(_field(opp, 'update', 'update_text', 'atualizacao',
                                               'atualização') or '').strip(),
                    'responsible': str(_field(opp, 'responsible', 'responsavel',
                                               'responsável') or '').strip(),
                })
            contas.append({'name': nome_conta, 'account_id': None,
                           'match_confidence': None, 'opportunities': opps})
        managers.append({
            'name': str(_field(manager, 'name', 'nome') or '').strip() or GERENTE_NAO_IDENTIFICADO,
            'accounts': contas,
        })

    return {
        'header': {
            'title': titulo,
            'meeting_date': _clean_null(_field(parsed, 'meeting_date', 'data_reuniao', 'data')),
            'meeting_time': _clean_null(_field(parsed, 'meeting_time', 'horario', 'horário', 'hora')),
            'topic': str(_field(parsed, 'topic', 'tema') or '').strip() or titulo,
            'participants': _parse_participants(_field(parsed, 'participants', 'participantes')),
        },
        'managers': managers,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/iata.py tests/test_iata.py && git commit -m "feat(iata): prompt e parsing da hierarquia"
```

**Addendum pós-revisão (mesma Task 3, commit seguinte):** a revisão de
qualidade encontrou mais um descarte silencioso total de dado e dois
ajustes menores, e pediu a divisão em pacote antes da Task 4. Registrado
aqui para as tasks seguintes não reintroduzirem nenhum dos dois:

1. **CRITICAL — coleção como mapa nome→objeto colapsava a hierarquia
   inteira**, sem virar `None` e sem logar. `_as_item_list` tratava
   qualquer `dict` recebido como "um item único" (`[value]`), sem
   distinguir do caso, igualmente plausível num LLM sem grammar estrita,
   de a coleção vir mapeada por nome: `{"Ana": {...}, "Bruno": {...}}` em
   vez de `[{"name": "Ana", ...}, {"name": "Bruno", ...}]`. Reproduzido
   nos três níveis (`managers`, `accounts`, `opportunities`). Corrigido
   distinguindo os dois formatos por `item_keys` (parâmetro novo de
   `_as_item_list`): se o dict tem alguma chave de item conhecida daquele
   nível (`name`/`nome`, ou uma chave estrutural como `accounts`/
   `contas`), é item único; senão, se todos os *valores* do dict são eles
   próprios dicts, é mapa — a chave do mapa vira o `name` do item que não
   tiver nome próprio. Ver a versão final de `_as_item_list` no arquivo
   real (`integrations/iata/llm.py`).
2. **IMPORTANT — `_loads_tolerante` rejeitava JSON válido por causa de
   chave solta no texto ao redor.** O recorte do primeiro `{` ao último
   `}` engole qualquer chave solta no texto explicativo antes ou depois
   do JSON ("Segue conforme {template} solicitado: {...json...}"),
   fazendo o parse do objeto central, perfeitamente válido, falhar
   inteiro. Corrigido trocando o recorte por `json.JSONDecoder().raw_decode()`
   a partir de cada posição de `{` (limitado a `_MAX_TENTATIVAS_RAW_DECODE
   = 20` tentativas para não virar varredura quadrática), aceitando a
   primeira que decodificar um `dict` válido — `raw_decode` para no fim do
   objeto e ignora o que vem depois, então resolve lixo antes e depois ao
   mesmo tempo.
3. **MINOR — documentada a limitação do split de `participants` como
   string única** (fragmenta "Bruno Costa, Diretor Comercial da Ambev" em
   dois participantes falsos): aceita como está, só o docstring de
   `_parse_participants` ganhou o aviso — não é perda de dado, o custo de
   errar é um participante espúrio, não uma oportunidade desaparecendo.
4. **Divisão em pacote, antes da Task 4** — ver "Estrutura de arquivos" no
   topo do plano e a nota abaixo.

```bash
git add integrations/iata tests/test_iata.py docs/superpowers/plans/2026-08-04-iata-autotoca.md && git rm integrations/iata.py && git commit -m "fix(iata): mapa nome->objeto e raw_decode tolerante; divide em pacote"
```

**`integrations/iata.py` vira o pacote `integrations/iata/`** — motivo:
`integrations/iata.py` já estava em ~560 linhas com duas responsabilidades
ortogonais (reconciliação da Task 2, parsing/prompt da Task 3), e as Tasks
4-5 adicionam uma terceira (renderização). Dividir agora, enquanto é
barato, evita um arquivo de 800+ linhas nas Tasks seguintes. Estrutura:

| Arquivo | Contém |
|---|---|
| `integrations/iata/__init__.py` | Reexporta tudo que é público (e `_loads_tolerante`, privado mas consumido diretamente pelas rotas nas Tasks 7-8) — `from integrations import iata as iata_lib` e `iata_lib.<qualquer coisa>` continuam funcionando sem mudança em quem consome. |
| `integrations/iata/reconcile.py` | `normalize_name`, `reconcile`, `SEM_UPDATE`, `GERENTE_NAO_IDENTIFICADO` e helpers privados — conteúdo da Task 2. |
| `integrations/iata/llm.py` | `build_extraction_prompt`, `parse_hierarchy`, `MAX_TRANSCRICAO_CHARS`, `_loads_tolerante` e helpers privados — conteúdo desta Task 3. Importa `GERENTE_NAO_IDENTIFICADO` de `.reconcile`. |
| `integrations/iata/render.py` | Tasks 4 e 5 concluídas — `render_markdown`, `render_email_html`, `email_subject`. |

Nenhum import em `tests/test_iata.py` precisou mudar — `from integrations
import iata as iata_lib` já resolve para o pacote automaticamente.

**Tasks 4, 5, 6, 7, 8 e 9 abaixo foram atualizadas** para apontar para o
arquivo certo dentro do pacote em vez do antigo `integrations/iata.py`
monolítico — Task 4 e 5 modificam `integrations/iata/render.py`
especificamente (não os outros dois arquivos do pacote).

---

### Task 4: Renderização em texto (markdown)

**Files:**
- Modify: `integrations/iata/render.py` (o pacote agora divide o antigo
  `integrations/iata.py` — ver nota de divisão ao final da Task 3;
  `render_markdown` importa `GERENTE_NAO_IDENTIFICADO` de `.reconcile` e
  `_clean_null` de `.llm`, e precisa ser reexportado em `__init__.py`)
- Test: `tests/test_iata.py`

- [x] **Step 1: Write the failing test**

```python
def _header_exemplo():
    return {'title': 'Pipeline Semanal', 'meeting_date': '04/08/2026',
            'meeting_time': '10:00', 'topic': 'Revisão de funil',
            'participants': [{'name': 'Ana', 'role': 'Gerente'}, {'name': 'Bruno', 'role': ''}]}


def _managers_exemplo():
    return [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Migração SAP', 'previous_status': 'Proposta enviada',
         'update_text': 'Cliente pediu desconto', 'responsible': 'Bruno',
         'carried_over': False}]}]}]


def test_render_markdown_segue_o_formato_acordado():
    texto = iata_lib.render_markdown(_header_exemplo(), _managers_exemplo())
    assert 'Título da Reunião: Pipeline Semanal' in texto
    assert 'Data e horário: 04/08/2026 10:00' in texto
    assert 'Participantes: Ana, Bruno' in texto
    assert 'Tema: Revisão de funil' in texto
    assert 'Gerente Comercial: Ana' in texto
    assert 'Ambev' in texto
    assert 'Migração SAP: Proposta enviada' in texto
    assert 'Update: Cliente pediu desconto' in texto
    assert 'Responsável: Bruno' in texto


def test_render_markdown_oportunidade_sem_status_anterior_nao_mostra_dois_pontos_vazio():
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Programa de IA', 'previous_status': None, 'update_text': 'Kickoff',
         'responsible': 'Ana', 'carried_over': False}]}]}]
    texto = iata_lib.render_markdown(_header_exemplo(), managers)
    assert 'Programa de IA\n' in texto
    assert 'Programa de IA:' not in texto


def test_render_markdown_inclui_secoes_opcionais_no_fim():
    extras = {'decisions': ['Aprovar desconto de 5%'],
              'next_steps': [{'action': 'Enviar proposta', 'responsible': 'Bruno',
                              'deadline': '10/08/2026'}],
              'insights': [{'pain': 'Custo alto de licença',
                            'matched_offer': 'FinOps', 'observation': 'Aderente'}]}
    texto = iata_lib.render_markdown(_header_exemplo(), _managers_exemplo(), extras)
    assert 'Decisões' in texto and 'Aprovar desconto de 5%' in texto
    assert 'Próximos passos' in texto and 'Enviar proposta' in texto
    assert 'Insights de negócio' in texto and 'FinOps' in texto
    assert texto.index('Gerente Comercial: Ana') < texto.index('Decisões')


def test_render_markdown_sem_extras_nao_cria_secoes_vazias():
    texto = iata_lib.render_markdown(_header_exemplo(), _managers_exemplo(), None)
    assert 'Decisões' not in texto and 'Insights de negócio' not in texto
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k render_markdown -v`
Expected: FAIL — `has no attribute 'render_markdown'`.

- [x] **Step 3: Implementar**

**Correção pós-revisão:** a versão original desta referência renderizava
conta/oportunidade sem nome como `f"  * {account.get('name') or ''}"` — um
bullet vazio (`"  * "`) que não deixa claro pro usuário que existe algo ali.
A Task 3 preservou deliberadamente esses blocos sem nome em vez de
descartá-los (podem ter update/responsável reais), e deixou a decisão de
rótulo para a renderização — então a implementação final usa
`CONTA_SEM_NOME = 'Conta sem nome'` e
`OPORTUNIDADE_SEM_NOME = 'Oportunidade sem nome'` como fallback visível.

```python
CONTA_SEM_NOME = 'Conta sem nome'
OPORTUNIDADE_SEM_NOME = 'Oportunidade sem nome'


def render_markdown(header, managers, extras=None):
    header = header or {}
    linhas = [
        f"Título da Reunião: {header.get('title') or ''}",
        "Data e horário: " + ' '.join(
            p for p in [header.get('meeting_date') or '', header.get('meeting_time') or ''] if p
        ).strip(),
        "Participantes: " + ', '.join(
            (p.get('name') or '') for p in (header.get('participants') or []) if p.get('name')
        ),
        f"Tema: {header.get('topic') or ''}",
        '',
    ]

    for manager in (managers or []):
        linhas.append(f"Gerente Comercial: {manager.get('name') or GERENTE_NAO_IDENTIFICADO}")
        linhas.append('')
        for account in (manager.get('accounts') or []):
            linhas.append(f"  * {(account.get('name') or '').strip() or CONTA_SEM_NOME}")
            for opp in (account.get('opportunities') or []):
                status = (opp.get('previous_status') or '').strip()
                titulo = (opp.get('name') or '').strip() or OPORTUNIDADE_SEM_NOME
                linhas.append(f"     * {titulo}: {status}" if status else f"     * {titulo}")
                linhas.append(f"        * Update: {(opp.get('update_text') or '').strip()}")
                linhas.append(f"        * Responsável: {(opp.get('responsible') or '').strip()}")
            linhas.append('')

    extras = extras or {}
    for chave, titulo in (('agenda', 'Pauta'), ('decisions', 'Decisões')):
        itens = [str(i).strip() for i in (extras.get(chave) or []) if str(i).strip()]
        if itens:
            linhas.append(titulo)
            linhas.extend(f'  * {i}' for i in itens)
            linhas.append('')

    passos = [s for s in (extras.get('next_steps') or []) if isinstance(s, dict)]
    if passos:
        linhas.append('Próximos passos')
        for s in passos:
            prazo = _clean_null(s.get('deadline'))
            sufixo = f" (prazo: {prazo})" if prazo else ''
            linhas.append(
                f"  * {(s.get('action') or '').strip()} — "
                f"{(s.get('responsible') or 'A definir').strip()}{sufixo}"
            )
        linhas.append('')

    insights = [i for i in (extras.get('insights') or []) if isinstance(i, dict)]
    if insights:
        linhas.append('Insights de negócio')
        for i in insights:
            oferta = _clean_null(i.get('matched_offer')) or 'sem solução mapeada'
            obs = (i.get('observation') or '').strip()
            linhas.append(f"  * {(i.get('pain') or '').strip()} → {oferta}"
                          + (f" — {obs}" if obs else ''))
        linhas.append('')

    return '\n'.join(linhas).rstrip() + '\n'
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add integrations/iata/render.py integrations/iata/__init__.py tests/test_iata.py && git commit -m "feat(iata): render da ata em texto"
```

---

### Task 5: HTML do e-mail

**Files:**
- Modify: `integrations/iata/render.py` (mesmo arquivo da Task 4, dentro do
  pacote; `email_subject` provavelmente usa `_clean_null` de `.llm` também)
- Test: `tests/test_iata.py`

Cliente de e-mail descarta `<style>` no `<head>` e ignora indentação de texto — por isso o HTML sai com `<ul>` aninhado de verdade e estilo inline em cada elemento.

- [x] **Step 1: Write the failing test**

```python
def test_render_email_html_usa_ul_aninhado_e_estilo_inline():
    html = iata_lib.render_email_html(_header_exemplo(), _managers_exemplo())
    assert '<style' not in html.lower(), 'cliente de e-mail descarta <style>'
    assert html.count('<ul') >= 3, 'conta, oportunidade e detalhes são níveis aninhados'
    assert 'style="' in html
    assert 'Migração SAP' in html


def test_render_email_html_escapa_html_do_conteudo():
    managers = [{'name': '<script>alert(1)</script>', 'accounts': []}]
    html = iata_lib.render_email_html(_header_exemplo(), managers)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_render_email_subject_usa_titulo_e_data():
    assert iata_lib.email_subject(_header_exemplo()) == 'Ata — Pipeline Semanal — 04/08/2026'


def test_render_email_subject_sem_data():
    header = dict(_header_exemplo(), meeting_date=None)
    assert iata_lib.email_subject(header) == 'Ata — Pipeline Semanal'
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k email -v`
Expected: FAIL — `has no attribute 'render_email_html'`.

**Correção pós-revisão:** pelo mesmo motivo do render de texto (Task 4), a
versão original renderizava conta/oportunidade sem nome como
`_escape(account.get("name") or "")` — resulta em `<strong></strong>` vazio,
sem indicar pro usuário que existe algo ali. A implementação final reusa
`CONTA_SEM_NOME`/`OPORTUNIDADE_SEM_NOME` (definidas em `render.py` pela
Task 4) como fallback.

- [x] **Step 3: Implementar**

```python
from html import escape as _escape

_ESTILO_BASE = "font-family:Segoe UI,Arial,sans-serif; font-size:14px; color:#111827;"
_ESTILO_UL = "margin:4px 0 4px 0; padding-left:22px;"
_ESTILO_LI = "margin:2px 0;"


def email_subject(header):
    header = header or {}
    titulo = (header.get('title') or 'Ata de Reunião').strip()
    data = _clean_null(header.get('meeting_date'))
    return f"Ata — {titulo} — {data}" if data else f"Ata — {titulo}"


def render_email_html(header, managers, extras=None):
    header = header or {}
    partes = [f'<div style="{_ESTILO_BASE}">']

    def campo(rotulo, valor):
        if valor:
            partes.append(
                f'<p style="margin:2px 0;"><strong>{_escape(rotulo)}:</strong> '
                f'{_escape(valor)}</p>'
            )

    campo('Título da Reunião', (header.get('title') or '').strip())
    campo('Data e horário', ' '.join(
        p for p in [header.get('meeting_date') or '', header.get('meeting_time') or ''] if p
    ).strip())
    campo('Participantes', ', '.join(
        (p.get('name') or '') for p in (header.get('participants') or []) if p.get('name')))
    campo('Tema', (header.get('topic') or '').strip())

    for manager in (managers or []):
        partes.append(
            f'<p style="margin:16px 0 4px;"><strong>Gerente Comercial:</strong> '
            f'{_escape(manager.get("name") or GERENTE_NAO_IDENTIFICADO)}</p>'
        )
        partes.append(f'<ul style="{_ESTILO_UL}">')
        for account in (manager.get('accounts') or []):
            nome_conta = (account.get('name') or '').strip() or CONTA_SEM_NOME
            partes.append(
                f'<li style="{_ESTILO_LI}"><strong>'
                f'{_escape(nome_conta)}</strong>'
            )
            partes.append(f'<ul style="{_ESTILO_UL}">')
            for opp in (account.get('opportunities') or []):
                status = (opp.get('previous_status') or '').strip()
                rotulo = _escape((opp.get('name') or '').strip() or OPORTUNIDADE_SEM_NOME)
                if status:
                    rotulo += ': ' + _escape(status)
                partes.append(f'<li style="{_ESTILO_LI}">{rotulo}')
                partes.append(f'<ul style="{_ESTILO_UL}">')
                partes.append(
                    f'<li style="{_ESTILO_LI}"><strong>Update:</strong> '
                    f'{_escape((opp.get("update_text") or "").strip())}</li>'
                )
                partes.append(
                    f'<li style="{_ESTILO_LI}"><strong>Responsável:</strong> '
                    f'{_escape((opp.get("responsible") or "").strip())}</li>'
                )
                partes.append('</ul></li>')
            partes.append('</ul></li>')
        partes.append('</ul>')

    extras = extras or {}
    for chave, titulo in (('agenda', 'Pauta'), ('decisions', 'Decisões')):
        itens = [str(i).strip() for i in (extras.get(chave) or []) if str(i).strip()]
        if itens:
            partes.append(f'<p style="margin:16px 0 4px;"><strong>{titulo}</strong></p>')
            partes.append(f'<ul style="{_ESTILO_UL}">')
            partes.extend(f'<li style="{_ESTILO_LI}">{_escape(i)}</li>' for i in itens)
            partes.append('</ul>')

    passos = [s for s in (extras.get('next_steps') or []) if isinstance(s, dict)]
    if passos:
        partes.append('<p style="margin:16px 0 4px;"><strong>Próximos passos</strong></p>')
        partes.append(f'<ul style="{_ESTILO_UL}">')
        for s in passos:
            prazo = _clean_null(s.get('deadline'))
            texto = (f"{(s.get('action') or '').strip()} — "
                     f"{(s.get('responsible') or 'A definir').strip()}"
                     + (f" (prazo: {prazo})" if prazo else ''))
            partes.append(f'<li style="{_ESTILO_LI}">{_escape(texto)}</li>')
        partes.append('</ul>')

    insights = [i for i in (extras.get('insights') or []) if isinstance(i, dict)]
    if insights:
        partes.append('<p style="margin:16px 0 4px;"><strong>Insights de negócio</strong></p>')
        partes.append(f'<ul style="{_ESTILO_UL}">')
        for i in insights:
            oferta = _clean_null(i.get('matched_offer')) or 'sem solução mapeada'
            obs = (i.get('observation') or '').strip()
            texto = f"{(i.get('pain') or '').strip()} → {oferta}" + (f" — {obs}" if obs else '')
            partes.append(f'<li style="{_ESTILO_LI}">{_escape(texto)}</li>')
        partes.append('</ul>')

    partes.append('</div>')
    return ''.join(partes)
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add integrations/iata/render.py integrations/iata/__init__.py tests/test_iata.py && git commit -m "feat(iata): html do e-mail com ul aninhado e estilo inline"
```

---

### Task 6: Persistência da hierarquia e rotas de leitura

**Files:**
- Create: `routes/autotoca_iata.py`
- Modify: `app.py:12650` (`ROUTE_MODULES`)
- Test: `tests/test_iata.py`

- [x] **Step 1: Write the failing test**

A função de persistência é `_iata_save_record`, definida em
`routes/autotoca_iata.py` e disponível como atributo do módulo `app` porque as
rotas são executadas no namespace dele por `_load_route_modules()`.

```python
def test_save_record_persiste_hierarquia_completa(db_path):
    header = {'title': 'Pipeline Semanal', 'meeting_date': '04/08/2026',
              'meeting_time': '10:00', 'topic': 'Funil',
              'participants': [{'name': 'Ana', 'role': 'Gerente'}]}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': 'alta', 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'Proposta',
             'responsible': 'Bruno', 'carried_over': False,
             'prev_opportunity_id': None, 'match_confidence': None}]}]}]

    rid = toca._iata_save_record(header, managers, extras={}, raw_text='texto',
                                 previous_record_id=None)

    registro = toca._iata_load_record(rid)
    assert registro['title'] == 'Pipeline Semanal'
    assert registro['format_version'] == 2
    assert registro['managers'][0]['name'] == 'Ana'
    assert registro['managers'][0]['accounts'][0]['opportunities'][0]['responsible'] == 'Bruno'
    assert 'Gerente Comercial: Ana' in registro['body_markdown']


def test_get_e_list_retornam_a_ata(client, db_path):
    header = {'title': 'Pipeline Semanal', 'meeting_date': None, 'meeting_time': None,
              'topic': 'Funil', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Op', 'previous_status': None, 'update_text': 'u',
             'responsible': 'Ana', 'carried_over': False,
             'prev_opportunity_id': None, 'match_confidence': None}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    lista = client.get('/api/autotoca/iata')
    assert lista.status_code == 200
    assert any(r['id'] == rid for r in lista.get_json())

    detalhe = client.get(f'/api/autotoca/iata/{rid}')
    assert detalhe.status_code == 200
    assert detalhe.get_json()['managers'][0]['accounts'][0]['name'] == 'Ambev'

    assert client.get('/api/autotoca/iata/99999').status_code == 404


def test_delete_remove_ata_e_hierarquia(client, db_path):
    import sqlite3
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Op', 'previous_status': None, 'update_text': 'u',
             'responsible': 'Ana', 'carried_over': False,
             'prev_opportunity_id': None, 'match_confidence': None}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    assert client.delete(f'/api/autotoca/iata/{rid}').status_code == 200

    conn = sqlite3.connect(db_path)
    try:
        restantes = conn.execute(
            'SELECT COUNT(*) FROM iata_opportunities WHERE record_id = ?', (rid,)).fetchone()[0]
    finally:
        conn.close()
    assert restantes == 0, 'a exclusão precisa levar a hierarquia junto'
```

Nota sobre o `DELETE`: `PRAGMA foreign_keys` não vem ligado por padrão no
SQLite, então o `ON DELETE CASCADE` pode não disparar. A implementação apaga as
tabelas filhas explicitamente — o teste acima cobre isso.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k "save_record or get_e_list or delete_remove" -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute '_iata_save_record'`.

- [x] **Step 3: Criar `routes/autotoca_iata.py`**

**Correção pós-revisão:** a versão original desta referência tinha três
defeitos de perda silenciosa de dado, achados testando round-trip
save→load contra `iata_lib.reconcile`:

1. **`match_confidence` de oportunidade não tinha coluna.** A migração 17
   (Task 1) só criou `match_confidence` em `iata_accounts` — `iata_opportunities`
   não tinha essa coluna, então o valor que `reconcile()` calcula por
   oportunidade (`alta`/`media`/`baixa`/`None`) era descartado a cada
   gravação, sem erro. Corrigido com uma migração nova (18,
   `iata_opportunity_match_confidence`, função
   `_iata_add_opportunity_match_confidence_column` seguindo o padrão de
   `_iata_add_record_columns`) mais a coluna no `CREATE TABLE IF NOT EXISTS`
   do `init_db` (para bancos novos). `_iata_write_hierarchy` e o `INSERT` em
   `iata_opportunities` passaram a gravar `opp.get('match_confidence')`.
2. **`match_confirmed` de conta voltava como `int` (0/1), não `bool`.**
   Inconsistente com `carried_over`, que já convertia. `_iata_read_hierarchy`
   agora aplica `bool(conta.get('match_confirmed'))` também.
3. **`_iata_load_record` inicializava `ata_json`/`participants`/`insights_json`
   com fallback `'[]'` (lista) mesmo `ata_json` sendo sempre um objeto —
   funcionava por acidente graças ao `isinstance(..., dict)` guard, mas era
   frágil.** Reescrito para dar fallback `'{}'` a `ata_json` especificamente,
   com o mesmo guard de `isinstance` mantido por segurança.

`PRAGMA foreign_keys=ON` já é ligado em toda conexão por `get_db()` (não é
"desligado por padrão" como a nota abaixo sugeria) — o `DELETE` explícito das
tabelas filhas na rota `DELETE` continua correto, só deixou de ser a única
linha de defesa contra órfãos.

```python
# -*- coding: utf-8 -*-
# Rotas do iAta dentro do AutoToca.
# Este arquivo é executado no namespace de app.py por _load_route_modules():
# tem acesso a get_db, logger, _llm_prompt, _outlook_send_mail e afins.

from integrations import iata as iata_lib


def _iata_save_record(header, managers, extras, raw_text, previous_record_id,
                      body_markdown=None):
    """Grava a ata e a hierarquia. Devolve o id do registro."""
    header = header or {}
    body = body_markdown or iata_lib.render_markdown(header, managers, extras)
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO iata_records
               (title, meeting_date, meeting_time, topic, participants, ata_json,
                insights_json, raw_text, previous_record_id, body_markdown,
                body_edited, reparse_failed, format_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,0,2)''',
            (header.get('title') or 'Ata sem título',
             header.get('meeting_date'), header.get('meeting_time'),
             header.get('topic') or '',
             json.dumps(header.get('participants') or [], ensure_ascii=False),
             json.dumps({'header': header, 'managers': managers, 'extras': extras or {}},
                        ensure_ascii=False),
             json.dumps((extras or {}).get('insights') or [], ensure_ascii=False),
             raw_text or '', previous_record_id, body))
        record_id = c.lastrowid
        _iata_write_hierarchy(c, record_id, managers)
        conn.commit()
        return record_id
    finally:
        conn.close()


def _iata_write_hierarchy(c, record_id, managers):
    """(Re)escreve as tabelas da hierarquia para uma ata."""
    c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
    for m_ordem, manager in enumerate(managers or []):
        c.execute('INSERT INTO iata_managers (record_id, name, display_order) VALUES (?,?,?)',
                  (record_id, manager.get('name') or iata_lib.GERENTE_NAO_IDENTIFICADO, m_ordem))
        manager_id = c.lastrowid
        for a_ordem, account in enumerate(manager.get('accounts') or []):
            nome_conta = account.get('name') or ''
            c.execute(
                '''INSERT INTO iata_accounts
                   (record_id, manager_id, account_id, name, name_norm,
                    match_confidence, match_confirmed, display_order)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (record_id, manager_id, account.get('account_id'), nome_conta,
                 iata_lib.normalize_name(nome_conta), account.get('match_confidence'),
                 1 if account.get('match_confirmed') else 0, a_ordem))
            conta_id = c.lastrowid
            for o_ordem, opp in enumerate(account.get('opportunities') or []):
                nome_opp = opp.get('name') or ''
                c.execute(
                    '''INSERT INTO iata_opportunities
                       (record_id, iata_account_id, name, name_norm, previous_status,
                        update_text, responsible, carried_over, prev_opportunity_id,
                        display_order)
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (record_id, conta_id, nome_opp, iata_lib.normalize_name(nome_opp),
                     opp.get('previous_status'), opp.get('update_text'),
                     opp.get('responsible'), 1 if opp.get('carried_over') else 0,
                     opp.get('prev_opportunity_id'), o_ordem))


def _iata_read_hierarchy(c, record_id):
    """Lê a hierarquia no formato canônico, com os ids do banco."""
    c.execute('SELECT * FROM iata_managers WHERE record_id = ? ORDER BY display_order, id',
              (record_id,))
    managers = [dict_from_row(r) for r in c.fetchall()]
    for manager in managers:
        c.execute('''SELECT * FROM iata_accounts WHERE manager_id = ?
                     ORDER BY display_order, id''', (manager['id'],))
        contas = [dict_from_row(r) for r in c.fetchall()]
        for conta in contas:
            c.execute('''SELECT * FROM iata_opportunities WHERE iata_account_id = ?
                         ORDER BY display_order, id''', (conta['id'],))
            conta['opportunities'] = [dict_from_row(r) for r in c.fetchall()]
            for opp in conta['opportunities']:
                opp['carried_over'] = bool(opp.get('carried_over'))
        manager['accounts'] = contas
    return managers


def _iata_load_record(record_id):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT * FROM iata_records WHERE id = ?', (record_id,))
        row = c.fetchone()
        if not row:
            return None
        registro = dict_from_row(row)
        for campo in ('participants', 'ata_json', 'insights_json'):
            try:
                registro[campo] = json.loads(registro.get(campo) or '[]')
            except Exception:
                registro[campo] = []
        registro['extras'] = (registro.get('ata_json') or {}).get('extras', {}) \
            if isinstance(registro.get('ata_json'), dict) else {}
        registro['header'] = (registro.get('ata_json') or {}).get('header', {}) \
            if isinstance(registro.get('ata_json'), dict) else {}
        registro['managers'] = _iata_read_hierarchy(c, record_id)
        return registro
    finally:
        conn.close()


@app.route('/api/autotoca/iata', methods=['GET'])
def list_iata_records():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''SELECT id, title, meeting_date, meeting_time, topic, participants,
                            format_version, body_edited, reparse_failed, created_at
                     FROM iata_records ORDER BY datetime(created_at) DESC, id DESC''')
        registros = []
        for row in c.fetchall():
            r = dict_from_row(row)
            try:
                r['participants'] = json.loads(r.get('participants') or '[]')
            except Exception:
                r['participants'] = []
            registros.append(r)
        conn.close()
        return jsonify(registros)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao listar registros: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['GET'])
def get_iata_record(record_id):
    try:
        registro = _iata_load_record(record_id)
        if not registro:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify(registro)
    except Exception as e:
        logger.exception(f'[iAta] Erro ao buscar registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/<int:record_id>', methods=['DELETE'])
def delete_iata_record(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        # PRAGMA foreign_keys não vem ligado por padrão: apagar filhas na mão.
        c.execute('DELETE FROM iata_opportunities WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_accounts WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_managers WHERE record_id = ?', (record_id,))
        c.execute('DELETE FROM iata_records WHERE id = ?', (record_id,))
        removidos = c.rowcount
        conn.commit()
        conn.close()
        if not removidos:
            return jsonify({'error': 'Ata não encontrada.'}), 404
        return jsonify({'message': 'Ata removida com sucesso.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao remover registro {record_id}: {e}')
        return jsonify({'error': str(e)}), 500
```

Antes de escrever, conferir em `routes/portfolio.py` como `dict_from_row` é
usado e confirmar que `json` já está importado no namespace do `app.py` (está —
`app.py` importa `json` no topo).

- [x] **Step 4: Registrar o módulo de rotas**

Em `app.py:12650`, acrescentar `'autotoca_iata'` à lista:

```python
ROUTE_MODULES = ['clients', 'accounts', 'activities_agenda', 'kanban', 'campaigns',
                 'whatsapp', 'outlook', 'itoca', 'autotoca', 'autotoca_iata', 'wikitoca',
                 'portfolio', 'config', 'home', 'reembolsos', 'feedback']
```

As rotas antigas em `routes/portfolio.py` ainda existem neste ponto, mas usam
nomes de função iguais (`list_iata_records`, `get_iata_record`,
`delete_iata_record`) e o Flask recusa endpoints duplicados. Então **remover
agora** o bloco `/api/portfolio/iata*` de `routes/portfolio.py:301-380` (as
cinco rotas, do `@app.route('/api/portfolio/iata', methods=['GET'])` até o fim
de `delete_iata_record`). O POST e o polling voltam na Task 7.

- [x] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [x] **Step 6: Verificar que o app ainda sobe**

Run: `python -c "import app; print(len(app.app.url_map._rules))"`
Expected: imprime um número (sem exceção de endpoint duplicado).

- [x] **Step 7: Commit**

```bash
git add routes/autotoca_iata.py routes/portfolio.py app.py tests/test_iata.py && git commit -m "feat(iata): rotas de leitura no autotoca com hierarquia persistida"
```

---

### Task 7: Geração assíncrona da ata

**Files:**
- Modify: `routes/autotoca_iata.py`
- Test: `tests/test_iata.py`

- [ ] **Step 1: Write the failing test**

```python
import json as _json


def test_pipeline_gera_ata_com_continuidade(db_path, monkeypatch):
    """A reunião nova cita só uma das duas oportunidades da ata anterior:
    a outra precisa entrar como 'sem update'."""
    header_ant = {'title': 'Ata Anterior', 'meeting_date': None, 'meeting_time': None,
                  'topic': '', 'participants': []}
    managers_ant = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'Proposta enviada',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None},
            {'name': 'Observabilidade', 'previous_status': None,
             'update_text': 'Aguardando budget', 'responsible': 'Ana',
             'carried_over': False, 'prev_opportunity_id': None}]}]}]
    anterior_id = toca._iata_save_record(header_ant, managers_ant, {}, 'texto', None)

    resposta_ia = _json.dumps({
        'title': 'Pipeline 04/08', 'meeting_date': '04/08/2026', 'meeting_time': '10:00',
        'topic': 'Funil', 'participants': [{'name': 'Ana', 'role': 'Gerente'}],
        'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Migração SAP', 'update': 'Cliente pediu desconto',
             'responsible': 'Bruno'}]}]}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia)

    task_id = 'teste123'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, 'transcrição qualquer',
                             previous_record_id=anterior_id, with_insights=False)

    task = toca._iata_task_get(task_id)
    assert task['status'] == 'done', task.get('error')
    registro = toca._iata_load_record(task['result']['id'])
    opps = {o['name']: o for o in registro['managers'][0]['accounts'][0]['opportunities']}
    assert opps['Migração SAP']['previous_status'] == 'Proposta enviada'
    assert opps['Migração SAP']['update_text'] == 'Cliente pediu desconto'
    assert opps['Observabilidade']['update_text'] == toca.iata_lib.SEM_UPDATE
    assert opps['Observabilidade']['carried_over'] is True
    assert registro['previous_record_id'] == anterior_id


def test_pipeline_falha_quando_llm_nao_responde(db_path, monkeypatch):
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: None)
    task_id = 'teste_erro'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, 'texto', previous_record_id=None,
                             with_insights=False)
    task = toca._iata_task_get(task_id)
    assert task['status'] == 'error'
    assert 'IA' in (task.get('error') or '')


def test_post_inicia_task_e_retorna_202(client, db_path, monkeypatch):
    monkeypatch.setattr(toca, '_iata_process_async', lambda *a, **k: None)
    resp = client.post('/api/autotoca/iata', data={'raw_text': 'transcrição'})
    assert resp.status_code == 202
    assert resp.get_json().get('task_id')


def test_post_sem_conteudo_retorna_400(client, db_path):
    assert client.post('/api/autotoca/iata', data={}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k "pipeline or post_" -v`
Expected: FAIL — `_iata_process_async` não existe com essa assinatura.

- [ ] **Step 3: Implementar**

Acrescentar a `routes/autotoca_iata.py`. Os helpers de extração de texto e de
task vêm do bloco antigo do `app.py:9575-9950` — copiar `_iata_extract_file_text`,
`_parse_vtt_text`, `_parse_srt_text`, `_iata_extract_bytes`, `_iata_task_set`,
`_iata_task_get`, `_iata_task_cleanup` e a classe `_BytesFS` para cá **sem
alterações** (a remoção do original acontece na Task 14).

```python
def _iata_resolver_ambiguidade(pares):
    """Desempata oportunidades parecidas em UMA chamada de IA, em lote."""
    if not pares:
        return {}
    prompt = (
        "Você recebe pares de oportunidades comerciais. Para cada par, diga se a "
        "oportunidade nova é a MESMA da lista de candidatas anteriores.\n"
        "Retorne EXCLUSIVAMENTE JSON: "
        '{"decisoes":[{"index":0,"id_anterior":123}]}. '
        "Use id_anterior null quando for uma oportunidade diferente.\n\n"
        + json.dumps(pares, ensure_ascii=False)
    )
    raw = _llm_prompt(prompt, log_tag='iAta/Ambiguidade')
    parsed = iata_lib._loads_tolerante(raw) if raw else None
    if not isinstance(parsed, dict):
        return {}
    saida = {}
    for d in (parsed.get('decisoes') or []):
        if isinstance(d, dict) and d.get('index') is not None:
            try:
                saida[int(d['index'])] = d.get('id_anterior')
            except Exception:
                continue
    return saida


def _iata_previous_managers(previous_record_id):
    if not previous_record_id:
        return []
    anterior = _iata_load_record(previous_record_id)
    return (anterior or {}).get('managers') or []


def _iata_process_async(task_id, file_bytes, filename, raw_text_input,
                        previous_record_id=None, with_insights=True):
    try:
        raw_text = (raw_text_input or '').strip()
        if file_bytes:
            _iata_task_set(task_id, {'step': 'Extraindo texto do arquivo...', 'progress': 15})
            texto_arquivo = _iata_extract_bytes(file_bytes, filename)
            raw_text = (texto_arquivo + '\n\n' + raw_text).strip() if raw_text else texto_arquivo
        if not raw_text:
            _iata_task_set(task_id, {'status': 'error',
                                     'error': 'Não foi possível extrair texto da reunião.'})
            return

        if len(raw_text) > iata_lib.MAX_TRANSCRICAO_CHARS:
            # O risco registrado no spec: transcrição longa demais para o contexto
            # do modelo. Truncar é aceitável por ora, mas precisa ficar no log —
            # é o sinal de que chegou a hora de dividir a extração por gerente.
            logger.warning(f'[iAta][Task:{task_id}] Transcrição truncada de '
                           f'{len(raw_text)} para {iata_lib.MAX_TRANSCRICAO_CHARS} caracteres.')

        _iata_task_set(task_id, {'step': 'Extraindo contas e oportunidades...', 'progress': 35})
        raw = _llm_prompt(iata_lib.build_extraction_prompt(raw_text), log_tag='iAta/Extração')
        parsed = iata_lib.parse_hierarchy(raw) if raw else None
        if not parsed:
            _iata_task_set(task_id, {
                'status': 'error',
                'error': 'A IA não retornou uma ata utilizável. Tente novamente.'})
            return

        _iata_task_set(task_id, {'step': 'Cruzando contas com o CRM...', 'progress': 55})
        _iata_sugerir_contas(parsed['managers'])

        _iata_task_set(task_id, {'step': 'Comparando com a ata anterior...', 'progress': 70})
        managers = iata_lib.reconcile(
            parsed['managers'], _iata_previous_managers(previous_record_id),
            resolver=_iata_resolver_ambiguidade)

        extras = {}
        if with_insights:
            _iata_task_set(task_id, {'step': 'Gerando insights de negócio...', 'progress': 85})
            extras['insights'] = _iata_insights_ofertas(parsed['header'], managers)

        _iata_task_set(task_id, {'step': 'Salvando ata...', 'progress': 95})
        record_id = _iata_save_record(parsed['header'], managers, extras, raw_text,
                                      previous_record_id)
        registro = _iata_load_record(record_id)
        _iata_task_set(task_id, {'step': 'Concluído!', 'progress': 100,
                                 'status': 'done', 'result': registro})
    except Exception as e:
        logger.exception(f'[iAta][Task:{task_id}] Erro: {e}')
        _iata_task_set(task_id, {'status': 'error', 'error': str(e)})
    finally:
        _iata_task_cleanup(task_id)


@app.route('/api/autotoca/iata', methods=['POST'])
def create_iata_record():
    try:
        file_obj = request.files.get('meeting_file')
        raw_text_input = (request.form.get('raw_text') or '').strip()
        if not file_obj and not raw_text_input:
            return jsonify({'error': 'Envie um arquivo de reunião ou cole o texto.'}), 400

        file_bytes, filename = None, None
        if file_obj and file_obj.filename:
            file_bytes = file_obj.read()
            filename = file_obj.filename

        previous_record_id = request.form.get('previous_record_id') or None
        if previous_record_id:
            try:
                previous_record_id = int(previous_record_id)
            except ValueError:
                previous_record_id = None
        with_insights = (request.form.get('with_insights') or '1') != '0'

        task_id = uuid.uuid4().hex
        _iata_task_set(task_id, {'status': 'processing', 'step': 'Iniciando...', 'progress': 5})
        threading.Thread(
            target=_iata_process_async,
            args=(task_id, file_bytes, filename, raw_text_input),
            kwargs={'previous_record_id': previous_record_id, 'with_insights': with_insights},
            daemon=True).start()
        return jsonify({'task_id': task_id}), 202
    except Exception as e:
        logger.exception(f'[iAta] Erro ao iniciar tarefa: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/autotoca/iata/tasks/<task_id>', methods=['GET'])
def get_iata_task_status(task_id):
    task = _iata_task_get(task_id)
    if not task:
        return jsonify({'status': 'error', 'error': 'Tarefa não encontrada ou expirada.'}), 404
    return jsonify(task)
```

Para o teste conseguir usar `toca.iata_lib`, o import no topo do módulo já
expõe o nome no namespace do `app` (é `from integrations import iata as iata_lib`).

`_iata_sugerir_contas` e `_iata_insights_ofertas` entram na Task 8; enquanto
isso, criar stubs no mesmo arquivo para o pipeline rodar:

```python
def _iata_sugerir_contas(managers):
    return managers


def _iata_insights_ofertas(header, managers):
    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/autotoca_iata.py tests/test_iata.py && git commit -m "feat(iata): geracao assincrona com continuidade entre atas"
```

---

### Task 8: Sugestão de conta do CRM, confirmação e insights

**Files:**
- Modify: `routes/autotoca_iata.py`
- Test: `tests/test_iata.py`

- [ ] **Step 1: Write the failing test**

```python
def test_sugerir_contas_casa_por_nome_normalizado(db_path, monkeypatch):
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.commit()
    account_id = conn.execute("SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    conn.close()

    managers = [{'name': 'Ana', 'accounts': [
        {'name': 'AMBEV S/A', 'account_id': None, 'match_confidence': None,
         'opportunities': []},
        {'name': 'Empresa Que Não Existe', 'account_id': None, 'match_confidence': None,
         'opportunities': []}]}]

    toca._iata_sugerir_contas(managers)

    casada, orfa = managers[0]['accounts']
    assert casada['account_id'] == account_id
    assert casada['match_confidence'] == 'alta'
    assert casada.get('match_confirmed') is not True, 'sugestão não confirma sozinha'
    assert orfa['account_id'] is None


def test_link_confirma_vinculo_da_conta(client, db_path):
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.commit()
    account_id = conn.execute("SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    conn.close()

    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': 'alta', 'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    conta_id = toca._iata_load_record(rid)['managers'][0]['accounts'][0]['id']

    resp = client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_id}/link',
                       json={'account_id': account_id})
    assert resp.status_code == 200

    conta = toca._iata_load_record(rid)['managers'][0]['accounts'][0]
    assert conta['account_id'] == account_id
    assert conta['match_confirmed'] == 1


def test_link_com_account_id_nulo_desfaz_o_vinculo(client, db_path):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    conta_id = toca._iata_load_record(rid)['managers'][0]['accounts'][0]['id']

    resp = client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_id}/link',
                       json={'account_id': None})
    assert resp.status_code == 200
    assert toca._iata_load_record(rid)['managers'][0]['accounts'][0]['account_id'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k "sugerir or link_" -v`
Expected: FAIL — o stub de `_iata_sugerir_contas` não casa nada e a rota `/link` não existe.

- [ ] **Step 3: Implementar (substituindo os stubs da Task 7)**

```python
def _iata_sugerir_contas(managers):
    """Sugere o vínculo com `accounts` por nome normalizado. Nunca confirma
    sozinho — quem confirma é o usuário, pela rota /link."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT id, name FROM accounts')
        catalogo = {iata_lib.normalize_name(r['name']): r['id'] for r in c.fetchall()}
    finally:
        conn.close()

    for manager in (managers or []):
        for account in (manager.get('accounts') or []):
            norm = iata_lib.normalize_name(account.get('name'))
            if not norm:
                continue
            if norm in catalogo:
                account['account_id'] = catalogo[norm]
                account['match_confidence'] = 'alta'
                continue
            proximos = difflib.get_close_matches(norm, list(catalogo.keys()), n=1, cutoff=0.85)
            if proximos:
                account['account_id'] = catalogo[proximos[0]]
                account['match_confidence'] = 'media'
    return managers


def _iata_insights_ofertas(header, managers):
    """Cruza as oportunidades com as ofertas do portfólio STF."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute('SELECT title, description FROM portfolio_offers ORDER BY title')
        ofertas = [dict_from_row(r) for r in c.fetchall()]
    finally:
        conn.close()
    if not ofertas:
        return []

    resumo = [
        {'conta': a.get('name'), 'oportunidade': o.get('name'), 'update': o.get('update_text')}
        for m in (managers or []) for a in (m.get('accounts') or [])
        for o in (a.get('opportunities') or [])
    ]
    if not resumo:
        return []

    prompt = (
        "Você é consultor de negócios. Para as oportunidades abaixo, identifique dores "
        "e cruze com as soluções do portfólio.\n"
        "Retorne EXCLUSIVAMENTE JSON: "
        '{"insights":[{"pain":"dor","matched_offer":"título da oferta ou null",'
        '"confidence":"alta/media/baixa","observation":"observação breve"}]}\n\n'
        f"OPORTUNIDADES:\n{json.dumps(resumo, ensure_ascii=False)[:12000]}\n\n"
        f"SOLUÇÕES STF:\n{json.dumps(ofertas, ensure_ascii=False)[:12000]}"
    )
    raw = _llm_prompt(prompt, log_tag='iAta/Insights')
    parsed = iata_lib._loads_tolerante(raw) if raw else None
    if not isinstance(parsed, dict):
        logger.warning('[iAta] Insights sem resposta utilizável da IA.')
        return []
    return [i for i in (parsed.get('insights') or []) if isinstance(i, dict)]


@app.route('/api/autotoca/iata/<int:record_id>/accounts/<int:iata_account_id>/link',
           methods=['POST'])
def link_iata_account(record_id, iata_account_id):
    try:
        payload = request.get_json(silent=True) or {}
        account_id = payload.get('account_id')
        if account_id is not None:
            try:
                account_id = int(account_id)
            except (TypeError, ValueError):
                return jsonify({'error': 'account_id inválido.'}), 400

        conn = get_db()
        c = conn.cursor()
        c.execute('''UPDATE iata_accounts SET account_id = ?, match_confirmed = ?
                     WHERE id = ? AND record_id = ?''',
                  (account_id, 1 if account_id is not None else 0, iata_account_id, record_id))
        alterados = c.rowcount
        conn.commit()
        conn.close()
        if not alterados:
            return jsonify({'error': 'Conta da ata não encontrada.'}), 404
        return jsonify({'message': 'Vínculo atualizado.'})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao vincular conta {iata_account_id}: {e}')
        return jsonify({'error': str(e)}), 500
```

Adicionar `import difflib` no topo de `routes/autotoca_iata.py`.
Antes de escrever, confirmar as colunas reais de `portfolio_offers`
(`app.py:668`) — se não houver `description`, ajustar o `SELECT`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/autotoca_iata.py tests/test_iata.py && git commit -m "feat(iata): sugestao de conta do crm e insights"
```

---

### Task 9: Edição do texto e re-parse

**Files:**
- Modify: `routes/autotoca_iata.py`
- Modify: `integrations/iata/llm.py` (prompt de re-parse — mesmo arquivo de
  `build_extraction_prompt`/`parse_hierarchy`; reexportar `build_reparse_prompt`
  em `integrations/iata/__init__.py`)
- Test: `tests/test_iata.py`

Regra do desenho: o texto do usuário é gravado **antes** do re-parse. Se o
re-parse falhar, o texto fica e a falha vira aviso visível.

- [ ] **Step 1: Write the failing test**

```python
def test_put_body_salva_texto_e_atualiza_hierarquia(client, db_path, monkeypatch):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'antigo',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': 7}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: _json.dumps({
        'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev',
            'opportunities': [{'name': 'Migração SAP', 'update': 'texto editado à mão',
                               'responsible': 'Bruno'}]}]}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body',
                      json={'body_markdown': 'Gerente Comercial: Ana\n...'})
    assert resp.status_code == 200
    assert resp.get_json()['reparse_failed'] is False

    registro = toca._iata_load_record(rid)
    assert registro['body_markdown'].startswith('Gerente Comercial: Ana')
    assert registro['body_edited'] == 1
    opp = registro['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['update_text'] == 'texto editado à mão'
    assert opp['prev_opportunity_id'] == 7, 'o encadeamento com a ata anterior se mantém'


def test_put_body_preserva_texto_quando_reparse_falha(client, db_path, monkeypatch):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'original',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'desculpe, não consegui')

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'meu texto'})
    assert resp.status_code == 200
    assert resp.get_json()['reparse_failed'] is True

    registro = toca._iata_load_record(rid)
    assert registro['body_markdown'] == 'meu texto', 'o texto do usuário nunca se perde'
    assert registro['reparse_failed'] == 1
    opp = registro['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['update_text'] == 'original', 'estrutura antiga preservada'


def test_put_body_vazio_retorna_400(client, db_path):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    rid = toca._iata_save_record(header, [], {}, 'texto', None)
    assert client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': '  '}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k put_body -v`
Expected: FAIL — 405/404 (rota inexistente).

- [ ] **Step 3: Implementar o prompt de re-parse em `integrations/iata/llm.py`**

```python
def build_reparse_prompt(body_markdown):
    return (
        "O texto abaixo é uma ata de reunião comercial editada à mão. "
        "Converta-a de volta para JSON, preservando exatamente o conteúdo escrito.\n"
        "Retorne EXCLUSIVAMENTE JSON válido:\n"
        '{"title":"Título","meeting_date":"DD/MM/AAAA ou null","meeting_time":"HH:MM ou null",'
        '"topic":"Tema","participants":[{"name":"Nome","role":""}],'
        '"managers":[{"name":"Gerente","accounts":[{"name":"Conta",'
        '"opportunities":[{"name":"Oportunidade","update":"texto do Update",'
        '"responsible":"texto do Responsável"}]}]}]}\n'
        "REGRAS:\n"
        "- Não reescreva, não resuma e não corrija o texto — apenas estruture;\n"
        "- Quando a linha da oportunidade tiver 'Nome: status', o status é o histórico "
        "anterior e NÃO deve ir para 'update';\n"
        "- Preserve a ordem em que gerentes, contas e oportunidades aparecem.\n\n"
        f"ATA:\n{(body_markdown or '')[:MAX_TRANSCRICAO_CHARS]}"
    )
```

- [ ] **Step 4: Implementar a rota em `routes/autotoca_iata.py`**

```python
@app.route('/api/autotoca/iata/<int:record_id>/body', methods=['PUT'])
def update_iata_body(record_id):
    try:
        payload = request.get_json(silent=True) or {}
        body = (payload.get('body_markdown') or '').strip()
        if not body:
            return jsonify({'error': 'O corpo da ata não pode ficar vazio.'}), 400

        atual = _iata_load_record(record_id)
        if not atual:
            return jsonify({'error': 'Ata não encontrada.'}), 404

        # 1) grava o texto ANTES de qualquer coisa: o que o usuário escreveu não se perde.
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE iata_records SET body_markdown = ?, body_edited = 1 WHERE id = ?',
                  (body, record_id))
        conn.commit()
        conn.close()

        # 2) tenta trazer o texto de volta para a hierarquia.
        raw = _llm_prompt(iata_lib.build_reparse_prompt(body), log_tag='iAta/Reparse')
        parsed = iata_lib.parse_hierarchy(raw) if raw else None
        if not parsed:
            logger.warning(f'[iAta] Re-parse falhou para a ata {record_id}; '
                           'texto preservado, estrutura mantida.')
            conn = get_db()
            conn.execute('UPDATE iata_records SET reparse_failed = 1 WHERE id = ?', (record_id,))
            conn.commit()
            conn.close()
            return jsonify({'message': 'Texto salvo.', 'reparse_failed': True})

        # 3) preserva prev_opportunity_id e account_id do que continua casando por name_norm.
        anteriores_opp, anteriores_conta = {}, {}
        for m in atual['managers']:
            for a in m['accounts']:
                anteriores_conta[iata_lib.normalize_name(a['name'])] = a
                for o in a['opportunities']:
                    chave = (iata_lib.normalize_name(a['name']),
                             iata_lib.normalize_name(o['name']))
                    anteriores_opp[chave] = o

        for m in parsed['managers']:
            for a in m['accounts']:
                conta_norm = iata_lib.normalize_name(a['name'])
                antiga_conta = anteriores_conta.get(conta_norm) or {}
                a['account_id'] = antiga_conta.get('account_id')
                a['match_confirmed'] = antiga_conta.get('match_confirmed')
                a['match_confidence'] = antiga_conta.get('match_confidence')
                for o in a['opportunities']:
                    antiga = anteriores_opp.get(
                        (conta_norm, iata_lib.normalize_name(o['name']))) or {}
                    o['previous_status'] = antiga.get('previous_status')
                    o['prev_opportunity_id'] = antiga.get('prev_opportunity_id')
                    o['carried_over'] = bool(antiga.get('carried_over'))
                    o['responsible'] = o.get('responsible') or m.get('name')

        conn = get_db()
        c = conn.cursor()
        _iata_write_hierarchy(c, record_id, parsed['managers'])
        c.execute('''UPDATE iata_records SET reparse_failed = 0, title = ?, ata_json = ?
                     WHERE id = ?''',
                  (parsed['header'].get('title') or atual['title'],
                   json.dumps({'header': parsed['header'], 'managers': parsed['managers'],
                               'extras': atual.get('extras') or {}}, ensure_ascii=False),
                   record_id))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Ata atualizada.', 'reparse_failed': False})
    except Exception as e:
        logger.exception(f'[iAta] Erro ao salvar corpo da ata {record_id}: {e}')
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add routes/autotoca_iata.py integrations/iata/llm.py integrations/iata/__init__.py tests/test_iata.py && git commit -m "feat(iata): edicao do texto com reparse tolerante a falha"
```

---

### Task 10: Preview e envio por e-mail

**Files:**
- Modify: `routes/autotoca_iata.py`
- Test: `tests/test_iata.py`

`_outlook_send_mail` (`app.py:7539`) aceita **um** destinatário; vários viram um
envio por endereço, com relatório individual.

- [ ] **Step 1: Write the failing test**

```python
def _ata_para_email(db_path):
    header = {'title': 'Pipeline Semanal', 'meeting_date': '04/08/2026',
              'meeting_time': '10:00', 'topic': 'Funil', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': 'Proposta enviada',
             'update_text': 'Desconto pedido', 'responsible': 'Bruno',
             'carried_over': False, 'prev_opportunity_id': None}]}]}]
    return toca._iata_save_record(header, managers, {}, 'texto', None)


def test_preview_devolve_assunto_e_html(client, db_path):
    rid = _ata_para_email(db_path)
    resp = client.get(f'/api/autotoca/iata/{rid}/email/preview')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['subject'] == 'Ata — Pipeline Semanal — 04/08/2026'
    assert '<ul' in payload['html'] and 'Migração SAP' in payload['html']


def test_email_envia_um_por_destinatario(client, db_path, monkeypatch):
    rid = _ata_para_email(db_path)
    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: enviados.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email',
                       json={'to': ['ana@x.com', 'bruno@x.com']})

    assert resp.status_code == 200
    assert enviados == ['ana@x.com', 'bruno@x.com']
    assert all(r['ok'] for r in resp.get_json()['results'])


def test_email_reporta_falha_por_destinatario(client, db_path, monkeypatch):
    rid = _ata_para_email(db_path)

    def fake_send(to, subject, html, attachments=None):
        if to == 'quebra@x.com':
            raise RuntimeError('caixa cheia')

    monkeypatch.setattr(toca, '_outlook_send_mail', fake_send)

    resp = client.post(f'/api/autotoca/iata/{rid}/email',
                       json={'to': ['ok@x.com', 'quebra@x.com']})

    assert resp.status_code == 207
    resultados = {r['to']: r for r in resp.get_json()['results']}
    assert resultados['ok@x.com']['ok'] is True
    assert resultados['quebra@x.com']['ok'] is False
    assert 'caixa cheia' in resultados['quebra@x.com']['error']


def test_email_sem_destinatario_retorna_400(client, db_path):
    rid = _ata_para_email(db_path)
    assert client.post(f'/api/autotoca/iata/{rid}/email', json={'to': []}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iata.py -k email -v`
Expected: FAIL — rotas inexistentes.

- [ ] **Step 3: Implementar**

```python
def _iata_email_payload(record_id):
    registro = _iata_load_record(record_id)
    if not registro:
        return None
    header = registro.get('header') or {
        'title': registro.get('title'), 'meeting_date': registro.get('meeting_date'),
        'meeting_time': registro.get('meeting_time'), 'topic': registro.get('topic'),
        'participants': registro.get('participants') or [],
    }
    extras = registro.get('extras') or {}
    return {
        'subject': iata_lib.email_subject(header),
        'html': iata_lib.render_email_html(header, registro['managers'], extras),
    }


@app.route('/api/autotoca/iata/<int:record_id>/email/preview', methods=['GET'])
def preview_iata_email(record_id):
    payload = _iata_email_payload(record_id)
    if not payload:
        return jsonify({'error': 'Ata não encontrada.'}), 404
    return jsonify(payload)


@app.route('/api/autotoca/iata/<int:record_id>/email', methods=['POST'])
def send_iata_email(record_id):
    try:
        body = request.get_json(silent=True) or {}
        destinatarios = [str(e).strip() for e in (body.get('to') or []) if str(e).strip()]
        if not destinatarios:
            return jsonify({'error': 'Informe ao menos um destinatário.'}), 400

        payload = _iata_email_payload(record_id)
        if not payload:
            return jsonify({'error': 'Ata não encontrada.'}), 404

        resultados = []
        for destino in destinatarios:
            try:
                _outlook_send_mail(destino, payload['subject'], payload['html'])
                resultados.append({'to': destino, 'ok': True})
            except Exception as e:
                logger.warning(f'[iAta] Falha ao enviar ata {record_id} para {destino}: {e}')
                resultados.append({'to': destino, 'ok': False, 'error': str(e)})

        status = 200 if all(r['ok'] for r in resultados) else 207
        logger.info(f'[iAta] Ata {record_id} enviada: {resultados}')
        return jsonify({'results': resultados}), status
    except Exception as e:
        logger.exception(f'[iAta] Erro ao enviar ata {record_id}: {e}')
        return jsonify({'error': str(e)}), 500
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/autotoca_iata.py tests/test_iata.py && git commit -m "feat(iata): preview e envio da ata por email"
```

---

### Task 11: Frontend — painel no AutoToca e saída do Portfolio

**Files:**
- Create: `public/js/autotoca-iata.js`
- Modify: `public/index.html` (linhas 736, 754-758, 866-870, 2016-2022)
- Modify: `public/js/itoca-autotoca.js:3517-3528`

- [ ] **Step 1: Adicionar o botão e o painel no AutoToca**

Em `public/index.html`, na fileira de botões do AutoToca (após
`autoTocaBtn_reembolsos`, linha 870):

```html
                <button id="autoTocaBtn_iata" class="btn btn-auto-mapping" onclick="toggleAutoTocaAutomation('iata')"><span class="ai-star-icon">✦</span> iAta</button>
```

E, depois do painel `autoTocaReembolsos` (linha 1076 em diante, ao fim do
bloco), acrescentar:

```html
            <div id="autoTocaIAta" style="display:none; background:#fff; border:1px solid #e5e7eb; border-radius:12px; padding:16px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; gap:8px; flex-wrap:wrap;">
                    <div>
                        <div style="font-weight:700; color:#065f46;">Atas de reunião</div>
                        <div style="font-size:12px; color:#6b7280;">Gerente Comercial → Conta → Oportunidade, com o status da ata anterior carregado.</div>
                    </div>
                    <button class="btn btn-auto-mapping btn-small" onclick="openIAtaModal()"><span class="ai-star-icon">✦</span> + Nova Ata</button>
                </div>
                <div id="iataContent"></div>
            </div>
```

Antes de escrever, ler `toggleAutoTocaAutomation` em
`public/js/itoca-autotoca.js` e verificar como ela mapeia a chave da automação
para o id do painel (`autoTocaChamadoJuridico`, `autoTocaReembolsos`, ...). Se
o mapeamento for por dicionário explícito, acrescentar `iata: 'autoTocaIAta'` e
chamar `loadIAta()` ao abrir; se for por convenção de nome, seguir a convenção.

- [ ] **Step 2: Remover a sub-aba do Portfolio**

Em `public/index.html`, apagar o botão da linha 736
(`portfolioSubBtn_iata`) e o bloco `portfolioSubPanel_iata` (linhas 754-758).

Em `public/js/itoca-autotoca.js:3528`, remover a linha:

```javascript
            else if (subTab === 'iata') loadIAta();
```

E, em `switchPortfolioSubmodule` (linha 3517), remover `'iata'` de qualquer
lista de sub-abas válidas. Se o valor default salvo (`_portfolioCurrentSubTab`,
linha 3514) puder ser `'iata'`, adicionar o fallback:

```javascript
            const _sub = (_portfolioCurrentSubTab === 'iata') ? 'stf' : (_portfolioCurrentSubTab || 'stf');
            switchPortfolioSubmodule(_sub);
```

Sem isso, quem tinha a sub-aba iAta aberta abre o Portfolio num painel que não
existe mais.

- [ ] **Step 3: Criar `public/js/autotoca-iata.js` com a listagem**

Mover para cá as funções `loadIAta`, `renderIAtaHistory`, `deleteIAtaRecord`
(hoje em `public/js/itoca-autotoca.js:3915-3990` e `:4462`), trocando
`${API_BASE}/portfolio/iata` por `${API_BASE}/autotoca/iata`. A listagem passa a
usar os campos novos:

```javascript
        // ─── iAta (AutoToca) ───────────────────────────────────────────────
        let iataRecords = [];

        async function loadIAta() {
            const container = document.getElementById('iataContent');
            if (!container) return;
            container.innerHTML = '<p style="color:#6b7280;">Carregando histórico de atas...</p>';
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata`);
                const payload = await response.json().catch(() => []);
                if (!response.ok) throw new Error(payload.error || 'Erro ao carregar atas.');
                iataRecords = Array.isArray(payload) ? payload : [];
                renderIAtaHistory(iataRecords);
            } catch (error) {
                container.innerHTML = `<div class="alert alert-error" style="display:block;">${escapeHtml(error.message || 'Erro ao carregar histórico de atas.')}</div>`;
            }
        }

        function renderIAtaHistory(records = []) {
            const container = document.getElementById('iataContent');
            if (!container) return;
            if (!records.length) {
                container.innerHTML = `<div class="empty-state"><div class="empty-state-icon">📋</div><h3>Nenhuma ata gerada</h3><p>Clique em "+ Nova Ata" para gerar a ata de uma reunião com IA.</p></div>`;
                return;
            }
            container.innerHTML = records.map(record => {
                const rid = Number(record.id);
                const quando = [record.meeting_date, record.meeting_time].filter(Boolean).join(' ');
                const aviso = record.reparse_failed
                    ? `<p style="margin:4px 0 0; font-size:12px; color:#b45309;"><i class="fas fa-exclamation-triangle"></i> Estrutura desatualizada após edição manual</p>`
                    : '';
                const editada = record.body_edited
                    ? `<span style="font-size:11px; color:#6b7280;">· editada</span>` : '';
                return `
                    <div class="history-item" style="border:1px solid rgba(16,185,129,.25); border-radius:12px; margin-bottom:10px; background:#fff; padding:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                            <div style="flex:1; min-width:0; cursor:pointer;" onclick="viewIAtaFull(${rid})">
                                <div style="display:flex; align-items:center; gap:8px; color:#065f46; flex-wrap:wrap;">
                                    <i class="fas fa-file-alt"></i>
                                    <h3 style="margin:0; font-size:15px;">${escapeHtml(record.title || 'Ata sem título')}</h3>
                                    <span style="font-size:12px; color:#6b7280; font-weight:400;">${escapeHtml(quando)}</span>
                                    ${editada}
                                </div>
                                ${aviso}
                            </div>
                            <div style="display:flex; gap:6px; flex-shrink:0;">
                                <button class="btn btn-secondary btn-small" onclick="viewIAtaFull(${rid})" title="Abrir"><i class="fas fa-eye"></i></button>
                                <button class="btn btn-danger btn-small" onclick="deleteIAtaRecord(${rid})" title="Excluir"><i class="fas fa-trash"></i></button>
                            </div>
                        </div>
                    </div>`;
            }).join('');
        }

        async function deleteIAtaRecord(rid) {
            if (!await uiConfirm('Deseja realmente excluir esta ata?', 'Excluir Ata')) return;
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}`, { method: 'DELETE' });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao excluir ata.');
                showSuccess('Ata excluída com sucesso.');
                await loadIAta();
            } catch (error) {
                showError(error.message || 'Erro ao excluir ata.');
            }
        }
```

`uiConfirm` é obrigatório — `confirm()` nativo é proibido no projeto.

- [ ] **Step 4: Carregar o script novo**

Em `public/index.html`, após a linha 2016 (`/js/itoca-autotoca.js`):

```html
    <script src="/js/autotoca-iata.js"></script>
```

- [ ] **Step 5: Verificar no navegador**

Subir o app com a ferramenta de preview (nunca `python app.py` via Bash), abrir
o AutoToca e confirmar: o botão iAta aparece, o painel abre, a listagem carrega
(ou mostra o estado vazio), e o Portfolio não tem mais a sub-aba iAta. Checar
`read_console_messages` — nenhum `ReferenceError` de função removida.

- [ ] **Step 6: Commit**

```bash
git add public/index.html public/js/autotoca-iata.js public/js/itoca-autotoca.js && git commit -m "feat(iata): painel no autotoca e saida do portfolio"
```

---

### Task 12: Frontend — modal com base da ata e progresso

**Files:**
- Modify: `public/js/autotoca-iata.js`

- [ ] **Step 1: Implementar o modal**

Acrescentar a `public/js/autotoca-iata.js`. Passo 0 escolhe a base; o restante
segue o padrão de progresso do projeto (barra verde + `coelho-correndo.webp`).

```javascript
        function openIAtaModal() {
            const modalId = 'iataNewModal';
            document.getElementById(modalId)?.remove();
            const opcoes = iataRecords.map(r =>
                `<option value="${Number(r.id)}">${escapeHtml(r.title || 'Ata sem título')}${r.meeting_date ? ' — ' + escapeHtml(r.meeting_date) : ''}</option>`
            ).join('');
            const html = `
                <div class="modal active" id="${modalId}">
                    <div class="modal-content" style="max-width:680px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-file-alt"></i> Nova Ata — iAta</h2>
                            <button class="modal-close" id="iataModalCloseBtn" onclick="document.getElementById('${modalId}').remove()">&#215;</button>
                        </div>
                        <div id="iataFormArea">
                            <div class="form-group">
                                <label>Base da ata</label>
                                <div style="display:flex; flex-direction:column; gap:6px; font-size:13px;">
                                    <label><input type="radio" name="iataBase" value="historico" checked onchange="_iataToggleBase()"> Continuar a partir de uma ata do histórico</label>
                                    <label><input type="radio" name="iataBase" value="upload" onchange="_iataToggleBase()"> Enviar o arquivo da ata anterior</label>
                                    <label><input type="radio" name="iataBase" value="zero" onchange="_iataToggleBase()"> Começar uma ata totalmente nova</label>
                                </div>
                            </div>
                            <div class="form-group" id="iataBaseHistorico">
                                <label>Ata anterior</label>
                                <select id="iataPreviousSelect">${opcoes || '<option value="">Nenhuma ata salva ainda</option>'}</select>
                            </div>
                            <div class="form-group" id="iataBaseUpload" style="display:none;">
                                <label>Arquivo da ata anterior</label>
                                <input id="iataPreviousFile" type="file" accept=".pdf,.docx,.txt,.vtt,.srt">
                            </div>
                            <hr style="border:none; border-top:1px solid #e5e7eb; margin:16px 0;">
                            <div class="form-group">
                                <label>Arquivo da reunião de agora</label>
                                <input id="iataFileInput" type="file" accept=".pdf,.doc,.docx,.txt,.vtt,.srt,.csv,text/plain,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document">
                                <small style="color:#9ca3af; font-size:11px; display:block; margin-top:4px;">PDF, DOCX, TXT, VTT (Teams), SRT</small>
                            </div>
                            <div class="form-group">
                                <label>OU cole o texto da reunião</label>
                                <textarea id="iataRawTextInput" rows="7" placeholder="Cole aqui a transcrição, notas ou chat da reunião..."></textarea>
                            </div>
                            <div class="form-group">
                                <label style="font-size:13px;"><input type="checkbox" id="iataWithInsights" checked> Incluir insights de negócio (cruzamento com as Soluções STF)</label>
                            </div>
                        </div>
                        <div id="iataProgressArea" style="display:none; padding:20px 4px 12px;">
                            <div style="font-size:13px; color:#6b7280; margin-bottom:12px; text-align:center;" id="iataProgressStep">Iniciando...</div>
                            <div style="position:relative; background:#d1fae5; border-radius:99px; height:12px; overflow:visible; margin:0 16px 6px;">
                                <div id="iataProgressBar" style="position:relative; height:100%; width:5%; background:linear-gradient(90deg,#059669,#10b981,#34d399); border-radius:99px; transition:width .6s ease;">
                                    <img src="/images/coelho-correndo.webp" class="coelho-run" alt="">
                                </div>
                            </div>
                            <div style="display:flex; justify-content:flex-end; padding:0 16px;">
                                <div style="font-size:11px; color:#6b7280;" id="iataProgressPct">5%</div>
                            </div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
                            <button id="iataCancelBtn" class="btn btn-secondary" onclick="document.getElementById('${modalId}').remove()">Cancelar</button>
                            <button id="iataSubmitBtn" class="btn btn-auto-mapping btn-small" onclick="submitIAta()">
                                <span class="ai-star-icon">✦</span> Gerar Ata com IA
                            </button>
                        </div>
                    </div>
                </div>`;
            document.body.insertAdjacentHTML('beforeend', html);
        }

        function _iataToggleBase() {
            const escolha = document.querySelector('input[name="iataBase"]:checked')?.value;
            document.getElementById('iataBaseHistorico').style.display = escolha === 'historico' ? '' : 'none';
            document.getElementById('iataBaseUpload').style.display = escolha === 'upload' ? '' : 'none';
        }

        function _iataSetProgress(pct, step) {
            const bar = document.getElementById('iataProgressBar');
            const stepEl = document.getElementById('iataProgressStep');
            const pctEl = document.getElementById('iataProgressPct');
            if (bar) bar.style.width = Math.max(5, pct) + '%';
            if (stepEl) stepEl.textContent = step || '';
            if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        }
```

- [ ] **Step 2: Implementar o envio**

```javascript
        async function submitIAta() {
            const file = document.getElementById('iataFileInput')?.files?.[0] || null;
            const rawText = (document.getElementById('iataRawTextInput')?.value || '').trim();
            if (!file && !rawText) {
                showError('Envie um arquivo ou cole o texto da reunião.');
                return;
            }
            const base = document.querySelector('input[name="iataBase"]:checked')?.value || 'zero';
            const previousId = document.getElementById('iataPreviousSelect')?.value;
            const previousFile = document.getElementById('iataPreviousFile')?.files?.[0] || null;
            if (base === 'historico' && !previousId) {
                showError('Escolha a ata anterior ou marque "Começar uma ata totalmente nova".');
                return;
            }
            if (base === 'upload' && !previousFile) {
                showError('Envie o arquivo da ata anterior.');
                return;
            }

            const btn = document.getElementById('iataSubmitBtn');
            const cancelBtn = document.getElementById('iataCancelBtn');
            const formArea = document.getElementById('iataFormArea');
            const progressArea = document.getElementById('iataProgressArea');
            if (btn) btn.style.display = 'none';
            if (cancelBtn) cancelBtn.style.display = 'none';
            if (formArea) formArea.style.display = 'none';
            if (progressArea) progressArea.style.display = 'block';
            _iataSetProgress(5, 'Enviando arquivo...');

            try {
                const fd = new FormData();
                if (file) fd.append('meeting_file', file);
                if (rawText) fd.append('raw_text', rawText);
                if (base === 'historico') fd.append('previous_record_id', previousId);
                if (base === 'upload') fd.append('previous_file', previousFile);
                fd.append('with_insights', document.getElementById('iataWithInsights')?.checked ? '1' : '0');

                const response = await fetch(`${API_BASE}/autotoca/iata`, { method: 'POST', body: fd });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao iniciar processamento.');
                const taskId = payload.task_id;
                if (!taskId) throw new Error('Resposta inesperada do servidor.');

                BgTaskManager.register(
                    taskId,
                    `${API_BASE}/autotoca/iata/tasks/${taskId}`,
                    'Gerando Ata com IA',
                    (typeof _currentTab !== 'undefined' ? _currentTab : 'autotoca'),
                    (record) => {
                        document.getElementById('iataNewModal')?.remove();
                        showSuccess('Ata gerada com sucesso!');
                        loadIAta().then(() => { if (record && record.id) viewIAtaFull(record.id); });
                    },
                    (errMsg) => {
                        showError(errMsg || 'Erro ao processar reunião com IA.');
                        if (btn) btn.style.display = '';
                        if (cancelBtn) cancelBtn.style.display = '';
                        if (formArea) formArea.style.display = '';
                        if (progressArea) progressArea.style.display = 'none';
                    },
                    (pct, step) => _iataSetProgress(pct, step)
                );
            } catch (error) {
                showError(error.message || 'Erro ao processar reunião com IA.');
                if (btn) btn.style.display = '';
                if (cancelBtn) cancelBtn.style.display = '';
                if (formArea) formArea.style.display = '';
                if (progressArea) progressArea.style.display = 'none';
            }
        }
```

- [ ] **Step 3: Suportar `previous_file` no backend**

O `previous_file` da opção (b) precisa virar hierarquia anterior. Em
`routes/autotoca_iata.py`, na rota POST, ler o arquivo:

```python
        prev_file = request.files.get('previous_file')
        prev_bytes, prev_name = None, None
        if prev_file and prev_file.filename:
            prev_bytes = prev_file.read()
            prev_name = prev_file.filename
```

e passar `prev_bytes`/`prev_name` para `_iata_process_async` via kwargs. Em
`_iata_process_async`, antes da reconciliação:

```python
        anteriores = _iata_previous_managers(previous_record_id)
        if not anteriores and prev_bytes:
            _iata_task_set(task_id, {'step': 'Lendo a ata anterior...', 'progress': 25})
            texto_ant = _iata_extract_bytes(prev_bytes, prev_name)
            raw_ant = _llm_prompt(iata_lib.build_reparse_prompt(texto_ant),
                                  log_tag='iAta/AtaAnterior')
            parsed_ant = iata_lib.parse_hierarchy(raw_ant) if raw_ant else None
            if parsed_ant:
                anteriores = parsed_ant['managers']
            else:
                logger.warning('[iAta] Ata anterior enviada não pôde ser lida; '
                               'seguindo como ata do zero.')
                _iata_task_set(task_id, {'warning': 'A ata anterior não pôde ser lida; '
                                                    'esta ata foi gerada do zero.'})
```

e usar `anteriores` na chamada de `iata_lib.reconcile`. Acrescentar um teste em
`tests/test_iata.py` cobrindo o caminho de ata anterior ilegível:

```python
def test_ata_anterior_ilegivel_segue_como_ata_do_zero(db_path, monkeypatch):
    respostas = iter(['não consegui ler', _json.dumps({
        'title': 'Nova', 'managers': [{'name': 'Ana', 'accounts': [
            {'name': 'Ambev', 'opportunities': [{'name': 'Op', 'update': 'u'}]}]}]})])
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: next(respostas))

    task_id = 'prev_ruim'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, 'transcrição',
                             previous_record_id=None, with_insights=False,
                             prev_bytes=b'conteudo ilegivel', prev_name='ata.txt')

    task = toca._iata_task_get(task_id)
    assert task['status'] == 'done'
    assert 'anterior' in (task.get('warning') or '').lower()
```

Atenção à ordem das respostas: a primeira chamada de `_llm_prompt` no pipeline
com `prev_bytes` é a da ata anterior, a segunda é a extração da reunião nova.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_iata.py -v`
Expected: PASS.

- [ ] **Step 5: Verificar no navegador**

Abrir o AutoToca → iAta → **+ Nova Ata**, colar um texto curto de reunião de
pipeline, gerar, e confirmar: barra verde com o coelho correndo, etapas
mudando, ata aberta ao final. Conferir `read_console_messages` e
`preview_logs` (o `app.log` traz `[iAta]`).

- [ ] **Step 6: Commit**

```bash
git add public/js/autotoca-iata.js routes/autotoca_iata.py tests/test_iata.py && git commit -m "feat(iata): modal com base da ata anterior"
```

---

### Task 13: Frontend — visualização, edição e envio

**Files:**
- Modify: `public/js/autotoca-iata.js`

- [ ] **Step 1: Implementar a visualização**

```javascript
        let _iataCurrent = null;

        async function viewIAtaFull(rid) {
            document.getElementById('iataViewModal')?.remove();
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}`);
                const record = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(record.error || 'Erro ao abrir a ata.');
                _iataCurrent = record;
                document.body.insertAdjacentHTML('beforeend', _renderIAtaViewModal(record));
            } catch (error) {
                showError(error.message || 'Erro ao abrir a ata.');
            }
        }

        function _renderIAtaViewModal(record) {
            const aviso = record.reparse_failed
                ? `<div class="alert alert-warning" style="display:block; margin-bottom:12px;">O texto foi salvo, mas a estrutura não pôde ser atualizada — a próxima ata pode não carregar os status corretamente.</div>`
                : '';
            const contas = (record.managers || []).flatMap(m => (m.accounts || []).map(a => ({ manager: m.name, ...a })));
            const revisao = contas.filter(a => a.account_id && !a.match_confirmed).map(a => `
                <div style="display:flex; align-items:center; gap:8px; font-size:12px; margin:4px 0;">
                    <span>Conta <strong>${escapeHtml(a.name)}</strong> → sugerida como conta do CRM (${escapeHtml(a.match_confidence || '')})</span>
                    <button class="btn btn-secondary btn-small" onclick="confirmIAtaAccount(${Number(record.id)}, ${Number(a.id)}, ${Number(a.account_id)})">Confirmar</button>
                    <button class="btn btn-secondary btn-small" onclick="confirmIAtaAccount(${Number(record.id)}, ${Number(a.id)}, null)">Descartar</button>
                </div>`).join('');
            return `
                <div class="modal active" id="iataViewModal">
                    <div class="modal-content" style="max-width:860px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-file-alt"></i> ${escapeHtml(record.title || 'Ata')}</h2>
                            <button class="modal-close" onclick="document.getElementById('iataViewModal').remove()">&#215;</button>
                        </div>
                        ${aviso}
                        ${revisao ? `<div style="background:#fffbeb; border:1px solid #fcd34d; border-radius:8px; padding:10px; margin-bottom:12px;"><div style="font-weight:600; font-size:13px; color:#92400e; margin-bottom:4px;">Contas sugeridas pela IA — confirme o vínculo</div>${revisao}</div>` : ''}
                        <textarea id="iataBodyEditor" rows="22" style="width:100%; font-family:Consolas,monospace; font-size:13px; line-height:1.5;">${escapeHtml(record.body_markdown || '')}</textarea>
                        <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:12px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('iataViewModal').remove()">Fechar</button>
                            <button class="btn btn-secondary" onclick="saveIAtaBody(${Number(record.id)})"><i class="fas fa-save"></i> Salvar texto</button>
                            <button class="btn btn-auto-mapping btn-small" onclick="openIAtaEmailModal(${Number(record.id)})"><span class="ai-star-icon">✦</span> Enviar por e-mail</button>
                        </div>
                    </div>
                </div>`;
        }

        async function confirmIAtaAccount(rid, iataAccountId, accountId) {
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/accounts/${iataAccountId}/link`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ account_id: accountId })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao vincular a conta.');
                showSuccess('Vínculo atualizado.');
                await viewIAtaFull(rid);
            } catch (error) {
                showError(error.message || 'Erro ao vincular a conta.');
            }
        }

        async function saveIAtaBody(rid) {
            const body = document.getElementById('iataBodyEditor')?.value || '';
            if (!body.trim()) { showError('A ata não pode ficar vazia.'); return; }
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/body`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ body_markdown: body })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(payload.error || 'Erro ao salvar a ata.');
                if (payload.reparse_failed) {
                    showError('Texto salvo, mas a estrutura não pôde ser atualizada. A próxima ata pode não carregar os status corretamente.');
                } else {
                    showSuccess('Ata atualizada.');
                }
                await loadIAta();
            } catch (error) {
                showError(error.message || 'Erro ao salvar a ata.');
            }
        }
```

- [ ] **Step 2: Implementar o modal de e-mail com preview**

```javascript
        async function openIAtaEmailModal(rid) {
            document.getElementById('iataEmailModal')?.remove();
            let preview = { subject: '', html: '' };
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/email/preview`);
                preview = await response.json();
                if (!response.ok) throw new Error(preview.error || 'Erro ao gerar o preview.');
            } catch (error) {
                showError(error.message || 'Erro ao gerar o preview do e-mail.');
                return;
            }
            document.body.insertAdjacentHTML('beforeend', `
                <div class="modal active" id="iataEmailModal">
                    <div class="modal-content" style="max-width:820px;">
                        <div class="modal-header">
                            <h2 class="modal-title"><i class="fas fa-envelope"></i> Enviar ata por e-mail</h2>
                            <button class="modal-close" onclick="document.getElementById('iataEmailModal').remove()">&#215;</button>
                        </div>
                        <div class="form-group">
                            <label>Destinatários (separados por vírgula ou ponto e vírgula)</label>
                            <input id="iataEmailTo" type="text" placeholder="fulano@empresa.com, ciclano@empresa.com">
                        </div>
                        <div class="form-group">
                            <label>Assunto</label>
                            <input id="iataEmailSubject" type="text" value="${escapeHtml(preview.subject || '')}" readonly style="background:#f3f4f6; color:#6b7280;">
                        </div>
                        <div class="form-group">
                            <label>Preview</label>
                            <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; max-height:320px; overflow:auto; background:#fff;">${preview.html || ''}</div>
                        </div>
                        <div style="display:flex; justify-content:flex-end; gap:8px;">
                            <button class="btn btn-secondary" onclick="document.getElementById('iataEmailModal').remove()">Cancelar</button>
                            <button class="btn btn-auto-mapping btn-small" onclick="sendIAtaEmail(${Number(rid)})"><span class="ai-star-icon">✦</span> Enviar</button>
                        </div>
                    </div>
                </div>`);
        }

        async function sendIAtaEmail(rid) {
            const destinos = (document.getElementById('iataEmailTo')?.value || '')
                .split(/[,;]/).map(s => s.trim()).filter(Boolean);
            if (!destinos.length) { showError('Informe ao menos um destinatário.'); return; }
            if (!await uiConfirm(`Enviar a ata para ${destinos.length} destinatário(s)?`, 'Enviar Ata')) return;
            try {
                const response = await fetch(`${API_BASE}/autotoca/iata/${rid}/email`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ to: destinos })
                });
                const payload = await response.json().catch(() => ({}));
                if (response.status === 400 || response.status === 404) {
                    throw new Error(payload.error || 'Erro ao enviar a ata.');
                }
                const falhas = (payload.results || []).filter(r => !r.ok);
                if (falhas.length) {
                    showError('Falha para: ' + falhas.map(f => `${f.to} (${f.error})`).join('; '));
                } else {
                    showSuccess('Ata enviada.');
                    document.getElementById('iataEmailModal')?.remove();
                }
            } catch (error) {
                showError(error.message || 'Erro ao enviar a ata.');
            }
        }
```

O envio é ação externa e irreversível — daí o `uiConfirm` antes.

- [ ] **Step 3: Verificar no navegador**

Abrir uma ata gerada, editar uma linha, salvar (confirmar o toast), reabrir e
verificar que o texto persistiu. Abrir o modal de e-mail e conferir que o
preview mostra a hierarquia com bullets aninhados. **Não enviar e-mail real**
sem o usuário pedir.

- [ ] **Step 4: Commit**

```bash
git add public/js/autotoca-iata.js && git commit -m "feat(iata): visualizacao, edicao e envio por email"
```

---

### Task 14: Limpeza do código antigo

**Files:**
- Modify: `app.py:9575-9965`
- Modify: `public/js/itoca-autotoca.js`
- Test: `tests/test_iata.py`, `tests/test_routes.py`

- [ ] **Step 1: Remover os helpers antigos do `app.py`**

Apagar de `app.py` (bloco `9575-9965`): `_iata_parse_llm_ata`,
`_iata_parse_llm_insights`, `_iata_call_llm`, `_iata_generate_ata`,
`_iata_generate_insights`, `_iata_record_to_dict`.

**Manter** `_iata_extract_file_text`, `_parse_vtt_text`, `_parse_srt_text`,
`_iata_extract_bytes`, `_BytesFS`, `_iata_task_set`, `_iata_task_get`,
`_iata_task_cleanup` **se** o `routes/autotoca_iata.py` estiver reutilizando as
versões do `app.py` em vez de ter cópias próprias — nesse caso remover as cópias
do módulo de rotas. Escolher **um** dos dois lugares e deixar só ele; duas
cópias divergem com o tempo.

Antes de apagar, conferir se algo mais usa esses nomes:

Run: `grep -rn "_iata_call_llm\|_iata_generate_ata\|_iata_record_to_dict\|_iata_generate_insights" --include=*.py .`
Expected: só as próprias definições (o uso em `app.py:10398` precisa ser
verificado — se `_iata_call_llm` for usado por outra feature, trocar a chamada
por `_llm_prompt` antes de remover).

- [ ] **Step 2: Remover o código iAta antigo do `itoca-autotoca.js`**

Apagar de `public/js/itoca-autotoca.js` as funções que foram movidas ou
substituídas: `loadIAta`, `renderIAtaHistory`, `_renderIAtaExpanded`,
`toggleIAtaExpand`, `viewIAtaFull`, `openIAtaModal`, `_iataSetProgress`,
`submitIAta`, `deleteIAtaRecord`, `_iataParticipantNames`, `_iataDeadline`, a
variável `iataRecords` e o `Set` `expandedIAtaRecords`.

Confirmar que nenhuma sobrou referenciada:

Run: `grep -rn "expandedIAtaRecords\|_renderIAtaExpanded\|toggleIAtaExpand" public/`
Expected: nenhum resultado.

- [ ] **Step 3: Rodar a suíte inteira**

Run: `python -m pytest -q`
Expected: PASS. `tests/test_routes.py` pode ter um teste que enumera rotas ou
bate em `/api/portfolio/iata` — se falhar, atualizar para o caminho novo.

- [ ] **Step 4: Verificar o app no navegador**

Recarregar o app, abrir Portfolio (sub-abas STF e Whitespace funcionando, sem
iAta) e AutoToca → iAta (listagem, nova ata, abrir, editar). Conferir
`read_console_messages`: nenhum `ReferenceError`.

- [ ] **Step 5: Commit**

```bash
git add app.py public/js/itoca-autotoca.js tests/ && git commit -m "refactor(iata): remove o codigo antigo do portfolio"
```

---

## Verificação final

- [ ] `python -m pytest -q` — suíte inteira passando
- [ ] `python -c "import app"` sem exceção
- [ ] `grep -rn "portfolio/iata" public/ routes/ app.py` — nenhum resultado
- [ ] Fluxo completo no navegador: nova ata a partir do histórico → hierarquia com status anterior → editar texto → preview de e-mail com bullets aninhados
- [ ] `app.log` com as linhas `[iAta]` das etapas
