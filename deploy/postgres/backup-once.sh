#!/bin/sh
set -eu

: "${PGHOST:?Defina PGHOST}"
: "${PGDATABASE:?Defina PGDATABASE}"
: "${PGUSER:?Defina PGUSER}"
: "${PGPASSWORD:?Defina PGPASSWORD}"

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

case "$BACKUP_RETENTION_DAYS" in
    ''|*[!0-9]*) echo "BACKUP_RETENTION_DAYS deve ser inteiro." >&2; exit 2 ;;
esac

umask 077
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="$BACKUP_DIR/tocadocoelho-${timestamp}.dump"
temp_path="$BACKUP_DIR/.tocadocoelho-${timestamp}.$$"

cleanup() {
    rm -f "$temp_path" "$temp_path.sha256"
}
trap cleanup EXIT HUP INT TERM

pg_dump \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-acl \
    --file="$temp_path"

# pg_restore --list detecta arquivo truncado/corrompido antes da promoção.
pg_restore --list "$temp_path" >/dev/null
checksum="$(sha256sum "$temp_path" | awk '{print $1}')"
printf '%s  %s\n' "$checksum" "$(basename "$final_path")" > "$temp_path.sha256"

mv "$temp_path" "$final_path"
mv "$temp_path.sha256" "$final_path.sha256"
printf '%s %s\n' "$timestamp" "$(basename "$final_path")" > "$BACKUP_DIR/.last-success"

find "$BACKUP_DIR" -type f \
    \( -name 'tocadocoelho-*.dump' -o -name 'tocadocoelho-*.dump.sha256' \) \
    -mtime "+$BACKUP_RETENTION_DAYS" -delete

trap - EXIT HUP INT TERM
printf 'backup_ok path=%s sha256=%s\n' "$final_path" "$checksum"
