#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="/srv/eom/conda/envs/eom-api/bin/python"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if (($# != 2)) || [[ "$1" != "migrate" && "$1" != "tests" ]]; then
  printf '%s\n' "usage: $0 {migrate|tests} /tmp/eom-api-testdb-<ID>" >&2
  exit 2
fi
[[ "$(id -un)" == "eom" ]] || fail "test database execution must run as eom"
[[ -x "${PYTHON}" ]] || fail "isolated eom-api Python is unavailable"

action="$1"
state_directory="$2"
[[ "${state_directory}" == /tmp/eom-api-testdb-* ]] || fail "unsafe test state path"
[[ ! -L "${state_directory}" && -d "${state_directory}" ]] || fail "test state is unavailable"
[[ "$(stat -Lc '%U:%G:%a' "${state_directory}")" == "eom:eom:700" ]] || \
  fail "test state directory metadata mismatch"
for path in "${state_directory}/manifest.json" "${state_directory}/owner.env"; do
  [[ ! -L "${path}" && -f "${path}" ]] || fail "test state file is unavailable"
  [[ "$(stat -Lc '%U:%G:%a' "${path}")" == "eom:eom:600" ]] || \
    fail "test state file metadata mismatch"
done

set -a
source "${state_directory}/owner.env"
set +a
EOM_API_TEST_STATE="${state_directory}" PYTHONPATH="${REPOSITORY_ROOT}" "${PYTHON}" <<'PY'
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.api.testdb_guard import TestDatabaseManifest, validate_state_directory

state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
manifest = TestDatabaseManifest.load(state / "manifest.json")
parsed = urlsplit(os.environ.get("EOM_DATABASE_URL", ""))
if (
    parsed.scheme != "postgresql+psycopg"
    or parsed.username != manifest.owner_role
    or unquote(parsed.path.removeprefix("/")) != manifest.database
):
    raise SystemExit("owner URL is not for the guarded disposable database")
PY

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
export PYTHONPATH="${python_path}"

cd "${REPOSITORY_ROOT}"
if [[ "${action}" == "migrate" ]]; then
  "${PYTHON}" -m alembic upgrade head
  "${PYTHON}" -m alembic downgrade -1
  "${PYTHON}" -m alembic upgrade head
  printf 'Disposable API test database migration cycle passed.\n'
  printf 'Next privileged phase: scripts/api/testdb_prepare.sh --reconcile %s\n' \
    "${state_directory}"
  exit 0
fi

runtime_environment="${state_directory}/runtime.env"
[[ ! -L "${runtime_environment}" && -f "${runtime_environment}" ]] || \
  fail "reconciled runtime environment is unavailable"
[[ "$(stat -Lc '%U:%G:%a' "${runtime_environment}")" == "eom:eom:600" ]] || \
  fail "runtime environment metadata mismatch"
export EOM_API_TEST_RUNTIME_ENV="${runtime_environment}"
export EOM_RUN_API_INTEGRATION=1
"${PYTHON}" -m pytest -q \
  tests/api/test_runtime_role_live.py \
  tests/api/test_identity_integration.py \
  tests/api/test_api_integration.py \
  tests/api/test_api_concurrency.py
printf 'Disposable Application API integration and concurrency tests passed.\n'
