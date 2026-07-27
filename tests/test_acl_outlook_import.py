# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.14b): ACL no import de e-mails do Outlook (owner + escopo).

- _outlook_import_emails (via /api/outlook/import) casa só contra contatos
  VISÍVEIS e grava owner_id na atividade importada (contexto de request).
- _outlook_confirm_async (import em thread de background) recebe owner + user do
  request: grava owner nas activities/commitments e pula contato não-visível.
Login off → tudo global (desktop, regra de ouro).
"""

import io
import json

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org OutImport')")
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


def _seed_client(owner_id, name, email=None):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, email, owner_id) "
              "VALUES (?, 'Co', 'C', ?, ?)", (name, email, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _user_dict(uid):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (uid,))
    row = toca.dict_from_row(c.fetchone()); conn.close()
    return row


def _activities():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT client_id, owner_id FROM activities WHERE contact_type = 'Email'")
    rows = [toca.dict_from_row(x) for x in c.fetchall()]; conn.close()
    return rows


def _email(sender_email, subject='Assunto', date='2026-01-15T10:00'):
    return {'subject': subject, 'date': date, 'direction': 'received',
            'sender': {'email': sender_email, 'name': 'Contato'}, 'recipients': [], 'body_preview': 'corpo'}


def _no_llm(monkeypatch):
    monkeypatch.setattr(toca, '_sai_simple_prompt', lambda *a, **k: None)
    monkeypatch.setattr(toca, '_llm_prompt', lambda *a, **k: None)


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _upload_import(client, emails):
    payload = json.dumps({'emails': emails}).encode('utf-8')
    return client.post('/api/outlook/import',
                       data={'file': (io.BytesIO(payload), 'emails.json')},
                       content_type='multipart/form-data')


# ── _outlook_import_emails (via /api/outlook/import) ────────────────────────

def test_import_scoped_and_owner(client, monkeypatch):
    _auth_on(monkeypatch); _no_llm(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA', 'a@acme.com')
    _seed_client(b_id, 'CliB', 'b@beta.com')
    _login(client, a_id)
    r = _upload_import(client, [_email('a@acme.com'), _email('b@beta.com')])
    assert r.status_code == 200 and r.get_json()['imported'] == 1     # só casa o de A
    acts = _activities()
    assert len(acts) == 1 and acts[0]['client_id'] == ca and acts[0]['owner_id'] == a_id


def test_auth_off_import_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _no_llm(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_client(a_id, 'CliA', 'a@acme.com'); _seed_client(b_id, 'CliB', 'b@beta.com')
    r = _upload_import(client, [_email('a@acme.com'), _email('b@beta.com')])
    assert r.get_json()['imported'] == 2                             # desktop: casa contra todos


# ── _outlook_confirm_async (import em background) ───────────────────────────

def test_confirm_async_owner_and_guard(client, monkeypatch):
    _auth_on(monkeypatch); _no_llm(monkeypatch)
    monkeypatch.setattr(toca, '_outlook_call_llm', lambda *a, **k: None)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    items = [
        {'client_id': ca, 'subject': 'Reunião', 'date': '2026-01-15T10:00', 'counterpart_name': 'X'},
        {'client_id': cb, 'subject': 'Sigilo', 'date': '2026-01-15T11:00', 'counterpart_name': 'Y'},   # de B → pulado
    ]
    # Chamada direta (síncrona) da função de background, com owner+user do request.
    toca._outlook_confirm_async('task-test', items, owner_id=a_id, user=_user_dict(a_id))
    acts = _activities()
    assert len(acts) == 1 and acts[0]['client_id'] == ca and acts[0]['owner_id'] == a_id


def test_detect_followup_commitment_owner(client, monkeypatch):
    # Exercita o INSERT real do follow-up (que antes não gravava owner_id): com o
    # LLM devolvendo um compromisso, ele deve herdar o owner recebido.
    monkeypatch.setattr(toca, '_llm_prompt',
                        lambda *a, **k: '{"followup": {"data": "2026-12-31", "titulo": "Retorno"}}')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA')
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO activities (client_id, contact_type, information) VALUES (?, 'Email', 'x')", (ca,))
    aid = c.lastrowid
    n = toca._detect_followup_from_text(c, ca, aid, 'Contato', 'combinamos um retorno', owner_id=a_id)
    conn.commit()
    assert n == 1
    c.execute("SELECT owner_id FROM commitments WHERE activity_id = ? AND source_type = 'outlook'", (aid,))
    rows = [toca.dict_from_row(x) for x in c.fetchall()]; conn.close()
    assert rows and all(r['owner_id'] == a_id for r in rows)         # compromisso herda o dono
