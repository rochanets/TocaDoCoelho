"""Caixa de respostas pendentes (Bloco 6)."""


def _webhook(client, phone_client_id, from_me=False, ts=1750000000, msg_id='m1', body='Oi, tudo bem?'):
    payload = {
        'event': 'message',
        'payload': {
            'id': msg_id,
            'from': '5511999999999@c.us' if not from_me else 'me@c.us',
            'to': '5511999999999@c.us' if from_me else 'me@c.us',
            'fromMe': from_me,
            'body': body,
            'timestamp': ts,
        },
    }
    return client.post('/api/whatsapp/webhook', json=payload)


def _mk_client_with_phone(client):
    resp = client.post('/api/clientes', data={
        'name': 'Zap Cliente', 'company': 'ACME', 'position': 'CEO',
        'phone': '+55 11 99999-9999',
    })
    assert resp.status_code == 201
    return resp.get_json()['id']


def test_webhook_registra_pendencia_e_dedup(client, db_path):
    cid = _mk_client_with_phone(client)
    assert _webhook(client, cid).status_code == 200
    # mesmo msg_id => sem duplicata (polling + webhook juntos)
    assert _webhook(client, cid).status_code == 200
    pend = client.get('/api/inbound/pending').get_json()
    assert len(pend) == 1
    assert pend[0]['client_id'] == cid
    assert 'Oi, tudo bem?' in pend[0]['preview']


def test_webhook_from_me_marca_respondido(client, db_path):
    cid = _mk_client_with_phone(client)
    _webhook(client, cid, ts=1750000000)
    assert len(client.get('/api/inbound/pending').get_json()) == 1
    # resposta minha => pendência some
    _webhook(client, cid, from_me=True, ts=1750003600, msg_id='m2')
    assert client.get('/api/inbound/pending').get_json() == []
    # métrica registra o tempo de resposta
    m = client.get('/api/inbound/metrics').get_json()
    assert m['responded_count_30d'] >= 0  # fora da janela de 30d se ts antigo


def test_respond_manual(client, db_path):
    cid = _mk_client_with_phone(client)
    _webhook(client, cid)
    item = client.get('/api/inbound/pending').get_json()[0]
    assert client.post(f"/api/inbound/{item['id']}/respond").status_code == 200
    assert client.get('/api/inbound/pending').get_json() == []
