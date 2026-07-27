# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.14c): ACL no stream de revisão do Outlook.

_build_outlook_stream_response casa e-mails e monta a lista de seleção
(all_clients) para a revisão do sync. Roda num gerador SSE SEM contexto de request
e recebe o user_id do dono do mailbox — deve escopar o match e o all_clients aos
contatos VISÍVEIS a esse usuário. Login off → global (desktop, regra de ouro).
"""

import json

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org OutStream')")
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


def _seed_client(owner_id, name, email):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, email, owner_id) "
              "VALUES (?, 'Co', 'C', ?, ?)", (name, email, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _email(sender_email, date='2026-01-15T10:00'):
    return {'subject': 'Assunto', 'date': date, 'direction': 'received',
            'sender': {'email': sender_email, 'name': 'Contato'}, 'recipients': [],
            'body_preview': 'corpo', 'message_id': f'mid-{sender_email}', 'conversation_id': ''}


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _mock_graph(monkeypatch, emails):
    """Mocka o conector Graph (sem rede/OAuth) e injeta a lista de e-mails; o
    gerador SSE precisa rodar via endpoint (stream_with_context exige request)."""
    monkeypatch.setattr(toca, 'outlook_graph_get_valid_access_token', lambda *a, **k: 'faketoken')
    monkeypatch.setattr(toca, '_graph_get_me_email', lambda *a, **k: 'me@myco.com')
    monkeypatch.setattr(toca, 'outlook_graph_fetch_messages', lambda *a, **k: emails)


def _stream_done(client):
    """Consome o SSE do endpoint Graph e devolve o dict do evento phase='done'."""
    resp = client.get('/api/outlook/sync-stream-graph')
    done = None
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith('data: '):
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            if d.get('phase') == 'done':
                done = d
    return done


def test_stream_review_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _mock_graph(monkeypatch, [_email('a@acme.com'), _email('b@beta.com')])
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    _login(client, a_id)
    done = _stream_done(client)
    assert done is not None
    all_names = {cl['name'] for cl in done.get('all_clients', [])}
    assert 'CliA' in all_names and 'CliB' not in all_names          # seleção só com visíveis
    matched = {a['client_name'] for a in done.get('activities', [])}
    assert matched == {'CliA'}                                      # b@beta (de B) não casa


def test_auth_off_stream_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _mock_graph(monkeypatch, [_email('a@acme.com'), _email('b@beta.com')])
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    done = _stream_done(client)
    all_names = {cl['name'] for cl in done.get('all_clients', [])}
    assert {'CliA', 'CliB'} <= all_names                            # desktop: todos
    matched = {a['client_name'] for a in done.get('activities', [])}
    assert matched == {'CliA', 'CliB'}
