#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY=/home/eom/EOM
WORKER=eom-cdx-06
WORKER_HOME=/srv/eom/worker-homes/eom-cdx-06

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail "reserved chat identity check requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail "usage: provision_worker_identity.sh COMMIT"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "$1" ]] || fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || fail "working tree is not clean"

# Slot 06 is an existing identity, not a new account to create, enroll or modify.
getent passwd "${WORKER}" >/dev/null || fail "existing slot 06 identity is unavailable"
[[ "$(getent passwd "${WORKER}" | cut -d: -f6-7)" == "${WORKER_HOME}:/usr/sbin/nologin" ]] || \
  fail "slot 06 identity metadata differs"
[[ "$(id -gn "${WORKER}")" == "${WORKER}" ]] || fail "slot 06 primary group differs"
for group in $(id -nG "${WORKER}"); do
  case "${group}" in eom|sudo|docker|lxd|adm) fail "unsafe slot 06 supplementary group";; esac
done
for private in "${WORKER_HOME}" "${WORKER_HOME}/.codex"; do
  [[ ! -L ${private} && -d ${private} && \
     "$(stat -c '%U:%G:%a' "${private}")" == "${WORKER}:${WORKER}:700" ]] || \
    fail "slot 06 private home boundary differs"
done
printf 'general_chat_worker_identity=EXISTING_SLOT_06\nworker_credentials=UNCHANGED\n'
printf 'worker_layout=PREPARED_BY_INSTALL_RUNTIME\nservice_activation=NONE\n'
