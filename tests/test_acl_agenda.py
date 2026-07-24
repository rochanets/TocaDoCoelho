# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.3): ACL na agenda — activities e commitments (raízes) +
account_renewal_events (filha de accounts, na visão unificada da agenda).

Registros de CRM (não é espaço pessoal como o Kanban): usam visible_where /
can_read / can_write — dono + shares + visão-org do admin. Login off = no-op.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Agenda')")
    org_id = c.lastrowid

    def _mk(email, role):
        c.execute("INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
                  (org_id, email, email, role))
        return c.lastrowid

    admin_id = _mk('founder@ex.com', 'admin')
    a_id = _mk('a@ex.com', 'member')
    b_id = _mk('b@ex.com', 'member')
    conn.commit(); conn.close()
    return org_id, admin_id, a_id, b_id


def _new_client(owner_id, name='C', company='Co'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, 'P', ?)",
              (name, company, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _new_activity(owner_id, client_id, info='oi'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO activities (client_id, information, owner_id) VALUES (?, ?, ?)",
              (client_id, info, owner_id))
    aid = c.lastrowid
    conn.commit(); conn.close()
    return aid


def _new_commitment(owner_id, client_id, due_date='2026-08-01', title='Reunião'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, ?, ?, ?, 'manual', ?)", (client_id, title, title, due_date, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _new_renewal(owner_id, due_date='2026-08-02', name='AccR'):
    """Conta (dona=owner) + presença + evento de renovação (filho de accounts)."""
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (name, owner_id))
    acc = c.lastrowid
    c.execute("INSERT INTO account_presences (account_id, delivery_name) VALUES (?, 'D')", (acc,))
    pres = c.lastrowid
    c.execute("INSERT INTO account_renewal_events (account_id, presence_id, title, due_date) "
              "VALUES (?, ?, 'Renovação', ?)", (acc, pres, due_date))
    ev = c.lastrowid
    conn.commit(); conn.close()
    return acc, ev


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _owner_of(table, row_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute(f'SELECT owner_id FROM {table} WHERE id = ?', (row_id,))
    row = c.fetchone(); conn.close()
    return row['owner_id'] if row else None


# ── activities ──────────────────────────────────────────────────────────────

def test_activities_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id, 'CA'); cb = _new_client(b_id, 'CB')
    _new_activity(a_id, ca, 'A-act'); _new_activity(b_id, cb, 'B-act')
    _login(client, a_id)
    infos = {a['information'] for a in client.get('/api/activities').get_json()}
    assert 'A-act' in infos and 'B-act' not in infos


def test_create_activity_sets_owner_and_guards_client(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id, 'CA'); cb = _new_client(b_id, 'CB')
    _login(client, a_id)
    # cria na própria conta → owner = A
    r = client.post('/api/activities', json={'client_id': ca, 'description': 'nova'})
    assert r.status_code == 201, r.get_json()
    assert _owner_of('activities', r.get_json()['id']) == a_id
    # não cria atividade num cliente que não enxerga
    r2 = client.post('/api/activities', json={'client_id': cb, 'description': 'invasao'})
    assert r2.status_code == 404


def test_cannot_edit_or_delete_others_activity(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, 'CB')
    act_b = _new_activity(b_id, cb)
    _login(client, a_id)
    # o PUT de atividade é a rota em PT (/api/atividades/<id>); o DELETE existe nas duas
    assert client.put(f'/api/atividades/{act_b}', json={'information': 'x'}).status_code == 404
    assert client.delete(f'/api/activities/{act_b}').status_code == 404


# ── commitments / agenda ────────────────────────────────────────────────────

def test_agenda_commitments_filtered(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id, 'CA'); cb = _new_client(b_id, 'CB')
    _new_commitment(a_id, ca, title='CompA'); _new_commitment(b_id, cb, title='CompB')
    _login(client, a_id)
    titles = {i['title'] for i in client.get('/api/agenda').get_json()}
    assert 'CompA' in titles and 'CompB' not in titles


def test_agenda_renewal_events_filtered(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_renewal(a_id, name='RenA'); _new_renewal(b_id, name='RenB')
    _login(client, a_id)
    # o item de renovação aparece como client_company = nome da conta
    companies = {i.get('client_company') for i in client.get('/api/agenda').get_json()}
    assert 'RenA' in companies and 'RenB' not in companies


def test_commitment_write_guard(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, 'CB')
    comm_b = _new_commitment(b_id, cb)
    _login(client, a_id)
    assert client.delete(f'/api/agenda/{comm_b}').status_code == 404
    assert client.put(f'/api/agenda/{comm_b}/time', json={'due_time': '10:00'}).status_code == 404


def test_admin_sees_all_commitments(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id, 'CA'); cb = _new_client(b_id, 'CB')
    _new_commitment(a_id, ca, title='CompA'); _new_commitment(b_id, cb, title='CompB')
    _login(client, admin_id)
    titles = {i['title'] for i in client.get('/api/agenda').get_json()}
    assert {'CompA', 'CompB'} <= titles


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_sees_all_activities(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id, 'CA'); cb = _new_client(b_id, 'CB')
    _new_activity(a_id, ca, 'A-act'); _new_activity(b_id, cb, 'B-act')
    infos = {a['information'] for a in client.get('/api/activities').get_json()}
    assert {'A-act', 'B-act'} <= infos
