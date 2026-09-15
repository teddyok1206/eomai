#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="/home/eom/EOM/infra/compose/compose.yml"
SECRET_FILE="/etc/eom/secrets/postgres.env"
LOCAL_DIR="/srv/eom/backups"
NAS_DIR="/mnt/nas/eom/backups/postgresql"
SERVICE="eom-postgres"
EOM_CORE_PYTHON="/srv/eom/conda/envs/eom-core/bin/python"
MANIFEST_CONTRACT="/home/eom/EOM/scripts/infra/postgres_backup_contract.py"

umask 077

usage() {
  echo "Usage: postgres_backup.sh" >&2
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

for cmd in docker sha256sum stat date mktemp mv rm ln awk tr; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 2; }
done

[[ -x "$EOM_CORE_PYTHON" ]] || { echo "explicit EOM Python is unavailable" >&2; exit 2; }
[[ -f "$MANIFEST_CONTRACT" && ! -L "$MANIFEST_CONTRACT" ]] || {
  echo "backup manifest contract is unavailable" >&2
  exit 2
}

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
    rm -f -- "$NAS_TMP"
  fi
  if [[ -n "${NAS_MANIFEST_TMP:-}" && "$NAS_MANIFEST_TMP" == "$NAS_DIR"/*.incomplete ]]; then
    rm -f -- "$NAS_MANIFEST_TMP"
  fi
  if [[ "${DUMP_PUBLISHED:-0}" == "1" ]]; then
    rm -f -- "$NAS_FINAL"
  fi
  if [[ "${MANIFEST_PUBLISHED:-0}" == "1" ]]; then
    rm -f -- "$NAS_MANIFEST"
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
"$EOM_CORE_PYTHON" -I "$MANIFEST_CONTRACT" create \
  --created-at-utc "$TS" \
  --database "$POSTGRES_DB" \
  --postgres-version "$PG_VERSION" \
  --file "$FINAL_NAME" \
  --size-bytes "$SIZE" \
  --sha256 "$HASH" > "$TMP.manifest.incomplete"

mv "$TMP" "$NAS_TMP"
mv "$TMP.manifest.incomplete" "$NAS_MANIFEST_TMP"
DUMP_PUBLISHED=0
MANIFEST_PUBLISHED=0
ln "$NAS_TMP" "$NAS_FINAL"
DUMP_PUBLISHED=1
rm -f -- "$NAS_TMP"
ln "$NAS_MANIFEST_TMP" "$NAS_MANIFEST"
MANIFEST_PUBLISHED=1
rm -f -- "$NAS_MANIFEST_TMP"
"$EOM_CORE_PYTHON" -I "$MANIFEST_CONTRACT" verify \
  "$NAS_FINAL" "$NAS_MANIFEST" >/dev/null
DUMP_PUBLISHED=0
MANIFEST_PUBLISHED=0
trap - EXIT

echo "PASS postgres_backup"
echo "backup=$NAS_FINAL"
echo "manifest=$NAS_MANIFEST"
echo "size_bytes=$SIZE"
echo "sha256_prefix=$SHORT"
