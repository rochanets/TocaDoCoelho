# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.8a): ACL no histórico de chat do iToca (itoca_chat_history).

O histórico é PESSOAL (por-usuário, como o Kanban): owned_where, sem shares e
sem visão-org de admin. Antes a lista de sessões varria a tabela inteira e
vazava as conversas de todos. A migração 16 adicionou owner_id. Cobre a lista
por-dono, o get/delete por sessão escopados (não dá para ler nem apagar a
sessão de outro), o owner_id gravado no /ask e o no-op de login-off.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org iToca')")
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


def _seed_msg(session_id, owner_id, role='user', content='msg'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO itoca_chat_history (session_id, role, content, owner_id) VALUES (?, ?, ?, ?)",
              (session_id, role, content, owner_id))
    conn.commit(); conn.close()


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── migração 16 ─────────────────────────────────────────────────────────────

def test_migration_added_owner_id(client):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("PRAGMA table_info(itoca_chat_history)")
    cols = {row[1] for row in c.fetchall()}
    conn.close()
    assert 'owner_id' in cols


# ── lista de sessões ────────────────────────────────────────────────────────

def test_history_list_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_msg('sA', a_id, 'user', 'pergunta A')
    _seed_msg('sA', a_id, 'assistant', 'resposta A')
    _seed_msg('sB', b_id, 'user', 'pergunta B')
    _login(client, a_id)
    sessions = client.get('/api/itoca/history').get_json()
    ids = {s['session_id'] for s in sessions}
    assert 'sA' in ids and 'sB' not in ids


# ── sessão específica: get + delete escopados ───────────────────────────────

def test_history_session_get_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_msg('sB', b_id, 'user', 'segredo do B')
    _login(client, a_id)
    # A não enxerga as mensagens da sessão de B (200 com lista vazia)
    msgs = client.get('/api/itoca/history/sB').get_json()
    assert msgs == []


def test_history_session_delete_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_msg('sB', b_id, 'user', 'segredo do B')
    _login(client, a_id)
    # A tenta apagar a sessão de B — não deve remover nada
    assert client.delete('/api/itoca/history/sB').status_code == 200
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) AS n FROM itoca_chat_history WHERE session_id='sB'")
    assert c.fetchone()['n'] == 1        # a mensagem de B permanece
    conn.close()
    # e B ainda vê a própria sessão
    _login(client, b_id)
    assert len(client.get('/api/itoca/history/sB').get_json()) == 1


# ── /ask grava o dono na mensagem do usuário ────────────────────────────────

def test_ask_sets_owner_on_user_message(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    # base pronta (evita o 409) e thread de LLM neutralizada
    monkeypatch.setattr(toca, '_itoca_get_cached_base', lambda: (['item'], 'agora'))
    monkeypatch.setattr(toca, '_itoca_ask_async', lambda *a, **k: None)
    _login(client, a_id)
    r = client.post('/api/itoca/ask', json={'question': 'oi', 'session_id': 'sess-A'})
    assert r.status_code == 202, r.get_data(as_text=True)[:200]
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT owner_id FROM itoca_chat_history WHERE session_id='sess-A' AND role='user'")
    assert c.fetchone()['owner_id'] == a_id
    conn.close()


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_history_sees_all(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_msg('sA', a_id, 'user', 'A')
    _seed_msg('sB', b_id, 'user', 'B')
    ids = {s['session_id'] for s in client.get('/api/itoca/history').get_json()}
    assert {'sA', 'sB'} <= ids          # desktop: vê tudo
