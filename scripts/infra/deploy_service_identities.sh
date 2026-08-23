#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
ARTIFACT_GROUP=eom-artifact-committers
ARTIFACT_ROOT=/mnt/nas/eom/artifacts
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules
SERVICES=(
  eom-catalog-application-runner.service
  eom-hwpx-application-runner.service
  eom-workflow-runner.service
)
STOPPED=0

fail() {
  echo "ERROR: $1" >&2
  exit 1
}

ensure_identity() {
  local user=$1
  local home=$2
  local primary_group=$3
  local supplementary_groups=$4
  if ! getent passwd "${user}" >/dev/null; then
    useradd --system --no-create-home --home-dir "${home}" --shell /usr/sbin/nologin \
      --gid "${primary_group}" --groups "${supplementary_groups}" "${user}"
  else
    usermod --gid "${primary_group}" --groups "${supplementary_groups}" "${user}"
  fi
  passwd --lock "${user}" >/dev/null
  [[ "$(getent passwd "${user}" | cut -d: -f6-7)" == "${home}:/usr/sbin/nologin" ]] || \
    fail "${user} account metadata mismatch"
  local forbidden
  for forbidden in sudo docker lxd adm; do
    if id -nG "${user}" | tr ' ' '\n' | grep -Fxq "${forbidden}"; then
      fail "${user} has forbidden group ${forbidden}"
    fi
  done
}

require_process_identity() {
  local service=$1
  local expected_user=$2
  shift 2
  local pid uid group group_id
  pid=$(systemctl show --property=MainPID --value "${service}")
  [[ ${pid} =~ ^[1-9][0-9]*$ && -r /proc/${pid}/status ]] || \
    fail "${service} process unavailable"
  uid=$(id -u "${expected_user}")
  grep -Eq "^Uid:[[:space:]]+${uid}[[:space:]]+${uid}[[:space:]]+${uid}[[:space:]]+${uid}$" \
    "/proc/${pid}/status" || fail "${service} UID mismatch"
  for group in "$@"; do
    group_id=$(getent group "${group}" | cut -d: -f3)
    grep -Eq "^Groups:.*[[:space:]]${group_id}([[:space:]]|$)" "/proc/${pid}/status" || \
      fail "${service} group ${group} missing"
  done
  for group in sudo docker lxd adm; do
    group_id=$(getent group "${group}" | cut -d: -f3)
    if [[ -n ${group_id} ]] && \
       grep -Eq "^Groups:.*[[:space:]]${group_id}([[:space:]]|$)" "/proc/${pid}/status"; then
      fail "${service} inherited forbidden group ${group}"
    fi
  done
}

restart_on_failure() {
  local status=$?
  trap - ERR
  if [[ ${STOPPED} -eq 1 ]]; then
    systemctl start "${SERVICES[@]}" || true
  fi
  exit "${status}"
}
trap restart_on_failure ERR

[[ ${EUID} -eq 0 ]] || fail "service identity deployment requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || fail "usage: deploy_service_identities.sh COMMIT"
EXPECTED_COMMIT=$1
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || fail "working tree is not clean"
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}" || fail "${service} is not active"
  systemctl is-enabled --quiet "${service}" || fail "${service} is not enabled"
done
if systemctl list-units --no-legend --state=activating,active,deactivating \
  'eom-worker-*@*.service' 'eom-hwpx-kordoc@*.service' 'eom-hwpx-builder@*.service' | grep -q .; then
  fail "a fixed child unit is active"
fi
[[ -d ${ARTIFACT_ROOT} && ! -L ${ARTIFACT_ROOT} ]] || fail "Artifact root is unsafe"
[[ "$(stat -c '%U' "${ARTIFACT_ROOT}")" == eom ]] || fail "Artifact root owner mismatch"

getent group "${ARTIFACT_GROUP}" >/dev/null || groupadd --system "${ARTIFACT_GROUP}"
ensure_identity eom-workflow-runner /var/lib/eom-workflow-runner eom \
  "${ARTIFACT_GROUP},eom-cdx-01,eom-cdx-02,eom-cdx-03,eom-cdx-04,eom-cdx-05"
