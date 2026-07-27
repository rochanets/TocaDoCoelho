# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.12b): ACL no lado de SAÍDA do whatsapp + agendamentos.

- /whatsapp/send e /send-batch só despacham para contatos VISÍVEIS ao usuário e
  gravam owner_id na atividade gerada.
- scheduled_sends (migração 19) é fila PESSOAL: cada usuário vê/gerencia só os
  SEUS agendamentos (owned_where); create grava owner e pula contato não-visível.
Login off → tudo global (desktop, regra de ouro).
"""

from datetime import datetime, timedelta

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org WA out')")
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


def _seed_scheduled(owner_id, client_id, when=None, status='pending', channel='whatsapp'):
    conn = toca.get_db(); c = conn.cursor()
    when = when or (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    c.execute("""INSERT INTO scheduled_sends
                 (channel, client_id, phone, message, scheduled_for, status, owner_id)
                 VALUES (?, ?, '11999990000', 'oi', ?, ?, ?)""",
              (channel, client_id, when, status, owner_id))
    sid = c.lastrowid; conn.commit(); conn.close()
    return sid


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _mock_waha_ok(monkeypatch):
    """Faz o envio WAHA 'suceder' sem rede — para exercitar o registro da atividade."""
    monkeypatch.setattr(toca, '_waha_send_text', lambda chat_id, text: (True, None))


class _ImmediateThread:
    """Thread que roda o alvo já no .start() — torna o despacho em lote síncrono
    e determinístico no teste (sem corrida com a asserção)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        if self._t:
            self._t(*self._a, **self._k)


# ── migração 19 ─────────────────────────────────────────────────────────────

def test_migration_added_owner_id(client):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("PRAGMA table_info(scheduled_sends)")
    cols = {row[1] for row in c.fetchall()}
    conn.close()
    assert 'owner_id' in cols


# ── /whatsapp/send ──────────────────────────────────────────────────────────

def test_send_guards_recipient(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/whatsapp/send',
                    json={'client_id': cb, 'phone': '11999990000', 'message': 'oi'})
    assert r.status_code == 404                                      # contato de B
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) AS n FROM activities")
    assert toca.dict_from_row(c.fetchone())['n'] == 0                # nada registrado
    conn.close()


def test_send_sets_owner_on_activity(client, monkeypatch):
    _auth_on(monkeypatch)
    _mock_waha_ok(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA')
    _login(client, a_id)
    r = client.post('/api/whatsapp/send',
                    json={'client_id': ca, 'phone': '11999990000', 'message': 'oi'})
    assert r.status_code == 200 and r.get_json()['ok']
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT owner_id FROM activities WHERE contact_type='WhatsApp'")
    rows = [toca.dict_from_row(x) for x in c.fetchall()]
    conn.close()
    assert len(rows) == 1 and rows[0]['owner_id'] == a_id


# ── /whatsapp/send-batch ────────────────────────────────────────────────────

def test_send_batch_filters_all_non_visible(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/whatsapp/send-batch', json={'items': [
        {'client_id': cb, 'phone': '11999991111', 'message': 'oi B'},   # só contato de B
    ]})
    assert r.status_code == 400                                     # nada visível na fila


def test_send_batch_keeps_visible_and_threads_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setattr(toca.threading, 'Thread', _ImmediateThread)
    captured = {}

    def _fake_async(task_id, items, imin, imax, owner_id=None):
        captured['items'] = items
        captured['owner_id'] = owner_id

    monkeypatch.setattr(toca, '_whatsapp_batch_send_async', _fake_async)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    r = client.post('/api/whatsapp/send-batch', json={'items': [
        {'client_id': ca, 'phone': '11999990000', 'message': 'oi A'},
        {'client_id': cb, 'phone': '11999991111', 'message': 'oi B'},   # de B → filtrado
        {'phone': '11988887777', 'message': 'avulso'},                  # sem client_id → passa
    ]})
    assert r.status_code == 202
    client_ids = {it.get('client_id') for it in captured['items']}
    assert ca in client_ids and cb not in client_ids
    assert len(captured['items']) == 2                              # A + avulso
    assert captured['owner_id'] == a_id


# ── scheduled_sends: create ─────────────────────────────────────────────────

def test_scheduled_create_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA')
    _login(client, a_id)
    when = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')
    r = client.post('/api/scheduled-sends',
                    json={'client_id': ca, 'channel': 'whatsapp', 'phone': '11999990000',
                          'message': 'agendada', 'scheduled_for': when})
    assert r.status_code == 201
    sid = r.get_json()['ids'][0]
    conn = toca.get_db(); c = conn.cursor()
    c.execute("SELECT owner_id, activity_id FROM scheduled_sends WHERE id = ?", (sid,))
    row = toca.dict_from_row(c.fetchone())
    assert row['owner_id'] == a_id
    c.execute("SELECT owner_id FROM activities WHERE id = ?", (row['activity_id'],))
    assert toca.dict_from_row(c.fetchone())['owner_id'] == a_id       # placeholder herda dono
    conn.close()


def test_scheduled_create_skips_non_visible(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _seed_client(b_id, 'CliB')
    _login(client, a_id)
    when = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M')
    r = client.post('/api/scheduled-sends',
                    json={'client_id': cb, 'channel': 'whatsapp', 'phone': '11999990000',
                          'message': 'agendada', 'scheduled_for': when})
    assert r.status_code == 400                                     # contato de B → nada agendado


# ── scheduled_sends: list / missed ──────────────────────────────────────────

def test_scheduled_list_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_scheduled(a_id, ca); _seed_scheduled(b_id, cb)
    _login(client, a_id)
    rows = client.get('/api/scheduled-sends').get_json()
    owners = {r.get('owner_id') for r in rows}
    assert owners == {a_id}                                         # só os de A


def test_scheduled_missed_scoped(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    past = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
    _seed_scheduled(a_id, ca, when=past); _seed_scheduled(b_id, cb, when=past)
    _login(client, a_id)
    rows = client.get('/api/scheduled-sends/missed').get_json()
    owners = {r.get('owner_id') for r in rows}
    assert owners == {a_id}                                         # só os perdidos de A


# ── scheduled_sends: send-now / cancel ──────────────────────────────────────

def test_send_now_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _seed_client(b_id, 'CliB')
    sid = _seed_scheduled(b_id, cb)
    _login(client, a_id)
    assert client.post(f'/api/scheduled-sends/{sid}/send-now').status_code == 404   # de B


def test_cancel_guarded_and_owned(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    sid_b = _seed_scheduled(b_id, cb)
    _login(client, a_id)
    assert client.post(f'/api/scheduled-sends/{sid_b}/cancel').status_code == 404   # de B
    sid_a = _seed_scheduled(a_id, ca)
    assert client.post(f'/api/scheduled-sends/{sid_a}/cancel').status_code == 200   # dele


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_scheduled_global(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CliA'); cb = _seed_client(b_id, 'CliB')
    _seed_scheduled(a_id, ca); _seed_scheduled(b_id, cb)
    rows = client.get('/api/scheduled-sends').get_json()
    assert len(rows) == 2                                           # desktop: tudo
