#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="/home/eom/EOM/infra/compose/compose.yml"
SECRET_FILE="/etc/eom/secrets/postgres.env"
SERVICE="eom-postgres"
EOM_CORE_PYTHON="/srv/eom/conda/envs/eom-core/bin/python"
MANIFEST_CONTRACT="/home/eom/EOM/scripts/infra/postgres_backup_contract.py"
BACKUP="${1:-}"

usage() {
  echo "Usage: postgres_restore_dry_run.sh /mnt/nas/eom/backups/postgresql/<backup>.dump" >&2
}

if [[ -z "$BACKUP" || "$BACKUP" == "-h" || "$BACKUP" == "--help" ]]; then
  usage
  exit 2
fi

for cmd in docker basename date; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 2; }
done

[[ -x "$EOM_CORE_PYTHON" ]] || { echo "explicit EOM Python is unavailable" >&2; exit 2; }
[[ -f "$MANIFEST_CONTRACT" && ! -L "$MANIFEST_CONTRACT" ]] || {
  echo "backup manifest contract is unavailable" >&2
  exit 2
}

case "$BACKUP" in
  /mnt/nas/eom/backups/postgresql/*.dump) ;;
  *) echo "backup must be under /mnt/nas/eom/backups/postgresql" >&2; exit 3 ;;
esac

[[ -f "$BACKUP" ]] || { echo "backup file missing" >&2; exit 3; }
MANIFEST="${BACKUP%.dump}.manifest.json"
[[ -f "$MANIFEST" ]] || { echo "manifest missing" >&2; exit 3; }

VALIDATION="$("$EOM_CORE_PYTHON" -I "$MANIFEST_CONTRACT" verify "$BACKUP" "$MANIFEST")"

[[ -r "$SECRET_FILE" ]] || { echo "secret file not readable: $SECRET_FILE" >&2; exit 3; }
set -a
# shellcheck disable=SC1090
source "$SECRET_FILE"
set +a

TS="$(date -u +%Y%m%d%H%M%S)"
RESTORE_DB="eom_restore_${TS}_$$"
CONTAINER_PATH="/tmp/${RESTORE_DB}_$(basename "$BACKUP")"

cleanup() {
  docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
    psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\";" >/dev/null 2>&1 || true
  docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" rm -f "$CONTAINER_PATH" >/dev/null 2>&1 || true
}
trap cleanup EXIT

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
echo "$VALIDATION"
