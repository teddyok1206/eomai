#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCHES=("main" "feat/application-api-v0" "feat/hwpx-application-api-v0")
API_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
API_PIP="${API_PYTHON} -m pip"
GIT="/usr/bin/git"
SHA256SUM="/usr/bin/sha256sum"
TAR="/usr/bin/tar"
SERVICE="eom-api.service"
WORKFLOW_RUNNER_SERVICE="eom-workflow-runner.service"
WORKFLOW_MAINTENANCE_SERVICE="eom-workflow-maintenance.service"
PLATFORM_CONSUMER_SERVICES=(
  "eom-catalog-application-runner.service"
  "eom-workflow-maintenance.service"
  "eom-workflow-runner.service"
  "eom-hwpx-application-runner.service"
  "eom-api.service"
)
SHARED_RUNTIME_TRANSIENT_PATTERNS=(
  "eom-workflow-runner-*.service"
)
WORKFLOW_RUNNER_ACCELERATOR_RUNTIME_UNIT="/run/systemd/system/eom-workflow-runner-accelerator.service"
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/eom-api.service"
UNIT_TARGET="/etc/systemd/system/eom-api.service"
WORKFLOW_RUNNER_UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/${WORKFLOW_RUNNER_SERVICE}"
WORKFLOW_RUNNER_UNIT_TARGET="/etc/systemd/system/${WORKFLOW_RUNNER_SERVICE}"
WORKFLOW_RUNNER_RUNTIME_ENV_TARGET="/etc/eom/workflow-runtime.env"
WORKFLOW_MAINTENANCE_UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/${WORKFLOW_MAINTENANCE_SERVICE}"
WORKFLOW_MAINTENANCE_UNIT_TARGET="/etc/systemd/system/${WORKFLOW_MAINTENANCE_SERVICE}"
METADATA_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_deployment_metadata.sh"
METADATA_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-deployment-metadata"
RUNTIME_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_runtime_isolation.sh"
RUNTIME_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-runtime-isolation"
OFFICE_CONVERTER_INSTALLER="${REPOSITORY_ROOT}/scripts/catalog/install_office_document_converter.sh"
MOCK_EXAM_DEPLOYMENT_ADMISSION_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_mock_exam_deployment_admission.py"
MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET="/usr/local/libexec/eom-api/verify-mock-exam-deployment-admission"
WORKFLOW_RUNNER_HOLD_LIBRARY="${REPOSITORY_ROOT}/scripts/api/workflow_runner_deployment_hold.sh"
RELEASE_OPERATOR_LIBRARY="${REPOSITORY_ROOT}/scripts/api/release_operator_boundary.sh"
WORKFLOW_RUNNER_HOLD_SOURCE="${REPOSITORY_ROOT}/infra/systemd/zzzz-eom-workflow-runner-deployment-hold.conf"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_workflow_runner_hold_release.py"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT="/usr/local/libexec/eom-api"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-workflow-runner-hold-release"
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED="/usr/local/libexec/eom-api/.verify-workflow-runner-hold-release.staged"
# The current and immediately preceding reviewed verifier bytes are immutable migration states.
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256="sha256:b2549defa8c9c41638d4e5fba66056545dc2bf89a2413c8dc5602fab6083dcbb"
# Exact verifier installed by the immediately preceding reviewed release. Replacing any other
# root-owned bytes is not an upgrade; it is unexplained privileged-state drift.
WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_PREDECESSOR_SHA256="sha256:e96645de007d435510a765fbade0769ed67273d697cae6db41aa68f3ed782500"
WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT="/var/lib/eom-api/mock-exam-retirement-receipts"
ACTION="verify"
PRESERVE_WORKFLOW_RUNNER_INACTIVE=false
STAGING_ROOT=""
SOURCE_ARCHIVE_PATH=""
SOURCE_ARCHIVE_SHA256=""
SOURCE_ROOT=""
SOURCE_TREE=""
VERSION=""
RELEASE_RECEIPT_FILE=""
RELEASE_EXECUTION_ID=""
RELEASE_EXECUTION_REVISION_ID=""
RELEASE_CHECKPOINT_SHA256=""
RELEASE_PRODUCTION_REQUEST_ID=""
RELEASE_PRODUCTION_PLAN_ID=""
RELEASE_PRODUCTION_PLAN_SHA256=""
RELEASE_OPERATOR_ID=""
RELEASE_RECEIPT_SHA256=""
RELEASE_WHEEL_INSPECTION_IDENTITY=""
RECOVERY_EXECUTION_ID=""
RECOVERY_EXECUTION_REVISION_ID=""
RECOVERY_CHECKPOINT_SHA256=""
RECOVERY_FAILURE_CODE=""

usage() {
  printf '%s\n' "usage: $0 [--build-only|--install|--install-preserve-workflow-runner-inactive|--verify]" \
    "       $0 --install-recover-retryable-blocked EXECUTION_ID EXECUTION_REVISION_ID CHECKPOINT_SHA256 FAILURE_CODE" \
    "       $0 --release-workflow-runner-hold RECEIPT_FILE EXECUTION_ID EXECUTION_REVISION_ID CHECKPOINT_SHA256 PRODUCTION_REQUEST_ID PRODUCTION_PLAN_ID PRODUCTION_PLAN_SHA256 OPERATOR_ID RECEIPT_SHA256"
}

if (($# > 0)) && [[ "$1" == "--install-recover-retryable-blocked" ]]; then
  (($# == 5)) || { usage >&2; exit 2; }
  ACTION="install"
  RECOVERY_EXECUTION_ID="$2"
  RECOVERY_EXECUTION_REVISION_ID="$3"
  RECOVERY_CHECKPOINT_SHA256="$4"
  RECOVERY_FAILURE_CODE="$5"
elif (($# > 0)) && [[ "$1" == "--release-workflow-runner-hold" ]]; then
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
source "${RELEASE_OPERATOR_LIBRARY}"

activate_workflow_runner_deployment_hold() {
  local activation_identity_before activation_identity_after runtime_mask_state staged_hold
  [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]] || return 0
  staged_hold="${WORKFLOW_RUNNER_HOLD_DIRECTORY}/.zzzz-eom-deployment-hold.staged"
  if [[ ! -e "${WORKFLOW_RUNNER_HOLD_TARGET}" && ! -L "${WORKFLOW_RUNNER_HOLD_TARGET}" && \
    ! -e "${staged_hold}" && ! -L "${staged_hold}" && \
    ! -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" && \
    ! -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]]; then
    activation_identity_before="$(
      workflow_runner_unheld_synchronized_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )" || \
      fail "${WORKFLOW_RUNNER_SERVICE} must be synchronized, unheld, and stopped before acquisition"
  else
    activation_identity_before="$(
      workflow_runner_stopped_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )" || \
      fail "${WORKFLOW_RUNNER_SERVICE} hold recovery state is not stopped and bounded"
  fi
  workflow_runner_require_base_unit_file "${WORKFLOW_RUNNER_FRAGMENT}" || \
    fail "workflow runner base unit identity mismatch"
  workflow_runner_require_source_hold_file \
    "${WORKFLOW_RUNNER_HOLD_SOURCE}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
    fail "canonical workflow runner deployment hold source mismatch"

  # Close the reboot window before materializing the hold, but do not reload here: an implicit
  # reload can garbage-collect this inactive unit and erase its last InvocationID. A concurrent
  # activation in this short disabled-but-not-yet-held interval is detected by the pinned identity.
  sudo -n /usr/bin/systemctl disable --no-reload "${WORKFLOW_RUNNER_SERVICE}" >/dev/null || \
    fail "workflow runner could not be disabled before hold activation"
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

  # Re-enable only after the hold is durable on disk. --no-reload keeps the stopped unit's prior
  # invocation identity available until the one reload that exposes the enabled hold.
  sudo -n /usr/bin/systemctl enable --no-reload "${WORKFLOW_RUNNER_SERVICE}" >/dev/null || \
    fail "workflow runner could not be re-enabled under its on-disk hold"
  activation_identity_after="$(
    workflow_runner_stopped_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner did not remain stopped before loading its persistent hold"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked while its on-disk hold was being enabled"
  activation_identity_before="${activation_identity_after}"
  sudo -n /usr/bin/systemctl daemon-reload || \
    fail "systemd could not load the workflow runner deployment hold"
  activation_identity_after="$(
    workflow_runner_deployment_hold_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner persistent deployment hold was not loaded safely"
  workflow_runner_require_same_activation_identity \
    "${activation_identity_before}" "${activation_identity_after}" || \
    fail "workflow runner was invoked while the persistent hold was loaded"

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

require_workflow_runner_hold_release_verifier_root() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}" metadata
  [[ "${expected_uid}" =~ ^[0-9]+$ && "${expected_gid}" =~ ^[0-9]+$ ]] || return 64
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" && \
    -d "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" ]] || \
    fail "installed workflow runner hold-release verifier directory is unavailable"
  metadata="$(
    /usr/bin/stat --format='%u:%g:%a' -- \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" 2>/dev/null
  )" || fail "installed workflow runner hold-release verifier directory metadata is unavailable"
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:755" ]] || \
    fail "installed workflow runner hold-release verifier directory identity mismatch"
}

require_workflow_runner_hold_release_verifier_target_identity() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}" metadata
  require_workflow_runner_hold_release_verifier_root \
    "${expected_uid}" "${expected_gid}"
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" && \
    -f "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" ]] || \
    fail "installed workflow runner hold-release verifier is unavailable"
  metadata="$(
    /usr/bin/stat --format='%u:%g:%a:%h' -- \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" 2>/dev/null
  )" || fail "installed workflow runner hold-release verifier metadata is unavailable"
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:755:1" ]] || \
    fail "installed workflow runner hold-release verifier identity mismatch"
}

