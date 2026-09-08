#!/usr/bin/env bash

# This file is a sourced library. Mutations stay in deploy_release.sh so this helper is also usable
# by unprivileged behavioral tests and read-only operational checks.

readonly WORKFLOW_RUNNER_HOLD_TARGET="/etc/systemd/system/eom-workflow-runner.service.d/zzzz-eom-deployment-hold.conf"
readonly WORKFLOW_RUNNER_HOLD_DIRECTORY="/etc/systemd/system/eom-workflow-runner.service.d"
readonly WORKFLOW_RUNNER_HOLD_SHA256="sha256:d63c1155611f0305d4bcc99da04be6ab89811b7ec1b0abff93e1af118df056e0"
readonly WORKFLOW_RUNNER_FRAGMENT="/etc/systemd/system/eom-workflow-runner.service"
readonly WORKFLOW_RUNNER_FRAGMENT_SHA256="sha256:1688c77a606ea647d498aacbb3f8f75265f459cf888e1495ae82a8d2887b2878"
readonly WORKFLOW_RUNNER_INEFFECTIVE_RUNTIME_MASK="/run/systemd/system/eom-workflow-runner.service"
readonly WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP="/etc/systemd/system/eom-workflow-runner.service.d/.zzzz-eom-deployment-hold.released"

