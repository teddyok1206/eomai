#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY=/home/eom/EOM
OWNER=eom-general-chat
OWNER_HOME=/var/lib/eom-general-chat

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail "chat owner preparation requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail "usage: provision_owner_identity.sh COMMIT"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "$1" ]] || fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain=v1)" ]] || fail "working tree is not clean"
[[ "$(systemctl show eom-general-chat.service --property=ActiveState --value)" == inactive ]] || \
  fail "owner service is not stopped"
for group in eom-api eom eom-cdx-chat; do
  getent group "${group}" >/dev/null || fail "required service group is absent"
done
[[ ! -L ${OWNER_HOME} ]] || fail "owner state must not be a symlink"
if getent passwd "${OWNER}" >/dev/null; then
  [[ "$(getent passwd "${OWNER}" | cut -d: -f6-7)" == "${OWNER_HOME}:/usr/sbin/nologin" ]] || \
    fail "existing owner identity differs"
  [[ "$(id -gn "${OWNER}")" == "${OWNER}" && "$(id -nG "${OWNER}")" == "${OWNER}" ]] || \
    fail "owner account groups differ; service-only groups must remain scoped"
  [[ "$(id -u "${OWNER}")" -gt 0 && "$(id -u "${OWNER}")" -lt 1000 ]] || fail "not a system identity"
elif [[ -e ${OWNER_HOME} ]]; then
  fail "owner state exists without its identity"
fi
if [[ -e ${OWNER_HOME} ]]; then
  [[ -d ${OWNER_HOME} && "$(stat -c '%U:%G:%a' "${OWNER_HOME}")" == "${OWNER}:eom-api:700" ]] || \
    fail "existing private owner state metadata differs"
fi
if ! getent group "${OWNER}" >/dev/null; then groupadd --system "${OWNER}"; fi
if ! getent passwd "${OWNER}" >/dev/null; then
  useradd --system --no-create-home --home-dir "${OWNER_HOME}" --shell /usr/sbin/nologin \
    --gid "${OWNER}" "${OWNER}"
fi
passwd --lock "${OWNER}" >/dev/null
install -d -o "${OWNER}" -g eom-api -m 0700 "${OWNER_HOME}"
printf 'general_chat_owner_identity=PREPARED\nservice_activation=NONE\nworker_groups=UNCHANGED\n'