ensure_identity eom-catalog-manager /var/lib/eom-catalog-api eom-api \
  "eom,${ARTIFACT_GROUP}"
ensure_identity eom-hwpx-manager /var/lib/eom-hwpx-api eom-api \
  "eom,${ARTIFACT_GROUP},eom-hwpx"

chgrp "${ARTIFACT_GROUP}" "${ARTIFACT_ROOT}"
chmod 02770 "${ARTIFACT_ROOT}"
[[ "$(stat -c '%U:%G:%a' "${ARTIFACT_ROOT}")" == \
    "eom:${ARTIFACT_GROUP}:2770" ]] || fail "Artifact root contract mismatch"

install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
install -o root -g root -m 0644 \
  "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
  /etc/systemd/system/eom-workflow-runner.service
install -o root -g root -m 0644 \
  "${REPOSITORY}/infra/systemd/eom-hwpx-application-runner.service" \
  /etc/systemd/system/eom-hwpx-application-runner.service
/srv/eom/conda/envs/eom-api/bin/python \
  "${REPOSITORY}/scripts/catalog/install_application_runner.py" "${EXPECTED_COMMIT}"
systemd-analyze verify \
  "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
  "${REPOSITORY}/infra/systemd/eom-catalog-application-runner.service" \
  "${REPOSITORY}/infra/systemd/eom-hwpx-application-runner.service"

systemctl daemon-reload
systemctl stop "${SERVICES[@]}"
STOPPED=1
systemctl start "${SERVICES[@]}"
STOPPED=0
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}"
  systemctl is-enabled --quiet "${service}"
done

require_process_identity eom-workflow-runner.service eom-workflow-runner \
  eom "${ARTIFACT_GROUP}" eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05
require_process_identity eom-catalog-application-runner.service eom-catalog-manager \
  eom-api eom "${ARTIFACT_GROUP}"
require_process_identity eom-hwpx-application-runner.service eom-hwpx-manager \
  eom-api eom "${ARTIFACT_GROUP}" eom-hwpx

CATALOG_SOCKET=/run/eom-catalog-api/manager.sock
HWPX_SOCKET=/run/eom-hwpx-api/manager.sock
for attempt in $(seq 1 50); do
  [[ -S ${CATALOG_SOCKET} && -S ${HWPX_SOCKET} ]] && break
  sleep 0.1
done
[[ "$(stat -c '%U:%G:%a' "${CATALOG_SOCKET}")" == eom-catalog-manager:eom-api:660 ]] || \
  fail "Catalog socket owner mismatch"
[[ "$(stat -c '%U:%G:%a' "${HWPX_SOCKET}")" == eom-hwpx-manager:eom-api:660 ]] || \
  fail "HWPX socket owner mismatch"

WORKFLOW_PID=$(systemctl show --property=MainPID --value eom-workflow-runner.service)
HWPX_PID=$(systemctl show --property=MainPID --value eom-hwpx-application-runner.service)
pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${WORKFLOW_PID}" \
  --detail unit eom-worker-probe-01@probe_0123456789abcdef0123456789abcdef.service \
  --detail verb start --allow-user-interaction=no
pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${HWPX_PID}" \
  --detail unit eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service \
  --detail verb start --allow-user-interaction=no
if pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${WORKFLOW_PID}" \
  --detail unit eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service \
  --detail verb start --allow-user-interaction=no; then
  fail "workflow identity can start an HWPX unit"
fi
if pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${HWPX_PID}" \
  --detail unit eom-worker-01@job_0123456789abcdef0123456789abcdef.service \
  --detail verb start --allow-user-interaction=no; then
  fail "HWPX identity can start a workflow unit"
fi

echo "SERVICE_IDENTITIES=PASS"
echo "OPERATOR_GROUP_INHERITANCE=ABSENT"
echo "POLKIT_CROSS_START=DENIED"
