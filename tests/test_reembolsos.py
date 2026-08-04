"""Testes do submódulo AutoToca Reembolsos."""
import json as _json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import app as toca

_EXTENSION_DIR = (
    Path(__file__).resolve().parents[1]
    / 'public' / 'autotoca-extension' / 'autotoca-chrome-extension'
)


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
        {'data': None, 'valor_cents': 725},
        {'data': None, 'valor_cents': None},
    ]
    result = toca._reembolso_aggregate_receipts(extracted)
    assert result['valor_total_cents'] == 2225
    assert result['periodo_inicio'] == '2026-06-10'
    assert result['periodo_fim'] == '2026-06-10'
    assert result['quantidade'] == 3  # conta todos os arquivos anexados, válidos ou não


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


def test_parse_receipt_text_ignora_cnpj_e_prioriza_valor_pago():
    result = toca._reembolso_parse_receipt_text(
        'CNPJ: 66,815,560/0034-88\n'
        '03/07/26 14:38\n'
        'AVULSO R$ 47,98\n'
        'DINHEIRO R$ 47,98\n'
    )
    assert result == {'data': '2026-07-03', 'valor_cents': 4798}


def test_aggregate_receipts_caso_dasa_e_planisa():
    result = toca._reembolso_aggregate_receipts([
        {'data': '2026-07-03', 'valor_cents': 4798},
        {'data': '2026-06-25', 'valor_cents': 2500},
    ])
    assert result == {
        'valor_total_cents': 7298,
        'periodo_inicio': '2026-06-25',
        'periodo_fim': '2026-07-03',
        'quantidade': 2,
    }


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
    applied = {row[0] for row in conn.execute('SELECT version FROM schema_version').fetchall()}
    conn.close()
    # Confere que a migração dos reembolsos rodou — sem amarrar o teste ao total
    # de migrações, que cresce a cada mudança de schema.
    assert 14 in applied
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


def test_extract_task_processa_lote_e_agrega(monkeypatch):
    results = {
        'Visita Dasa.jpeg': {'data': '2026-07-03', 'valor_cents': 4798},
        'Evento Planisa.jpeg': {'data': '2026-06-25', 'valor_cents': 2500},
    }
    monkeypatch.setattr(
        toca,
        '_reembolso_extract_receipt',
        lambda file_bytes, mime, filename='': results[filename],
    )
    monkeypatch.setattr(toca, '_reembolso_task_cleanup', lambda task_id: None)
    task_id = 'extract-batch-test'
    toca._reembolso_task_set(task_id, {'status': 'processing', 'progress': 5})

    toca._reembolso_process_extract_async(task_id, [
        {'bytes': b'dasa', 'mime': 'image/jpeg', 'filename': 'Visita Dasa.jpeg'},
        {'bytes': b'planisa', 'mime': 'image/jpeg', 'filename': 'Evento Planisa.jpeg'},
    ])

    task = toca._reembolso_task_get(task_id)
    assert task['status'] == 'done'
    assert task['progress'] == 100
    assert task['result']['valor_total_cents'] == 7298
    assert task['result']['quantidade'] == 2
    assert [item['filename'] for item in task['result']['items']] == [
        'Visita Dasa.jpeg', 'Evento Planisa.jpeg'
    ]


def test_wait_for_login_avisa_e_continua_quando_formulario_aparece(monkeypatch):
    from integrations import reembolso_robot

    page = MagicMock()
    page.is_closed.return_value = False
    page.url = 'https://login.microsoftonline.com/'
    monkeypatch.setattr(reembolso_robot, '_portal_form_ready', MagicMock(side_effect=[False, True]))
    monkeypatch.setattr(reembolso_robot, '_is_login_screen', lambda current_page: True)
    progress = MagicMock()

    with patch('time.sleep'):
        reembolso_robot._wait_for_login(
            page,
            reembolso_robot.DESLOCAMENTOS_URL,
            'CÉLULA CUSTO',
            progress,
        )

    assert any('Login necessário' in call.args[1] for call in progress.call_args_list)
    assert any('Login confirmado' in call.args[1] for call in progress.call_args_list)


def test_robot_normaliza_opcoes_com_zero_a_esquerda_e_acentos():
    from integrations import reembolso_robot

    assert reembolso_robot._option_matches('1 - DBD IGOR - HENRIQUE NETTO', '001')
    assert reembolso_robot._option_matches('STEFANINI - SAO PAULO', 'Stefanini - Sao Paulo')
    assert reembolso_robot._option_matches('PROSPECCAO', 'Prospecção')
    assert reembolso_robot._option_matches('02', '2')
    assert reembolso_robot._option_matches('Gasto com cliente', 'Gasto com cliente')


def test_robot_suporta_select2_legado_do_portal():
    from integrations import reembolso_robot

    assert '.select2-choice' in reembolso_robot._FIELD_ROOT_SELECTOR
    assert '.select2-choice' in reembolso_robot._FIELD_GLOBAL_SELECTOR
    assert reembolso_robot._option_search_text('001') == '1'
    assert reembolso_robot._option_search_text('Stefanini - Sao Paulo') == 'stefanini'


