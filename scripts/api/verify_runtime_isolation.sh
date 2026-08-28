#!/usr/bin/env bash
set -euo pipefail

SERVICE="eom-api.service"
SERVICE_CONTEXT_VERIFIER="/srv/eom/conda/envs/eom-api/bin/eom-api-runtime-isolation"
EXPECTED_SUPPLEMENTARY_GROUPS="eom-codex-auth"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

if [[ "$(id -u)" -ne 0 ]]; then
  fail "runtime isolation verification must run as root"
fi

systemctl is-active --quiet "${SERVICE}" || fail "service is not active"
systemctl is-enabled --quiet "${SERVICE}" || fail "service is not enabled"
[[ -x "${SERVICE_CONTEXT_VERIFIER}" ]] || fail "installed service-context verifier is unavailable"

main_pid="$(systemctl show --property=MainPID --value "${SERVICE}")"
[[ "${main_pid}" =~ ^[1-9][0-9]*$ && "${main_pid}" -gt 1 ]] || \
  fail "service has no valid main process"

mapfile -t listeners < <(ss -H -lnt 'sport = :8765')
[[ "${#listeners[@]}" -eq 1 ]] || fail "listener count mismatch"
[[ "${listeners[0]}" == *"127.0.0.1:8765"* ]] || fail "listener is not IPv4 loopback-only"

[[ "$(systemctl show --property=User --value "${SERVICE}")" == "eom-api" ]] || \
  fail "service user mismatch"
[[ "$(systemctl show --property=Group --value "${SERVICE}")" == "eom-api" ]] || \
  fail "service group mismatch"
[[ "$(systemctl show --property=SupplementaryGroups --value "${SERVICE}")" == \
  "${EXPECTED_SUPPLEMENTARY_GROUPS}" ]] || \
  fail "service supplementary groups mismatch"
[[ "$(systemctl show --property=WorkingDirectory --value "${SERVICE}")" == \
  "/var/lib/eom-api" ]] || fail "service working directory mismatch"
[[ "$(systemctl show --property=NoNewPrivileges --value "${SERVICE}")" == "yes" ]] || \
  fail "NoNewPrivileges is not enabled"
[[ -z "$(systemctl show --property=CapabilityBoundingSet --value "${SERVICE}")" ]] || \
  fail "capability bounding set is not empty"
[[ "$(systemctl show --property=PrivateTmp --value "${SERVICE}")" == "yes" ]] || \
  fail "PrivateTmp is not enabled"
[[ "$(systemctl show --property=PrivateUsers --value "${SERVICE}")" == "no" ]] || \
  fail "unexpected private user namespace"
[[ "$(systemctl show --property=ProtectSystem --value "${SERVICE}")" == "strict" ]] || \
  fail "ProtectSystem mismatch"
[[ "$(systemctl show --property=ProtectHome --value "${SERVICE}")" == "yes" ]] || \
  fail "ProtectHome mismatch"

unit_paths="$(systemctl show --property=InaccessiblePaths --value "${SERVICE}")"
for path in \
  /home/eom/EOM \
  /home/eom/EOMIS \
  /root/.codex \
  /srv/eom/worker-homes \
  /mnt/nas \
  /var/run/docker.sock \
  /etc/eom/secrets/postgres.env \
  /etc/eom/secrets/dev-slack.env \
  /etc/eom/secrets/observe.env; do
  [[ " ${unit_paths} " == *" ${path} "* ]] || {
    printf 'Unit sandbox omits required inaccessible path: %s\n' "${path}" >&2
    exit 1
  }
done

read_only_paths="$(systemctl show --property=ReadOnlyPaths --value "${SERVICE}")"
for path in /etc/eom-api/api.yaml /etc/eom/secrets/api.env; do
  [[ " ${read_only_paths} " == *" ${path} "* ]] || \
    fail "unit sandbox omits a required read-only path"
done
read_write_paths="$(systemctl show --property=ReadWritePaths --value "${SERVICE}")"
[[ " ${read_write_paths} " == *" /var/lib/eom-api "* ]] || \
  fail "unit sandbox omits the service state path"

"${SERVICE_CONTEXT_VERIFIER}"

printf 'Application API runtime isolation verified.\n'
