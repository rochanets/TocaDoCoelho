"""Testes do submódulo AutoToca Reembolsos."""
import app as toca


def test_schema_reembolsos_tabelas_existem(db_path):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row['name'] for row in c.fetchall()}
    conn.close()
    assert 'reembolso_origem_historico' in tables
    assert 'account_reembolso_enderecos' in tables
    assert 'reembolsos_history' in tables


def test_account_reembolso_enderecos_um_por_conta(db_path, sample_client_id):
    conn = toca.get_db()
    c = conn.cursor()
    c.execute("INSERT INTO accounts (name) VALUES ('Conta Teste')")
    account_id = c.lastrowid
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?)",
        (account_id, 'Rua A, 100, São Paulo, SP')
    )
    conn.commit()
    # UNIQUE(account_id) — um segundo INSERT com ON CONFLICT deve substituir, não duplicar
    c.execute(
        "INSERT INTO account_reembolso_enderecos (account_id, endereco) VALUES (?, ?) "
        "ON CONFLICT(account_id) DO UPDATE SET endereco = excluded.endereco",
        (account_id, 'Rua B, 200, São Paulo, SP')
    )
    conn.commit()
    c.execute("SELECT endereco FROM account_reembolso_enderecos WHERE account_id = ?", (account_id,))
    rows = c.fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]['endereco'] == 'Rua B, 200, São Paulo, SP'
