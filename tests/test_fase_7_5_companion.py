# -*- coding: utf-8 -*-
"""F7.5: executor local do Toca Companion."""

import hashlib
from pathlib import Path

import pytest

from integrations.companion_client import (
    CompanionApiClient,
    CompanionConfigStore,
    CompanionConfigurationError,
    CompanionIntegrityError,
    CompanionRunner,
    validate_form_url,
    validate_server_url,
)
from integrations.forms_robot import FormsRobotCancelled


class _Response:
    def __init__(self, status=200, body=None, content=b''):
        self.status_code = status
        self._body = body or {}
        self._content = content
        self.closed = False

    def json(self):
        return self._body

    def iter_content(self, chunk_size=65536):
        del chunk_size
        yield self._content

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_server_url_requires_https_except_localhost():
    assert validate_server_url('https://toca.example.com/') == 'https://toca.example.com'
    assert validate_server_url('http://127.0.0.1:3000') == 'http://127.0.0.1:3000'
    with pytest.raises(CompanionConfigurationError):
        validate_server_url('http://toca.example.com')
    with pytest.raises(CompanionConfigurationError):
        validate_server_url('https://user:secret@toca.example.com')


def test_form_url_is_restricted_to_official_microsoft_forms():
    assert validate_form_url(
        'https://forms.office.com/Pages/ResponsePage.aspx?id=abc'
    ).startswith('https://forms.office.com/')
    with pytest.raises(CompanionConfigurationError):
        validate_form_url('https://evil.example/upload')


def test_pairing_uses_contract_field_and_never_auth_header():
    response = _Response(
        status=201,
        body={'device_id': 'abc', 'device_token': 'token'},
    )
    session = _Session(response)
    client = CompanionApiClient(
        'https://toca.example.com',
        app_version='7.5.0',
        session=session,
    )

    paired = client.claim_pairing('abcd-efgh-2345', 'Meu PC')

    assert paired['device_token'] == 'token'
    _, url, options = session.calls[0]
    assert url.endswith('/api/companion/v1/pairings/claim')
    assert options['json']['pairing_code'] == 'ABCD-EFGH-2345'
    assert 'Authorization' not in options['headers']


def test_config_encrypts_device_token_at_rest(tmp_path):
    store = CompanionConfigStore(tmp_path)
    store.save(
        server_url='https://toca.example.com',
        device_id='device_123',
        device_name='Notebook',
        device_token='segredo-super-sensivel',
    )

    raw = store.path.read_text(encoding='utf-8')
    identity = store.load()

    assert 'segredo-super-sensivel' not in raw
    assert identity.device_token == 'segredo-super-sensivel'
    assert identity.server_url == 'https://toca.example.com'


def test_download_checks_origin_size_and_sha256(tmp_path):
    content = b'arquivo juridico'
    response = _Response(content=content)
    session = _Session(response)
    client = CompanionApiClient(
        'https://toca.example.com',
        'device-token',
        session=session,
    )
    metadata = {
        'id': 'file_123',
        'original_name': '..\\contrato.pdf',
        'size_bytes': len(content),
        'sha256': hashlib.sha256(content).hexdigest(),
        'download_url': '/api/companion/v1/tasks/task_1/files/file_123',
    }

    path = client.download_task_file('task_1', 'lease-token', metadata, tmp_path)

    assert path.parent == tmp_path
    assert path.read_bytes() == content
    _, _, options = session.calls[0]
    assert options['headers']['Authorization'] == 'Bearer device-token'
    assert options['headers']['X-Toca-Task-Lease'] == 'lease-token'
    assert response.closed

    metadata['download_url'] = 'https://evil.example/file'
    with pytest.raises(CompanionIntegrityError):
        client.download_task_file('task_1', 'lease-token', metadata, tmp_path)


class _FakeClient:
    def __init__(self, task, file_content=b'contrato'):
        self.task = task
        self.file_content = file_content
        self.updates = []

    def next_task(self):
        task, self.task = self.task, None
        return task

    def update_task(self, task_id, lease_token, **body):
        self.updates.append((task_id, lease_token, body))
        return {'status': body.get('status') or 'running', 'cancel_requested': False}

    def download_task_file(self, task_id, lease_token, metadata, target_dir):
        del task_id, lease_token
        target = Path(target_dir) / metadata['original_name']
        target.write_bytes(self.file_content)
        return target


