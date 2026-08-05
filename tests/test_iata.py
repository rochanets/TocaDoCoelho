# -*- coding: utf-8 -*-
import json
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


def test_reconcile_conta_com_sufixo_de_forma_juridica_nao_duplica():
    """Variação de forma jurídica ('Ambev S.A.' vs 'Ambev') não é erro de
    digitação — o SequenceMatcher penaliza a diferença de comprimento
    (ratio 0.71, abaixo do cutoff de fuzzy de conta) e nunca casaria via
    fuzzy sem afrouxar o cutoff a ponto de arriscar fundir contas de fato
    diferentes. É um mecanismo à parte: remover o sufixo jurídico do fim do
    nome antes de comparar."""
    anterior = [{'name': 'Ana', 'accounts': [{'name': 'Ambev S.A.', 'opportunities': [
        {'id': 1, 'name': 'Migração SAP', 'update_text': 'Proposta enviada'}]}]}]
    atual = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}]}]}]

    result = iata_lib.reconcile(atual, anterior)

    contas = [a['name'] for m in result for a in m['accounts']]
    assert contas == ['Ambev']
    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['prev_opportunity_id'] == 1
    assert opp['previous_status'] == 'Proposta enviada'
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
    vale = [a for m in result for a in m['accounts'] if a['name'] == 'Vale'][0]
    assert vale['opportunities'][0]['prev_opportunity_id'] == 1
    vale_verde = [a for m in result for a in m['accounts'] if a['name'] == 'Vale Verde'][0]
    assert vale_verde['opportunities'][0]['update_text'] == iata_lib.SEM_UPDATE
    assert vale_verde['opportunities'][0]['prev_opportunity_id'] == 2


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
    assert casada['match_confidence'] == 'media'


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


# --- Task 3: prompt e parsing da hierarquia --------------------------------


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


# --- Defeitos e robustez adicionais investigados na Task 3 -----------------


def test_parse_hierarchy_conta_com_nome_vazio_nao_descarta_oportunidades():
    """Descartar a conta inteira (name vazio) apagaria a oportunidade real
    que veio junto — pior do que exibi-la sem nome de conta."""
    raw = json.dumps({'title': 'X', 'managers': [
        {'name': 'Ana', 'accounts': [{'name': '   ', 'opportunities': [
            {'name': 'Migração SAP', 'update': 'Proposta enviada'}]}]}]})

    parsed = iata_lib.parse_hierarchy(raw)

    contas = parsed['managers'][0]['accounts']
    assert len(contas) == 1
    assert contas[0]['name'] == ''
    assert contas[0]['opportunities'][0]['name'] == 'Migração SAP'