def test_robot_usa_proximidade_quando_bloco_tem_mais_de_um_combo(monkeypatch):
    from integrations import reembolso_robot

    page = MagicMock()
    container = MagicMock()
    controls = MagicMock()
    controls.count.return_value = 2
    first = MagicMock()
    second = MagicMock()
    first.is_visible.return_value = True
    second.is_visible.return_value = True
    controls.nth.side_effect = [first, second]
    container.locator.return_value = controls
    nearest = MagicMock()
    monkeypatch.setattr(reembolso_robot, '_field_container', lambda *_: container)
    monkeypatch.setattr(reembolso_robot, '_nearest_field_control', lambda *_: nearest)

    found = reembolso_robot._select2_control(page, 'CLIENTE')

    assert found is nearest


def test_robot_aguarda_combo_recriado_por_postback(monkeypatch):
    from integrations import reembolso_robot

    page = MagicMock()
    page.is_closed.return_value = False
    control = MagicMock()
    control.count.return_value = 1
    control.is_visible.return_value = True
    control.is_enabled.return_value = True
    monkeypatch.setattr(
        reembolso_robot,
        '_select2_control',
        MagicMock(side_effect=[RuntimeError('nó substituído'), control]),
    )

    found = reembolso_robot._wait_for_select_control(page, 'CLIENTE', timeout_ms=1000)

    assert found is control
    page.wait_for_timeout.assert_called_once_with(250)


def test_robot_aguarda_rede_antes_do_combo_dependente(monkeypatch):
    from integrations import reembolso_robot

    page = MagicMock()
    expected = MagicMock()
    wait_control = MagicMock(return_value=expected)
    monkeypatch.setattr(reembolso_robot, '_wait_for_select_control', wait_control)

    found = reembolso_robot._wait_for_dependent_select(page, 'SERVIÇO', timeout_ms=9000)

    assert found is expected
    page.wait_for_load_state.assert_called_once_with('networkidle', timeout=9000)
    wait_control.assert_called_once_with(page, 'SERVIÇO', timeout_ms=9000)


def test_robot_pode_anexar_aba_em_navegador_existente_via_cdp(monkeypatch):
    from integrations import reembolso_robot

    browser = MagicMock()
    context = MagicMock()
    browser.contexts = [context]
    playwright = MagicMock()
    playwright.chromium.connect_over_cdp.return_value = browser
    monkeypatch.setenv('TOCA_ROBOT_CDP_URL', 'http://127.0.0.1:9222')

    attached = reembolso_robot._launch_context(playwright, headless=False)

    assert attached is context
    playwright.chromium.connect_over_cdp.assert_called_once_with('http://127.0.0.1:9222')
    reembolso_robot._cleanup(playwright, context)
    context.close.assert_not_called()
    playwright.stop.assert_called_once()


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


def test_almoco_extensao_abre_tarefa_sem_iniciar_playwright(client, db_path):
    from io import BytesIO

    resp = client.post('/api/autotoca/reembolsos/almoco/robot', data={
        'browser_mode': 'extension',
        'celula_custo': '001',
        'descricao_despesa': 'Almoço com cliente',
        'quantidade': '1',
        'periodo_inicio': '2026-06-25',
        'periodo_fim': '2026-06-25',
        'valor_total': '89.90',
        'descricao': 'Reunião comercial',
        'comprovantes': (BytesIO(b'jpeg-de-teste'), 'nota.jpg', 'image/jpeg'),
    }, content_type='multipart/form-data')

    assert resp.status_code == 202
    started = resp.get_json()
    assert started['browser_mode'] == 'extension'
    assert started['target_url'].endswith('/Reembolso/OutrasDespesas.aspx')

    payload_resp = client.get(
        f'/api/autotoca/reembolsos/extension/tasks/{started["task_id"]}'
    )
    assert payload_resp.status_code == 200
    payload = payload_resp.get_json()
    assert payload['flow'] == 'almoco'
    assert payload['payload']['celula_custo'] == '001'
    assert payload['files']['comprovantes'][0]['name'].startswith('nota')
    assert payload['files']['comprovantes'][0]['name'].endswith('.jpg')
    assert payload['files']['comprovantes'][0]['base64']

    done_resp = client.post(
        f'/api/autotoca/reembolsos/extension/tasks/{started["task_id"]}',
        json={'status': 'done', 'progress': 100, 'step': 'Concluído'},
    )
    assert done_resp.status_code == 200


