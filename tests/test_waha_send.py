"""Envio via WAHA (Bloco 8): validação e limite diário."""
from pathlib import Path
import os
import subprocess


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


def test_waha_lite_implementa_endpoint_de_envio():
    """Contrato entre o backend Flask e o mini-servidor distribuído no app."""
    source = (Path(__file__).parents[1] / 'waha-lite' / 'waha-lite.js').read_text(encoding='utf-8')
    assert "app.post('/api/sendText'" in source
    assert 'waClient.sendMessage(chatId, text)' in source


def test_restart_waha_preserva_diretorio_da_sessao(monkeypatch, tmp_path):
    import app as toca

    session_dir = tmp_path / 'sessao-waha'
    captured = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured['args'] = args
            captured['env'] = kwargs['env']

    monkeypatch.setattr(toca, '_waha_last_restart', 0.0)
    monkeypatch.setattr(toca, '_waha_deps_missing', lambda: False)
    monkeypatch.setattr(toca, '_waha_runtime_paths', lambda: ('node.exe', str(tmp_path / 'waha-lite.js')))
    monkeypatch.setattr(
        toca,
        '_waha_settings',
        lambda: ('http://localhost:3001', 'chave-teste', 'sessao-teste'),
    )
    monkeypatch.setattr(toca, '_kill_process_on_port', lambda port: False)
    monkeypatch.setattr(toca.time, 'time', lambda: 1000.0)
    monkeypatch.setattr(toca, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(subprocess, 'Popen', _FakePopen)
    monkeypatch.setenv('WAHA_DATA_DIR', str(session_dir))
    monkeypatch.delenv('WAHA_LOG', raising=False)

    assert toca._restart_waha_lite() is True
    assert captured['env']['WAHA_DATA_DIR'] == str(session_dir)
    assert captured['env']['WAHA_PORT'] == os.environ.get('WAHA_PORT', '3001')
    assert captured['env']['WAHA_API_KEY'] == 'chave-teste'
    assert captured['env']['WAHA_SESSION_NAME'] == 'sessao-teste'
