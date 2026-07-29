"""Sessões WAHA privadas por usuário na versão web autenticada."""

import base64

import app as toca


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _seed_users():
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES ('Org WAHA multiusuário')")
    org_id = cur.lastrowid
    user_ids = []
    for suffix in ('a', 'b'):
        cur.execute(
            '''INSERT INTO users
                  (org_id, email, full_name, role, is_active)
               VALUES (?, ?, ?, 'member', 1)''',
            (org_id, f'waha-{suffix}@corp.com', f'Usuário {suffix.upper()}'),
        )
        user_ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return tuple(user_ids)


def _login(client, user_id):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def _seed_client(owner_id, name, phone):
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO clients (name, company, position, phone, owner_id)
           VALUES (?, 'Coelho SA', 'Comercial', ?, ?)''',
        (name, phone, owner_id),
    )
    client_id = cur.lastrowid
    conn.commit()
    conn.close()
    return client_id


class _Response:
    def __init__(self, status_code=200, body=None, content=b'', content_type='image/png'):
        self.status_code = status_code
        self._body = body or {}
        self.content = content
        self.headers = {'Content-Type': content_type}
        self.text = ''
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._body


def test_web_sessions_are_distinct_stable_and_opaque(db_path, monkeypatch):
    _auth_on(monkeypatch)
    user_a, user_b = _seed_users()

    session_a = toca._waha_user_session_name(user_a, create=True)
    session_b = toca._waha_user_session_name(user_b, create=True)

    assert session_a != session_b
    assert session_a == toca._waha_user_session_name(user_a)
    assert session_b == toca._waha_user_session_name(user_b)
    assert session_a.startswith('toca_') and session_b.startswith('toca_')
    assert 'waha-a' not in session_a and 'waha-b' not in session_b
    assert '@' not in session_a and '@' not in session_b


def test_each_member_connects_only_its_own_qr(client, monkeypatch):
    _auth_on(monkeypatch)
    user_a, user_b = _seed_users()
    monkeypatch.setattr(toca.time, 'sleep', lambda _seconds: None)
    seen_created = []
    status_calls = {}

    def fake_get(url, **_kwargs):
        if url.endswith('/auth/qr'):
            return _Response(content=b'private-qr')
        status_calls[url] = status_calls.get(url, 0) + 1
        if status_calls[url] == 1:
            return _Response(status_code=404)
        return _Response(body={'status': 'SCAN_QR_CODE'})

    def fake_post(url, json=None, **_kwargs):
        if url.endswith('/api/sessions/'):
            seen_created.append(json['name'])
        return _Response(status_code=201)

    monkeypatch.setattr(toca.requests, 'get', fake_get)
    monkeypatch.setattr(toca.requests, 'post', fake_post)

    payloads = []
    for user_id in (user_a, user_b):
        _login(client, user_id)
        response = client.post('/api/whatsapp/connect')
        assert response.status_code == 200
        payloads.append(response.get_json())

    assert all(item['qr'].startswith('data:image/png;base64,') for item in payloads)
    assert base64.b64decode(payloads[0]['qr'].split(',', 1)[1]) == b'private-qr'
    conn = toca.get_db()
    rows = conn.execute(
        'SELECT user_id, session_name FROM user_waha_sessions ORDER BY user_id'
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    assert rows[0]['session_name'] != rows[1]['session_name']
    assert seen_created == [row['session_name'] for row in rows]


def test_send_and_daily_quota_are_isolated_by_user(client, monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setenv('WAHA_DAILY_SEND_LIMIT', '1')
    user_a, user_b = _seed_users()
    client_a = _seed_client(user_a, 'Contato A', '11999990001')
    client_b = _seed_client(user_b, 'Contato B', '11999990002')
    session_a = toca._waha_user_session_name(user_a, create=True)
    session_b = toca._waha_user_session_name(user_b, create=True)
    sent_sessions = []

    def fake_post(url, json=None, **_kwargs):
        if url.endswith('/api/sendText'):
            sent_sessions.append(json['session'])
        return _Response(status_code=201)

    monkeypatch.setattr(toca.requests, 'post', fake_post)

    _login(client, user_a)
    first_a = client.post(
        '/api/whatsapp/send',
        json={
            'client_id': client_a,
            'phone': '11999990001',
            'message': 'Mensagem A',
        },
    )
    second_a = client.post(
        '/api/whatsapp/send',
        json={
            'client_id': client_a,
            'phone': '11999990001',
            'message': 'Mensagem A novamente',
        },
    )
    _login(client, user_b)
    first_b = client.post(
        '/api/whatsapp/send',
        json={
            'client_id': client_b,
            'phone': '11999990002',
            'message': 'Mensagem B',
        },
    )

    assert first_a.status_code == 200
    assert second_a.status_code == 429
    assert first_b.status_code == 200
    assert sent_sessions == [session_a, session_b]
    conn = toca.get_db()
    owners = [
        row['owner_id']
        for row in conn.execute(
            "SELECT owner_id FROM whatsapp_sends WHERE status = 'sent' ORDER BY id"
        ).fetchall()
    ]
    conn.close()
    assert owners == [user_a, user_b]


def test_webhook_routes_message_to_session_owner_only(client, monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setattr(toca, '_waha_webhook_is_authorized', lambda *_args: True)
    user_a, user_b = _seed_users()
    client_a = _seed_client(user_a, 'Contato privado A', '11988880000')
    _seed_client(user_b, 'Contato privado B', '11988880000')
    session_a = toca._waha_user_session_name(user_a, create=True)

    response = client.post(
        '/api/whatsapp/webhook',
        json={
            'event': 'message.any',
            'session': session_a,
            'payload': {
                'from': '5511988880000@c.us',
                'fromMe': False,
                'body': 'Somente para A',
                'timestamp': 1750000000,
                'id': 'msg-private-a',
            },
        },
    )
    unknown = client.post(
        '/api/whatsapp/webhook',
        json={
            'event': 'message.any',
            'session': 'sessao-nao-mapeada',
            'payload': {
                'from': '5511988880000@c.us',
                'fromMe': False,
                'body': 'Ignorar',
                'timestamp': 1750000001,
            },
        },
    )

    assert response.status_code == 200
    assert unknown.get_json()['ignored'] == 'sessao_desconhecida'
    conn = toca.get_db()
    rows = conn.execute(
        'SELECT client_id, owner_id, preview FROM inbound_messages'
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]['client_id'] == client_a
    assert rows[0]['owner_id'] == user_a
    assert rows[0]['preview'] == 'Somente para A'


def test_disconnect_removes_only_current_user_session(client, monkeypatch):
    _auth_on(monkeypatch)
    user_a, user_b = _seed_users()
    session_a = toca._waha_user_session_name(user_a, create=True)
    session_b = toca._waha_user_session_name(user_b, create=True)
    logged_out = []

    def fake_post(url, **_kwargs):
        logged_out.append(url)
        return _Response(status_code=200)

    monkeypatch.setattr(toca.requests, 'post', fake_post)
    _login(client, user_a)
    response = client.post('/api/whatsapp/disconnect')

    assert response.status_code == 200
    assert response.get_json()['disconnected'] is True
    assert logged_out == [
        f'http://localhost:3001/api/sessions/{session_a}/logout'
    ]
    assert toca._waha_user_session_name(user_a) is None
    assert toca._waha_user_session_name(user_b) == session_b


def test_admin_deactivation_logs_out_only_deactivated_user(client, monkeypatch):
    _auth_on(monkeypatch)
    admin_id, member_id = _seed_users()
    conn = toca.get_db()
    conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()
    admin_session = toca._waha_user_session_name(admin_id, create=True)
    member_session = toca._waha_user_session_name(member_id, create=True)
    logged_out = []

    def fake_post(url, **_kwargs):
        logged_out.append(url)
        return _Response(status_code=200)

    monkeypatch.setattr(toca.requests, 'post', fake_post)
    _login(client, admin_id)
    response = client.delete(f'/api/admin/users/{member_id}', json={})

    assert response.status_code == 204
    assert logged_out == [
        f'http://localhost:3001/api/sessions/{member_session}/logout'
    ]
    assert toca._waha_user_session_name(admin_id) == admin_session
    assert toca._waha_user_session_name(member_id) is None


def test_desktop_keeps_legacy_single_session(db_path, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '0')
    conn = toca.get_db()
    conn.execute(
        "UPDATE app_settings SET value = 'desktop-default' "
        "WHERE key = 'waha_session_name'"
    )
    conn.commit()
    conn.close()

    assert toca._waha_settings() == (
        'http://localhost:3001',
        '',
        'desktop-default',
    )
