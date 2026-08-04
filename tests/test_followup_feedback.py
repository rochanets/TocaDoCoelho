"""Follow-up de compromisso na agenda e módulo de Feedback."""

import time

import app as toca


# ---------------------------------------------------------------------------
# Parte 1 — Follow-up do compromisso
# ---------------------------------------------------------------------------

def _criar_compromisso(client, client_id, due_date='2026-09-10'):
    resp = client.post('/api/agenda', json={
        'client_id': client_id,
        'due_date': due_date,
        'due_time': '14:00',
        'title': 'Reunião de alinhamento',
    })
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()['item']['id']


def test_agenda_expoe_followup_activity_id(client, sample_client_id):
    _criar_compromisso(client, sample_client_id)

    itens = client.get('/api/agenda').get_json()
    assert itens, 'a agenda deveria listar o compromisso criado'
    assert 'followup_activity_id' in itens[0]
    assert itens[0]['followup_activity_id'] is None


def test_followup_vincula_atividade_ao_compromisso(client, sample_client_id):
    commitment_id = _criar_compromisso(client, sample_client_id)

    atividade = client.post('/api/atividades', json={
        'client_id': sample_client_id,
        'contact_type': 'Reunião',
        'information': 'Follow-up do compromisso "Reunião de alinhamento": cliente pediu proposta.',
    })
    assert atividade.status_code == 201
    activity_id = atividade.get_json()['id']

    resp = client.post(f'/api/agenda/{commitment_id}/followup', json={'activity_id': activity_id})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['followup_activity_id'] == activity_id

    item = client.get('/api/agenda').get_json()[0]
    assert item['followup_activity_id'] == activity_id


def test_followup_rejeita_atividade_de_outro_contato(client, sample_client_id):
    commitment_id = _criar_compromisso(client, sample_client_id)

    outro = client.post('/api/clientes', data={
        'name': 'Beltrano', 'company': 'Outra Empresa', 'position': 'Diretor',
    }).get_json()['id']
    atividade_alheia = client.post('/api/atividades', json={
        'client_id': outro,
        'contact_type': 'Email',
        'information': 'Atividade de outro contato',
    }).get_json()['id']

    resp = client.post(f'/api/agenda/{commitment_id}/followup', json={'activity_id': atividade_alheia})
    assert resp.status_code == 400
    assert 'outro contato' in resp.get_json()['error']

    assert client.get('/api/agenda').get_json()[0]['followup_activity_id'] is None


def test_followup_valida_entrada(client, sample_client_id):
    commitment_id = _criar_compromisso(client, sample_client_id)

    assert client.post(f'/api/agenda/{commitment_id}/followup', json={}).status_code == 400
    assert client.post(f'/api/agenda/{commitment_id}/followup',
                       json={'activity_id': 999999}).status_code == 400
    assert client.post('/api/agenda/999999/followup',
                       json={'activity_id': 1}).status_code == 404


# ---------------------------------------------------------------------------
# Parte 2 — Feedback
# ---------------------------------------------------------------------------

def _aguardar_task(client, task_id, timeout=5.0):
    limite = time.time() + timeout
    task = {}
    while time.time() < limite:
        task = client.get(f'/api/feedback/tasks/{task_id}').get_json()
        if task.get('status') in ('done', 'error'):
            return task
        time.sleep(0.05)
    return task


def test_feedback_envia_email_com_log_anexado(client, monkeypatch, tmp_path):
    log_file = tmp_path / 'app.log'
    log_file.write_text('linha de log 1\nlinha de log 2\n', encoding='utf-8')
    monkeypatch.setattr(toca, 'LOG_FILE', log_file)

    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, body, attachments=None:
                        enviados.append((to, subject, body, attachments)))

    resp = client.post('/api/feedback', json={'message': 'A agenda está lenta ao abrir o mês.'})
    assert resp.status_code == 202
    task_id = resp.get_json()['task_id']

    task = _aguardar_task(client, task_id)
    assert task.get('status') == 'done', task

    assert len(enviados) == 1
    destino, assunto, corpo, anexos = enviados[0]
    assert destino == 'hfnetto@stefanini.com'
    assert 'Feedback do Toca' in assunto
    assert 'A agenda está lenta ao abrir o mês.' in corpo
    assert len(anexos) == 1
    assert anexos[0]['name'].startswith('app-log-')
    assert anexos[0]['content_type'] == 'text/plain'

    import base64
    conteudo = base64.b64decode(anexos[0]['content_bytes']).decode('utf-8')
    assert 'linha de log 1' in conteudo


