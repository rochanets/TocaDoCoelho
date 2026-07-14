"""Testes do submódulo AutoToca Reembolsos."""
import json as _json
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


def test_extract_receipt_parseia_resposta_openrouter(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})

    fake_response = MagicMock()
    fake_response.read.return_value = _json.dumps({
        'choices': [{'message': {'content': '{"data": "2026-06-10", "valor": 45.90}'}}]
    }).encode('utf-8')

    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = fake_response
        result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')

    assert result == {'data': '2026-06-10', 'valor_cents': 4590}


def test_extract_receipt_sem_openrouter_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: None)
    result = toca._reembolso_extract_receipt(b'fake-image-bytes', 'image/jpeg')
    assert result == {'data': None, 'valor_cents': None}


def test_extract_receipt_resposta_invalida_retorna_none(monkeypatch):
    monkeypatch.setattr(toca, '_resolve_setting', lambda key, env: 'fake-or-key' if key == 'openrouter_api_key' else None)
    monkeypatch.setattr(toca, '_load_app_settings_map', lambda keys: {})

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
