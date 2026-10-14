#!/usr/bin/env bash
# This reviewed launcher must itself be root-owned and independently hash-checked by its caller.
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin TZ=UTC LANG=C.UTF-8 LC_ALL=C
unset PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH BASH_ENV ENV
umask 077

fail() { printf '%s\n' RELEASE_OPERATOR_RUNTIME_REJECTED >&2; exit 1; }
[[ "$EUID" == 0 && $# == 9 ]] || fail
MODE=$1; PREFIX=$2; RUNTIME_SHA=$3; CONTEXT=$4; CONTEXT_SHA=$5
LAUNCHER_SHA=$6; HELPER_SHA=$7; CALLBACK=$8; EXPECTED_COMMIT=$9
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || fail
[[ "$MODE" == ADMIT || "$MODE" == EXECUTE ]] || fail
case "$CALLBACK" in
  MIGRATION_VERIFY|MIGRATION_UPGRADE_0051|MIGRATION_VERIFY_0052|MIGRATION_UPGRADE_0052|MIGRATION_VERIFY_0053|MIGRATION_UPGRADE_0053|MIGRATION_VERIFY_0054|MIGRATION_UPGRADE_0054|MIGRATION_VERIFY_0055|MIGRATION_UPGRADE_0055|API_ROLE_BOOTSTRAP|CATALOG_ROLE_RECONCILE|HWPX_ROLE_RECONCILE|PDF_RUNTIME_VERIFY|API_ISOLATION_VERIFY|ADMIT) ;;
  *) fail;;
esac
[[ "$MODE:$CALLBACK" == ADMIT:ADMIT || "$MODE" == EXECUTE && "$CALLBACK" != ADMIT ]] || fail
for value in "$RUNTIME_SHA" "$CONTEXT_SHA" "$LAUNCHER_SHA" "$HELPER_SHA"; do
  [[ "$value" =~ ^sha256:[0-9a-f]{64}$ ]] || fail
done
[[ "$PREFIX" == /* && "$PREFIX" != / ]] || fail
LAUNCHER=$(realpath -e -- "${BASH_SOURCE[0]}")
HELPER=$(dirname -- "$LAUNCHER")/release_operator_runtime.py

protected_path() {
  local path="$1" parent metadata
  [[ "$path" == /* && ! "$path" =~ (^|/)\.{1,2}(/|$) && ! "$path" =~ [[:cntrl:]] ]] || fail
  parent="$path"
  while :; do
    [[ ! -L "$parent" && -e "$parent" ]] || fail
    metadata=$(stat -c '%u %a' -- "$parent") || fail
    [[ "${metadata%% *}" == 0 ]] || fail
    (( (8#${metadata##* } & 8#022) == 0 )) || fail
    [[ "$parent" != / ]] || break
    parent=$(dirname -- "$parent")
  done
}
protected_path "$LAUNCHER"
protected_path "$HELPER"
protected_path "$CONTEXT"
[[ -f "$LAUNCHER" && -f "$HELPER" && -f "$CONTEXT" ]] || fail
[[ "$(stat -c %h -- "$LAUNCHER")" == 1 && "$(stat -c %h -- "$HELPER")" == 1 && "$(stat -c %h -- "$CONTEXT")" == 1 ]] || fail
[[ "sha256:$(sha256sum -- "$LAUNCHER" | cut -c 1-64)" == "$LAUNCHER_SHA" ]] || fail
[[ "sha256:$(sha256sum -- "$HELPER" | cut -c 1-64)" == "$HELPER_SHA" ]] || fail
[[ "sha256:$(sha256sum -- "$CONTEXT" | cut -c 1-64)" == "$CONTEXT_SHA" ]] || fail
protected_path "$PREFIX"
# Metadata scans are O(N), not repeated O(B) hashes. External links/special nodes are never executable.
# GNU find performs regular-member checks in one C traversal, not multiple stat forks per file.
invalid=$(find -P "$PREFIX" -regextype posix-extended \
  \( ! -uid 0 -o -regex '.*[[:cntrl:]].*' \
     -o \( ! -type l -a \
       \( ! \( -type d -o -type f \) -o -perm /6022 \
          -o \( -type f -a ! -links 1 \) \) \) \) -printf x -quit) || fail
[[ -z "$invalid" ]] || fail
while IFS= read -r -d '' member; do
  [[ "$(realpath -e -- "$member")" == "$PREFIX/"* ]] || fail
done < <(find -P "$PREFIX" -type l -print0)
[[ -x "$PREFIX/bin/python" && "$(realpath -e -- "$PREFIX/bin/python")" == "$PREFIX/"* ]] || fail
if [[ "$MODE" == ADMIT ]]; then
  digest=$( (
    cd -- "$PREFIX"
    while IFS= read -r -d '' member; do
      if [[ -L "$member" ]]; then printf 'L\0%s\0%s\0' "$member" "$(readlink -- "$member")"
      elif [[ -d "$member" ]]; then printf 'D\0%s\0' "$member"
      else raw=$(sha256sum -- "$member"); printf 'F\0%s\0%s\0' "$member" "${raw:0:64}"; fi
    done < <(find -P . -mindepth 1 -print0 | sort -z)
  ) | sha256sum | cut -c 1-64)
  [[ "sha256:$digest" == "$RUNTIME_SHA" ]] || fail
fi
exec /usr/bin/timeout --signal=TERM --kill-after=10s 180s \
  /usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin TZ=UTC LANG=C.UTF-8 \
  "$PREFIX/bin/python" -I -B "$HELPER" "$MODE" "$PREFIX" "$RUNTIME_SHA" \
  "$CONTEXT" "$CONTEXT_SHA" "$CALLBACK" "$EXPECTED_COMMIT"
