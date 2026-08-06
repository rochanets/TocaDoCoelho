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


# --- Task 6: persistência da hierarquia e rotas de leitura ------------------


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


def test_delete_inexistente_retorna_404(client, db_path):
    assert client.delete('/api/autotoca/iata/99999').status_code == 404


def _cria_account(db_path, nome='Ambev'):
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.execute('INSERT INTO accounts (name) VALUES (?)', (nome,))
        conn.commit()
        return conn.execute('SELECT id FROM accounts WHERE name = ?', (nome,)).fetchone()[0]
    finally:
        conn.close()


def _hierarquia_completa(account_id=None, **overrides):
    opp = {'name': 'Migração SAP', 'previous_status': 'Fase 1 fechada',
           'update_text': 'Proposta revisada', 'responsible': 'Bruno',
           'carried_over': True, 'prev_opportunity_id': None,
           'match_confidence': 'media'}
    opp.update(overrides)
    return [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': account_id,
        'match_confidence': 'alta', 'match_confirmed': True,
        'opportunities': [opp]}]}]


def test_save_record_round_trip_preserva_todos_os_campos_da_oportunidade(db_path):
    """O que sai de _iata_load_record precisa servir como previous_managers
    para iata_lib.reconcile na próxima ata — se um campo se perder na volta
    do banco, o encadeamento entre atas quebra em silêncio."""
    account_id = _cria_account(db_path)
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = _hierarquia_completa(account_id=account_id)

    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    registro = toca._iata_load_record(rid)

    conta = registro['managers'][0]['accounts'][0]
    opp = conta['opportunities'][0]
    assert conta['account_id'] == account_id
    assert conta['match_confidence'] == 'alta'
    assert conta['match_confirmed'] is True
    assert opp['previous_status'] == 'Fase 1 fechada'
    assert opp['update_text'] == 'Proposta revisada'
    assert opp['responsible'] == 'Bruno'
    assert opp['carried_over'] is True
    assert opp['match_confidence'] == 'media'
    assert 'id' in opp  # reconcile precisa do id do banco para casar de novo


def test_registro_lido_do_banco_serve_como_previous_managers_para_reconcile(db_path):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = _hierarquia_completa()  # account_id None: reconciliação não depende dele
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    registro = toca._iata_load_record(rid)

    atual = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Migração SAP', 'update_text': 'Fechado', 'responsible': 'Ana'}]}]}]
    result = iata_lib.reconcile(atual, registro['managers'])

    opp = result[0]['accounts'][0]['opportunities'][0]
    assert opp['match_confidence'] == 'alta'
    assert opp['previous_status'] == 'Proposta revisada'


def test_save_record_respeita_display_order_mesmo_inserido_fora_de_ordem(db_path):
    managers = [
        {'name': 'Bruno', 'accounts': [{'name': 'Vale', 'account_id': None,
            'match_confidence': None, 'opportunities': [
                {'name': 'Data Lake', 'previous_status': None, 'update_text': 'u',
                 'responsible': 'Bruno', 'carried_over': False,
                 'prev_opportunity_id': None, 'match_confidence': None}]}]},
        {'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
            'match_confidence': None, 'opportunities': [
                {'name': 'Op2', 'previous_status': None, 'update_text': 'u2',
                 'responsible': 'Ana', 'carried_over': False,
                 'prev_opportunity_id': None, 'match_confidence': None},
                {'name': 'Op1', 'previous_status': None, 'update_text': 'u1',
                 'responsible': 'Ana', 'carried_over': False,
                 'prev_opportunity_id': None, 'match_confidence': None}]}]},
    ]
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    registro = toca._iata_load_record(rid)

    nomes_gerentes = [m['name'] for m in registro['managers']]
    assert nomes_gerentes == ['Bruno', 'Ana']
    opps = registro['managers'][1]['accounts'][0]['opportunities']
    assert [o['name'] for o in opps] == ['Op2', 'Op1']


def test_list_retorna_participantes_parseados(client, db_path):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': [{'name': 'Ana', 'role': 'Gerente'}]}
    managers = [{'name': 'Ana', 'accounts': []}]
    toca._iata_save_record(header, managers, {}, 'texto', None)

    lista = client.get('/api/autotoca/iata').get_json()
    assert lista[0]['participants'] == [{'name': 'Ana', 'role': 'Gerente'}]


