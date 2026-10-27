#!/usr/bin/env bash
# Presentation-only adapter. Build-only may source this file without reading any operator setting.

_release_operator_fail() {
  printf '%s\n' RELEASE_OPERATOR_BOUNDARY_REJECTED >&2
  return 1
}

run_release_operator() {
  [[ "$#" == 2 ]] || { _release_operator_fail; return 1; }
  local callback="$1" expected_commit="$2" member metadata launcher actual result
  local -a required=(
    EOM_RELEASE_OPERATOR_LAUNCHER EOM_RELEASE_OPERATOR_RUNTIME_PREFIX
    EOM_RELEASE_OPERATOR_RUNTIME_SHA256 EOM_RELEASE_OPERATOR_CONTEXT
    EOM_RELEASE_OPERATOR_CONTEXT_SHA256 EOM_RELEASE_OPERATOR_LAUNCHER_SHA256
    EOM_RELEASE_OPERATOR_HELPER_SHA256
  )
  case "$callback" in
    MIGRATION_VERIFY|MIGRATION_UPGRADE_0051|MIGRATION_VERIFY_0052|MIGRATION_UPGRADE_0052|MIGRATION_VERIFY_0053|MIGRATION_UPGRADE_0053|MIGRATION_VERIFY_0054|MIGRATION_UPGRADE_0054|MIGRATION_VERIFY_0055|MIGRATION_UPGRADE_0055|MIGRATION_VERIFY_0056|MIGRATION_UPGRADE_0056|MIGRATION_VERIFY_0057|MIGRATION_UPGRADE_0057|MIGRATION_VERIFY_0058|MIGRATION_UPGRADE_0058|MIGRATION_VERIFY_0059|MIGRATION_UPGRADE_0059|MIGRATION_VERIFY_0060|MIGRATION_UPGRADE_0060|API_ROLE_BOOTSTRAP|CATALOG_ROLE_RECONCILE|HWPX_ROLE_RECONCILE|PDF_RUNTIME_VERIFY|API_ISOLATION_VERIFY) ;;
    *) _release_operator_fail; return 1;;
  esac
  [[ "$expected_commit" =~ ^[0-9a-f]{40}$ ]] || { _release_operator_fail; return 1; }
  for member in "${required[@]}"; do
    [[ -n "${!member:-}" ]] || { _release_operator_fail; return 1; }
  done
  for member in EOM_RELEASE_OPERATOR_RUNTIME_SHA256 EOM_RELEASE_OPERATOR_CONTEXT_SHA256 \
    EOM_RELEASE_OPERATOR_LAUNCHER_SHA256 EOM_RELEASE_OPERATOR_HELPER_SHA256; do
    [[ "${!member}" =~ ^sha256:[0-9a-f]{64}$ ]] || { _release_operator_fail; return 1; }
  done
  launcher=$EOM_RELEASE_OPERATOR_LAUNCHER
  [[ "$launcher" == /* && ! "$launcher" =~ (^|/)\.{1,2}(/|$) && \
     ! "$launcher" =~ [[:cntrl:]] && -f "$launcher" && ! -L "$launcher" ]] || \
    { _release_operator_fail; return 1; }
  # The launcher must be checked BEFORE sudo starts Bash, not only after its own first instruction.
  member=$launcher
  while :; do
    [[ -e "$member" && ! -L "$member" ]] || { _release_operator_fail; return 1; }
    metadata=$(/usr/bin/stat -c '%u %a' -- "$member") || { _release_operator_fail; return 1; }
    [[ "${metadata%% *}" == 0 ]] && (( (8#${metadata##* } & 8#022) == 0 )) || \
      { _release_operator_fail; return 1; }
    [[ "$member" != / ]] || break
    member=$(/usr/bin/dirname -- "$member")
  done
  [[ "$(/usr/bin/stat -c %h -- "$launcher")" == 1 ]] || { _release_operator_fail; return 1; }
  actual=$(/usr/bin/sha256sum -- "$launcher") || { _release_operator_fail; return 1; }
  [[ "sha256:${actual:0:64}" == "$EOM_RELEASE_OPERATOR_LAUNCHER_SHA256" ]] || \
    { _release_operator_fail; return 1; }
  if /usr/bin/sudo -n /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin TZ=UTC LANG=C.UTF-8 \
    /usr/bin/bash "$launcher" EXECUTE "$EOM_RELEASE_OPERATOR_RUNTIME_PREFIX" \
    "$EOM_RELEASE_OPERATOR_RUNTIME_SHA256" "$EOM_RELEASE_OPERATOR_CONTEXT" \
    "$EOM_RELEASE_OPERATOR_CONTEXT_SHA256" "$EOM_RELEASE_OPERATOR_LAUNCHER_SHA256" \
    "$EOM_RELEASE_OPERATOR_HELPER_SHA256" "$callback" "$expected_commit"; then
    return 0
  else
    result=$?
    if [[ "$result" == 124 || "$result" == 137 ]]; then
      printf '%s\n' RELEASE_OPERATOR_TIMEOUT_STATE_UNKNOWN >&2
    fi
    return "$result"
  fi
}