require_workflow_runner_hold_release_verifier_staged() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}" metadata staged_sha256
  require_workflow_runner_hold_release_verifier_root \
    "${expected_uid}" "${expected_gid}"
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" && \
    -f "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" ]] || \
    fail "staged workflow runner hold-release verifier is unavailable"
  metadata="$(
    /usr/bin/stat --format='%u:%g:%a:%h' -- \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" 2>/dev/null
  )" || fail "staged workflow runner hold-release verifier metadata is unavailable"
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:755:1" ]] || \
    fail "staged workflow runner hold-release verifier identity mismatch"
  staged_sha256="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}")" || \
    fail "staged workflow runner hold-release verifier hash is unavailable"
  [[ "${staged_sha256}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
    fail "staged workflow runner hold-release verifier hash mismatch"
}

require_workflow_runner_hold_release_verifier_empty_incoming() {
  (($# == 1 || $# == 3)) || return 64
  local path="$1" expected_uid="${2:-0}" expected_gid="${3:-0}" metadata name parent
  parent="${path%/*}"
  name="${path##*/}"
  [[ "${parent}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" && \
    "${name}" =~ ^\.verify-workflow-runner-hold-release\.incoming\.[A-Za-z0-9]{12}$ ]] || \
    return 64
  require_workflow_runner_hold_release_verifier_root \
    "${expected_uid}" "${expected_gid}"
  [[ ! -L "${path}" && -f "${path}" ]] || \
    fail "workflow runner hold-release verifier incoming file is unavailable"
  metadata="$(/usr/bin/stat --format='%u:%g:%a:%h:%s' -- "${path}" 2>/dev/null)" || \
    fail "workflow runner hold-release verifier incoming metadata is unavailable"
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:600:1:0" ]] || \
    fail "workflow runner hold-release verifier incoming identity mismatch"
}

require_workflow_runner_hold_release_verifier_complete_incoming() {
  (($# == 1 || $# == 3)) || return 64
  local path="$1" expected_uid="${2:-0}" expected_gid="${3:-0}" incoming_sha256 metadata name parent
  parent="${path%/*}"
  name="${path##*/}"
  [[ "${parent}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" && \
    "${name}" =~ ^\.verify-workflow-runner-hold-release\.incoming\.[A-Za-z0-9]{12}$ ]] || \
    return 64
  require_workflow_runner_hold_release_verifier_root \
    "${expected_uid}" "${expected_gid}"
  [[ ! -L "${path}" && -f "${path}" ]] || \
    fail "complete workflow runner hold-release verifier incoming file is unavailable"
  metadata="$(/usr/bin/stat --format='%u:%g:%a:%h' -- "${path}" 2>/dev/null)" || \
    fail "complete workflow runner hold-release verifier incoming metadata is unavailable"
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:755:1" ]] || \
    fail "complete workflow runner hold-release verifier incoming identity mismatch"
  incoming_sha256="$(workflow_runner_file_sha256 "${path}")" || \
    fail "complete workflow runner hold-release verifier incoming hash is unavailable"
  [[ "${incoming_sha256}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
    fail "complete workflow runner hold-release verifier incoming hash mismatch"
}

cleanup_workflow_runner_hold_release_verifier_incoming() {
  (($# == 1 || $# == 3)) || return 64
  local path="$1" expected_uid="${2:-0}" expected_gid="${3:-0}" metadata name parent
  [[ -n "${path}" ]] || return 0
  [[ -e "${path}" || -L "${path}" ]] || return 0
  parent="${path%/*}"
  name="${path##*/}"
  [[ "${parent}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" && \
    "${name}" =~ ^\.verify-workflow-runner-hold-release\.incoming\.[A-Za-z0-9]{12}$ ]] || \
    return 1
  [[ ! -L "${path}" && -f "${path}" ]] || return 1
  metadata="$(/usr/bin/stat --format='%u:%g:%a:%h' -- "${path}" 2>/dev/null)" || return 1
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:600:1" || \
    "${metadata}" == "${expected_uid}:${expected_gid}:755:1" ]] || return 1
  sudo -n /usr/bin/rm -- "${path}"
}

materialize_workflow_runner_hold_release_verifier_staged() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}"
  (
    set -euo pipefail
    local incoming_path="" source_sha256_after
    trap 'cleanup_workflow_runner_hold_release_verifier_incoming \
      "${incoming_path}" "${expected_uid}" "${expected_gid}"' EXIT
    incoming_path="$(sudo -n /usr/bin/mktemp \
      --tmpdir="${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" \
      '.verify-workflow-runner-hold-release.incoming.XXXXXXXXXXXX')"
    require_workflow_runner_hold_release_verifier_empty_incoming \
      "${incoming_path}" "${expected_uid}" "${expected_gid}"
    sudo -n /usr/bin/install -o root -g root -m 0755 -T \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" "${incoming_path}"
    require_workflow_runner_hold_release_verifier_complete_incoming \
      "${incoming_path}" "${expected_uid}" "${expected_gid}"
    source_sha256_after="$(workflow_runner_file_sha256 \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
      fail "workflow runner hold-release verifier source hash is unavailable after incoming copy"
    [[ "${source_sha256_after}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
      fail "workflow runner hold-release verifier source changed during incoming copy"
    sudo -n /usr/bin/mv -T \
      "${incoming_path}" "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}"
    incoming_path=""
    require_workflow_runner_hold_release_verifier_staged \
      "${expected_uid}" "${expected_gid}"
  )
}

require_installed_workflow_runner_hold_release_verifier() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}" source_sha256 target_sha256
  [[ ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" && \
    -f "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" ]] || \
    fail "workflow runner hold-release verifier source is unavailable"
  require_workflow_runner_hold_release_verifier_target_identity \
    "${expected_uid}" "${expected_gid}"
  source_sha256="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
    fail "workflow runner hold-release verifier source hash is unavailable"
  target_sha256="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}")" || \
    fail "installed workflow runner hold-release verifier hash is unavailable"
  [[ "${target_sha256}" == "${source_sha256}" ]] || \
    fail "installed workflow runner hold-release verifier source drift"
}

install_workflow_runner_hold_release_verifier() {
  (($# == 0 || $# == 2)) || return 64
  local expected_uid="${1:-0}" expected_gid="${2:-0}"
  local existing_target_sha256 source_sha256_before source_sha256_after
  source_sha256_before="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
    fail "workflow runner hold-release verifier source hash is unavailable before installation"
  [[ "${source_sha256_before}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
    fail "workflow runner hold-release verifier source does not match the reviewed release"
  if [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" || \
    -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}" ]]; then
    require_workflow_runner_hold_release_verifier_root "${expected_uid}" "${expected_gid}"
  else
    sudo -n /usr/bin/install -d -o root -g root -m 0755 \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT}"
  fi
  require_workflow_runner_hold_release_verifier_root "${expected_uid}" "${expected_gid}"
  if [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" || \
    -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}" ]]; then
    # The previous release may contain older reviewed bytes, but its filesystem identity must be
    # exact before this release replaces it inside the root-owned directory.
    require_workflow_runner_hold_release_verifier_target_identity \
      "${expected_uid}" "${expected_gid}"
    existing_target_sha256="$(workflow_runner_file_sha256 \
      "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}")" || \
      fail "installed workflow runner hold-release verifier hash is unavailable before installation"
    [[ "${existing_target_sha256}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" || \
      "${existing_target_sha256}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_PREDECESSOR_SHA256}" \
    ]] || \
      fail "installed workflow runner hold-release verifier predecessor is unrecognized"
  fi
  if [[ "${existing_target_sha256:-}" == \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]]; then
    [[ ! -e "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" && \
      ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" ]] || \
      fail "current workflow runner hold-release verifier conflicts with a staged file"
    require_installed_workflow_runner_hold_release_verifier \
      "${expected_uid}" "${expected_gid}"
    return 0
  fi
  if [[ -e "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" || \
    -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" ]]; then
    require_workflow_runner_hold_release_verifier_staged \
      "${expected_uid}" "${expected_gid}"
  else
    materialize_workflow_runner_hold_release_verifier_staged \
      "${expected_uid}" "${expected_gid}"
  fi
  source_sha256_after="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
    fail "workflow runner hold-release verifier source hash is unavailable after installation"
  [[ "${source_sha256_after}" == "${source_sha256_before}" && \
    "${source_sha256_after}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
    fail "workflow runner hold-release verifier source changed during installation"
  require_workflow_runner_hold_release_verifier_staged \
    "${expected_uid}" "${expected_gid}"
  sudo -n /usr/bin/mv -T \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}"
  [[ ! -e "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" && \
    ! -L "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED}" ]] || \
    fail "staged workflow runner hold-release verifier remains after installation"
  require_installed_workflow_runner_hold_release_verifier \
    "${expected_uid}" "${expected_gid}"
  source_sha256_after="$(workflow_runner_file_sha256 \
    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}")" || \
    fail "workflow runner hold-release verifier source hash is unavailable after publication"
  [[ "${source_sha256_after}" == "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}" ]] || \
    fail "workflow runner hold-release verifier source changed during publication"
}

install_workflow_runner_hold_release_boundary() {
  id eom-api >/dev/null 2>&1 || fail "eom-api system user is absent"
  install_workflow_runner_hold_release_verifier

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
  # Recheck the independently protected verifier after the eom-api-owned path operation so an
  # interrupted pre-admission deployment always leaves one exact releasable boundary.
  require_installed_workflow_runner_hold_release_verifier
}

prepare_workflow_runner_hold_release_boundary_before_admission() {
  [[ "${PRESERVE_WORKFLOW_RUNNER_INACTIVE}" == true ]] || return 0
  verify_workflow_runner_deployment_hold
  install_workflow_runner_hold_release_boundary
  verify_workflow_runner_deployment_hold
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
  (($# == 2)) || return 64
  local target_present=false backup_present=false release_pre_state="UNSET"
  local base_sha256_before base_sha256_after
  local activation_identity_before activation_identity_after journal_cursor
  local journal_not_before="$1" journal_not_before_unix_us="$2"
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
  journal_cursor="$(
    workflow_runner_journal_cursor_at_or_before \
      /usr/bin/journalctl --system \
      "${journal_not_before}" "${journal_not_before_unix_us}"
  )" || fail "workflow runner release journal lower bound is unavailable"

  if [[ "${target_present}" == true ]]; then
    if activation_identity_before="$(
      workflow_runner_deployment_hold_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Normal release from the exact enabled hold.
      release_pre_state="HELD"
    elif activation_identity_before="$(
      workflow_runner_release_fenced_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Retry after a reboot preserved the disabled on-disk fence and loaded hold.
      release_pre_state="RELEASE_FENCED"
    elif activation_identity_before="$(
      workflow_runner_release_transition_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # Same-boot retry after disable --no-reload left the loaded hold pending reload.
      release_pre_state="TRANSITION"
    else
      fail "workflow runner deployment hold is not exact, disabled, and quiescent"
    fi
    # Do not let disable reload and garbage-collect the stopped unit before its identity is checked.
    # The removed enablement links are the durable reboot fence; the loaded hold remains the
    # same-boot manual/dependency fence until the explicit release reload below.
    sudo -n /usr/bin/systemctl disable --no-reload "${WORKFLOW_RUNNER_SERVICE}" >/dev/null || \
      fail "workflow runner could not be disabled before hold release"
    if activation_identity_after="$(
      workflow_runner_release_transition_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # A changed enablement link is pending manager reload under the cached hold.
    elif [[ "${release_pre_state}" == "RELEASE_FENCED" ]] && activation_identity_after="$(
      workflow_runner_release_fenced_activation_identity \
        /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
    )"; then
      : # An already-disabled reboot state remains synchronized after the idempotent disable.
    else
      fail "workflow runner was not disabled on disk under its loaded persistent hold"
    fi
    workflow_runner_require_same_activation_identity \
      "${activation_identity_before}" "${activation_identity_after}" || \
      fail "workflow runner was invoked while its release reboot fence was installed"
    activation_identity_before="${activation_identity_after}"
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
  workflow_runner_require_release_identity_with_journal_fence \
    "${activation_identity_before}" "${activation_identity_after}" \
    /usr/bin/journalctl --system "${WORKFLOW_RUNNER_SERVICE}" "${journal_cursor}" || \
    fail "workflow runner release identity lacks a clean journal fence"
  activation_identity_before="${activation_identity_after}"
  workflow_runner_require_base_unit_file "${WORKFLOW_RUNNER_FRAGMENT}" || \
    fail "workflow runner base unit identity changed during hold release"
  base_sha256_after="$(workflow_runner_file_sha256 "${WORKFLOW_RUNNER_FRAGMENT}")" || \
    fail "workflow runner base unit hash is unavailable after hold release"
  [[ "${base_sha256_after}" == "${base_sha256_before}" ]] || \
    fail "workflow runner base unit hash changed during hold release"
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || \
    fail "workflow runner deployment hold release backup changed unexpectedly"
  activation_identity_after="$(
    workflow_runner_released_activation_identity \
      /usr/bin/systemctl "${WORKFLOW_RUNNER_SERVICE}"
  )" || \
    fail "workflow runner changed state before deployment hold cleanup"
  workflow_runner_require_release_identity_with_journal_fence \
    "${activation_identity_before}" "${activation_identity_after}" \
    /usr/bin/journalctl --system "${WORKFLOW_RUNNER_SERVICE}" "${journal_cursor}" || \
    fail "workflow runner changed or emitted journal activity before hold cleanup"
  # Leave the exact backup in place until every fallible state/journal proof has passed. If a proof
  # fails, the immutable receipt cursor and backup make retry exact; after unlink, output loss is the
  # already-proven disabled/unheld no-op handled at the top of this function.
  sudo -n /usr/bin/rm -- "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" || \
    fail "workflow runner deployment hold release backup could not be removed"
  [[ ! -e "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" && \
    ! -L "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" ]] || \
    fail "workflow runner deployment hold release backup remains after removal"
  printf '%s\n' "workflow_runner_deployment_hold=RELEASED_INACTIVE_DISABLED"
  printf '%s\n' \
    "Explicitly enable --now eom-workflow-runner.service after the retirement receipt release."
}

release_workflow_runner_deployment_hold_after_verified_receipt() {
  local verifier_pid verifier_read_fd verifier_write_fd verifier_status verifier_confirmation
  local verifier_prefix journal_not_before journal_not_before_unix_us
  coproc WORKFLOW_RUNNER_RECEIPT_VERIFIER {
    verify_workflow_runner_hold_release_receipt --hold-lock-until-release-signal
  }
  verifier_pid="${WORKFLOW_RUNNER_RECEIPT_VERIFIER_PID}"
  verifier_read_fd="${WORKFLOW_RUNNER_RECEIPT_VERIFIER[0]}"
  verifier_write_fd="${WORKFLOW_RUNNER_RECEIPT_VERIFIER[1]}"
  verifier_prefix="workflow_runner_hold_release_receipt=VERIFIED_LOCKED journal_not_before="
  if ! IFS= read -r verifier_status <&"${verifier_read_fd}" || \
    [[ "${verifier_status}" != "${verifier_prefix}"* ]]; then
    exec {verifier_write_fd}>&-
    wait "${verifier_pid}" || true
    return 1
  fi
  journal_not_before="${verifier_status#"${verifier_prefix}"}"
  journal_not_before_unix_us="${journal_not_before##* journal_not_before_unix_us=}"
  journal_not_before="${journal_not_before%% journal_not_before_unix_us=*}"
  if [[ ! "${journal_not_before}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$ || \
    ! "${journal_not_before_unix_us}" =~ ^[0-9]{1,18}$ ]]; then
    exec {verifier_write_fd}>&-
    wait "${verifier_pid}" || true
    return 1
  fi

  # The verifier keeps an exclusive flock on the exact checkpoint until this mutation has either
  # completed or failed. No official checkpoint writer can advance between validation and release.
  if ! release_workflow_runner_deployment_hold \
    "${journal_not_before}" "${journal_not_before_unix_us}"; then
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
  local -a admission_arguments=()
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
  if [[ -n "${RECOVERY_EXECUTION_ID}" ]]; then
    admission_arguments=(
      --admit-exact-retryable-blocked
      "${RECOVERY_EXECUTION_ID}"
      "${RECOVERY_EXECUTION_REVISION_ID}"
      "${RECOVERY_CHECKPOINT_SHA256}"
      "${RECOVERY_FAILURE_CODE}"
    )
  fi
  sudo -n -u eom-api /usr/bin/env -i \
    HOME=/var/lib/eom-api \
    PATH=/usr/bin:/bin \
    PYTHONSAFEPATH=1 \
    "${API_PYTHON}" -I "${MOCK_EXAM_DEPLOYMENT_ADMISSION_TARGET}" \
    "${admission_arguments[@]}"
}

prepare_runtime_dependencies() {
  getent group eom-codex-auth >/dev/null || \
    fail "eom-codex-auth identity must be deployed before the API unit"
  run_release_operator MIGRATION_VERIFY_0062 "${COMMIT}"
  run_release_operator API_ROLE_BOOTSTRAP "${COMMIT}"
}

verify_native_pdf_annotation_runtime() {
  run_release_operator PDF_RUNTIME_VERIFY "${COMMIT}"
}

reconcile_installed_catalog_runtime_privileges() {
  # The Catalog runner has its own DB role and its privilege matrix ships in
  # the platform wheel. Reconcile it after installing the wheel so a release
  # that introduces new pointer-only tables cannot restart Catalog against the
  # preceding release's grant set.
  run_release_operator CATALOG_ROLE_RECONCILE "${COMMIT}"
}

reconcile_installed_hwpx_manager_runtime_privileges() {
  # The HWPX manager owns its build queues through a dedicated DB role. Keep
  # its closed privilege matrix synchronized after migrations add a new queue.
  run_release_operator HWPX_ROLE_RECONCILE "${COMMIT}"
}

cleanup() {
  if [[ -n "${STAGING_ROOT}" && -d "${STAGING_ROOT}" ]]; then
    rm -rf "${STAGING_ROOT}"
  fi
}
trap cleanup EXIT

[[ "$(id -un)" == "eom" ]] || fail "release builds must run as eom"
[[ "$("${GIT}" -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
CURRENT_BRANCH="$("${GIT}" -C "${REPOSITORY_ROOT}" branch --show-current)"
branch_allowed=false
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${CURRENT_BRANCH}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"
[[ -x "${API_PYTHON}" ]] || fail "isolated eom-api Python is unavailable"

COMMIT="$("${GIT}" -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
BUILD_PARENT="/tmp/eom-api-build"
BUILD_ROOT=""
DIST_DIR=""

require_clean_tree() {
  [[ "$("${GIT}" -C "${REPOSITORY_ROOT}" rev-parse HEAD)" == "${COMMIT}" ]] || \
    fail "repository HEAD changed after release identity was selected"
  [[ -z "$("${GIT}" -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
    fail "working tree must be clean before a release build"
}

materialize_release_source() {
  local archive_digest
  SOURCE_TREE="$("${GIT}" -C "${REPOSITORY_ROOT}" rev-parse "${COMMIT}^{tree}")"
  [[ "${COMMIT}" =~ ^[0-9a-f]{40}$ && "${SOURCE_TREE}" =~ ^[0-9a-f]{40}$ ]] || \
    fail "release commit and tree must use canonical lowercase SHA-1 identities"
  if "${GIT}" -C "${REPOSITORY_ROOT}" ls-tree -r "${COMMIT}" | \
    /usr/bin/awk '$1 == "120000" || $1 == "160000" { found = 1 } END { exit !found }'; then
    fail "release source cannot contain symlinks or unmaterialized Git submodules"
  fi
  SOURCE_ARCHIVE_PATH="${BUILD_ROOT}/source.tar"
  SOURCE_ROOT="${BUILD_ROOT}/source"
  mkdir -p "${SOURCE_ROOT}"
  "${GIT}" -C "${REPOSITORY_ROOT}" archive \
    --format=tar --output="${SOURCE_ARCHIVE_PATH}" "${COMMIT}"
  /usr/bin/chmod 0600 "${SOURCE_ARCHIVE_PATH}"
  read -r archive_digest _ < <("${SHA256SUM}" "${SOURCE_ARCHIVE_PATH}")
  [[ "${archive_digest}" =~ ^[0-9a-f]{64}$ ]] || \
    fail "release source archive hash is not canonical SHA-256"
  SOURCE_ARCHIVE_SHA256="sha256:${archive_digest}"
  "${TAR}" --extract --file="${SOURCE_ARCHIVE_PATH}" --directory="${SOURCE_ROOT}" \
    --no-same-owner --no-same-permissions
  VERSION="$(PYPROJECT="${SOURCE_ROOT}/apps/application_api/pyproject.toml" \
    "${API_PYTHON}" -c \
    'import os,pathlib,tomllib; print(tomllib.loads(pathlib.Path(os.environ["PYPROJECT"]).read_text())["project"]["version"])')"
}

verify_release_wheel_records() {
  local -a release_wheels
  if (($#)); then
    release_wheels=("$@")
  else
    release_wheels=("${DIST_DIR}"/*.whl)
  fi
  ((${#release_wheels[@]} == 3)) || fail "release wheels are unavailable for RECORD verification"
  /usr/bin/chmod 0600 "${release_wheels[@]}"
  "${API_PYTHON}" -I "${SOURCE_ROOT}/scripts/api/verify_release_wheel_records.py" \
    "${release_wheels[@]}"
}

capture_release_wheel_inspection_identity() {
  local -a release_wheels=("${DIST_DIR}"/*.whl)
  ((${#release_wheels[@]} == 3)) || fail "release wheels are unavailable for identity capture"
  /usr/bin/chmod 0600 "${release_wheels[@]}"
  RELEASE_WHEEL_INSPECTION_IDENTITY="$(
    "${API_PYTHON}" -I "${SOURCE_ROOT}/scripts/api/verify_release_wheel_records.py" \
      --emit-identity "${release_wheels[@]}"
  )"
  [[ "${RELEASE_WHEEL_INSPECTION_IDENTITY}" == \
    release_wheel_inspection_identity=\{* ]] || \
    fail "release wheel inspection identity output is invalid"
}

verify_captured_release_wheel_inspection_identity() {
  local observed
  (($# == 3)) || fail "release wheel identity verification requires exactly three wheels"
  [[ -n "${RELEASE_WHEEL_INSPECTION_IDENTITY}" ]] || \
    fail "release wheel inspection identity was not captured"
  observed="$(
    "${API_PYTHON}" -I "${SOURCE_ROOT}/scripts/api/verify_release_wheel_records.py" \
      --emit-identity "$@"
  )"
  [[ "${observed}" == "${RELEASE_WHEEL_INSPECTION_IDENTITY}" ]] || \
    fail "release wheel bytes changed after inspection"
}

build_release() {
  require_clean_tree
  mkdir -p "${BUILD_PARENT}"
  BUILD_ROOT="$(mktemp -d "${BUILD_PARENT}/${COMMIT}.XXXXXX")"
  DIST_DIR="${BUILD_ROOT}/dist"
  mkdir -p "${DIST_DIR}"
  STAGING_ROOT="$(mktemp -d "${BUILD_ROOT}/staging.XXXXXX")"
  materialize_release_source

  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${SOURCE_ROOT}" >/dev/null

  mkdir -p "${STAGING_ROOT}/contracts/eom_api_contracts/schemas"
  cp "${SOURCE_ROOT}/packages/api_contracts/pyproject.toml" \
    "${STAGING_ROOT}/contracts/pyproject.toml"
  cp -a "${SOURCE_ROOT}/packages/api_contracts/eom_api_contracts/." \
    "${STAGING_ROOT}/contracts/eom_api_contracts/"
  find "${STAGING_ROOT}/contracts/eom_api_contracts" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  cp "${SOURCE_ROOT}"/schemas/api/v1/*.schema.json \
    "${STAGING_ROOT}/contracts/eom_api_contracts/schemas/"
  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${STAGING_ROOT}/contracts" >/dev/null

  mkdir -p "${STAGING_ROOT}/application/eom_api"
  cp "${SOURCE_ROOT}/apps/application_api/pyproject.toml" \
    "${STAGING_ROOT}/application/pyproject.toml"
  cp -a "${SOURCE_ROOT}/apps/application_api/eom_api/." \
    "${STAGING_ROOT}/application/eom_api/"
  find "${STAGING_ROOT}/application/eom_api" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  mkdir -p "${STAGING_ROOT}/application/eom_api/openapi"
  cp "${SOURCE_ROOT}/api/openapi/eom-api-v1.openapi.json" \
    "${SOURCE_ROOT}/api/openapi/eom-api-v1.sha256" \
    "${STAGING_ROOT}/application/eom_api/openapi/"
  BUILD_TIMESTAMP="$(/usr/bin/date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    COMMIT="${COMMIT}" SOURCE_TREE="${SOURCE_TREE}" \
    SOURCE_ARCHIVE_SHA256="${SOURCE_ARCHIVE_SHA256}" \
    VERSION="${VERSION}" STAGING_ROOT="${STAGING_ROOT}" \
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
            "schema_version": "api-release-build-info/1.0",
            "source_archive_sha256": os.environ["SOURCE_ARCHIVE_SHA256"],
            "source_commit": os.environ["COMMIT"],
            "source_tree": os.environ["SOURCE_TREE"],
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

  verify_release_wheel_records
  inspect_release
  capture_release_wheel_inspection_identity
  printf 'Built and inspected EOM Application API %s from %s.\n' "${VERSION}" "${COMMIT}"
  printf 'application_api_release_wheel_dir=%s\n' "${DIST_DIR}"
}

inspect_release() {
  DIST_DIR="${DIST_DIR}" EXPECTED_COMMIT="${COMMIT}" EXPECTED_VERSION="${VERSION}" \
    EXPECTED_SOURCE_TREE="${SOURCE_TREE}" \
    EXPECTED_SOURCE_ARCHIVE_SHA256="${SOURCE_ARCHIVE_SHA256}" \
    SOURCE_ARCHIVE_PATH="${SOURCE_ARCHIVE_PATH}" \
    REPOSITORY_ROOT="${SOURCE_ROOT}" API_PYTHON="${API_PYTHON}" \
    "${API_PYTHON}" - <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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
        "eom_api/educational_quality_models.py",
        "eom_api/mock_exam_production_cli.py",
        "eom_api/runtime_isolation_pidfd.py",
        "eom_api/runtime_isolation_verifier.py",
        "eom_api/routers/control_plane.py",
        "eom_api/routers/educational_quality_reviews.py",
        "eom_api/routers/general_chat.py",
        "eom_api/routers/knowledge_analysis.py",
        "eom_api/routers/assessment_assemblies.py",
        "eom_api/routers/item_bank.py",
        "eom_api/routers/inference_transfer.py",
        "eom_api/routers/reference_queries.py",
        "eom_api/services/reference_query_preparation.py",
        "eom_api/services/reference_query_prepare_client.py",
        "eom_api/services/reference_item_start.py",
        "eom_api/services/reference_item_start_ports.py",
        "eom_api/services/reference_item_preparation.py",
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
        "eom_api/services/document_review_correction_service.py",
        "eom_api/services/document_review_annotation_service.py",
        "eom_api/services/educational_quality_service.py",
        "eom_api/services/general_chat_service.py",
        "eom_api/services/chat_knowledge_service.py",
        "eom_api/services/chat_knowledge_query_adapter.py",
        "eom_api/services/inference_transfer_snapshot.py",
        "eom_api/services/inference_transfer_snapshot_port.py",
        "eom_api/services/inference_transfer_snapshot_client.py",
        "eom_api/services/inference_transfer_snapshot_staging.py",
        "eom_api/services/inference_transfer_metadata.py",
        "eom_api/services/inference_transfer_metadata_client.py",
        "eom_api/services/inference_transfer_submission.py",
        "eom_api/services/inference_transfer_start_adapter.py",
        "eom_api/services/inference_transfer_workflow_client.py",
        "eom_api/services/inference_transfer_workflow_read.py",
        "eom_api/services/pdf_document_review_service.py",
        "eom_api/services/paired_document_review_service.py",
        "eom_api/services/pdf_upload_stager.py",
        "eom_api/routers/pdf_document_reviews.py",
        "eom_api/pdf_document_review_models.py",
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
    build_bytes = archive.read("eom_api/build-info.json")
    build = json.loads(build_bytes)
    canonical_build = (json.dumps(build, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    if build_bytes != canonical_build:
        raise SystemExit("Application API wheel build information is not canonical JSON")
    build_schema_path = (
        Path(os.environ["REPOSITORY_ROOT"])
        / "schemas/api/v1/api-release-build-info-v1.schema.json"
    )
    build_schema = json.loads(build_schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(build_schema)
    build_errors = tuple(
        Draft202012Validator(build_schema, format_checker=FormatChecker()).iter_errors(build)
    )
    if build_errors:
        raise SystemExit("Application API wheel build information violates its schema")
    if build["source_commit"] != os.environ["EXPECTED_COMMIT"]:
        raise SystemExit("Application API wheel source commit mismatch")
    if build["source_tree"] != os.environ["EXPECTED_SOURCE_TREE"]:
        raise SystemExit("Application API wheel source tree mismatch")
    if build["source_archive_sha256"] != os.environ["EXPECTED_SOURCE_ARCHIVE_SHA256"]:
        raise SystemExit("Application API wheel source archive mismatch")
    source_archive_path = Path(os.environ["SOURCE_ARCHIVE_PATH"])
    descriptor = os.open(source_archive_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
        ):
            raise SystemExit("Application API release source archive metadata mismatch")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise SystemExit("Application API release source archive changed during inspection")
    finally:
        os.close(descriptor)
    source_archive_sha256 = "sha256:" + digest.hexdigest()
    if build["source_archive_sha256"] != source_archive_sha256:
        raise SystemExit("Application API wheel source archive bytes mismatch")
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
    canonical_api_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/api/v1"
    expected_api_schemas = {
        "eom_api_contracts/schemas/" + path.name
        for path in canonical_api_root.glob("*.schema.json")
    }
    if not expected_api_schemas:
        raise SystemExit("canonical API schema inventory is unavailable")
    if schemas != expected_api_schemas:
        raise SystemExit(
            "packaged API schemas differ from the canonical release inventory, "
            f"missing={sorted(expected_api_schemas - schemas)} "
            f"unexpected={sorted(schemas - expected_api_schemas)}"
        )
    required_contract_runtime = {
        "eom_api_contracts/__init__.py",
        "eom_api_contracts/assessment_assemblies.py",
        "eom_api_contracts/customer_support.py",
        "eom_api_contracts/document_review.py",
        "eom_api_contracts/educational_quality.py",
        "eom_api_contracts/general_chat.py",
        "eom_api_contracts/chat_knowledge.py",
        "eom_api_contracts/inference_transfer.py",
        "eom_api_contracts/reference_queries.py",
        "eom_api_contracts/workflow_reference_start.py",
        "eom_api_contracts/item_bank.py",
        "eom_api_contracts/mock_exam_execution.py",
        "eom_api_contracts/mock_exam_retirement.py",
        "eom_api_contracts/preset_model_selection.py",
        "eom_api_contracts/system.py",
        "eom_api_contracts/workflows.py",
    }
    if missing := required_contract_runtime - names:
        raise SystemExit(f"mock-exam API contract runtime missing from wheel: {sorted(missing)}")
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
chat_schema_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/general-chat"
chat_resources = {
    "eom_protocol/schemas/" + path.name: path
    for path in chat_schema_root.glob("*.schema.json")
}
chat_resources["eom_protocol/schemas/general-chat-views.schema.json"] = (
    canonical_api_root / "general-chat-v1.schema.json"
)
chat_source_root = (
    Path(os.environ["REPOSITORY_ROOT"]) / "services/orchestrator/eom_orchestrator"
)
chat_protocol_root = (
    Path(os.environ["REPOSITORY_ROOT"]) / "packages/protocol/eom_protocol"
)
chat_runtime = {
    "eom_orchestrator/" + path.name for path in chat_source_root.glob("general_chat*.py")
} | {
    "eom_protocol/" + path.name for path in chat_protocol_root.glob("general_chat*.py")
}
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
        "eom_orchestrator/auth_enrollment_processor.py",
        "eom_orchestrator/auth_enrollment_capabilities.py",
        "eom_orchestrator/auth_enrollment_capability_admission.py",
        "eom_orchestrator/capability_snapshot_queries.py",
        "eom_orchestrator/reviewed_capability_policy.py",
        "eom_orchestrator/capability_observer.py",
        "eom_orchestrator/capacity_controller.py",
        "eom_orchestrator/control_artifacts.py",
        "eom_orchestrator/control_bootstrap.py",
        "eom_orchestrator/customer_support_bootstrap.py",
        "eom_orchestrator/inference_transfer_bootstrap.py",
        "eom_orchestrator/inference_transfer_control_auth.py",
        "eom_orchestrator/inference_transfer_control_invocation.py",
        "eom_orchestrator/inference_transfer_cpu_handoff.py",
        "eom_orchestrator/inference_transfer_cpu_systemd.py",
        "eom_orchestrator/inference_transfer_cpu_installation.py",
        "eom_orchestrator/inference_transfer_resolution.py",
        "eom_orchestrator/inference_transfer_snapshot_staging.py",
        "eom_orchestrator/inference_transfer_experiment_ports.py",
        "eom_orchestrator/inference_transfer_experiment_workspace.py",
        "eom_orchestrator/inference_transfer_experiment_execution.py",
        "eom_orchestrator/inference_transfer_experiment_artifacts.py",
        "eom_orchestrator/inference_transfer_experiment_invocation.py",
        "eom_orchestrator/inference_transfer_owner_http.py",
        "eom_orchestrator/inference_transfer_human_review.py",
        "eom_orchestrator/inference_transfer_human_review_artifacts.py",
        "eom_orchestrator/knowledge_item_bootstrap.py",
        "eom_orchestrator/control_command_processor.py",
        "eom_orchestrator/control_commands.py",
        "eom_orchestrator/control_models.py",
        "eom_orchestrator/control_service.py",
        "eom_orchestrator/execution_materializer.py",
        "eom_orchestrator/execution_resolver.py",
        "eom_orchestrator/external_item_learning_controls.py",
        "eom_orchestrator/external_item_learning_control_release.py",
        "eom_orchestrator/external_item_learning_policy_preparation.py",
        "eom_orchestrator/external_item_learning_execution.py",
        "eom_orchestrator/external_item_learning_page_render.py",
        "eom_orchestrator/external_item_learning_page_publication.py",
        "eom_orchestrator/migration.py",
        "eom_orchestrator/workflow_job_retirement.py",
        "eom_orchestrator/legacy_item_extraction_artifact.py",
        "eom_orchestrator/legacy_item_extraction_bootstrap.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_artifact.py",
        "eom_orchestrator/legacy_item_editorial_compatibility_bootstrap.py",
        "eom_orchestrator/preset_lifecycle.py",
        "eom_orchestrator/preset_model_evidence.py",
        "eom_orchestrator/preset_model_release.py",
        "eom_orchestrator/preset_model_selection.py",
        "eom_orchestrator/preset_model_validation.py",
        "eom_orchestrator/preset_model_validation_processor.py",
        "eom_orchestrator/preset_policy.py",
        "eom_orchestrator/svg_label_layout_validation.py",
        "eom_workflow/control_plane.py",
        "eom_workflow/control_schemas.py",
        "eom_workflow/preset_model_validation.py",
        "eom_workflow/inference_transfer.py",
        "eom_workflow/inference_transfer_control.py",
        "eom_workflow/inference_transfer_bootstrap_contract.py",
        "eom_workflow/inference_transfer_control_invocation.py",
        "eom_workflow/inference_transfer_materialization.py",
        "eom_workflow/inference_transfer_workflow.py",
        "eom_workflow/models.py",
        "eom_workflow_runner/composition.py",
        "eom_workflow_runner/engine.py",
        "eom_workflow_runner/models.py",
        "eom_workflow_runner/repository.py",
        "eom_workflow_runner/inference_transfer_admission.py",
        "eom_workflow_runner/inference_transfer_execution_port.py",
        "eom_workflow_runner/inference_transfer_executor.py",
        "eom_workflow_runner/role_execution_binding.py",
        "eom_workflow_runner/role_execution_port.py",
        "eom_workflow_runner/external_item_learning_admission.py",
        "eom_workflow_runner/external_item_learning_preparation.py",
        "eom_workflow_runner/external_item_learning_catalog_client.py",
        "eom_workflow_runner/mock_exam_production_retirement.py",
        "eom_workflow_runner/retirement_quiescence.py",
        "eom_workflow_runner/systemd_retirement_quiescence.py",
        "eomctl/cli.py",
        "eomctl/creative_learning.py",
        "eomctl/control_plane.py",
        "eomctl/inference_transfer_controls.py",
        "eomctl/knowledge.py",
        "eomctl/legacy_assessment.py",
    }
    catalog_staging_runtime = {
        "eom_catalog_service/external_creative_learning_source.py",
        "eom_catalog_service/external_item_learning_preparation_service.py",
        "eom_catalog_service/external_item_learning_authorization_service.py",
        "eom_catalog_service/external_item_learning_authorization_dispatch.py",
        "eom_catalog_service/chat_knowledge_discovery.py",
        "eom_catalog_service/chat_knowledge_resolution.py",
        "eom_catalog_service/chat_knowledge_search.py",
        "eom_catalog_service/chat_rag_resolution.py",
        "eom_image_contracts/models.py",
        "eom_image_contracts/safe_svg.py",
        "eom_image_contracts/svg_label_layout.py",
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
        "eom_catalog_contracts/document_review.py",
        "eom_catalog_contracts/document_review_application.py",
        "eom_catalog_contracts/document_review_evidence.py",
        "eom_catalog_contracts/item_review.py",
        "eom_catalog_contracts/knowledge.py",
        "eom_catalog_contracts/item_inference_transfer.py",
        "eom_catalog_contracts/inference_transfer_experiment.py",
        "eom_catalog_contracts/inference_transfer_embedding.py",
        "eom_catalog_contracts/inference_transfer_retry.py",
        "eom_catalog_contracts/inference_transfer_snapshot_timing.py",
        "eom_catalog_contracts/inference_transfer_human_review.py",
        "eom_catalog_contracts/inference_transfer_snapshot.py",
        "eom_catalog_contracts/inference_transfer_snapshot_binding.py",
        "eom_catalog_contracts/inference_transfer_invocation.py",
        "eom_catalog_contracts/inference_transfer_invocation_v11.py",
        "eom_catalog_contracts/inference_transfer_pair_result_v11.py",
        "eom_catalog_contracts/inference_transfer_workflow_binding.py",
        "eom_catalog_contracts/inference_transfer_workflow_binding_v11.py",
        "eom_catalog_contracts/inference_transfer_text.py",
        "eom_catalog_contracts/inference_transfer_metadata.py",
        "eom_catalog_contracts/knowledge_analysis_batch.py",
        "eom_catalog_contracts/item_origin.py",
        "eom_catalog_contracts/legacy_assessment.py",
        "eom_catalog_contracts/legacy_item_media_compatibility.py",
        "eom_catalog_contracts/resources/legacy-assessment/legacy-item-media-pointer-compatibility-v1.json",
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
        "eom_catalog_service/inference_transfer_catalog_adapter.py",
        "eom_catalog_service/inference_transfer_comparison.py",
        "eom_catalog_service/inference_transfer_cpu_stdio.py",
        "eom_catalog_service/inference_transfer_cpu_verifier.py",
        "eom_catalog_service/inference_transfer_evaluation.py",
        "eom_catalog_service/inference_transfer_experiment.py",
        "eom_catalog_service/inference_transfer_item_projection.py",
        "eom_catalog_service/inference_transfer_ports.py",
        "eom_catalog_service/inference_transfer_population_read_set.py",
        "eom_catalog_service/inference_transfer_projection.py",
        "eom_catalog_service/inference_transfer_read_timing.py",
        "eom_catalog_service/inference_transfer_scope.py",
        "eom_catalog_service/inference_transfer_service.py",
        "eom_catalog_service/inference_transfer_snapshot_catalog_adapter.py",
        "eom_catalog_service/inference_transfer_snapshot_dispatch.py",
        "eom_catalog_service/inference_transfer_snapshot_service.py",
        "eom_catalog_service/inference_transfer_metadata_service.py",
        "eom_catalog_service/inference_transfer_metadata_dispatch.py",
        "eom_catalog_service/inference_transfer_vectors.py",
        "eom_catalog_service/inference_transfer_worker_preparation.py",
        "eom_catalog_service/inference_transfer_workflow_dispatch.py",
        "eom_catalog_service/inference_transfer_workflow_dispatch_v11.py",
        "eom_catalog_service/inference_transfer_workflow_read.py",
        "eom_catalog_service/item_content_import.py",
        "eom_catalog_service/item_origin_models.py",
        "eom_catalog_service/item_origin_service.py",
        "eom_catalog_service/knowledge_analysis_risk.py",
        "eom_catalog_service/knowledge_analysis_batch_models.py",
        "eom_catalog_service/knowledge_analysis_batch_service.py",
        "eom_catalog_service/knowledge_analysis_service.py",
        "eom_catalog_service/knowledge_analysis_sources.py",
        "eom_catalog_service/past_exam_source_provenance.py",
        "eom_catalog_service/knowledge_graph_models.py",
        "eom_catalog_service/knowledge_graph_publication_service.py",
        "eom_catalog_service/knowledge_stimulus.py",
        "eom_catalog_service/knowledge_retrieval_service.py",
        "eom_catalog_service/local_image_adapter.py",
        "eom_catalog_service/mock_exam_assembly_service.py",
        "eom_catalog_service/mock_exam_candidate_repository.py",
        "eom_catalog_service/mock_exam_item_review_publication_service.py",
        "eom_catalog_service/document_review_hwpx.py",
        "eom_catalog_service/document_review_hwpx_correction_service.py",
        "eom_catalog_service/document_review_pdf_annotation.py",
        "eom_catalog_service/document_review_pdf_annotation_service.py",
        "eom_catalog_service/document_review_evidence_service.py",
        "eom_catalog_service/office_converter_worker.py",
        "eom_catalog_service/office_document_converter.py",
        "eom_catalog_service/office_document_review_intake.py",
        "eom_catalog_service/pdf_document_review_intake.py",
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
        "eom_catalog_service/legacy_item_media_compatibility_service.py",
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
        | chat_runtime
        | chat_resources.keys()
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
    for member in sorted(chat_runtime | chat_resources.keys()):
        if member not in record:
            raise SystemExit(f"general chat runtime missing from RECORD: {member}")
    for member, canonical in chat_resources.items():
        if archive.read(member) != canonical.read_bytes():
            raise SystemExit(f"general chat schema resource drift: {canonical.name}")
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
# Read the authoritative frozen registry as data without importing source packages.
# The isolated installed-wheel check below independently verifies its public inventory.
def catalog_resources_from_registry(source: str) -> dict[str, str]:
    assignments = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "CATALOG_SCHEMA_RESOURCES"
    ]
    if len(assignments) != 1:
        raise SystemExit("Catalog Contract source registry is unavailable")
    wrapper = assignments[0].value
    if (
        not isinstance(wrapper, ast.Call)
        or not isinstance(wrapper.func, ast.Name)
        or wrapper.func.id != "MappingProxyType"
        or len(wrapper.args) != 1
        or wrapper.keywords
        or not isinstance(wrapper.args[0], ast.Dict)
    ):
        raise SystemExit("Catalog Contract source registry is not frozen literal data")
    result: dict[str, str] = {}
    families: set[str] = set()
    for family_node, resource in zip(wrapper.args[0].keys, wrapper.args[0].values, strict=True):
        if family_node is None:
            raise SystemExit("Catalog Contract source family identity is invalid")
        family = ast.literal_eval(family_node)
        if not isinstance(family, str) or not family or family in families:
            raise SystemExit("Catalog Contract source family identity is invalid")
        families.add(family)
        if (
            not isinstance(resource, ast.Call)
            or not isinstance(resource.func, ast.Name)
            or resource.func.id != "CatalogSchemaResource"
            or len(resource.args) != 4
            or resource.keywords
        ):
            raise SystemExit("Catalog Contract source resource is not literal data")
        canonical, packaged = (ast.literal_eval(value) for value in resource.args[:2])
        if (
            not isinstance(canonical, str)
            or not canonical.startswith("schemas/")
            or not isinstance(packaged, str)
            or not packaged.startswith("resources/")
            or any(part in {"", ".", ".."} for part in canonical.split("/"))
            or any(part in {"", ".", ".."} for part in packaged.split("/"))
        ):
            raise SystemExit("Catalog Contract source resource path is invalid")
        resource_name = packaged.removeprefix("resources/")
        if resource_name in result and result[resource_name] != canonical:
            raise SystemExit("Catalog Contract source resource identity conflicts")
        result[resource_name] = canonical
    return result


catalog_resources = catalog_resources_from_registry(
    (
        Path(os.environ["REPOSITORY_ROOT"])
        / "packages/catalog_contracts/eom_catalog_contracts/validation.py"
    ).read_text(encoding="utf-8")
)
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
            f"missing={sorted(expected - packaged)} extra={sorted(packaged - expected)}"
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
    source.name: source.relative_to(Path(os.environ["REPOSITORY_ROOT"])).as_posix()
    for source in sorted(
        (Path(os.environ["REPOSITORY_ROOT"]) / "schemas/image-provider").glob("*.schema.json")
    )
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
    for version in (
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "1.7",
        "1.8",
        "1.9",
        "1.10",
        "1.11",
        "1.12",
        "1.13",
        "1.14",
        "1.15",
        "1.16",
    ):
        definition = root / f"generic-item-development.v{version}.yaml"
        definition.write_bytes(
            (
                Path(os.environ["REPOSITORY_ROOT"])
                / f"config/workflows/generic-item-development.v{version}.yaml"
            ).read_bytes()
        )
        definitions.append(definition)
    analysis_definitions = []
    for version in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10"):
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
    creative_definition = root / "external-item-learning.v1.yaml"
    creative_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/external-item-learning.v1.yaml"
        ).read_bytes()
    )
    editorial_definition = root / "legacy-item-editorial-compatibility.v1.yaml"
    editorial_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/legacy-item-editorial-compatibility.v1.yaml"
        ).read_bytes()
    )
    customer_support_definition = root / "customer-support.v1.yaml"
    customer_support_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/customer-support.v1.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1 = root / "pdf-document-review.v1.yaml"
    pdf_document_review_definition_v1.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1_1 = root / "pdf-document-review.v1.1.yaml"
    pdf_document_review_definition_v1_1.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.1.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1_2 = root / "pdf-document-review.v1.2.yaml"
    pdf_document_review_definition_v1_2.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.2.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1_3 = root / "pdf-document-review.v1.3.yaml"
    pdf_document_review_definition_v1_3.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.3.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1_4 = root / "pdf-document-review.v1.4.yaml"
    pdf_document_review_definition_v1_4.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.4.yaml"
        ).read_bytes()
    )
    pdf_document_review_definition_v1_5 = root / "pdf-document-review.v1.5.yaml"
    pdf_document_review_definition_v1_5.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/pdf-document-review.v1.5.yaml"
        ).read_bytes()
    )
    inference_transfer_definition = root / "item-inference-transfer-comparison.v1.yaml"
    inference_transfer_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/item-inference-transfer-comparison.v1.yaml"
        ).read_bytes()
    )
    inference_transfer_definition_v1_1 = root / "item-inference-transfer-comparison.v1_1.yaml"
    inference_transfer_definition_v1_1.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/item-inference-transfer-comparison.v1_1.yaml"
        ).read_bytes()
    )
    local_embedding_definition = root / "local-embedding-index.v1.yaml"
    local_embedding_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/local-embedding-index.v1.yaml"
        ).read_bytes()
    )
    local_embedding_definition_v2 = root / "local-embedding-index.v2.yaml"
    local_embedding_definition_v2.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/local-embedding-index.v2.yaml"
        ).read_bytes()
    )
    reference_query_definition = root / "local-embedding-reference-query.v1.yaml"
    reference_query_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/local-embedding-reference-query.v1.yaml"
        ).read_bytes()
    )
    private_chat_query_definition = root / "local-embedding-private-chat-query.v1.yaml"
    private_chat_query_definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/local-embedding-private-chat-query.v1.yaml"
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
                str(by_prefix["eom_application_api"]),
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
import json
import os
import sys
from pathlib import Path
from pydantic import TypeAdapter

installed_root = Path(sys.argv[1]).resolve()
repository, definition_v1_1, definition_v1_2, definition_v1_3, definition_v1_4, definition_v1_5, definition_v1_6, definition_v1_7, definition_v1_8, definition_v1_9, definition_v1_10, definition_v1_11, definition_v1_12, definition_v1_13, definition_v1_14, definition_v1_15, definition_v1_16, analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6, analysis_v7, analysis_v8, analysis_v9, analysis_v10, legacy_definition, editorial_definition, customer_support_definition, pdf_document_review_definition_v1, pdf_document_review_definition_v1_1, pdf_document_review_definition_v1_2, pdf_document_review_definition_v1_3, pdf_document_review_definition_v1_4, pdf_document_review_definition_v1_5, inference_transfer_definition, inference_transfer_definition_v1_1, local_embedding_definition, local_embedding_definition_v2, reference_query_definition, private_chat_query_definition, worker_config, staging, workspace_root, codex_binary, expected_commit, expected_tree, expected_archive_sha256, expected_catalog_resources_json = sys.argv[2:]
sys.path.insert(0, str(installed_root))
os.environ["EOM_WORKER_CONFIG"] = worker_config
os.environ["EOM_STAGING_ROOT"] = staging
os.environ["EOM_WORKSPACE_ROOT"] = workspace_root
os.environ["EOM_CODEX_BINARY"] = codex_binary
from eom_workflow import AgentStep, WORKFLOW_ADMISSION_BY_IDENTITY
from eom_workflow.control_schemas import control_schema_inventory, load_control_schema
from eom_api_contracts import (
    ApiReleaseBuildInfo,
    CreateEducationalQualityPlanCommand,
    EducationalQualityReviewWorkbenchView,
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecution,
    MockExamProductionExecutionV1,
    MockExamProductionExecutionV2,
    MockExamProductionExecutionV3,
    MockExamProductionExecutionV4,
    MockExamProductionExecutionV5,
    MockExamProductionRetirementCommandV1,
    MockExamProductionRetirementReceiptV1,
    mock_exam_production_is_terminal,
)
from eom_api.build_info import get_build_info
from eom_workflow.compiler import compile_definition
from eom_workflow.definition_execution_protocol import definition_execution_protocol
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

creative_definition = Path(legacy_definition).with_name("external-item-learning.v1.yaml")

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
customer_support_help = CliRunner().invoke(
    eomctl_app,
    ["control-plane", "bootstrap-customer-support", "--help"],
)
if (
    customer_support_help.exit_code != 0
    or "bootstrap-customer-support" not in customer_support_help.stdout
):
    raise SystemExit("installed-wheel eomctl customer-support bootstrap command is unavailable")
pdf_document_review_help = CliRunner().invoke(
    eomctl_app,
    ["control-plane", "bootstrap-pdf-document-review", "--help"],
)
if (
    pdf_document_review_help.exit_code != 0
    or "bootstrap-pdf-document-review" not in pdf_document_review_help.stdout
):
    raise SystemExit("installed-wheel eomctl PDF document-review bootstrap is unavailable")
creative_prepare_help = CliRunner().invoke(
    eomctl_app,
    ["content", "external-items", "learning", "prepare", "--help"],
)
if (
    creative_prepare_help.exit_code != 0
    or "--request-file" not in creative_prepare_help.stdout
    or "--start" in creative_prepare_help.stdout
):
    raise SystemExit("installed-wheel creative PREPARE-only command is unavailable")
if any(
    model.__module__ != "eom_api_contracts.mock_exam_execution"
    for model in (
        MockExamExplicitAnalysisReviewSetV1,
        MockExamExplicitRatingSetV1,
        MockExamGenerationBlockResolutionV1,
        MockExamGraphPublicationInputV1,
        MockExamProductionExecutionV1,
        MockExamProductionExecutionV2,
        MockExamProductionExecutionV3,
        MockExamProductionExecutionV4,
        MockExamProductionExecutionV5,
    )
):
    raise SystemExit("mock-exam contract package exports are incomplete")
if ApiReleaseBuildInfo.__module__ != "eom_api_contracts.system":
    raise SystemExit("API release build information contract export is incomplete")
if (
    CreateEducationalQualityPlanCommand.__module__
    != "eom_api_contracts.educational_quality"
    or EducationalQualityReviewWorkbenchView.__module__
    != "eom_api_contracts.educational_quality"
):
    raise SystemExit("educational quality review contract package exports are incomplete")
build_info = get_build_info()
if (
    build_info.source_commit != expected_commit
    or build_info.source_tree != expected_tree
    or build_info.source_archive_sha256 != expected_archive_sha256
):
    raise SystemExit("installed-wheel API release source identity mismatch")
# Matching two stale snapshot files does not prove that current routes match them.
# Construct the installed application offline; never load production credentials
# or open a database connection to inspect its public contract.
from eom_api.app import create_app
from eom_api.lifespan import build_services
from eom_api.settings import ApiSecrets, ApiSettings
from pydantic import SecretStr

contract_services = build_services(
    ApiSettings(),
    ApiSecrets(
        database_url=SecretStr("postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid"),
        token_hash_key=SecretStr("contract-inspection-token-key-not-a-runtime-secret"),
        fingerprint_key=SecretStr("contract-inspection-fingerprint-key-not-a-runtime-secret"),
    ),
)
try:
    generated_openapi = create_app(contract_services).openapi()
    packaged_openapi = json.loads(
        (installed_root / "eom_api/openapi/eom-api-v1.openapi.json").read_bytes()
    )
    if generated_openapi != packaged_openapi:
        raise SystemExit("installed-wheel OpenAPI does not match current application routes")
finally:
    contract_services.engine.dispose()
if mock_exam_production_is_terminal.__module__ != "eom_api_contracts.mock_exam_execution":
    raise SystemExit("mock-exam terminal-state contract export is incomplete")
execution_discriminator = TypeAdapter(MockExamProductionExecution).json_schema().get(
    "discriminator", {}
)
if set(execution_discriminator.get("mapping", {})) != {
    "mock-exam-production-execution/1.0",
    "mock-exam-production-execution/2.0",
    "mock-exam-production-execution/3.0",
    "mock-exam-production-execution/4.0",
    "mock-exam-production-execution/5.0",
}:
    raise SystemExit("mock-exam execution successor dispatch export is incomplete")
if any(
    model.__module__ != "eom_api_contracts.mock_exam_retirement"
    for model in (
        MockExamProductionRetirementCommandV1,
        MockExamProductionRetirementReceiptV1,
    )
):
    raise SystemExit("mock-exam retirement contract package exports are incomplete")
if CURRENT_MIGRATION_REVISION != "20261027_0062":
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
load_role_input_schema("support", "workflow-role/1.21.0")
load_role_input_schema("support", "workflow-role/1.22.0")
load_role_input_schema("support", "workflow-role/1.25.0")
load_role_input_schema("support", "workflow-role/1.26.0")
load_role_input_schema("support", "workflow-role/1.27.0")
load_role_input_schema("support", "workflow-role/1.33.0")
load_codex_result_schema("external-item-learning-result@1.0")
load_role_input_schema("support", "workflow-role/1.28.0")
load_role_input_schema("support", "workflow-role/1.29.0")
load_role_input_schema("support", "workflow-role/1.30.0")
load_role_input_schema("support", "workflow-role/1.31.0")
load_role_input_schema("support", "workflow-role/1.32.0")
load_role_input_schema("authoring", "workflow-role/1.19.0")
load_role_input_schema("image", "workflow-role/1.19.0")
load_role_input_schema("review", "workflow-role/1.19.0")
load_role_input_schema("item_management", "workflow-role/1.19.0")
load_role_input_schema("authoring", "workflow-role/1.20.0")
load_role_input_schema("image", "workflow-role/1.20.0")
load_role_input_schema("review", "workflow-role/1.20.0")
load_role_input_schema("item_management", "workflow-role/1.20.0")
load_role_input_schema("authoring", "workflow-role/1.23.0")
load_role_input_schema("image", "workflow-role/1.23.0")
load_role_input_schema("review", "workflow-role/1.23.0")
load_role_input_schema("item_management", "workflow-role/1.23.0")
load_role_input_schema("authoring", "workflow-role/1.24.0")
load_role_input_schema("image", "workflow-role/1.24.0")
load_role_input_schema("review", "workflow-role/1.24.0")
load_role_input_schema("item_management", "workflow-role/1.24.0")
for schema_id in RESULT_SCHEMA_FILES:
    load_role_result_schema(schema_id)
    load_codex_result_schema(schema_id)
control_schema_names = {name for name, _ in control_schema_inventory()}
if not {
    "inference-transfer-control-bootstrap",
    "inference-transfer-control-bootstrap-v1.1",
    "inference-transfer-control-invocation",
    "inference-transfer-control-invocation-v1.1",
    "resolved-execution-plan-v21",
    "resolved-execution-plan-v22",
    "resolved-execution-plan-v26",
    "standard-control-bootstrap-v10",
    "knowledge-item-control-bootstrap-v7",
    "standard-control-bootstrap-v11",
    "knowledge-item-control-bootstrap-v8",
    "standard-control-bootstrap-v12",
    "knowledge-item-control-bootstrap-v9",
    "standard-control-bootstrap-v13",
    "knowledge-item-control-bootstrap-v10",
    "standard-control-bootstrap-v14",
    "knowledge-item-control-bootstrap-v11",
    "standard-control-bootstrap-v15",
    "knowledge-item-control-bootstrap-v12",
    "standard-control-bootstrap-v16",
    "knowledge-item-control-bootstrap-v13",
    "standard-control-bootstrap-v17",
    "knowledge-item-control-bootstrap-v14",
    "customer-support-control-bootstrap",
    "pdf-document-review-control-bootstrap",
    "pdf-document-review-control-bootstrap-v2",
    "pdf-document-review-control-bootstrap-v3",
    "pdf-document-review-control-bootstrap-v4",
    "pdf-document-review-control-bootstrap-v5",
    "pdf-document-review-control-bootstrap-v6",
    "pdf-document-review-control-bootstrap-v7",
    "resolved-execution-plan-v14",
    "resolved-execution-plan-v15",
    "resolved-execution-plan-v16",
    "resolved-execution-plan-v18",
    "resolved-execution-plan-v19",
    "resolved-execution-plan-v20",
    "document-review-evidence-validation-receipt",
    "resolved-execution-plan-v10",
    "resolved-execution-plan-v13",
    "worker-capacity-policy-v4",
}.issubset(control_schema_names):
    raise SystemExit("control-policy successor schema inventory is incomplete")
for schema_name in control_schema_names:
    load_control_schema(schema_name)
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
        definition_v1_10,
        definition_v1_11,
        definition_v1_12,
        definition_v1_13,
        definition_v1_14,
        definition_v1_15,
        definition_v1_16,
    )
}
if compiled_versions != {"1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.8.0", "1.9.0", "1.10.0", "1.11.0", "1.12.0", "1.13.0", "1.14.0", "1.15.0", "1.16.0"}:
    raise SystemExit("generic workflow definition versions mismatch")
analysis_versions = {
    compile_definition(Path(path), {"support"}).definition.definition_version
    for path in (analysis_v1, analysis_v2, analysis_v3, analysis_v4, analysis_v5, analysis_v6, analysis_v7, analysis_v8, analysis_v9, analysis_v10)
}
if analysis_versions != {"1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0", "6.0.0", "7.0.0", "8.0.0", "9.0.0", "10.0.0"}:
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
customer_support = compile_definition(Path(customer_support_definition), {"support"}).definition
if (
    customer_support.definition_key != "customer-support"
    or customer_support.definition_version != "1.0.0"
):
    raise SystemExit("customer-support workflow definition mismatch")
pdf_document_reviews = tuple(
    compile_definition(Path(path), {"support"}).definition
    for path in (
        pdf_document_review_definition_v1,
        pdf_document_review_definition_v1_1,
        pdf_document_review_definition_v1_2,
        pdf_document_review_definition_v1_3,
        pdf_document_review_definition_v1_4,
        pdf_document_review_definition_v1_5,
    )
)
if tuple(
    (value.definition_key, value.definition_version) for value in pdf_document_reviews
) != (
    ("pdf-document-review", "1.0.0"),
    ("pdf-document-review", "1.1.0"),
    ("pdf-document-review", "1.2.0"),
    ("pdf-document-review", "1.3.0"),
    ("pdf-document-review", "1.4.0"),
    ("pdf-document-review", "1.5.0"),
):
    raise SystemExit("PDF document review workflow definition mismatch")
admitted_definitions = (
    compile_definition(Path(definition_v1_8), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_9), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_10), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_11), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_12), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_13), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_14), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_15), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(definition_v1_16), {"authoring", "image", "review", "item_management"}),
    compile_definition(Path(analysis_v1), {"support"}),
    compile_definition(Path(analysis_v4), {"support"}),
    compile_definition(Path(analysis_v8), {"support"}),
    compile_definition(Path(analysis_v9), {"support"}),
    compile_definition(Path(analysis_v10), {"support"}),
    compile_definition(Path(legacy_definition), {"support"}),
    compile_definition(creative_definition, {"support"}),
    compile_definition(Path(editorial_definition), {"support"}),
    compile_definition(Path(customer_support_definition), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1_1), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1_2), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1_3), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1_4), {"support"}),
    compile_definition(Path(pdf_document_review_definition_v1_5), {"support"}),
    compile_definition(Path(inference_transfer_definition), {"support"}),
    compile_definition(Path(inference_transfer_definition_v1_1), {"support"}),
    compile_definition(Path(local_embedding_definition), set()),
    compile_definition(Path(local_embedding_definition_v2), set()),
    compile_definition(Path(reference_query_definition), set()),
    compile_definition(Path(private_chat_query_definition), set()),
)
if {
    (compiled.definition.definition_key, compiled.definition.definition_version):
        definition_execution_protocol(compiled.definition)
    for compiled in admitted_definitions
} != {
    identity: admission.role_protocol_version
    for identity, admission in WORKFLOW_ADMISSION_BY_IDENTITY.items()
}:
    raise SystemExit("workflow admission policy does not match the installed definitions")
installed_catalog_resources = {
    resource.resource_path.removeprefix("resources/"): resource.canonical_path
    for _, resource in catalog_schema_inventory()
}
if installed_catalog_resources != json.loads(expected_catalog_resources_json):
    raise SystemExit("installed Catalog Contract inventory differs from the canonical registry")
catalog_schema_names = {name for name, _ in catalog_schema_inventory()}
if not {
    "item-inference-transfer",
    "item-inference-transfer-invocation",
    "item-inference-transfer-workflow-binding",
    "item-inference-transfer-invocation-v1.1",
    "item-inference-transfer-pair-result-v1.1",
    "item-inference-transfer-workflow-binding-v1.1",
}.issubset(catalog_schema_names):
    raise SystemExit("Catalog comparison predecessor/successor schema inventory is incomplete")
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
            str(customer_support_definition),
            str(pdf_document_review_definition_v1),
            str(pdf_document_review_definition_v1_1),
            str(pdf_document_review_definition_v1_2),
            str(pdf_document_review_definition_v1_3),
            str(pdf_document_review_definition_v1_4),
            str(pdf_document_review_definition_v1_5),
            str(inference_transfer_definition),
            str(inference_transfer_definition_v1_1),
            str(local_embedding_definition),
            str(local_embedding_definition_v2),
            str(reference_query_definition),
            str(private_chat_query_definition),
            str(worker_config),
            str(staging),
            str(workspace_root),
            str(codex_binary),
            os.environ["EXPECTED_COMMIT"],
            os.environ["EXPECTED_SOURCE_TREE"],
            os.environ["EXPECTED_SOURCE_ARCHIVE_SHA256"],
            json.dumps(catalog_resources, sort_keys=True, separators=(",", ":")),
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
  # Re-open and verify the exact install arguments after every admission gate.
  verify_captured_release_wheel_inspection_identity "${wheels[@]}"
  (
    umask 022
    ${API_PIP} install --no-deps --force-reinstall "${wheels[@]}" >/dev/null
  )
  verify_captured_release_wheel_inspection_identity "${wheels[@]}"
  ${API_PIP} check
  verify_install_mode exact-source
}

verify_worker_executable_release_identity() {
  local source_executable="${SOURCE_ROOT}/services/orchestrator/eom_orchestrator/worker_exec.py"
  local source_contract="${SOURCE_ROOT}/services/orchestrator/eom_orchestrator/worker_systemd.py"
  local installed_executable=/usr/local/libexec/eom-worker-exec
  local expected_sha source_sha
  [[ -f "${source_executable}" && ! -L "${source_executable}" && \
    -f "${source_contract}" && ! -L "${source_contract}" ]] || \
    fail 'release worker executable is unavailable'
  expected_sha="$(sed -nE 's/^WORKER_EXECUTABLE_SHA256 = "([0-9a-f]{64})"$/\1/p' "${source_contract}")"
  [[ "${expected_sha}" =~ ^[0-9a-f]{64}$ ]] || \
    fail 'release worker executable contract is invalid'
  source_sha="$(sha256sum "${source_executable}" | cut -d' ' -f1)"
  [[ "${source_sha}" == "${expected_sha}" ]] || \
    fail 'release worker executable source differs from its adapter contract'
  [[ -f "${installed_executable}" && ! -L "${installed_executable}" && \
    "$(stat -c '%U:%G:%a:%h' -- "${installed_executable}")" == 'root:root:755:1' ]] || \
    fail 'protected worker executable identity is invalid'
  cmp --silent "${source_executable}" "${installed_executable}" || \
    fail 'WORKER_RUNTIME_DEPLOYMENT_REQUIRED: install the matching reviewed worker executable before replacing Platform wheels'
  printf 'worker_runtime_release_identity=PASS\n'
}

verify_install_mode() {
  local source_identity_mode="${1:-}"
  [[ "${source_identity_mode}" == "exact-source" || \
    "${source_identity_mode}" == "validated-resource-only" ]] || \
    fail "installed release source identity verification mode is invalid"
  REPOSITORY_ROOT="${REPOSITORY_ROOT}" \
    SOURCE_IDENTITY_MODE="${source_identity_mode}" EXPECTED_COMMIT="${COMMIT}" \
    EXPECTED_SOURCE_TREE="${SOURCE_TREE}" \
    EXPECTED_SOURCE_ARCHIVE_SHA256="${SOURCE_ARCHIVE_SHA256}" \
    "${API_PYTHON}" -I - <<'PY'
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
from eom_api.build_info import get_build_info

for name, _ in catalog_schema_inventory():
    load_schema(name)
build_info = get_build_info()
if os.environ["SOURCE_IDENTITY_MODE"] == "exact-source" and (
    not os.environ["EXPECTED_SOURCE_TREE"]
    or not os.environ["EXPECTED_SOURCE_ARCHIVE_SHA256"]
    or build_info.source_commit != os.environ["EXPECTED_COMMIT"]
    or build_info.source_tree != os.environ["EXPECTED_SOURCE_TREE"]
    or build_info.source_archive_sha256 != os.environ["EXPECTED_SOURCE_ARCHIVE_SHA256"]
):
    raise SystemExit("installed API release source identity mismatch")
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

from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION

dist = Path(os.environ["DIST_DIR"])
wheels = {}
for path in sorted(dist.glob("*.whl")):
    wheels[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
payload = {
    "deployed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "source_commit": os.environ["COMMIT"],
    "migration_head": CURRENT_MIGRATION_REVISION,
    "workflow_runner_held_inactive": os.environ["WORKFLOW_RUNNER_HELD"] == "true",
    "package_version": os.environ["VERSION"],
    "wheels": wheels,
    "rollback": (
        "First verify schema-head and installed-release compatibility. Immutable validation "
        "history forbids blind schema downgrade; old wheels alone may fail exact-head readiness. "
        "Withdraw the new UI entrypoint using a compatible retained Web release while keeping "
        "the new platform/schema and history, or use a separately reviewed compatible release "
        "set. Restore only verified nonsecret configuration/unit predecessors, then verify."
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

require_no_active_transient_platform_consumers() {
  local pattern unit
  local -a active_units=()
  for pattern in "${SHARED_RUNTIME_TRANSIENT_PATTERNS[@]}"; do
    while IFS= read -r unit; do
      [[ -n "${unit}" ]] && active_units+=("${unit}")
    done < <(
      systemctl list-units \
        --type=service \
        --state=active \
        --no-legend \
        --plain \
        "${pattern}" | awk 'NF {print $1}'
    )
  done
  ((${#active_units[@]} == 0)) || \
    fail "active transient shared-runtime consumers must be quiesced and stopped before installation: ${active_units[*]}"
}

require_no_staged_workflow_runner_accelerator() {
  [[ ! -e "${WORKFLOW_RUNNER_ACCELERATOR_RUNTIME_UNIT}" && \
    ! -L "${WORKFLOW_RUNNER_ACCELERATOR_RUNTIME_UNIT}" ]] || \
    fail "staged Workflow runner accelerator must be removed before release"
}

require_workflow_runner_runtime_identity() {
  [[ -f "${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}" && \
    ! -L "${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}" ]] || \
    fail "workflow runner runtime identity is missing or unsafe"
  [[ "$(stat -c '%U:%G:%a' "${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}")" == \
    "root:root:644" ]] || fail "workflow runner runtime identity metadata mismatch"
  [[ "$(wc -l <"${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}")" == "1" ]] || \
    fail "workflow runner runtime identity must contain exactly one line"
  grep -Fxq "EOM_RUNTIME_SOURCE_COMMIT=${COMMIT}" \
    "${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}" || \
    fail "workflow runner runtime identity does not match the installed release"
}

install_workflow_runner_runtime_identity() {
  local expected staged
  expected="${BUILD_ROOT}/workflow-runtime.env"
  staged="${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}.staged.${COMMIT}"
  printf 'EOM_RUNTIME_SOURCE_COMMIT=%s\n' "${COMMIT}" >"${expected}"
  [[ ! -L "${staged}" ]] || fail "workflow runner staged runtime identity is unsafe"
  sudo -n install -o root -g root -m 0644 "${expected}" "${staged}"
  cmp --silent "${expected}" "${staged}" || \
    fail "workflow runner staged runtime identity content mismatch"
  sudo -n mv -T "${staged}" "${WORKFLOW_RUNNER_RUNTIME_ENV_TARGET}"
  require_workflow_runner_runtime_identity
}

install_service() {
  id eom-api >/dev/null 2>&1 || fail "eom-api system user is absent"
  sudo -n "${OFFICE_CONVERTER_INSTALLER}"
  sudo -n install -d -o eom-api -g eom-api -m 0700 \
    /var/lib/eom-api/pdf-review-uploads
  systemd-analyze verify \
    "${UNIT_SOURCE}" \
    "${WORKFLOW_MAINTENANCE_UNIT_SOURCE}" \
    "${WORKFLOW_RUNNER_UNIT_SOURCE}"
  install_workflow_runner_hold_release_boundary
  install_workflow_runner_runtime_identity
  sudo -n install -o root -g root -m 0755 \
    "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0755 \
    "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
  sudo -n install -o root -g root -m 0644 \
    "${WORKFLOW_RUNNER_UNIT_SOURCE}" "${WORKFLOW_RUNNER_UNIT_TARGET}"
  sudo -n install -o root -g root -m 0644 \
    "${WORKFLOW_MAINTENANCE_UNIT_SOURCE}" "${WORKFLOW_MAINTENANCE_UNIT_TARGET}"
  sudo -n "${METADATA_VERIFIER_TARGET}"
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable "${SERVICE}" >/dev/null
  sudo -n systemctl enable "${WORKFLOW_MAINTENANCE_SERVICE}" >/dev/null
  restart_platform_consumers
  verify_workflow_runner_deployment_hold
  wait_for_health
  printf 'runtime_isolation_verifier_invocation=START\n'
  run_release_operator API_ISOLATION_VERIFY "${COMMIT}"
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
  sudo -n "${OFFICE_CONVERTER_INSTALLER}" --verify
  # Standalone verification validates the embedded typed resource without
  # claiming that the checkout still denotes the installed release.
  verify_install_mode validated-resource-only
  cmp --silent "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}" || \
    fail "installed metadata verifier source drift"
  cmp --silent "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}" || \
    fail "installed runtime verifier source drift"
  cmp --silent "${WORKFLOW_RUNNER_UNIT_SOURCE}" "${WORKFLOW_RUNNER_UNIT_TARGET}" || \
    fail "installed workflow runner unit source drift"
  require_workflow_runner_runtime_identity
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
    verify_native_pdf_annotation_runtime
    activate_workflow_runner_deployment_hold
    prepare_workflow_runner_hold_release_boundary_before_admission
    verify_mock_exam_deployment_admission
    prepare_runtime_dependencies
    build_release
    # Close the build-window race before replacing any installed runtime package.
    verify_workflow_runner_deployment_hold
    verify_mock_exam_deployment_admission
    require_no_active_transient_platform_consumers
    require_no_staged_workflow_runner_accelerator
    verify_worker_executable_release_identity
    install_wheels
    reconcile_installed_catalog_runtime_privileges
    reconcile_installed_hwpx_manager_runtime_privileges
    install_service
    if [[ -n "${RECOVERY_EXECUTION_ID}" ]]; then
      # The mock-exam coordinator has no autonomous checkpoint writer. Recheck the exact
      # operator-authorized pointer after service replacement before declaring recovery ready.
      verify_mock_exam_deployment_admission
      printf 'mock_exam_recovery_deployment=READY execution_id=%s\n' \
        "${RECOVERY_EXECUTION_ID}"
    fi
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
    verify_native_pdf_annotation_runtime
    verify_service
    ;;
esac
