import inspect
import re
import sqlite3
from pathlib import Path

import app as toca

# Commit que congelou a migração 1 ("baseline_legacy_init"). A partir daí o
# init_db() deixou de rodar em bancos existentes, então toda tabela criada nele
# depois desta data precisa de uma migração numerada — ver test_toda_tabela_nova...
# (extraído de `git show 88dc4dc:app.py` + o ensure_schema do Outlook que ele chama)
BASELINE_TABLES = {
    'account_activities', 'account_archives', 'account_main_contacts',
    'account_presences', 'account_renewal_events', 'account_sectors', 'accounts',
    'activities', 'app_settings', 'automapping_runs', 'campaign_accounts',
    'campaign_action_logs', 'campaign_actions', 'campaigns', 'clients',
    'commitments', 'daily_suggestions', 'environment_cards',
    'environment_responses', 'iata_records', 'itoca_chat_history',
    'job_grouping_positions', 'job_groupings', 'kanban_card_activities',
    'kanban_cards', 'kanban_columns', 'message_templates',
    'outlook_processed_emails', 'portfolio_offer_items', 'portfolio_offers',
    'status_rules', 'user_integrations', 'user_profile', 'whatsapp_sync_log',
    'wiki_documents', 'wiki_entries',
}


def _tables_created_in(source: str) -> set:
    return set(re.findall(r'CREATE TABLE IF NOT EXISTS (\w+)', source, re.IGNORECASE))


def _init_db_source() -> str:
    """Fonte do init_db + a do ensure_schema que ele chama (DDL do conector Outlook)."""
    return inspect.getsource(toca.init_db) + inspect.getsource(toca.outlook_graph_ensure_schema)


def _migrations_source() -> str:
    """DDL de todas as migrações numeradas + o dos callables que elas invocam."""
    app_src = Path(toca.__file__).with_suffix('.py').read_text(encoding='utf-8')
    start = app_src.index('SCHEMA_MIGRATIONS = [')
    end = app_src.index('def _run_schema_migrations')
    chunks = [app_src[start:end]]
    for _version, _name, statements in toca.SCHEMA_MIGRATIONS:
        for stmt in statements or []:
            if callable(stmt):
                chunks.append(inspect.getsource(stmt))
    return '\n'.join(chunks)


def _tables(path):
    conn = sqlite3.connect(str(path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _applied_versions(path):
    conn = sqlite3.connect(str(path))
    try:
        return {row[0] for row in conn.execute('SELECT version FROM schema_version')}
    finally:
        conn.close()


def test_banco_novo_cria_as_tabelas_do_outlook_graph(db_path):
    """Instalação limpa: o conector do Outlook precisa das três tabelas."""
    tables = _tables(db_path)
    assert {'user_integrations', 'outlook_oauth_attempts', 'outlook_processed_emails'} <= tables
    # módulo de Feedback (migração 16)
    assert 'feedback' in tables


def test_banco_antigo_sem_a_tabela_de_oauth_e_curado(tmp_path, monkeypatch):
    """Reproduz o banco de produção que quebrava o 'Conectar Microsoft 365'.

    O usuário rodou um build da linhagem Live, que gravou schema_version até 32.
    De volta na linhagem main, MAX(version)=32 fazia toda migração nova ser
    pulada — e outlook_oauth_attempts (criada só dentro do init_db/baseline,
    depois que a baseline já rodara) nunca aparecia.
    """
    path = tmp_path / 'legado.db'
    monkeypatch.setattr(toca, 'DB_PATH', path)
    toca._run_schema_migrations()

    conn = sqlite3.connect(str(path))
    conn.execute('DROP TABLE outlook_oauth_attempts')
    conn.execute('DELETE FROM schema_version WHERE version = 15')
    # Marca a linhagem Live por cima das migrações desta linhagem.
    conn.execute(
        "INSERT INTO schema_version (version, name, applied_at) VALUES (32, 'go_live_waha_sessions_per_user', '2026-07-29T15:35:40')"
    )
    conn.commit()
    conn.close()

    assert 'outlook_oauth_attempts' not in _tables(path)

    toca._run_schema_migrations()

    assert 'outlook_oauth_attempts' in _tables(path)
    assert 15 in _applied_versions(path)
    # A migração da outra linhagem não pode ser reexecutada nem perdida.
    assert 32 in _applied_versions(path)


def test_migracoes_ja_aplicadas_nao_rodam_de_novo(db_path):
    """Rodar o migrador duas vezes é inofensivo (ALTER TABLE não é idempotente)."""
    antes = _applied_versions(db_path)
    toca._run_schema_migrations()
    assert _applied_versions(db_path) == antes


def test_toda_tabela_nova_do_init_db_tem_migracao_correspondente():
    """Guarda contra o bug que quebrou o Outlook em produção.

    O init_db() só roda uma vez por banco, como migração 1 ('baseline'). Criar uma
    tabela nova ali dentro NÃO a cria em quem já usa o app — foi assim que
    outlook_oauth_attempts (e depois 'feedback', na pr-307) nunca existiram nos
    bancos antigos, e o erro só apareceu em produção, no clique do usuário.

    Se este teste falhou, você acabou de adicionar uma tabela ao init_db(): mantenha
    o CREATE lá (bancos novos) e adicione também uma entrada nova em
    SCHEMA_MIGRATIONS (bancos existentes).
    """
    novas = _tables_created_in(_init_db_source()) - BASELINE_TABLES
    sem_migracao = sorted(novas - _tables_created_in(_migrations_source()))
    assert not sem_migracao, (
        'Tabelas criadas no init_db() sem migração correspondente: '
        f'{", ".join(sem_migracao)}. Em banco já existente elas nunca serão criadas — '
        'adicione uma entrada em SCHEMA_MIGRATIONS.'
    )


def test_baseline_tables_confere_com_o_init_db_atual():
    """BASELINE_TABLES é um retrato histórico: só pode conter tabelas que ainda existem."""
    sumidas = BASELINE_TABLES - _tables_created_in(_init_db_source())
    assert not sumidas, f'BASELINE_TABLES cita tabelas que o init_db não cria mais: {sorted(sumidas)}'


def test_banco_novo_cria_feedback_auto_jobs(db_path):
    """Watcher de feedback → Claude Code (migração 19)."""
    assert 'feedback_auto_jobs' in _tables(db_path)


def test_versoes_das_migracoes_sao_unicas_e_ordenadas():
    versions = [version for version, _name, _stmts in toca.SCHEMA_MIGRATIONS]
    assert len(versions) == len(set(versions))
    assert versions == sorted(versions)
