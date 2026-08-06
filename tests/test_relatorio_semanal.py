# -*- coding: utf-8 -*-
"""Relatório Semanal do AutoToca — compilação do período e resumo por assunto.

Os testes cobrem a coleta das três fontes exigidas (atividades, Agenda e
Kanban), o recorte por período, o casamento do nome de contato devolvido pelo
LLM com o cadastro (é o que traz nome/foto para a tela) e o fallback heurístico
quando nenhum provider de LLM responde.

As atividades são inseridas direto no banco porque `POST /api/atividades` sempre
grava `activity_date = CURRENT_TIMESTAMP` — não há como datar um registro fora
da janela pela API.
"""

import json
import sqlite3
import time
from datetime import date, timedelta

import pytest

import app as toca


HOJE = date.today()
DENTRO = (HOJE - timedelta(days=2)).isoformat()
FORA = (HOJE - timedelta(days=90)).isoformat()


def _seed_conta(client, nome='Conta Alfa S.A.'):
    resp = client.post('/api/accounts', data={'name': nome})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['id'], nome


def _seed_contato(client, nome, empresa, cargo='Diretor de TI'):
    resp = client.post('/api/clientes', data={
        'name': nome, 'company': empresa, 'position': cargo,
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['id']


def _exec(db_path, sql, params=()):
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(sql, params)
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def _seed_atividade(db_path, client_id, contact_type, information, description, quando):
    return _exec(db_path,
                 'INSERT INTO activities (client_id, contact_type, information, description, '
                 'activity_date) VALUES (?, ?, ?, ?, ?)',
                 (client_id, contact_type, information, description, quando))


def _coletar(db_path, account_id, start_date, end_date):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM accounts WHERE id = ?', (account_id,))
    account = toca.dict_from_row(c.fetchone())
    data = toca._weekly_report_collect_account(c, account, start_date, end_date)
    conn.close()
    return data


@pytest.fixture()
def _sem_llm(monkeypatch):
    """Nenhum provider responde — força o caminho de fallback heurístico."""
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: None)


def test_contas_do_modal_traz_total_de_contatos(client):
    account_id, nome = _seed_conta(client)
    _seed_contato(client, 'Ana Souza', nome)
    _seed_contato(client, 'Bruno Lima', nome)
    _seed_contato(client, 'Fora da Conta', 'Outra Empresa')

    resp = client.get('/api/autotoca/relatorio-semanal/contas')
    assert resp.status_code == 200
    contas = {row['id']: row for row in resp.get_json()}
    assert contas[account_id]['contacts_count'] == 2


def test_coleta_reune_atividade_agenda_e_kanban_do_periodo(client, db_path):
    account_id, nome = _seed_conta(client)
    contato_id = _seed_contato(client, 'Ana Souza', nome)

    # Atividade dentro e outra fora da janela
    _seed_atividade(db_path, contato_id, 'Reunião', 'Renovação de contrato',
                    'Discutimos a renovação do contrato de cloud.', DENTRO)
    _seed_atividade(db_path, contato_id, 'Email', 'Assunto antigo',
                    'Fora do período.', FORA)

    # Agenda (commitments) — um dentro, um fora
    _exec(db_path, 'INSERT INTO commitments (client_id, title, notes, due_date, source_type) '
                   'VALUES (?, ?, ?, ?, ?)',
          (contato_id, 'Follow-up da proposta', 'Revisar escopo de cloud', DENTRO, 'manual'))
    _exec(db_path, 'INSERT INTO commitments (client_id, title, notes, due_date, source_type) '
                   'VALUES (?, ?, ?, ?, ?)',
          (contato_id, 'Compromisso velho', 'Fora do período', FORA, 'manual'))

    # Atividade lançada na própria conta
    _exec(db_path, 'INSERT INTO account_activities (account_id, description, activity_date) '
                   'VALUES (?, ?, ?)',
          (account_id, 'Reunião de governança com o board.', DENTRO))

    # Kanban: card antigo que recebeu comentário dentro da janela precisa entrar
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
    column_id = c.fetchone()['id']
    c.execute('INSERT INTO kanban_cards (title, description, account_id, contact_id, column_id, '
              'created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
              ('Projeto Cyber', 'Assessment de segurança', account_id, contato_id, column_id,
               FORA, FORA))
    card_id = c.lastrowid
    c.execute('INSERT INTO kanban_card_activities (card_id, content, created_at) VALUES (?, ?, ?)',
              (card_id, 'Cliente aprovou o escopo do assessment.', DENTRO))
    conn.commit()
    conn.close()

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())

    assert data['counts']['atividades'] == 2      # 1 do contato + 1 da conta
    assert data['counts']['agenda'] == 1
    assert data['counts']['kanban'] == 1
    assert data['counts']['total'] == 4

    fontes = {e['source'] for e in data['events']}
    assert fontes == {'Atividade', 'Atividade da conta', 'Agenda', 'Kanban'}

    textos = ' '.join(e['text'] for e in data['events'])
    assert 'Fora do período' not in textos
    assert 'Cliente aprovou o escopo do assessment.' in textos

    # Só o contato que aparece nos registros entra na lista com foto/cargo
    assert [c['name'] for c in data['contacts']] == ['Ana Souza']


