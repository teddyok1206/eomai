#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="/srv/eom/conda/envs/eom-api/bin/python"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if (($# != 2)) || [[ "$1" != "verify" && "$1" != "migrate" && "$1" != "tests" ]]; then
  printf '%s\n' "usage: $0 {verify|migrate|tests} /tmp/eom-api-testdb-<ID>" >&2
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

import psycopg

from scripts.api.testdb_guard import (
    TestDatabaseManifest,
    TestDatabaseGuardError,
    validate_application_schema_metadata,
    validate_state_directory,
)

state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
manifest = TestDatabaseManifest.load(state / "manifest.json")
parsed = urlsplit(os.environ.get("EOM_DATABASE_URL", ""))
if (
    parsed.scheme != "postgresql+psycopg"
    or parsed.username != manifest.owner_role
    or unquote(parsed.path.removeprefix("/")) != manifest.database
):
    raise SystemExit("owner URL is not for the guarded disposable database")
connection = psycopg.connect(os.environ["EOM_DATABASE_URL"].replace("+psycopg", ""))
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT owner.rolname, description.description "
        "FROM pg_namespace namespace "
        "JOIN pg_roles owner ON owner.oid = namespace.nspowner "
        "LEFT JOIN pg_description description ON description.objoid = namespace.oid "
        "AND description.classoid = 'pg_namespace'::regclass "
        "WHERE namespace.nspname = 'app'"
    )
    schema_row = cursor.fetchone()
    if schema_row is None:
        search_path, has_usage, has_create = [], False, False
    else:
        cursor.execute(
            "SELECT current_schemas(false), "
            "has_schema_privilege(current_user, 'app', 'USAGE'), "
            "has_schema_privilege(current_user, 'app', 'CREATE')"
        )
        search_path, has_usage, has_create = cursor.fetchone() or ([], False, False)
connection.close()
try:
    validate_application_schema_metadata(
        manifest,
        schema_owner=None if schema_row is None else str(schema_row[0]),
        schema_comment=None if schema_row is None else schema_row[1],
        effective_search_path=tuple(str(value) for value in search_path),
        has_usage=bool(has_usage),
        has_create=bool(has_create),
    )
except TestDatabaseGuardError as exc:
    raise SystemExit(str(exc)) from exc
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
if [[ "${action}" == "verify" ]]; then
  printf 'Disposable application schema prerequisite passed.\n'
  exit 0
fi
if [[ "${action}" == "migrate" ]]; then
  "${PYTHON}" -m alembic upgrade head
  "${PYTHON}" -m alembic downgrade -1
  "${PYTHON}" -m alembic upgrade head
  "${PYTHON}" - <<'PY'
from eom_orchestrator.database import build_engine
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

engine = build_engine()
with engine.connect() as connection:
    assert connection.exec_driver_sql(
        "SELECT version_num FROM app.alembic_version"
    ).scalar_one() == CURRENT_MIGRATION_REVISION
    functions = connection.exec_driver_sql(
        "SELECT to_regprocedure('app.reject_identity_key_change()'), "
        "to_regprocedure('app.reject_api_audit_mutation()'), "
        "to_regprocedure('app.reject_control_plane_immutable_mutation()'), "
        "to_regprocedure('app.validate_control_plane_current_revision()'), "
        "to_regprocedure('app.protect_worker_lease_identity()')"
    ).one()
    assert all(value is not None for value in functions)
    triggers = set(
        connection.exec_driver_sql(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE trigger_schema = 'app' AND trigger_name IN ("
            "'roles_key_immutable','permissions_key_immutable',"
            "'api_audit_events_append_only','worker_leases_identity_immutable')"
        ).scalars()
    )
    assert triggers == {
        "roles_key_immutable",
        "permissions_key_immutable",
        "api_audit_events_append_only",
        "worker_leases_identity_immutable",
    }
engine.dispose()
print(f"migration_head={CURRENT_MIGRATION_REVISION} control_plane=PASS")
PY
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
export EOM_RUN_INTEGRATION=1
# The approval test writes immutable workflow history and append-only API audit
# rows. It must remain last; guarded database cleanup owns those records.
"${PYTHON}" -m pytest -q \
  tests/integration/test_persistence.py \
  tests/api/test_runtime_role_live.py \
  tests/api/test_identity_integration.py \
  tests/api/test_api_integration.py \
  tests/api/test_api_concurrency.py \
  tests/api/test_workflow_start_integration.py \
  tests/integration/test_workflow_engine.py \
  tests/integration/test_workflow_submission_idempotency.py \
  tests/integration/test_control_plane_persistence.py \
  tests/integration/test_knowledge_analysis_service.py \
  tests/integration/test_knowledge_analysis_batch_service.py \
  tests/integration/test_knowledge_analysis_protocol_lineage.py \
  tests/integration/test_v13_knowledge_analysis.py \
  tests/api/test_workflow_approval_runtime_role.py
printf 'Disposable Application API and workflow integration tests passed.\n'
