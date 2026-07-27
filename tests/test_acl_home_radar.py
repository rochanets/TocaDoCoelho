# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.9a): ACL no Radar do Dia / sugestões do Home.

O Radar é PESSOAL (por-usuário, como o Kanban): cada um vê sugestões geradas a
partir do que ELE vê (owner/share/admin nas fontes; owned_where no
armazenamento). Migração 17 adicionou owner_id em daily_suggestions;
job_change_events virou filha de clients. Login off → radar único (desktop).
"""

from datetime import datetime

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Radar')")
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


def _seed_client(owner_id, name):
    """Contato nunca contatado (last_activity_date NULL) → gera sugestão no radar."""
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, 'Acme', 'C', ?)",
              (name, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_suggestion(owner_id, title='S'):
    conn = toca.get_db(); c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("""INSERT INTO daily_suggestions
                 (date, suggestion_type, title, description, target_id, target_data, owner_id)
                 VALUES (?, 'test', ?, 'd', 1, '{}', ?)""", (today, title, owner_id))
    sid = c.lastrowid; conn.commit(); conn.close()
    return sid


def _seed_job_change(client_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO job_change_events (client_id, empresa_nova, status) VALUES (?, 'NovaCo', 'pendente')",
              (client_id,))
    jid = c.lastrowid; conn.commit(); conn.close()
    return jid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── migração 17 ─────────────────────────────────────────────────────────────

def test_migration_added_owner_id(client):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("PRAGMA table_info(daily_suggestions)")
    cols = {row[1] for row in c.fetchall()}
    conn.close()
    assert 'owner_id' in cols


# ── radar por-usuário ───────────────────────────────────────────────────────

def test_radar_generated_per_user(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'AliceContact'); _seed_client(b_id, 'BobContact')
    _login(client, a_id)
    titles = ' | '.join(s['title'] for s in client.get('/api/suggestions/today').get_json())
    assert 'AliceContact' in titles and 'BobContact' not in titles


def test_suggestion_complete_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    sb = _seed_suggestion(b_id, 'SB')
    _login(client, a_id)
    assert client.post(f'/api/suggestions/{sb}/complete').status_code == 404   # de B → invisível
    # a de B continua não-concluída
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT completed FROM daily_suggestions WHERE id = ?', (sb,))
    assert toca.dict_from_row(c.fetchone())['completed'] == 0
    conn.close()


def test_suggestion_snooze_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    sb = _seed_suggestion(b_id, 'SB')
    _login(client, a_id)
    assert client.post(f'/api/suggestions/{sb}/snooze', json={'days': 3}).status_code == 404


# ── job_change_events herda a visibilidade do contato ───────────────────────

def test_job_change_child_acl(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'ContatoA')
    ja = _seed_job_change(ca)
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.can_read('job_change_events', ja) is True
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.can_read('job_change_events', ja) is False


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_radar_sees_all(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'AliceContact'); _seed_client(b_id, 'BobContact')
    titles = ' | '.join(s['title'] for s in client.get('/api/suggestions/today').get_json())
    assert 'AliceContact' in titles and 'BobContact' in titles      # desktop: radar único