def test_parse_hierarchy_oportunidade_sem_nome_preserva_update_e_responsavel():
    """Uma oportunidade sem 'name' ainda carrega update/responsável reais —
    descartá-la silenciosamente apagaria a única menção àquele negócio."""
    raw = json.dumps({'title': 'X', 'managers': [
        {'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'update': 'Cliente pediu desconto', 'responsible': 'Bruno'}]}]}]})

    parsed = iata_lib.parse_hierarchy(raw)

    opp = parsed['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['name'] == ''
    assert opp['update_text'] == 'Cliente pediu desconto'
    assert opp['responsible'] == 'Bruno'


def test_parse_hierarchy_managers_como_dict_unico_nao_apaga_hierarquia():
    """Se o LLM devolver 'managers' como um objeto único em vez de lista de
    um elemento, iterar o dict cru percorreria suas CHAVES como se fossem
    itens — o filtro de isinstance(dict) seguinte descartaria tudo em
    silêncio, apagando a ata inteira."""
    raw = json.dumps({'title': 'X', 'managers': {
        'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Migração SAP', 'update': 'Fechado'}]}]}})

    parsed = iata_lib.parse_hierarchy(raw)

    assert len(parsed['managers']) == 1
    assert parsed['managers'][0]['name'] == 'Ana'
    assert parsed['managers'][0]['accounts'][0]['name'] == 'Ambev'


def test_parse_hierarchy_accounts_e_opportunities_como_string_solta():
    """Um LLM pode devolver uma lista de strings soltas em vez de objetos —
    vira item com aquele nome em vez de ser silenciosamente descartado."""
    raw = json.dumps({'title': 'X', 'managers': [
        {'name': 'Ana', 'accounts': ['Ambev']}]})

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed['managers'][0]['accounts'][0]['name'] == 'Ambev'


def test_parse_hierarchy_campos_em_portugues_sao_aceitos():
    """O prompt pede chaves em inglês, mas um LLM pode ignorar e devolver em
    português mesmo assim — perder a ata inteira por causa disso é pior do
    que tolerar as duas variantes de chave."""
    raw = json.dumps({'titulo': 'Pipeline', 'gerentes': [
        {'nome': 'Ana', 'contas': [{'nome': 'Ambev', 'oportunidades': [
            {'nome': 'Migração SAP', 'atualizacao': 'Proposta enviada',
             'responsavel': 'Bruno'}]}]}]}, ensure_ascii=False)

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed['header']['title'] == 'Pipeline'
    opp = parsed['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['name'] == 'Migração SAP'
    assert opp['update_text'] == 'Proposta enviada'
    assert opp['responsible'] == 'Bruno'


def test_parse_hierarchy_json_com_texto_explicativo_ao_redor():
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = 'Aqui está a extração da reunião:\n' + payload + '\nQualquer dúvida, me avise!'

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed['header']['title'] == 'X'


def test_parse_hierarchy_json_truncado_retorna_none_sem_lancar():
    raw = '{"title": "X", "managers": [{"name": "Ana", "accounts": ['
    assert iata_lib.parse_hierarchy(raw) is None


def test_parse_hierarchy_bloco_de_fence_sem_tag_json():
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = '```\n' + payload + '\n```'
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed['header']['title'] == 'X'


def test_parse_hierarchy_aspas_curvas_sao_reparadas():
    raw = '{\u201ctitle\u201d: \u201cPipeline\u201d, \u201cmanagers\u201d: []}'
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed is not None
    assert parsed['header']['title'] == 'Pipeline'


def test_parse_hierarchy_null_literal_em_string_vira_none():
    raw = json.dumps({'title': 'X', 'meeting_date': 'null', 'managers': []})
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed['header']['meeting_date'] is None


def test_parse_hierarchy_participantes_como_string_unica_nao_vira_caracteres():
    """Iterar uma string caractere a caractere (em vez de tratar como uma
    lista separada por vírgula) produziria 'A', 'n', 'a'... como nomes."""
    raw = json.dumps({'title': 'X', 'participants': 'Ana, Bruno', 'managers': []})
    parsed = iata_lib.parse_hierarchy(raw)
    assert parsed['header']['participants'] == [
        {'name': 'Ana', 'role': ''}, {'name': 'Bruno', 'role': ''}]


# --- Achados da revisão de qualidade: coleção como mapa nome->objeto -------


def test_parse_hierarchy_managers_como_mapa_nao_colapsa_a_ata():
    """CRITICAL: 'managers' devolvido como {"Ana": {...}, "Bruno": {...}}
    (mapa nome->objeto) é tão plausível quanto objeto único sem grammar
    estrita. Tratá-lo como item único produziria UM gerente vazio
    'Gerente não identificado' com accounts: [] — a ata inteira some, sem
    virar None e sem logar nada."""
    raw = json.dumps({'title': 'X', 'managers': {
        'Ana': {'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Migração SAP', 'update': 'Proposta enviada'}]}]},
        'Bruno': {'accounts': [{'name': 'Vale', 'opportunities': [
            {'name': 'Data Lake', 'update': 'POC em andamento'}]}]},
    }})

    parsed = iata_lib.parse_hierarchy(raw)

    nomes = {m['name'] for m in parsed['managers']}
    assert nomes == {'Ana', 'Bruno'}
    ana = [m for m in parsed['managers'] if m['name'] == 'Ana'][0]
    assert ana['accounts'][0]['name'] == 'Ambev'
    bruno = [m for m in parsed['managers'] if m['name'] == 'Bruno'][0]
    assert bruno['accounts'][0]['name'] == 'Vale'


