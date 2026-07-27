# -*- coding: utf-8 -*-
"""Cliente e executor local do contrato Toca Companion v1."""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from integrations.chamado_juridico import build_chamado_juridico_fields


PROTOCOL_VERSION = 1
TASK_TYPE_CHAMADO_JURIDICO = 'chamado_juridico'
DEFAULT_HEARTBEAT_SECONDS = 25
DEFAULT_REQUEST_TIMEOUT = (10, 45)
MAX_ERROR_TEXT = 1000
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


class CompanionError(Exception):
    code = 'COMPANION_ERROR'


class CompanionConfigurationError(CompanionError):
    code = 'COMPANION_CONFIGURATION_INVALID'


class CompanionAuthenticationError(CompanionError):
    code = 'COMPANION_AUTHENTICATION_FAILED'


class CompanionUpdateRequired(CompanionError):
    code = 'COMPANION_UPDATE_REQUIRED'


class CompanionIntegrityError(CompanionError):
    code = 'COMPANION_FILE_INTEGRITY_MISMATCH'


class CompanionCancelled(CompanionError):
    code = 'COMPANION_CANCELLED'


def companion_data_dir() -> Path:
    configured = (os.environ.get('TOCA_COMPANION_DATA_DIR') or '').strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = (
        Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
        if sys.platform == 'win32'
        else Path.home() / '.toca-do-coelho'
    )
    return base / 'companion'


def validate_server_url(value: str) -> str:
    raw = str(value or '').strip().rstrip('/')
    parsed = urlparse(raw)
    if not parsed.hostname or parsed.username or parsed.password:
        raise CompanionConfigurationError('Endereço do Toca web inválido.')
    is_local = parsed.hostname.lower() in {'localhost', '127.0.0.1', '::1'}
    if parsed.scheme.lower() != 'https' and not (
        parsed.scheme.lower() == 'http' and is_local
    ):
        raise CompanionConfigurationError(
            'O Toca Companion exige HTTPS; HTTP só é permitido em localhost.'
        )
    if parsed.query or parsed.fragment:
        raise CompanionConfigurationError('O endereço do servidor não pode conter query ou fragmento.')
    return raw


def validate_form_url(value: str) -> str:
    raw = str(value or '').strip()
    parsed = urlparse(raw)
    host = (parsed.hostname or '').lower()
    allowed = {
        'forms.office.com',
        'forms.microsoft.com',
        'forms.cloud.microsoft',
    }
    if (
        parsed.scheme.lower() != 'https'
        or host not in allowed
        or parsed.username
        or parsed.password
    ):
        raise CompanionConfigurationError(
            'A tarefa não aponta para um endereço oficial do Microsoft Forms.'
        )
    return raw


def _restrict_file(path: Path):
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


