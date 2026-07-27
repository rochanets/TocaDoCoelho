# -*- coding: utf-8 -*-
"""Fase 5: CRUD de shares, semântica read/write e isolamento por organização."""

import app as toca


def _seed_fixture():
    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO organizations (name) VALUES ('Org F5 Shares')")
    org_id = cur.lastrowid
    cur.execute("INSERT INTO organizations (name) VALUES ('Outra Org F5')")
    other_org_id = cur.lastrowid

    def user(org, email, role='member'):
        cur.execute(
            "INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
            (org, email, email, role),
        )
        return cur.lastrowid

    admin_id = user(org_id, 'admin-shares@corp.com', 'admin')
    owner_id = user(org_id, 'owner-shares@corp.com')
    member_id = user(org_id, 'member-shares@corp.com')
    colleague_id = user(org_id, 'colleague-shares@corp.com')
    other_admin_id = user(other_org_id, 'admin-other@corp.com', 'admin')
    outsider_id = user(other_org_id, 'outsider@corp.com')

    cur.execute(
        "INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, ?, ?)",
        ('Registro compartilhável', 'Coelho SA', 'Diretoria', owner_id),
    )
    record_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        'org': org_id,
        'admin': admin_id,
        'owner': owner_id,
        'member': member_id,
        'colleague': colleague_id,
        'other_admin': other_admin_id,
        'outsider': outsider_id,
        'record': record_id,
    }


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def _create(client, ids, recipient=None, permission='read'):
    return client.post(
        '/api/shares',
        json={
            'record_type': 'clients',
            'record_id': ids['record'],
            'shared_with_user_id': recipient or ids['member'],
            'permission': permission,
        },
    )


def test_owner_crud_changes_read_and_write_access(client, monkeypatch):
    _auth_on(monkeypatch)
    ids = _seed_fixture()
    _login(client, ids['owner'])

    created = _create(client, ids)
    assert created.status_code == 201, created.get_data(as_text=True)
    share = created.get_json()
    assert share['created'] is True
    assert share['created_by'] == ids['owner']
    assert share['permission'] == 'read'

    listed = client.get(
        f"/api/shares?record_type=clients&record_id={ids['record']}"
    )
    assert listed.status_code == 200
    assert [item['id'] for item in listed.get_json()['shares']] == [share['id']]

    _login(client, ids['member'])
    assert client.get(f"/api/clients/{ids['record']}").status_code == 200
    denied_write = client.put(
        f"/api/clients/{ids['record']}",
        data={'name': 'X', 'company': 'Y', 'position': 'Z'},
    )
    assert denied_write.status_code == 403

    _login(client, ids['owner'])
    updated = client.patch(f"/api/shares/{share['id']}", json={'permission': 'write'})
    assert updated.status_code == 200
    assert updated.get_json()['permission'] == 'write'

    _login(client, ids['member'])
    allowed_write = client.put(
        f"/api/clients/{ids['record']}",
        data={'name': 'Editado via share', 'company': 'Y', 'position': 'Z'},
    )
    assert allowed_write.status_code == 200

    _login(client, ids['owner'])
    removed = client.delete(f"/api/shares/{share['id']}")
    assert removed.status_code == 204

    _login(client, ids['member'])
    assert client.get(f"/api/clients/{ids['record']}").status_code == 404


def test_duplicate_create_is_idempotent_and_updates_permission(client, monkeypatch):
    _auth_on(monkeypatch)
    ids = _seed_fixture()
    _login(client, ids['owner'])

    first = _create(client, ids, permission='read')
    second = _create(client, ids, permission='write')
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()['created'] is False
    assert second.get_json()['permission'] == 'write'
    assert second.get_json()['created_by'] == ids['owner']

    conn = toca.get_db()
    cur = conn.cursor()
    cur.execute(
        '''SELECT COUNT(*) AS n, MIN(permission) AS permission
           FROM shares WHERE record_type = 'clients' AND record_id = ?
             AND shared_with_user_id = ?''',
        (ids['record'], ids['member']),
    )
    row = cur.fetchone()
    conn.close()
    assert row['n'] == 1
    assert row['permission'] == 'write'


def test_only_owner_or_same_org_admin_can_manage(client, monkeypatch):
    _auth_on(monkeypatch)
    ids = _seed_fixture()

    _login(client, ids['member'])
    assert _create(client, ids, recipient=ids['colleague']).status_code == 404
    assert client.get(
        f"/api/shares/clients/{ids['record']}"
    ).status_code == 404

    _login(client, ids['admin'])
    by_admin = _create(client, ids, recipient=ids['colleague'])
    assert by_admin.status_code == 201
    assert by_admin.get_json()['created_by'] == ids['admin']

    _login(client, ids['other_admin'])
    assert _create(client, ids, recipient=ids['outsider']).status_code == 404
    assert client.patch(
        f"/api/shares/{by_admin.get_json()['id']}",
        json={'permission': 'write'},
    ).status_code == 404


def test_write_recipient_cannot_reshare_or_remove(client, monkeypatch):
    _auth_on(monkeypatch)
    ids = _seed_fixture()
    _login(client, ids['owner'])
    created = _create(client, ids, permission='write')
    share_id = created.get_json()['id']

    _login(client, ids['member'])
    assert _create(client, ids, recipient=ids['colleague']).status_code == 404
    assert client.delete(f'/api/shares/{share_id}').status_code == 404


def test_cross_org_and_invalid_share_requests_are_rejected(client, monkeypatch):
    _auth_on(monkeypatch)
    ids = _seed_fixture()
    _login(client, ids['owner'])

    cross_org = _create(client, ids, recipient=ids['outsider'])
    assert cross_org.status_code == 400
    assert cross_org.get_json()['error_type'] == 'validation'

    invalid_type = client.post(
        '/api/shares',
        json={
            'record_type': 'users',
            'record_id': ids['record'],
            'shared_with_user_id': ids['member'],
            'permission': 'read',
        },
    )
    assert invalid_type.status_code == 400

    personal_type = client.post(
        '/api/shares',
        json={
            'record_type': 'kanban_columns',
            'record_id': 1,
            'shared_with_user_id': ids['member'],
            'permission': 'read',
        },
    )
    assert personal_type.status_code == 400

    bad_permission = _create(client, ids, permission='admin')
    assert bad_permission.status_code == 400

    self_share = _create(client, ids, recipient=ids['owner'])
    assert self_share.status_code == 400


def test_shares_keep_desktop_auth_off_compatibility(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    ids = _seed_fixture()
    created = _create(client, ids)
    assert created.status_code == 201
    assert client.get(
        f"/api/shares?record_type=clients&record_id={ids['record']}"
    ).status_code == 200