def test_parse_hierarchy_accounts_como_mapa_nao_apaga_contas_e_oportunidades():
    """CRITICAL: 'accounts' como mapa {"Ambev": {...}, "Vale": {...}} vira
    UMA conta vazia se tratado como item único — as contas reais e todas as
    oportunidades delas somem."""
    raw = json.dumps({'title': 'X', 'managers': [{'name': 'Ana', 'accounts': {
        'Ambev': {'opportunities': [{'name': 'Migração SAP', 'update': 'Fechado'}]},
        'Vale': {'opportunities': [{'name': 'Data Lake', 'update': 'POC'}]},
    }}]})

    parsed = iata_lib.parse_hierarchy(raw)

    contas = {a['name']: a for a in parsed['managers'][0]['accounts']}
    assert set(contas) == {'Ambev', 'Vale'}
    assert contas['Ambev']['opportunities'][0]['name'] == 'Migração SAP'
    assert contas['Vale']['opportunities'][0]['name'] == 'Data Lake'


def test_parse_hierarchy_opportunities_como_mapa_usa_chave_como_nome():
    """CRITICAL: 'opportunities' como mapa nome->objeto some se tratado como
    item único. A chave do mapa deve preencher o `name` quando o objeto
    interno não tiver nome próprio, para não perder nem esse dado."""
    raw = json.dumps({'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [
        {'name': 'Ambev', 'opportunities': {
            'Migração SAP': {'update': 'Proposta enviada', 'responsible': 'Bruno'},
            'Observabilidade': {'update': 'Aguardando budget'},
        }}]}]})

    parsed = iata_lib.parse_hierarchy(raw)

    opps = {o['name']: o for o in parsed['managers'][0]['accounts'][0]['opportunities']}
    assert set(opps) == {'Migração SAP', 'Observabilidade'}
    assert opps['Migração SAP']['update_text'] == 'Proposta enviada'
    assert opps['Migração SAP']['responsible'] == 'Bruno'
    assert opps['Observabilidade']['update_text'] == 'Aguardando budget'


# --- Achados da revisão de qualidade: raw_decode em vez de recorte ingênuo -


def test_parse_hierarchy_json_com_chave_solta_no_texto_antes():
    """IMPORTANT: recortar do primeiro '{' ao último '}' engole uma chave
    solta no texto explicativo antes do JSON, quebrando o parse do objeto
    perfeitamente válido que vem depois."""
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = 'Segue conforme {template} solicitado:\n' + payload

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed is not None
    assert parsed['header']['title'] == 'X'


def test_parse_hierarchy_json_apos_muitas_chaves_soltas():
    """Um modelo que ecoa o schema pedido no prompt antes de responder produz
    dezenas de chaves soltas: o cap de tentativas do raw_decode não pode ser
    apertado a ponto de rejeitar o JSON bom que vem logo depois."""
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = ''.join('{campo%d} ' % i for i in range(30)) + payload

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed is not None
    assert parsed['header']['title'] == 'X'


def test_parse_hierarchy_json_com_chave_solta_no_texto_depois():
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = payload + '\n(obs: aguardando retorno da {diretoria})'

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed is not None
    assert parsed['header']['title'] == 'X'


def test_parse_hierarchy_json_com_chave_solta_antes_e_depois():
    payload = json.dumps({'title': 'X', 'managers': []})
    raw = ('Segue conforme {template} solicitado:\n' + payload +
           '\n(obs: aguardando retorno da {diretoria})')

    parsed = iata_lib.parse_hierarchy(raw)

    assert parsed is not None
    assert parsed['header']['title'] == 'X'


# --- Task 4: render_markdown -----------------------------------------------


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


def test_render_markdown_conta_e_oportunidade_sem_nome_ganham_rotulo():
    """Task 3 decidiu deliberadamente preservar conta/oportunidade sem nome
    em vez de descartar o bloco (update/responsável podem ser dado real) —
    a decisão de rótulo ficou para a renderização. Um bullet vazio não deixa
    claro pro usuário que existe algo ali."""
    managers = [{'name': 'Ana', 'accounts': [{'name': '', 'opportunities': [
        {'name': '', 'previous_status': None, 'update_text': 'Kickoff',
         'responsible': 'Ana', 'carried_over': False}]}]}]
    texto = iata_lib.render_markdown(_header_exemplo(), managers)
    assert '  * Conta sem nome' in texto
    assert '     * Oportunidade sem nome' in texto