class SecretProtector:
    """DPAPI no Windows; Fernet local e fail-closed nas demais plataformas."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def protect(self, plaintext: str) -> str:
        if not plaintext:
            raise CompanionConfigurationError('Token do dispositivo vazio.')
        if sys.platform == 'win32':
            try:
                return 'dpapi:' + base64.b64encode(
                    self._dpapi_protect(plaintext.encode('utf-8'))
                ).decode('ascii')
            except Exception:
                # Fernet continua sendo criptografia autenticada com chave local
                # restrita ao usuário; texto puro nunca é usado como fallback.
                pass
        try:
            encrypted = self._fernet().encrypt(plaintext.encode('utf-8'))
            return 'fernet:' + encrypted.decode('ascii')
        except BaseException as exc:
            raise CompanionConfigurationError(
                'Não foi possível proteger o token do Companion neste computador.'
            ) from exc

    def unprotect(self, protected: str) -> str:
        value = str(protected or '')
        try:
            if value.startswith('dpapi:'):
                encrypted = base64.b64decode(value[6:], validate=True)
                return self._dpapi_unprotect(encrypted).decode('utf-8')
            if value.startswith('fernet:'):
                return self._fernet().decrypt(value[7:].encode('ascii')).decode('utf-8')
        except BaseException as exc:
            raise CompanionConfigurationError(
                'Não foi possível abrir o token protegido do Companion.'
            ) from exc
        raise CompanionConfigurationError(
            'Configuração insegura ou incompatível: vincule o Companion novamente.'
        )

    def _fernet(self):
        from cryptography.fernet import Fernet

        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_path = self.data_dir / '.device_token_key'
        if key_path.exists():
            key = key_path.read_bytes().strip()
            if key:
                return Fernet(key)
        key = Fernet.generate_key()
        try:
            fd = os.open(
                str(key_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            key = key_path.read_bytes().strip()
        else:
            try:
                os.write(fd, key)
            finally:
                os.close(fd)
        _restrict_file(key_path)
        return Fernet(key)

    @staticmethod
    def _dpapi_crypt(data: bytes, *, decrypt: bool) -> bytes:
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [
                ('cbData', wintypes.DWORD),
                ('pbData', ctypes.POINTER(ctypes.c_byte)),
            ]

        buffer = ctypes.create_string_buffer(data)
        in_blob = DataBlob(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = DataBlob()
        if decrypt:
            ok = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None, 0,
                ctypes.byref(out_blob),
            )
        else:
            ok = ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(in_blob), 'Toca Companion', None, None, None, 0,
                ctypes.byref(out_blob),
            )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def _dpapi_protect(cls, data: bytes) -> bytes:
        return cls._dpapi_crypt(data, decrypt=False)

    @classmethod
    def _dpapi_unprotect(cls, data: bytes) -> bytes:
        return cls._dpapi_crypt(data, decrypt=True)


@dataclass(frozen=True)
class CompanionIdentity:
    server_url: str
    device_id: str
    device_name: str
    device_token: str


class CompanionConfigStore:
    def __init__(self, data_dir: Path | None = None, protector=None):
        self.data_dir = Path(data_dir or companion_data_dir())
        self.path = self.data_dir / 'config.json'
        self.protector = protector or SecretProtector(self.data_dir)

    def save(self, *, server_url, device_id, device_name, device_token):
        server_url = validate_server_url(server_url)
        if not _SAFE_ID_RE.fullmatch(str(device_id or '')):
            raise CompanionConfigurationError('Identificador do dispositivo inválido.')
        payload = {
            'schema_version': 1,
            'server_url': server_url,
            'device_id': str(device_id),
            'device_name': str(device_name or 'Toca Companion')[:120],
            'device_token_protected': self.protector.protect(str(device_token)),
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix='.config-', suffix='.tmp', dir=str(self.data_dir)
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
            _restrict_file(self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    def load(self) -> CompanionIdentity:
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise CompanionConfigurationError(
                'Companion ainda não vinculado. Execute o comando "pair".'
            ) from exc
        except (OSError, ValueError, TypeError) as exc:
            raise CompanionConfigurationError('Configuração do Companion inválida.') from exc
        if payload.get('schema_version') != 1:
            raise CompanionConfigurationError('Versão da configuração não suportada.')
        device_id = str(payload.get('device_id') or '')
        if not _SAFE_ID_RE.fullmatch(device_id):
            raise CompanionConfigurationError('Identificador do dispositivo inválido.')
        return CompanionIdentity(
            server_url=validate_server_url(payload.get('server_url')),
            device_id=device_id,
            device_name=str(payload.get('device_name') or 'Toca Companion'),
            device_token=self.protector.unprotect(
                payload.get('device_token_protected')
            ),
        )


class CompanionApiClient:
    def __init__(
        self,
        server_url,
        device_token=None,
        *,
        app_version='1.0.0',
        session=None,
        timeout=DEFAULT_REQUEST_TIMEOUT,
    ):
        self.server_url = validate_server_url(server_url)
        self.device_token = device_token
        self.app_version = str(app_version or '1.0.0')[:32]
        self.session = session or requests.Session()
        self.timeout = timeout
        self._request_lock = threading.Lock()

    def _url(self, path):
        return urljoin(self.server_url + '/', str(path).lstrip('/'))

    def _headers(self, *, lease_token=None, authenticated=True):
        headers = {
            'Accept': 'application/json',
            'User-Agent': f'Toca-Companion/{self.app_version}',
            'X-Toca-Companion-Version': self.app_version,
        }
        if authenticated:
            if not self.device_token:
                raise CompanionAuthenticationError('Token do dispositivo ausente.')
            headers['Authorization'] = f'Bearer {self.device_token}'
        if lease_token:
            headers['X-Toca-Task-Lease'] = lease_token
        return headers

    def _request(
        self,
        method,
        path,
        *,
        json_body=None,
        lease_token=None,
        authenticated=True,
        stream=False,
    ):
        with self._request_lock:
            try:
                response = self.session.request(
                    method,
                    self._url(path),
                    json=json_body,
                    headers=self._headers(
                        lease_token=lease_token,
                        authenticated=authenticated,
                    ),
                    timeout=self.timeout,
                    stream=stream,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise CompanionError('Não foi possível conectar ao Toca web.') from exc
        if response.status_code == 426:
            body = self._json(response)
            raise CompanionUpdateRequired(
                body.get('error') or 'Atualização obrigatória do Companion.'
            )
        if response.status_code in {401, 403}:
            raise CompanionAuthenticationError(
                self._json(response).get('error')
                or 'Vínculo do Companion inválido ou revogado.'
            )
        if response.status_code >= 400:
            body = self._json(response)
            error = CompanionError(body.get('error') or f'Erro HTTP {response.status_code}.')
            error.code = str(body.get('code') or error.code)[:80]
            raise error
        return response

    @staticmethod
    def _json(response):
        try:
            data = response.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def claim_pairing(self, code, device_name, platform=None):
        response = self._request(
            'POST',
            '/api/companion/v1/pairings/claim',
            json_body={
                'pairing_code': str(code or '').strip().upper(),
                'device_name': str(device_name or 'Toca Companion')[:80],
                'platform': str(platform or sys.platform)[:40],
                'app_version': self.app_version,
            },
            authenticated=False,
        )
        return self._json(response)

    def next_task(self):
        response = self._request(
            'POST',
            '/api/companion/v1/tasks/next',
            json_body={'app_version': self.app_version},
        )
        if response.status_code == 204:
            return None
        return self._json(response)

    def update_task(
        self,
        task_id,
        lease_token,
        *,
        status=None,
        progress=None,
        step=None,
        result=None,
        error_code=None,
        error_message=None,
    ):
        if not _SAFE_ID_RE.fullmatch(str(task_id or '')):
            raise CompanionConfigurationError('Identificador da tarefa inválido.')
        body = {}
        for key, value in (
            ('status', status),
            ('progress', progress),
            ('step', step),
            ('result', result),
            ('error_code', error_code),
            ('error_message', error_message),
        ):
            if value is not None:
                body[key] = value
        response = self._request(
            'PATCH',
            f'/api/companion/v1/tasks/{task_id}',
            json_body=body,
            lease_token=lease_token,
        )
        return self._json(response)

    def download_task_file(self, task_id, lease_token, metadata, target_dir):
        file_id = str(metadata.get('id') or '')
        if not _SAFE_ID_RE.fullmatch(file_id):
            raise CompanionIntegrityError('Identificador de arquivo inválido.')
        expected_hash = str(metadata.get('sha256') or '').lower()
        if not _SHA256_RE.fullmatch(expected_hash):
            raise CompanionIntegrityError('SHA-256 do arquivo inválido.')
        try:
            expected_size = int(metadata.get('size_bytes'))
        except (TypeError, ValueError) as exc:
            raise CompanionIntegrityError('Tamanho do arquivo inválido.') from exc
        if expected_size < 0:
            raise CompanionIntegrityError('Tamanho do arquivo inválido.')

        download_path = str(metadata.get('download_url') or '')
        absolute = self._url(download_path)
        if self._origin(absolute) != self._origin(self.server_url):
            raise CompanionIntegrityError('Origem do download não autorizada.')
        response = self._request(
            'GET',
            absolute,
            lease_token=lease_token,
            stream=True,
        )
        filename = Path(str(metadata.get('original_name') or file_id)).name
        filename = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', filename).strip(' .')
        filename = filename[:180] or file_id
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f'{file_id[:12]}-{filename}'
        digest = hashlib.sha256()
        written = 0
        try:
            with target.open('xb') as stream:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise CompanionIntegrityError('Arquivo excedeu o tamanho anunciado.')
                    digest.update(chunk)
                    stream.write(chunk)
            if written != expected_size or digest.hexdigest() != expected_hash:
                raise CompanionIntegrityError('Integridade do arquivo baixado divergente.')
            return target
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            response.close()

    @staticmethod
    def _origin(value):
        parsed = urlparse(value)
        default_port = 443 if parsed.scheme.lower() == 'https' else 80
        return (
            parsed.scheme.lower(),
            (parsed.hostname or '').lower(),
            parsed.port or default_port,
        )

    def manifest(self):
        response = self._request(
            'GET',
            f'/api/companion/v1/manifest?current_version={self.app_version}',
        )
        return self._json(response)

    def download_verified_update(self, manifest, target):
        download = manifest.get('download') if isinstance(manifest, dict) else None
        url = str((download or {}).get('url') or '')
        expected = str((download or {}).get('sha256') or '').lower()
        parsed = urlparse(url)
        if parsed.scheme.lower() != 'https' or not parsed.hostname:
            raise CompanionIntegrityError('URL HTTPS da atualização ausente ou inválida.')
        if not _SHA256_RE.fullmatch(expected):
            raise CompanionIntegrityError('SHA-256 da atualização ausente ou inválido.')
        try:
            response = requests.get(
                url,
                stream=True,
                timeout=self.timeout,
                allow_redirects=False,
                headers={'User-Agent': f'Toca-Companion/{self.app_version}'},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CompanionError('Não foi possível baixar a atualização.') from exc
        target = Path(target)
        temporary = target.with_suffix(target.suffix + '.part')
        digest = hashlib.sha256()
        try:
            with temporary.open('wb') as stream:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        digest.update(chunk)
                        stream.write(chunk)
            if digest.hexdigest() != expected:
                raise CompanionIntegrityError('SHA-256 da atualização divergente.')
            os.replace(temporary, target)
            return target
        finally:
            response.close()
            temporary.unlink(missing_ok=True)


class CompanionRunner:
    def __init__(
        self,
        client,
        *,
        robot=None,
        temp_root=None,
        heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
    ):
        if robot is None:
            from integrations.forms_robot import run_chamado_juridico_robot
            robot = run_chamado_juridico_robot
        self.client = client
        self.robot = robot
        self.temp_root = Path(temp_root or companion_data_dir() / 'tasks')
        self.heartbeat_seconds = max(1, int(heartbeat_seconds))

    def run_once(self):
        task = self.client.next_task()
        if not task:
            return False
        self._execute(task)
        return True

    def _execute(self, task):
        task_id = str(task.get('task_id') or '')
        lease_token = str(task.get('lease_token') or '')
        if (
            task.get('protocol_version') != PROTOCOL_VERSION
            or not _SAFE_ID_RE.fullmatch(task_id)
            or not lease_token
        ):
            raise CompanionConfigurationError('Envelope de tarefa inválido.')
        payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        constraints = (
            payload.get('constraints')
            if isinstance(payload.get('constraints'), dict)
            else {}
        )
        if (
            payload.get('schema_version') != PROTOCOL_VERSION
            or payload.get('task_type') != TASK_TYPE_CHAMADO_JURIDICO
            or constraints.get('allow_submit') is not False
            or constraints.get('requires_user_review') is not True
        ):
            self._terminal(
                task_id,
                lease_token,
                status='failed',
                error_code='COMPANION_TASK_UNSUPPORTED',
                error_message='Tipo, versão ou restrições da tarefa não suportados.',
            )
            return
        try:
            form_url = validate_form_url(payload.get('form_url'))
        except CompanionConfigurationError as exc:
            self._terminal(
                task_id,
                lease_token,
                status='failed',
                error_code=exc.code,
                error_message=str(exc),
            )
            return

        cancel_event = threading.Event()
        heartbeat_stop = threading.Event()
        state_lock = threading.Lock()
        state = {
            'progress': 5,
            'step': 'Preparando arquivos temporários...',
            'awaiting_user': False,
            'heartbeat_error': None,
        }

        first = self.client.update_task(
            task_id,
            lease_token,
            status='running',
            progress=5,
            step=state['step'],
        )
        if first.get('cancel_requested'):
            cancel_event.set()

        def heartbeat():
            while not heartbeat_stop.wait(self.heartbeat_seconds):
                with state_lock:
                    progress = state['progress']
                    step = state['step']
                try:
                    response = self.client.update_task(
                        task_id,
                        lease_token,
                        progress=progress,
                        step=step,
                    )
                    if response.get('cancel_requested'):
                        cancel_event.set()
                except Exception as exc:
                    with state_lock:
                        state['heartbeat_error'] = exc
                    cancel_event.set()
                    return

        heartbeat_thread = threading.Thread(
            target=heartbeat,
            name=f'toca-companion-heartbeat-{task_id[:8]}',
            daemon=True,
        )
        heartbeat_thread.start()

        try:
            self.temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f'task-{task_id[:12]}-',
                dir=str(self.temp_root),
            ) as temporary:
                local_files = {}
                for metadata in task.get('files') or []:
                    if cancel_event.is_set():
                        raise CompanionCancelled('Cancelamento solicitado pelo usuário.')
                    field_key = str(metadata.get('field_key') or '')
                    local_path = self.client.download_task_file(
                        task_id,
                        lease_token,
                        metadata,
                        temporary,
                    )
                    local_files.setdefault(field_key, []).append({
                        'stored_path': str(local_path),
                        'original_name': metadata.get('original_name') or local_path.name,
                    })

                fields = build_chamado_juridico_fields(
                    payload.get('fields') or {},
                    local_files,
                )

                def on_progress(progress, step):
                    if cancel_event.is_set():
                        raise CompanionCancelled('Cancelamento solicitado pelo usuário.')
                    progress = min(100, max(0, int(progress)))
                    step = str(step or '')[:500]
                    needs_transition = False
                    with state_lock:
                        state['progress'] = progress
                        state['step'] = step
                        if progress >= 88 and not state['awaiting_user']:
                            state['awaiting_user'] = True
                            needs_transition = True
                    if needs_transition:
                        response = self.client.update_task(
                            task_id,
                            lease_token,
                            status='awaiting_user',
                            progress=progress,
                            step=step,
                        )
                        if response.get('cancel_requested'):
                            cancel_event.set()

                result = self.robot(
                    form_url,
                    fields,
                    on_progress,
                    should_cancel=cancel_event.is_set,
                )
                with state_lock:
                    heartbeat_error = state['heartbeat_error']
                if heartbeat_error is not None:
                    raise CompanionError('O lease da tarefa não pôde ser renovado.')
                if cancel_event.is_set():
                    raise CompanionCancelled('Cancelamento solicitado pelo usuário.')
                safe_result = {
                    # `submitted` permanece falso por contrato: o Companion
                    # jamais clica em Enviar. O sinal separado apenas registra
                    # que o Forms detectou a ação humana na janela local.
                    'submitted': False,
                    'human_submission_detected': bool(result.get('submitted')),
                    'filled': list(result.get('filled') or []),
                    'unmatched': list(result.get('unmatched') or []),
                    'errors': list(result.get('errors') or []),
                    'positional': list(result.get('positional') or []),
                    'questions_found': int(result.get('questions_found') or 0),
                    'history_id': payload.get('history_id'),
                }
                self._terminal(
                    task_id,
                    lease_token,
                    status='succeeded',
                    progress=100,
                    step=(
                        'Ação humana confirmada pelo Microsoft Forms.'
                        if safe_result['human_submission_detected']
                        else 'Preenchimento concluído para revisão e envio na janela local.'
                    ),
                    result=safe_result,
                )
        except CompanionCancelled:
            self._terminal(
                task_id,
                lease_token,
                status='cancelled',
                error_code='COMPANION_CANCELLED',
                error_message='Execução cancelada pelo usuário.',
            )
        except Exception as exc:
            with state_lock:
                heartbeat_error = state['heartbeat_error']
            if cancel_event.is_set() and heartbeat_error is None:
                self._terminal(
                    task_id,
                    lease_token,
                    status='cancelled',
                    error_code='COMPANION_CANCELLED',
                    error_message='Execução cancelada pelo usuário.',
                )
                return
            code = str(getattr(exc, 'code', '') or 'COMPANION_EXECUTION_FAILED')[:80]
            message = str(exc or 'Falha no executor local.')[:MAX_ERROR_TEXT]
            self._terminal(
                task_id,
                lease_token,
                status='failed',
                error_code=code,
                error_message=message,
            )
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)

    def _terminal(
        self,
        task_id,
        lease_token,
        *,
        status,
        progress=None,
        step=None,
        result=None,
        error_code=None,
        error_message=None,
    ):
        return self.client.update_task(
            task_id,
            lease_token,
            status=status,
            progress=progress,
            step=step,
            result=result,
            error_code=error_code,
            error_message=error_message,
        )
