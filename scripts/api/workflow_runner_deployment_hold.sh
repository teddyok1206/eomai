#!/usr/bin/env bash

# Read a bounded, exact service-manager snapshot. This library performs no mutation and deliberately
# accepts the systemctl path as an argument so behavioral tests never replace a production binary.
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
      --property=MainPID 2>/dev/null
  )"; then
    return 1
  fi
  ((${#output} <= 4096)) || return 1

  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" == *=* ]] || return 1
    key="${line%%=*}"
    value="${line#*=}"
    case "${key}" in
      ActiveState|SubState|UnitFileState)
        [[ "${value}" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
        ;;
      MainPID)
        [[ "${value}" =~ ^[0-9]+$ ]] || return 1
        ;;
      *) return 1 ;;
    esac
    [[ -z "${properties[${key}]+present}" ]] || return 1
    properties["${key}"]="${value}"
  done <<<"${output}"

  ((${#properties[@]} == 4)) || return 1
  printf '%s\t%s\t%s\t%s\n' \
    "${properties[ActiveState]}" \
    "${properties[SubState]}" \
    "${properties[UnitFileState]}" \
    "${properties[MainPID]}"
}

workflow_runner_require_stopped() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\t' read -r active_state sub_state unit_file_state main_pid <<<"${snapshot}"
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
  [[ -n "${unit_file_state}" ]] || return 1
}

workflow_runner_require_runtime_hold() {
  (($# == 2)) || return 64
  local snapshot active_state sub_state unit_file_state main_pid
  snapshot="$(workflow_runner_unit_snapshot "$1" "$2")" || return 1
  IFS=$'\t' read -r active_state sub_state unit_file_state main_pid <<<"${snapshot}"
  [[ "${active_state}" == "inactive" ]] || return 1
  [[ "${sub_state}" == "dead" ]] || return 1
  [[ "${unit_file_state}" == "masked-runtime" ]] || return 1
  [[ "${main_pid}" == "0" ]] || return 1
}
