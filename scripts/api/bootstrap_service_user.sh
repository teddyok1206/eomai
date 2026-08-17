#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="eom-api"
SERVICE_GROUP="eom-api"
STATE_DIRECTORY="/var/lib/eom-api"

if [[ "$(id -u)" -ne 0 ]]; then
  printf 'Run bootstrap_service_user.sh as root.\n' >&2
  exit 1
fi

if ! getent group "${SERVICE_GROUP}" >/dev/null; then
  groupadd --system "${SERVICE_GROUP}"
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${SERVICE_GROUP}" \
    --home-dir "${STATE_DIRECTORY}" \
    --create-home \
    --shell /usr/sbin/nologin \
    "${SERVICE_USER}"
fi

actual_group="$(id -gn "${SERVICE_USER}")"
actual_home="$(getent passwd "${SERVICE_USER}" | cut -d: -f6)"
actual_shell="$(getent passwd "${SERVICE_USER}" | cut -d: -f7)"
[[ "${actual_group}" == "${SERVICE_GROUP}" ]] || {
  printf 'Existing eom-api user has an unexpected primary group.\n' >&2
  exit 1
}
[[ "${actual_home}" == "${STATE_DIRECTORY}" ]] || {
  printf 'Existing eom-api user has an unexpected home.\n' >&2
  exit 1
}
[[ "${actual_shell}" == "/usr/sbin/nologin" ]] || {
  printf 'Existing eom-api user has an unexpected shell.\n' >&2
  exit 1
}

passwd --lock "${SERVICE_USER}" >/dev/null 2>&1 || true
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0700 "${STATE_DIRECTORY}"
if [[ ! -d /etc/eom ]]; then
  install -d -o root -g root -m 0751 /etc/eom
fi
if [[ ! -d /etc/eom/secrets ]]; then
  install -d -o root -g root -m 0711 /etc/eom/secrets
fi
chmod o+x /etc/eom /etc/eom/secrets

supplementary="$(id -nG "${SERVICE_USER}" | tr ' ' '\n' | grep -vFx "${SERVICE_GROUP}" || true)"
if [[ -n "${supplementary}" ]]; then
  printf 'eom-api must not have supplementary groups: %s\n' "${supplementary}" >&2
  exit 1
fi

printf 'eom-api system identity is ready.\n'
