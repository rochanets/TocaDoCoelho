# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.8c): ACL na busca RAG do iToca (/ask).

O contexto que vai ao LLM (snapshot + busca ao vivo + contas target) é filtrado
por visibilidade — o usuário só "conversa" sobre o que ELE vê no CRM (owner /
share / admin-org). O painel analítico (stats) tem os COUNTs escopados na
origem. Como a busca roda em thread de fundo, o usuário é capturado no request e
repassado. Login off → tudo (desktop).
"""

import app as toca


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org RAG')")
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
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, 'Co', 'C', ?)", (name, owner_id))
    cid = c.lastrowid; conn.commit(); conn.close()
    return cid


def _seed_account(owner_id, name, is_target=0):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, is_target, owner_id) VALUES (?, ?, ?)", (name, is_target, owner_id))
    aid = c.lastrowid; conn.commit(); conn.close()
    return aid


def _udict(user_id, org_id, role='member'):
    return {'id': user_id, 'org_id': org_id, 'role': role}


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')


# ── can_read com user explícito (thread) ────────────────────────────────────

def test_can_read_with_explicit_user(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CA'); cb = _seed_client(b_id, 'CB')
    a = _udict(a_id, org_id)
    assert toca.can_read('clients', ca, user=a) is True
    assert toca.can_read('clients', cb, user=a) is False


# ── filtro de linhas do RAG ─────────────────────────────────────────────────

def test_filter_visible_rows(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CA'); cb = _seed_client(b_id, 'CB')
    rows = [
        {'table': 'clients', 'id': ca, 'snippet': 'A'},
        {'table': 'clients', 'id': cb, 'snippet': 'B'},
        {'table': 'account_sectors', 'id': 1, 'snippet': 'catálogo'},   # fora do ACL
        {'table': 'user_profile', 'id': None, 'snippet': 'painel'},      # agregado sintético
    ]
    out = toca._itoca_filter_visible_rows(rows, _udict(a_id, org_id))
    keys = {(r['table'], r.get('id')) for r in out}
    assert ('clients', ca) in keys            # dono
    assert ('clients', cb) not in keys        # de outro dono — filtrado
    assert ('account_sectors', 1) in keys     # catálogo — passa
    assert ('user_profile', None) in keys     # sintético (tabela fora do ACL) — passa


def test_filter_auth_off_keeps_all(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CA'); cb = _seed_client(b_id, 'CB')
    rows = [{'table': 'clients', 'id': ca}, {'table': 'clients', 'id': cb}]
    out = toca._itoca_filter_visible_rows(rows, None)
    assert len(out) == 2                       # desktop: mantém tudo


def test_filter_admin_sees_org(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'CA'); cb = _seed_client(b_id, 'CB')
    out = toca._itoca_filter_visible_rows(
        [{'table': 'clients', 'id': ca}, {'table': 'clients', 'id': cb}],
        _udict(admin_id, org_id, role='admin'))
    assert len(out) == 2                       # admin vê a org inteira


# ── /ask (async chamado direto) filtra o contexto do LLM ────────────────────

def _stub_llm(captured):
    def fake(question, context_rows, history_rows=None):
        captured['rows'] = context_rows
        return {'answer': 'ok', 'confidence_percent': 50, 'needs_refinement': False,
                'refinement_hint': '', 'llm_used': False}
    return fake


def test_ask_async_scopes_live_and_snapshot(client, monkeypatch):
    _auth_on(monkeypatch)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    ca = _seed_client(a_id, 'ClienteA'); cb = _seed_client(b_id, 'ClienteB')
    captured = {}
    monkeypatch.setattr(toca, '_itoca_call_sai_llm', _stub_llm(captured))
    monkeypatch.setattr(toca, '_itoca_search_context', lambda q, limit=18: [
        {'table': 'clients', 'id': ca, 'snippet': 'A', 'search_text': 'a'},
        {'table': 'clients', 'id': cb, 'snippet': 'B', 'search_text': 'b'},
    ])
    monkeypatch.setattr(toca, '_itoca_search_in_cached_snapshot', lambda q, items, limit=18: [
        {'table': 'clients', 'id': cb, 'snippet': 'B-snap', 'search_text': 'b'},
    ])
    toca._itoca_ask_async('t1', 'clientes', '', [], 'now', [], owner_id=a_id, user=_udict(a_id, org_id))
    keys = {(r['table'], r.get('id')) for r in captured['rows']}
    assert ('clients', ca) in keys             # visível
    assert ('clients', cb) not in keys         # de B — filtrado do contexto


def test_ask_async_stats_panel_is_scoped(client, monkeypatch):
    """No painel analítico, os COUNTs refletem só o que o usuário vê."""
    _auth_on(monkeypatch)
    org_id, admin_id, a_id, b_id = _seed_org_and_users()
    _seed_account(a_id, 'AccA')                # 1 conta de A
    _seed_account(b_id, 'AccB1'); _seed_account(b_id, 'AccB2')   # 2 de B
    captured = {}
    monkeypatch.setattr(toca, '_itoca_call_sai_llm', _stub_llm(captured))
    monkeypatch.setattr(toca, '_itoca_search_context', lambda q, limit=18: [])
    monkeypatch.setattr(toca, '_itoca_search_in_cached_snapshot', lambda q, items, limit=18: [])
    # pergunta analítica → dispara o painel de stats
    toca._itoca_ask_async('t2', 'resumo geral', '', [], 'now', [], owner_id=a_id, user=_udict(a_id, org_id))
    panel = next((r for r in captured['rows'] if str(r.get('snippet', '')).startswith('PAINEL_GERAL')), None)
    assert panel is not None
    assert 'total_contas: 1' in panel['snippet']    # só a conta de A, não as de B