def test_coleta_ignora_card_de_kanban_fora_do_periodo(client, db_path):
    account_id, nome = _seed_conta(client)
    conn = toca.get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM kanban_columns ORDER BY display_order, id LIMIT 1')
    column_id = c.fetchone()['id']
    c.execute('INSERT INTO kanban_cards (title, description, account_id, column_id, '
              'created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
              ('Card parado', 'Nada aconteceu', account_id, column_id, FORA, FORA))
    conn.commit()
    conn.close()

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    assert data['counts']['kanban'] == 0


def test_coleta_traz_renovacao_da_agenda_da_conta(client, db_path):
    account_id, nome = _seed_conta(client)
    presence_id = _exec(db_path,
                        'INSERT INTO account_presences (account_id, delivery_name) VALUES (?, ?)',
                        (account_id, 'Service Desk'))
    _exec(db_path, 'INSERT INTO account_renewal_events (account_id, presence_id, title, due_date) '
                   'VALUES (?, ?, ?, ?)',
          (account_id, presence_id, 'Renovação Service Desk', DENTRO))

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    assert data['counts']['agenda'] == 1
    assert 'Service Desk' in data['events'][0]['text']


def test_coleta_ignora_conta_sem_registros(client, db_path):
    account_id, nome = _seed_conta(client)
    _seed_contato(client, 'Ana Souza', nome)

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    assert data['counts']['total'] == 0
    assert data['contacts'] == []
    assert data['all_contacts'][0]['name'] == 'Ana Souza'


def test_analise_casa_contato_do_llm_com_o_cadastro(client, db_path, monkeypatch):
    account_id, nome = _seed_conta(client)
    contato_id = _seed_contato(client, 'Ana Souza', nome)
    _seed_atividade(db_path, contato_id, 'Reunião', 'Cloud',
                    'Avanço no projeto de cloud.', DENTRO)

    # O LLM devolve o nome sem acento e em caixa diferente — tem que casar
    resposta = json.dumps({
        'resumo_periodo': 'A conta avançou no projeto de cloud.',
        'assuntos': [{
            'assunto': 'Projeto de Cloud',
            'resumo': 'Escopo aprovado na reunião da semana.',
            'contatos': ['ana souza', 'Contato Inexistente'],
            'origens': ['atividade', 'inventado'],
            'status': 'avancou',
        }],
        'proximos_passos': ['Enviar proposta revisada'],
        'alertas': [],
    }, ensure_ascii=False)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: f'Segue o JSON:\n{resposta}')

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    analise, llm_used = toca._weekly_report_analyze(data, DENTRO, HOJE.isoformat())

    assert llm_used is True
    assunto = analise['assuntos'][0]
    assert assunto['assunto'] == 'Projeto de Cloud'
    assert [c['name'] for c in assunto['contatos']] == ['Ana Souza']
    assert assunto['contatos_nao_identificados'] == ['Contato Inexistente']
    assert assunto['origens'] == ['Atividade']          # 'inventado' descartado
    assert assunto['status'] == 'avancou'
    assert analise['proximos_passos'] == ['Enviar proposta revisada']


def test_analise_cai_para_heuristica_sem_llm(client, db_path, _sem_llm):
    account_id, nome = _seed_conta(client)
    contato_id = _seed_contato(client, 'Ana Souza', nome)
    _seed_atividade(db_path, contato_id, 'Reunião', 'Cloud',
                    'Landing zone em azure discutida.', DENTRO)

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    analise, llm_used = toca._weekly_report_analyze(data, DENTRO, HOJE.isoformat())

    assert llm_used is False
    assert 'sem IA' in analise['resumo_periodo']
    assert analise['assuntos'], 'o fallback deve agrupar os registros por tópico'
    assert [c['name'] for c in analise['assuntos'][0]['contatos']] == ['Ana Souza']


