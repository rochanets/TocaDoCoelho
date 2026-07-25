# -*- coding: utf-8 -*-
"""Fase 4 (PR 4.7): ACL no wikitoca — wiki_entries + wiki_documents.

Ambas são raízes privadas-por-dono (+ shares + admin), mesmo modelo de
clients/accounts/portfolio. A migração de owner_id nessas tabelas já existe
(fundação da Fase 4). Cobre lista (inclusive o ramo de busca `q`, cuja
cláusula OR precisa vir parentetizada para não furar o filtro), guards de
escrita/exclusão, share de leitura, o serviço de arquivo do documento e o
no-op de login-off.
"""

import pytest

import app as toca


@pytest.fixture()
def wiki_dir(tmp_path, monkeypatch):
    """Isola WIKI_UPLOAD_DIR num diretório temporário (não polui o dir real)."""
    d = tmp_path / 'wikitoca'
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(toca, 'WIKI_UPLOAD_DIR', d)
    return d


def _seed_org_and_users():
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO organizations (name) VALUES ('Org Wiki')")
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


def _new_entry(owner_id, title='Conhecimento', content='corpo'):
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO wiki_entries (title, content, category, tags, owner_id) "
              "VALUES (?, ?, 'cat', 'tag', ?)", (title, content, owner_id))
    eid = c.lastrowid
    conn.commit(); conn.close()
    return eid


def _new_document(owner_id, title='Doc', file_name=None):
    file_name = file_name or f'wiki_{owner_id}_{title}.pdf'
    # cria o arquivo físico para o teste de /uploads/wikitoca/<file>
    toca.WIKI_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (toca.WIKI_UPLOAD_DIR / file_name).write_bytes(b'%PDF-1.4 conteudo')
    conn = toca.get_db(); c = conn.cursor()
    c.execute("INSERT INTO wiki_documents (title, file_name, original_name, file_url, file_ext, owner_id) "
              "VALUES (?, ?, ?, ?, '.pdf', ?)",
              (title, file_name, f'{title}.pdf', f'/uploads/wikitoca/{file_name}', owner_id))
    did = c.lastrowid
    conn.commit(); conn.close()
    return did, file_name


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


# ── entries ─────────────────────────────────────────────────────────────────

def test_entries_member_sees_only_own(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_entry(a_id, 'EntryA'); _new_entry(b_id, 'EntryB')
    _login(client, a_id)
    titles = {e['title'] for e in client.get('/api/wikitoca/entries').get_json()}
    assert 'EntryA' in titles and 'EntryB' not in titles


def test_entries_search_branch_filtered(client, monkeypatch):
    """O ramo de busca `q` (cláusula OR) precisa continuar filtrado por dono —
    a OR tem que estar parentetizada, senão o registro de B vazaria."""
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_entry(a_id, 'Comum', 'texto compartilhado')
    _new_entry(b_id, 'Comum', 'texto compartilhado')  # mesmo termo, dono B
    _login(client, a_id)
    rows = client.get('/api/wikitoca/entries?q=compartilhado').get_json()
    assert len(rows) == 1 and all(r['owner_id'] == a_id for r in rows)


def test_entry_update_delete_guarded(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    eb = _new_entry(b_id, 'EntryB')
    _login(client, a_id)
    assert client.put(f'/api/wikitoca/entries/{eb}',
                      json={'title': 'X', 'content': 'y'}).status_code == 404
    assert client.delete(f'/api/wikitoca/entries/{eb}').status_code == 404


def test_entry_read_share_grants_list_but_not_write(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    eb = _new_entry(b_id, 'EntryShared')
    _share('wiki_entries', eb, a_id, 'read')
    _login(client, a_id)
    titles = {e['title'] for e in client.get('/api/wikitoca/entries').get_json()}
    assert 'EntryShared' in titles                                           # via share
    assert client.put(f'/api/wikitoca/entries/{eb}',
                      json={'title': 'X', 'content': 'y'}).status_code == 403  # só leitura


def test_entry_create_sets_owner(client, monkeypatch):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _login(client, a_id)
    r = client.post('/api/wikitoca/entries', json={'title': 'Nova', 'content': 'c'})
    assert r.status_code == 201
    assert r.get_json()['owner_id'] == a_id


# ── documents ───────────────────────────────────────────────────────────────

def test_documents_member_sees_only_own(client, monkeypatch, wiki_dir):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_document(a_id, 'DocA'); _new_document(b_id, 'DocB')
    _login(client, a_id)
    titles = {d['title'] for d in client.get('/api/wikitoca/documents').get_json()}
    assert 'DocA' in titles and 'DocB' not in titles


def test_document_delete_guarded(client, monkeypatch, wiki_dir):
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    db, _ = _new_document(b_id, 'DocB')
    _login(client, a_id)
    assert client.delete(f'/api/wikitoca/documents/{db}').status_code == 404


def test_document_file_serving_guarded(client, monkeypatch, wiki_dir):
    """O arquivo em /uploads/wikitoca/<file> só é servido a quem pode ler a
    linha do documento (o dono aqui; B recebe 404)."""
    _auth_on(monkeypatch)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _, fname = _new_document(a_id, 'DocA')
    _login(client, a_id)
    assert client.get(f'/uploads/wikitoca/{fname}').status_code == 200      # dono
    _login(client, b_id)
    assert client.get(f'/uploads/wikitoca/{fname}').status_code == 404      # outro dono


# ── regra de ouro ───────────────────────────────────────────────────────────

def test_auth_off_sees_all_entries(client, monkeypatch):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _new_entry(a_id, 'EntryA'); _new_entry(b_id, 'EntryB')
    titles = {e['title'] for e in client.get('/api/wikitoca/entries').get_json()}
    assert {'EntryA', 'EntryB'} <= titles


def test_auth_off_serves_any_document(client, monkeypatch, wiki_dir):
    monkeypatch.delenv('TOCA_AUTH_ENABLED', raising=False)
    _, admin_id, a_id, b_id = _seed_org_and_users()
    _, fname = _new_document(a_id, 'DocA')
    assert client.get(f'/uploads/wikitoca/{fname}').status_code == 200      # desktop: serve
