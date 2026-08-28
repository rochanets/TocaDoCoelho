"""Despacho de e-mail da Mala Direta pela conta conectada (OAuth/Graph)."""
import time


def _espera_task(client, task_id, timeout=15):
    limite = time.time() + timeout
    while time.time() < limite:
        payload = client.get(f'/api/outlook/send-tasks/{task_id}').get_json()
        if payload.get('status') in ('done', 'error'):
            return payload
        time.sleep(0.1)
    raise AssertionError(f'task {task_id} não concluiu em {timeout}s')


def _sem_intervalo(db_path):
    import app as toca
    conn = toca.get_db()
    for key in ('outlook_send_interval_min', 'outlook_send_interval_max'):
        conn.execute('INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)', (key, '0'))
    conn.commit()
    conn.close()


def test_send_valida_campos(client, db_path):
    resp = client.post('/api/outlook/send', json={'to': '', 'message': ''})
    assert resp.status_code == 400


def test_send_envia_e_registra_atividade(client, sample_client_id, db_path, monkeypatch):
    import app as toca

    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, body, attachments=None: enviados.append((to, subject, body)))

    resp = client.post('/api/outlook/send', json={
        'client_id': sample_client_id,
        'to': 'contato@empresa.com',
        'subject': 'Handshake',
        'message': 'Olá Fulano!\nTudo bem?',
    })
    assert resp.status_code == 200, resp.get_json()
    payload = resp.get_json()
    assert payload['ok'] and payload['activity_id']

    to, subject, body = enviados[0]
    assert to == 'contato@empresa.com'
    assert subject == 'Handshake'
    # quebras de linha viram <br> e o conteúdo é escapado
    assert '<br>' in body

    atividades = client.get(f'/api/atividades?client_id={sample_client_id}').get_json()
    assert any(a['contact_type'] == 'Email' and 'Handshake' in a['information'] for a in atividades)


def test_send_escapa_html_do_corpo(client, sample_client_id, db_path, monkeypatch):
    """O corpo é texto puro digitado pelo usuário: '<b>' vai como texto, não markup."""
    import app as toca

    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, body, attachments=None: enviados.append(body))
    resp = client.post('/api/outlook/send', json={
        'client_id': sample_client_id, 'to': 'x@y.com', 'subject': 'S',
        'message': 'preço <b>alto</b> & cia',
    })
    assert resp.status_code == 200
    assert '&lt;b&gt;' in enviados[0] and '<b>' not in enviados[0]


def test_send_sem_conta_conectada_retorna_401(client, sample_client_id, db_path, monkeypatch):
    import app as toca

    def _sem_token(*a, **kw):
        raise toca.OutlookReauthRequiredError('Reconecte a conta Microsoft.')

    monkeypatch.setattr(toca, '_outlook_send_mail', _sem_token)
    resp = client.post('/api/outlook/send', json={
        'client_id': sample_client_id, 'to': 'x@y.com', 'subject': 'S', 'message': 'Oi',
    })
    assert resp.status_code == 401
    assert resp.get_json()['needs_auth'] is True


def test_send_batch_recusa_sem_conta_conectada(client, db_path, monkeypatch):
    import app as toca

    monkeypatch.setattr(toca, 'outlook_graph_get_integration_state',
                        lambda conn, user_id: {'connected': False, 'reason': 'Não autenticado'})
    resp = client.post('/api/outlook/send-batch', json={
        'items': [{'client_id': 1, 'to': 'x@y.com', 'subject': 'S', 'message': 'Oi'}]
    })
    assert resp.status_code == 401
    assert resp.get_json()['needs_auth'] is True


def test_send_batch_envia_fila_inteira(client, sample_client_id, db_path, monkeypatch):
    import app as toca

    _sem_intervalo(db_path)
    monkeypatch.setattr(toca, 'outlook_graph_get_integration_state',
                        lambda conn, user_id: {'connected': True})
    enviados = []
    monkeypatch.setattr(toca, '_outlook_send_mail',
                        lambda to, subject, body, attachments=None: enviados.append(to))

    itens = [
        {'client_id': sample_client_id, 'to': 'a@x.com', 'subject': 'S1', 'message': 'Oi A', 'name': 'A'},
        {'client_id': sample_client_id, 'to': 'b@x.com', 'subject': 'S2', 'message': 'Oi B', 'name': 'B'},
    ]
    resp = client.post('/api/outlook/send-batch', json={'items': itens})
    assert resp.status_code == 202
    result = _espera_task(client, resp.get_json()['task_id'])['result']
    assert result['sent'] == 2 and result['failed'] == 0 and result['blocked'] == 0
    assert enviados == ['a@x.com', 'b@x.com']
    assert all(d['status'] == 'sent' for d in result['details'])


def test_send_batch_falha_de_um_contato_nao_para_a_fila(client, sample_client_id, db_path, monkeypatch):
    import app as toca

    _sem_intervalo(db_path)
    monkeypatch.setattr(toca, 'outlook_graph_get_integration_state',
                        lambda conn, user_id: {'connected': True})

    def _envia(to, subject, body, attachments=None):
        if to == 'b@x.com':
            raise toca.OutlookSyncError('Caixa do destinatário rejeitou a mensagem.')

    monkeypatch.setattr(toca, '_outlook_send_mail', _envia)

    itens = [{'client_id': sample_client_id, 'to': f'{n}@x.com', 'subject': 'S', 'message': 'Oi', 'name': n}
             for n in ('a', 'b', 'c')]
    resp = client.post('/api/outlook/send-batch', json={'items': itens})
    result = _espera_task(client, resp.get_json()['task_id'])['result']
    assert result['sent'] == 2 and result['failed'] == 1 and result['blocked'] == 0
    assert [d['status'] for d in result['details']] == ['sent', 'error', 'sent']


def test_send_batch_token_caido_bloqueia_o_restante(client, sample_client_id, db_path, monkeypatch):
    """Se a autorização cai no meio da fila, o resto vira 'blocked' — não 'error'
    contato a contato: nenhum deles chegou a ser tentado de verdade."""
    import app as toca

    _sem_intervalo(db_path)
    monkeypatch.setattr(toca, 'outlook_graph_get_integration_state',
                        lambda conn, user_id: {'connected': True})

    def _envia(to, subject, body, attachments=None):
        if to != 'a@x.com':
            raise toca.OutlookReauthRequiredError('Grant revogado.')

    monkeypatch.setattr(toca, '_outlook_send_mail', _envia)

    itens = [{'client_id': sample_client_id, 'to': f'{n}@x.com', 'subject': 'S', 'message': 'Oi', 'name': n}
             for n in ('a', 'b', 'c')]
    resp = client.post('/api/outlook/send-batch', json={'items': itens})
    result = _espera_task(client, resp.get_json()['task_id'])['result']
    assert result['sent'] == 1 and result['blocked'] == 2
    assert [d['status'] for d in result['details']] == ['sent', 'blocked', 'blocked']
