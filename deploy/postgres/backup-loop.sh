#!/bin/sh
set -eu

BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"
case "$BACKUP_INTERVAL_HOURS" in
    ''|*[!0-9]*) echo "BACKUP_INTERVAL_HOURS deve ser inteiro." >&2; exit 2 ;;
esac
if [ "$BACKUP_INTERVAL_HOURS" -lt 1 ]; then
    echo "BACKUP_INTERVAL_HOURS deve ser ao menos 1." >&2
    exit 2
fi

while true; do
    sh /opt/toca/backup-once.sh
    sleep "$((BACKUP_INTERVAL_HOURS * 3600))"
done
