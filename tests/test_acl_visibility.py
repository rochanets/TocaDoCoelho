# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.1): camada de ACL/visibilidade aplicada a clients e accounts.

Garante:
  - REGRA DE OURO: com TOCA_AUTH_ENABLED desligado (desktop/SQLite), a camada é
    no-op — visible_where devolve '1=1', can_* devolve True e o fundador enxerga
    tudo, exatamente como o mono-usuário de sempre.
  - Login ligado: modelo privado-por-dono — o membro vê/edita só o que é seu;
    `shares` concede leitura ('read') e escrita ('write'); o admin enxerga a
    organização inteira.
  - INSERTs de entidades-raiz gravam owner_id = usuário atual.

Roda em SQLite (pytest) e o essencial é replicado em tests/test_postgres_acl.py.
"""

import app as toca


# ── Helpers de seed ─────────────────────────────────────────────────────────

def _seed_org_and_users():
    """Org + fundador(admin) + dois membros. Retorna (org_id, admin_id, a, b).
    O fundador é o menor id em users (fallback do login desligado)."""
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Teste ACL')")
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


def _new_client(owner_id, name='C', company='Co', position='P'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, ?, ?)",
              (name, company, position, owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _new_account(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO accounts (name, owner_id) VALUES (?, ?)", (name, owner_id))
    aid = c.lastrowid
    conn.commit(); conn.close()
    return aid


def _share(record_type, record_id, user_id, permission='read'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO shares (record_type, record_id, shared_with_user_id, permission) "
              "VALUES (?, ?, ?, ?)", (record_type, record_id, user_id, permission))
    conn.commit(); conn.close()


def _auth_on(monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    # Test client roda em http; o cookie Secure não voltaria — desliga p/ o teste.
    monkeypatch.setitem(toca.app.config, 'SESSION_COOKIE_SECURE', False)


def _auth_off(monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


def _owner_of(table, row_id):
    conn = toca.get_db(); c = conn.cursor()
    c.execute(f'SELECT owner_id FROM {table} WHERE id = ?', (row_id,))
    row = c.fetchone(); conn.close()
    return row['owner_id'] if row else None


# ── visible_where / can_* diretos ───────────────────────────────────────────

def test_visible_where_noop_when_auth_off(db_path, monkeypatch):
    _auth_off(monkeypatch)
    with toca.app.test_request_context('/'):
        where, params = toca.visible_where('clients')
    assert where == '1=1' and params == []


def test_visible_where_unknown_record_type_raises(db_path, monkeypatch):
    _auth_off(monkeypatch)
    with toca.app.test_request_context('/'):
        try:
            toca.visible_where('nao_existe')
            assert False, 'deveria levantar ValueError'
        except ValueError:
            pass


def test_can_read_write_true_when_auth_off(client, monkeypatch):
    _auth_off(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    with toca.app.test_request_context('/'):
        assert toca.can_read('clients', cb) is True
        assert toca.can_write('clients', cb) is True


def test_read_share_allows_read_but_not_write(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _share('clients', cb, a_id, 'read')  # só leitura
    _login(client, a_id)
    assert client.get(f'/api/clients/{cb}').status_code == 200          # lê via share 'read'
    r_write = client.put(f'/api/clients/{cb}', data={'name': 'X', 'company': 'Y', 'position': 'Z'})
    assert r_write.status_code == 403                                    # mas não escreve


# ── clients: listagem / detalhe ─────────────────────────────────────────────

def test_founder_sees_all_when_auth_off(client, monkeypatch):
    _auth_off(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_client(a_id, name='CA'); _new_client(b_id, name='CB')
    r = client.get('/api/clients')
    assert r.status_code == 200
    names = {c['name'] for c in r.get_json()}
    assert {'CA', 'CB'} <= names


def test_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_client(a_id, name='CA'); _new_client(b_id, name='CB')
    _login(client, a_id)
    names = {c['name'] for c in client.get('/api/clients').get_json()}
    assert 'CA' in names and 'CB' not in names


def test_member_sees_shared(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_client(a_id, name='CA')
    cb = _new_client(b_id, name='CB')
    _share('clients', cb, a_id, 'read')
    _login(client, a_id)
    names = {c['name'] for c in client.get('/api/clients').get_json()}
    assert {'CA', 'CB'} <= names


def test_member_detail_of_others_is_404(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _login(client, a_id)
    assert client.get(f'/api/clients/{cb}').status_code == 404


def test_admin_sees_all_in_org(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_client(a_id, name='CA'); _new_client(b_id, name='CB')
    _login(client, admin_id)
    names = {c['name'] for c in client.get('/api/clients').get_json()}
    assert {'CA', 'CB'} <= names


# ── clients: escrita (owner + guards) ───────────────────────────────────────

def test_create_client_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = client.post('/api/clients', data={'name': 'New', 'company': 'NewCo', 'position': 'Eng'})
    assert r.status_code == 201, r.get_json()
    assert _owner_of('clients', r.get_json()['id']) == a_id


def test_update_others_client_is_404(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _login(client, a_id)
    r = client.put(f'/api/clients/{cb}', data={'name': 'X', 'company': 'Y', 'position': 'Z'})
    assert r.status_code == 404  # nem sabe que existe


def test_update_write_shared_client_ok(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _share('clients', cb, a_id, 'write')
    _login(client, a_id)
    r = client.put(f'/api/clients/{cb}', data={'name': 'X', 'company': 'Y', 'position': 'Z'})
    assert r.status_code == 200


def test_delete_others_client_is_404(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _login(client, a_id)
    assert client.delete(f'/api/clients/{cb}').status_code == 404
    # ainda existe (não foi apagado)
    assert _owner_of('clients', cb) == b_id


def test_admin_can_delete_any(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    cb = _new_client(b_id, name='CB')
    _login(client, admin_id)
    assert client.delete(f'/api/clients/{cb}').status_code == 200


# ── accounts ────────────────────────────────────────────────────────────────

def test_accounts_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_account(a_id, 'AccA'); _new_account(b_id, 'AccB')
    _login(client, a_id)
    names = {a['name'] for a in client.get('/api/accounts').get_json()}
    assert 'AccA' in names and 'AccB' not in names


def test_accounts_detail_of_others_is_404(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ab = _new_account(b_id, 'AccB')
    _login(client, a_id)
    assert client.get(f'/api/accounts/{ab}').status_code == 404


def test_accounts_create_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = client.post('/api/accounts', data={'name': 'MinhaConta'})
    assert r.status_code == 201, r.get_json()
    assert _owner_of('accounts', r.get_json()['id']) == a_id


def test_accounts_presence_on_others_is_blocked(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    ab = _new_account(b_id, 'AccB')
    _login(client, a_id)
    r = client.post(f'/api/accounts/{ab}/presences', json={'delivery_name': 'Entrega X'})
    assert r.status_code in (403, 404)  # conta não visível → 404


def test_accounts_presence_owner_ok(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    aa = _new_account(a_id, 'AccA')
    _login(client, a_id)
    r = client.post(f'/api/accounts/{aa}/presences', json={'delivery_name': 'Entrega X'})
    assert r.status_code == 201, r.get_json()


def test_accounts_founder_sees_all_when_auth_off(client, monkeypatch):
    _auth_off(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_account(a_id, 'AccA'); _new_account(b_id, 'AccB')
    names = {a['name'] for a in client.get('/api/accounts').get_json()}
    assert {'AccA', 'AccB'} <= names
