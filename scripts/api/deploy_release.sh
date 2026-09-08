#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCHES=("main" "feat/application-api-v0" "feat/hwpx-application-api-v0")
API_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
API_PIP="${API_PYTHON} -m pip"
SERVICE="eom-api.service"
WORKFLOW_RUNNER_SERVICE="eom-workflow-runner.service"
PLATFORM_CONSUMER_SERVICES=(
  "eom-catalog-application-runner.service"
  "eom-workflow-runner.service"
  "eom-hwpx-application-runner.service"
  "eom-api.service"
)
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/eom-api.service"
UNIT_TARGET="/etc/systemd/system/eom-api.service"
METADATA_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_deployment_metadata.sh"
METADATA_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-deployment-metadata"
RUNTIME_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_runtime_isolation.sh"
RUNTIME_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-runtime-isolation"
MOCK_EXAM_DEPLOYMENT_ADMISSION_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_mock_exam_deployment_admission.py"
MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET="/usr/local/libexec/eom-api/verify-mock-exam-deployment-admission"
WORKFLOW_RUNNER_HOLD_LIBRARY="${REPOSITORY_ROOT}/scripts/api/workflow_runner_deployment_hold.sh"
WORKFLOW_RUNNER_HOLD_SOURCE="${REPOSITORY_ROOT}/infra/systemd/zzzz-eom-workflow-runner-deployment-hold.conf"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_workflow_runner_hold_release.py"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT="/usr/local/libexec/eom-api"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-workflow-runner-hold-release"
WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT="/var/lib/eom-api/mock-exam-retirement-receipts"
ACTION="verify"
PRESERVE_WORKFLOW_RUNNER_INACTIVE=false
STAGING_ROOT=""
RELEASE_RECEIPT_FILE=""
RELEASE_EXECUTION_ID=""
RELEASE_EXECUTION_REVISION_ID=""
RELEASE_CHECKPOINT_SHA256=""
RELEASE_PRODUCTION_REQUEST_ID=""
RELEASE_PRODUCTION_PLAN_ID=""
RELEASE_PRODUCTION_PLAN_SHA256=""
RELEASE_OPERATOR_ID=""
RELEASE_RECEIPT_SHA256=""

usage() {
  printf '%s\n' "usage: $0 [--build-only|--install|--install-preserve-workflow-runner-inactive|--verify]" \
    "       $0 --release-workflow-runner-hold RECEIPT_FILE EXECUTION_ID EXECUTION_REVISION_ID CHECKPOINT_SHA256 PRODUCTION_REQUEST_ID PRODUCTION_PLAN_ID PRODUCTION_PLAN_SHA256 OPERATOR_ID RECEIPT_SHA256"
}

if (($# > 0)) && [[ "$1" == "--release-workflow-runner-hold" ]]; then
  (($# == 10)) || { usage >&2; exit 2; }
  ACTION="release-workflow-runner-hold"
  RELEASE_RECEIPT_FILE="$2"
  RELEASE_EXECUTION_ID="$3"
  RELEASE_EXECUTION_REVISION_ID="$4"
  RELEASE_CHECKPOINT_SHA256="$5"
  RELEASE_PRODUCTION_REQUEST_ID="$6"
  RELEASE_PRODUCTION_PLAN_ID="$7"
  RELEASE_PRODUCTION_PLAN_SHA256="$8"
  RELEASE_OPERATOR_ID="$9"
  RELEASE_RECEIPT_SHA256="${10}"
elif (($# > 1)); then
  usage >&2
  exit 2
elif (($# == 1)); then
  case "$1" in
    --build-only) ACTION="build" ;;
    --install) ACTION="install" ;;
    --install-preserve-workflow-runner-inactive)
      ACTION="install"
      PRESERVE_WORKFLOW_RUNNER_INACTIVE=true
      ;;
    --verify) ACTION="verify" ;;
    *) usage >&2; exit 2 ;;
  esac
fi

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ -r "${WORKFLOW_RUNNER_HOLD_LIBRARY}" ]] || fail "workflow runner hold helper is unavailable"
# shellcheck source=scripts/api/workflow_runner_deployment_hold.sh
source "${WORKFLOW_RUNNER_HOLD_LIBRARY}"

activate_workflow_runner_deployment_hold() {
  local activation_identity_before activation_identity_after runtime_mask_state staged_hold
  [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]] || return 0
  activation_identity_before="$(
    workflow_runner_stopped_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "${WORKFLOW_RUNNER_SERVICE} must be inactive/dead with MainPID=0 before the hold"
  workflow_runner_require_base_unit_file "${WORKFLOW_RUNNER_FRAGMENT}" || \
    fail "workflow runner base unit identity mismatch"
  workflow_runner_require_source_hold_file \
    "${WORKFLOW_RUNNER_HOLD_SOURCE}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
    fail "canonical workflow runner deployment hold source mismatch"

  # Close the reboot window before materializing the hold. A concurrent activation in this short
  # disabled-but-not-yet-held interval is detected by the immutable invocation identity and aborts
  # the install before any wheel, migration, or service mutation.
  sudo -n /usr/bin/systemctl disable "${WORKFLOW_RUNNER_SERVICE}" >/dev/null
  activation_identity_after="$(
    workflow_runner_stopped_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner did not remain stopped while its reboot fence was installed"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked while its reboot fence was installed"
  activation_identity_before="${activation_identity_after}"
  if [[ -e "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || -L "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" ]]; then
    workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || \
      fail "workflow runner deployment hold directory identity mismatch"
  else
    sudo -n /usr/bin/install -d -o root -g root -m 0755 \
      "${WORKFLOW_RUNNER_HOLD_DIRECTORY}"
  fi
  workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || \
    fail "workflow runner deployment hold directory was not installed safely"

  staged_hold="${WORKFLOW_RUNNER_HOLD_DIRECTORY}/.zzzz-eom-deployment-hold.staged"
  if [[ -e "${WORKFLOW_RUNNER_HOLD_TARGET}" || -L "${WORKFLOW_RUNNER_HOLD_TARGET}" ]]; then
    [[ ! -e "${staged_hold}" && ! -L "${staged_hold}" && \
      ! -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" && \
      ! -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]] || \
      fail "conflicting workflow runner deployment hold materializations require review"
    workflow_runner_require_hold_file \
      "${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
      fail "existing workflow runner deployment hold identity mismatch"
  else
    if [[ -e "${staged_hold}" || -L "${staged_hold}" ]] && \
      [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
        -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]]; then
      fail "conflicting workflow runner deployment hold recovery files require review"
    fi
    if [[ -e "${staged_hold}" || -L "${staged_hold}" ]]; then
      workflow_runner_require_hold_file "${staged_hold}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
        fail "staged workflow runner deployment hold identity mismatch"
    elif [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
      -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]]; then
      workflow_runner_require_hold_file \
        "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
        fail "released workflow runner deployment hold backup identity mismatch"
      sudo -n /usr/bin/mv -T \
        "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${staged_hold}"
    else
      sudo -n /usr/bin/install -o root -g root -m 0644 \
        "${WORKFLOW_RUNNER_HOLD_SOURCE}" "${staged_hold}"
      workflow_runner_require_hold_file "${staged_hold}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
        fail "staged workflow runner deployment hold was not materialized safely"
    fi
    sudo -n /usr/bin/mv -T "${staged_hold}" "${WORKFLOW_RUNNER_HOLD_TARGET}"
  fi

  # No release mutation is allowed until systemd has loaded and exposed the exact persistent hold.
  sudo -n /usr/bin/systemctl daemon-reload
  activation_identity_after="$(
    workflow_runner_release_fenced_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner persistent deployment hold was not loaded under its reboot fence"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked while the persistent hold was being activated"
  sudo -n /usr/bin/systemctl enable "${WORKFLOW_RUNNER_SERVICE}" >/dev/null
  activation_identity_after="$(
    workflow_runner_deployment_hold_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner persistent deployment hold was not enabled safely"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked while the held unit was re-enabled"

  # Commit 6691567 may have left this exact ineffective lower-precedence runtime mask. Remove only
  # that reviewed identity and only while the effective persistent hold is already proven.
  runtime_mask_state="$(workflow_runner_ineffective_runtime_mask_state)" || \
    fail "foreign workflow runner runtime-mask residue requires manual review"
  if [[ "${runtime_mask_state}" == "EXACT" ]]; then
    sudo -n /usr/bin/rm -- "${WORKFLOW_RUNNER_INEFFECTIVE_RUNTIME_MASK}"
    sudo -n /usr/bin/systemctl daemon-reload
  fi
  workflow_runner_require_no_ineffective_runtime_mask || \
    fail "ineffective workflow runner runtime-mask residue remains"
  activation_identity_after="$(
    workflow_runner_deployment_hold_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner persistent deployment hold was lost during residue cleanup"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked during persistent-hold activation"
}

verify_workflow_runner_deployment_hold() {
  [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]] || return 0
  workflow_runner_require_no_ineffective_runtime_mask || \
    fail "ineffective workflow runner runtime-mask residue reappeared"
  workflow_runner_require_deployment_hold /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}" || \
    fail "workflow runner persistent deployment hold was lost or is not quiescent"
}

require_installed_workflow_runner_hold_release_verifier() {
  local metadata parent_metadata source_sha256 target_sha256
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" && \
    -f "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" ]] || \
    fail "workflow runner hold-release verifier source is unavailable"
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" && \
    -f "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" ]] || \
    fail "installed workflow runner hold-release verifier is unavailable"
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" && \
    -d "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" ]] || \
    fail "installed workflow runner hold-release verifier directory is unavailable"
  parent_metadata="$(
    /usr/bin/stat --format='%u:%g:%a' -- \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" 2>/dev/null
  )" || fail "installed workflow runner hold-release verifier directory metadata is unavailable"
  [[ "${parent_metadata}" == "0:0:755" ]] || \
    fail "installed workflow runner hold-release verifier directory identity mismatch"
  metadata="$(
    /usr/bin/stat --format='%u:%g:%a:%h' -- \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" 2>/dev/null
  )" || fail "installed workflow runner hold-release verifier metadata is unavailable"
  [[ "${metadata}" == "0:0:755:1" ]] || \
    fail "installed workflow runner hold-release verifier identity mismatch"
  source_sha256="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
    fail "workflow runner hold-release verifier source hash is unavailable"
  target_sha256="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}")" || \
    fail "installed workflow runner hold-release verifier hash is unavailable"
  [[ "${target_sha256}" == "${source_sha256}" ]] || \
    fail "installed workflow runner hold-release verifier source drift"
}

require_workflow_runner_retirement_receipt_root() {
  local expected_uid expected_gid metadata
  expected_uid="$(id -u eom-api)" || fail "eom-api user identity is unavailable"
  expected_gid="$(id -g eom-api)" || fail "eom-api group identity is unavailable"
  metadata="$(
    sudo -n -u eom-api /usr/bin/stat --format='%F:%u:%g:%a' -- \
      "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}" 2>/dev/null
  )" || fail "workflow runner retirement receipt directory metadata is unavailable"
  [[ "${metadata}" == "directory:${expected_uid}:${expected_gid}:700" ]] || \
    fail "workflow runner retirement receipt directory identity mismatch"
}

