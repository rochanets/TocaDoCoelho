# -*- coding: utf-8 -*-
"""Cobertura da estabilização multiusuário da Fase 4.5."""

import app as toca


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _users():
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org F45')")
    org_id = c.lastrowid
    ids = []
    for email in ('a@empresa.test', 'b@empresa.test'):
        c.execute(
            """INSERT INTO users
               (org_id, email, full_name, nickname, position, phone, photo_url, role)
               VALUES (?, ?, ?, 'Inicial', 'Cargo', '11999999999', '/uploads/avatar.jpg', 'member')""",
            (org_id, email, email)
        )
        ids.append(c.lastrowid)
    conn.commit()
    conn.close()
    return ids


def test_profile_and_theme_are_personal_and_sso_email_is_immutable(client, monkeypatch):
    _auth_on(monkeypatch)
    a_id, b_id = _users()

    _login(client, a_id)
    response = client.post('/api/config/profile', data={
        'full_name': 'Usuário A',
        'nickname': 'A',
        'position': 'Executivo',
        'phone': '(11) 98888-7777',
        'boss_name': 'Chefe A',
        'boss_email': 'chefe-a@empresa.test',
        'email': 'tentativa-de-troca@empresa.test',
    })
    assert response.status_code == 200, response.get_json()
    assert client.put('/api/config/theme', json={'theme': 'blue-space'}).status_code == 200

    profile_a = client.get('/api/config/profile').get_json()
    assert profile_a['full_name'] == 'Usuário A'
    assert profile_a['boss_name'] == 'Chefe A'
    assert profile_a['email'] == 'a@empresa.test'
    assert client.get('/api/config/theme').get_json()['theme'] == 'blue-space'

    _login(client, b_id)
    profile_b = client.get('/api/config/profile').get_json()
    assert profile_b['full_name'] == 'b@empresa.test'
    assert profile_b['boss_name'] is None
    assert client.get('/api/config/theme').get_json()['theme'] == 'verde-classico'


def test_personal_histories_are_not_visible_to_another_member(client, monkeypatch):
    _auth_on(monkeypatch)
    a_id, b_id = _users()
    conn = toca.get_db()
    c = conn.cursor()
    c.execute(
        """INSERT INTO automapping_runs
           (company, country, industry, query_key, result_json, owner_id)
           VALUES ('Empresa A', 'BR', 'TI', 'a-br-ti', '{}', ?)""",
        (a_id,)
    )
    run_id = c.lastrowid
    c.execute(
        """INSERT INTO chamado_juridico_history
           (conta, payload_json, files_json, owner_id)
           VALUES ('Conta A', '{}', '{}', ?)""",
        (a_id,)
    )
    history_id = c.lastrowid
    conn.commit()
    conn.close()

    _login(client, b_id)
    assert client.get(f'/api/automapping/runs/{run_id}').status_code == 404
    assert client.delete(f'/api/automapping/runs/{run_id}').status_code == 404
    assert client.get('/api/automapping/runs').get_json()['runs'] == []
    assert client.get(f'/api/autotoca/chamado-juridico/history/{history_id}').status_code == 404
    assert client.get('/api/autotoca/chamado-juridico/history').get_json() == []
    assert client.get(
        f'/uploads/autotoca/chamado-juridico/{history_id}/contrato/arquivo.pdf'
    ).status_code == 404


def test_background_task_polling_is_personal(client, monkeypatch):
    _auth_on(monkeypatch)
    a_id, b_id = _users()
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id
        toca._bg_task_set('task-f45', {'status': 'processing'})
    _login(client, a_id)
    assert client.get('/api/tasks/task-f45').status_code == 200

    _login(client, b_id)
    assert client.get('/api/tasks/task-f45').status_code == 404


def test_sqlite_backup_routes_are_closed_on_postgresql(client, monkeypatch):
    monkeypatch.setattr(toca, 'DB_BACKEND', 'postgresql')
    assert client.get('/api/backup/database').status_code == 409
    assert client.post('/api/restore/database').status_code == 409


def test_database_table_names_uses_sqlite_catalog(db_path):
    conn = toca.get_db()
    names = toca._database_table_names(conn.cursor())
    conn.close()
    assert 'users' in names
    assert 'schema_version' in names


def test_weekly_email_uses_explicit_sso_user(monkeypatch, db_path):
    sent = {}
    user = {'id': 42, 'email': 'pessoa@empresa.test', 'role': 'member', 'org_id': 1}
    monkeypatch.setattr(toca, '_weekly_review_data', lambda cursor, acl_user=None: {
        'week_start': '2026-07-20', 'touches': 0, 'cooled': [],
        'followups_created': 0, 'followups_done': 0,
        'pending_suggestions': [], 'next_week_plan': [],
    })
    monkeypatch.setattr(toca, '_briefings_to_pdf', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        toca, '_outlook_send_mail',
        lambda to, subject, body, attachments=None, user_id=None:
            sent.update(to=to, user_id=user_id)
    )
    assert toca._send_weekly_review_for_user(user) is True
    assert sent == {'to': 'pessoa@empresa.test', 'user_id': 42}
