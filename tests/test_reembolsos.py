"""Testes do submódulo AutoToca Reembolsos."""
import json as _json
import sqlite3
from unittest.mock import patch, MagicMock

import app as toca


def test_schema_reembolsos_tabelas_existem(db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row['name'] for row in c.fetchall()}
    conn.close()
    assert 'reembolso_origem_historico' in tables
    assert 'account_reembolso_enderecos' in tables
    assert 'reembolsos_history' in tables


def test_account_reembolso_enderecos_um_por_conta(db_path, sample_client_id):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Teste')")
    account_id = c.lastrowid
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?)",
        (account_id, 'Rua A, 100, São Paulo, SP')
    )
    conn.commit()
    # UNIQUE(account_id) — um segundo INSERT com ON CONFLICT deve substituir, não duplicar
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?) "
        "ON CONFLICT(account_id) DO UPDATE SET endereco = excluded.endereco",
        (account_id, 'Rua B, 200, São Paulo, SP')
    )
    conn.commit()
    c.execute("SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?", (account_id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]['endereco'] == 'Rua B, 200, São Paulo, SP'


def test_aggregate_receipts_soma_e_periodo():
    extracted = [
        {'data': '2026-06-10', 'valor_cents': 1500},
        {'data': '2026-06-08', 'valor_cents': 2000},
        {'data': '2026-06-12', 'valor_cents': 999},
    ]
    result = toca._reembolso_aggregate_receipts(extracted)
    assert result['valor_total_cents'] == 4499
    assert result['periodo_inicio'] == '2026-06-08'
    assert result['periodo_fim'] == '2026-06-12'
    assert result['quantidade'] == 3


def test_aggregate_receipts_ignora_entradas_invalidas():
    extracted = [
        {'data': '2026-06-10', 'valor_cents': 1500},
        {'data': None, 'valor_cents': None},
    ]
    result = toca._reembolso_aggregate_receipts(extracted)
    assert result['valor_total_cents'] == 1500
    assert result['periodo_inicio'] == '2026-06-10'
    assert result['periodo_fim'] == '2026-06-10'
    assert result['quantidade'] == 2  # conta todos os arquivos anexados, válidos ou não


def test_aggregate_receipts_lista_vazia():
    result = toca._reembolso_aggregate_receipts([])
    assert result == {'valor_total_cents': 0, 'periodo_inicio': None, 'periodo_fim': None, 'quantidade': 0}


def test_parse_receipt_text_estacionamento_com_ocr_ruidoso():
    result = toca._reembolso_parse_receipt_text(
        'Entrada: 25/06/26 09:28:38\n'
        'SUBTOTAL R$ 56,98\n'
        'VALOR: R$ 56,98\n'
    )
    assert result == {'data': '2026-06-25', 'valor_cents': 5698}


def test_migracao_reembolsos_para_banco_existente(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)')
    conn.execute('CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)')
    conn.executemany(
        'INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)',
        [(version, f'migration_{version}', '') for version in range(1, 14)]
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(toca, 'DB_PATH', path)
    toca._run_schema_migrations()

    conn = sqlite3.connect(path)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    version = conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0]
    conn.close()
    assert version == 14
    assert {'reembolso_origem_historico', 'account_reembolso_enderecos', 'reembolsos_history'} <= tables


def test_extract_receipt_parseia_resposta_openrouter(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})
    monkeypatch.setattr(toca, '_reembolso_extract_text_from_bytes', lambda b, m, f='': '')

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': '{"data": "2026-06-10", "valor": 45.90}'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': '2026-06-10', 'valor_cents': 4590}


def test_extract_receipt_usa_ocr_local_sem_openrouter(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: None)
    monkeypatch.setattr(
        toca,
        '_reembolso_extract_text_from_bytes',
        lambda b, m, f='': 'DATA DA EMISSAO 10/06/2026\nVALOR TOTAL R$ 45,90'
    )

    result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': '2026-06-10', 'valor_cents': 4590}


def test_extract_receipt_parseia_valor_string_openrouter(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})
    monkeypatch.setattr(toca, '_reembolso_extract_text_from_bytes', lambda b, m, f='': '')

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': '{"data": "10/06/2026", "valor": "R$ 45,90"}'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': '2026-06-10', 'valor_cents': 4590}


def test_extract_receipt_sem_openrouter_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: None)
    monkeypatch.setattr(toca, '_reembolso_extract_text_from_bytes', lambda b, m, f='': '')
    result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')
    assert result == {'data': None, 'valor_cents': None}


def test_extract_receipt_resposta_invalida_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})
    monkeypatch.setattr(toca, '_reembolso_extract_text_from_bytes', lambda b, m, f='': '')

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': 'não é json'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': None, 'valor_cents': None}


def test_gerar_arquivo_corrompido(tmp_path):
    from integrations.reembolso_robot import gerar_comprovante_corrompido
    target_dir = tmp_path / 'pedagio'
    target_dir.mkdir()
    path = gerar_comprovante_corrompido(target_dir)
    assert path.exists()
    assert path.suffix == '.jpg'
    content = path.read_bytes()
    assert len(content) > 0
    # Não é um JPEG válido: não começa com a assinatura JPEG (FF D8 FF)
    assert content[:3] != b'\xff\xd8\xff'


