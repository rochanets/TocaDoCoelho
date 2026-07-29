"""Envio agendado, primeiro acesso e aviso de extensão (ajustes pós-roadmap)."""
from datetime import datetime, timedelta


def _schedule(client, cid, minutes_from_now=60, channel='whatsapp'):
    when = (datetime.now() + timedelta(minutes=minutes_from_now)).strftime('%Y-%m-%d %H:%M')
    item = {'channel': channel, 'client_id': cid, 'message': 'Mensagem agendada de teste'}
    if channel == 'whatsapp':
        item['phone'] = '+55 11 99999-9999'
    else:
        item['email_to'] = 'cliente@teste.com'
        item['subject'] = 'Assunto teste'
    resp = client.post('/api/scheduled-sends', json={'scheduled_for': when, 'items': [item]})
    return resp


def test_agendar_validacoes(client, sample_client_id, db_path):
    # passado => recusa
    past = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    resp = client.post('/api/scheduled-sends', json={
        'scheduled_for': past,
        'items': [{'channel': 'whatsapp', 'phone': '11999999999', 'message': 'x'}],
    })
    assert resp.status_code == 400
    # formato inválido => recusa
    resp = client.post('/api/scheduled-sends', json={
        'scheduled_for': 'amanhã', 'items': [{'channel': 'whatsapp', 'phone': '1', 'message': 'x'}],
    })
    assert resp.status_code == 400
    # válido => cria e aparece na lista de pendentes
    resp = _schedule(client, sample_client_id)
    assert resp.status_code == 201
    pend = client.get('/api/scheduled-sends').get_json()
    assert len(pend) == 1 and pend[0]['status'] == 'pending'


def test_worker_envia_no_horario_e_missed_pergunta(client, sample_client_id, db_path, monkeypatch):
    import app as toca
    monkeypatch.setattr(
        toca, '_waha_send_text',
        lambda chat_id, text, owner_id=None: (True, None),
    )

    sid = _schedule(client, sample_client_id).get_json()['ids'][0]
    conn = toca.get_db()
    # vencido há 1 minuto (dentro da janela de graça) => worker envia sozinho
    due = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
    conn.execute('UPDATE scheduled_sends SET scheduled_for = ? WHERE id = ?', (due, sid))
    conn.commit()
    conn.close()
    assert toca._scheduled_sends_worker_tick() == 1
    conn = toca.get_db()
    row = conn.execute('SELECT status FROM scheduled_sends WHERE id = ?', (sid,)).fetchone()
    assert row[0] == 'sent'
    # atividade registrada automaticamente
    n = conn.execute('SELECT COUNT(*) FROM activities WHERE client_id = ?', (sample_client_id,)).fetchone()[0]
    assert n >= 1
    conn.close()

    # vencido há muito tempo (sistema estava desligado) => NÃO envia sozinho, vira 'missed'
    sid2 = _schedule(client, sample_client_id).get_json()['ids'][0]
    conn = toca.get_db()
    old = (datetime.now() - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M')
    conn.execute('UPDATE scheduled_sends SET scheduled_for = ? WHERE id = ?', (old, sid2))
    conn.commit()
    conn.close()
    assert toca._scheduled_sends_worker_tick() == 0
    missed = client.get('/api/scheduled-sends/missed').get_json()
    assert [m['id'] for m in missed] == [sid2]
    # usuário decide enviar agora
    assert client.post(f'/api/scheduled-sends/{sid2}/send-now').status_code == 200
    assert client.get('/api/scheduled-sends/missed').get_json() == []


def test_cancelar_agendamento(client, sample_client_id, db_path):
    sid = _schedule(client, sample_client_id).get_json()['ids'][0]
    assert client.post(f'/api/scheduled-sends/{sid}/cancel').status_code == 200
    assert client.get('/api/scheduled-sends').get_json() == []
    # cancelar de novo => 404
    assert client.post(f'/api/scheduled-sends/{sid}/cancel').status_code == 404


def test_first_run_e_extensao(client, db_path):
    # banco novo sem cadastro => primeiro acesso
    assert client.get('/api/config/first-run').get_json()['first_run'] is True
    # durante o primeiro acesso não avisa update de extensão
    ext = client.get('/api/extension/update-status').get_json()
    assert ext['update_available'] is False
    assert ext['current']  # versão do manifest empacotado

    # marca como visto => nunca mais redireciona e extensão fica marcada como atual
    assert client.post('/api/config/first-run/seen').status_code == 200
    assert client.get('/api/config/first-run').get_json()['first_run'] is False
    assert client.get('/api/extension/update-status').get_json()['update_available'] is False

    # simula update do app com extensão mais nova que a vista pelo usuário
    import app as toca
    toca._save_app_setting('extension_version_seen', '0.7.0')
    ext = client.get('/api/extension/update-status').get_json()
    assert ext['update_available'] is True and ext['seen'] == '0.7.0'
    # usuário instala e confirma
    assert client.post('/api/extension/update-status/seen').status_code == 200
    assert client.get('/api/extension/update-status').get_json()['update_available'] is False


def test_agendamento_cria_atividade_provisoria_e_promove(client, sample_client_id, db_path, monkeypatch):
    import app as toca
    monkeypatch.setattr(
        toca, '_waha_send_text',
        lambda chat_id, text, owner_id=None: (True, None),
    )

    sid = _schedule(client, sample_client_id).get_json()['ids'][0]
    conn = toca.get_db()
    # atividade provisória criada com relógio, SEM atualizar o status do contato
    act = conn.execute('SELECT id, information FROM activities WHERE client_id = ?', (sample_client_id,)).fetchone()
    assert act and act[1].startswith('⏰ [AGENDADO')
    last = conn.execute('SELECT last_activity_date FROM clients WHERE id = ?', (sample_client_id,)).fetchone()[0]
    assert last is None

    # enviar agora => atividade promovida (sem relógio) e status atualizado
    assert client.post(f'/api/scheduled-sends/{sid}/send-now').status_code == 200
    info = conn.execute('SELECT information FROM activities WHERE id = ?', (act[0],)).fetchone()[0]
    assert not info.startswith('⏰') and 'agendada' in info
    last = conn.execute('SELECT last_activity_date FROM clients WHERE id = ?', (sample_client_id,)).fetchone()[0]
    assert last is not None
    # não duplicou atividade
    n = conn.execute('SELECT COUNT(*) FROM activities WHERE client_id = ?', (sample_client_id,)).fetchone()[0]
    assert n == 1
    conn.close()


def test_cancelamento_remove_atividade_provisoria(client, sample_client_id, db_path):
    import app as toca
    sid = _schedule(client, sample_client_id).get_json()['ids'][0]
    conn = toca.get_db()
    assert conn.execute('SELECT COUNT(*) FROM activities WHERE client_id = ?', (sample_client_id,)).fetchone()[0] == 1
    conn.close()
    assert client.post(f'/api/scheduled-sends/{sid}/cancel').status_code == 200
    conn = toca.get_db()
    assert conn.execute('SELECT COUNT(*) FROM activities WHERE client_id = ?', (sample_client_id,)).fetchone()[0] == 0
    conn.close()