def test_feedback_persiste_e_marca_como_enviado(client, monkeypatch, tmp_path):
    monkeypatch.setattr(toca, 'LOG_FILE', tmp_path / 'inexistente.log')
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, body, attachments=None: None)

    resp = client.post('/api/feedback', json={'message': 'Sugestão: modo escuro na agenda.'})
    task = _aguardar_task(client, resp.get_json()['task_id'])
    assert task.get('status') == 'done'

    conn = toca.get_db()
    row = conn.cursor().execute(
        'SELECT message, status, sent_to, sent_at FROM feedback ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    assert row['message'] == 'Sugestão: modo escuro na agenda.'
    assert row['status'] == 'sent'
    assert row['sent_to'] == 'hfnetto@stefanini.com'
    assert row['sent_at']


def test_feedback_sem_outlook_fica_pendente_com_mensagem_acionavel(client, monkeypatch, tmp_path):
    monkeypatch.setattr(toca, 'LOG_FILE', tmp_path / 'inexistente.log')

    def _falha(*args, **kwargs):
        raise toca.OutlookSyncError('Sem token válido do Graph')

    monkeypatch.setattr(toca, '_outlook_send_mail', _falha)

    resp = client.post('/api/feedback', json={'message': 'Erro ao importar planilha.'})
    task = _aguardar_task(client, resp.get_json()['task_id'])

    assert task.get('status') == 'error'
    assert 'Configurações' in task['error'] and 'Microsoft 365' in task['error']

    conn = toca.get_db()
    row = conn.cursor().execute(
        'SELECT status, error FROM feedback ORDER BY id DESC LIMIT 1').fetchone()
    conn.close()
    assert row['status'] == 'pending' or row['status'] == 'error'
    assert row['error']


def test_graph_redirect_uri_funciona_fora_de_request(client):
    """O envio roda em thread, sem request. Antes isso estourava
    'Working outside of request context' e derrubava também o briefing matinal."""
    esperado = 'http://localhost:3000/api/outlook/oauth/callback'

    # Um request de verdade persiste o endereço observado...
    with toca.app.test_request_context('/', base_url='http://localhost:3000'):
        assert toca._graph_redirect_uri() == esperado

    # ...e a thread, sem nenhum contexto, recupera das configurações sem estourar.
    import threading
    resultado = {}

    def _na_thread():
        try:
            resultado['uri'] = toca._graph_redirect_uri()
        except Exception as e:  # pragma: no cover - só falha se a regressão voltar
            resultado['erro'] = repr(e)

    t = threading.Thread(target=_na_thread)
    t.start()
    t.join(timeout=5)

    assert 'erro' not in resultado, resultado
    assert resultado['uri'] == esperado


def test_feedback_exige_mensagem(client):
    assert client.post('/api/feedback', json={'message': '   '}).status_code == 400
    assert client.post('/api/feedback', json={}).status_code == 400


def test_feedback_log_respeita_teto_de_bytes(monkeypatch, tmp_path):
    log_file = tmp_path / 'grande.log'
    log_file.write_text('x' * 40 + '\n' * 1, encoding='utf-8')
    # 2 MB de log em linhas curtas
    with open(log_file, 'w', encoding='utf-8') as fh:
        for i in range(60000):
            fh.write(f'{i:06d} ' + 'y' * 40 + '\n')
    monkeypatch.setattr(toca, 'LOG_FILE', log_file)

    texto, total = toca._feedback_log_tail()
    assert total == 60000
    assert len(texto.encode('utf-8')) <= toca.FEEDBACK_LOG_MAX_BYTES + 40
    assert texto.rstrip().endswith('y' * 40)
