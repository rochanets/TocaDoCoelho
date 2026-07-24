# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.2): ACL no Kanban — quadro POR-USUÁRIO + herança pai→filha.

O Kanban é um espaço PESSOAL: cada usuário tem o próprio conjunto de colunas
(semeadas no 1º acesso) e os cards herdam a visibilidade da coluna. O escopo é
`owned_where`/`owns` (estritamente do dono), não `visible_where` — nem o admin
vê o quadro dos outros. Com login desligado, tudo é no-op (desktop igual).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Kanban')")
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


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _columns(client):
    r = client.get('/api/kanban/columns')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _cards(client):
    r = client.get('/api/kanban/cards')
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def _new_card(client, title='Card X', description='desc'):
    r = client.post('/api/kanban/cards', json={'title': title, 'description': description})
    assert r.status_code == 201, r.get_json()
    return r.get_json()['id']


# ── owned_where / owns diretos ──────────────────────────────────────────────

def test_owned_where_noop_when_auth_off(db_path, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    with toca.app.test_request_context('/'):
        assert toca.owned_where('kanban_columns') == ('1=1', [])
        assert toca.owned_where('kanban_cards') == ('1=1', [])  # child também vira no-op


def test_child_visibility_resolves_recursively(client, monkeypatch):
    # kanban_card_activities → kanban_cards → kanban_columns (2 níveis)
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO kanban_columns (title, display_order, owner_id) VALUES ('Col', 1, ?)", (a_id,))
    col = c.lastrowid
    c.execute("INSERT INTO kanban_cards (title, description, column_id) VALUES ('c','',?)", (col,))
    card = c.lastrowid
    c.execute("INSERT INTO kanban_card_activities (card_id, content) VALUES (?, 'act')", (card,))
    act = c.lastrowid
    conn.commit(); conn.close()
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.owns('kanban_card_activities', act) is True
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.owns('kanban_card_activities', act) is False


# ── quadro por-usuário ──────────────────────────────────────────────────────

def test_board_seeded_per_user_on_first_access(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    cols = _columns(client)
    titles = [c['title'] for c in cols]
    assert 'Backlog' in titles and 'Done' in titles
    assert len(cols) == 5  # colunas de sistema semeadas para o usuário


def test_members_have_separate_boards(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    a_ids = {c['id'] for c in _columns(client)}
    _login(client, b_id)
    b_ids = {c['id'] for c in _columns(client)}
    assert a_ids and b_ids and a_ids.isdisjoint(b_ids)  # quadros distintos


def test_cards_are_isolated_between_members(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    _columns(client)  # semeia o quadro de A
    card_a = _new_card(client, title='Só do A')
    # B não vê o card de A
    _login(client, b_id)
    _columns(client)
    assert all(c['id'] != card_a for c in _cards(client))
    # A vê o próprio
    _login(client, a_id)
    assert any(c['id'] == card_a for c in _cards(client))


def test_cannot_edit_others_column(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    a_cols = _columns(client)
    # pega uma coluna editável (não bloqueada) do A
    target = next(c for c in a_cols if not c.get('is_locked'))
    _login(client, b_id)
    _columns(client)
    r = client.put(f"/api/kanban/columns/{target['id']}", json={'title': 'Invadido'})
    assert r.status_code == 404  # nem enxerga a coluna do outro


def test_cannot_touch_others_card(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    _columns(client)
    card_a = _new_card(client)
    _login(client, b_id)
    _columns(client)
    assert client.put(f'/api/kanban/cards/{card_a}',
                      json={'title': 'x', 'description': 'y'}).status_code == 404
    assert client.delete(f'/api/kanban/cards/{card_a}').status_code == 404
    assert client.patch(f'/api/kanban/cards/{card_a}/urgency',
                        json={'urgency': 'Alta'}).status_code == 404


def test_create_card_lands_on_own_board(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    _columns(client)
    card = _new_card(client)
    # o card cai numa coluna do próprio A
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT column_id FROM kanban_cards WHERE id = ?', (card,))
    col_id = c.fetchone()['column_id']
    c.execute('SELECT owner_id FROM kanban_columns WHERE id = ?', (col_id,))
    owner = c.fetchone()['owner_id']; conn.close()
    assert owner == a_id


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_founder_sees_all_columns(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    # coluna de um membro qualquer + a do fundador
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO kanban_columns (title, display_order, owner_id) VALUES ('DoMembro', 9, ?)", (a_id,))
    conn.commit(); conn.close()
    titles = [c['title'] for c in _columns(client)]
    assert 'DoMembro' in titles  # no-op: enxerga tudo com login desligado
