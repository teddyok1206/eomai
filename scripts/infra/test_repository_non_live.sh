#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
API_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
HWPX_PYTHON="/srv/eom/conda/envs/eom-hwpx/bin/python"
API_SITE_PACKAGES="/srv/eom/conda/envs/eom-api/lib/python3.12/site-packages"
HWPX_SITE_PACKAGES="/srv/eom/conda/envs/eom-hwpx/lib/python3.12/site-packages"

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

for opt_in in \
  EOM_RUN_API_INTEGRATION \
  EOM_RUN_API_RUNTIME_ISOLATION_PRIVILEGED \
  EOM_RUN_API_SERVICE_LIVE \
  EOM_RUN_CATALOG_CODEX_LIVE \
  EOM_RUN_CODEX_LIVE \
  EOM_RUN_DEV_SLACK_LIVE \
  EOM_RUN_HWPX_PRIVILEGED \
  EOM_RUN_INTEGRATION \
  EOM_RUN_OBSERVE_BROWSER_LIVE \
  EOM_RUN_OBSERVE_INTEGRATION \
  EOM_RUN_RETIREMENT_MUTATION_INTEGRATION \
  EOM_RUN_SYSTEMD_HOLD_TEST \
  EOM_RUN_SYSTEMD_WORKER_AUTHORIZATION \
  EOM_RUN_WORKFLOW_CODEX_LIVE \
  EOM_RUN_WORKFLOW_PRIVILEGED; do
  [[ -z "${!opt_in:-}" ]] || fail "non-live test gate refuses opt-in variable: ${opt_in}"
done

[[ -x "${API_PYTHON}" ]] || fail "Application API test interpreter is unavailable"
[[ -x "${HWPX_PYTHON}" ]] || fail "HWPX test interpreter is unavailable"
[[ -d "${API_SITE_PACKAGES}" ]] || fail "Application API site-packages are unavailable"
[[ -d "${HWPX_SITE_PACKAGES}" ]] || fail "HWPX site-packages are unavailable"
cd "${REPOSITORY_ROOT}"

mapfile -t source_roots < <(
  find packages services apps tools -mindepth 1 -maxdepth 1 -type d \
    -printf "${REPOSITORY_ROOT}/%p\n" | sort
)
[[ ${#source_roots[@]} -gt 0 ]] || fail "repository source roots are unavailable"
SOURCE_PATHS=$(IFS=:; printf '%s' "${source_roots[*]}")

run_api() {
  printf '%s\n' "repository_non_live_phase=api"
  PYTHONNOUSERSITE=1 PYTHONPATH="${SOURCE_PATHS}" "${API_PYTHON}" -m pytest -q \
    tests/unit tests/api tests/content_intake tests/content_pack tests/item_registry \
    tests/observe tests/web_gui tests/e2e \
    --ignore=tests/unit/test_local_image_provider.py
}

run_hwpx() {
  printf '%s\n' "repository_non_live_phase=hwpx_and_local_image"
  # Keep the HWPX environment's pinned Pydantic/Pillow ahead of the API test-only pytest and
  # SQLAlchemy dependencies. This is a test harness boundary, never a runtime import path.
  PYTHONNOUSERSITE=1 \
    PYTHONPATH="${SOURCE_PATHS}:${HWPX_SITE_PACKAGES}:${API_SITE_PACKAGES}" \
    "${HWPX_PYTHON}" -m pytest -q \
    tests/hwpx tests/unit/test_local_image_provider.py
}

run_integration_collection() {
  printf '%s\n' "repository_non_live_phase=integration_collection"
  PYTHONNOUSERSITE=1 PYTHONPATH="${SOURCE_PATHS}" "${API_PYTHON}" -m pytest -q \
    tests/integration
}

case "${1:-all}" in
  all)
    run_api
    run_hwpx
    run_integration_collection
    ;;
  api)
    run_api
    ;;
  hwpx)
    run_hwpx
    ;;
  integration-collection)
    run_integration_collection
    ;;
  *)
    fail "usage: $0 {all|api|hwpx|integration-collection}"
    ;;
esac