def test_analise_cai_para_heuristica_quando_llm_nao_devolve_json(client, db_path, monkeypatch):
    account_id, nome = _seed_conta(client)
    contato_id = _seed_contato(client, 'Ana Souza', nome)
    _seed_atividade(db_path, contato_id, 'Reunião', 'Cloud', 'Azure em pauta.', DENTRO)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: 'Desculpe, não consigo responder.')

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    analise, llm_used = toca._weekly_report_analyze(data, DENTRO, HOJE.isoformat())

    assert llm_used is False
    assert analise['assuntos']


def test_analise_sem_registros_nao_chama_llm(client, db_path, monkeypatch):
    account_id, nome = _seed_conta(client)
    _seed_contato(client, 'Ana Souza', nome)

    chamou = []

    def _falha(*a, **k):
        chamou.append(1)
        return 'x'

    monkeypatch.setattr(toca, '_llm_prompt', _falha)

    data = _coletar(db_path, account_id, DENTRO, HOJE.isoformat())
    analise, llm_used = toca._weekly_report_analyze(data, DENTRO, HOJE.isoformat())

    assert chamou == []
    assert llm_used is False
    assert analise['assuntos'] == []
    assert 'Nenhum registro' in analise['resumo_periodo']


def test_endpoint_valida_entrada(client):
    assert client.post('/api/autotoca/relatorio-semanal', json={}).status_code == 400
    assert client.post('/api/autotoca/relatorio-semanal',
                       json={'account_ids': [1], 'start_date': '06/08/2026'}).status_code == 400
    resp = client.post('/api/autotoca/relatorio-semanal', json={
        'account_ids': [1], 'start_date': '2026-08-10', 'end_date': '2026-08-01'})
    assert resp.status_code == 400
    assert 'posterior' in resp.get_json()['error']


def test_endpoint_gera_relatorio_ponta_a_ponta(client, db_path, _sem_llm):
    account_id, nome = _seed_conta(client)
    contato_id = _seed_contato(client, 'Ana Souza', nome)
    _seed_atividade(db_path, contato_id, 'Reunião', 'Cloud',
                    'Discussão de migração para azure.', DENTRO)

    resp = client.post('/api/autotoca/relatorio-semanal', json={
        'account_ids': [account_id, account_id],   # duplicata deve ser ignorada
        'start_date': DENTRO, 'end_date': HOJE.isoformat(),
    })
    assert resp.status_code == 202
    task_id = resp.get_json()['task_id']

    task = {}
    for _ in range(120):
        task = client.get(f'/api/autotoca/relatorio-semanal/tasks/{task_id}').get_json()
        if task.get('status') in ('done', 'error'):
            break
        time.sleep(0.05)

    assert task.get('status') == 'done', task
    result = task['result']
    assert result['period'] == {'start_date': DENTRO, 'end_date': HOJE.isoformat()}
    assert result['totals']['accounts'] == 1
    conta = result['accounts'][0]
    assert conta['account']['name'] == nome
    assert conta['counts']['atividades'] == 1
    assert conta['llm_used'] is False
    assert [c['name'] for c in conta['contacts']] == ['Ana Souza']


def test_endpoint_conta_inexistente_reporta_erro(client, _sem_llm):
    resp = client.post('/api/autotoca/relatorio-semanal', json={
        'account_ids': [98765], 'start_date': DENTRO, 'end_date': HOJE.isoformat()})
    assert resp.status_code == 202
    task_id = resp.get_json()['task_id']

    task = {}
    for _ in range(120):
        task = client.get(f'/api/autotoca/relatorio-semanal/tasks/{task_id}').get_json()
        if task.get('status') in ('done', 'error'):
            break
        time.sleep(0.05)
    assert task.get('status') == 'error'
    assert 'Nenhuma das contas selecionadas' in task['error']


def test_task_inexistente_retorna_404(client):
    resp = client.get('/api/autotoca/relatorio-semanal/tasks/naoexiste')
    assert resp.status_code == 404
    assert resp.get_json()['status'] == 'not_found'
