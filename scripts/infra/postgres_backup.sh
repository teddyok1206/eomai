#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="/home/eom/EOM/infra/compose/compose.yml"
SECRET_FILE="/etc/eom/secrets/postgres.env"
LOCAL_DIR="/srv/eom/backups"
NAS_DIR="/mnt/nas/eom/backups/postgresql"
SERVICE="eom-postgres"

usage() {
  echo "Usage: postgres_backup.sh" >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

for cmd in docker sha256sum stat date mktemp mv rm; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 2; }
done

[[ -r "$SECRET_FILE" ]] || { echo "secret file not readable: $SECRET_FILE" >&2; exit 3; }
[[ -d "$LOCAL_DIR" ]] || { echo "local backup dir missing: $LOCAL_DIR" >&2; exit 3; }
[[ -d "$NAS_DIR" ]] || { echo "NAS backup dir missing: $NAS_DIR" >&2; exit 3; }

set -a
# shellcheck disable=SC1090
source "$SECRET_FILE"
set +a

required_vars=(POSTGRES_DB POSTGRES_USER)
for var in "${required_vars[@]}"; do
  [[ -n "${!var:-}" ]] || { echo "missing required secret var: $var" >&2; exit 4; }
done

health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$SERVICE" 2>/dev/null || true)"
[[ "$health" == "healthy" ]] || { echo "postgres not healthy: $health" >&2; exit 5; }

TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp "$LOCAL_DIR/eom_${TS}_XXXXXX.dump.incomplete")"
cleanup() {
  rm -f -- "$TMP" "$TMP.manifest.incomplete"
  if [[ -n "${NAS_TMP:-}" && "$NAS_TMP" == "$NAS_DIR"/*.incomplete ]]; then
    rm -f -- "$NAS_TMP" "$NAS_TMP.manifest.incomplete"
  fi
}
trap cleanup EXIT

docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$TMP"

HASH="$(sha256sum "$TMP" | awk '{print $1}')"
SHORT="${HASH:0:12}"
FINAL_NAME="eom_${TS}_${SHORT}.dump"
MANIFEST_NAME="eom_${TS}_${SHORT}.manifest.json"
NAS_TMP="$NAS_DIR/$FINAL_NAME.incomplete"
NAS_FINAL="$NAS_DIR/$FINAL_NAME"
NAS_MANIFEST_TMP="$NAS_DIR/$MANIFEST_NAME.incomplete"
NAS_MANIFEST="$NAS_DIR/$MANIFEST_NAME"

[[ ! -e "$NAS_FINAL" && ! -e "$NAS_MANIFEST" ]] || { echo "backup target already exists" >&2; exit 6; }

PG_VERSION="$(docker compose --env-file "$SECRET_FILE" -f "$COMPOSE_FILE" exec -T "$SERVICE" postgres --version | tr -d '\r')"
SIZE="$(stat -c '%s' "$TMP")"
cat > "$TMP.manifest.incomplete" <<JSON
{
  "created_at_utc": "$TS",
  "database": "$POSTGRES_DB",
  "postgres_version": "$PG_VERSION",
  "file": "$FINAL_NAME",
  "size_bytes": $SIZE,
  "sha256": "$HASH"
}
JSON

mv "$TMP" "$NAS_TMP"
mv "$TMP.manifest.incomplete" "$NAS_MANIFEST_TMP"
mv "$NAS_TMP" "$NAS_FINAL"
mv "$NAS_MANIFEST_TMP" "$NAS_MANIFEST"
trap - EXIT

echo "PASS postgres_backup"
echo "backup=$NAS_FINAL"
echo "manifest=$NAS_MANIFEST"
echo "size_bytes=$SIZE"
echo "sha256_prefix=$SHORT"
