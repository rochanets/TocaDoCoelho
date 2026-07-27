# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.12a): ACL no whatsapp inbound + approve.

inbound_messages é filha de clients (herda a visibilidade do contato). O approve
grava owner_id nas activities/commitments criados e pula contatos não-visíveis.
inbound/pending e /metrics escopados pelo contato; /respond guardado. Login off
→ tudo global (desktop).
"""

from datetime import datetime

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org WA')")
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
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, 'Co', 'C', ?)",
              (name, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_inbound(client_id, responded=False):
    conn = toca.get_db(); c = conn.cursor()
    now = datetime.now().isoformat(timespec='seconds')
    c.execute("INSERT INTO inbound_messages (client_id, channel, received_at, preview, responded_at, source_msg_id) "
              "VALUES (?, 'whatsapp', ?, 'oi', ?, ?)",
              (client_id, now, (now if responded else None), f'src-{client_id}-{now}'))
    iid = c.lastrowid; conn.commit(); conn.close()
    return iid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── inbound/pending ─────────────────────────────────────────────────────────

def test_inbound_pending_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_inbound(ca); _seed_inbound(cb)
    _login(client, a_id)
    rows = client.get('/api/inbound/pending').get_json()
    names = {r['name'] for r in rows}
    assert 'CliA' in names and 'CliB' not in names


def test_inbound_respond_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _seed_client(b_id, 'CliB')
    ib = _seed_inbound(cb)
    _login(client, a_id)
    assert client.post(f'/api/inbound/{ib}/respond').status_code == 404   # de contato de B


# ── approve: owner + pula contato de outro ──────────────────────────────────

def test_approve_sets_owner_and_skips_others(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/whatsapp/approve', json={'items': [
        {'client_id': ca, 'summary': 'conversa A', 'content_hash': 'ha'},
        {'client_id': cb, 'summary': 'conversa B', 'content_hash': 'hb'},   # contato de B → pulado
    ]})
    assert r.status_code == 200
    assert r.get_json()['inserted'] == 1                                    # só a de A
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT client_id, owner_id FROM activities WHERE contact_type='WhatsApp'")
    rows = [toca.dict_from_row(x) for x in c.fetchall()]
    conn.close()
    assert len(rows) == 1 and rows[0]['client_id'] == ca and rows[0]['owner_id'] == a_id


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_inbound_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_inbound(ca); _seed_inbound(cb)
    names = {r['name'] for r in client.get('/api/inbound/pending').get_json()}
    assert 'CliA' in names and 'CliB' in names      # desktop: tudo
