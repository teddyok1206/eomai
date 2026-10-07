#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY=/home/eom/EOM
WORKER=eom-cdx-chat
WORKER_HOME=/srv/eom/worker-homes/eom-cdx-chat
WORKSPACE=/srv/eom/workspaces/general-chat
CONFIG_SOURCE=${REPOSITORY}/infra/chat/codex-config.toml

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail "dedicated chat identity provisioning requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || \
  fail "usage: provision_worker_identity.sh COMMIT"
EXPECTED_COMMIT=$1
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || \
  fail "working tree is not clean"

for parent in /srv/eom/worker-homes /srv/eom/workspaces; do
  [[ ! -L ${parent} && -d ${parent} && \
     "$(stat -c '%u:%g:%a' "${parent}")" == "0:0:711" ]] || \
    fail "dedicated chat parent boundary differs"
done
[[ ! -L ${CONFIG_SOURCE} && -f ${CONFIG_SOURCE} ]] || fail "pinned config is unavailable"

if getent passwd "${WORKER}" >/dev/null; then
  [[ "$(getent passwd "${WORKER}" | cut -d: -f6-7)" == \
      "${WORKER_HOME}:/usr/sbin/nologin" ]] || fail "chat account metadata mismatch"
  [[ "$(id -gn "${WORKER}")" == "${WORKER}" ]] || fail "chat primary group mismatch"
  [[ "$(id -nG "${WORKER}")" == "${WORKER}" ]] || fail "chat supplementary groups differ"
  [[ "$(id -u "${WORKER}")" -gt 0 && "$(id -u "${WORKER}")" -lt 1000 ]] || \
    fail "chat identity is not a dedicated system account"
elif [[ -e ${WORKER_HOME} ]]; then
  fail "chat home already exists without its dedicated identity"
fi
for target in "${WORKER_HOME}" "${WORKER_HOME}/.codex" "${WORKSPACE}" \
  "${WORKSPACE}/native"; do
  [[ ! -L ${target} ]] || fail "dedicated chat path must not be a symlink"
  [[ ! -e ${target} || -d ${target} ]] || fail "dedicated chat directory target differs"
done
for private in "${WORKER_HOME}" "${WORKER_HOME}/.codex"; do
  if [[ -e ${private} ]]; then
    [[ "$(stat -c '%U:%G:%a' "${private}")" == "${WORKER}:${WORKER}:700" ]] || \
      fail "existing chat home ownership differs"
  fi
done
for isolated in "${WORKSPACE}" "${WORKSPACE}/native"; do
  if [[ -e ${isolated} ]]; then
    [[ "$(stat -c '%U:%G:%a' "${isolated}")" == "root:${WORKER}:750" ]] || \
      fail "existing chat workspace ownership differs"
  fi
done
if [[ -e ${WORKER_HOME}/.codex/config.toml || -L ${WORKER_HOME}/.codex/config.toml ]]; then
  [[ ! -L ${WORKER_HOME}/.codex/config.toml && \
     -f ${WORKER_HOME}/.codex/config.toml ]] || fail "chat config target differs"
  cmp --silent "${CONFIG_SOURCE}" "${WORKER_HOME}/.codex/config.toml" || \
    fail "existing chat config differs; do not overwrite it"
fi

if ! getent group "${WORKER}" >/dev/null; then
  groupadd --system "${WORKER}"
fi
if ! getent passwd "${WORKER}" >/dev/null; then
  useradd --system --no-create-home --home-dir "${WORKER_HOME}" \
    --shell /usr/sbin/nologin --gid "${WORKER}" "${WORKER}"
fi
passwd --lock "${WORKER}" >/dev/null
[[ "$(id -nG "${WORKER}")" == "${WORKER}" ]] || fail "dedicated chat group boundary differs"

install -d -o "${WORKER}" -g "${WORKER}" -m 0700 "${WORKER_HOME}"
install -d -o "${WORKER}" -g "${WORKER}" -m 0700 "${WORKER_HOME}/.codex"
install -d -o root -g "${WORKER}" -m 0750 "${WORKSPACE}" "${WORKSPACE}/native"
if [[ ! -e ${WORKER_HOME}/.codex/config.toml ]]; then
  install -o root -g "${WORKER}" -m 0640 "${CONFIG_SOURCE}" \
    "${WORKER_HOME}/.codex/config.toml"
fi
[[ "$(stat -c '%U:%G:%a' "${WORKER_HOME}/.codex/config.toml")" == \
    "root:${WORKER}:640" ]] || fail "chat pinned config ownership differs"

printf 'general_chat_worker_identity=PROVISIONED\n'
printf 'worker_credentials=NOT_COPIED\n'
printf 'existing_six_slots=UNCHANGED\n'
printf 'db_migration=NONE\n'
printf 'service_activation=NONE\n'
