# -*- coding: utf-8 -*-
"""Fase 5: write-gating administrativo sem bloquear leituras/pessoal."""

import app as toca


def _seed_users():
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES ('Org F5 Permissões')")
    org_id = cur.lastrowid

    def create(email, role):
        cur.execute(
            "INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
            (org_id, email, email, role),
        )
        return cur.lastrowid

    admin_id = create('admin-f5@corp.com', 'admin')
    member_id = create('member-f5@corp.com', 'member')
    conn.commit()
    conn.close()
    return admin_id, member_id


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def test_member_is_forbidden_from_global_and_administrative_writes(client, monkeypatch):
    _auth_on(monkeypatch)
    _, member_id = _seed_users()
    _login(client, member_id)

    requests = [
        ('put', '/api/config/status/universal', {'green_days': 7, 'yellow_days': 14}),
        ('post', '/api/config/position-groupings', {'name': 'Gestão', 'positions': ['A', 'B']}),
        ('post', '/api/config/status/rules', {'position': 'CEO', 'green_days': 7, 'yellow_days': 14}),
        ('put', '/api/config/integrations', {}),
        ('put', '/api/config/update-source', {}),
        ('post', '/api/config/snooze-update', {}),
        ('post', '/api/config/download-update', {}),
        ('post', '/api/config/install-update', {}),
        ('put', '/api/whatsapp/config', {}),
        ('post', '/api/outlook/graph-config', {}),
        ('post', '/api/itoca/base-update', {}),
        ('post', '/api/environment/cards', {'title': 'Global'}),
        ('put', '/api/environment/cards/1', {'title': 'Global'}),
        ('delete', '/api/environment/cards/1', {}),
        ('post', '/api/restore/database', {}),
    ]
    for method, url, payload in requests:
        response = getattr(client, method)(url, json=payload)
        assert response.status_code == 403, (method, url, response.get_data(as_text=True))
        assert response.get_json()['error_type'] == 'forbidden'

    backup = client.get('/api/backup/database')
    assert backup.status_code == 403
    assert backup.get_json()['error_type'] == 'forbidden'


def test_member_keeps_config_reads_and_personal_writes(client, monkeypatch):
    _auth_on(monkeypatch)
    _, member_id = _seed_users()
    _login(client, member_id)

    for url in (
        '/api/config/status',
        '/api/config/integrations',
        '/api/config/update-source',
        '/api/whatsapp/config',
        '/api/outlook/graph-config',
        '/api/environment/cards',
        '/api/config/profile',
        '/api/config/theme',
    ):
        response = client.get(url)
        assert response.status_code == 200, (url, response.get_data(as_text=True))

    theme = client.put('/api/config/theme', json={'theme': 'baby-pink'})
    assert theme.status_code == 200
    assert theme.get_json()['theme'] == 'baby-pink'

    # A credencial Graph é pessoal: cada usuário pode desconectar a própria.
    disconnect = client.delete('/api/outlook/graph-disconnect')
    assert disconnect.status_code == 200


def test_admin_can_write_global_configuration(client, monkeypatch):
    _auth_on(monkeypatch)
    admin_id, _ = _seed_users()
    _login(client, admin_id)

    status = client.put(
        '/api/config/status/universal',
        json={'green_days': 8, 'yellow_days': 16},
    )
    assert status.status_code == 200

    graph = client.post(
        '/api/outlook/graph-config',
        json={'tenant_id': 'tenant-f5', 'client_id': 'client-f5'},
    )
    assert graph.status_code == 200

    whatsapp = client.put(
        '/api/whatsapp/config',
        json={'waha_api_url': 'http://localhost:3001', 'waha_session_name': 'f5'},
    )
    assert whatsapp.status_code == 200

    environment = client.post(
        '/api/environment/cards',
        json={'title': 'Pergunta administrativa', 'description': 'Catálogo global'},
    )
    assert environment.status_code == 201


def test_member_cannot_create_global_environment_card_via_itoca(client, monkeypatch):
    _auth_on(monkeypatch)
    _, member_id = _seed_users()
    _login(client, member_id)

    response = client.post(
        '/api/itoca/execute-action',
        json={
            'action_type': 'environment_mapping',
            'fields': {
                'company': 'Empresa F5',
                'card_title': 'Pergunta criada indiretamente',
                'response': 'Resposta',
            },
        },
    )
    assert response.status_code == 403
    assert response.get_json()['error_type'] == 'forbidden'

    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute(
        'SELECT COUNT(*) AS n FROM environment_cards WHERE title = ?',
        ('Pergunta criada indiretamente',),
    )
    assert cur.fetchone()['n'] == 0
    conn.close()


def test_admin_write_gate_is_noop_on_desktop(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    response = client.put(
        '/api/config/status/universal',
        json={'green_days': 9, 'yellow_days': 18},
    )
    assert response.status_code == 200