def test_extensao_reembolso_retoma_fluxo_apos_postback():
    extension_dir = (
        Path(__file__).resolve().parents[1]
        / 'public' / 'autotoca-extension' / 'autotoca-chrome-extension'
    )
    robot_source = (extension_dir / 'reembolso.js').read_text(encoding='utf-8')
    background_source = (extension_dir / 'background.js').read_text(encoding='utf-8')
    manifest = _json.loads((extension_dir / 'manifest.json').read_text(encoding='utf-8'))
    core_source = (Path(__file__).parents[1] / 'public' / 'js' / 'core.js').read_text(encoding='utf-8')

    # Versão mínima aceita pelo gate do core.js — sem fixar o número exato, que
    # muda a cada correção da extensão e deixava este teste vermelho sem motivo.
    version = tuple(int(part) for part in manifest['version'].split('.'))
    assert version >= (0, 9, 6), manifest['version']
    assert 'https://ereembolso.stefanini.com.br/*' in manifest['host_permissions']
    assert "setCheckpoint(task, 'deslocamento-added')" in robot_source
    assert robot_source.count("setCheckpoint(task, 'final-added')") >= 3
    assert "task.checkpoint === 'final-added'" in robot_source
    assert "'outros-files-attached-v093'" in robot_source
    assert "file: 'fuOutrosFile', attach: 'lkAnexarOutrosFile'" in robot_source
    assert "await fillOtherTravelFields(payload, null, 'Estacionamento')" in robot_source
    assert "message.type === 'set_reembolso_checkpoint'" in background_source
    assert "message.type === 'click_reembolso_control'" in background_source
    assert "world: 'MAIN'" in background_source
    assert "window.__doPostBack(postback[1], postback[2])" in background_source
    assert "ids ? clickByIdInPage(ids.attach)" in robot_source
    assert "attachmentsConfirmed(files, ids)" in robot_source
    assert "tableSignature('gvOutrosDeslocamentos')" in robot_source
    assert "await completeTask(task)" in robot_source
    assert "(versionParts[2] || 0) >= 6" in core_source


def test_extensao_reembolso_usa_eventos_que_os_widgets_escutam():
    """Chosen (OutrasDespesas.aspx) e Select2 (Deslocamentos.aspx) abrem e
    selecionam em mousedown/mouseup e ignoram `click`. Verificado ao vivo no
    portal: `.chosen-single`.click() não abre nada e o robô ficava preso no
    primeiro combo (CÉLULA CUSTO) até estourar o timeout."""
    robot_source = _EXTENSION_DIR.joinpath('reembolso.js').read_text(encoding='utf-8')

    assert 'function pressPointer(el)' in robot_source
    for event in ('mouseover', 'mousedown', 'mouseup', 'click'):
        assert f"new MouseEvent('{event}', init)" in robot_source

    # Nenhum combo/opção pode voltar a ser acionado só por .click().
    assert 'control.click();' not in robot_source
    assert 'match.click();' not in robot_source
    assert 'pressPointer(control);' in robot_source
    assert 'pressPointer(match);' in robot_source


def test_extensao_reembolso_mira_campos_por_id_do_portal():
    """As duas descrições convivem na mesma página. Buscar por rótulo fazia
    "DESCRIÇÃO" casar com "Descrição da despesa" (que vem antes no DOM), então a
    descrição do reembolso ia para o campo errado — o sintoma "preenche tudo
    menos a descrição". Cada campo agora é endereçado pelo ID do ASP.NET."""
    robot_source = _EXTENSION_DIR.joinpath('reembolso.js').read_text(encoding='utf-8')

    # Rótulo exato tem precedência sobre o que apenas começa com o termo.
    assert 'candidates.find(el => normalize(el.textContent) === wanted) ||' in robot_source

    # Campos confirmados por inspeção ao vivo do portal logado.
    for control_id in (
        'ddlCelulaCusto', 'ddlCliente', 'ddlServico', 'txtDescricaoAtividade',
        'ddlDespesaTipo', 'ddlDespesaQuantidade', 'txtDespesaPeriodoDe',
        'txtDespesaPeriodoA', 'txtDespesaValor', 'txtDespesaDescricao',
        'fuDespesaFile', 'lkAnexarArquivos', 'btnInserirDeslocamentos',
        'txtCombustivelOrigem', 'txtCombustivelDestino', 'txtCombustivelData',
        'ddlCombustivelKmUnidade', 'ccbIdaVolta', 'txtCombustivelDescricao',
        'btnInserirDeslocamentoCombustivel',
    ):
        assert f"'{control_id}'" in robot_source, control_id

    # As duas descrições vão para controles DIFERENTES.
    assert "fillTextById('txtDescricaoAtividade', payload.descricao_despesa)" in robot_source
    assert "fillTextById('txtDespesaDescricao', payload.descricao)" in robot_source

    # Nenhum campo do fluxo pode voltar a ser localizado por rótulo.
    for banned in (
        "fillText('DESCRIÇÃO'", "fillText('DESCRIÇÃO DA DESPESA'",
        "chooseOption('CÉLULA CUSTO'", "chooseOption('CLIENTE'",
        "chooseOption('SERVIÇO'", "chooseNative('TIPO DE DESPESA'",
        "chooseNative('QUANTIDADE'", 'fillPeriod(payload',
    ):
        assert banned not in robot_source, banned