def _task():
    content = b'contrato'
    return {
        'protocol_version': 1,
        'task_id': 'task_123',
        'lease_token': 'lease-token',
        'payload': {
            'schema_version': 1,
            'task_type': 'chamado_juridico',
            'history_id': 42,
            'form_url': 'https://forms.office.com/example',
            'fields': {
                'conta': 'ACME',
                'endereco': 'Rua 1',
                'minuta_tipo': 'cliente',
                'havera_reajuste': 'nao',
                'houve_reoneracao': 'nao',
                'inclui_novos_servicos': 'nao',
                'e_prorrogacao_vigencia': 'nao',
                'assinatura_plataforma': 'cliente',
                'descricao_pedido': 'Renovação',
            },
            'constraints': {
                'allow_submit': False,
                'requires_user_review': True,
            },
        },
        'files': [{
            'id': 'file_1',
            'field_key': 'contrato_anterior',
            'original_name': 'contrato.pdf',
            'size_bytes': len(content),
            'sha256': hashlib.sha256(content).hexdigest(),
            'download_url': '/private/file_1',
        }],
    }


def test_runner_downloads_executes_awaits_user_and_cleans_temp(tmp_path):
    client = _FakeClient(_task())
    observed = {}

    def robot(form_url, fields, on_progress, should_cancel):
        observed['url'] = form_url
        file_field = next(field for field in fields if field['key'] == 'contrato_anterior')
        observed['file'] = Path(file_field['file_paths'][0])
        assert observed['file'].exists()
        assert not should_cancel()
        on_progress(50, 'Preenchendo')
        on_progress(88, 'Aguardando revisão humana')
        return {
            'submitted': True,
            'filled': ['Conta'],
            'unmatched': [],
            'errors': [],
            'positional': [],
            'questions_found': 22,
        }

    runner = CompanionRunner(
        client,
        robot=robot,
        temp_root=tmp_path,
        heartbeat_seconds=60,
    )

    assert runner.run_once() is True
    statuses = [body.get('status') for _, _, body in client.updates if body.get('status')]
    assert statuses == ['running', 'awaiting_user', 'succeeded']
    succeeded = client.updates[-1][2]
    assert succeeded['result']['submitted'] is False
    assert succeeded['result']['human_submission_detected'] is True
    assert succeeded['result']['history_id'] == 42
    assert not observed['file'].exists()
    assert list(tmp_path.iterdir()) == []


def test_runner_honors_cancel_requested_during_human_review(tmp_path):
    client = _FakeClient(_task())

    def update_with_cancel(task_id, lease_token, **body):
        client.updates.append((task_id, lease_token, body))
        return {
            'status': body.get('status') or 'running',
            'cancel_requested': body.get('status') == 'awaiting_user',
        }

    client.update_task = update_with_cancel

    def robot(form_url, fields, on_progress, should_cancel):
        del form_url, fields
        on_progress(88, 'Aguardando revisão humana')
        assert should_cancel()
        raise FormsRobotCancelled('cancelado')

    runner = CompanionRunner(
        client,
        robot=robot,
        temp_root=tmp_path,
        heartbeat_seconds=60,
    )
    assert runner.run_once() is True

    statuses = [body.get('status') for _, _, body in client.updates if body.get('status')]
    assert statuses == ['running', 'awaiting_user', 'cancelled']
    assert client.updates[-1][2]['error_code'] == 'COMPANION_CANCELLED'


def test_runner_rejects_task_that_allows_auto_submit(tmp_path):
    task = _task()
    task['payload']['constraints']['allow_submit'] = True
    client = _FakeClient(task)
    runner = CompanionRunner(
        client,
        robot=lambda *args, **kwargs: pytest.fail('robô não deveria executar'),
        temp_root=tmp_path,
    )

    assert runner.run_once() is True
    assert client.updates[-1][2]['status'] == 'failed'
    assert client.updates[-1][2]['error_code'] == 'COMPANION_TASK_UNSUPPORTED'


def test_outlook_legacy_endpoint_is_retired_and_stream_ignores_com_mode(
    client,
    monkeypatch,
):
    import app as toca

    retired = client.post('/api/outlook/sync', json={'days': 7})
    assert retired.status_code == 410
    assert retired.get_json()['error_type'] == 'connector_retired'

    monkeypatch.setenv('OUTLOOK_CONNECTOR_MODE', 'com')
    monkeypatch.setattr(
        toca,
        '_outlook_sync_stream_graph',
        lambda: toca.jsonify({'connector': 'graph'}),
    )
    response = client.get('/api/outlook/sync-stream')
    assert response.get_json() == {'connector': 'graph'}


def test_no_selenium_or_com_executor_remains_in_runtime_source():
    root = Path(__file__).resolve().parents[1]
    runtime = '\n'.join([
        (root / 'app.py').read_text(encoding='utf-8'),
        (root / 'routes' / 'outlook.py').read_text(encoding='utf-8'),
        (root / 'requirements.txt').read_text(encoding='utf-8'),
    ]).lower()
    assert 'selenium' not in runtime
    assert '_outlook_fetch_via_powershell' not in runtime
    assert 'new-object -comobject' not in runtime
