#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "Uso: restore-verify.sh ARQUIVO.dump BANCO_DESCARTAVEL" >&2
    exit 2
fi

: "${PGHOST:?Defina PGHOST}"
: "${PGDATABASE:?Defina PGDATABASE}"
: "${PGUSER:?Defina PGUSER}"
: "${PGPASSWORD:?Defina PGPASSWORD}"

backup_path="$1"
target_database="$2"

case "$target_database" in
    *[!A-Za-z0-9_]*|'')
        echo "Nome do banco descartável inválido." >&2
        exit 2
        ;;
esac
if [ "$target_database" = "$PGDATABASE" ]; then
    echo "O restore de verificação nunca pode usar o banco de origem." >&2
    exit 2
fi
if [ ! -f "$backup_path" ]; then
    echo "Backup não encontrado: $backup_path" >&2
    exit 2
fi

pg_restore --list "$backup_path" >/dev/null
checksum_path="$backup_path.sha256"
if [ -f "$checksum_path" ]; then
    (
        cd "$(dirname "$backup_path")"
        sha256sum -c "$(basename "$checksum_path")"
    )
fi

if psql --dbname=postgres --tuples-only --no-align \
    --command="SELECT 1 FROM pg_database WHERE datname = '$target_database'" \
    | grep -q '^1$'; then
    echo "O banco descartável já existe; nada foi alterado." >&2
    exit 2
fi

cleanup() {
    dropdb --if-exists "$target_database" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

createdb "$target_database"
pg_restore \
    --exit-on-error \
    --no-owner \
    --no-acl \
    --dbname="$target_database" \
    "$backup_path"

schema_version="$(
    psql --dbname="$target_database" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command='SELECT COALESCE(MAX(version), 0) FROM schema_version'
)"
table_count="$(
    psql --dbname="$target_database" --tuples-only --no-align \
        --set=ON_ERROR_STOP=1 \
        --command="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'"
)"

if [ "$schema_version" -lt 1 ] || [ "$table_count" -lt 1 ]; then
    echo "Restore incompleto: schema_version=$schema_version tables=$table_count" >&2
    exit 1
fi

printf 'restore_verify_ok database=%s schema_version=%s tables=%s\n' \
    "$target_database" "$schema_version" "$table_count"
