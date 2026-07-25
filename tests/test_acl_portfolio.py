# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.6): ACL no Portfólio — portfolio_offers + items (filha) + iata_records.

Modelo privado-por-dono + shares + admin (a UI de compartilhar itens é Fase 5;
o ACL já respeita a tabela shares). portfolio_offer_items herda a visibilidade
da oferta via offer_id. Login off = no-op.
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Portf')")
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


def _new_offer(owner_id, title='Offer'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO portfolio_offers (title, summary, owner_id) VALUES (?, 's', ?)", (title, owner_id))
    oid = c.lastrowid
    c.execute("INSERT INTO portfolio_offer_items (offer_id, pain, solution, sort_order) VALUES (?, 'p', 's', 0)", (oid,))
    item = c.lastrowid
    conn.commit(); conn.close()
    return oid, item


def _new_iata(owner_id, title='Ata'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO iata_records (title, owner_id) VALUES (?, ?)", (title, owner_id))
    rid = c.lastrowid
    conn.commit(); conn.close()
    return rid


def _share(record_type, record_id, user_id, permission='read'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO shares (record_type, record_id, shared_with_user_id, permission) "
              "VALUES (?, ?, ?, ?)", (record_type, record_id, user_id, permission))
    conn.commit(); conn.close()


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


# ── offers ──────────────────────────────────────────────────────────────────

def test_offers_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_offer(a_id, 'OfferA'); _new_offer(b_id, 'OfferB')
    _login(client, a_id)
    titles = {o['title'] for o in client.get('/api/portfolio/offers').get_json()}
    assert 'OfferA' in titles and 'OfferB' not in titles


def test_offer_detail_and_write_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ob, item_b = _new_offer(b_id, 'OfferB')
    _login(client, a_id)
    assert client.get(f'/api/portfolio/offers/{ob}').status_code == 404
    assert client.put(f'/api/portfolio/offers/{ob}', json={'title': 'X'}).status_code == 404
    assert client.delete(f'/api/portfolio/offers/{ob}').status_code == 404


def test_offer_item_guarded_via_parent(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ob, item_b = _new_offer(b_id, 'OfferB')
    _login(client, a_id)
    assert client.post(f'/api/portfolio/offers/{ob}/items', json={'pain': 'p'}).status_code == 404
    assert client.put(f'/api/portfolio/offers/{ob}/items/{item_b}', json={'pain': 'p'}).status_code == 404
    assert client.delete(f'/api/portfolio/offers/{ob}/items/{item_b}').status_code == 404


def test_offer_item_child_acl(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    oa, item_a = _new_offer(a_id, 'OfferA')
    with toca.app.test_request_context('/'):
        from flask import session
        session['user_id'] = a_id; toca._reset_request_user_cache()
        assert toca.can_write('portfolio_offer_items', item_a) is True
        session['user_id'] = b_id; toca._reset_request_user_cache()
        assert toca.can_read('portfolio_offer_items', item_a) is False


def test_offer_read_share_grants_visibility(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ob, item_b = _new_offer(b_id, 'OfferB')
    _share('portfolio_offers', ob, a_id, 'read')
    _login(client, a_id)
    assert client.get(f'/api/portfolio/offers/{ob}').status_code == 200          # via share
    assert client.put(f'/api/portfolio/offers/{ob}', json={'title': 'X'}).status_code == 403  # só leitura


# ── iata ────────────────────────────────────────────────────────────────────

def test_iata_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_iata(a_id, 'AtaA'); _new_iata(b_id, 'AtaB')
    _login(client, a_id)
    titles = {r['title'] for r in client.get('/api/portfolio/iata').get_json()}
    assert 'AtaA' in titles and 'AtaB' not in titles


def test_iata_detail_and_delete_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    rb = _new_iata(b_id, 'AtaB')
    _login(client, a_id)
    assert client.get(f'/api/portfolio/iata/{rb}').status_code == 404
    assert client.delete(f'/api/portfolio/iata/{rb}').status_code == 404


# ── whitespace-matrix filtrado ──────────────────────────────────────────────

def test_whitespace_matrix_offers_filtered(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_offer(a_id, 'OfferA'); _new_offer(b_id, 'OfferB')
    _login(client, a_id)
    r = client.get('/api/portfolio/whitespace-matrix')
    assert r.status_code == 200
    titles = {o['title'] for o in r.get_json()['offers']}
    assert 'OfferA' in titles and 'OfferB' not in titles


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_sees_all_offers(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_offer(a_id, 'OfferA'); _new_offer(b_id, 'OfferB')
    titles = {o['title'] for o in client.get('/api/portfolio/offers').get_json()}
    assert {'OfferA', 'OfferB'} <= titles
