# -*- coding: utf-8 -*-
"""Fase 6: sessão SPA, administração segura e diretório de compartilhamento."""

from pathlib import Path

import app as toca


ROOT = Path(__file__).resolve().parents[1]


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _seed_org(name):
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute('INSERT INTO organizations (name) VALUES (?)', (name,))
    org_id = cur.lastrowid
    conn.commit()
    conn.close()
    return org_id


def _seed_user(org_id, email, role='member', active=1):
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO users
              (org_id, email, full_name, role, is_active)
           VALUES (?, ?, ?, ?, ?)''',
        (org_id, email, email.split('@')[0].title(), role, active),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id


def _login(client, user_id):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def test_auth_me_exposes_spa_identity(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id = _seed_org('Org Sessão F6')
    admin_id = _seed_user(org_id, 'admin-f6@corp.com', role='admin')
    _login(client, admin_id)

    response = client.get('/api/auth/me')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['authenticated'] is True
    assert payload['auth_enabled'] is True
    assert payload['user']['id'] == admin_id
    assert payload['user']['role'] == 'admin'


def test_admin_user_list_is_scoped_to_organization(client, monkeypatch):
    _auth_on(monkeypatch)
    own_org = _seed_org('Org Admin F6')
    other_org = _seed_org('Outra Org F6')
    admin_id = _seed_user(own_org, 'admin-list-f6@corp.com', role='admin')
    _seed_user(own_org, 'member-list-f6@corp.com')
    _seed_user(other_org, 'outsider-list-f6@corp.com')
    _login(client, admin_id)

    response = client.get('/api/admin/users')

    assert response.status_code == 200
    emails = {item['email'] for item in response.get_json()['users']}
    assert emails == {'admin-list-f6@corp.com', 'member-list-f6@corp.com'}


def test_last_admin_cannot_be_demoted_or_deactivated(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id = _seed_org('Org Último Admin F6')
    admin_id = _seed_user(org_id, 'last-admin-f6@corp.com', role='admin')
    _login(client, admin_id)

    demote = client.patch(
        f'/api/admin/users/{admin_id}',
        json={'role': 'member', 'confirm_self_change': True},
    )
    deactivate = client.delete(
        f'/api/admin/users/{admin_id}',
        json={'confirm_self_change': True},
    )

    assert demote.status_code == 409
    assert demote.get_json()['error_type'] == 'last_admin'
    assert deactivate.status_code == 409
    assert deactivate.get_json()['error_type'] == 'last_admin'


def test_self_demotion_requires_explicit_confirmation(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id = _seed_org('Org Confirmação F6')
    admin_id = _seed_user(org_id, 'self-admin-f6@corp.com', role='admin')
    _seed_user(org_id, 'backup-admin-f6@corp.com', role='admin')
    _login(client, admin_id)

    denied = client.patch(
        f'/api/admin/users/{admin_id}',
        json={'role': 'member'},
    )
    allowed = client.patch(
        f'/api/admin/users/{admin_id}',
        json={'role': 'member', 'confirm_self_change': True},
    )

    assert denied.status_code == 400
    assert denied.get_json()['error_type'] == 'confirmation_required'
    assert allowed.status_code == 200
    assert allowed.get_json()['role'] == 'member'


def test_deactivation_revokes_session_without_deleting_owned_data(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id = _seed_org('Org Desativação F6')
    admin_id = _seed_user(org_id, 'admin-deactivate-f6@corp.com', role='admin')
    member_id = _seed_user(org_id, 'member-deactivate-f6@corp.com')
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO clients (name, company, position, owner_id)
           VALUES ('Contato preservado', 'Coelho SA', 'Diretoria', ?)''',
        (member_id,),
    )
    record_id = cur.lastrowid
    conn.commit()
    conn.close()

    _login(client, admin_id)
    response = client.delete(f'/api/admin/users/{member_id}', json={})
    assert response.status_code == 204

    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute('SELECT is_active FROM users WHERE id = ?', (member_id,))
    assert cur.fetchone()['is_active'] == 0
    cur.execute('SELECT owner_id FROM clients WHERE id = ?', (record_id,))
    assert cur.fetchone()['owner_id'] == member_id
    conn.close()

    _login(client, member_id)
    me = client.get('/api/auth/me')
    protected = client.get('/api/clients')
    assert me.status_code == 200
    assert me.get_json()['authenticated'] is False
    assert protected.status_code == 401


def test_reprovision_reactivates_without_duplicate_user(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id = _seed_org('Org Reativação F6')
    admin_id = _seed_user(org_id, 'admin-reactivate-f6@corp.com', role='admin')
    inactive_id = _seed_user(
        org_id, 'returning-f6@corp.com', role='member', active=0
    )
    _login(client, admin_id)

    response = client.post(
        '/api/admin/users',
        json={
            'email': 'RETURNING-f6@corp.com',
            'full_name': 'Usuária Retornando',
            'role': 'admin',
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload['id'] == inactive_id
    assert payload['reactivated'] is True
    assert payload['role'] == 'admin'


def test_share_recipient_directory_is_minimal_and_org_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    own_org = _seed_org('Org Diretório F6')
    other_org = _seed_org('Outra Org Diretório F6')
    owner_id = _seed_user(own_org, 'owner-directory-f6@corp.com')
    colleague_id = _seed_user(own_org, 'colleague-directory-f6@corp.com')
    _seed_user(own_org, 'inactive-directory-f6@corp.com', active=0)
    _seed_user(other_org, 'outsider-directory-f6@corp.com')
    _login(client, owner_id)

    response = client.get('/api/shares/users')

    assert response.status_code == 200
    users = response.get_json()['users']
    assert users == [{
        'id': colleague_id,
        'email': 'colleague-directory-f6@corp.com',
        'full_name': 'Colleague-Directory-F6',
        'photo_url': None,
    }]
    assert set(users[0]) == {'id', 'email', 'full_name', 'photo_url'}


def test_spa_shell_declares_session_gate_and_central_multiuser_script(
    client, monkeypatch
):
    _auth_on(monkeypatch)
    shell = client.get('/')
    assert shell.status_code == 200
    html = shell.get_data(as_text=True)
    assert 'class="session-pending"' in html
    assert 'id="sessionGate"' in html
    assert 'class="session-gate-visual"' in html
    assert '/images/login-toca-reference.png' in (
        ROOT / 'public' / 'css' / 'app.css'
    ).read_text(encoding='utf-8')
    assert 'Bem-vindo de volta!' in html
    assert '/js/multiuser.js' in html

    script = (ROOT / 'public' / 'js' / 'multiuser.js').read_text(encoding='utf-8')
    assert "response.status === 401" in script
    assert "response.status === 403" in script
    assert "'kanban_columns'" not in script.split('SHAREABLE_TYPES', 1)[1].split(']);', 1)[0]