def test_origem_historico_vazio_por_padrao(client):
    resp = client.get('/api/autotoca/reembolsos/origem-historico')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_origem_historico_lista_mais_recentes_primeiro(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reembolso_origem_historico (texto) VALUES ('Rua A, 1, São Paulo, SP')")
    c.execute("INSERT INTO reembolso_origem_historico (texto) VALUES ('Rua B, 2, São Paulo, SP')")
    conn.commit()
    conn.close()
    resp = client.get('/api/autotoca/reembolsos/origem-historico')
    assert resp.status_code == 200
    textos = [r['texto'] for r in resp.get_json()]
    assert textos == ['Rua B, 2, São Paulo, SP', 'Rua A, 1, São Paulo, SP']


def test_conta_endereco_nao_encontrado_retorna_null(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Sem Endereco')")
    account_id = c.lastrowid
    conn.commit()
    conn.close()
    resp = client.get(f'/api/autotoca/reembolsos/conta-endereco/{account_id}')
    assert resp.status_code == 200
    assert resp.get_json() == {'endereco': None}


def test_conta_endereco_encontrado(client, db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Com Endereco')")
    account_id = c.lastrowid
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?)",
        (account_id, 'Av. Paulista, 1000, São Paulo, SP')
    )
    conn.commit()
    conn.close()
    resp = client.get(f'/api/autotoca/reembolsos/conta-endereco/{account_id}')
    assert resp.status_code == 200
    assert resp.get_json() == {'endereco': 'Av. Paulista, 1000, São Paulo, SP'}


def test_extract_endpoint_sem_arquivo(client):
    resp = client.post('/api/autotoca/reembolsos/extract')
    assert resp.status_code == 400


def test_extract_endpoint_com_arquivo(client, monkeypatch):
    monkeypatch.setattr(toca, '_reembolso_extract_receipt', lambda b, m, f='': {'data': '2026-06-10', 'valor_cents': 4590})
    from io import BytesIO
    resp = client.post(
        '/api/autotoca/reembolsos/extract',
        data={'file': (BytesIO(b'fake-bytes'), 'nota.jpg', 'image/jpeg')},
        content_type='multipart/form-data'
    )
    assert resp.status_code == 200
    assert resp.get_json() == {'data': '2026-06-10', 'valor_cents': 4590}


def _sync_thread(monkeypatch):
    """Substitui threading.Thread por execução síncrona no teste, para não
    depender de timing (o robô real é mockado por essas rotas nos testes)."""
    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(toca.threading, 'Thread', _SyncThread)


def test_deslocamento_robot_sem_celula_custo_400(client):
    resp = client.post('/api/autotoca/reembolsos/deslocamento/robot', data={'sub_fluxo': 'deslocamento'})
    assert resp.status_code == 400


def test_deslocamento_robot_dispara_task(client, monkeypatch, db_path):
    monkeypatch.setattr(
        toca, '_reembolso_process_deslocamento_async',
        lambda task_id, history_id, payload, file_paths: toca._reembolso_task_set(task_id, {'status': 'done', 'progress': 100})
    )
    _sync_thread(monkeypatch)

    resp = client.post('/api/autotoca/reembolsos/deslocamento/robot', data={
        'celula_custo': '19 - DBD PEDROSO',
        'descricao_despesa': 'Visita comercial',
        'sub_fluxo': 'estacionamento',
        'conta': 'Conta Teste',
        'quantidade': '2',
        'periodo_inicio': '2026-06-01',
        'periodo_fim': '2026-06-05',
        'valor_total': '45.90',
        'descricao_estacionamento': 'Estacionamento na visita',
    })
    assert resp.status_code == 202
    assert 'task_id' in resp.get_json()


def test_almoco_robot_sem_celula_custo_400(client):
    resp = client.post('/api/autotoca/reembolsos/almoco/robot', data={})
    assert resp.status_code == 400


def test_almoco_robot_dispara_task(client, monkeypatch, db_path):
    monkeypatch.setattr(
        toca, '_reembolso_process_almoco_async',
        lambda task_id, history_id, payload, comprovantes: toca._reembolso_task_set(task_id, {'status': 'done', 'progress': 100})
    )
    _sync_thread(monkeypatch)
    from io import BytesIO
    resp = client.post('/api/autotoca/reembolsos/almoco/robot', data={
        'celula_custo': '19 - DBD PEDROSO',
        'descricao_despesa': 'Almoço com cliente X',
        'quantidade': '1',
        'periodo_inicio': '2026-06-01',
        'periodo_fim': '2026-06-01',
        'valor_total': '89.90',
        'descricao': 'Almoço de negociação',
        'comprovantes': (BytesIO(b'fake-bytes'), 'nota.jpg', 'image/jpeg'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 202
    assert 'task_id' in resp.get_json()