verify_workflow_runner_hold_release_receipt() {
  local -a verifier_mode=()
  if (($# == 1)) && [[ "$1" == "--hold-lock-until-release-signal" ]]; then
    verifier_mode=("$1")
  elif (($# != 0)); then
    return 64
  fi
  [[ "${RELEASE_RECEIPT_FILE}" == \
    "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}/${RELEASE_EXECUTION_ID}.retirement-receipt.json" \
  ]] || fail "workflow runner retirement receipt path must match the expected execution"
  require_installed_workflow_runner_hold_release_verifier
  sudo -n -u eom-api /usr/bin/env -i \
    HOME=/var/lib/eom-api \
    PATH=/usr/bin:/bin \
    PYTHONSAFEPATH=1 \
    "${API_PYTHON}" -I "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" \
    --receipt-file "${RELEASE_RECEIPT_FILE}" \
    --execution-id "${RELEASE_EXECUTION_ID}" \
    --execution-revision-id "${RELEASE_EXECUTION_REVISION_ID}" \
    --checkpoint-sha256 "${RELEASE_CHECKPOINT_SHA256}" \
    --production-request-id "${RELEASE_PRODUCTION_REQUEST_ID}" \
    --production-plan-id "${RELEASE_PRODUCTION_PLAN_ID}" \
    --production-plan-sha256 "${RELEASE_PRODUCTION_PLAN_SHA256}" \
    --operator-id "${RELEASE_OPERATOR_ID}" \
    --receipt-sha256 "${RELEASE_RECEIPT_SHA256}" \
    "${verifier_mode[@]}"
}

release_workflow_runner_deployment_hold() {
  local target_present=false backup_present=false base_sha256_before base_sha256_after
  local activation_identity_before activation_identity_after
  workflow_runner_require_source_hold_file \
    "${WORKFLOW_RUNNER_HOLD_SOURCE}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
    fail "canonical workflow runner deployment hold source mismatch"
  workflow_runner_require_no_ineffective_runtime_mask || \
    fail "workflow runner runtime-mask residue must be reviewed before hold release"
  workflow_runner_require_base_unit_file "${WORKFLOW_RUNNER_FRAGMENT}" || \
    fail "workflow runner base unit identity mismatch before hold release"
  base_sha256_before="$(workflow_runner_file_sha256 "${WORKFLOW_RUNNER_FRAGMENT}")" || \
    fail "workflow runner base unit hash is unavailable before hold release"
  if [[ -e "${WORKFLOW_RUNNER_HOLD_TARGET}" || -L "${WORKFLOW_RUNNER_HOLD_TARGET}" ]]; then
    target_present=true
  fi
  if [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
    -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]]; then
    backup_present=true
  fi
  [[ "${target_present}" != true || "${backup_present}" != true ]] || \
    fail "conflicting workflow runner deployment hold materializations require review"

  # An output-loss retry after a completed release must be an exact no-op. The disabled state is
  # the durable reboot fence between release and the separate explicit enable-and-start action.
  if [[ "${target_present}" != true && "${backup_present}" != true ]]; then
    workflow_runner_released_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}" >/dev/null || \
      fail "workflow runner deployment hold is absent without a completed disabled release"
    printf '%s\n' "workflow_runner_deployment_hold=REPLAYED_RELEASED_INACTIVE_DISABLED"
    return 0
  fi

  if [[ "${target_present}" == true ]]; then
    if activation_identity_before="$(
      workflow_runner_deployment_hold_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      # Disable before removing the persistent .conf. A power loss at every later instruction
      # therefore reboots to an unscheduled runner even if systemd has not yet reloaded the move.
      sudo -n /usr/bin/systemctl disable "${WORKFLOW_RUNNER_SERVICE}" >/dev/null || \
        fail "workflow runner could not be disabled before hold release"
      activation_identity_after="$(
        workflow_runner_release_fenced_activation_identity \
          /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
      )" || \
        fail "workflow runner was not disabled under the persistent hold"
      workflow_runner_require_same_activation_identity \
        "${activation_identity_before}" "${activation_identity_after}" || \
        fail "workflow runner was invoked while its release reboot fence was installed"
      activation_identity_before="${activation_identity_after}"
    elif activation_identity_before="$(
      workflow_runner_release_fenced_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Idempotent retry after disable and before the atomic hold move.
    else
      fail "workflow runner deployment hold is not exact, disabled, and quiescent"
    fi
    sudo -n /usr/bin/mv -T \
      "${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
      fail "workflow runner deployment hold could not be moved to its release backup"
  else
    workflow_runner_require_hold_file \
      "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
      fail "workflow runner deployment hold release backup identity mismatch"
    if activation_identity_before="$(
      workflow_runner_cached_release_fenced_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Same-boot retry before daemon-reload; the manager still holds the removed path.
    elif activation_identity_before="$(
      workflow_runner_released_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Retry after daemon-reload or reboot, before the exact backup was removed.
    else
      fail "workflow runner must remain stopped and disabled while resuming hold release"
    fi
  fi

  # The unit is already persistently disabled. Removing the loaded drop-in never starts it, and a
  # reboot before or after this reload keeps it unscheduled. The exact backup makes the operation
  # resumable until the released state has been proven.
  sudo -n /usr/bin/systemctl daemon-reload || \
    fail "systemd could not reload the workflow runner hold release"
  activation_identity_after="$(
    workflow_runner_released_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner deployment hold release did not leave a quiescent unit"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked during deployment hold release"
  workflow_runner_require_base_unit_file "${WORKFLOW_RUNNER_FRAGMENT}" || \
    fail "workflow runner base unit identity changed during hold release"
  base_sha256_after="$(workflow_runner_file_sha256 "${WORKFLOW_RUNNER_FRAGMENT}")" || \
    fail "workflow runner base unit hash is unavailable after hold release"
  [[ "${base_sha256_after}" == "${base_sha256_before}" ]] || \
    fail "workflow runner base unit hash changed during hold release"
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
    fail "workflow runner deployment hold release backup changed unexpectedly"
  sudo -n /usr/bin/rm -- "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
    fail "workflow runner deployment hold release backup could not be removed"
  [[ ! -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" && \
    ! -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]] || \
    fail "workflow runner deployment hold release backup remains after removal"
  activation_identity_after="$(
    workflow_runner_released_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner changed state after deployment hold release"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked after deployment hold release"
  printf '%s\n' "workflow_runner_deployment_hold=RELEASED_INACTIVE_DISABLED"
  printf '%s\n' \
    "Explicitly enable --now eom-workflow-runner.service after the retirement receipt release."
}

release_workflow_runner_deployment_hold_after_verified_receipt() {
  local verifier_pid verifier_read_fd verifier_write_fd verifier_status verifier_confirmation
  coproc WORKFLOW_RUNNER_RECEIPT_VERIFIER {
    verify_workflow_runner_hold_release_receipt --hold-lock-until-release-signal
  }
  verifier_pid="${WORKFLOW_RUNNER_RECEIPT_VERIFIER_PID}"
  verifier_read_fd="${WORKFLOW_RUNNER_RECEIPT_VERIFIER[0]}"
  verifier_write_fd="${WORKFLOW_RUNNER_RECEIPT_VERIFIER[1]}"
  if ! IFS= read -r verifier_status <&"${verifier_read_fd}" || \
    [[ "${verifier_status}" != \
      "workflow_runner_hold_release_receipt=VERIFIED_LOCKED" ]]; then
    exec {verifier_write_fd}>&-
    wait "${verifier_pid}" || true
    return 1
  fi

  # The verifier keeps an exclusive flock on the exact checkpoint until this mutation has either
  # completed or failed. No official checkpoint writer can advance between validation and release.
  if ! release_workflow_runner_deployment_hold; then
    exec {verifier_write_fd}>&-
    wait "${verifier_pid}" || true
    return 1
  fi
  if ! printf '%s\n' "RELEASE_COMPLETE" >&"${verifier_write_fd}"; then
    exec {verifier_write_fd}>&-
    wait "${verifier_pid}" || true
    return 1
  fi
  exec {verifier_write_fd}>&-
  if ! IFS= read -r verifier_confirmation <&"${verifier_read_fd}" || \
    [[ "${verifier_confirmation}" != \
      "workflow_runner_hold_release_receipt=RELEASE_CONFIRMED" ]]; then
    wait "${verifier_pid}" || true
    return 1
  fi
  wait "${verifier_pid}"
}

verify_mock_exam_deployment_admission() {
  id eom-api >/dev/null 2>&1 || fail "eom-api system user is absent"
  # Establish a root-owned code boundary, then drop privileges before the helper
  # reads eom-api-owned checkpoints. Mutable repository Python is never run as root.
  sudo -n install -d -o root -g root -m 0755 /usr/local/libexec/eom-api
  sudo -n install -o root -g root -m 0755 \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_SOURCE}" \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}"
  cmp --silent \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_SOURCE}" \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}" || \
    fail "installed mock-exam deployment admission source drift"
  sudo -n -u eom-api /usr/bin/env -i \
    HOME=/var/lib/eom-api \
    PATH=/usr/bin:/bin \
    PYTHONSAFEPATH=1 \
    "${API_PYTHON}" -I "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}"
}

prepare_runtime_dependencies() {
  getent group eom-codex-auth >/dev/null || \
    fail "eom-codex-auth identity must be deployed before the API unit"
  sudo -n /usr/bin/bash "${REPOSITORY_ROOT}/scripts/api/migrate_release.sh" \
    --verify "${COMMIT}"
  sudo -n /usr/bin/bash "${REPOSITORY_ROOT}/scripts/api/bootstrap_runtime_role.sh"
}

reconcile_installed_catalog_runtime_privileges() {
  # The Catalog runner has its own DB role and its privilege matrix ships in
  # the platform wheel. Reconcile it after installing the wheel so a release
  # that introduces new pointer-only tables cannot restart Catalog against the
  # preceding release's grant set.
  sudo -n "${API_PYTHON}" \
    "${REPOSITORY_ROOT}/scripts/catalog/bootstrap_runtime_role.py"
}

reconcile_installed_hwpx_manager_runtime_privileges() {
  # The HWPX manager owns its build queues through a dedicated DB role. Keep
  # its closed privilege matrix synchronized after migrations add a new queue.
  sudo -n "${API_PYTHON}" \
    "${REPOSITORY_ROOT}/scripts/hwpx/bootstrap_manager_runtime_role.py"
}

cleanup() {
  if [[ -n "${STAGING_ROOT}" && -d "${STAGING_ROOT}" ]]; then
    rm -rf "${STAGING_ROOT}"
  fi
}
trap cleanup EXIT

[[ "$(id -un)" == "eom" ]] || fail "release builds must run as eom"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
CURRENT_BRANCH="$(git -C "${REPOSITORY_ROOT}" branch --show-current)"
branch_allowed=false
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${CURRENT_BRANCH}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"
[[ -x "${API_PYTHON}" ]] || fail "isolated eom-api Python is unavailable"

COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
VERSION="$(PYPROJECT="${REPOSITORY_ROOT}/apps/application_api/pyproject.toml" \
  "${API_PYTHON}" -c \
  'import os,pathlib,tomllib; print(tomllib.loads(pathlib.Path(os.environ["PYPROJECT"]).read_text())["project"]["version"])')"
BUILD_PARENT="/tmp/eom-api-build"
BUILD_ROOT=""
DIST_DIR=""

require_clean_tree() {
  [[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
    fail "working tree must be clean before a release build"
}

build_release() {
  require_clean_tree
  mkdir -p "${BUILD_PARENT}"
  BUILD_ROOT="$(mktemp -d "${BUILD_PARENT}/${COMMIT}.XXXXXX")"
  DIST_DIR="${BUILD_ROOT}/dist"
  mkdir -p "${DIST_DIR}"
  STAGING_ROOT="$(mktemp -d "${BUILD_ROOT}/staging.XXXXXX")"

  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${REPOSITORY_ROOT}" >/dev/null

  mkdir -p "${STAGING_ROOT}/contracts/eom_api_contracts/schemas"
  cp "${REPOSITORY_ROOT}/packages/api_contracts/pyproject.toml" \
    "${STAGING_ROOT}/contracts/pyproject.toml"
  cp -a "${REPOSITORY_ROOT}/packages/api_contracts/eom_api_contracts/." \
    "${STAGING_ROOT}/contracts/eom_api_contracts/"
  find "${STAGING_ROOT}/contracts/eom_api_contracts" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  cp "${REPOSITORY_ROOT}"/schemas/api/v1/*.schema.json \
    "${STAGING_ROOT}/contracts/eom_api_contracts/schemas/"
  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${STAGING_ROOT}/contracts" >/dev/null

  mkdir -p "${STAGING_ROOT}/application/eom_api"
  cp "${REPOSITORY_ROOT}/apps/application_api/pyproject.toml" \
    "${STAGING_ROOT}/application/pyproject.toml"
  cp -a "${REPOSITORY_ROOT}/apps/application_api/eom_api/." \
    "${STAGING_ROOT}/application/eom_api/"
  find "${STAGING_ROOT}/application/eom_api" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  mkdir -p "${STAGING_ROOT}/application/eom_api/openapi"
  cp "${REPOSITORY_ROOT}/api/openapi/eom-api-v1.openapi.json" \
    "${REPOSITORY_ROOT}/api/openapi/eom-api-v1.sha256" \
    "${STAGING_ROOT}/application/eom_api/openapi/"
  BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    COMMIT="${COMMIT}" VERSION="${VERSION}" STAGING_ROOT="${STAGING_ROOT}" \
    "${API_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

target = Path(os.environ["STAGING_ROOT"]) / "application" / "eom_api" / "build-info.json"
target.write_text(
    json.dumps(
        {
            "build_timestamp_utc": os.environ["BUILD_TIMESTAMP"],
            "package_version": os.environ["VERSION"],
            "source_commit": os.environ["COMMIT"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="ascii",
)
PY
  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${STAGING_ROOT}/application" >/dev/null

  inspect_release
  printf 'Built and inspected EOM Application API %s from %s.\n' "${VERSION}" "${COMMIT}"
  printf 'application_api_release_wheel_dir=%s\n' "${DIST_DIR}"
}

inspect_release() {
  DIST_DIR="${DIST_DIR}" EXPECTED_COMMIT="${COMMIT}" EXPECTED_VERSION="${VERSION}" \
    REPOSITORY_ROOT="${REPOSITORY_ROOT}" API_PYTHON="${API_PYTHON}" \
    "${API_PYTHON}" - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

dist = Path(os.environ["DIST_DIR"])
wheels = sorted(dist.glob("*.whl"))
if len(wheels) != 3:
    raise SystemExit(f"expected 3 wheels, found {len(wheels)}")
by_prefix = {wheel.name.split("-", 1)[0]: wheel for wheel in wheels}
required_wheels = {"eom_platform", "eom_api_contracts", "eom_application_api"}
if set(by_prefix) != required_wheels:
    raise SystemExit(f"unexpected wheel set: {sorted(by_prefix)}")

with zipfile.ZipFile(by_prefix["eom_application_api"]) as archive:
    names = set(archive.namelist())
    required = {
        "eom_api/__init__.py",
        "eom_api/app.py",
        "eom_api/build_info.py",
        "eom_api/build-info.json",
        "eom_api/cli.py",
        "eom_api/mock_exam_production_cli.py",
        "eom_api/runtime_isolation_pidfd.py",
        "eom_api/runtime_isolation_verifier.py",
        "eom_api/routers/control_plane.py",
        "eom_api/routers/knowledge_analysis.py",
        "eom_api/routers/assessment_assemblies.py",
        "eom_api/routers/item_bank.py",
        "eom_api/services/command_adapter.py",
        "eom_api/services/query_adapter.py",
        "eom_api/services/catalog_application_client.py",
        "eom_api/services/mock_exam_generation_block_resolver.py",
        "eom_api/services/mock_exam_production_application.py",
        "eom_api/services/mock_exam_production_checkpoint_store.py",
        "eom_api/services/mock_exam_production_composition.py",
        "eom_api/services/mock_exam_production_coordinator.py",
        "eom_api/services/mock_exam_production_release_resolver.py",
        "eom_api/services/mock_exam_production_runner.py",
        "eom_api/services/control_plane_adapter.py",
        "eom_api/openapi/eom-api-v1.openapi.json",
        "eom_api/openapi/eom-api-v1.sha256",
    }
    if missing := required - names:
        raise SystemExit(f"Application API wheel resources missing: {sorted(missing)}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    entry_point_source = archive.read(entry_points).decode()
    if "eom-api = eom_api.cli:main" not in entry_point_source:
        raise SystemExit("eom-api console entry point missing")
    if (
        "eom-api-runtime-isolation = eom_api.runtime_isolation_verifier:main"
        not in entry_point_source
    ):
        raise SystemExit("runtime isolation console entry point missing")
    build = json.loads(archive.read("eom_api/build-info.json"))
    if build["source_commit"] != os.environ["EXPECTED_COMMIT"]:
        raise SystemExit("Application API wheel source commit mismatch")
    if build["package_version"] != os.environ["EXPECTED_VERSION"]:
        raise SystemExit("Application API wheel version mismatch")
    canonical_openapi = (
        Path(os.environ["REPOSITORY_ROOT"]) / "api/openapi/eom-api-v1.openapi.json"
    ).read_bytes()
    canonical_openapi_checksum = (
        Path(os.environ["REPOSITORY_ROOT"]) / "api/openapi/eom-api-v1.sha256"
    ).read_bytes()
    packaged_openapi = archive.read("eom_api/openapi/eom-api-v1.openapi.json")
    packaged_checksum = archive.read("eom_api/openapi/eom-api-v1.sha256")
    if packaged_openapi != canonical_openapi or packaged_checksum != canonical_openapi_checksum:
        raise SystemExit("Application API packaged OpenAPI differs from canonical release artifacts")
    if packaged_checksum.decode("ascii").split()[0] != hashlib.sha256(packaged_openapi).hexdigest():
        raise SystemExit("Application API packaged OpenAPI checksum mismatch")
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    for member in sorted(required):
        if member not in record:
            raise SystemExit(f"Application API runtime missing from RECORD: {member}")

with zipfile.ZipFile(by_prefix["eom_api_contracts"]) as archive:
    names = set(archive.namelist())
    schemas = {
        name
        for name in names
        if name.startswith("eom_api_contracts/schemas/") and name.endswith(".schema.json")
    }
    expected_api_schemas = {
        "eom_api_contracts/schemas/assessment-item-occurrence-v1.schema.json",
        "eom_api_contracts/schemas/assessment-item-occurrence-v2.schema.json",
        "eom_api_contracts/schemas/assessment-learning-batch-v1.schema.json",
        "eom_api_contracts/schemas/assessment-learning-exam-v1.schema.json",
        "eom_api_contracts/schemas/assessment-learning-page-v1.schema.json",
        "eom_api_contracts/schemas/auth.schema.json",
        "eom_api_contracts/schemas/common.schema.json",
        "eom_api_contracts/schemas/curriculum-graph-capability-v1.schema.json",
        "eom_api_contracts/schemas/errors.schema.json",
        "eom_api_contracts/schemas/hwpx.schema.json",
        "eom_api_contracts/schemas/hwpx-v2.schema.json",
        "eom_api_contracts/schemas/item-bank-entry-v1.schema.json",
        "eom_api_contracts/schemas/items.schema.json",
        "eom_api_contracts/schemas/mock-exam-assembly-plan-v1.schema.json",
        "eom_api_contracts/schemas/mock-exam-assembly-plan-v2.schema.json",
        "eom_api_contracts/schemas/mock-exam-explicit-analysis-review-set-v1.schema.json",
        "eom_api_contracts/schemas/mock-exam-production-execution-v1.schema.json",
        "eom_api_contracts/schemas/mock-exam-production-execution-v2.schema.json",
        "eom_api_contracts/schemas/mock-exam-production-retirement-v1.schema.json",
        "eom_api_contracts/schemas/mock-exam-review-eligibility-v1.schema.json",
        "eom_api_contracts/schemas/mock-exam-review-eligibility-v2.schema.json",
        "eom_api_contracts/schemas/operators.schema.json",
        "eom_api_contracts/schemas/production-item-candidate-v1.schema.json",
        "eom_api_contracts/schemas/production-item-candidate-v2.schema.json",
        "eom_api_contracts/schemas/resources.schema.json",
        "eom_api_contracts/schemas/workflow-start-v1.schema.json",
    }
    if schemas != expected_api_schemas:
        raise SystemExit(
            "expected exactly 26 packaged API schemas including Workflow-start and mock-exam "
            "production execution/review/retirement contracts, "
            f"missing={sorted(expected_api_schemas - schemas)} "
            f"unexpected={sorted(schemas - expected_api_schemas)}"
        )
    required_contract_runtime = {
        "eom_api_contracts/__init__.py",
        "eom_api_contracts/assessment_assemblies.py",
        "eom_api_contracts/item_bank.py",
        "eom_api_contracts/mock_exam_execution.py",
        "eom_api_contracts/mock_exam_retirement.py",
        "eom_api_contracts/workflows.py",
    }
    if missing := required_contract_runtime - names:
        raise SystemExit(f"mock-exam API contract runtime missing from wheel: {sorted(missing)}")
    canonical_api_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/api/v1"
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    for member in sorted(expected_api_schemas):
        canonical = canonical_api_root / Path(member).name
        if archive.read(member) != canonical.read_bytes():
            raise SystemExit(f"API schema resource drift: {canonical.name}")
        if member not in record:
            raise SystemExit(f"API schema resource missing from RECORD: {canonical.name}")
    for member in sorted(required_contract_runtime):
        if member not in record:
            raise SystemExit(f"API contract runtime missing from RECORD: {member}")

workflow_prefix = "eom_workflow/resources/"
canonical_workflow_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/workflow"
workflow_resources = {
    path.relative_to(canonical_workflow_root).as_posix()
    for path in canonical_workflow_root.rglob("*.schema.json")
}
platform_wheel = by_prefix["eom_platform"]
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    worker_runtime = {
        "eom_orchestrator/capability_observer.py",
        "eom_orchestrator/capacity_controller.py",
        "eom_orchestrator/live_preflight.py",
        "eom_orchestrator/runtime_configuration.py",
        "eom_orchestrator/settings.py",
        "eom_orchestrator/worker.py",
        "eom_orchestrator/worker_auth.py",
        "eom_orchestrator/auth_enrollment.py",
        "eom_orchestrator/worker_auth_exec.py",
        "eom_orchestrator/worker_device_login_exec.py",
        "eom_orchestrator/worker_exec.py",
        "eom_orchestrator/worker_systemd.py",
        "eom_orchestrator/codex_auth_broker_client.py",
        "eom_orchestrator/codex_auth_broker_server.py",
    }
    actor_runtime = {
        "eom_workflow_runner/actor_authorization.py",
        "eom_workflow_runner/actor_authorization_adapters.py",
        "eom_workflow_runner/settings.py",
    }
    identity_recovery_runtime = {
        "eom_operator_identity/errors.py",
        "eom_identity_service/local_admin_recovery.py",
        "eomctl/operator.py",
    }
    control_plane_runtime = {
        "eom_orchestrator/capability_observer.py",
        "eom_orchestrator/capacity_controller.py",
        "eom_orchestrator/control_artifacts.py",
        "eom_orchestrator/control_bootstrap.py",
        "eom_orchestrator/control_command_processor.py",
        "eom_orchestrator/control_commands.py",
        "eom_orchestrator/control_models.py",
        "eom_orchestrator/control_service.py",
        "eom_orchestrator/execution_materializer.py",
        "eom_orchestrator/execution_resolver.py",
        "eom_orchestrator/migration.py",
        "eom_orchestrator/workflow_job_retirement.py",
        "eom_orchestrator/legacy_item_extraction_artifact.py",
        "eom_orchestrator/legacy_item_extraction_bootstrap.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_artifact.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_bootstrap.py",
        "eom_orchestrator/preset_lifecycle.py",
        "eom_workflow/control_plane.py",
        "eom_workflow/control_schemas.py",
        "eom_workflow/models.py",
        "eom_workflow_runner/composition.py",
        "eom_workflow_runner/engine.py",
        "eom_workflow_runner/models.py",
        "eom_workflow_runner/repository.py",
        "eom_workflow_runner/mock_exam_production_retirement.py",
        "eom_workflow_runner/retirement_quiescence.py",
        "eom_workflow_runner/systemd_retirement_quiescence.py",
        "eomctl/cli.py",
        "eomctl/control_plane.py",
        "eomctl/knowledge.py",
        "eomctl/legacy_assessment.py",
    }
    catalog_staging_runtime = {
        "eom_image_contracts/models.py",
        "eom_image_contracts/safe_svg.py",
        "eom_image_contracts/validation.py",
        "eom_hwpx_contracts/models.py",
        "eom_hwpx_contracts/content_team_equations.py",
        "eom_hwpx_contracts/content_team_markdown.py",
        "eom_hwpx_contracts/validation.py",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-editorial-question-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-render-request-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-build-result-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v3.schema.json",
        "eom_catalog_contracts/assessment_item.py",
        "eom_catalog_contracts/assessment_assembly.py",
        "eom_catalog_contracts/approved_item_graph_publication.py",
        "eom_catalog_contracts/application.py",
        "eom_catalog_contracts/item_review.py",
        "eom_catalog_contracts/knowledge.py",
        "eom_catalog_contracts/knowledge_analysis_batch.py",
        "eom_catalog_contracts/item_origin.py",
        "eom_catalog_contracts/legacy_assessment.py",
        "eom_catalog_contracts/legacy_extraction_batch.py",
        "eom_catalog_contracts/legacy_item_learning.py",
        "eom_catalog_contracts/legacy_knowledge.py",
        "eom_catalog_contracts/legacy_usage.py",
        "eom_catalog_contracts/validation.py",
        "eom_catalog_contracts/mock_exam_planner.py",
        "eom_catalog_contracts/mock_exam_production_plan.py",
        "eom_catalog_service/approved_item_graph_publication_service.py",
        "eom_catalog_service/application_runner.py",
        "eom_catalog_service/application_server.py",
        "eom_catalog_service/automatic_item_graph_publication_service.py",
        "eom_catalog_service/curriculum_graph_structure.py",
        "eom_catalog_service/generated_stimulus.py",
        "eom_catalog_service/item_content_import.py",
        "eom_catalog_service/item_origin_models.py",
        "eom_catalog_service/item_origin_service.py",
        "eom_catalog_service/knowledge_analysis_risk.py",
        "eom_catalog_service/knowledge_analysis_batch_models.py",
        "eom_catalog_service/knowledge_analysis_batch_service.py",
        "eom_catalog_service/knowledge_analysis_service.py",
        "eom_catalog_service/knowledge_analysis_sources.py",
        "eom_catalog_service/knowledge_graph_models.py",
        "eom_catalog_service/knowledge_graph_publication_service.py",
        "eom_catalog_service/knowledge_stimulus.py",
        "eom_catalog_service/knowledge_retrieval_service.py",
        "eom_catalog_service/local_image_adapter.py",
        "eom_catalog_service/mock_exam_assembly_service.py",
        "eom_catalog_service/mock_exam_candidate_repository.py",
        "eom_catalog_service/mock_exam_item_review_publication_service.py",
        "eom_catalog_service/legacy_usage_models.py",
        "eom_catalog_service/legacy_usage_service.py",
        "eom_catalog_service/legacy_xlsx.py",
        "eom_catalog_service/legacy_knowledge_intake_service.py",
        "eom_catalog_service/legacy_assessment_bundle_discovery.py",
        "eom_catalog_service/legacy_assessment_models.py",
        "eom_catalog_service/legacy_assessment_packages.py",
        "eom_catalog_service/legacy_assessment_registry.py",
        "eom_catalog_service/legacy_assessment_rights.py",
        "eom_catalog_service/legacy_item_acceptance_service.py",
        "eom_catalog_service/legacy_item_extraction_batch_models.py",
        "eom_catalog_service/legacy_item_extraction_batch_service.py",
        "eom_catalog_service/legacy_item_extraction_service.py",
        "eom_catalog_service/legacy_item_editorial_compatibility_service.py",
        "eom_catalog_service/legacy_item_editorial_validation.py",
        "eom_catalog_service/legacy_item_learning_models.py",
        "eom_catalog_service/legacy_item_learning_service.py",
        "eom_catalog_service/legacy_item_promotion_service.py",
        "eom_catalog_service/legacy_source_inventory.py",
        "eom_catalog_service/settings.py",
        "eom_catalog_service/staging.py",
        "eom_catalog_service/vector_stimulus.py",
        "eom_catalog_service/workflow_catalog.py",
        "eom_catalog_service/registry_service.py",
        "eom_catalog_service/runtime_privileges.py",
    }
    hwpx_application_runtime = {
        "eom_hwpx_manager/application_adapter.py",
        "eom_hwpx_manager/application_service.py",
        "eom_hwpx_manager/application_state.py",
        "eom_hwpx_manager/assembly_render_projection.py",
        "eom_hwpx_manager/capability.py",
        "eom_hwpx_manager/content_team_exam_service.py",
        "eom_hwpx_manager/content_team_service.py",
        "eom_hwpx_manager/content_team_compatibility_evidence.py",
        "eom_hwpx_manager/download_server.py",
        "eom_hwpx_manager/errors.py",
        "eom_hwpx_manager/markdown_structure.py",
        "eom_hwpx_manager/models.py",
        "eom_hwpx_manager/exam_application_service.py",
        "eom_hwpx_manager/protocol.py",
        "eom_hwpx_manager/question_template.py",
        "eom_hwpx_manager/question_template_service.py",
        "eom_hwpx_manager/runner.py",
        "eom_hwpx_manager/runtime_privileges.py",
    }
    if missing := identity_recovery_runtime - names:
        raise SystemExit(f"identity recovery runtime missing from wheel: {sorted(missing)}")
    if missing := (
        worker_runtime
        | actor_runtime
        | control_plane_runtime
        | catalog_staging_runtime
        | hwpx_application_runtime
    ) - names:
        raise SystemExit(f"platform runtime missing from wheel: {sorted(missing)}")
    settings_source = archive.read("eom_orchestrator/settings.py")
    for forbidden in (
        b"parents[",
        b"worker-slots.example.yaml",
        b"/home/eom/EOM",
    ):
        if forbidden in settings_source:
            raise SystemExit("Orchestrator settings retain implicit source/install path inference")
    workflow_settings_source = archive.read("eom_workflow_runner/settings.py")
    for forbidden in (
        b"parents[",
        b".example.yaml",
        b"/home/eom/EOM",
    ):
        if forbidden in workflow_settings_source:
            raise SystemExit("workflow settings retain implicit source/install path inference")
    for required in (
        b"/etc/eom/workflows/generic-item-development.yaml",
        b"/etc/eom/human-actors.yaml",
        b"/etc/eom/workflow-runner.yaml",
        b"/etc/eom/workflow-prompts",
    ):
        if required not in workflow_settings_source:
            raise SystemExit("workflow settings operator path contract is missing")
    legacy_graph_source = archive.read(
        "eom_catalog_service/legacy_item_graph_learning_service.py"
    )
    if (
        b"\nMAX_AUTOMATIC_GRAPH_BATCH_SIZE = 16\n" not in legacy_graph_source
        or b"    MAX_AUTOMATIC_GRAPH_BATCH_SIZE,\n" in legacy_graph_source
    ):
        raise SystemExit("legacy Graph automation must preserve its local 1..16 batch contract")
    packaged = {
        name.removeprefix(workflow_prefix)
        for name in names
        if name.startswith(workflow_prefix) and name.endswith(".schema.json")
    }
    if packaged != workflow_resources:
        raise SystemExit(
            "workflow schema wheel resources mismatch: "
            f"expected={sorted(workflow_resources)} actual={sorted(packaged)}"
        )
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    for member in sorted(worker_runtime):
        if member not in record:
            raise SystemExit(f"fixed worker runtime missing from RECORD: {member}")
    for member in sorted(actor_runtime):
        if member not in record:
            raise SystemExit(f"workflow actor runtime missing from RECORD: {member}")
    for member in sorted(identity_recovery_runtime):
        if member not in record:
            raise SystemExit(f"identity recovery runtime missing from RECORD: {member}")
    for member in sorted(control_plane_runtime):
        if member not in record:
            raise SystemExit(f"Codex control-plane runtime missing from RECORD: {member}")
    for member in sorted(catalog_staging_runtime):
        if member not in record:
            raise SystemExit(f"Catalog staging runtime missing from RECORD: {member}")
    for member in sorted(hwpx_application_runtime):
        if member not in record:
            raise SystemExit(f"HWPX application runtime missing from RECORD: {member}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    entry_point_source = archive.read(entry_points).decode()
    if "eomctl = eomctl.cli:app" not in entry_point_source:
        raise SystemExit("eomctl console entry point missing")
    if "eom-hwpx-application-runner = eom_hwpx_manager.runner:main" not in archive.read(
        entry_points
    ).decode():
        raise SystemExit("HWPX application runner console entry point missing")
    if "eom-catalog-application-runner = eom_catalog_service.application_runner:main" not in archive.read(
        entry_points
    ).decode():
        raise SystemExit("Catalog application runner console entry point missing")
    worker_exec_source = (
        Path(os.environ["REPOSITORY_ROOT"])
        / "services/orchestrator/eom_orchestrator/worker_exec.py"
    )
    if archive.read("eom_orchestrator/worker_exec.py") != worker_exec_source.read_bytes():
        raise SystemExit("root-installed worker executable source drift")
    worker_auth_exec_source = (
        Path(os.environ["REPOSITORY_ROOT"])
        / "services/orchestrator/eom_orchestrator/worker_auth_exec.py"
    )
    if archive.read("eom_orchestrator/worker_auth_exec.py") != worker_auth_exec_source.read_bytes():
        raise SystemExit("root-installed worker authentication executable source drift")
    for logical_name in sorted(workflow_resources):
        member = workflow_prefix + logical_name
        if archive.read(member) != (canonical_workflow_root / logical_name).read_bytes():
            raise SystemExit(f"workflow schema resource drift: {logical_name}")
        if member not in record:
            raise SystemExit(f"workflow schema resource missing from RECORD: {logical_name}")

catalog_prefix = "eom_catalog_contracts/resources/"
catalog_resources = {
    "assessment-assembly/mock-exam-assembly-cohort-v1.schema.json": "schemas/assessment-assembly/mock-exam-assembly-cohort-v1.schema.json",
    "assessment-assembly/mock-exam-assembly-manifest-v1.schema.json": "schemas/assessment-assembly/mock-exam-assembly-manifest-v1.schema.json",
    "assessment-assembly/mock-exam-assembly-manifest-v2.schema.json": "schemas/assessment-assembly/mock-exam-assembly-manifest-v2.schema.json",
    "assessment-assembly/mock-exam-assembly-manifest-v3.schema.json": "schemas/assessment-assembly/mock-exam-assembly-manifest-v3.schema.json",
    "assessment-assembly/mock-exam-assembly-plan-v1.schema.json": "schemas/assessment-assembly/mock-exam-assembly-plan-v1.schema.json",
    "assessment-assembly/mock-exam-assembly-plan-v2.schema.json": "schemas/assessment-assembly/mock-exam-assembly-plan-v2.schema.json",
    "assessment-assembly/mock-exam-assembly-policy-v1.schema.json": "schemas/assessment-assembly/mock-exam-assembly-policy-v1.schema.json",
    "assessment-assembly/mock-exam-layout-policy-v1.schema.json": "schemas/assessment-assembly/mock-exam-layout-policy-v1.schema.json",
    "assessment-assembly/mock-exam-rating-policy-v1.schema.json": "schemas/assessment-assembly/mock-exam-rating-policy-v1.schema.json",
    "assessment-assembly/mock-exam-item-review-decision-v1.schema.json": "schemas/assessment-assembly/mock-exam-item-review-decision-v1.schema.json",
    "assessment-assembly/mock-exam-item-review-decision-v2.schema.json": "schemas/assessment-assembly/mock-exam-item-review-decision-v2.schema.json",
    "assessment-assembly/mock-exam-item-review-publication-command-v1.schema.json": "schemas/assessment-assembly/mock-exam-item-review-publication-command-v1.schema.json",
    "assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json": "schemas/assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json",
    "assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json": "schemas/assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json",
    "assessment-assembly/mock-exam-production-plan-v1.schema.json": "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json",
    "assessment-assembly/mock-exam-production-plan-v2.schema.json": "schemas/assessment-assembly/mock-exam-production-plan-v2.schema.json",
    "assessment-assembly/mock-exam-review-eligibility-query-v1.schema.json": "schemas/assessment-assembly/mock-exam-review-eligibility-query-v1.schema.json",
    "assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json": "schemas/assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json",
    "assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json": "schemas/assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json",
    "catalog-application/catalog-application-request-v1.schema.json": "schemas/catalog-application/catalog-application-request-v1.schema.json",
    "catalog-application/catalog-application-response-v1.schema.json": "schemas/catalog-application/catalog-application-response-v1.schema.json",
    "catalog-application/catalog-application-request-v2.schema.json": "schemas/catalog-application/catalog-application-request-v2.schema.json",
    "catalog-application/catalog-application-response-v2.schema.json": "schemas/catalog-application/catalog-application-response-v2.schema.json",
    "catalog-application/catalog-application-request-v3.schema.json": "schemas/catalog-application/catalog-application-request-v3.schema.json",
    "catalog-application/catalog-application-response-v3.schema.json": "schemas/catalog-application/catalog-application-response-v3.schema.json",
    "catalog-application/catalog-application-request-v4.schema.json": "schemas/catalog-application/catalog-application-request-v4.schema.json",
    "catalog-application/catalog-application-response-v4.schema.json": "schemas/catalog-application/catalog-application-response-v4.schema.json",
    "catalog-application/catalog-application-request-v5.schema.json": "schemas/catalog-application/catalog-application-request-v5.schema.json",
    "catalog-application/catalog-application-response-v5.schema.json": "schemas/catalog-application/catalog-application-response-v5.schema.json",
    "catalog-application/catalog-application-response-v6.schema.json": "schemas/catalog-application/catalog-application-response-v6.schema.json",
    "catalog-application/catalog-application-request-v6.schema.json": "schemas/catalog-application/catalog-application-request-v6.schema.json",
    "catalog-application/catalog-application-request-v7.schema.json": "schemas/catalog-application/catalog-application-request-v7.schema.json",
    "catalog-application/catalog-application-request-v8.schema.json": "schemas/catalog-application/catalog-application-request-v8.schema.json",
    "catalog-application/catalog-application-request-v9.schema.json": "schemas/catalog-application/catalog-application-request-v9.schema.json",
    "catalog-application/catalog-application-request-v10.schema.json": "schemas/catalog-application/catalog-application-request-v10.schema.json",
    "catalog-application/catalog-application-response-v7.schema.json": "schemas/catalog-application/catalog-application-response-v7.schema.json",
    "catalog-application/catalog-application-response-v8.schema.json": "schemas/catalog-application/catalog-application-response-v8.schema.json",
    "catalog-application/catalog-application-response-v9.schema.json": "schemas/catalog-application/catalog-application-response-v9.schema.json",
    "catalog-application/catalog-application-response-v10.schema.json": "schemas/catalog-application/catalog-application-response-v10.schema.json",
    "catalog-application/catalog-application-request-v11.schema.json": "schemas/catalog-application/catalog-application-request-v11.schema.json",
    "catalog-application/catalog-application-response-v11.schema.json": "schemas/catalog-application/catalog-application-response-v11.schema.json",
    "catalog-application/catalog-application-request-v12.schema.json": "schemas/catalog-application/catalog-application-request-v12.schema.json",
    "catalog-application/catalog-application-response-v12.schema.json": "schemas/catalog-application/catalog-application-response-v12.schema.json",
    "catalog-application/catalog-item-media-request-v1.schema.json": "schemas/catalog-application/catalog-item-media-request-v1.schema.json",
    "catalog-application/catalog-item-media-response-v1.schema.json": "schemas/catalog-application/catalog-item-media-response-v1.schema.json",
    "catalog-application/catalog-assessment-page-list-request-v1.schema.json": "schemas/catalog-application/catalog-assessment-page-list-request-v1.schema.json",
    "catalog-application/catalog-assessment-page-list-response-v1.schema.json": "schemas/catalog-application/catalog-assessment-page-list-response-v1.schema.json",
    "catalog-application/catalog-assessment-page-media-request-v1.schema.json": "schemas/catalog-application/catalog-assessment-page-media-request-v1.schema.json",
    "catalog-application/catalog-assessment-page-media-response-v1.schema.json": "schemas/catalog-application/catalog-assessment-page-media-response-v1.schema.json",
    "knowledge/knowledge-analysis-batch-request-v1.schema.json": "schemas/knowledge/knowledge-analysis-batch-request-v1.schema.json",
    "knowledge/knowledge-analysis-batch-request-v2.schema.json": "schemas/knowledge/knowledge-analysis-batch-request-v2.schema.json",
    "knowledge/knowledge-analysis-batch-request-v3.schema.json": "schemas/knowledge/knowledge-analysis-batch-request-v3.schema.json",
    "knowledge/knowledge-analysis-batch-request-v4.schema.json": "schemas/knowledge/knowledge-analysis-batch-request-v4.schema.json",
    "knowledge/approved-item-graph-publication-command-v1.schema.json": "schemas/knowledge/approved-item-graph-publication-command-v1.schema.json",
    "knowledge/approved-item-graph-publication-result-v1.schema.json": "schemas/knowledge/approved-item-graph-publication-result-v1.schema.json",
    "content-intake/intake-manifest-v1.schema.json": "schemas/content-intake/intake-manifest-v1.schema.json",
    "content-intake/mapping-proposal-v1.schema.json": "schemas/content-intake/mapping-proposal-v1.schema.json",
    "content-intake/uncertainties-v1.schema.json": "schemas/content-intake/uncertainties-v1.schema.json",
    "content-intake/human-decision-v1.schema.json": "schemas/content-intake/human-decision-v1.schema.json",
    "content-pack/content-pack-v1.schema.json": "schemas/content-pack/content-pack-v1.schema.json",
    "content-pack/content-pack-v2.schema.json": "schemas/content-pack/content-pack-v2.schema.json",
    "content-pack/profile-v1.schema.json": "schemas/content-pack/profile-v1.schema.json",
    "content-pack/prompt-envelope-v1.schema.json": "schemas/content-pack/prompt-envelope-v1.schema.json",
    "curriculum/integrated-science-editorial-outline-v1.schema.json": "schemas/curriculum/integrated-science-editorial-outline-v1.schema.json",
    "guidance/eom-guidance-markdown-control-v1.schema.json": "schemas/guidance/eom-guidance-markdown-control-v1.schema.json",
    "educational-document/educational-document-registration-receipt-v1.schema.json": "schemas/educational-document/educational-document-registration-receipt-v1.schema.json",
    "educational-document/educational-document-registration-receipt-v2.schema.json": "schemas/educational-document/educational-document-registration-receipt-v2.schema.json",
    "educational-document/educational-document-registration-request-v1.schema.json": "schemas/educational-document/educational-document-registration-request-v1.schema.json",
    "educational-document/educational-document-registration-request-v2.schema.json": "schemas/educational-document/educational-document-registration-request-v2.schema.json",
    "educational-document/educational-document-revision-manifest-v1.schema.json": "schemas/educational-document/educational-document-revision-manifest-v1.schema.json",
    "educational-document/educational-document-revision-manifest-v2.schema.json": "schemas/educational-document/educational-document-revision-manifest-v2.schema.json",
    "educational-document/educational-document-rights-attestation-v1.schema.json": "schemas/educational-document/educational-document-rights-attestation-v1.schema.json",
    "educational-document/educational-document-types-v1.schema.json": "schemas/educational-document/educational-document-types-v1.schema.json",
    "item-registry/assessment-item-content-v1.schema.json": "schemas/item-registry/assessment-item-content-v1.schema.json",
    "item-registry/assessment-item-content-v2.schema.json": "schemas/item-registry/assessment-item-content-v2.schema.json",
    "item-registry/assessment-item-content-v3.schema.json": "schemas/item-registry/assessment-item-content-v3.schema.json",
    "item-registry/item-revision-manifest-v1.schema.json": "schemas/item-registry/item-revision-manifest-v1.schema.json",
    "item-origin/item-origin-types-v1.schema.json": "schemas/item-origin/item-origin-types-v1.schema.json",
    "item-origin/organization-revision-v1.schema.json": "schemas/item-origin/organization-revision-v1.schema.json",
    "item-origin/assessment-occurrence-revision-v1.schema.json": "schemas/item-origin/assessment-occurrence-revision-v1.schema.json",
    "item-origin/assessment-occurrence-revision-v2.schema.json": "schemas/item-origin/assessment-occurrence-revision-v2.schema.json",
    "item-origin/item-origin-profile-v1.schema.json": "schemas/item-origin/item-origin-profile-v1.schema.json",
    "legacy-assessment/legacy-assessment-types-v1.schema.json": "schemas/legacy-assessment/legacy-assessment-types-v1.schema.json",
    "legacy-assessment/assessment-source-bundle-proposal-v1.schema.json": "schemas/legacy-assessment/assessment-source-bundle-proposal-v1.schema.json",
    "legacy-assessment/assessment-source-bundle-v1.schema.json": "schemas/legacy-assessment/assessment-source-bundle-v1.schema.json",
    "legacy-assessment/assessment-layout-observation-v1.schema.json": "schemas/legacy-assessment/assessment-layout-observation-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-request-v1.schema.json": "schemas/legacy-assessment/legacy-item-extraction-request-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-receipt-v1.schema.json": "schemas/legacy-assessment/legacy-item-extraction-receipt-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-result-v1.schema.json": "schemas/legacy-assessment/legacy-item-extraction-result-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-acceptance-v1.schema.json": "schemas/legacy-assessment/legacy-item-extraction-acceptance-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-batch-v1.schema.json": "schemas/legacy-assessment/legacy-item-extraction-batch-v1.schema.json",
    "legacy-assessment/legacy-item-extraction-batch-v2.schema.json": "schemas/legacy-assessment/legacy-item-extraction-batch-v2.schema.json",
    "legacy-assessment/legacy-item-corpus-coverage-v1.schema.json": "schemas/legacy-assessment/legacy-item-corpus-coverage-v1.schema.json",
    "legacy-assessment/legacy-item-promotion-request-v1.schema.json": "schemas/legacy-assessment/legacy-item-promotion-request-v1.schema.json",
    "legacy-assessment/legacy-item-editorial-compatibility-policy-v1.schema.json": "schemas/legacy-assessment/legacy-item-editorial-compatibility-policy-v1.schema.json",
    "legacy-assessment/legacy-item-editorial-compatibility-request-v1.schema.json": "schemas/legacy-assessment/legacy-item-editorial-compatibility-request-v1.schema.json",
    "legacy-assessment/legacy-item-editorial-compatibility-proposal-v1.schema.json": "schemas/legacy-assessment/legacy-item-editorial-compatibility-proposal-v1.schema.json",
    "legacy-assessment/legacy-item-editorial-compatibility-result-v1.schema.json": "schemas/legacy-assessment/legacy-item-editorial-compatibility-result-v1.schema.json",
    "knowledge/knowledge-types-v1.schema.json": "schemas/knowledge/knowledge-types-v1.schema.json",
    "knowledge/knowledge-types-v2.schema.json": "schemas/knowledge/knowledge-types-v2.schema.json",
    "knowledge/knowledge-analysis-request-v1.schema.json": "schemas/knowledge/knowledge-analysis-request-v1.schema.json",
    "knowledge/knowledge-analysis-result-v1.schema.json": "schemas/knowledge/knowledge-analysis-result-v1.schema.json",
    "knowledge/knowledge-analysis-types-v2.schema.json": "schemas/knowledge/knowledge-analysis-types-v2.schema.json",
    "knowledge/knowledge-analysis-request-v2.schema.json": "schemas/knowledge/knowledge-analysis-request-v2.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v1.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v1.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v1.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v1.schema.json",
    "knowledge/knowledge-analysis-risk-policy-v1.schema.json": "schemas/knowledge/knowledge-analysis-risk-policy-v1.schema.json",
    "knowledge/knowledge-analysis-review-decision-v1.schema.json": "schemas/knowledge/knowledge-analysis-review-decision-v1.schema.json",
    "knowledge/knowledge-analysis-result-v2.schema.json": "schemas/knowledge/knowledge-analysis-result-v2.schema.json",
    "knowledge/knowledge-analysis-types-v3.schema.json": "schemas/knowledge/knowledge-analysis-types-v3.schema.json",
    "knowledge/knowledge-analysis-types-v4.schema.json": "schemas/knowledge/knowledge-analysis-types-v4.schema.json",
    "knowledge/knowledge-analysis-types-v5.schema.json": "schemas/knowledge/knowledge-analysis-types-v5.schema.json",
    "knowledge/knowledge-assessment-page-image-observation-v2.schema.json": "schemas/knowledge/knowledge-assessment-page-image-observation-v2.schema.json",
    "knowledge/knowledge-analysis-request-v3.schema.json": "schemas/knowledge/knowledge-analysis-request-v3.schema.json",
    "knowledge/knowledge-analysis-request-v4.schema.json": "schemas/knowledge/knowledge-analysis-request-v4.schema.json",
    "knowledge/knowledge-analysis-request-v5.schema.json": "schemas/knowledge/knowledge-analysis-request-v5.schema.json",
    "knowledge/knowledge-analysis-request-v6.schema.json": "schemas/knowledge/knowledge-analysis-request-v6.schema.json",
    "knowledge/knowledge-analysis-request-v7.schema.json": "schemas/knowledge/knowledge-analysis-request-v7.schema.json",
    "knowledge/knowledge-analysis-request-v8.schema.json": "schemas/knowledge/knowledge-analysis-request-v8.schema.json",
    "knowledge/knowledge-analysis-request-v9.schema.json": "schemas/knowledge/knowledge-analysis-request-v9.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v2.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v2.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v3.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v3.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v4.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v4.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v5.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v5.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v6.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v6.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v7.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v7.schema.json",
    "knowledge/knowledge-analysis-proposal-receipt-v8.schema.json": "schemas/knowledge/knowledge-analysis-proposal-receipt-v8.schema.json",
    "knowledge/knowledge-analysis-result-v3.schema.json": "schemas/knowledge/knowledge-analysis-result-v3.schema.json",
    "knowledge/knowledge-analysis-result-v4.schema.json": "schemas/knowledge/knowledge-analysis-result-v4.schema.json",
    "knowledge/knowledge-analysis-result-v5.schema.json": "schemas/knowledge/knowledge-analysis-result-v5.schema.json",
    "knowledge/knowledge-analysis-result-v6.schema.json": "schemas/knowledge/knowledge-analysis-result-v6.schema.json",
    "knowledge/knowledge-analysis-result-v7.schema.json": "schemas/knowledge/knowledge-analysis-result-v7.schema.json",
    "knowledge/knowledge-analysis-result-v8.schema.json": "schemas/knowledge/knowledge-analysis-result-v8.schema.json",
    "knowledge/knowledge-analysis-result-v9.schema.json": "schemas/knowledge/knowledge-analysis-result-v9.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v2.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v2.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v3.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v3.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v4.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v4.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v5.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v5.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v6.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v6.schema.json",
    "knowledge/knowledge-analysis-worker-proposal-v7.schema.json": "schemas/knowledge/knowledge-analysis-worker-proposal-v7.schema.json",
    "knowledge/knowledge-analysis-proposed-node-v3.schema.json": "schemas/knowledge/knowledge-analysis-proposed-node-v3.schema.json",
    "knowledge/knowledge-analysis-proposed-node-v4.schema.json": "schemas/knowledge/knowledge-analysis-proposed-node-v4.schema.json",
    "knowledge/knowledge-analysis-proposed-edge-v4.schema.json": "schemas/knowledge/knowledge-analysis-proposed-edge-v4.schema.json",
    "knowledge/knowledge-graph-projection-v1.schema.json": "schemas/knowledge/knowledge-graph-projection-v1.schema.json",
    "knowledge/knowledge-graph-projection-v2.schema.json": "schemas/knowledge/knowledge-graph-projection-v2.schema.json",
    "knowledge/knowledge-graph-projection-v3.schema.json": "schemas/knowledge/knowledge-graph-projection-v3.schema.json",
    "knowledge/knowledge-graph-projection-v4.schema.json": "schemas/knowledge/knowledge-graph-projection-v4.schema.json",
    "knowledge/knowledge-graph-publication-result-v1.schema.json": "schemas/knowledge/knowledge-graph-publication-result-v1.schema.json",
    "knowledge/knowledge-graph-publication-v1.schema.json": "schemas/knowledge/knowledge-graph-publication-v1.schema.json",
    "knowledge/knowledge-graph-publication-v2.schema.json": "schemas/knowledge/knowledge-graph-publication-v2.schema.json",
    "knowledge/knowledge-graph-publication-v3.schema.json": "schemas/knowledge/knowledge-graph-publication-v3.schema.json",
    "knowledge/knowledge-graph-publication-v4.schema.json": "schemas/knowledge/knowledge-graph-publication-v4.schema.json",
    "knowledge/knowledge-graph-publication-v5.schema.json": "schemas/knowledge/knowledge-graph-publication-v5.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v1.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v2.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v2.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v3.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v3.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v4.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v4.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v5.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v5.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v6.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v6.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v7.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v7.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v8.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v8.schema.json",
    "knowledge/knowledge-graph-structure-manifest-v1.schema.json": "schemas/knowledge/knowledge-graph-structure-manifest-v1.schema.json",
    "knowledge/knowledge-graph-structure-manifest-v2.schema.json": "schemas/knowledge/knowledge-graph-structure-manifest-v2.schema.json",
    "knowledge/knowledge-graph-structure-manifest-v3.schema.json": "schemas/knowledge/knowledge-graph-structure-manifest-v3.schema.json",
    "knowledge/knowledge-graph-structure-manifest-v4.schema.json": "schemas/knowledge/knowledge-graph-structure-manifest-v4.schema.json",
    "knowledge/knowledge-graph-structure-manifest-v5.schema.json": "schemas/knowledge/knowledge-graph-structure-manifest-v5.schema.json",
    "knowledge/education-retrieval-access-policy-v1.schema.json": "schemas/knowledge/education-retrieval-access-policy-v1.schema.json",
    "knowledge/education-retrieval-request-v1.schema.json": "schemas/knowledge/education-retrieval-request-v1.schema.json",
    "knowledge/education-retrieval-request-v2.schema.json": "schemas/knowledge/education-retrieval-request-v2.schema.json",
    "knowledge/evidence-bundle-manifest-v1.schema.json": "schemas/knowledge/evidence-bundle-manifest-v1.schema.json",
    "knowledge/evidence-bundle-manifest-v2.schema.json": "schemas/knowledge/evidence-bundle-manifest-v2.schema.json",
    "knowledge/evidence-bundle-manifest-v3.schema.json": "schemas/knowledge/evidence-bundle-manifest-v3.schema.json",
    "knowledge/evidence-bundle-manifest-v4.schema.json": "schemas/knowledge/evidence-bundle-manifest-v4.schema.json",
    "knowledge/evidence-bundle-publication-result-v1.schema.json": "schemas/knowledge/evidence-bundle-publication-result-v1.schema.json",
    "knowledge/educational-retrieval-requirement-v1.schema.json": "schemas/knowledge/educational-retrieval-requirement-v1.schema.json",
    "knowledge/evidence-bundle-publication-result-v2.schema.json": "schemas/knowledge/evidence-bundle-publication-result-v2.schema.json",
    "knowledge/evidence-bundle-publication-result-v3.schema.json": "schemas/knowledge/evidence-bundle-publication-result-v3.schema.json",
    "knowledge/evidence-bundle-publication-result-v4.schema.json": "schemas/knowledge/evidence-bundle-publication-result-v4.schema.json",
    "legacy-knowledge/legacy-source-inventory-v1.schema.json": "schemas/legacy-knowledge/legacy-source-inventory-v1.schema.json",
    "legacy-knowledge/legacy-source-inventory-policy-v1.schema.json": "schemas/legacy-knowledge/legacy-source-inventory-policy-v1.schema.json",
    "legacy-knowledge/legacy-source-inventory-v2.schema.json": "schemas/legacy-knowledge/legacy-source-inventory-v2.schema.json",
    "legacy-knowledge/legacy-source-relation-manifest-v1.schema.json": "schemas/legacy-knowledge/legacy-source-relation-manifest-v1.schema.json",
    "legacy-knowledge/legacy-source-rights-review-v1.schema.json": "schemas/legacy-knowledge/legacy-source-rights-review-v1.schema.json",
    "legacy-knowledge/legacy-source-rights-review-v2.schema.json": "schemas/legacy-knowledge/legacy-source-rights-review-v2.schema.json",
    "legacy-knowledge/legacy-source-selection-v1.schema.json": "schemas/legacy-knowledge/legacy-source-selection-v1.schema.json",
    "legacy-knowledge/legacy-source-selection-v2.schema.json": "schemas/legacy-knowledge/legacy-source-selection-v2.schema.json",
    "legacy-knowledge/pdf-page-range-materialization-manifest-v1.schema.json": "schemas/legacy-knowledge/pdf-page-range-materialization-manifest-v1.schema.json",
    "legacy-knowledge/textbook-analysis-bundle-manifest-v1.schema.json": "schemas/legacy-knowledge/textbook-analysis-bundle-manifest-v1.schema.json",
    "legacy-knowledge/textbook-analysis-bundle-manifest-v2.schema.json": "schemas/legacy-knowledge/textbook-analysis-bundle-manifest-v2.schema.json",
    "legacy-usage/assessment-assembly-manifest-v1.schema.json": "schemas/legacy-usage/assessment-assembly-manifest-v1.schema.json",
    "legacy-usage/legacy-usage-import-manifest-v1.schema.json": "schemas/legacy-usage/legacy-usage-import-manifest-v1.schema.json",
    "legacy-usage/legacy-usage-mapping-contract-v1.schema.json": "schemas/legacy-usage/legacy-usage-mapping-contract-v1.schema.json",
    "legacy-usage/legacy-usage-row-proposal-v1.schema.json": "schemas/legacy-usage/legacy-usage-row-proposal-v1.schema.json",
    "legacy-usage/product-usage-graph-projection-v1.schema.json": "schemas/legacy-usage/product-usage-graph-projection-v1.schema.json",
}
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    packaged = {
        name.removeprefix(catalog_prefix)
        for name in names
        if name.startswith(catalog_prefix) and name.endswith(".schema.json")
    }
    expected = set(catalog_resources)
    if packaged != expected:
        raise SystemExit(
            "Catalog Contract schema wheel resources mismatch: "
            f"expected={sorted(expected)} actual={sorted(packaged)}"
        )
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    repository_root = Path(os.environ["REPOSITORY_ROOT"])
    for resource_name, canonical_name in sorted(catalog_resources.items()):
        member = catalog_prefix + resource_name
        if archive.read(member) != (repository_root / canonical_name).read_bytes():
            raise SystemExit(f"Catalog Contract schema resource drift: {resource_name}")
        if member not in record:
            raise SystemExit(f"Catalog Contract resource missing from RECORD: {resource_name}")
    for policy_name in (
        "integrated-science-mock-exam-assembly-v1.json",
        "integrated-science-mock-exam-layout-v1.json",
        "integrated-science-item-rating-v1.json",
    ):
        policy_member = catalog_prefix + "assessment-assembly/" + policy_name
        policy_source = repository_root / "content/assembly-policies" / policy_name
        if (
            archive.read(policy_member) != policy_source.read_bytes()
            or policy_member not in record
        ):
            raise SystemExit(f"Catalog Contract assembly policy resource drift: {policy_name}")

image_prefix = "eom_image_contracts/schemas/"
image_resources = {
    "local-image-model-manifest-v1.schema.json": "schemas/image-provider/local-image-model-manifest-v1.schema.json",
    "local-image-generation-request-v1.schema.json": "schemas/image-provider/local-image-generation-request-v1.schema.json",
    "local-image-generation-receipt-v1.schema.json": "schemas/image-provider/local-image-generation-receipt-v1.schema.json",
    "local-image-provider-binding-v1.schema.json": "schemas/image-provider/local-image-provider-binding-v1.schema.json",
    "local-image-composite-request-v1.schema.json": "schemas/image-provider/local-image-composite-request-v1.schema.json",
    "local-image-composite-receipt-v1.schema.json": "schemas/image-provider/local-image-composite-receipt-v1.schema.json",
}
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    packaged = {
        name.removeprefix(image_prefix)
        for name in names
        if name.startswith(image_prefix) and name.endswith(".schema.json")
    }
    if packaged != set(image_resources):
        raise SystemExit(
            "Image Contract schema wheel resources mismatch: "
            f"expected={sorted(image_resources)} actual={sorted(packaged)}"
        )
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    repository_root = Path(os.environ["REPOSITORY_ROOT"])
    for resource_name, canonical_name in sorted(image_resources.items()):
        member = image_prefix + resource_name
        if archive.read(member) != (repository_root / canonical_name).read_bytes():
            raise SystemExit(f"Image Contract schema resource drift: {resource_name}")
        if member not in record:
            raise SystemExit(f"Image Contract resource missing from RECORD: {resource_name}")

with tempfile.TemporaryDirectory(prefix="eom-workflow-wheel-check.") as temporary:
    root = Path(temporary)
    installed_root = root / "site-packages"
    definitions = []
    for version in ("1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "1.9"):
        definition = root / f"generic-item-development.v{version}.yaml"
        definition.write_bytes(
            (
                Path(os.environ["REPOSITORY_ROOT"])
                / f"config/workflows/generic-item-development.v{version}.yaml"
            ).read_bytes()
        )
        definitions.append(definition)
    analysis_definitions = []
    for version in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
        definition = root / f"knowledge-analysis.v{version}.yaml"
        definition.write_bytes(
            (
                Path(os.environ["REPOSITORY_ROOT"])
                / f"config/workflows/knowledge-analysis.v{version}.yaml"
            ).read_bytes()
        )
        analysis_definitions.append(definition)
    legacy_definition = root / "legacy-item-extraction.v1.yaml"
    legacy_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/legacy-item-extraction.v1.yaml"
        ).read_bytes()
    )
    editorial_definition = root / "legacy-item-editorial-compatibility.v1.yaml"
    editorial_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/legacy-item-editorial-compatibility.v1.yaml"
        ).read_bytes()
    )
    worker_config = root / "worker-slots.yaml"
    worker_config.write_bytes(
        (Path(os.environ["REPOSITORY_ROOT"]) / "config/worker-slots.example.yaml").read_bytes()
    )
    staging = root / "staging"
    workspace_root = root / "workspaces"
    staging.mkdir()
    (workspace_root / "eom-cdx-01").mkdir(parents=True)
    codex_binary = root / "codex"
    codex_binary.write_text("isolated non-live executable placeholder\n", encoding="utf-8")
    codex_binary.chmod(0o700)
    previous_umask = os.umask(0o022)
    try:
        subprocess.run(
            [
                os.environ["API_PYTHON"],
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                "--no-compile",
                "--target",
                str(installed_root),
                str(platform_wheel),
                str(by_prefix["eom_api_contracts"]),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    finally:
        os.umask(previous_umask)
    for path in (installed_root, *installed_root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("installed simulation contains a symlink")
        expected_mode = (
            0o755 if path.is_dir() or path.parent == installed_root / "bin" else 0o644
        )
        if path.stat().st_mode & 0o777 != expected_mode:
            raise SystemExit(f"installed simulation mode mismatch: {path.name}")
    check = r'''
import importlib.util
import os
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository, definition_v1_1, definition_v1_2, definition_v1_3, definition_v1_4, definition_v1_5, definition_v1_6, definition_v1_7, definition_v1_8, definition_v1_9, analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6, analysis_v7, analysis_v8, analysis_v9, legacy_definition, editorial_definition, worker_config, staging, workspace_root, codex_binary = sys.argv[2:]
sys.path.insert(0, str(installed_root))
os.environ["EOM_WORKER_CONFIG"] = worker_config
os.environ["EOM_STAGING_ROOT"] = staging
os.environ["EOM_WORKSPACE_ROOT"] = workspace_root
os.environ["EOM_CODEX_BINARY"] = codex_binary
from eom_workflow import AgentStep, WORKFLOW_ADMISSION_BY_IDENTITY
from eom_api_contracts import (
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecutionV1,
    MockExamProductionRetirementCommandV1,
    MockExamProductionRetirementReceiptV1,
    mock_exam_production_is_terminal,
)
from eom_workflow.compiler import compile_definition
from eom_workflow.schemas import (
    INPUT_SCHEMA_FILES,
    RESULT_SCHEMA_FILES,
    load_codex_result_schema,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
    result_schema_protocol,
)
from eom_catalog_contracts import catalog_schema_inventory, load_schema, validate_contract
import eom_workflow_runner.actor_authorization
import eom_workflow_runner.actor_authorization_adapters
from eom_orchestrator.doctor import runtime_configuration_check
from eom_orchestrator.live_preflight import run_live_worker_preflight
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import DEFAULT_WORKER_CONFIG, Settings, WorkerConfigSource
from eom_orchestrator.worker_systemd import WorkerSystemdReadiness
from eomctl.cli import app as eomctl_app
from typer.testing import CliRunner

spec = importlib.util.find_spec("eom_workflow")
if (
    spec is None
    or spec.origin is None
    or not Path(spec.origin).resolve().is_relative_to(installed_root)
    or repository in spec.origin
):
    raise SystemExit("workflow package was not imported from the release wheel")
orchestrator_spec = importlib.util.find_spec("eom_orchestrator")
if (
    orchestrator_spec is None
    or orchestrator_spec.origin is None
    or not Path(orchestrator_spec.origin).resolve().is_relative_to(installed_root)
    or repository in orchestrator_spec.origin
):
    raise SystemExit("Orchestrator package was not imported from the release wheel")
api_contract_spec = importlib.util.find_spec("eom_api_contracts")
if (
    api_contract_spec is None
    or api_contract_spec.origin is None
    or not Path(api_contract_spec.origin).resolve().is_relative_to(installed_root)
    or repository in api_contract_spec.origin
):
    raise SystemExit("Application API contracts were not imported from the release wheel")
for recovery_module in (
    "eom_operator_identity.errors",
    "eom_identity_service.local_admin_recovery",
    "eomctl.operator",
):
    recovery_spec = importlib.util.find_spec(recovery_module)
    if (
        recovery_spec is None
        or recovery_spec.origin is None
        or not Path(recovery_spec.origin).resolve().is_relative_to(installed_root)
        or repository in recovery_spec.origin
    ):
        raise SystemExit(
            f"identity recovery module was not imported from the release wheel: {recovery_module}"
        )
recovery_help = CliRunner().invoke(
    eomctl_app,
    ["operator", "emergency-reset-admin-password", "--help"],
)
if recovery_help.exit_code != 0 or "emergency-reset-admin-password" not in recovery_help.stdout:
    raise SystemExit("installed-wheel eomctl emergency recovery command is unavailable")
if any(
    model.__module__ != "eom_api_contracts.mock_exam_execution"
    for model in (
        MockExamExplicitAnalysisReviewSetV1,
        MockExamExplicitRatingSetV1,
        MockExamGenerationBlockResolutionV1,
        MockExamGraphPublicationInputV1,
        MockExamProductionExecutionV1,
    )
):
    raise SystemExit("mock-exam contract package exports are incomplete")
if mock_exam_production_is_terminal.__module__ != "eom_api_contracts.mock_exam_execution":
    raise SystemExit("mock-exam terminal-state contract export is incomplete")
if any(
    model.__module__ != "eom_api_contracts.mock_exam_retirement"
    for model in (
        MockExamProductionRetirementCommandV1,
        MockExamProductionRetirementReceiptV1,
    )
):
    raise SystemExit("mock-exam retirement contract package exports are incomplete")
if CURRENT_MIGRATION_REVISION != "20260908_0032":
    raise SystemExit("installed runtime migration admission head mismatch")
settings = Settings.from_environment()
if settings.worker_config != Path(worker_config).resolve():
    raise SystemExit("explicit worker configuration was not selected")
if settings.worker_config_source is not WorkerConfigSource.ENVIRONMENT:
    raise SystemExit("worker configuration source was not retained")
if DEFAULT_WORKER_CONFIG != Path("/etc/eom/worker-slots.yaml"):
    raise SystemExit("operator-owned worker configuration default drift")
if settings.worker_config == Path(sys.prefix) / "config" / "worker-slots.example.yaml":
    raise SystemExit("install-prefix worker configuration inference detected")
resolved = resolve_worker_configuration(settings)
if resolved.live_worker.slot_id != "01" or not runtime_configuration_check(settings).passed:
    raise SystemExit("installed worker configuration readiness failed")
def ready(_slot):
    return WorkerSystemdReadiness(True, "READY", "isolated non-live boundary")
preflight = run_live_worker_preflight(
    settings,
    package_roots=(installed_root,),
    systemd_contract=ready,
    authorization_probe=ready,
)
if not preflight.ready:
    raise SystemExit(f"installed non-live worker preflight failed: {preflight.failed_codes}")
load_definition_schema()
for role in INPUT_SCHEMA_FILES:
    load_role_input_schema(role)
    load_role_input_schema(role, "workflow-role/1.1.0")
    load_role_input_schema(role, "workflow-role/1.2.0")
    load_role_input_schema(role, "workflow-role/1.3.0")
    load_role_input_schema(role, "workflow-role/1.12.0")
    load_role_input_schema(role, "workflow-role/1.13.0")
load_role_input_schema("support", "workflow-role/1.4.0")
load_role_input_schema("support", "workflow-role/1.5.0")
load_role_input_schema("support", "workflow-role/1.6.0")
load_role_input_schema("support", "workflow-role/1.7.0")
load_role_input_schema("support", "workflow-role/1.8.0")
load_role_input_schema("support", "workflow-role/1.9.0")
load_role_input_schema("support", "workflow-role/1.10.0")
load_role_input_schema("support", "workflow-role/1.11.0")
load_role_input_schema("support", "workflow-role/1.14.0")
load_role_input_schema("authoring", "workflow-role/1.15.0")
load_role_input_schema("review", "workflow-role/1.15.0")
load_role_input_schema("item_management", "workflow-role/1.15.0")
load_role_input_schema("support", "workflow-role/1.16.0")
load_role_input_schema("authoring", "workflow-role/1.17.0")
load_role_input_schema("image", "workflow-role/1.17.0")
load_role_input_schema("review", "workflow-role/1.17.0")
load_role_input_schema("item_management", "workflow-role/1.17.0")
load_role_input_schema("support", "workflow-role/1.18.0")
load_role_input_schema("authoring", "workflow-role/1.19.0")
load_role_input_schema("image", "workflow-role/1.19.0")
load_role_input_schema("review", "workflow-role/1.19.0")
load_role_input_schema("item_management", "workflow-role/1.19.0")
for schema_id in RESULT_SCHEMA_FILES:
    load_role_result_schema(schema_id)
    load_codex_result_schema(schema_id)
compiled_versions = {
    compile_definition(
        Path(definition_path), {"authoring", "image", "review", "item_management"}
    ).definition.definition_version
    for definition_path in (
        definition_v1_1,
        definition_v1_2,
        definition_v1_3,
        definition_v1_4,
        definition_v1_5,
        definition_v1_6,
        definition_v1_7,
        definition_v1_8,
        definition_v1_9,
    )
}
if compiled_versions != {"1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.8.0", "1.9.0"}:
    raise SystemExit("generic workflow definition versions mismatch")
analysis_versions = {
    compile_definition(Path(path), {"support"}).definition.definition_version
    for path in (analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6, analysis_v7, analysis_v8, analysis_v9)
}
if analysis_versions != {"1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0", "7.0.0", "8.0.0", "9.0.0"}:
    raise SystemExit("knowledge analysis workflow definition mismatch")
legacy = compile_definition(Path(legacy_definition), {"support"}).definition
if (
    legacy.definition_key != "legacy-item-extraction"
    or legacy.definition_version != "1.0.0"
):
    raise SystemExit("legacy item extraction workflow definition mismatch")
editorial = compile_definition(Path(editorial_definition), {"support"}).definition
if (
    editorial.definition_key != "legacy-item-editorial-compatibility"
    or editorial.definition_version != "1.0.0"
):
    raise SystemExit("legacy item editorial compatibility workflow definition mismatch")
admitted_definitions = (
    compile_definition(Path(definition_v1_8), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_9), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(analysis_v1), {"support"}),
    compile_definition(Path(analysis_v4), {"support"}),
    compile_definition(Path(analysis_v8), {"support"}),
    compile_definition(Path(analysis_v9), {"support"}),
    compile_definition(Path(legacy_definition), {"support"}),
    compile_definition(Path(editorial_definition), {"support"}),
)
if {
    (compiled.definition.definition_key, compiled.definition.definition_version): next(iter({
        result_schema_protocol(step.result_schema)
        for step in compiled.definition.steps
        if isinstance(step, AgentStep)
    }))
    for compiled in admitted_definitions
} != {
    identity: admission.role_protocol_version
    for identity, admission in WORKFLOW_ADMISSION_BY_IDENTITY.items()
}:
    raise SystemExit("workflow admission policy does not match the installed definitions")
for name, _ in catalog_schema_inventory():
    load_schema(name)
validate_contract(
    "prompt-envelope",
    {
        "schema_version": "1.0",
        "pack_release_id": "packrel_" + "0" * 32,
        "pack_release_sha256": "sha256:" + "0" * 64,
        "profile_key": "authoring-default",
        "profile_version": "0.1.0",
        "profile_sha256": "sha256:" + "0" * 64,
        "template_path": "prompt-templates/authoring.md",
        "template_sha256": "sha256:" + "0" * 64,
        "render_context_sha256": "sha256:" + "0" * 64,
        "rendered_prompt_sha256": "sha256:" + "0" * 64,
        "workflow_id": "workflow_" + "0" * 32,
        "step_run_id": "steprun_" + "0" * 32,
        "source_intake_batch_ids": ["intake_" + "0" * 32],
    },
)
'''
    subprocess.run(
        [
            os.environ["API_PYTHON"],
            "-I",
            "-c",
            check,
            str(installed_root),
            os.environ["REPOSITORY_ROOT"],
            *(str(definition) for definition in definitions),
            *(str(definition) for definition in analysis_definitions),
            str(legacy_definition),
            str(editorial_definition),
            str(worker_config),
            str(staging),
            str(workspace_root),
            str(codex_binary),
        ],
        cwd=root,
        check=True,
    )

with tempfile.TemporaryDirectory(prefix="eom-api-verifier-wheel-check.") as temporary:
    root = Path(temporary)
    installed_root = root / "site-packages"
    previous_umask = os.umask(0o022)
    try:
        subprocess.run(
            [
                os.environ["API_PYTHON"],
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                "--no-compile",
                "--target",
                str(installed_root),
                str(by_prefix["eom_application_api"]),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    finally:
        os.umask(previous_umask)
    for path in (installed_root, *installed_root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Application API installed simulation contains a symlink")
        expected_mode = (
            0o755 if path.is_dir() or path.parent == installed_root / "bin" else 0o644
        )
        if path.stat().st_mode & 0o777 != expected_mode:
            raise SystemExit(f"Application API installed simulation mode mismatch: {path.name}")
    capability_check = r'''
import importlib.util
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(installed_root))
spec = importlib.util.find_spec("eom_api.runtime_isolation_verifier")
if (
    spec is None
    or spec.origin is None
    or not Path(spec.origin).resolve().is_relative_to(installed_root)
    or Path(spec.origin).resolve().is_relative_to(repository)
):
    raise SystemExit("runtime-isolation verifier was not imported from the installed wheel")
sys.argv = ["eom-api-runtime-isolation", "--capabilities"]
from eom_api.runtime_isolation_verifier import main
main()
'''
    completed = subprocess.run(
        [
            os.environ["API_PYTHON"],
            "-I",
            "-c",
            capability_check,
            str(installed_root),
            os.environ["REPOSITORY_ROOT"],
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = set(completed.stdout.splitlines())
    if "runtime_isolation_verifier_capability=READY" not in lines:
        raise SystemExit("installed-wheel runtime-isolation capability is not ready")
    if not lines.intersection(
        {"selected_pidfd_backend=PYTHON_OS_PIDFD", "selected_pidfd_backend=LIBC_PIDFD"}
    ):
        raise SystemExit("installed-wheel runtime-isolation pidfd backend is unavailable")
    if "pidfd_policy=FAIL_CLOSED" not in lines or completed.stderr:
        raise SystemExit("installed-wheel runtime-isolation capability output mismatch")

for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith((".py", ".json", ".pth")):
                content = archive.read(name)
                if b"__editable__" in content:
                    raise SystemExit(f"wheel contains editable metadata: {wheel.name}:{name}")
                if name.endswith(".pth") and b"/home/eom/EOM" in content:
                    raise SystemExit(
                        f"wheel contains a source-checkout path mapping: {wheel.name}:{name}"
                    )
PY
}

install_wheels() {
  mapfile -t wheels < <(find "${DIST_DIR}" -maxdepth 1 -type f -name '*.whl' | sort)
  ((${#wheels[@]} == 3)) || fail "release wheels are unavailable"
  (
    umask 022
    ${API_PIP} install --no-deps --force-reinstall "${wheels[@]}" >/dev/null
  )
  ${API_PIP} check
  verify_install_mode
}

verify_install_mode() {
  REPOSITORY_ROOT="${REPOSITORY_ROOT}" "${API_PYTHON}" - <<'PY'
from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import os
import site
import stat
import subprocess
from pathlib import Path

site_roots = [Path(value).resolve() for value in site.getsitepackages()]
runtime_package_roots: set[Path] = set()
for module in (
    "eom_api",
    "eom_api_contracts",
    "eom_operator_identity",
    "eom_operator_identity.errors",
    "eom_identity_service.local_admin_recovery",
    "eomctl.operator",
    "eom_catalog_contracts",
    "eom_workflow",
    "eom_workflow_runner",
    "eom_catalog_service",
    "eom_hwpx_manager",
):
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise SystemExit(f"installed module is missing: {module}")
    origin = Path(spec.origin).resolve()
    if not any(origin.is_relative_to(root) for root in site_roots):
        raise SystemExit(f"module is outside site-packages: {module}")
    if str(origin).startswith(os.environ["REPOSITORY_ROOT"]):
        raise SystemExit(f"source checkout import detected: {module}")
    runtime_package_roots.add(origin.parent)

for module in (
    "eom_operator_identity.errors",
    "eom_identity_service.local_admin_recovery",
    "eomctl.operator",
):
    importlib.import_module(module)

expected_uid = os.getuid()
expected_gid = os.getgid()
for root in sorted(runtime_package_roots):
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"runtime package contains a symlink: {path.name}")
        metadata = path.stat()
        if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
            raise SystemExit(f"runtime package ownership mismatch: {path.name}")
        expected_mode = 0o755 if path.is_dir() else 0o644
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise SystemExit(f"runtime package mode mismatch: {path.name}")

for name in (
    "eomctl",
    "eom-api",
    "eom-api-runtime-isolation",
    "eom-workflow-runner",
    "eom-hwpx-application-runner",
    "eom-catalog-application-runner",
):
    entrypoint = Path(os.environ.get("API_PYTHON", "/srv/eom/conda/envs/eom-api/bin/python"))
    entrypoint = entrypoint.resolve().parent / name
    metadata = entrypoint.stat()
    if (
        metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o755
    ):
        raise SystemExit(f"runtime entry point mode mismatch: {name}")
eomctl_environment = os.environ.copy()
eomctl_environment.pop("PYTHONHOME", None)
eomctl_environment.pop("PYTHONPATH", None)
eomctl_entrypoint = Path(
    os.environ.get("API_PYTHON", "/srv/eom/conda/envs/eom-api/bin/python")
).resolve().parent / "eomctl"
eomctl_help = subprocess.run(
    [str(eomctl_entrypoint), "operator", "emergency-reset-admin-password", "--help"],
    cwd=eomctl_entrypoint.parent,
    env=eomctl_environment,
    capture_output=True,
    text=True,
    check=False,
)
if (
    eomctl_help.returncode != 0
    or "emergency-reset-admin-password" not in eomctl_help.stdout
    or eomctl_help.stderr
):
    raise SystemExit("installed eomctl emergency recovery command is unavailable")
for name in ("eom-application-api", "eom-api-contracts", "eom-platform"):
    distribution = importlib.metadata.distribution(name)
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
        raise SystemExit(f"editable distribution detected: {name}")
for root in site_roots:
    for path in root.glob("__editable__*"):
        raise SystemExit(f"editable metadata detected: {path.name}")

from eom_catalog_contracts import catalog_schema_inventory, load_schema

for name, _ in catalog_schema_inventory():
    load_schema(name)
PY
  "${API_PYTHON}" -I -m eom_api.runtime_isolation_verifier --capabilities
}

record_release() {
  local record temporary
  temporary="$(mktemp)"
  record="/var/lib/eom-api/deployments/${COMMIT}.json"
  COMMIT="${COMMIT}" VERSION="${VERSION}" DIST_DIR="${DIST_DIR}" RECORD="${temporary}" \
    WORKFLOW_RUNNER_HELD="${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" \
    "${API_PYTHON}" - <<'PY'
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

dist = Path(os.environ["DIST_DIR"])
wheels = {}
for path in sorted(dist.glob("*.whl")):
    wheels[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
payload = {
    "deployed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "source_commit": os.environ["COMMIT"],
    "workflow_runner_held_inactive": os.environ["WORKFLOW_RUNNER_HELD"] == "true",
    "package_version": os.environ["VERSION"],
    "wheels": wheels,
    "rollback": (
        "Reinstall the three retained wheels for the prior source commit, restore the prior "
        "unit if it changed, then run deploy_release.sh --verify."
    ),
}
Path(os.environ["RECORD"]).write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
PY
  sudo -n install -d -o eom-api -g eom-api -m 0700 /var/lib/eom-api/deployments
  sudo -n install -o eom-api -g eom-api -m 0600 "${temporary}" "${record}"
  rm -f "${temporary}"
  printf 'Rollback record: %s\n' "${record}"
}

wait_for_health() {
  local attempt
  for attempt in {1..30}; do
    if curl --fail --silent --max-time 1 \
      http://127.0.0.1:8765/api/v1/health/live >/dev/null && \
      curl --fail --silent --max-time 1 \
      http://127.0.0.1:8765/api/v1/health/ready >/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  fail "Application API did not become healthy within 15 seconds"
}

restart_platform_consumers() {
  local consumer main_pid
  for consumer in "${PLATFORM_CONSUMER_SERVICES[@]}"; do
    if [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true && \
      "${consumer}" == "${WORKFLOW_RUNNER_SERVICE}" ]]; then
      verify_workflow_runner_deployment_hold
      continue
    fi
    systemctl is-enabled --quiet "${consumer}" || \
      fail "${consumer} must already be enabled before shared-platform deployment"
  done
  for consumer in "${PLATFORM_CONSUMER_SERVICES[@]}"; do
    if [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true && \
      "${consumer}" == "${WORKFLOW_RUNNER_SERVICE}" ]]; then
      verify_workflow_runner_deployment_hold
      continue
    fi
    sudo -n systemctl restart "${consumer}"
    systemctl is-active --quiet "${consumer}" || \
      fail "${consumer} did not become active after shared-platform deployment"
    main_pid="$(systemctl show --property=MainPID --value "${consumer}")"
    [[ "${main_pid}" =~ ^[1-9][0-9]*$ ]] || \
      fail "${consumer} did not expose a fresh main process"
  done
}

install_service() {
  id eom-api >/dev/null 2>&1 || fail "eom-api system user is absent"
  systemd-analyze verify "${UNIT_SOURCE}"
  sudo -n install -d -o root -g root -m 0755 /usr/local/libexec/eom-api
  sudo -n install -o root -g root -m 0755 \
    "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0755 \
    "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0755 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}"
  if sudo -n -u eom-api /usr/bin/test -e "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}" || \
    sudo -n -u eom-api /usr/bin/test -L "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}"; then
    require_workflow_runner_retirement_receipt_root
  else
    # The parent is eom-api-owned and mode 0700. Create the absent leaf without root authority;
    # even an EEXIST symlink race therefore cannot become a privileged chmod/chown write gadget.
    sudo -n -u eom-api /usr/bin/install -d -m 0700 \
      "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}"
  fi
  require_workflow_runner_retirement_receipt_root
  require_installed_workflow_runner_hold_release_verifier
  sudo -n install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
  sudo -n "${METADATA_VERIFIER_TARGET}"
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable "${SERVICE}" >/dev/null
  restart_platform_consumers
  verify_workflow_runner_deployment_hold
  wait_for_health
  printf 'runtime_isolation_verifier_invocation=START\n'
  sudo -n "${RUNTIME_VERIFIER_TARGET}"
  record_release
  if [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]]; then
    printf '%s\n' "Authenticated smoke deferred while the Workflow runner hold is active."
  elif [[ -n "${EOM_API_SMOKE_USERNAME:-}" && -n "${EOM_API_SMOKE_PASSWORD_FILE:-}" ]]; then
    "${REPOSITORY_ROOT}/scripts/api/smoke_test.sh"
  else
    printf 'Authenticated smoke deferred until EOM_API_SMOKE_USERNAME and '
    printf 'EOM_API_SMOKE_PASSWORD_FILE are set.\n'
  fi
}

verify_service() {
  local consumer
  verify_install_mode
  cmp --silent "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}" || \
    fail "installed metadata verifier source drift"
  cmp --silent "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}" || \
    fail "installed runtime verifier source drift"
  require_installed_workflow_runner_hold_release_verifier
  cmp --silent \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_SOURCE}" \
    "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}" || \
    fail "installed mock-exam deployment admission source drift"
  for consumer in "${PLATFORM_CONSUMER_SERVICES[@]}"; do
    systemctl is-active --quiet "${consumer}" || fail "${consumer} is not active"
    systemctl is-enabled --quiet "${consumer}" || fail "${consumer} is not enabled"
  done
  wait_for_health
  "${REPOSITORY_ROOT}/scripts/api/smoke_test.sh" --health-only
  printf 'Installed EOM Application API release verified.\n'
}

case "${ACTION}" in
  build)
    build_release
    ;;
  install)
    sudo -n true || fail "noninteractive privileged access is required before installation"
    require_clean_tree
    activate_workflow_runner_deployment_hold
    verify_mock_exam_deployment_admission
    prepare_runtime_dependencies
    build_release
    # Close the build-window race before replacing any installed runtime package.
    verify_workflow_runner_deployment_hold
    verify_mock_exam_deployment_admission
    install_wheels
    reconcile_installed_catalog_runtime_privileges
    reconcile_installed_hwpx_manager_runtime_privileges
    install_service
    if [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]]; then
      printf '%s\n' "workflow_runner_deployment_hold=ACTIVE"
      printf '%s\n' \
        "Retire the pinned occurrence before releasing the hold and starting eom-workflow-runner.service."
    fi
    ;;
  release-workflow-runner-hold)
    sudo -n true || fail "noninteractive privileged access is required before hold release"
    require_clean_tree
    release_workflow_runner_deployment_hold_after_verified_receipt
    ;;
  verify)
    verify_service
    ;;
esac
