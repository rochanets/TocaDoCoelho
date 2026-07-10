"""Dedup do sync WhatsApp: content_hash + last_message_ts não podem regredir."""


def _approve_payload(client_id, content_hash='abc123', ts=1700000000):
    return {'items': [{
        'client_id': client_id,
        'summary': 'Resumo da conversa de teste',
        'content_hash': content_hash,
        'phone': '5511999999999',
        'period_days': 7,
        'message_count': 3,
        'last_message_ts': ts,
    }]}


def test_approve_dedup_por_content_hash(client, sample_client_id):
    resp = client.post('/api/whatsapp/approve', json=_approve_payload(sample_client_id))
    assert resp.status_code == 200
    assert resp.get_json()['inserted'] == 1

    # Mesmo hash de conteúdo => não duplica a atividade
    resp = client.post('/api/whatsapp/approve', json=_approve_payload(sample_client_id))
    assert resp.get_json()['inserted'] == 0

    # Hash diferente (conversa nova) => insere
    resp = client.post('/api/whatsapp/approve', json=_approve_payload(sample_client_id, content_hash='outro456'))
    assert resp.get_json()['inserted'] == 1


def test_approve_registra_last_message_ts(client, sample_client_id):
    import app as toca
    client.post('/api/whatsapp/approve', json=_approve_payload(sample_client_id, ts=1712345678))
    conn = toca.get_db()
    row = conn.execute(
        'SELECT MAX(last_message_ts) FROM whatsapp_sync_log WHERE client_id = ?',
        (sample_client_id,)
    ).fetchone()
    conn.close()
    assert row[0] == 1712345678


def test_approve_cria_followup(client, sample_client_id):
    payload = _approve_payload(sample_client_id, content_hash='comfup')
    payload['items'][0]['followup_date'] = '2030-01-15'
    payload['items'][0]['followup_title'] = 'Retornar proposta'
    resp = client.post('/api/whatsapp/approve', json=payload)
    assert resp.get_json()['commitments'] == 1

    import app as toca
    conn = toca.get_db()
    row = conn.execute(
        "SELECT title, due_date, source_type FROM commitments WHERE client_id = ?",
        (sample_client_id,)
    ).fetchone()
    conn.close()
    assert row['title'] == 'Retornar proposta'
    assert row['due_date'] == '2030-01-15'
    assert row['source_type'] == 'whatsapp'
