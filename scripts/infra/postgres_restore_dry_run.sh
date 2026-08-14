#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="/home/eom/EOM/infra/compose/compose.yml"
SECRET_FILE="/etc/eom/secrets/postgres.env"
SERVICE="eom-postgres"
BACKUP="${1:-}"

usage() {
  echo "Usage: postgres_restore_dry_run.sh /mnt/nas/eom/backups/postgresql/<backup>.dump" >&2
}

if [[ -z "$BACKUP" || "$BACKUP" == "-h" || "$BACKUP" == "--help" ]]; then
  usage
  exit 2
fi

for cmd in docker sha256sum basename date python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 2; }
done

case "$BACKUP" in
  /mnt/nas/eom/backups/postgresql/*.dump) ;;
  *) echo "backup must be under /mnt/nas/eom/backups/postgresql" >&2; exit 3 ;;
esac

[[ -f "$BACKUP" ]] || { echo "backup file missing" >&2; exit 3; }
MANIFEST="${BACKUP%.dump}.manifest.json"
[[ -f "$MANIFEST" ]] || { echo "manifest missing" >&2; exit 3; }

set -a
# shellcheck disable=SC1090
source "$SECRET_FILE"
set +a

TS="$(date -u +%Y%m%d%H%M%S)"
RESTORE_DB="eom_restore_${TS}"
CONTAINER_PATH="/tmp/$(basename "$BACKUP")"

cleanup() {
  docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\";" >/dev/null 2>&1 || true
  docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" rm -f "$CONTAINER_PATH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

expected="$(python3 - "$MANIFEST" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['sha256'])
PY
)"
actual="$(sha256sum "$BACKUP" | awk '{print $1}')"
[[ "$expected" == "$actual" ]] || { echo "checksum mismatch" >&2; exit 4; }

docker cp "$BACKUP" "$SERVICE:$CONTAINER_PATH"
docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$RESTORE_DB\";"
docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  pg_restore -U "$POSTGRES_USER" -d "$RESTORE_DB" "$CONTAINER_PATH"
docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  psql -U "$POSTGRES_USER" -d "$RESTORE_DB" -v ON_ERROR_STOP=1 -c "SELECT current_database();" >/dev/null

cleanup
trap - EXIT
echo "PASS postgres_restore_dry_run"
echo "database_restored_and_removed=$RESTORE_DB"
echo "backup=$(basename "$BACKUP")"
