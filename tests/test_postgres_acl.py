"""ACL/visibilidade (Fase 4) contra PostgreSQL.

Valida que as cláusulas de visibilidade introduzidas na Fase 4 — EXISTS sobre
`shares`, COALESCE(owner_id, (SELECT MIN(id) FROM users)) e o IN-subquery do
admin org-scoped — são traduzidas pelo wrapper SQLite→PG e rodam de fato no
Postgres (o smoke da Fase 2 só exercita o caminho login-off, onde a cláusula é
'1=1'). Roda só no CI com serviço Postgres; pulado localmente sem DATABASE_URL.
"""
import os
import uuid

import pytest

import app as toca

_URL = os.getenv('DATABASE_URL', '')
pytestmark = pytest.mark.skipif(
    not _URL.startswith(('postgres://', 'postgresql://')),
    reason='DATABASE_URL PostgreSQL ausente (roda só no CI com serviço Postgres)',
)


@pytest.fixture(scope='module')
def client():
    toca.app.config['TESTING'] = True
    toca.app.config['SESSION_COOKIE_SECURE'] = False
    with toca.app.test_client() as c:
        yield c


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES (?)", (f'OrgACL-{uuid.uuid4().hex[:8]}',))
    org_id = c.lastrowid

    def _mk(role):
        email = f'{role}-{uuid.uuid4().hex[:10]}@ex.com'
        c.execute("INSERT INTO users (org_id, email, full_name, role) VALUES (?, ?, ?, ?)",
                  (org_id, email, email, role))
        return c.lastrowid

    admin_id, a_id, b_id = _mk('admin'), _mk('member'), _mk('member')
    conn.commit(); conn.close()
    return org_id, admin_id, a_id, b_id


def _new_client(owner_id, name):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO clients (name, company, position, owner_id) VALUES (?, ?, ?, ?)",
              (name, 'CoACL', 'Cargo', owner_id))
    cid = c.lastrowid
    conn.commit(); conn.close()
    return cid


def _share(record_type, record_id, user_id, permission='read'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO shares (record_type, record_id, shared_with_user_id, permission) "
              "VALUES (?, ?, ?, ?)", (record_type, record_id, user_id, permission))
    conn.commit(); conn.close()


def test_pg_member_visibility_and_shares(client, monkeypatch):
    """Exercita EXISTS(shares) + COALESCE owner no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    own = _new_client(a_id, f'own-{tag}')
    shared = _new_client(b_id, f'shared-{tag}')
    hidden = _new_client(b_id, f'hidden-{tag}')
    _share('clients', shared, a_id, 'read')

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.get('/api/clients')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    names = {c['name'] for c in r.get_json()}
    assert f'own-{tag}' in names            # dono
    assert f'shared-{tag}' in names         # compartilhado (read)
    assert f'hidden-{tag}' not in names     # de outro dono, sem share


def test_pg_admin_org_scope(client, monkeypatch):
    """Exercita o IN-subquery org-scoped do admin no Postgres."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    _new_client(a_id, f'adm-a-{tag}')
    _new_client(b_id, f'adm-b-{tag}')

    with client.session_transaction() as s:
        s['user_id'] = admin_id
    r = client.get('/api/clients')
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    names = {c['name'] for c in r.get_json()}
    assert f'adm-a-{tag}' in names and f'adm-b-{tag}' in names


def test_pg_write_guard(client, monkeypatch):
    """can_write no Postgres: escrita em registro de outro dono é negada."""
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    tag = uuid.uuid4().hex[:8]
    cb = _new_client(b_id, f'wg-{tag}')

    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.put(f'/api/clients/{cb}', data={'name': 'X', 'company': 'Y', 'position': 'Z'})
    assert r.status_code == 404  # nem visível → 404 (sem vazar existência)


def test_pg_create_sets_owner(client, monkeypatch):
    monkeypatch.setenv('TOCA_AUTH_ENABLED', '1')
    _, admin_id, a_id, b_id = _seed_org_and_users()
    with client.session_transaction() as s:
        s['user_id'] = a_id
    r = client.post('/api/clients', data={'name': f'c-{uuid.uuid4().hex[:8]}',
                                          'company': 'Co', 'position': 'P'})
    assert r.status_code == 201, r.get_data(as_text=True)[:300]
    conn = toca.get_db(); c = conn.cursor()
    c.execute('SELECT owner_id FROM clients WHERE id = ?', (r.get_json()['id'],))
    owner = c.fetchone()['owner_id']; conn.close()
    assert owner == a_id