# Read a bounded, exact service-manager snapshot. The systemctl path is injected so behavioral
# tests never replace or shadow the production binary.
workflow_runner_unit_snapshot() {
  (($# == 2)) || return 64
  local systemctl_path="$1"
  local unit_name="$2"
  local output line key value
  local -A properties=()

  [[ -x "${systemctl_path}" ]] || return 1
  if ! output="$(
    "${systemctl_path}" show "${unit_name}" --no-pager \
      --property=ActiveState \
      --property=SubState \
      --property=UnitFileState \
      --property=MainPID \
      --property=LoadState \
      --property=FragmentPath \
      --property=DropInPaths \
      --property=RefuseManualStart \
      --property=NeedDaemonReload \
      --property=Job \
      --property=InvocationID \
      --property=ActiveEnterTimestampMonotonic 2>/dev/null
  )"; then
    return 1
  fi
  ((${#output} <= 4096)) || return 1

  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" == *=* ]] || return 1
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      ActiveState|SubState|UnitFileState|LoadState)
        [[ "${value}" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
        ;;
      MainPID)
        [[ "${value}" =~ ^[0-9]+$ ]] || return 1
        ;;
      FragmentPath)
        [[ -z "${value}" || "${value}" == /* ]] || return 1
        [[ "${value}" != *$'\x1f'* ]] || return 1
        ;;
      DropInPaths)
        [[ "${value}" != *$'\x1f'* ]] || return 1
        ;;
      RefuseManualStart)
        [[ "${value}" == "yes" || "${value}" == "no" ]] || return 1
        ;;
      NeedDaemonReload)
        [[ "${value}" == "yes" || "${value}" == "no" ]] || return 1
        ;;
      Job)
        [[ -z "${value}" || "${value}" =~ ^[0-9]+$ ]] || return 1
        ;;
      InvocationID)
        [[ -z "${value}" || "${value}" =~ ^[0-9a-f]{32}$ ]] || return 1
        ;;
      ActiveEnterTimestampMonotonic)
        [[ "${value}" =~ ^[0-9]+$ ]] || return 1
        ;;
      *) return 1 ;;
    esac
    [[ -z "${properties[${key}]+present}" ]] || return 1
    properties["${key}"]="${value}"
  done <<<"${output}"

  ((${#properties[@]} == 12)) || return 1
  printf '%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\x1f%s\n' \
    "${properties[ActiveState]}" \
    "${properties[SubState]}" \
    "${properties[UnitFileState]}" \
    "${properties[MainPID]}" \
    "${properties[LoadState]}" \
    "${properties[FragmentPath]}" \
    "${properties[DropInPaths]}" \
    "${properties[RefuseManualStart]}" \
    "${properties[NeedDaemonReload]}" \
    "${properties[Job]}" \
    "${properties[InvocationID]}" \
    "${properties[ActiveEnterTimestampMonotonic]}"
}

workflow_runner_stopped_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ -n "${unit_file_state}" ]] || return 1
  # A stopped pre-activation unit may or may not already have the exact hold on an idempotent retry.
  [[ -n "${refuse}" ]] || return 1
  [[ -n "${reload}" ]] || return 1
  [[ -z "${job}" ]] || return 1
  [[ -z "${drop_ins}" || "${drop_ins}" == "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

workflow_runner_unheld_synchronized_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "enabled" || "${unit_file_state}" == "disabled" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ -z "${drop_ins}" ]] || return 1
  [[ "${refuse}" == "no" ]] || return 1
  [[ "${reload}" == "no" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

workflow_runner_require_stopped() {
  (($# == 2)) || return 64
  workflow_runner_stopped_activation_identity "$1" "$2" >/dev/null
}

workflow_runner_require_same_activation_identity() {
  (($# == 2)) || return 64
  [[ "$1" =~ ^([0-9a-f]{32})?:[0-9]+$ ]] || return 1
  [[ "$2" =~ ^([0-9a-f]{32})?:[0-9]+$ ]] || return 1
  [[ "$1" == "$2" ]]
}

workflow_runner_journal_cursor_at_or_before() {
  (($# == 4)) || return 64
  local journalctl_path="$1" scope="$2" retired_at="$3" retired_at_unix_us="$4"
  local output cursor observed_unix_us
  local cursor_pattern='^[A-Za-z0-9_=;:.,+/@-]{16,1024}$'
  local -a lines=()
  [[ -x "${journalctl_path}" ]] || return 1
  [[ "${scope}" == "--system" || "${scope}" == "--user" ]] || return 64
  [[ "${retired_at}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$ ]] || \
    return 64
  [[ "${retired_at_unix_us}" =~ ^[0-9]{1,18}$ ]] || return 64
  output="$(
    "${journalctl_path}" "${scope}" --quiet --no-pager \
      --until="${retired_at}" --lines=1 --show-cursor --output=json \
      --output-fields=__CURSOR 2>/dev/null
  )" || return 1
  ((${#output} <= 4096)) || return 1
  mapfile -t lines <<<"${output}"
  ((${#lines[@]} == 2)) || return 1
  [[ "${lines[1]}" == "-- cursor: "* ]] || return 1
  cursor="${lines[1]#-- cursor: }"
  [[ "${cursor}" =~ ${cursor_pattern} ]] || return 1
  [[ "${lines[0]}" == *"\"__CURSOR\":\"${cursor}\""* ]] || return 1
  [[ "${lines[0]}" =~ \"__REALTIME_TIMESTAMP\":\"([0-9]{1,18})\" ]] || return 1
  observed_unix_us="${BASH_REMATCH[1]}"
  ((10#${observed_unix_us} <= 10#${retired_at_unix_us})) || return 1
  printf '%s\n' "${cursor}"
}

workflow_runner_require_no_unit_journal_after_cursor() {
  (($# == 4)) || return 64
  local journalctl_path="$1" scope="$2" unit_name="$3" cursor="$4" output
  local cursor_pattern='^[A-Za-z0-9_=;:.,+/@-]{16,1024}$'
  [[ -x "${journalctl_path}" ]] || return 1
  [[ "${scope}" == "--system" || "${scope}" == "--user" ]] || return 64
  [[ "${unit_name}" =~ ^[A-Za-z0-9_.@-]+\.service$ ]] || return 64
  [[ "${cursor}" =~ ${cursor_pattern} ]] || return 64
  # journalctl may return success and no matched unit rows for a missing --after-cursor. Prove the
  # cursor itself is still retained immediately before and after the filtered query so journal
  # rotation or an access change can never be mistaken for an empty activity range.
  workflow_runner_require_journal_cursor_retained \
    "${journalctl_path}" "${scope}" "${cursor}" || return 1
  output="$(
    "${journalctl_path}" "${scope}" --quiet --no-pager \
      --after-cursor="${cursor}" --unit="${unit_name}" --lines=1 --output=json \
      --output-fields=__CURSOR,MESSAGE_ID,JOB_TYPE 2>/dev/null
  )" || return 1
  ((${#output} <= 4096)) || return 1
  [[ -z "${output}" ]] || return 1
  workflow_runner_require_journal_cursor_retained \
    "${journalctl_path}" "${scope}" "${cursor}"
}

workflow_runner_require_journal_cursor_retained() {
  (($# == 3)) || return 64
  local journalctl_path="$1" scope="$2" cursor="$3" output observed_cursor
  local cursor_pattern='^[A-Za-z0-9_=;:.,+/@-]{16,1024}$'
  local json_cursor_pattern='"__CURSOR":"([A-Za-z0-9_=;:.,+/@-]{16,1024})"'
  local -a lines=()
  [[ -x "${journalctl_path}" ]] || return 1
  [[ "${scope}" == "--system" || "${scope}" == "--user" ]] || return 64
  [[ "${cursor}" =~ ${cursor_pattern} ]] || return 64
  output="$(
    "${journalctl_path}" "${scope}" --quiet --no-pager \
      --cursor="${cursor}" --lines=1 --output=json --output-fields=__CURSOR 2>/dev/null
  )" || return 1
  ((${#output} <= 4096)) || return 1
  mapfile -t lines <<<"${output}"
  ((${#lines[@]} == 1)) || return 1
  [[ "${lines[0]}" =~ ${json_cursor_pattern} ]] || return 1
  observed_cursor="${BASH_REMATCH[1]}"
  [[ "${observed_cursor}" == "${cursor}" ]]
}

workflow_runner_require_release_identity_with_journal_fence() {
  (($# == 6)) || return 64
  [[ "$1" =~ ^([0-9a-f]{32})?:[0-9]+$ ]] || return 1
  [[ "$2" =~ ^([0-9a-f]{32})?:[0-9]+$ ]] || return 1
  workflow_runner_require_no_unit_journal_after_cursor "$3" "$4" "$5" "$6" || return 1
  [[ "$2" == "$1" || "$2" == ":0" ]]
}

workflow_runner_unit_disabled_on_disk() {
  (($# == 2)) || return 64
  local systemctl_path="$1" unit_name="$2" output status
  [[ -x "${systemctl_path}" ]] || return 1
  if output="$("${systemctl_path}" is-enabled "${unit_name}" 2>/dev/null)"; then
    return 1
  else
    status=$?
  fi
  [[ "${status}" == "1" && "${output}" == "disabled" ]]
}

workflow_runner_require_hold_directory() {
  (($# == 1 || $# == 4)) || return 64
  local metadata expected_uid="${2:-0}" expected_gid="${3:-0}" expected_mode="${4:-755}"
  [[ ! -L "$1" && -d "$1" ]] || return 1
  metadata="$(/usr/bin/stat --format='%u:%g:%a' -- "$1" 2>/dev/null)" || return 1
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:${expected_mode}" ]] || return 1
}

workflow_runner_require_hold_file() {
  (($# == 2 || $# == 5)) || return 64
  local path="$1"
  local expected_sha256="$2"
  local expected_uid="${3:-0}" expected_gid="${4:-0}" expected_mode="${5:-644}"
  local metadata actual_sha256
  [[ "${expected_sha256}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 64
  [[ ! -L "${path}" && -f "${path}" ]] || return 1
  metadata="$(/usr/bin/stat --format='%u:%g:%a:%h' -- "${path}" 2>/dev/null)" || return 1
  [[ "${metadata}" == "${expected_uid}:${expected_gid}:${expected_mode}:1" ]] || return 1
  actual_sha256="$(/usr/bin/sha256sum -- "${path}" 2>/dev/null)" || return 1
  actual_sha256="sha256:${actual_sha256%% *}"
  [[ "${actual_sha256}" == "${expected_sha256}" ]] || return 1
}

workflow_runner_require_source_hold_file() {
  (($# == 2)) || return 64
  local path="$1"
  local expected_sha256="$2"
  local actual_sha256 link_count
  [[ "${expected_sha256}" =~ ^sha256:[0-9a-f]{64}$ ]] || return 64
  [[ ! -L "${path}" && -f "${path}" ]] || return 1
  link_count="$(/usr/bin/stat --format='%h' -- "${path}" 2>/dev/null)" || return 1
  [[ "${link_count}" == "1" ]] || return 1
  actual_sha256="$(/usr/bin/sha256sum -- "${path}" 2>/dev/null)" || return 1
  actual_sha256="sha256:${actual_sha256%% *}"
  [[ "${actual_sha256}" == "${expected_sha256}" ]] || return 1
}

workflow_runner_require_base_unit_file() {
  (($# == 1)) || return 64
  local actual_sha256 metadata
  [[ ! -L "$1" && -f "$1" ]] || return 1
  metadata="$(/usr/bin/stat --format='%u:%g:%a:%h' -- "$1" 2>/dev/null)" || return 1
  [[ "${metadata}" == "0:0:644:1" ]] || return 1
  actual_sha256="$(/usr/bin/sha256sum -- "$1" 2>/dev/null)" || return 1
  actual_sha256="sha256:${actual_sha256%% *}"
  [[ "${actual_sha256}" == "${WORKFLOW_RUNNER_FRAGMENT_SHA256}" ]] || return 1
}

workflow_runner_file_sha256() {
  (($# == 1)) || return 64
  local digest link_count
  [[ ! -L "$1" && -f "$1" ]] || return 1
  link_count="$(/usr/bin/stat --format='%h' -- "$1" 2>/dev/null)" || return 1
  [[ "${link_count}" == "1" ]] || return 1
  digest="$(/usr/bin/sha256sum -- "$1" 2>/dev/null)" || return 1
  printf 'sha256:%s\n' "${digest%% *}"
}

workflow_runner_deployment_hold_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || return 1
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || return 1
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "enabled" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ "${drop_ins}" == "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || return 1
  [[ "${refuse}" == "yes" ]] || return 1
  [[ "${reload}" == "no" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

workflow_runner_require_deployment_hold() {
  (($# == 2)) || return 64
  workflow_runner_deployment_hold_activation_identity "$1" "$2" >/dev/null
}

# During release the unit is deliberately disabled before the persistent hold is removed. This
# intermediate state survives a reboot without scheduling the runner, while the still-loaded hold
# continues to reject manual and dependency activation in the current manager.
workflow_runner_release_fenced_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || return 1
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || return 1
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "disabled" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ "${drop_ins}" == "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || return 1
  [[ "${refuse}" == "yes" ]] || return 1
  [[ "${reload}" == "no" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

workflow_runner_release_transition_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || return 1
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || return 1
  workflow_runner_unit_disabled_on_disk "$1" "$2" || return 1
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "enabled" || "${unit_file_state}" == "disabled" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ "${drop_ins}" == "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || return 1
  [[ "${refuse}" == "yes" ]] || return 1
  # disable --no-reload changes enablement on disk without refreshing the manager. The loaded hold
  # and cached UnitFileState may therefore remain unchanged, but systemd must report the pending
  # on-disk change through NeedDaemonReload=yes before the hold is moved.
  [[ "${reload}" == "yes" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

# Resume the exact post-rename/pre-reload state. The file has moved to its reviewed backup name,
# while the live manager still enforces the cached hold and reports that a reload is required.
workflow_runner_cached_release_fenced_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  workflow_runner_require_hold_directory "${WORKFLOW_RUNNER_HOLD_DIRECTORY}" || return 1
  [[ ! -e "${WORKFLOW_RUNNER_HOLD_TARGET}" && ! -L "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || \
    return 1
  workflow_runner_require_hold_file \
    "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}" "${WORKFLOW_RUNNER_HOLD_SHA256}" || return 1
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "enabled" || "${unit_file_state}" == "disabled" ]] || return 1
  workflow_runner_unit_disabled_on_disk "$1" "$2" || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ "${drop_ins}" == "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || return 1
  [[ "${refuse}" == "yes" ]] || return 1
  [[ "${reload}" == "yes" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

# Return EXACT when the only known residue has the expected root-owned /dev/null identity, ABSENT
# when no directory entry exists, and non-zero for every foreign or tampered entry.
workflow_runner_ineffective_runtime_mask_state() {
  (($# == 0 || $# == 3)) || return 64
  local path="${1:-${WORKFLOW_RUNNER_INEFFECTIVE_RUNTIME_MASK}}"
  local expected_uid="${2:-0}" expected_gid="${3:-0}"
  local metadata target
  if [[ -L "${path}" ]]; then
    metadata="$(
      /usr/bin/stat --format='%u:%g:%a' -- "${path}" 2>/dev/null
    )" || return 1
    target="$(/usr/bin/readlink -- "${path}")" || return 1
    [[ "${metadata}" == "${expected_uid}:${expected_gid}:777" ]] || return 1
    [[ "${target}" == "/dev/null" ]] || return 1
    printf '%s\n' "EXACT"
    return 0
  fi
  [[ ! -e "${path}" ]] || return 1
  printf '%s\n' "ABSENT"
}

workflow_runner_require_no_ineffective_runtime_mask() {
  (($# == 0)) || return 64
  [[ "$(workflow_runner_ineffective_runtime_mask_state)" == "ABSENT" ]]
}

workflow_runner_released_activation_identity() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job invocation_id active_enter_timestamp
  [[ ! -e "${WORKFLOW_RUNNER_HOLD_TARGET}" && ! -L "${WORKFLOW_RUNNER_HOLD_TARGET}" ]] || \
    return 1
  workflow_runner_require_no_ineffective_runtime_mask || return 1
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\x1f' read -r \
    active_state sub_state unit_file_state main_pid load_state fragment drop_ins refuse reload job \
    invocation_id active_enter_timestamp \
    <<<"${snapshot}"
  [[ "${load_state}" == "loaded" ]] || return 1
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ "${unit_file_state}" == "disabled" ]] || return 1
  [[ "${fragment}" == "${WORKFLOW_RUNNER_FRAGMENT}" ]] || return 1
  [[ -z "${drop_ins}" ]] || return 1
  [[ "${refuse}" == "no" ]] || return 1
  [[ "${reload}" == "no" ]] || return 1
  [[ -z "${job}" ]] || return 1
  printf '%s:%s\n' "${invocation_id}" "${active_enter_timestamp}"
}

workflow_runner_require_released() {
  (($# == 2)) || return 64
  workflow_runner_released_activation_identity "$1" "$2" >/dev/null
}
