"""Testes da migração 20 — fundação multiusuário (Fase A).

Cobre dois cenários:
  1. Estrutura: tabelas users/organizations/shares criadas, coluna owner_id
     presente nas entidades-raiz e ausente nas tabelas que herdam via FK.
  2. Backfill: partindo de um banco v13 com user_profile + dados de negócio,
     a migração cria o fundador e atribui owner_id = fundador em tudo.
"""
import sqlite3

import pytest

import app as toca


# Tabelas-raiz que DEVEM ganhar owner_id nesta migração.
OWNER_TABLES = [
    'clients', 'accounts', 'campaigns', 'commitments', 'activities',
    'kanban_columns', 'wiki_entries', 'wiki_documents', 'portfolio_offers',
    'iata_records', 'environment_cards',
]

# Tabelas que herdam a dona via FK do pai — NÃO devem ter owner_id.
INHERITING_TABLES = ['kanban_cards', 'job_change_events']


def _columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}


def _apply_migrations_up_to(path, max_version):
    """Aplica SCHEMA_MIGRATIONS até `max_version` (inclusive) em `path`."""
    original = toca.SCHEMA_MIGRATIONS
    toca.SCHEMA_MIGRATIONS = [m for m in original if m[0] <= max_version]
    try:
        toca._run_schema_migrations()
    finally:
        toca.SCHEMA_MIGRATIONS = original


# --------------------------------------------------------------- estrutura

