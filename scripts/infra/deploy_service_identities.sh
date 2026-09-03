#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
ARTIFACT_MOUNT=/mnt/nas
ARTIFACT_ROOT=/mnt/nas/eom/artifacts
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
LEASE_GUARD=${REPOSITORY}/scripts/workflow/check_no_active_worker_leases.py
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

require_mount_option() {
  local options=$1
  local required=$2
  tr ',' '\n' <<<"${options}" | grep -Fxq "${required}" || \
    fail "Artifact mount option ${required} is missing"
}

verify_artifact_mount() {
  local mount_source mount_type mount_options
  mount_source=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o SOURCE)
  mount_type=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o FSTYPE)
  mount_options=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o OPTIONS)
  [[ ${mount_source} == //172.30.1.30/AI_Linux && ${mount_type} == cifs ]] || \
    fail "Artifact mount identity mismatch"
  for required in forceuid forcegid nounix nosuid nodev noexec "uid=$(id -u eom)" \
    "gid=$(getent group eom | cut -d: -f3)" file_mode=0660 dir_mode=0770; do
    require_mount_option "${mount_options}" "${required}"
  done
  [[ "$(stat -c '%U:%G:%a' "${ARTIFACT_MOUNT}")" == eom:eom:770 ]] || \
    fail "Artifact mount metadata mismatch"
  [[ "$(stat -c '%U:%G:%a' "${ARTIFACT_ROOT}")" == eom:eom:770 ]] || \
    fail "Artifact root metadata mismatch"
}

ensure_identity() {
  local user=$1
  local home=$2
  local primary_group=$3
  local supplementary_groups=$4
  if ! getent passwd "${user}" >/dev/null; then
    if [[ -n ${supplementary_groups} ]]; then
      useradd --system --no-create-home --home-dir "${home}" --shell /usr/sbin/nologin \
        --gid "${primary_group}" --groups "${supplementary_groups}" "${user}"
    else
      useradd --system --no-create-home --home-dir "${home}" --shell /usr/sbin/nologin \
        --gid "${primary_group}" "${user}"
    fi
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
  local pid uid group group_id ready=0
  uid=$(id -u "${expected_user}")
  for _attempt in $(seq 1 50); do
    pid=$(systemctl show --property=MainPID --value "${service}")
    if [[ ${pid} =~ ^[1-9][0-9]*$ && -r /proc/${pid}/status ]] && \
       grep -Eq "^Uid:[[:space:]]+${uid}[[:space:]]+${uid}[[:space:]]+${uid}[[:space:]]+${uid}$" \
         "/proc/${pid}/status"; then
      ready=1
      break
    fi
    sleep 0.1
  done
  [[ ${ready} -eq 1 ]] || fail "${service} UID mismatch"
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
  'eom-worker-*@*.service' 'eom-worker-auth-*.service' \
  'eom-hwpx-kordoc@*.service' 'eom-hwpx-builder@*.service' \
  'eom-hwpx-content-team@*.service' | grep -q .; then
  fail "a fixed child unit is active"
fi
[[ -f ${LEASE_GUARD} && ! -L ${LEASE_GUARD} ]] || fail "worker lease guard is unsafe"
runuser -u eom-workflow-runner -g eom -- \
  env -i HOME=/var/lib/eom-workflow-runner USER=eom-workflow-runner \
    LOGNAME=eom-workflow-runner TZ=UTC PATH=/srv/eom/conda/envs/eom-api/bin:/usr/bin:/bin \
    EOM_POSTGRES_ENV=/etc/eom/secrets/postgres.env \
    "${PYTHON}" -I "${LEASE_GUARD}" || \
  fail "an active or reconciling worker lease blocks identity deployment"
[[ -d ${ARTIFACT_ROOT} && ! -L ${ARTIFACT_ROOT} ]] || fail "Artifact root is unsafe"
verify_artifact_mount
if ! getent group eom-codex-auth >/dev/null; then
  groupadd --system eom-codex-auth
fi
if ! getent group eom-cdx-06 >/dev/null; then
  groupadd --system eom-cdx-06
fi
ensure_identity eom-cdx-06 /srv/eom/worker-homes/eom-cdx-06 eom-cdx-06 ""
ensure_identity eom-workflow-runner /var/lib/eom-workflow-runner eom \
  "eom-cdx-01,eom-cdx-02,eom-cdx-03,eom-cdx-04,eom-cdx-05,eom-cdx-06,eom-codex-auth"
ensure_identity eom-codex-auth-broker /var/lib/eom-codex-auth-broker eom-codex-auth \
  "eom-codex-auth"
ensure_identity eom-catalog-manager /var/lib/eom-catalog-api eom-api \
  "eom"
ensure_identity eom-hwpx-manager /var/lib/eom-hwpx-api eom-api \
  "eom,eom-hwpx"

install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
install -o root -g root -m 0644 \
  "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
  /etc/systemd/system/eom-workflow-runner.service
install -o root -g root -m 0644 \
  "${REPOSITORY}/infra/systemd/eom-hwpx-application-runner.service" \
  /etc/systemd/system/eom-hwpx-application-runner.service
install -o root -g root -m 0644 \
  "${REPOSITORY}/infra/systemd/eom-hwpx-content-team@.service" \
  /etc/systemd/system/eom-hwpx-content-team@.service
/srv/eom/conda/envs/eom-api/bin/python \
  "${REPOSITORY}/scripts/catalog/install_application_runner.py" "${EXPECTED_COMMIT}"
systemd-analyze verify \
  "${REPOSITORY}/infra/systemd/eom-workflow-runner.service" \
  "${REPOSITORY}/infra/systemd/eom-catalog-application-runner.service" \
  "${REPOSITORY}/infra/systemd/eom-hwpx-application-runner.service" \
  "${REPOSITORY}/infra/systemd/eom-hwpx-content-team@.service"

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
  eom eom-cdx-01 eom-cdx-02 eom-cdx-03 eom-cdx-04 eom-cdx-05 eom-cdx-06 eom-codex-auth
require_process_identity eom-catalog-application-runner.service eom-catalog-manager \
  eom-api eom
require_process_identity eom-hwpx-application-runner.service eom-hwpx-manager \
  eom-api eom eom-hwpx

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
  --detail verb start
pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${HWPX_PID}" \
  --detail unit eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service \
  --detail verb start
pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${HWPX_PID}" \
  --detail unit eom-hwpx-content-team@hwpxbuild_0123456789abcdef0123456789abcdef.service \
  --detail verb start
if pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${WORKFLOW_PID}" \
  --detail unit eom-hwpx-builder@hwpxbuild_0123456789abcdef0123456789abcdef.service \
  --detail verb start; then
  fail "workflow identity can start an HWPX unit"
fi
if pkcheck --action-id org.freedesktop.systemd1.manage-units --process "${HWPX_PID}" \
  --detail unit eom-worker-01@job_0123456789abcdef0123456789abcdef.service \
  --detail verb start; then
  fail "HWPX identity can start a workflow unit"
fi

echo "SERVICE_IDENTITIES=PASS"
echo "OPERATOR_GROUP_INHERITANCE=ABSENT"
echo "POLKIT_CROSS_START=DENIED"
