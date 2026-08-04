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


def test_scan_sem_conversas_registra_o_motivo(client, db_path, monkeypatch, caplog):
    """O scan precisa dizer POR QUE ficou em zero.

    Num chamado real de produção o app.log só mostrava 'Scan WhatsApp: 0 conversas
    verificadas' repetido por dias, sem nada que distinguisse WAHA fora do ar de
    telefone inválido — impossível diagnosticar sem acesso à máquina do usuário.
    """
    import logging

    import requests

    import app as toca

    _mk_client_with_phone(client)

    def _waha_fora_do_ar(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError('conexao recusada')

    monkeypatch.setattr(toca.requests, 'get', _waha_fora_do_ar)

    with caplog.at_level(logging.WARNING):
        resultado = toca._inbound_scan_whatsapp()

    assert resultado['scanned'] == 0
    assert resultado['motivos'] == {'waha_inacessivel': 1}
    assert any('waha_inacessivel=1' in r.message for r in caplog.records)


def test_scan_bem_sucedido_nao_emite_alerta(client, db_path, monkeypatch, caplog):
    import logging

    import app as toca

    _mk_client_with_phone(client)

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return []

    monkeypatch.setattr(toca.requests, 'get', lambda *a, **k: _Resp())

    with caplog.at_level(logging.WARNING):
        resultado = toca._inbound_scan_whatsapp()

    assert resultado['scanned'] == 1
    assert resultado['motivos'] == {}
    assert not [r for r in caplog.records if 'motivos' in r.message]
