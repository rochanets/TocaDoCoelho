#!/usr/bin/env python3
"""ETL de dados SQLite → PostgreSQL preservando IDs (Fase 2 — migração de dados).

Uso:
  DATABASE_URL=postgresql://user:pass@host/db \\
      python scripts/etl_sqlite_to_postgres.py [caminho/origem.db]

Se a origem for omitida, usa o banco padrão do app (DATA_DIR/toca-do-coelho.db).

Pré-requisitos:
  - O schema já deve existir no PostgreSQL de destino (rode as migrations antes,
    ex.: `DATABASE_URL=... python -c "import app"`).
  - A origem SQLite deve estar migrada até a mesma versão de schema (o app faz
    isso automaticamente ao abrir o arquivo).

Estratégia (segura e idempotente):
  - Copia, tabela a tabela, as linhas da origem para o destino, usando a
    INTERSEÇÃO de colunas (resiliente a pequenas diferenças de schema).
  - FKs desligadas durante a carga (`session_replication_role='replica'`), e
    TRUNCATE remove os seeds default criados pelas migrations antes de carregar
    os dados reais — o destino vira uma cópia fiel da origem.
  - Ao final, reajusta as sequences das colunas `id` para MAX(id) e valida
    COUNT(*) origem vs destino por tabela.
"""
import os
import sqlite3
import sys
from pathlib import Path

# Tabelas gerenciadas pelo próprio destino / internas do SQLite — não copiar.
SKIP_TABLES = {'schema_version', 'sqlite_sequence'}


def _pg_columns_by_table(pg):
    cur = pg.cursor()
    cur.execute(
        "SELECT table_name::text, column_name::text FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    )
    out = {}
    for table, column in cur.fetchall():
        out.setdefault(table, []).append(column)
    return out


def _sqlite_tables(sq):
    rows = sq.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def _sqlite_columns(sq, table):
    return [r[1] for r in sq.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _reset_postgres_id_sequences(pg, tables, pg_cols):
    """Reajusta somente IDs que realmente têm sequence no PostgreSQL.

    Algumas tabelas usam `id TEXT` com UUID/token aleatório. Consultar MAX(id)
    junto ao fallback inteiro do setval nessas tabelas causa DatatypeMismatch,
    mesmo quando pg_get_serial_sequence() é NULL.
    """
    from psycopg import sql

    cur = pg.cursor()
    for table in tables:
        if 'id' not in pg_cols[table]:
            continue
        cur.execute(
            "SELECT pg_get_serial_sequence(%s, 'id')",
            (f'"{table}"',),
        )
        sequence_name = cur.fetchone()[0]
        if not sequence_name:
            continue
        cur.execute(
            sql.SQL(
                "SELECT setval("
                "  %s,"
                "  COALESCE((SELECT MAX(id) FROM {}), 1),"
                "  (SELECT COUNT(*) FROM {}) > 0"
                ")"
            ).format(sql.Identifier(table), sql.Identifier(table)),
            (sequence_name,),
        )


def run_etl(sqlite_path, database_url, *, log=print):
    """Executa o ETL e devolve um resumo {tables: {t: n}, mismatches: [...]}"""
    import psycopg

    sq = sqlite3.connect(str(sqlite_path))
    pg = psycopg.connect(database_url)
    try:
        pg_cols = _pg_columns_by_table(pg)
        tables = [t for t in _sqlite_tables(sq)
                  if t in pg_cols and t not in SKIP_TABLES]

        cur = pg.cursor()
        # Desliga verificação de FK/triggers durante a carga (exige superuser).
        cur.execute("SET session_replication_role = 'replica'")
        if tables:
            cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE")

        summary = {}
        for table in tables:
            src_cols = _sqlite_columns(sq, table)
            cols = [c for c in src_cols if c in pg_cols[table]]  # interseção, ordem da origem
            collist = ", ".join(f'"{c}"' for c in cols)
            rows = sq.execute(f'SELECT {collist} FROM "{table}"').fetchall()
            if rows:
                placeholders = ", ".join(["%s"] * len(cols))
                cur.executemany(
                    f'INSERT INTO "{table}" ({collist}) VALUES ({placeholders})', rows
                )
            summary[table] = len(rows)
            log(f'  {table}: {len(rows)} linhas')

        cur.execute("SET session_replication_role = 'origin'")
        pg.commit()

        # Reajusta apenas sequences reais. IDs textuais (ex.: Companion) não
        # possuem sequence e devem ser ignorados.
        _reset_postgres_id_sequences(pg, tables, pg_cols)
        pg.commit()

        # Validação: COUNT(*) origem vs destino.
        mismatches = []
        for table in tables:
            n_src = sq.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            n_dst = pg.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            if n_src != n_dst:
                mismatches.append((table, n_src, n_dst))
        return {'tables': summary, 'mismatches': mismatches}
    finally:
        sq.close()
        pg.close()


def main(argv):
    database_url = os.getenv('DATABASE_URL')
    if not database_url or not database_url.startswith(('postgres://', 'postgresql://')):
        print('ERRO: defina DATABASE_URL apontando para o PostgreSQL de destino.')
        return 2
    if len(argv) > 1:
        sqlite_path = Path(argv[1])
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        import app  # noqa: WPS433 — usa o DB_PATH padrão do app
        sqlite_path = app.DB_PATH
    if not Path(sqlite_path).exists():
        print(f'ERRO: origem SQLite não encontrada: {sqlite_path}')
        return 2

    print(f'ETL: {sqlite_path} → PostgreSQL')
    result = run_etl(sqlite_path, database_url)
    total = sum(result['tables'].values())
    print(f'\nTotal: {total} linhas em {len(result["tables"])} tabelas.')
    if result['mismatches']:
        print('DIVERGÊNCIAS DE CONTAGEM:')
        for t, s, d in result['mismatches']:
            print(f'  {t}: origem={s} destino={d}')
        return 1
    print('Validação COUNT(*) OK — origem e destino batem em todas as tabelas.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
