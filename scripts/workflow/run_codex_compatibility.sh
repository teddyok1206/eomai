#!/usr/bin/env bash
# Operator-only service window; model work and durable replay belong to the installed use case.
set -euo pipefail

export PATH=/usr/bin:/bin
REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
RUNUSER=/usr/sbin/runuser
SYSTEMCTL=/usr/bin/systemctl
POSTGRES_ENV=/etc/eom/secrets/postgres.env
WORKER_CONFIG=/etc/eom/worker-slots.yaml
CAPABILITY_POLICY=/etc/eom/codex-capabilities.yaml
FENCED_UNITS=(
  eom-general-chat.service
  eom-general-chat-worker.service
  eom-workflow-maintenance.service
  eom-workflow-runner.service
  eom-codex-auth-broker.service
)
RESTORE_UNITS=(
  eom-codex-auth-broker.service
  eom-workflow-maintenance.service
  eom-workflow-runner.service
  eom-general-chat-worker.service
  eom-general-chat.service
)
declare -A PREVIOUSLY_ACTIVE=()
WINDOW_STARTED=0

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

installed_source_matches() {
  local installed_source
  installed_source=$("${PYTHON}" -I -c \
    'from eom_api.build_info import get_build_info; print(get_build_info().source_commit)') || return 1
  [[ ${installed_source} == "${EXPECTED_COMMIT}" ]]
}

restore_units() {
  local status=$? unit restore_failed=0
  trap - EXIT INT TERM
  if [[ ${WINDOW_STARTED} -eq 1 ]]; then
    # An interrupted owner can release its DB fence while the fixed native unit
    # still runs without an ordinary lease. Do not restore unaccounted producers.
    if ! installed_source_matches || ! run_installed restoration-preflight; then
      printf '%s\n' \
        'CODEX_COMPATIBILITY_RESTORATION_UNCONFIRMED: operator action required; producer restart withheld' \
        >&2
      exit 1
    fi
    for unit in "${RESTORE_UNITS[@]}"; do
      if [[ ${PREVIOUSLY_ACTIVE[${unit}]:-0} -eq 1 ]]; then
        "${SYSTEMCTL}" start "${unit}" || restore_failed=1
      fi
    done
    if [[ ${restore_failed} -ne 0 ]]; then
      printf '%s\n' 'ERROR: original producer state could not be fully restored' >&2
      status=1
    fi
  fi
  exit "${status}"
}

require_regular() {
  local path=$1 metadata=$2
  [[ -f "${path}" && ! -L "${path}" && \
    "$(stat -c '%U:%G:%a' -- "${path}")" == "${metadata}" ]] || \
    fail 'protected runtime configuration metadata differs'
}

run_installed() {
  # -g without -G discards existing supplementary groups, preventing access to
  # worker-private workspaces. Use the account's existing groups, not new grants.
  "${RUNUSER}" -u eom-workflow-runner -- \
    /usr/bin/env -i HOME=/var/lib/eom-workflow-runner \
    USER=eom-workflow-runner LOGNAME=eom-workflow-runner TZ=UTC LANG=C.UTF-8 \
    PATH=/srv/eom/conda/envs/eom-api/bin:/usr/bin:/bin \
    EOM_POSTGRES_ENV="${POSTGRES_ENV}" EOM_WORKER_CONFIG="${WORKER_CONFIG}" \
    EOM_CODEX_CAPABILITY_POLICY="${CAPABILITY_POLICY}" \
    EOM_STAGING_ROOT=/var/lib/eom-workflow-runner/orchestrator-staging \
    EOM_RUNTIME_SOURCE_COMMIT="${EXPECTED_COMMIT}" \
    "${PYTHON}" -I -m eomctl.cli control-plane codex-runtime "$1" \
    --request-file "${REQUEST_PATH}" --source-commit "${EXPECTED_COMMIT}"
}

[[ ${EUID} -eq 0 ]] || fail 'Codex compatibility maintenance requires root'
[[ ($# -eq 2 || $# -eq 3) && $1 =~ ^[0-9a-f]{40}$ && $2 == /* && \
  (${3:-global} == global || ${3:-global} == scoped) ]] || \
  fail 'usage: run_codex_compatibility.sh COMMIT ABSOLUTE_REQUEST_PATH [scoped]'
EXPECTED_COMMIT=$1
REQUEST_PATH=$2
SCOPE=${3:-global}
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail 'source commit differs'
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || \
  fail 'source working tree is not clean'
installed_source_matches || fail 'installed release differs from requested source'

require_regular "${POSTGRES_ENV}" root:eom:640
require_regular "${WORKER_CONFIG}" root:eom:640
require_regular "${CAPABILITY_POLICY}" root:root:644
[[ "$(/usr/bin/id -gn eom-workflow-runner)" == eom ]] || \
  fail 'runner primary group differs from the installed service identity'
[[ "$(readlink -e -- "${REQUEST_PATH}")" == "${REQUEST_PATH}" && \
  -f "${REQUEST_PATH}" && ! -L "${REQUEST_PATH}" && \
  "$(stat -c '%U:%G:%a:%h' -- "${REQUEST_PATH}")" == 'eom-workflow-runner:eom:600:1' ]] || \
  fail 'request must be a canonical runner-owned mode-0600 single-link regular file'

if [[ ${SCOPE} == scoped ]]; then
  # The application still takes the host lock and rechecks fixed-slot leases and
  # physical worker units before every probe. Unrelated GPU jobs keep running.
  run_installed scoped-preflight || fail 'fixed-slot work or invalid request prevents diagnostics'
  run_installed verify-scoped
  exit 0
fi

# A busy or expired request must fail before the first stop. This is observation,
# not inference authority; the use case takes/rechecks the host fence after stop.
run_installed maintenance-preflight || fail 'existing work or invalid request prevents maintenance'

for unit in "${FENCED_UNITS[@]}"; do
  state=$("${SYSTEMCTL}" show --no-pager --value --property=ActiveState "${unit}")
  case ${state} in
    active) PREVIOUSLY_ACTIVE[${unit}]=1 ;;
    inactive) PREVIOUSLY_ACTIVE[${unit}]=0 ;;
    *) fail 'a producer is transitioning or failed; maintenance did not stop services' ;;
  esac
done
# Starting the owner also starts its Wants= worker. Reject inconsistent input state
# rather than inadvertently activating an originally inactive worker during restoration.
if [[ ${PREVIOUSLY_ACTIVE[eom-general-chat.service]} -eq 1 && \
  ${PREVIOUSLY_ACTIVE[eom-general-chat-worker.service]} -eq 0 ]]; then
  fail 'chat owner/worker state cannot be restored without changing inactive services'
fi

trap restore_units EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
WINDOW_STARTED=1
for unit in "${FENCED_UNITS[@]}"; do
  "${SYSTEMCTL}" stop "${unit}"
done
run_installed verify
