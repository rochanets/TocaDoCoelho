"""Envio via WAHA (Bloco 8): validação e limite diário."""


def test_send_valida_campos(client, db_path):
    resp = client.post('/api/whatsapp/send', json={'message': ''})
    assert resp.status_code == 400


def test_send_quota_e_limite(client, sample_client_id, db_path, monkeypatch):
    import app as toca

    q = client.get('/api/whatsapp/send-quota').get_json()
    assert q['limit'] == 45 and q['used_today'] == 0

    # simula envio bem-sucedido sem WAHA real
    monkeypatch.setattr(toca, '_waha_send_text', lambda chat_id, text: (True, None))

    resp = client.post('/api/whatsapp/send', json={
        'client_id': sample_client_id, 'phone': '+55 11 99999-9999', 'message': 'Olá!'
    })
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] and payload['activity_id']

    q = client.get('/api/whatsapp/send-quota').get_json()
    assert q['used_today'] == 1

    # limite diário: zera a cota e o backend recusa com 429
    conn = toca.get_db()
    conn.execute("INSERT INTO app_settings (key, value) VALUES ('waha_daily_send_limit', '1') "
                 "ON CONFLICT(key) DO UPDATE SET value = '1'")
    conn.commit()
    conn.close()
    resp = client.post('/api/whatsapp/send', json={
        'client_id': sample_client_id, 'phone': '+55 11 99999-9999', 'message': 'Segunda msg'
    })
    assert resp.status_code == 429
    assert 'Limite diário' in resp.get_json()['error']