def test_render_markdown_gerente_sem_nome_usa_rotulo_padrao():
    managers = [{'name': '', 'accounts': []}]
    texto = iata_lib.render_markdown(_header_exemplo(), managers)
    assert 'Gerente Comercial: Gerente não identificado' in texto


# --- Task 5: render_email_html e email_subject ------------------------------


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


def test_render_email_html_escapa_status_da_oportunidade_sem_escape_duplo():
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': '<b>SAP</b>', 'previous_status': '<i>Proposta</i>',
         'update_text': 'ok', 'responsible': 'Ana', 'carried_over': False}]}]}]
    html = iata_lib.render_email_html(_header_exemplo(), managers)
    assert '<b>' not in html and '<i>' not in html
    assert '&lt;b&gt;SAP&lt;/b&gt;' in html
    assert '&lt;i&gt;Proposta&lt;/i&gt;' in html
    # sem escape duplo: '<' vira '&lt;' uma única vez, nunca '&amp;lt;'
    assert '&amp;lt;' not in html


def test_render_email_html_nome_vazio_de_conta_e_oportunidade_ganha_rotulo():
    managers = [{'name': 'Ana', 'accounts': [{'name': '', 'opportunities': [
        {'name': '', 'previous_status': None, 'update_text': 'Kickoff',
         'responsible': 'Ana', 'carried_over': False}]}]}]
    html = iata_lib.render_email_html(_header_exemplo(), managers)
    assert '<strong>Conta sem nome</strong>' in html
    assert 'Oportunidade sem nome' in html
    assert '<strong></strong>' not in html


def test_render_email_html_aninhamento_fecha_com_conta_sem_oportunidades():
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': []}]}]
    html = iata_lib.render_email_html(_header_exemplo(), managers)
    assert html.count('<ul') == html.count('</ul>')
    assert html.count('<li') == html.count('</li>')


def test_render_email_html_aninhamento_fecha_com_gerente_sem_contas():
    managers = [{'name': 'Ana', 'accounts': []}]
    html = iata_lib.render_email_html(_header_exemplo(), managers)
    assert html.count('<ul') == html.count('</ul>')
    assert html.count('<li') == html.count('</li>')


def test_render_email_html_aninhamento_fecha_sem_managers():
    html = iata_lib.render_email_html(_header_exemplo(), [])
    assert html.count('<ul') == html.count('</ul>')
    assert html.count('<li') == html.count('</li>')
    assert '<ul' not in html


def test_render_email_subject_usa_titulo_e_data():
    assert iata_lib.email_subject(_header_exemplo()) == 'Ata — Pipeline Semanal — 04/08/2026'


def test_render_email_subject_sem_data():
    header = dict(_header_exemplo(), meeting_date=None)
    assert iata_lib.email_subject(header) == 'Ata — Pipeline Semanal'


def test_render_extras_com_item_fora_do_formato_nao_some_da_ata():
    """A IA às vezes devolve next_steps/insights como string solta em vez do
    objeto estruturado. Descartar o item silenciosamente esconde do usuário
    uma ação real combinada na reunião — entra como texto cru."""
    extras = {'next_steps': ['Enviar proposta até sexta',
                             {'action': 'Agendar POC', 'responsible': 'Ana'}],
              'insights': ['Cliente reclamou do custo de licença']}

    texto = iata_lib.render_markdown(_header_exemplo(), _managers_exemplo(), extras)
    assert 'Enviar proposta até sexta' in texto
    assert 'Agendar POC' in texto
    assert 'Cliente reclamou do custo de licença' in texto

    html = iata_lib.render_email_html(_header_exemplo(), _managers_exemplo(), extras)
    assert 'Enviar proposta até sexta' in html
    assert 'Cliente reclamou do custo de licença' in html
