# -*- coding: utf-8 -*-
import sqlite3

import app as toca
from integrations import iata as iata_lib


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


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_migracao_17_recria_tabelas_derrubadas_em_banco_existente(db_path):
    """Reproduz um banco já migrado que perdeu a hierarquia iAta.

    A fixture db_path já roda o baseline (init_db atual, que já contém o
    schema novo), então as duas primeiras asserções por si só não provam que
    a migração 17 funciona isoladamente sobre um banco existente — é preciso
    apagar as tabelas e desmarcar a versão 17, como em
    test_banco_antigo_sem_a_tabela_de_oauth_e_curado (tests/test_schema_migrations.py).
    """
    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE iata_opportunities')
    conn.execute('DROP TABLE iata_accounts')
    conn.execute('DROP TABLE iata_managers')
    conn.execute('DELETE FROM schema_version WHERE version = 17')
    conn.commit()
    conn.close()

    assert not ({'iata_managers', 'iata_accounts', 'iata_opportunities'} & _tables(db_path))

    toca._run_schema_migrations()

    assert {'iata_managers', 'iata_accounts', 'iata_opportunities'} <= _tables(db_path)


def test_iata_add_record_columns_adiciona_o_que_falta(tmp_path):
    """SQLite não recria colunas sem recriar a tabela — exercita a função
    direto sobre um iata_records "cru" (sem as colunas novas), em vez de
    forçar a remoção artificial de colunas num banco real."""
    path = tmp_path / 'cru.db'
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE iata_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL
    )''')
    conn.commit()

    cols_antes = {r[1] for r in conn.execute('PRAGMA table_info(iata_records)')}
    assert 'format_version' not in cols_antes

    toca._iata_add_record_columns(conn)
    conn.commit()

    cols_depois = {r[1] for r in conn.execute('PRAGMA table_info(iata_records)')}
    conn.close()
    assert {'previous_record_id', 'body_markdown', 'body_edited',
            'reparse_failed', 'format_version'} <= cols_depois


def test_iata_add_record_columns_tolera_tabela_ausente(tmp_path):
    """Bancos sintéticos de teste que pulam a baseline não têm iata_records
    ainda — a função não deve estourar OperationalError nesse caso."""
    path = tmp_path / 'sem_tabela.db'
    conn = sqlite3.connect(path)
    toca._iata_add_record_columns(conn)  # não deve lançar
    conn.close()


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


# --- Defeitos encontrados na revisão de qualidade da Task 2 ---------------


def test_reconcile_conta_repetida_sob_dois_gerentes_mescla_oportunidades_anteriores():
    """C1: a mesma conta pode aparecer sob gerentes diferentes na ata
    anterior (trocou de dono entre reuniões) — as oportunidades do segundo
    bloco não podem desaparecer silenciosamente."""
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
    assert expansao[0]['previous_status'] == 'Proposta enviada'


def test_reconcile_duas_oportunidades_homonimas_na_mesma_conta_nao_se_fundem():
    """C2: nomes repetidos na mesma conta são um cenário plausível (dois
    contratos homônimos) — casar a nova com uma delas não pode fazer a
    outra desaparecer, nem fundir os dois ids num só."""
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
    assert sobrando[0]['previous_status'] == 'Contrato B assinado'


def test_reconcile_conta_anterior_com_nome_vazio_nao_e_descartada():
    """C3: extração ruidosa da IA pode devolver conta sem nome — perder a
    conta inteira (e suas oportunidades) é pior do que exibi-la sem nome."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': '   ', 'opportunities': [
        {'id': 5, 'name': 'Piloto', 'update_text': 'Em teste'}]}]}]
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    piloto = [o for m in result for a in m['accounts'] for o in a['opportunities']
              if o['name'] == 'Piloto']
    assert len(piloto) == 1
    assert piloto[0]['carried_over'] is True
    assert piloto[0]['prev_opportunity_id'] == 5


def test_reconcile_gerentes_com_grafia_de_caixa_diferente_nao_duplicam_bloco():
    """I1: gerentes devem ser casados por nome normalizado — 'ANA PAULA' e
    'Ana Paula' são a mesma pessoa, não dois blocos na ata."""
    anterior = [{'name': 'ANA PAULA', 'accounts': [{'name': 'Vale', 'opportunities': [
        {'id': 3, 'name': 'Data Lake', 'update_text': 'POC em andamento'}]}]}]
    atual = [{'name': 'Ana Paula', 'accounts': [
        {'name': 'Ambev', 'opportunities': [
            {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana Paula'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    assert len(result) == 1
    contas = {a['name'] for a in result[0]['accounts']}
    assert {'Ambev', 'Vale'} <= contas


def test_reconcile_conta_com_grafia_levemente_diferente_nao_duplica():
    """I2: grafia levemente diferente de conta (typo) não pode gerar dois
    blocos de conta contraditórios — um novo e um 'sem update' — para o
    mesmo negócio."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': 'Comercial Pedroso', 'opportunities': [
        {'id': 1, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}]}]}]
    atual = [{'name': 'Ana', 'accounts': [{'name': 'Comercial Pedrozo', 'opportunities': [
        {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    contas = [a['name'] for m in result for a in m['accounts']]
    assert contas == ['Comercial Pedrozo']
    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['prev_opportunity_id'] == 1
    assert opp['previous_status'] == 'Proposta enviada'


def test_reconcile_resolver_com_id_none_no_candidato_nao_casa_sem_decisao_explicita():
    """I3: resolver devolvendo {} (sem decisão) não pode casar com um
    candidato cujo id também é None — None de 'não decidi' e None de 'id
    desconhecido' não são a mesma coisa."""
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
    assert casada['previous_status'] is None
    assert casada['match_confidence'] == 'baixa'


def test_reconcile_resolver_nao_pode_atribuir_o_mesmo_id_a_dois_pares():
    """I4: um LLM respondendo em lote pode devolver o mesmo id para dois
    índices distintos — só o primeiro pode reivindicar; o segundo vira
    'baixa' em vez de duplicar o carregamento do mesmo id."""
    anterior = _hierarquia([
        {'id': 9, 'name': 'Migração SAP Fase 1', 'update_text': 'Em análise'},
    ])
    atual = _hierarquia([
        {'name': 'Migração SAP fase I', 'update_text': 'a', 'responsible': 'Ana'},
        {'name': 'Migração SAP fase Um', 'update_text': 'b', 'responsible': 'Ana'},
    ])

    result = iata_lib.reconcile(atual, anterior, resolver=lambda pares: {0: 9, 1: 9})

    opps = result[0]['accounts'][0]['opportunities']
    com_id = [o for o in opps if o['prev_opportunity_id'] == 9]
    assert len(com_id) == 1
    baixa = [o for o in opps if o['match_confidence'] == 'baixa']
    assert len(baixa) == 1
    assert baixa[0]['prev_opportunity_id'] is None


def test_reconcile_resolver_com_chaves_string_no_retorno_e_normalizado():
    """I5: um resolver que parseia JSON devolve índices como string
    ('0', não 0) — sem normalizar, todo par ambíguo cairia em 'baixa' em
    silêncio."""
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
    assert casada['match_confidence'] == 'alta'


def test_reconcile_resolver_que_lanca_excecao_nao_propaga_e_e_registrado(caplog):
    """I6: uma falha do resolver (ex.: LLM fora do ar) não pode derrubar a
    reconciliação nem ficar indistinguível de 'sem match' — precisa deixar
    rastro no log."""
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
    assert casada['match_confidence'] == 'baixa'
    assert any('resolver' in rec.message.lower() for rec in caplog.records)


def test_reconcile_match_exato_recebe_confianca_alta():
    """M2: o campo match_confidence deve distinguir match limpo (exato) de
    item novo (None) e de carried over (None)."""
    anterior = _hierarquia([{'id': 7, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}])
    atual = _hierarquia([{'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}])

    result = iata_lib.reconcile(atual, anterior)

    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['match_confidence'] == 'alta'
