#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
SERVICE="eom-workflow-runner.service"
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/${SERVICE}"
UNIT_TARGET="/etc/systemd/system/${SERVICE}"
RUNNER="/srv/eom/conda/envs/eom-api/bin/eom-workflow-runner"
RELEASE_ROOT="/var/lib/eom-workflow-runner-deployments"
SERVICE_USER="eom-workflow-runner"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

require_file_metadata() {
  local path="$1"
  local expected="$2"
  [[ -f "${path}" && ! -L "${path}" && \
     "$(stat -c '%U:%G:%a' "${path}")" == "${expected}" ]] || \
    fail "metadata mismatch: ${path}"
}

require_directory_metadata() {
  local path="$1"
  local expected="$2"
  [[ -d "${path}" && ! -L "${path}" && \
     "$(stat -c '%U:%G:%a' "${path}")" == "${expected}" ]] || \
    fail "metadata mismatch: ${path}"
}

require_group_membership() {
  local user="$1"
  local group="$2"
  id -nG "${user}" | tr ' ' '\n' | grep -Fxq "${group}" || \
    fail "${user} is not a member of ${group}"
}

reject_group_membership() {
  local user="$1"
  local group="$2"
  if getent group "${group}" >/dev/null && \
     id -nG "${user}" | tr ' ' '\n' | grep -Fxq "${group}"; then
    fail "${user} has obsolete group ${group}"
  fi
}

require_property() {
  local property="$1"
  local expected="$2"
  [[ "$(systemctl show --property="${property}" --value "${SERVICE}")" == "${expected}" ]] || \
    fail "installed ${property} mismatch"
}

preflight() {
  local expected_commit="$1"
  [[ "$(id -u)" == "0" ]] || fail "workflow runner deployment requires root"
  [[ "${expected_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit is invalid"
  [[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
    fail "repository root mismatch"
  [[ "$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)" == "${expected_commit}" ]] || \
    fail "repository source commit mismatch"
  [[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
    fail "repository working tree is not clean"
  [[ -f "${UNIT_SOURCE}" && ! -L "${UNIT_SOURCE}" ]] || fail "unit source is unsafe"
  [[ -x "${RUNNER}" && -f "${RUNNER}" && ! -L "${RUNNER}" ]] || \
    fail "installed workflow runner is unavailable"
  require_file_metadata /etc/eom/secrets/postgres.env root:eom:640
  require_file_metadata /etc/eom/worker-slots.yaml root:eom:640
  require_file_metadata /etc/eom/human-actors.yaml root:eom:640
  require_file_metadata /etc/eom/workflow-runner.yaml root:eom:640
  require_file_metadata /etc/eom/codex-capabilities.yaml root:root:644
  require_directory_metadata /etc/eom/workflows root:eom:750
  require_directory_metadata /etc/eom/workflow-prompts root:eom:750
  getent passwd "${SERVICE_USER}" >/dev/null || fail "workflow runner identity is unavailable"
  require_group_membership "${SERVICE_USER}" eom
  reject_group_membership "${SERVICE_USER}" eom-artifact-committers
  for group in eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05; do
    require_group_membership "${SERVICE_USER}" "${group}"
  done
  systemd-analyze verify "${UNIT_SOURCE}"
}

verify_unit() {
  [[ -f "${UNIT_TARGET}" && ! -L "${UNIT_TARGET}" ]] || fail "installed unit is unsafe"
  require_file_metadata "${UNIT_TARGET}" root:root:644
  cmp --silent "${UNIT_SOURCE}" "${UNIT_TARGET}" || fail "installed unit content drift"
  require_property User "${SERVICE_USER}"
  require_property Group eom
  require_property UMask 0007
  require_property RestrictSUIDSGID no
  require_property NoNewPrivileges yes
  require_property ProtectSystem strict
  require_property ProtectHome yes
  require_property IPAddressDeny "0.0.0.0/0 ::/0"
  [[ "$(systemctl show --property=SupplementaryGroups --value "${SERVICE}")" == \
      "eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05" ]] || \
    fail "installed supplementary group contract mismatch"
  local runtime_environment
  runtime_environment="$(systemctl show --property=Environment --value "${SERVICE}")"
  [[ " ${runtime_environment} " == \
    *" EOM_STAGING_ROOT=/var/lib/eom-workflow-runner/orchestrator-staging "* ]] || \
    fail "installed orchestrator staging environment mismatch"
  require_directory_metadata \
    /var/lib/eom-workflow-runner/orchestrator-staging \
    eom-workflow-runner:eom:700
  systemctl is-enabled --quiet "${SERVICE}" || fail "workflow runner is not enabled"
  systemctl is-active --quiet "${SERVICE}" || fail "workflow runner is not active"
  local main_pid
  main_pid="$(systemctl show --property=MainPID --value "${SERVICE}")"
  [[ "${main_pid}" =~ ^[1-9][0-9]*$ && -r "/proc/${main_pid}/status" ]] || \
    fail "workflow runner process is unavailable"
  local group group_id
  for group in eom eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05; do
    group_id="$(getent group "${group}" | cut -d: -f3)"
    [[ "${group_id}" =~ ^[1-9][0-9]*$ ]] || fail "worker group identity is unavailable"
    grep -E "^Groups:.*[[:space:]]${group_id}([[:space:]]|$)" "/proc/${main_pid}/status" \
      >/dev/null || fail "workflow runner process group snapshot is incomplete"
  done
}

record_release() {
  local expected_commit="$1"
  local unit_sha temporary record
  unit_sha="$(sha256sum "${UNIT_TARGET}" | cut -d' ' -f1)"
  install -d -o root -g root -m 0700 "${RELEASE_ROOT}"
  temporary="$(mktemp "${RELEASE_ROOT}/.${expected_commit}.XXXXXX")"
  chmod 0600 "${temporary}"
  {
    printf 'source_commit=%s\n' "${expected_commit}"
    printf 'unit_sha256=%s\n' "${unit_sha}"
    printf 'deployed_at_utc=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  } >"${temporary}"
  record="${RELEASE_ROOT}/${expected_commit}.txt"
  mv -f "${temporary}" "${record}"
  require_file_metadata "${record}" root:root:600
}

main() {
  [[ "$#" == "2" ]] || fail "usage: deploy_runner_service.sh <install|verify> EXPECTED_COMMIT"
  local action="$1"
  local expected_commit="$2"
  [[ "${action}" == "install" || "${action}" == "verify" ]] || fail "unsupported action"
  preflight "${expected_commit}"
  if [[ "${action}" == "install" ]]; then
    if [[ -e "${UNIT_TARGET}" || -L "${UNIT_TARGET}" ]]; then
      require_file_metadata "${UNIT_TARGET}" root:root:644
    fi
    if systemctl is-active --quiet "${SERVICE}" 2>/dev/null && \
       { [[ ! -f "${UNIT_TARGET}" ]] || ! cmp --silent "${UNIT_SOURCE}" "${UNIT_TARGET}"; }; then
      fail "active workflow runner unit differs; refuse an implicit execution interruption"
    fi
    install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
    systemctl daemon-reload
    systemctl enable "${SERVICE}" >/dev/null
    systemctl start "${SERVICE}"
  fi
  verify_unit
  if [[ "${action}" == "install" ]]; then
    record_release "${expected_commit}"
  fi
  printf 'workflow_runner_service=%s\n' "${action^^}_PASS"
}

main "$@"
