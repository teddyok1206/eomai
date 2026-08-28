#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
WORKER=eom-cdx-06
WORKER_HOME=/srv/eom/worker-homes/eom-cdx-06
RUNNER=eom-workflow-runner

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

has_group() {
  local user=$1 group=$2
  id -nG "${user}" | tr ' ' '\n' | grep -Fxq "${group}"
}

[[ ${EUID} -eq 0 ]] || fail "slot 06 identity provisioning requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || \
  fail "usage: provision_worker_slot06.sh COMMIT"
EXPECTED_COMMIT=$1
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || \
  fail "working tree is not clean"
getent passwd "${RUNNER}" >/dev/null || fail "workflow runner identity is unavailable"

if ! getent group "${WORKER}" >/dev/null; then
  groupadd --system "${WORKER}"
fi
if ! getent passwd "${WORKER}" >/dev/null; then
  useradd --system --no-create-home --home-dir "${WORKER_HOME}" \
    --shell /usr/sbin/nologin --gid "${WORKER}" "${WORKER}"
fi
passwd --lock "${WORKER}" >/dev/null
[[ "$(getent passwd "${WORKER}" | cut -d: -f6-7)" == \
    "${WORKER_HOME}:/usr/sbin/nologin" ]] || fail "slot 06 account metadata mismatch"
[[ "$(id -gn "${WORKER}")" == "${WORKER}" ]] || fail "slot 06 primary group mismatch"

for forbidden in eom sudo docker lxd adm; do
  if has_group "${WORKER}" "${forbidden}"; then
    fail "slot 06 has forbidden group ${forbidden}"
  fi
done
if ! has_group "${RUNNER}" "${WORKER}"; then
  usermod --append --groups "${WORKER}" "${RUNNER}"
fi
has_group "${RUNNER}" "${WORKER}" || fail "workflow runner lacks slot 06 handoff group"

printf 'slot06_identity=PROVISIONED\n'
printf 'service_restart=NONE\n'
