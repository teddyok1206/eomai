#!/usr/bin/env bash
set -euo pipefail

SECRET_DIRECTORY="/etc/eom/secrets"
SECRET_FILE="${SECRET_DIRECTORY}/api.env"
CONFIG_DIRECTORY="/etc/eom-api"
CONFIG_FILE="${CONFIG_DIRECTORY}/api.yaml"
UNIT_FILE="/etc/systemd/system/eom-api.service"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if [[ "$(id -u)" -ne 0 ]]; then
  fail "deployment metadata verification must run as root"
fi

check_metadata() {
  local path="$1" expected="$2" actual
  [[ ! -L "${path}" ]] || fail "protected path must not be a symlink: ${path}"
  actual="$(stat -Lc '%U:%G:%a' "${path}" 2>/dev/null)" || \
    fail "protected path is missing: ${path}"
  [[ "${actual}" == "${expected}" ]] || \
    fail "protected path metadata mismatch: ${path}"
}

check_metadata "${SECRET_DIRECTORY}" "root:eom:750"
check_metadata "${SECRET_FILE}" "root:eom-api:640"
[[ -f "${SECRET_FILE}" ]] || fail "API environment must be a regular file"
check_metadata "${CONFIG_DIRECTORY}" "root:eom-api:750"
check_metadata "${CONFIG_FILE}" "root:eom-api:640"
[[ -f "${CONFIG_FILE}" ]] || fail "API configuration must be a regular file"
check_metadata "${UNIT_FILE}" "root:root:644"
[[ -f "${UNIT_FILE}" ]] || fail "systemd unit must be a regular file"

declare -A required=(
  [EOM_API_DATABASE_URL]=0
  [EOM_API_TOKEN_HASH_KEY]=0
  [EOM_API_FINGERPRINT_KEY]=0
)
while IFS= read -r line || [[ -n "${line}" ]]; do
  [[ -z "${line}" || "${line}" == \#* ]] && continue
  [[ "${line}" =~ ^([A-Z0-9_]+)=(.+)$ ]] || fail "invalid API environment entry"
  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  [[ -v "required[${key}]" ]] || fail "unexpected API environment key"
  [[ "${required[${key}]}" -eq 0 ]] || fail "duplicate API environment key"
  [[ "${value,,}" != *placeholder* ]] || fail "placeholder API environment value"
  required["${key}"]=1
done < "${SECRET_FILE}"

for key in "${!required[@]}"; do
  [[ "${required[${key}]}" -eq 1 ]] || fail "required API environment key is missing"
done

grep -Fxq 'EnvironmentFile=/etc/eom/secrets/api.env' "${UNIT_FILE}" || \
  fail "systemd EnvironmentFile boundary mismatch"
grep -Fxq 'Environment=EOM_API_CONFIG=/etc/eom-api/api.yaml' "${UNIT_FILE}" || \
  fail "systemd configuration boundary mismatch"

if id -nG eom-api 2>/dev/null | tr ' ' '\n' | grep -Fxq eom; then
  fail "eom-api must not belong to the eom group"
fi

printf 'Application API deployment metadata verified.\n'