def test_get_registro_antigo_sem_hierarquia_e_body_markdown_nao_quebra(client, db_path):
    """Simula um registro no formato antigo (format_version=1), inserido
    diretamente como o código legado fazia — sem body_markdown e sem linhas
    nas tabelas de hierarquia."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''INSERT INTO iata_records (title, meeting_date, meeting_time, topic,
               participants, ata_json, insights_json, raw_text, format_version)
               VALUES (?,?,?,?,?,?,?,?,1)''',
            ('Ata Antiga', None, None, '', '[]', '{}', '[]', 'texto antigo'))
        rid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    detalhe = client.get(f'/api/autotoca/iata/{rid}')
    assert detalhe.status_code == 200
    corpo = detalhe.get_json()
    assert corpo['managers'] == []
    assert corpo['body_markdown'] is None


def test_save_record_e_transacional_na_falha_da_hierarquia(db_path, monkeypatch):
    """Se a escrita da hierarquia falhar no meio, o registro em iata_records
    não pode sobrar sozinho no banco — tudo ou nada."""
    def _quebra(*a, **k):
        raise RuntimeError('falha simulada na escrita da hierarquia')
    monkeypatch.setattr(toca, '_iata_write_hierarchy', _quebra)

    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': []}]

    import pytest
    with pytest.raises(RuntimeError):
        toca._iata_save_record(header, managers, {}, 'texto', None)

    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        total = conn.execute('SELECT COUNT(*) FROM iata_records').fetchone()[0]
    finally:
        conn.close()
    assert total == 0, 'INSERT sem commit não pode sobreviver a uma falha na hierarquia'


# ---------------------------------------------------------------------------
# Task 7: geração assíncrona da ata
# ---------------------------------------------------------------------------

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

    resposta_ia = json.dumps({
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


def test_pipeline_raw_text_salvo_e_completo_mesmo_quando_prompt_trunca(db_path, monkeypatch):
    """build_extraction_prompt() só embute os primeiros MAX_TRANSCRICAO_CHARS
    caracteres no prompt da IA — mas o raw_text persistido no banco precisa
    continuar sendo o texto INTEIRO. Perder a transcrição original seria
    perda de dado real, não só uma limitação do prompt."""
    texto_longo = 'Assunto discutido na reunião de pipeline. ' * 1000
    assert len(texto_longo) > iata_lib.MAX_TRANSCRICAO_CHARS

    resposta_ia = json.dumps({
        'title': 'Pipeline Longo', 'meeting_date': None, 'meeting_time': None,
        'topic': 'Funil', 'participants': [],
        'managers': [{'name': 'Ana', 'accounts': []}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia)

    task_id = 'teste_truncamento'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, texto_longo,
                             previous_record_id=None, with_insights=False)

    task = toca._iata_task_get(task_id)
    assert task['status'] == 'done', task.get('error')
    registro = toca._iata_load_record(task['result']['id'])
    # _iata_process_async faz .strip() no texto de entrada (remove espaços
    # nas pontas) — não é o truncamento em MAX_TRANSCRICAO_CHARS sob teste
    # aqui, então comparamos contra o texto igualmente stripado.
    assert registro['raw_text'] == texto_longo.strip()
    assert len(registro['raw_text']) > iata_lib.MAX_TRANSCRICAO_CHARS


def test_pipeline_previous_record_id_inexistente_gera_aviso_sem_referencia_fantasma(
        db_path, monkeypatch):
    """Um previous_record_id que não existe mais no banco (deletado entre a
    escolha do usuário e o fim da geração, ou id inválido) não pode virar uma
    ata 'do zero' sem que o usuário saiba: isso é perda de contexto silenciosa."""
    resposta_ia = json.dumps({
        'title': 'Ata Sem Continuidade', 'meeting_date': None, 'meeting_time': None,
        'topic': '', 'participants': [],
        'managers': [{'name': 'Ana', 'accounts': []}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia)

    task_id = 'teste_prev_inexistente'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, 'texto qualquer',
                             previous_record_id=999999, with_insights=False)

    task = toca._iata_task_get(task_id)
    assert task['status'] == 'done', task.get('error')
    assert task.get('warning'), 'usuário pediu continuidade e não foi avisado que ela não aconteceu'
    registro = toca._iata_load_record(task['result']['id'])
    assert registro['previous_record_id'] is None


def test_pipeline_resolver_de_ambiguidade_casa_oportunidade_com_confianca_media(
        db_path, monkeypatch):
    """`_iata_resolver_ambiguidade` devolve {indice: id_anterior}; confirma
    fim a fim, pelo pipeline completo, que esse formato bate de fato com o
    que `reconcile()` espera (ver integrations/iata/reconcile.py) — não só
    isolado."""
    header_ant = {'title': 'Ata Anterior', 'meeting_date': None, 'meeting_time': None,
                  'topic': '', 'participants': []}
    managers_ant = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Renovacao de contrato', 'previous_status': None,
             'update_text': 'Em análise', 'responsible': 'Ana',
             'carried_over': False, 'prev_opportunity_id': None}]}]}]
    anterior_id = toca._iata_save_record(header_ant, managers_ant, {}, 'texto', None)
    anterior = toca._iata_load_record(anterior_id)
    opp_id_anterior = anterior['managers'][0]['accounts'][0]['opportunities'][0]['id']

    # Nome parecido ("Renovacao contrato") — próximo o bastante para virar
    # candidato ambíguo, mas não idêntico ao normalizar, então não é match
    # exato: precisa passar pelo resolver.
    resposta_ia = json.dumps({
        'title': 'Pipeline Ambiguo', 'meeting_date': None, 'meeting_time': None,
        'topic': '', 'participants': [],
        'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Renovacao contrato', 'update': 'Contrato assinado',
             'responsible': 'Ana'}]}]}]})

    chamadas = {'extracao': 0, 'resolver': 0}

    def _llm_fake(prompt, log_tag='llm', **kwargs):
        if log_tag == 'iAta/Ambiguidade':
            chamadas['resolver'] += 1
            assert str(opp_id_anterior) in prompt
            return json.dumps({'decisoes': [{'index': 0, 'id_anterior': opp_id_anterior}]})
        chamadas['extracao'] += 1
        return resposta_ia

    monkeypatch.setattr(toca, '_llm_prompt', _llm_fake)

    task_id = 'teste_ambiguidade'
    toca._iata_task_set(task_id, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id, None, None, 'transcrição qualquer',
                             previous_record_id=anterior_id, with_insights=False)

    task = toca._iata_task_get(task_id)
    assert task['status'] == 'done', task.get('error')
    assert chamadas['resolver'] == 1
    registro = toca._iata_load_record(task['result']['id'])
    opp = registro['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['match_confidence'] == 'media'
    assert opp['prev_opportunity_id'] == opp_id_anterior
    assert opp['previous_status'] == 'Em análise'


def test_post_with_insights_false_desliga_insights(client, db_path, monkeypatch):
    """'false' significa desligado. A partir da Task 8 os insights são uma
    chamada de LLM paga — ligar contra a vontade do usuário custa dinheiro."""
    capturado = {}

    class ThreadSincrona:
        """Roda o alvo na hora, para o teste não depender do escalonamento da
        thread real (senão a asserção corre contra o worker)."""

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._chamada = (target, args, kwargs or {})

        def start(self):
            target, args, kwargs = self._chamada
            capturado.update(kwargs)
            target(*args, **kwargs)

    monkeypatch.setattr(toca, '_iata_process_async', lambda *a, **k: None)
    monkeypatch.setattr(toca.threading, 'Thread', ThreadSincrona)

    resp = client.post('/api/autotoca/iata',
                       data={'raw_text': 'transcrição', 'with_insights': 'false'})

    assert resp.status_code == 202
    assert capturado['with_insights'] is False


def test_post_arquivo_vazio_falha_na_hora_com_400(client, db_path):
    """Arquivo com nome mas sem conteúdo: 400 imediato em vez de uma task que
    só morre no meio do processamento."""
    from io import BytesIO
    resp = client.post('/api/autotoca/iata',
                       data={'meeting_file': (BytesIO(b''), 'reuniao.txt')},
                       content_type='multipart/form-data')

    assert resp.status_code == 400
    assert 'vazio' in resp.get_json()['error'].lower()


# --- Task 8: sugestão de conta do CRM, confirmação e insights --------------

def test_sugerir_contas_casa_por_nome_normalizado(db_path):
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


def test_sugerir_contas_casa_por_sufixo_juridico(db_path):
    """'Ambev' (sem sufixo) citada na reunião precisa casar com 'Ambev S.A.'
    cadastrada no CRM — o caso mais comum de uma reunião real, e o motivo de
    reaproveitar `iata_lib.match_account_name` em vez de só exato + fuzzy
    0.85 (SequenceMatcher dá ratio 0.71 para 'ambev' x 'ambev s a', abaixo
    do cutoff, então nunca casaria sozinho)."""
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.commit()
    account_id = conn.execute("SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    conn.close()

    managers = [{'name': 'Ana', 'accounts': [
        {'name': 'Ambev', 'account_id': None, 'match_confidence': None, 'opportunities': []}]}]

    toca._iata_sugerir_contas(managers)

    conta = managers[0]['accounts'][0]
    assert conta['account_id'] == account_id
    assert conta['match_confidence'] == 'alta'


def test_sugerir_contas_nao_sobrescreve_vinculo_confirmado_pelo_usuario(db_path):
    """Uma conta que já veio com `match_confirmed=True` (herdado da ata
    anterior via reconcile) não pode ser trocada por uma nova sugestão —
    mesmo que o nome também case com outra conta do catálogo."""
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.commit()
    account_id_ambev = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    conn.close()

    managers = [{'name': 'Ana', 'accounts': [
        {'name': 'Ambev', 'account_id': 999999, 'match_confidence': 'alta',
         'match_confirmed': True, 'opportunities': []}]}]

    toca._iata_sugerir_contas(managers)

    conta = managers[0]['accounts'][0]
    assert conta['account_id'] == 999999
    assert conta['account_id'] != account_id_ambev


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
    # _iata_read_hierarchy (Task 6) padronizou match_confirmed como bool na
    # leitura — não int 0/1 como fica gravado na coluna do SQLite.
    assert conta['match_confirmed'] is True


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


def test_link_com_account_id_inexistente_retorna_erro(client, db_path):
    """Vincular a uma conta que não existe mais em `accounts` (id chutado ou
    apagado entre a sugestão e a confirmação) não pode ser aceito em silêncio."""
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    conta_id = toca._iata_load_record(rid)['managers'][0]['accounts'][0]['id']

    resp = client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_id}/link',
                       json={'account_id': 999999})
    assert resp.status_code == 404
    assert toca._iata_load_record(rid)['managers'][0]['accounts'][0]['account_id'] is None


def test_link_record_id_que_nao_bate_com_a_conta_retorna_404(client, db_path):
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    outro_rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    conta_id = toca._iata_load_record(rid)['managers'][0]['accounts'][0]['id']

    resp = client.post(f'/api/autotoca/iata/{outro_rid}/accounts/{conta_id}/link',
                       json={'account_id': None})
    assert resp.status_code == 404


def test_confirmacao_de_vinculo_sobrevive_a_ata_seguinte(client, db_path, monkeypatch):
    """Regressão de um bug real encontrado em revisão: a confirmação humana
    de vínculo (via /link) não sobrevivia à ata seguinte, porque (1)
    `_iata_sugerir_contas` rodava sobre `parsed['managers']` — fresco da
    extração da IA, que nunca tem `match_confirmed` — ANTES do `reconcile`,
    de modo que o guard "não sobrescrever confirmado" nunca via um valor
    verdadeiro no caminho real; e (2) `reconcile()` propagava `account_id`
    da conta anterior mas não `match_confirmed`/`match_confidence`, então o
    campo simplesmente não existia na saída.

    Chamar só `_iata_sugerir_contas` isolada (como os outros testes deste
    arquivo fazem) NÃO reproduz o bug — ela nunca é invocada assim no
    caminho real. Este teste percorre o encadeamento verdadeiro:
    `_iata_process_async` (extração -> reconcile -> sugestão -> save) ->
    `/link` -> `_iata_process_async` de novo com `previous_record_id`.
    """
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev Holding')")
    conn.commit()
    id_sugestao_automatica = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    id_confirmado_pelo_usuario = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Ambev Holding'").fetchone()[0]
    conn.close()

    resposta_ata1 = json.dumps({
        'title': 'Ata 1', 'meeting_date': None, 'meeting_time': None,
        'topic': '', 'participants': [],
        'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Renovação', 'update': 'Em análise', 'responsible': 'Ana'}]}]}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ata1)

    task_id_1 = 'confirmacao_ata1'
    toca._iata_task_set(task_id_1, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id_1, None, None, 'transcrição 1',
                             previous_record_id=None, with_insights=False)
    task1 = toca._iata_task_get(task_id_1)
    assert task1['status'] == 'done', task1.get('error')
    rid1 = task1['result']['id']

    conta1 = toca._iata_load_record(rid1)['managers'][0]['accounts'][0]
    # Sugestão automática acerta via sufixo jurídico ("Ambev" == "Ambev
    # S.A."), mas ninguém confirmou nada ainda.
    assert conta1['account_id'] == id_sugestao_automatica
    assert conta1['match_confirmed'] is False

    # Usuário discorda da sugestão automática (cenário real: mais de uma
    # conta "Ambev" no CRM, e a correta para este cliente é outra) e
    # confirma manualmente o vínculo correto.
    resp = client.post(f'/api/autotoca/iata/{rid1}/accounts/{conta1["id"]}/link',
                       json={'account_id': id_confirmado_pelo_usuario})
    assert resp.status_code == 200
    assert toca._iata_load_record(rid1)['managers'][0]['accounts'][0]['account_id'] \
        == id_confirmado_pelo_usuario

    # Ata 2, com continuidade da ata 1 — mesmo encadeamento real da rota de
    # criação (extração -> reconcile -> sugestão -> save).
    resposta_ata2 = json.dumps({
        'title': 'Ata 2', 'meeting_date': None, 'meeting_time': None,
        'topic': '', 'participants': [],
        'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
            {'name': 'Renovação', 'update': 'Contrato assinado', 'responsible': 'Ana'}]}]}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ata2)

    task_id_2 = 'confirmacao_ata2'
    toca._iata_task_set(task_id_2, {'status': 'processing', 'progress': 5})
    toca._iata_process_async(task_id_2, None, None, 'transcrição 2',
                             previous_record_id=rid1, with_insights=False)
    task2 = toca._iata_task_get(task_id_2)
    assert task2['status'] == 'done', task2.get('error')

    conta2 = toca._iata_load_record(task2['result']['id'])['managers'][0]['accounts'][0]
    assert conta2['account_id'] == id_confirmado_pelo_usuario, \
        'a confirmação humana precisa sobreviver à ata seguinte, não voltar à sugestão automática'
    assert conta2['match_confirmed'] is True, \
        'match_confirmed precisa sobreviver ao reconcile, não voltar False'


def test_insights_ofertas_sem_portfolio_nao_chama_llm(db_path, monkeypatch):
    """Sem nenhuma oferta cadastrada no portfólio, não vale a pena gastar
    uma chamada de LLM — devolve lista vazia direto."""
    def _quebra(*a, **k):
        raise AssertionError('não deveria chamar _llm_prompt sem ofertas cadastradas')
    monkeypatch.setattr(toca, '_llm_prompt', _quebra)

    header = {'title': 'X'}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Renovação', 'update_text': 'Em análise'}]}]}]
    assert toca._iata_insights_ofertas(header, managers) == []


def test_insights_ofertas_usa_colunas_reais_do_portfolio(db_path, monkeypatch):
    """`portfolio_offers` não tem coluna `description` (tem `summary`) — um
    SELECT errado derrubaria a geração inteira da ata com uma exceção de
    SQLite. Confere que a função monta o prompt e devolve os insights sem
    lançar."""
    conn = toca.get_db()
    conn.execute("INSERT INTO portfolio_offers (title, summary) VALUES (?, ?)",
                 ('Observabilidade 360', 'Monitoramento full-stack'))
    conn.commit()
    conn.close()

    resposta_ia = json.dumps({'insights': [
        {'pain': 'Falta de visibilidade de infra', 'matched_offer': 'Observabilidade 360',
         'confidence': 'alta', 'observation': 'Bate direto com a dor relatada.'}]})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia)

    header = {'title': 'X'}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Renovação', 'update_text': 'Sem visibilidade de infra'}]}]}]
    insights = toca._iata_insights_ofertas(header, managers)
    assert insights == [{'pain': 'Falta de visibilidade de infra',
                          'matched_offer': 'Observabilidade 360', 'confidence': 'alta',
                          'observation': 'Bate direto com a dor relatada.'}]


def test_insights_aceita_item_fora_do_formato_dict(db_path, monkeypatch):
    """Mesma tolerância de `_linhas_de_passos`/`_linhas_de_insights` (Tasks
    4/5): um item que não veio como dict entra como texto cru em vez de
    sumir em silêncio, e um único dict solto em vez de lista também é aceito."""
    conn = toca.get_db()
    conn.execute("INSERT INTO portfolio_offers (title, summary) VALUES (?, ?)",
                 ('Oferta X', 'resumo'))
    conn.commit()
    conn.close()

    resposta_ia = json.dumps({'insights': 'Só uma frase solta, fora do formato esperado'})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia)

    header = {'title': 'X'}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'opportunities': [
        {'name': 'Renovação', 'update_text': 'Em análise'}]}]}]
    # 'insights' como string (não list, não dict): sem itens estruturados
    # utilizáveis -> lista vazia, mas sem lançar exceção.
    assert toca._iata_insights_ofertas(header, managers) == []

    resposta_ia_dict_unico = json.dumps({'insights': {
        'pain': 'Dor única', 'matched_offer': None, 'confidence': 'baixa', 'observation': ''}})
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: resposta_ia_dict_unico)
    insights = toca._iata_insights_ofertas(header, managers)
    assert insights == [{'pain': 'Dor única', 'matched_offer': None, 'confidence': 'baixa',
                          'observation': ''}]


# --- Task 9: edição do texto e re-parse -------------------------------------
# `_json` do plano de referência não existe no arquivo (só `import json`
# como `json`); usamos `json` diretamente, que já cobre o mesmo uso.

def test_put_body_salva_texto_e_atualiza_hierarquia(client, db_path, monkeypatch):
    # O plano de referência usava um `prev_opportunity_id: 7` fixo — mas a
    # coluna tem FK real para iata_opportunities(id) (`ON DELETE SET NULL`,
    # ver app.py), então um id inventado que não existe derruba o INSERT
    # com IntegrityError antes mesmo do PUT ser exercitado. Gera-se aqui uma
    # ata anterior de verdade para obter um id real de oportunidade, do
    # jeito que o sistema realmente produz esse encadeamento (Task 2/7).
    header_ant = {'title': 'Ata Anterior', 'meeting_date': None, 'meeting_time': None,
                  'topic': '', 'participants': []}
    managers_ant = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'proposta',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    anterior_id = toca._iata_save_record(header_ant, managers_ant, {}, 'texto', None)
    opp_anterior_id = toca._iata_load_record(anterior_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']

    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'antigo',
             'responsible': 'Ana', 'carried_over': False,
             'prev_opportunity_id': opp_anterior_id}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', anterior_id)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
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
    assert opp['prev_opportunity_id'] == opp_anterior_id, \
        'o encadeamento com a ata anterior se mantém'
    assert registro['reparse_failed'] == 0


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


def test_put_body_registro_inexistente_retorna_404(client, db_path):
    resp = client.put('/api/autotoca/iata/999999/body', json={'body_markdown': 'texto'})
    assert resp.status_code == 404


def test_put_body_ata_legada_sem_hierarquia_funciona(client, db_path, monkeypatch):
    """format_version=1: sem body_markdown e sem linhas na hierarquia. O
    PUT precisa funcionar mesmo assim — é exatamente o caminho pelo qual uma
    ata antiga ganha estrutura pela primeira vez."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''INSERT INTO iata_records (title, meeting_date, meeting_time, topic,
               participants, ata_json, insights_json, raw_text, format_version)
               VALUES (?,?,?,?,?,?,?,?,1)''',
            ('Ata Antiga', None, None, '', '[]', '{}', '[]', 'texto antigo'))
        rid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Ata Antiga', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev',
            'opportunities': [{'name': 'Migração SAP', 'update': 'texto novo',
                               'responsible': 'Ana'}]}]}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto novo'})
    assert resp.status_code == 200
    assert resp.get_json()['reparse_failed'] is False

    registro = toca._iata_load_record(rid)
    assert registro['body_markdown'] == 'texto novo'
    assert registro['managers'][0]['accounts'][0]['opportunities'][0]['update_text'] == 'texto novo'


def test_put_body_rename_de_conta_por_posicao_vira_sugestao_nao_confirmacao(
        client, db_path, monkeypatch):
    """Achado da revisão de qualidade da Task 9: se o usuário RENOMEIA a
    conta no texto editado, o casamento por name_norm com a conta antiga
    falha, e o fallback posicional entra (mesma ideia do robô de
    formulário: nome primeiro, posição como último recurso). Mas um
    casamento por posição é um PALPITE, não uma identidade confirmada — a
    primeira versão desta correção herdava `match_confirmed=True` cegamente
    do lado antigo, o que troca vínculos de CRM quando duas contas do
    mesmo gerente são renomeadas ao mesmo tempo (ver o teste de troca
    cruzada abaixo). A regra corrigida: o account_id/confidence viram
    SUGESTÃO (o usuário reconfirma em um clique), `match_confirmed` é
    sempre zerado quando o casamento veio por posição, e a resposta sinaliza
    o casamento posicional em `positional_matches` — nunca em silêncio."""
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

    # Usuário confirma o vínculo pela rota real, como faria na tela.
    assert client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_id}/link',
                       json={'account_id': account_id}).status_code == 200
    assert toca._iata_load_record(rid)['managers'][0]['accounts'][0]['match_confirmed'] is True

    # Ata editada: o nome da conta mudou de "Ambev" para "Ambev Brasil".
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev Brasil',
            'opportunities': []}]}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto editado'})
    assert resp.status_code == 200
    corpo = resp.get_json()
    assert corpo['reparse_failed'] is False
    assert corpo['positional_matches']['accounts'] == [
        {'manager': 'Ana', 'name': 'Ambev Brasil', 'previous_name': 'Ambev'}], \
        'o casamento posicional precisa ser sinalizado na resposta, não silencioso'

    conta = toca._iata_load_record(rid)['managers'][0]['accounts'][0]
    assert conta['name'] == 'Ambev Brasil'
    assert conta['account_id'] == account_id, \
        'account_id sobrevive como SUGESTÃO via fallback posicional'
    assert conta['match_confirmed'] is False, \
        'confirmação humana não pode nascer de um palpite posicional'


def test_put_body_troca_cruzada_de_duas_contas_nao_inverte_vinculos_confirmados(
        client, db_path, monkeypatch):
    """Reprodução exata do defeito crítico apontado na revisão: duas contas
    do mesmo gerente, "Ambev" e "Heineken", ambas com vínculo CONFIRMADO via
    /link. O usuário reescreve o texto renomeando as duas E invertendo a
    ordem em que aparecem. Sem a guarda de `match_confirmed=False` no
    casamento posicional, cada conta herdaria (por posição) o account_id
    CONFIRMADO da outra — "Heineken NV" ficaria com o vínculo confirmado da
    Ambev e vice-versa, uma troca de CRM silenciosa. Com a guarda, o
    account_id ainda é sugerido (por posição), mas nenhuma das duas fica
    marcada como confirmada — o usuário precisa reconfirmar. (O `account_id`
    sugerido por posição pode continuar sendo o da conta trocada — é só um
    palpite, sinalizado em `positional_matches`; o dano que a revisão
    apontou é especificamente a CONFIRMAÇÃO nascendo de um palpite, não o
    palpite em si.)"""
    conn = toca.get_db()
    conn.execute("INSERT INTO accounts (name) VALUES ('Ambev S.A.')")
    conn.execute("INSERT INTO accounts (name) VALUES ('Heineken Brasil')")
    conn.commit()
    account_id_ambev = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Ambev S.A.'").fetchone()[0]
    account_id_heineken = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Heineken Brasil'").fetchone()[0]
    conn.close()

    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [
        {'name': 'Ambev', 'account_id': None, 'match_confidence': 'alta', 'opportunities': []},
        {'name': 'Heineken', 'account_id': None, 'match_confidence': 'alta',
         'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)
    contas = toca._iata_load_record(rid)['managers'][0]['accounts']
    conta_ambev_id = next(a['id'] for a in contas if a['name'] == 'Ambev')
    conta_heineken_id = next(a['id'] for a in contas if a['name'] == 'Heineken')

    assert client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_ambev_id}/link',
                       json={'account_id': account_id_ambev}).status_code == 200
    assert client.post(f'/api/autotoca/iata/{rid}/accounts/{conta_heineken_id}/link',
                       json={'account_id': account_id_heineken}).status_code == 200

    # Texto editado: nomes reescritos E ordem invertida (Heineken antes de Ambev).
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [
            {'name': 'Heineken NV', 'opportunities': []},
            {'name': 'Ambev Brasil', 'opportunities': []}]}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto editado'})
    assert resp.status_code == 200

    corpo = resp.get_json()
    nomes_sinalizados = {p['name'] for p in corpo['positional_matches']['accounts']}
    assert nomes_sinalizados == {'Heineken NV', 'Ambev Brasil'}, \
        'as duas contas casadas por posição precisam aparecer sinalizadas'

    contas_depois = {a['name']: a for a in
                     toca._iata_load_record(rid)['managers'][0]['accounts']}
    heineken_nv = contas_depois['Heineken NV']
    ambev_brasil = contas_depois['Ambev Brasil']
    # O dano concreto que a revisão reproduziu: nenhuma das duas pode ficar
    # com um vínculo marcado como CONFIRMADO por um palpite posicional —
    # mesmo que o account_id sugerido tenha vindo trocado (é só sugestão).
    assert heineken_nv['match_confirmed'] is False, \
        'vínculo de "Heineken NV" não pode nascer confirmado de um palpite posicional'
    assert ambev_brasil['match_confirmed'] is False, \
        'vínculo de "Ambev Brasil" não pode nascer confirmado de um palpite posicional'


def test_put_body_rename_de_oportunidade_mantem_encadeamento_por_posicao(
        client, db_path, monkeypatch):
    """Mesmo raciocínio para o nome da oportunidade: corrigir um typo no
    nome ('Migraçao' -> 'Migração') quebra o casamento por name_norm com a
    oportunidade anterior. O fallback posicional garante que a próxima ata
    ainda encadeia (prev_opportunity_id não se perde)."""
    header_ant = {'title': 'Ata Anterior', 'meeting_date': None, 'meeting_time': None,
                  'topic': '', 'participants': []}
    managers_ant = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'proposta',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    anterior_id = toca._iata_save_record(header_ant, managers_ant, {}, 'texto', None)
    opp_anterior_id = toca._iata_load_record(anterior_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']

    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migraçao SAP', 'previous_status': None, 'update_text': 'antigo',
             'responsible': 'Ana', 'carried_over': False,
             'prev_opportunity_id': opp_anterior_id}]}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', anterior_id)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev',
            'opportunities': [{'name': 'Migração SAP', 'update': 'texto novo',
                               'responsible': 'Ana'}]}]}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto corrigido'})
    assert resp.status_code == 200

    opp = toca._iata_load_record(rid)['managers'][0]['accounts'][0]['opportunities'][0]
    assert opp['name'] == 'Migração SAP'
    assert opp['prev_opportunity_id'] == opp_anterior_id, \
        'correção de typo não deve quebrar o encadeamento com a ata anterior'


def test_put_body_extras_e_insights_json_preservados_apos_reparse(client, db_path, monkeypatch):
    """O reparse não extrai seções opcionais (insights) do texto livre —
    documenta que `extras`/`insights_json` continuam sendo os da geração
    original mesmo depois de uma edição bem-sucedida."""
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': []}]
    extras = {'insights': [{'pain': 'dor', 'matched_offer': 'Oferta X',
                            'confidence': 'alta', 'observation': 'obs'}]}
    rid = toca._iata_save_record(header, managers, extras, 'texto', None)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'X', 'managers': [{'name': 'Ana', 'accounts': []}]}))

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto editado'})
    assert resp.status_code == 200

    registro = toca._iata_load_record(rid)
    assert registro['extras'] == extras
    assert registro['insights_json'] == extras['insights']


def test_put_body_falha_inesperada_no_meio_nao_apaga_o_reparse_failed(
        client, db_path, monkeypatch):
    """Se algo explodir DEPOIS do texto já ter sido gravado (passo 1) mas
    ANTES do reparse concluir com sucesso (passo 3), o registro não pode
    ficar com `body_edited=1` e `reparse_failed=0` mentindo que a
    hierarquia está em dia. `reparse_failed` é marcado 1 já no passo 1 e só
    volta a 0 quando o reparse realmente termina — então uma falha no meio
    deixa o sinal ligado, não apagado."""
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': []}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    def _explode(*a, **k):
        raise RuntimeError('falha simulada depois de gravar o texto')
    monkeypatch.setattr(toca, '_llm_prompt', _explode)

    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': 'texto novo'})
    assert resp.status_code == 500

    registro = toca._iata_load_record(rid)
    assert registro['body_markdown'] == 'texto novo', 'texto gravado antes da exceção sobrevive'
    assert registro['body_edited'] == 1
    assert registro['reparse_failed'] == 1, \
        'assume falho até prova em contrário — nunca "sucesso" por omissão'


# --- Task 9: defeitos críticos/importantes achados na revisão de qualidade -

def test_put_body_edicao_remapeia_encadeamento_de_ata_futura(client, db_path, monkeypatch):
    """Reprodução exata do defeito CRÍTICO da revisão: ata1 -> ata2 -> ata3
    (ata3 encadeada com a oportunidade de ata2 via `prev_opportunity_id`).
    Editar o texto de ata2 com re-parse bem-sucedido faz
    `_iata_write_hierarchy` apagar e reinserir as oportunidades de ata2 —
    nova identidade FÍSICA (id novo) para a MESMA oportunidade lógica. Sem
    remapeamento, o `ON DELETE SET NULL` da FK dispara em cascata e apaga
    silenciosamente o `prev_opportunity_id` de ata3, mesmo a rota nunca
    tendo tocado em ata3."""
    header1 = {'title': 'Ata 1', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers1 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'inicio',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    ata1_id = toca._iata_save_record(header1, managers1, {}, 'texto', None)
    opp1_id = toca._iata_load_record(ata1_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']

    header2 = {'title': 'Ata 2', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers2 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': 'inicio', 'update_text': 'meio',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': opp1_id}]}]}]
    ata2_id = toca._iata_save_record(header2, managers2, {}, 'texto', ata1_id)
    opp2_id = toca._iata_load_record(ata2_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']

    header3 = {'title': 'Ata 3', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers3 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': 'meio', 'update_text': 'fim',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': opp2_id}]}]}]
    ata3_id = toca._iata_save_record(header3, managers3, {}, 'texto', ata2_id)

    assert toca._iata_load_record(ata3_id)['managers'][0]['accounts'][0][
        'opportunities'][0]['prev_opportunity_id'] == opp2_id

    # Edita o texto de ata2 — mesmo nome de oportunidade, reparse bem-sucedido,
    # mas fisicamente _iata_write_hierarchy vai apagar e recriar a linha.
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Ata 2', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev',
            'opportunities': [{'name': 'Migração SAP', 'update': 'meio editado',
                               'responsible': 'Ana'}]}]}]}))
    resp = client.put(f'/api/autotoca/iata/{ata2_id}/body',
                      json={'body_markdown': 'texto editado'})
    assert resp.status_code == 200

    opp2_novo_id = toca._iata_load_record(ata2_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']
    assert opp2_novo_id != opp2_id, \
        'pré-condição do teste: o DELETE+INSERT precisa ter dado um id físico novo'

    prev_id_depois = toca._iata_load_record(ata3_id)['managers'][0]['accounts'][0][
        'opportunities'][0]['prev_opportunity_id']
    assert prev_id_depois is not None, \
        'editar ata2 não pode apagar silenciosamente o encadeamento de ata3'
    assert prev_id_depois == opp2_novo_id, \
        'o encadeamento de ata3 precisa apontar para o id NOVO da oportunidade de ata2'


def test_put_body_edicao_que_remove_oportunidade_limpa_encadeamento_honesto(
        client, db_path, monkeypatch):
    """Contraparte do teste acima: se a oportunidade que ata3 encadeia
    REALMENTE sumiu do texto editado de ata2 (o usuário apagou aquele
    trecho), não há id novo correspondente — `prev_opportunity_id` de ata3
    deve mesmo virar `None` (via `ON DELETE SET NULL`). Isso não é bug: é o
    resultado honesto quando não há mais nada para encadear."""
    header1 = {'title': 'Ata 1', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers1 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': None, 'update_text': 'inicio',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    ata1_id = toca._iata_save_record(header1, managers1, {}, 'texto', None)

    header2 = {'title': 'Ata 2', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers2 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': 'inicio', 'update_text': 'meio',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    ata2_id = toca._iata_save_record(header2, managers2, {}, 'texto', ata1_id)
    opp2_id = toca._iata_load_record(ata2_id)[
        'managers'][0]['accounts'][0]['opportunities'][0]['id']

    header3 = {'title': 'Ata 3', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers3 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'Migração SAP', 'previous_status': 'meio', 'update_text': 'fim',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': opp2_id}]}]}]
    ata3_id = toca._iata_save_record(header3, managers3, {}, 'texto', ata2_id)

    # Texto editado de ata2: a conta/oportunidade "Migração SAP" some de vez.
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Ata 2', 'managers': [{'name': 'Ana', 'accounts': []}]}))
    resp = client.put(f'/api/autotoca/iata/{ata2_id}/body',
                      json={'body_markdown': 'texto sem a oportunidade'})
    assert resp.status_code == 200

    prev_id_depois = toca._iata_load_record(ata3_id)['managers'][0]['accounts'][0][
        'opportunities'][0]['prev_opportunity_id']
    assert prev_id_depois is None, \
        'sem correspondente novo, None é o resultado honesto — não um bug'


def test_put_body_dois_puts_concorrentes_nao_entrelacam_texto_e_hierarquia(
        client, db_path, monkeypatch):
    """Reprodução do defeito IMPORTANTE da revisão: PUT A (IA lenta) e PUT B
    (rápida) na MESMA ata, concorrentes. Sem lock, cada um abre suas
    próprias transações e o resultado final mistura `body_markdown` de uma
    edição com a hierarquia de outra. Um lock em memória por `record_id`
    serializa os dois PUTs — o que espera a vez sempre parte do resultado
    já commitado do outro, nunca de uma leitura no meio do caminho."""
    header = {'title': 'X', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': []}]}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    import threading
    import time

    def _llm_prompt_fake(prompt, **kwargs):
        if 'texto A (lento)' in prompt:
            time.sleep(0.3)
            return json.dumps({'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [
                {'name': 'Ambev', 'opportunities': [
                    {'name': 'Oportunidade A', 'update': 'A', 'responsible': 'Ana'}]}]}]})
        return json.dumps({'title': 'X', 'managers': [{'name': 'Ana', 'accounts': [
            {'name': 'Ambev', 'opportunities': [
                {'name': 'Oportunidade B', 'update': 'B', 'responsible': 'Ana'}]}]}]})

    monkeypatch.setattr(toca, '_llm_prompt', _llm_prompt_fake)

    resultados = {}

    def _put(nome, texto):
        # Cada thread usa seu próprio test client: o client do Flask não é
        # seguro para chamadas concorrentes vindas de threads diferentes
        # (contexto de request/app é thread-local por baixo dos panos).
        with toca.app.test_client() as thread_client:
            resp = thread_client.put(f'/api/autotoca/iata/{rid}/body',
                                     json={'body_markdown': texto})
            resultados[nome] = resp.get_json()

    t_a = threading.Thread(target=_put, args=('A', 'texto A (lento)'))
    t_b = threading.Thread(target=_put, args=('B', 'texto B'))
    t_a.start()
    time.sleep(0.05)  # garante que A já está dentro do lock quando B tenta entrar
    t_b.start()
    t_a.join()
    t_b.join()

    registro = toca._iata_load_record(rid)
    nome_opp = registro['managers'][0]['accounts'][0]['opportunities'][0]['name']
    if registro['body_markdown'] == 'texto A (lento)':
        assert nome_opp == 'Oportunidade A', \
            'texto e hierarquia precisam vir da MESMA edição, nunca misturados'
    else:
        assert registro['body_markdown'] == 'texto B'
        assert nome_opp == 'Oportunidade B', \
            'texto e hierarquia precisam vir da MESMA edição, nunca misturados'


def test_put_body_mantem_titulo_anterior_quando_ainda_aparece_no_texto(
        client, db_path, monkeypatch):
    """Defeito IMPORTANTE da revisão: a IA reformula o título mesmo quando o
    usuário só corrigiu um typo no corpo. Se o título antigo ainda aparece
    no texto editado (comparado por normalize_name), ele prevalece — a IA
    não pode reescrever o cabeçalho por conta própria."""
    header = {'title': 'Reunião Ambev - Q3', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': []}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Reunião comercial Ambev',  # a IA reformulou por conta própria
        'managers': [{'name': 'Ana', 'accounts': []}]}))

    corpo_editado = 'Reunião Ambev - Q3\nGerente Comercial: Ana\n(typo corrigido no meio)'
    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': corpo_editado})
    assert resp.status_code == 200

    registro = toca._iata_load_record(rid)
    assert registro['title'] == 'Reunião Ambev - Q3', \
        'título antigo ainda está no corpo -- a IA não pode trocá-lo por conta própria'


def test_put_body_aceita_titulo_novo_quando_antigo_sumiu_do_texto(client, db_path, monkeypatch):
    """Contraparte: quando o usuário reescreve o cabeçalho de propósito (o
    título antigo não aparece mais em lugar nenhum do corpo editado), a
    mudança é aceita — foi uma decisão deliberada, não um efeito colateral
    da IA reformulando."""
    header = {'title': 'Reunião Ambev - Q3', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    managers = [{'name': 'Ana', 'accounts': []}]
    rid = toca._iata_save_record(header, managers, {}, 'texto', None)

    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Reunião Pipeline Setembro',
        'managers': [{'name': 'Ana', 'accounts': []}]}))

    corpo_editado = 'Reunião Pipeline Setembro\nGerente Comercial: Ana'
    resp = client.put(f'/api/autotoca/iata/{rid}/body', json={'body_markdown': corpo_editado})
    assert resp.status_code == 200

    registro = toca._iata_load_record(rid)
    assert registro['title'] == 'Reunião Pipeline Setembro', \
        'título antigo sumiu do corpo -- a mudança deliberada do usuário deve valer'


def test_put_body_duas_oportunidades_ambiguas_remapeiam_cruzado_mas_sinalizadas(
        client, db_path, monkeypatch):
    """Limite conhecido do fallback posicional, fixado por teste.

    Quando o usuário renomeia DUAS oportunidades da mesma conta numa só
    edição e ainda inverte a ordem, o casamento por posição não tem como
    distinguir "renomeou" de "trocou de lugar" — o encadeamento das atas
    futuras sai cruzado. O que a correção garante não é acertar esse caso
    (impossível sem perguntar ao usuário), e sim que ele NÃO seja silencioso:
    `positional_matches` reporta as duas trocas, do mesmo jeito que o robô de
    formulários do projeto reporta o fallback posicional para conferência
    visual. Se algum dia esse sinal sumir, este teste quebra.
    """
    header1 = {'title': 'Ata 1', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers1 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'OppX', 'previous_status': None, 'update_text': 'x1',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None},
            {'name': 'OppY', 'previous_status': None, 'update_text': 'y1',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': None}]}]}]
    ata1_id = toca._iata_save_record(header1, managers1, {}, 'texto', None)
    opps1 = toca._iata_load_record(ata1_id)['managers'][0]['accounts'][0]['opportunities']
    id_x, id_y = opps1[0]['id'], opps1[1]['id']

    header2 = {'title': 'Ata 2', 'meeting_date': None, 'meeting_time': None,
               'topic': '', 'participants': []}
    managers2 = [{'name': 'Ana', 'accounts': [{'name': 'Ambev', 'account_id': None,
        'match_confidence': None, 'opportunities': [
            {'name': 'ContinuacaoDeX', 'previous_status': 'x1', 'update_text': 'x2',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': id_x},
            {'name': 'ContinuacaoDeY', 'previous_status': 'y1', 'update_text': 'y2',
             'responsible': 'Ana', 'carried_over': False, 'prev_opportunity_id': id_y}]}]}]
    ata2_id = toca._iata_save_record(header2, managers2, {}, 'texto', ata1_id)

    # Renomeia as duas E inverte a ordem em que aparecem no texto.
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: json.dumps({
        'title': 'Ata 1', 'managers': [{'name': 'Ana', 'accounts': [{'name': 'Ambev',
            'opportunities': [
                {'name': 'OppY renomeada', 'update': 'y1', 'responsible': 'Ana'},
                {'name': 'OppX renomeada', 'update': 'x1', 'responsible': 'Ana'}]}]}]}))
    resp = client.put(f'/api/autotoca/iata/{ata1_id}/body',
                      json={'body_markdown': 'texto editado'})

    assert resp.status_code == 200
    sinalizadas = resp.get_json().get('positional_matches', {}).get('opportunities') or []
    assert len(sinalizadas) == 2, (
        'as duas oportunidades casadas por posição precisam ser reportadas — '
        'sem esse sinal, o cruzamento do encadeamento fica invisível para o usuário')


# ---------------------------------------------------------------------------
# Task 10: preview e envio por e-mail
# ---------------------------------------------------------------------------

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


def test_preview_ata_nao_encontrada_retorna_404(client, db_path):
    resp = client.get('/api/autotoca/iata/999999/email/preview')
    assert resp.status_code == 404


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


def test_email_ata_nao_encontrada_retorna_404(client, db_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError('não deveria enviar e-mail para ata inexistente')
    monkeypatch.setattr(toca, '_outlook_send_mail', _boom)
    resp = client.post('/api/autotoca/iata/999999/email', json={'to': ['a@x.com']})
    assert resp.status_code == 404


def test_email_dedup_destinatarios_repetidos(client, db_path, monkeypatch):
    """O mesmo endereço, repetido na lista de destinatários (ex.: colado duas
    vezes no campo de texto do frontend), não pode gerar dois envios reais —
    duplicaria a caixa de entrada do destinatário sem nenhum benefício."""
    rid = _ata_para_email(db_path)
    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: enviados.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email',
                       json={'to': ['dup@x.com', 'outro@x.com', 'dup@x.com']})

    assert resp.status_code == 200
    assert enviados == ['dup@x.com', 'outro@x.com'], (
        'endereço duplicado deve ser enviado uma única vez, preservando a primeira ordem')
    assert [r['to'] for r in resp.get_json()['results']] == ['dup@x.com', 'outro@x.com']


def test_email_endereco_invalido_nao_chama_outlook(client, db_path, monkeypatch):
    """Endereço malformado deve ser rejeitado antes de qualquer chamada real
    ao Graph — não faz sentido gastar uma tentativa de rede (e um possível
    erro genérico do Outlook) num endereço que já sabemos ser inválido."""
    rid = _ata_para_email(db_path)
    chamadas = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: chamadas.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email',
                       json={'to': ['nao-e-um-email']})

    assert resp.status_code == 207
    assert chamadas == [], '_outlook_send_mail não deveria ter sido chamado'
    resultado = resp.get_json()['results'][0]
    assert resultado['ok'] is False
    assert 'inválido' in resultado['error'].lower()


def test_preview_avisa_quando_hierarquia_desatualizada(client, db_path, monkeypatch):
    """Quando o re-parse de uma edição de texto falha, a hierarquia salva
    fica desatualizada em relação ao body_markdown editado pelo usuário — o
    e-mail (renderizado a partir da hierarquia) sairia com conteúdo antigo.
    O preview precisa expor isso claramente."""
    rid = _ata_para_email(db_path)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'desculpe, não consegui')
    put_resp = client.put(f'/api/autotoca/iata/{rid}/body',
                          json={'body_markdown': 'texto editado que não foi reestruturado'})
    assert put_resp.get_json()['reparse_failed'] is True

    resp = client.get(f'/api/autotoca/iata/{rid}/email/preview')
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['stale'] is True
    assert payload.get('warning')


def test_email_bloqueia_quando_hierarquia_desatualizada(client, db_path, monkeypatch):
    rid = _ata_para_email(db_path)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'desculpe, não consegui')
    client.put(f'/api/autotoca/iata/{rid}/body',
              json={'body_markdown': 'texto editado que não foi reestruturado'})

    chamadas = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: chamadas.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email', json={'to': ['a@x.com']})

    assert resp.status_code == 409
    assert chamadas == [], 'não pode enviar e-mail com conteúdo desatualizado sem confirmação'
    assert resp.get_json().get('stale') is True


def test_email_envia_quando_confirma_hierarquia_desatualizada(client, db_path, monkeypatch):
    rid = _ata_para_email(db_path)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'desculpe, não consegui')
    client.put(f'/api/autotoca/iata/{rid}/body',
              json={'body_markdown': 'texto editado que não foi reestruturado'})

    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: enviados.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email',
                       json={'to': ['a@x.com'], 'confirm_stale': True})

    assert resp.status_code == 200
    assert enviados == ['a@x.com']


def _cria_ata_legada(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            '''INSERT INTO iata_records
               (title, meeting_date, meeting_time, topic, participants, ata_json,
                insights_json, raw_text, body_markdown, body_edited, reparse_failed,
                format_version)
               VALUES (?,?,?,?,?,?,?,?,?,0,0,1)''',
            ('Ata legada', '01/01/2020', '09:00', '', '[]', '{}', '[]', 'texto cru', None))
        conn.commit()
        rid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    finally:
        conn.close()
    return rid


def test_preview_ata_legada_sem_hierarquia_bloqueia(client, db_path):
    rid = _cria_ata_legada(db_path)
    resp = client.get(f'/api/autotoca/iata/{rid}/email/preview')
    assert resp.status_code == 422
    assert resp.get_json().get('error')


def test_email_ata_legada_sem_hierarquia_bloqueia(client, db_path, monkeypatch):
    rid = _cria_ata_legada(db_path)
    chamadas = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, html, attachments=None: chamadas.append(to))

    resp = client.post(f'/api/autotoca/iata/{rid}/email', json={'to': ['a@x.com']})

    assert resp.status_code == 422
    assert chamadas == []


def test_email_ata_sem_estrutura_com_texto_editado_culpa_o_reparse_nao_o_formato(
        client, db_path, monkeypatch):
    """Ata legada que o usuário escreveu à mão e cujo re-parse falhou: a
    mensagem tem que dizer que o problema é o re-parse (corrigir o texto
    resolve), não que o registro é de "formato antigo" — isso sugeriria uma
    limitação permanente e o usuário desistiria sem saber o que fazer."""
    header = {'title': 'Ata Legada', 'meeting_date': None, 'meeting_time': None,
              'topic': '', 'participants': []}
    rid = toca._iata_save_record(header, [], {}, 'texto', None)
    conn = toca.get_db()
    conn.execute('UPDATE iata_records SET format_version = 1 WHERE id = ?', (rid,))
    conn.commit()
    conn.close()

    # O usuário escreve a ata inteira à mão e o re-parse não consegue estruturar.
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'desculpe, não consegui')
    resp = client.put(f'/api/autotoca/iata/{rid}/body',
                      json={'body_markdown': 'Gerente Comercial: Ana\n  * Ambev'})
    assert resp.status_code == 200 and resp.get_json()['reparse_failed'] is True

    preview = client.get(f'/api/autotoca/iata/{rid}/email/preview')
    assert preview.status_code == 422
    erro = preview.get_json()['error']
    assert 'não conseguiu convertê-lo' in erro or 'Ajuste o texto' in erro, erro
    assert 'formato antigo' not in erro, \
        'culpar o formato antigo aqui engana: o texto é novo, quem falhou foi o re-parse'


def test_email_subject_colapsa_quebra_de_linha_do_titulo():
    header = {'title': 'Pipeline\nSemanal', 'meeting_date': '04/08/2026'}
    assert iata_lib.email_subject(header) == 'Ata — Pipeline Semanal — 04/08/2026'