def test_new_tables_exist(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {'organizations', 'users', 'shares'} <= names


def test_owner_id_on_root_tables(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        for table in OWNER_TABLES:
            assert 'owner_id' in _columns(conn, table), f'{table} sem owner_id'
    finally:
        conn.close()


def test_inheriting_tables_have_no_owner_id(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        for table in INHERITING_TABLES:
            assert 'owner_id' not in _columns(conn, table), \
                f'{table} não deveria ter owner_id (herda via FK do pai)'
    finally:
        conn.close()


def test_founding_org_seeded(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute('SELECT name FROM organizations').fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == 'Toca do Coelho'


def test_shares_unique_constraint(db_path):
    """shares não aceita compartilhamento duplicado do mesmo registro/usuário."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO shares (record_type, record_id, shared_with_user_id) "
            "VALUES ('clients', 1, 99)")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO shares (record_type, record_id, shared_with_user_id) "
                "VALUES ('clients', 1, 99)")
            conn.commit()
    finally:
        conn.close()


def test_multiple_null_entra_object_id_allowed(db_path):
    """UNIQUE(entra_object_id) deve permitir múltiplos NULL (usuários pré-SSO)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("INSERT INTO users (email, full_name, nickname, position) "
                     "VALUES ('a@x.com', 'A', 'a', 'x')")
        conn.execute("INSERT INTO users (email, full_name, nickname, position) "
                     "VALUES ('b@x.com', 'B', 'b', 'x')")
        conn.commit()
        n = conn.execute(
            'SELECT COUNT(*) FROM users WHERE entra_object_id IS NULL').fetchone()[0]
        assert n >= 2
    finally:
        conn.close()


# ----------------------------------------------------------------- backfill

def test_backfill_founder_and_owner_id(tmp_path, monkeypatch):
    """Banco v13 com user_profile + dados → migração cria fundador e backfila."""
    path = tmp_path / 'legacy.db'
    monkeypatch.setattr(toca, 'DB_PATH', path)

    # 1. Sobe até a v13 (antes da fundação multiusuário).
    _apply_migrations_up_to(path, 13)

    # 2. Popula estado "legado": perfil do fundador + registros de negócio.
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO user_profile (id, full_name, nickname, position, email) "
        "VALUES (1, 'Fundadora Teste', 'Fund', 'Sócia', 'fund@toca.com')")
    conn.execute("INSERT INTO clients (name, company, position) "
                 "VALUES ('Cliente 1', 'Empresa 1', 'Gerente')")
    conn.execute("INSERT INTO accounts (name) VALUES ('Conta 1')")
    conn.commit()
    # owner_id ainda não existe na v13
    assert 'owner_id' not in _columns(conn, 'clients')
    conn.close()

    # 3. Aplica a migração 20.
    _apply_migrations_up_to(path, 20)

    # 4. Valida fundador + org + backfill.
    conn = sqlite3.connect(str(path))
    try:
        org = conn.execute('SELECT id, name FROM organizations').fetchall()
        assert len(org) == 1
        org_id = org[0][0]

        users = conn.execute(
            'SELECT id, org_id, email, full_name, role, entra_object_id '
            'FROM users').fetchall()
        assert len(users) == 1
        founder = users[0]
        assert founder[1] == org_id            # org_id aponta pra org fundadora
        assert founder[2] == 'fund@toca.com'   # email veio do user_profile
        assert founder[3] == 'Fundadora Teste'
        assert founder[4] == 'admin'           # papel do fundador
        assert founder[5] is None              # entra_object_id NULL (pré-SSO)
        founder_id = founder[0]

        # Todo registro de negócio pré-existente aponta pro fundador.
        for table in ('clients', 'accounts'):
            owners = [r[0] for r in conn.execute(f'SELECT owner_id FROM {table}')]
            assert owners and all(o == founder_id for o in owners), \
                f'{table} não backfilado para o fundador'
    finally:
        conn.close()


def test_migration_idempotent_on_empty_db(tmp_path, monkeypatch):
    """Banco novo sem user_profile: migração roda sem erro, sem fundador."""
    path = tmp_path / 'fresh.db'
    monkeypatch.setattr(toca, 'DB_PATH', path)
    _apply_migrations_up_to(path, 20)
    conn = sqlite3.connect(str(path))
    try:
        # Org é sempre semeada; usuário só existe se houver user_profile.
        assert conn.execute('SELECT COUNT(*) FROM organizations').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
    finally:
        conn.close()


def test_reconciles_foreign_v14_and_partial_old_live(tmp_path, monkeypatch):
    """Banco que rodou a PR experimental v14 e iniciou a antiga v15 é reparado.

    A migration experimental permanece registrada; a fundação multiusuário
    entra na faixa 20+ e ADD COLUMN já aplicado é ignorado com segurança.
    """
    path = tmp_path / 'foreign-v14.db'
    monkeypatch.setattr(toca, 'DB_PATH', path)
    _apply_migrations_up_to(path, 13)

    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO user_profile (id, full_name, nickname, position, email) "
        "VALUES (1, 'Fundador', 'Fund', 'Sócio', 'fund@corp.com')"
    )
    conn.execute(
        "INSERT INTO schema_version (version, name, applied_at) "
        "VALUES (14, 'reembolsos_schema', '2026-07-14T00:00:00')"
    )
    # Estado parcial observado no banco real: DDLs da antiga migration 15
    # persistiram antes de o UPDATE que dependia de users falhar.
    conn.execute('ALTER TABLE account_archives ADD COLUMN owner_id INTEGER')
    conn.execute('ALTER TABLE account_planning_runs ADD COLUMN owner_id INTEGER')
    conn.execute('CREATE INDEX idx_account_archives_owner ON account_archives(owner_id)')
    conn.execute('CREATE INDEX idx_account_planning_runs_owner ON account_planning_runs(owner_id)')
    conn.commit()
    conn.close()

    _apply_migrations_up_to(path, 27)

    conn = sqlite3.connect(str(path))
    try:
        versions = dict(conn.execute('SELECT version, name FROM schema_version'))
        assert versions[14] == 'reembolsos_schema'
        assert versions[20] == 'multiusuario_fase_a_users_orgs_shares_owner_id'
        assert versions[27] == 'multiusuario_fase_4_5_user_profile_preferences'
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
        assert 'owner_id' in _columns(conn, 'account_archives')
        assert 'owner_id' in _columns(conn, 'account_planning_runs')
    finally:
        conn.close()
