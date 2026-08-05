import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger('toca-do-coelho.outlook-graph')

GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0'
TOKEN_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
AUTH_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
PROVIDER = 'outlook_graph'

_MAX_SYNC_PAGES = 50
_MAX_SYNC_RANGE_DAYS = 366
_MAX_ATTACHMENTS = 10
_MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024
_MAX_TOTAL_ATTACHMENT_BYTES = 10 * 1024 * 1024
_MAX_BODY_HTML_BYTES = 5 * 1024 * 1024

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class OutlookOAuthError(Exception):
    pass


class OutlookSyncError(Exception):
    pass


class TokenProtectionError(OutlookOAuthError):
    """Nenhum mecanismo de criptografia disponível para proteger o token — a
    aplicação recusa persistir o token em vez de gravá-lo em texto puro."""
    pass


def _now_utc():
    return datetime.now(timezone.utc)


def _to_iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _safe_json_loads(raw_bytes):
    try:
        return json.loads((raw_bytes or b'').decode('utf-8', errors='replace'))
    except Exception:
        return {}


def ensure_schema(conn: sqlite3.Connection):
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS user_integrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            scope TEXT,
            token_type TEXT,
            expires_at TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, provider)
        )'''
    )
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_integrations_provider ON user_integrations(provider)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_integrations_user ON user_integrations(user_id)')

    # Tentativas de autorização OAuth (state + PKCE verifier), persistidas em
    # banco para sobreviver a reinícios/múltiplos workers e para permitir
    # invalidação de uso único (consumed) — ver consume_oauth_state().
    c.execute(
        '''CREATE TABLE IF NOT EXISTS outlook_oauth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_hash TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            pkce_verifier TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0
        )'''
    )
    c.execute('CREATE INDEX IF NOT EXISTS idx_outlook_oauth_attempts_state ON outlook_oauth_attempts(state_hash)')

    # Registro de emails já processados, para deduplicação entre sincronizações.
    # message_id = internetMessageId (globalmente único). conversation_id agrupa a thread.
    c.execute(
        '''CREATE TABLE IF NOT EXISTS outlook_processed_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            message_id TEXT NOT NULL,
            conversation_id TEXT,
            client_id INTEGER,
            activity_id INTEGER,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, message_id)
        )'''
    )
    c.execute('CREATE INDEX IF NOT EXISTS idx_outlook_processed_msg ON outlook_processed_emails(message_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_outlook_processed_conv ON outlook_processed_emails(conversation_id)')


def _http_form_post(url, form_data):
    payload = urllib.parse.urlencode(form_data).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _safe_json_loads(resp.read())
    except urllib.error.HTTPError as e:
        body = _safe_json_loads(e.read())
        err = body.get('error_description') or body.get('error') or str(e)
        if 'AADSTS65001' in str(err) or 'consent' in str(err).lower() or 'interaction_required' in str(body.get('error') or ''):
            raise OutlookOAuthError(
                'As permissões de e-mail ainda não foram concedidas para esta conta. '
                'Use o botão "Tentar de novo pedindo consentimento" nesta tela. '
                'Se a empresa exigir aprovação do administrador, peça que ele conceda '
                'o consentimento para o aplicativo no Azure (Mail.Read, Mail.Send, '
                'offline_access e User.Read).'
            ) from e
        logger.error(f'[OutlookGraph] Falha OAuth no token endpoint: {err}')
        raise OutlookOAuthError(
            'Falha ao autenticar com a Microsoft. Tente reconectar a integração do Outlook.'
        ) from e
    except Exception as e:
        logger.error(f'[OutlookGraph] Falha de conexão no token endpoint: {e}')
        raise OutlookOAuthError('Falha de conexão com o servidor de autenticação da Microsoft.') from e


def _http_get_json(url, headers=None):
    req = urllib.request.Request(url, method='GET')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return _safe_json_loads(resp.read())
    except urllib.error.HTTPError as e:
        body = _safe_json_loads(e.read())
        msg = body.get('error', {}).get('message') if isinstance(body.get('error'), dict) else body.get('error')
        logger.error(f'[OutlookGraph] Falha Graph API ({getattr(e, "code", "?")}): {msg or str(e)}')
        raise OutlookSyncError('Falha ao consultar a API do Microsoft Graph. Tente novamente em instantes.') from e
    except Exception as e:
        logger.error(f'[OutlookGraph] Falha de conexão Graph API: {e}')
        raise OutlookSyncError('Falha de conexão com a API do Microsoft Graph.') from e


# ── PKCE (RFC 7636) ─────────────────────────────────────────────────────────
# Public client flow — sem client_secret. Recomendado pela Microsoft para apps
# desktop/nativos (https://learn.microsoft.com/en-us/azure/active-directory/
# develop/v2-oauth2-auth-code-flow#request-an-authorization-code).
# O verifier é persistido junto do state em outlook_oauth_attempts (ver seção
# "State CSRF" abaixo) — não em memória do processo — para funcionar entre
# reinícios e múltiplos workers, e para ser invalidado após o primeiro uso.

def _pkce_make_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode('ascii')


def _pkce_make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


# ── Proteção de tokens em repouso ────────────────────────────────────────────
# No Windows, usa o DPAPI (chave amarrada à conta do usuário do SO). Em
# qualquer outra situação — outra plataforma, ou falha do DPAPI — usa
# criptografia autenticada (Fernet/AES-CBC+HMAC) com uma chave gerada uma
# única vez por instalação e persistida fora do banco, em arquivo com
# permissão restrita ao usuário do SO (fora do código-fonte e do repositório).
# Se nenhum dos dois mecanismos estiver disponível, o token NUNCA é gravado em
# texto puro: a operação falha (fail-closed) e o usuário é levado a reconectar.

_DPAPI_PREFIX = 'dpapi:'
_FERNET_PREFIX = 'fernet:'

_fernet_instance = None
_fernet_lock = threading.Lock()


def _local_data_dir() -> Path:
    base = (
        Path.home() / 'AppData' / 'Roaming' / 'toca-do-coelho'
        if sys.platform == 'win32'
        else Path.home() / '.toca-do-coelho'
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _load_or_create_fernet_key() -> bytes:
    from cryptography.fernet import Fernet
    key_path = _local_data_dir() / '.outlook_token_key'
    if key_path.exists():
        key = key_path.read_bytes().strip()
        if key:
            return key
    key = Fernet.generate_key()
    fd = os.open(str(key_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    try:
        os.chmod(str(key_path), 0o600)
    except Exception:
        logger.debug('[OutlookGraph] Não foi possível restringir permissões do arquivo de chave.', exc_info=True)
    return key


def _get_fernet():
    global _fernet_instance
    if _fernet_instance is None:
        with _fernet_lock:
            if _fernet_instance is None:
                from cryptography.fernet import Fernet
                _fernet_instance = Fernet(_load_or_create_fernet_key())
    return _fernet_instance


def _token_encrypt(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    if sys.platform == 'win32':
        try:
            import win32crypt  # type: ignore
            encrypted = win32crypt.CryptProtectData(plaintext.encode('utf-8'), None, None, None, None, 0)
            return _DPAPI_PREFIX + base64.b64encode(encrypted).decode('ascii')
        except Exception:
            logger.warning('[OutlookGraph] DPAPI indisponível; usando criptografia local como alternativa.')
    try:
        token = _get_fernet().encrypt(plaintext.encode('utf-8'))
        return _FERNET_PREFIX + token.decode('ascii')
    except BaseException as exc:
        # BaseException (não só Exception): bindings nativos de bibliotecas de
        # criptografia podem falhar fora da hierarquia normal de exceções
        # Python — a proteção fail-closed precisa cobrir esse caso também.
        logger.exception('[OutlookGraph] Falha ao proteger token OAuth — nenhum mecanismo de criptografia disponível.')
        raise TokenProtectionError(
            'Não foi possível proteger o token OAuth (nenhum mecanismo de criptografia disponível). '
            'A conexão com o Outlook foi cancelada por segurança.'
        ) from exc


def _token_decrypt(value: str) -> str:
    if not value:
        return value
    if value.startswith(_DPAPI_PREFIX):
        try:
            import win32crypt  # type: ignore
            encrypted = base64.b64decode(value[len(_DPAPI_PREFIX):])
            _, decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)
            return decrypted.decode('utf-8')
        except Exception as exc:
            raise TokenProtectionError('Falha ao decifrar token protegido por DPAPI.') from exc
    if value.startswith(_FERNET_PREFIX):
        try:
            return _get_fernet().decrypt(value[len(_FERNET_PREFIX):].encode('ascii')).decode('utf-8')
        except BaseException as exc:
            raise TokenProtectionError('Falha ao decifrar token protegido localmente.') from exc
    # Token legado gravado em texto puro antes da correção do fallback
    # inseguro. Mantido legível para não derrubar contas já conectadas; é
    # automaticamente re-protegido na próxima renovação (via _upsert_tokens).
    logger.warning('[OutlookGraph] Token legado em texto puro detectado; será re-protegido na próxima renovação.')
    return value


# ── State CSRF + tentativa OAuth (uso único) ─────────────────────────────────
# O state é um token opaco aleatório (sem payload/assinatura) cuja única
# função é apontar para um registro server-side de uso único, com expiração
# curta. Isso elimina a necessidade de qualquer segredo de assinatura (e,
# portanto, qualquer valor padrão que pudesse ser reproduzido por quem tem
# acesso ao código-fonte).

def _cleanup_oauth_attempts(conn):
    try:
        c = conn.cursor()
        c.execute(
            'DELETE FROM outlook_oauth_attempts WHERE expires_at < ? OR consumed = 1',
            (_now_utc().timestamp() - 1800,),
        )
        conn.commit()
    except Exception:
        logger.debug('[OutlookGraph] Falha ao limpar tentativas OAuth expiradas.', exc_info=True)


def _create_oauth_attempt(conn, user_id: int, verifier: str) -> str:
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode('ascii')).hexdigest()
    now_ts = _now_utc().timestamp()
    c = conn.cursor()
    c.execute(
        '''INSERT INTO outlook_oauth_attempts
           (state_hash, user_id, pkce_verifier, created_at, expires_at, consumed)
           VALUES (?, ?, ?, ?, ?, 0)''',
        (state_hash, int(user_id), verifier, now_ts, now_ts + 600),
    )
    conn.commit()
    _cleanup_oauth_attempts(conn)
    return state


def consume_oauth_state(conn, state: str):
    """Valida o state (uso único, expiração de 10 min) e retorna (user_id, pkce_verifier).
    Levanta OutlookOAuthError se o state for desconhecido, expirado ou já usado."""
    state = (state or '').strip()
    if not state:
        raise OutlookOAuthError('state OAuth ausente.')
    state_hash = hashlib.sha256(state.encode('ascii')).hexdigest()
    now_ts = _now_utc().timestamp()
    c = conn.cursor()
    c.execute(
        '''UPDATE outlook_oauth_attempts SET consumed = 1
           WHERE state_hash = ? AND consumed = 0 AND expires_at >= ?''',
        (state_hash, now_ts),
    )
    conn.commit()
    if c.rowcount != 1:
        raise OutlookOAuthError(
            'state OAuth inválido, expirado ou já utilizado. Reinicie o fluxo de autorização.'
        )
    c.execute('SELECT user_id, pkce_verifier FROM outlook_oauth_attempts WHERE state_hash = ?', (state_hash,))
    row = c.fetchone()
    if not row:
        raise OutlookOAuthError('Tentativa OAuth não encontrada.')
    return int(row['user_id']), row['pkce_verifier']


# ── OAuth config ─────────────────────────────────────────────────────────────

_TENANT_RE = re.compile(r'^[a-zA-Z0-9](?:[a-zA-Z0-9.\-]{0,90}[a-zA-Z0-9])?$')
_CLIENT_ID_RE = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_ALLOWED_SCOPES = {'openid', 'profile', 'email', 'offline_access', 'User.Read', 'Mail.Read', 'Mail.Send'}
_ALLOWED_REDIRECT_SCHEMES = {'http', 'https'}


def _validate_oauth_config(tenant, client_id, redirect_uri, scope):
    if not _TENANT_RE.match(tenant):
        raise OutlookOAuthError('Tenant OAuth com formato inválido.')
    if not _CLIENT_ID_RE.match(client_id):
        raise OutlookOAuthError('Client ID OAuth com formato inválido (esperado GUID).')
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme not in _ALLOWED_REDIRECT_SCHEMES or not parsed.netloc:
        raise OutlookOAuthError('Redirect URI OAuth com formato inválido.')
    for s in scope.split():
        if s not in _ALLOWED_SCOPES:
            raise OutlookOAuthError(f'Escopo OAuth não permitido: {s}')


def _oauth_config(settings=None):
    if settings:
        tenant = (settings.get('tenant') or 'common').strip()
        client_id = (settings.get('client_id') or '').strip()
        redirect_uri = (settings.get('redirect_uri') or '').strip()
        scope = (settings.get('scope') or 'offline_access Mail.Read Mail.Send').strip()
    else:
        tenant = (os.environ.get('OUTLOOK_GRAPH_TENANT_ID') or 'common').strip()
        client_id = (os.environ.get('OUTLOOK_GRAPH_CLIENT_ID') or '').strip()
        redirect_uri = (os.environ.get('OUTLOOK_GRAPH_REDIRECT_URI') or '').strip()
        scope = (os.environ.get('OUTLOOK_GRAPH_SCOPE') or 'offline_access Mail.Read Mail.Send').strip()

    if not client_id or not redirect_uri:
        raise OutlookOAuthError(
            'Configuração OAuth ausente. Configure Tenant ID e Client ID nas Configurações do Toca.'
        )
    _validate_oauth_config(tenant, client_id, redirect_uri, scope)

    return {
        'tenant': tenant,
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': scope,
        'token_url': TOKEN_URL_TEMPLATE.format(tenant=tenant),
        'authorize_url': AUTH_URL_TEMPLATE.format(tenant=tenant),
    }


def build_authorize_url(conn, user_id: int, settings=None, force_consent: bool = False):
    """Monta a URL de autorização OAuth.

    `force_consent` (prompt=consent) só deve ser usado como último recurso, a
    pedido explícito do usuário. Ele pede um consentimento NOVO do usuário e
    ignora o consentimento de administrador já concedido para o tenant — em
    empresas onde o consentimento de usuário é bloqueado (o padrão corporativo),
    isso leva à tela "Aprovação necessária / Solicitar aprovação" mesmo com as
    permissões já liberadas pelo admin no Azure, travando a conexão para sempre.
    Sem ele, o Azure reconhece o consentimento do admin e devolve o código
    direto. Quando o consentimento de fato estiver faltando (escopo novo em
    tenant sem admin consent), o token endpoint devolve AADSTS65001 e aí sim
    vale reiniciar o fluxo com force_consent=True."""
    cfg = _oauth_config(settings)
    verifier = _pkce_make_verifier()
    state = _create_oauth_attempt(conn, user_id, verifier)
    params = {
        'client_id': cfg['client_id'],
        'response_type': 'code',
        'redirect_uri': cfg['redirect_uri'],
        'response_mode': 'query',
        'scope': cfg['scope'],
        'state': state,
        'code_challenge': _pkce_make_challenge(verifier),
        'code_challenge_method': 'S256',
    }
    if force_consent:
        params['prompt'] = 'consent'
    return f"{cfg['authorize_url']}?{urllib.parse.urlencode(params)}"


def _upsert_tokens(conn, user_id, token_payload):
    expires_in = int(token_payload.get('expires_in') or 3600)
    expires_at = _to_iso(_now_utc() + timedelta(seconds=expires_in))
    metadata_json = json.dumps({'obtained_at': _to_iso(_now_utc())}, ensure_ascii=False)
    c = conn.cursor()
    c.execute(
        '''INSERT INTO user_integrations
           (user_id, provider, access_token, refresh_token, scope, token_type, expires_at, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, provider) DO UPDATE SET
             access_token=excluded.access_token,
             refresh_token=COALESCE(excluded.refresh_token, user_integrations.refresh_token),
             scope=excluded.scope,
             token_type=excluded.token_type,
             expires_at=excluded.expires_at,
             metadata_json=excluded.metadata_json,
             updated_at=CURRENT_TIMESTAMP''',
        (
            int(user_id),
            PROVIDER,
            _token_encrypt(token_payload.get('access_token') or ''),
            _token_encrypt(token_payload.get('refresh_token') or ''),
            token_payload.get('scope'),
            token_payload.get('token_type') or 'Bearer',
            expires_at,
            metadata_json,
        ),
    )
    conn.commit()


def exchange_code_and_store(conn, code: str, user_id: int, verifier: str, settings=None):
    cfg = _oauth_config(settings)
    body = {
        'client_id': cfg['client_id'],
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': cfg['redirect_uri'],
        'scope': cfg['scope'],
        'code_verifier': verifier,
    }
    token_payload = _http_form_post(cfg['token_url'], body)
    if not token_payload.get('access_token'):
        raise OutlookOAuthError('Token OAuth inválido: access_token ausente.')
    _upsert_tokens(conn, user_id, token_payload)
    # Nunca devolve o token_payload completo (contém access_token/refresh_token) —
    # somente metadados não sensíveis para confirmar a conexão ao chamador.
    return {
        'connected': True,
        'scope': token_payload.get('scope'),
        'expires_in': token_payload.get('expires_in'),
    }


def _load_integration(conn, user_id: int):
    c = conn.cursor()
    c.execute(
        '''SELECT * FROM user_integrations WHERE user_id = ? AND provider = ? LIMIT 1''',
        (int(user_id), PROVIDER),
    )
    return c.fetchone()


def _is_expired(expires_at: str):
    if not expires_at:
        return True
    try:
        dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        return dt <= (_now_utc() + timedelta(seconds=60))
    except Exception:
        return True


def _refresh_tokens(conn, user_id: int, refresh_token: str, settings=None):
    cfg = _oauth_config(settings)
    body = {
        'client_id': cfg['client_id'],
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'scope': cfg['scope'],
    }
    payload = _http_form_post(cfg['token_url'], body)
    if not payload.get('access_token'):
        raise OutlookOAuthError('Falha ao renovar token OAuth: access_token ausente.')
    _upsert_tokens(conn, user_id, payload)
    return payload


def get_valid_access_token(conn, user_id: int, settings=None):
    row = _load_integration(conn, user_id)
    if not row:
        raise OutlookOAuthError('Integração Outlook Graph não conectada para este usuário.')

    access_token = _token_decrypt(row['access_token'] or '')
    refresh_token = _token_decrypt(row['refresh_token'] or '')
    expires_at = row['expires_at']

    if access_token and not _is_expired(expires_at):
        return access_token

    if not refresh_token:
        raise OutlookOAuthError('Token expirado e refresh_token indisponível. Refaça a conexão OAuth.')

    payload = _refresh_tokens(conn, user_id, refresh_token, settings=settings)
    return payload.get('access_token')


_ALLOWED_GRAPH_HOSTS = {'graph.microsoft.com'}


def _validate_graph_url(url: str) -> str:
    """Garante que o bearer token só é reenviado para o host oficial do Graph,
    mesmo seguindo o @odata.nextLink devolvido pela própria API."""
    parsed = urllib.parse.urlparse(url or '')
    if parsed.scheme != 'https':
        raise OutlookSyncError('URL de paginação do Graph sem HTTPS.')
    if parsed.hostname not in _ALLOWED_GRAPH_HOSTS:
        raise OutlookSyncError('URL de paginação do Graph aponta para um domínio não autorizado.')
    if parsed.username or parsed.password:
        raise OutlookSyncError('URL de paginação do Graph contém credenciais embutidas.')
    return url


def fetch_messages(access_token: str, start_date: datetime, end_date: datetime, page_size=50, max_pages=10):
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    if start_date > end_date:
        raise OutlookSyncError('Data inicial não pode ser posterior à data final.')
    if (end_date - start_date) > timedelta(days=_MAX_SYNC_RANGE_DAYS):
        raise OutlookSyncError(f'Intervalo de sincronização não pode exceder {_MAX_SYNC_RANGE_DAYS} dias.')

    page_size = max(1, min(int(page_size), 200))
    max_pages = max(1, min(int(max_pages), _MAX_SYNC_PAGES))

    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}

    def collect(folder_name, direction):
        items = []
        select = ('subject,receivedDateTime,sentDateTime,from,toRecipients,ccRecipients,'
                  'bodyPreview,internetMessageId,conversationId')
        flt = (
            f"receivedDateTime ge {start_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"and receivedDateTime le {end_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        params = {
            '$select': select,
            '$orderby': 'receivedDateTime desc',
            '$filter': flt,
            '$top': page_size,
        }
        next_url = f"{GRAPH_BASE_URL}/me/mailFolders/{folder_name}/messages?{urllib.parse.urlencode(params)}"
        page = 0
        while next_url and page < max_pages:
            payload = _http_get_json(next_url, headers=headers)
            for msg in payload.get('value', []) or []:
                sender = ((msg.get('from') or {}).get('emailAddress') or {})
                recipients = []
                for r in msg.get('toRecipients') or []:
                    em = (r.get('emailAddress') or {})
                    recipients.append({'name': em.get('name') or '', 'email': (em.get('address') or '').lower()})
                cc_recipients = []
                for r in msg.get('ccRecipients') or []:
                    em = (r.get('emailAddress') or {})
                    cc_recipients.append({'name': em.get('name') or '', 'email': (em.get('address') or '').lower()})
                when = msg.get('receivedDateTime') or msg.get('sentDateTime') or ''
                items.append({
                    'subject': msg.get('subject') or '',
                    'date': when.replace('Z', '+00:00'),
                    'direction': direction,
                    'sender': {
                        'name': sender.get('name') or '',
                        'email': (sender.get('address') or '').lower(),
                    },
                    'recipients': recipients,
                    'cc_recipients': cc_recipients,
                    'body_preview': msg.get('bodyPreview') or '',
                    'message_id': msg.get('internetMessageId') or '',
                    'conversation_id': msg.get('conversationId') or '',
                })
            next_url = payload.get('@odata.nextLink')
            if next_url:
                next_url = _validate_graph_url(next_url)
            page += 1
        return items

    inbox = collect('inbox', 'received')
    sent = collect('sentitems', 'sent')
    return inbox + sent


def send_mail(access_token: str, to: str, subject: str, body_html: str, attachments=None):
    """Envia e-mail via Microsoft Graph POST /me/sendMail (requer escopo Mail.Send).
    attachments: lista de dicts {'name', 'content_bytes' (base64 str), 'content_type'}.
    Após adicionar Mail.Send ao escopo, o usuário precisa reconectar a
    integração uma vez para conceder a nova permissão."""
    to = (to or '').strip()
    if not _EMAIL_RE.match(to):
        raise OutlookSyncError('Endereço de destinatário inválido.')

    body_html = body_html or ''
    if len(body_html.encode('utf-8')) > _MAX_BODY_HTML_BYTES:
        raise OutlookSyncError(f'Corpo do e-mail excede o limite de {_MAX_BODY_HTML_BYTES // (1024 * 1024)}MB.')

    message = {
        'subject': (subject or '')[:998],
        'body': {'contentType': 'HTML', 'content': body_html},
        'toRecipients': [{'emailAddress': {'address': to}}],
    }

    attachments = attachments or []
    if len(attachments) > _MAX_ATTACHMENTS:
        raise OutlookSyncError(f'Excesso de anexos: máximo permitido é {_MAX_ATTACHMENTS}.')
    if attachments:
        graph_attachments = []
        total_bytes = 0
        for att in attachments:
            name = os.path.basename((att.get('name') or 'anexo').strip()) or 'anexo'
            content_b64 = att.get('content_bytes') or ''
            try:
                decoded = base64.b64decode(content_b64, validate=True)
            except Exception as exc:
                raise OutlookSyncError(f'Anexo "{name}" com conteúdo base64 inválido.') from exc
            if len(decoded) > _MAX_ATTACHMENT_BYTES:
                raise OutlookSyncError(
                    f'Anexo "{name}" excede o tamanho máximo de {_MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB.'
                )
            total_bytes += len(decoded)
            if total_bytes > _MAX_TOTAL_ATTACHMENT_BYTES:
                raise OutlookSyncError(
                    f'Soma dos anexos excede o limite total de {_MAX_TOTAL_ATTACHMENT_BYTES // (1024 * 1024)}MB.'
                )
            graph_attachments.append({
                '@odata.type': '#microsoft.graph.fileAttachment',
                'name': name,
                'contentType': att.get('content_type') or 'application/octet-stream',
                'contentBytes': content_b64,
            })
        message['attachments'] = graph_attachments

    payload = json.dumps({'message': message, 'saveToSentItems': True}).encode('utf-8')
    req = urllib.request.Request(
        f'{GRAPH_BASE_URL}/me/sendMail',
        data=payload,
        method='POST',
        headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:500]
        logger.error(f'[OutlookGraph] Falha ao enviar e-mail via Graph: HTTP {e.code} — {body}')
        raise OutlookSyncError('Falha ao enviar e-mail via Microsoft Graph. Tente novamente.') from e
    except Exception as e:
        logger.error(f'[OutlookGraph] Falha de conexão ao enviar e-mail via Graph: {e}')
        raise OutlookSyncError('Falha de conexão com o Microsoft Graph ao enviar e-mail.') from e
    if status not in (200, 202):
        logger.error(f'[OutlookGraph] Falha ao enviar e-mail via Graph: HTTP {status}')
        raise OutlookSyncError('Falha ao enviar e-mail via Microsoft Graph.')
    return True
