#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
POSTGRES_ENV="/etc/eom/secrets/postgres.env"
EXPECTED_BRANCHES=("main" "feat/application-api-v0" "feat/hwpx-application-api-v0")

usage() {
  printf '%s\n' "usage: $0 {--upgrade|--verify} EXPECTED_COMMIT"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$#" -eq 2 ]] || { usage >&2; exit 2; }
ACTION="$1"
EXPECTED_COMMIT="$2"
[[ "${ACTION}" == "--upgrade" || "${ACTION}" == "--verify" ]] || {
  usage >&2
  exit 2
}
[[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit is invalid"
[[ "$(id -u)" -eq 0 ]] || fail "release migration requires the migration operator context"
[[ -x "${PYTHON}" ]] || fail "isolated eom-api Python is unavailable"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
  fail "working tree must be clean"

branch_allowed=false
current_branch="$(git -C "${REPOSITORY_ROOT}" branch --show-current)"
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${current_branch}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"

[[ -f "${POSTGRES_ENV}" && ! -L "${POSTGRES_ENV}" ]] || \
  fail "protected PostgreSQL environment is unavailable"
read -r secret_owner secret_mode secret_type < <(stat -Lc '%U %a %F' "${POSTGRES_ENV}")
[[ "${secret_owner}" == "root" && \
   ("${secret_mode}" == "600" || "${secret_mode}" == "640") && \
   "${secret_type}" == "regular file" ]] || \
  fail "protected PostgreSQL environment metadata is unsafe"

SOURCE_PATHS=(
  packages/protocol packages/identifiers packages/workflow services/orchestrator
  services/workflow_runner packages/hwpx_contracts services/hwpx_manager
  packages/content_intake packages/content_pack packages/item_registry
  packages/operator_identity services/identity_service packages/api_contracts
  apps/application_api packages/catalog_contracts services/catalog_service apps/eomctl
  tools/dev_reporter
)
python_path=""
for relative in "${SOURCE_PATHS[@]}"; do
  python_path+="${python_path:+:}${REPOSITORY_ROOT}/${relative}"
done

run_reviewed_python() {
  env -u EOM_DATABASE_URL \
    EOM_POSTGRES_ENV="${POSTGRES_ENV}" \
    PYTHONPATH="${python_path}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONSAFEPATH=1 \
    "${PYTHON}" "$@"
}

cd "${REPOSITORY_ROOT}"
run_reviewed_python - <<'PY'
from eom_orchestrator.database import build_engine

engine = build_engine()
try:
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT current_user, pg_get_userbyid(namespace.nspowner), "
            "current_schemas(false), "
            "has_schema_privilege(current_user, 'app', 'CREATE') "
            "FROM pg_namespace AS namespace WHERE namespace.nspname = 'app'"
        ).one()
    database_user, schema_owner, search_path, has_create = row
    if database_user != schema_owner or "app" not in search_path or not has_create:
        raise SystemExit("migration database ownership contract mismatch")
finally:
    engine.dispose()
print("migration_owner_preflight=PASS")
PY

if [[ "${ACTION}" == "--upgrade" ]]; then
  run_reviewed_python -m alembic upgrade head
fi

run_reviewed_python - <<'PY'
from eom_orchestrator.database import build_engine
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

engine = build_engine()
try:
    with engine.connect() as connection:
        actual = connection.exec_driver_sql(
            "SELECT version_num FROM app.alembic_version"
        ).scalar_one()
    if actual != CURRENT_MIGRATION_REVISION:
        raise SystemExit("production migration head mismatch")
finally:
    engine.dispose()
print(f"production_migration_head={CURRENT_MIGRATION_REVISION}")
print("release_migration=PASS")
PY
