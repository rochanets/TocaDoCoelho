# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.4): ACL nos briefings pré-reunião (Bloco 13).

meeting_briefings é FILHA de commitments — a visibilidade do briefing herda a do
compromisso. As rotas de ver/gerar são guardadas por can_read(commitment). O
contexto do briefing (atividades, cards de Kanban) é escopado ao usuário
autorizado, resolvido via owned_where(user=...) mesmo em thread de background.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Brief')")
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


def _new_client(owner_id, name='C'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, 'Co', 'P', ?)",
              (name, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _new_commitment(owner_id, client_id, due_date='2026-08-01'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO commitments (client_id, title, notes, due_date, source_type, owner_id) "
              "VALUES (?, 'R', 'R', ?, 'manual', ?)", (client_id, due_date, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _seed_briefing(commitment_id, content='briefing'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO meeting_briefings (commitment_id, content_md, generated_at) "
              "VALUES (?, ?, CURRENT_TIMESTAMP)", (commitment_id, content))
    bid = c.lastrowid
    conn.commit(); conn.close()
    return bid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── meeting_briefings como filha de commitments ─────────────────────────────

def test_meeting_briefings_child_acl(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id)
    comm_a = _new_commitment(a_id, ca)
    bid = _seed_briefing(comm_a, 'x')
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.can_read('meeting_briefings', bid) is True
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.can_read('meeting_briefings', bid) is False


def test_owned_where_accepts_explicit_user(db_path, monkeypatch):
    # usado pela thread do briefing (sem request): resolve pelo user passado
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    where, params = toca.owned_where('kanban_cards', user={'id': a_id, 'role': 'member', 'org_id': 1})
    assert params == [a_id] and 'EXISTS' in where   # não caiu no '1=0' de "sem usuário"


# ── rotas de briefing guardadas pelo compromisso ────────────────────────────

def test_briefing_get_filtered(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id); cb = _new_client(b_id)
    comm_a = _new_commitment(a_id, ca); comm_b = _new_commitment(b_id, cb)
    _seed_briefing(comm_a, 'A'); _seed_briefing(comm_b, 'B')
    _login(client, a_id)
    assert client.get(f'/api/commitments/{comm_a}/briefing').status_code == 200
    assert client.get(f'/api/commitments/{comm_b}/briefing').status_code == 404


def test_briefing_generate_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _new_client(a_id); cb = _new_client(b_id)
    comm_a = _new_commitment(a_id, ca); comm_b = _new_commitment(b_id, cb)
    _login(client, a_id)
    # compromisso de outro dono → 404 antes de qualquer processamento
    assert client.post(f'/api/commitments/{comm_b}/briefing').status_code == 404
    # próprio → 202 (task assíncrona; geração real depende de LLM, fora do teste)
    assert client.post(f'/api/commitments/{comm_a}/briefing').status_code == 202


def test_admin_reads_any_briefing(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id)
    comm_b = _new_commitment(b_id, cb)
    _seed_briefing(comm_b, 'B')
    _login(client, admin_id)
    assert client.get(f'/api/commitments/{comm_b}/briefing').status_code == 200


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_briefing_visible(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id)
    comm_b = _new_commitment(b_id, cb)
    _seed_briefing(comm_b, 'B')
    # login off → tudo visível ao fundador (no-op)
    assert client.get(f'/api/commitments/{comm_b}/briefing').status_code == 200
