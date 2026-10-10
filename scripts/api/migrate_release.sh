#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCHES=("main" "feat/application-api-v0" "feat/hwpx-application-api-v0")

usage() {
  printf '%s\n' "usage: $0 {--upgrade|--verify} EXPECTED_COMMIT"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$#" -eq 2 ]] || { usage >&2; exit 2; }
ACTION="$1"
EXPECTED_COMMIT="$2"
[[ "${ACTION}" == "--upgrade" || "${ACTION}" == "--verify" ]] || {
  usage >&2
  exit 2
}
[[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "expected commit is invalid"
# Git/config and sourced presentation code are developer-owned. Root uses the
# protected launcher directly; only its fixed callback may read owner credentials.
[[ "$EUID" -ne 0 ]] || fail "standalone migration preflight must run without root"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
# Read-only presentation preflight must not refresh/replace the developer Git index.
[[ -z "$(git --no-optional-locks -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
  fail "working tree must be clean"

branch_allowed=false
current_branch="$(git -C "${REPOSITORY_ROOT}" branch --show-current)"
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${current_branch}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"

source "${REPOSITORY_ROOT}/scripts/api/release_operator_boundary.sh"
if [[ "${ACTION}" == "--upgrade" ]]; then
  run_release_operator MIGRATION_UPGRADE_0051 "${EXPECTED_COMMIT}"
else
  run_release_operator MIGRATION_VERIFY "${EXPECTED_COMMIT}"
fi
