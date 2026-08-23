#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run as root" >&2
  exit 1
fi

REPOSITORY=/home/eom/EOM
SOURCE_CADDYFILE=${REPOSITORY}/config/caddy/Caddyfile
SOURCE_DROP_IN=${REPOSITORY}/config/systemd/caddy.service.d/eom-security.conf
TARGET_CADDYFILE=/etc/caddy/Caddyfile
TARGET_DROP_IN=/etc/systemd/system/caddy.service.d/eom-security.conf
BACKUP_ROOT=/var/lib/eom-deploy/caddy
BACKUP_DIRECTORY=
DROP_IN_WAS_PRESENT=0
MUTATION_STARTED=0

rollback() {
  local status=$?
  trap - ERR
  if [[ ${MUTATION_STARTED} -eq 1 ]]; then
    install -o root -g root -m 0644 "${BACKUP_DIRECTORY}/Caddyfile" "${TARGET_CADDYFILE}"
    if [[ ${DROP_IN_WAS_PRESENT} -eq 1 ]]; then
      install -D -o root -g root -m 0644 \
        "${BACKUP_DIRECTORY}/eom-security.conf" "${TARGET_DROP_IN}"
    else
      rm -f -- "${TARGET_DROP_IN}"
    fi
    systemctl daemon-reload
    systemctl restart caddy.service
  fi
  echo "CADDY_PUBLIC_HANDOVER=ROLLED_BACK" >&2
  exit "${status}"
}
trap rollback ERR

test "$(git -C "${REPOSITORY}" branch --show-current)" = main
test -z "$(git -C "${REPOSITORY}" status --porcelain)"
test -f "${SOURCE_CADDYFILE}"
test -f "${SOURCE_DROP_IN}"
test -f "${TARGET_CADDYFILE}"
test "$(stat -c '%U:%G:%a' "${TARGET_CADDYFILE}")" = root:root:644
test "$(systemctl is-active caddy.service)" = active
test "$(systemctl is-enabled caddy.service)" = enabled
test "$(systemctl is-active eom-web-gui.service)" = active
/usr/bin/caddy validate --config "${SOURCE_CADDYFILE}" --adapter caddyfile

install -d -o root -g root -m 0700 "${BACKUP_ROOT}"
BACKUP_DIRECTORY=$(mktemp -d --tmpdir="${BACKUP_ROOT}" public-handover.XXXXXXXX)
install -o root -g root -m 0600 "${TARGET_CADDYFILE}" "${BACKUP_DIRECTORY}/Caddyfile"
if [[ -f ${TARGET_DROP_IN} ]]; then
  DROP_IN_WAS_PRESENT=1
  install -o root -g root -m 0600 "${TARGET_DROP_IN}" \
    "${BACKUP_DIRECTORY}/eom-security.conf"
fi

MUTATION_STARTED=1
install -o root -g root -m 0644 "${SOURCE_CADDYFILE}" "${TARGET_CADDYFILE}"
install -D -o root -g root -m 0644 "${SOURCE_DROP_IN}" "${TARGET_DROP_IN}"
systemctl daemon-reload
systemctl restart caddy.service

test "$(systemctl is-active caddy.service)" = active
test "$(systemctl is-enabled caddy.service)" = enabled
test "$(stat -c '%U:%G:%a' /run/caddy-admin)" = caddy:caddy:700
test -S /run/caddy-admin/admin.sock
test "$(stat -c '%U:%G:%a' /run/caddy-admin/admin.sock)" = caddy:caddy:700
if /usr/bin/curl --silent --show-error --fail --max-time 2 http://127.0.0.1:2019/config/ \
  >/dev/null 2>&1; then
  echo "Caddy TCP admin endpoint is still reachable" >&2
  false
fi
/usr/bin/curl --silent --show-error --fail --max-time 5 \
  --unix-socket /run/caddy-admin/admin.sock http://localhost/config/ >/dev/null
if runuser -u eom-cdx-01 -g eom-cdx-01 -- \
  /usr/bin/curl --silent --show-error --fail --max-time 2 \
    --unix-socket /run/caddy-admin/admin.sock http://localhost/config/ >/dev/null 2>&1; then
  echo "worker identity can reach the Caddy admin socket" >&2
  false
fi

# This proves the persisted ExecReload command uses the protected socket too.
systemctl reload caddy.service
test "$(systemctl is-active caddy.service)" = active

HEADERS=$(mktemp)
trap 'rm -f -- "${HEADERS}"' EXIT
/usr/bin/curl --silent --show-error --fail --max-time 10 \
  --resolve eomai.duckdns.org:443:127.0.0.1 \
  --dump-header "${HEADERS}" --output /dev/null \
  https://eomai.duckdns.org/studio/login
grep -Eiq '^strict-transport-security: max-age=31536000\r?$' "${HEADERS}"
test "$(systemctl is-active eom-web-gui.service)" = active

MUTATION_STARTED=0
trap - ERR
echo "CADDY_PUBLIC_HANDOVER=PASS"
echo "CADDY_ADMIN=PROTECTED_UNIX_SOCKET"
echo "CADDY_BACKUP=${BACKUP_DIRECTORY}"
