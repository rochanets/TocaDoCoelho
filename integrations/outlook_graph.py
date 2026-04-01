import base64
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger('toca-do-coelho.outlook-graph')

GRAPH_BASE_URL = 'https://graph.microsoft.com/v1.0'
TOKEN_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
AUTH_URL_TEMPLATE = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
PROVIDER = 'outlook_graph'


class OutlookOAuthError(Exception):
    pass


class OutlookSyncError(Exception):
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
        raise OutlookOAuthError(f'Falha OAuth no token endpoint: {err}') from e
    except Exception as e:
        raise OutlookOAuthError(f'Falha de conexão no token endpoint: {e}') from e


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
        raise OutlookSyncError(f'Falha Graph API ({getattr(e, "code", "?")}): {msg or str(e)}') from e
    except Exception as e:
        raise OutlookSyncError(f'Falha de conexão Graph API: {e}') from e


def _state_secret():
    return (os.environ.get('OUTLOOK_GRAPH_STATE_SECRET') or 'toca-outlook-graph-state').encode('utf-8')


def make_state(user_id: int):
    payload = {'user_id': int(user_id), 'ts': int(_now_utc().timestamp())}
    raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    sig = hmac.new(_state_secret(), raw, hashlib.sha256).hexdigest()
    packed = {'p': base64.urlsafe_b64encode(raw).decode('ascii'), 's': sig}
    return base64.urlsafe_b64encode(json.dumps(packed).encode('utf-8')).decode('ascii')


def parse_state(state: str):
    try:
        packed = json.loads(base64.urlsafe_b64decode(state.encode('ascii')).decode('utf-8'))
        raw = base64.urlsafe_b64decode((packed.get('p') or '').encode('ascii'))
        sig = packed.get('s') or ''
        expected = hmac.new(_state_secret(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise OutlookOAuthError('state OAuth inválido (assinatura).')
        payload = json.loads(raw.decode('utf-8'))
        if _now_utc().timestamp() - int(payload.get('ts', 0)) > 1800:
            raise OutlookOAuthError('state OAuth expirado.')
        return int(payload.get('user_id', 1))
    except OutlookOAuthError:
        raise
    except Exception as e:
        raise OutlookOAuthError(f'state OAuth inválido: {e}') from e


def _oauth_config():
    tenant = (os.environ.get('OUTLOOK_GRAPH_TENANT_ID') or 'common').strip()
    client_id = (os.environ.get('OUTLOOK_GRAPH_CLIENT_ID') or '').strip()
    client_secret = (os.environ.get('OUTLOOK_GRAPH_CLIENT_SECRET') or '').strip()
    redirect_uri = (os.environ.get('OUTLOOK_GRAPH_REDIRECT_URI') or '').strip()
    scope = (os.environ.get('OUTLOOK_GRAPH_SCOPE') or 'offline_access Mail.Read').strip()

    if not client_id or not client_secret or not redirect_uri:
        raise OutlookOAuthError(
            'Configuração OAuth ausente. Defina OUTLOOK_GRAPH_CLIENT_ID, OUTLOOK_GRAPH_CLIENT_SECRET e OUTLOOK_GRAPH_REDIRECT_URI.'
        )

    return {
        'tenant': tenant,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'scope': scope,
        'token_url': TOKEN_URL_TEMPLATE.format(tenant=tenant),
        'authorize_url': AUTH_URL_TEMPLATE.format(tenant=tenant),
    }


def build_authorize_url(user_id: int):
    cfg = _oauth_config()
    params = {
        'client_id': cfg['client_id'],
        'response_type': 'code',
        'redirect_uri': cfg['redirect_uri'],
        'response_mode': 'query',
        'scope': cfg['scope'],
        'state': make_state(user_id),
    }
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
            token_payload.get('access_token'),
            token_payload.get('refresh_token'),
            token_payload.get('scope'),
            token_payload.get('token_type') or 'Bearer',
            expires_at,
            metadata_json,
        ),
    )
    conn.commit()


def exchange_code_and_store(conn, code: str, user_id: int):
    cfg = _oauth_config()
    body = {
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': cfg['redirect_uri'],
        'scope': cfg['scope'],
    }
    token_payload = _http_form_post(cfg['token_url'], body)
    if not token_payload.get('access_token'):
        raise OutlookOAuthError('Token OAuth inválido: access_token ausente.')
    _upsert_tokens(conn, user_id, token_payload)
    return token_payload


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


def _refresh_tokens(conn, user_id: int, refresh_token: str):
    cfg = _oauth_config()
    body = {
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'redirect_uri': cfg['redirect_uri'],
        'scope': cfg['scope'],
    }
    payload = _http_form_post(cfg['token_url'], body)
    if not payload.get('access_token'):
        raise OutlookOAuthError('Falha ao renovar token OAuth: access_token ausente.')
    _upsert_tokens(conn, user_id, payload)
    return payload


def get_valid_access_token(conn, user_id: int):
    row = _load_integration(conn, user_id)
    if not row:
        raise OutlookOAuthError('Integração Outlook Graph não conectada para este usuário.')

    access_token = row['access_token']
    refresh_token = row['refresh_token']
    expires_at = row['expires_at']

    if access_token and not _is_expired(expires_at):
        return access_token

    if not refresh_token:
        raise OutlookOAuthError('Token expirado e refresh_token indisponível. Refaça a conexão OAuth.')

    payload = _refresh_tokens(conn, user_id, refresh_token)
    return payload.get('access_token')


def fetch_messages(access_token: str, start_date: datetime, end_date: datetime, page_size=50, max_pages=10):
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)

    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/json'}

    def collect(folder_name, direction):
        items = []
        select = 'subject,receivedDateTime,sentDateTime,from,toRecipients,bodyPreview,internetMessageId'
        flt = (
            f"receivedDateTime ge {start_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
            f"and receivedDateTime le {end_date.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        params = {
            '$select': select,
            '$orderby': 'receivedDateTime desc',
            '$filter': flt,
            '$top': max(1, min(int(page_size), 200)),
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
                    'body_preview': msg.get('bodyPreview') or '',
                    'message_id': msg.get('internetMessageId') or '',
                })
            next_url = payload.get('@odata.nextLink')
            page += 1
        return items

    inbox = collect('inbox', 'received')
    sent = collect('sentitems', 'sent')
    return inbox + sent
