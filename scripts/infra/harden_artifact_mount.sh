#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
FSTAB=/etc/fstab
MOUNT_POINT=/mnt/nas
ARTIFACT_ROOT=/mnt/nas/eom/artifacts
EXPECTED_SOURCE=//172.30.1.30/AI_Linux
RELEASE_ROOT=/var/lib/eom-deploy/artifact-mount
SERVICES=(
  eom-catalog-application-runner.service
  eom-hwpx-application-runner.service
  eom-workflow-runner.service
)
STOPPED=0
BACKUP=
UPDATED=

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

verify_mount() {
  local source filesystem options
  source=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o SOURCE)
  filesystem=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o FSTYPE)
  options=$(findmnt -T "${ARTIFACT_ROOT}" -n -t cifs -o OPTIONS)
  [[ ${source} == "${EXPECTED_SOURCE}" && ${filesystem} == cifs ]] || \
    fail "Artifact mount identity mismatch"
  for required in forceuid forcegid nounix nosuid nodev noexec \
    "uid=$(id -u eom)" "gid=$(getent group eom | cut -d: -f3)" \
    file_mode=0640 dir_mode=0750; do
    require_mount_option "${options}" "${required}"
  done
  [[ "$(stat -c '%U:%G:%a' "${MOUNT_POINT}")" == eom:eom:750 ]] || \
    fail "Artifact mount metadata mismatch"
  [[ "$(stat -c '%U:%G:%a' "${ARTIFACT_ROOT}")" == eom:eom:750 ]] || \
    fail "Artifact root metadata mismatch"
}

recover() {
  local status=$?
  trap - EXIT
  if [[ ${status} -ne 0 ]]; then
    if [[ -n ${BACKUP} && -f ${BACKUP} ]]; then
      local restore
      restore=$(mktemp /etc/.eom-fstab-restore.XXXXXX) || true
      if [[ -n ${restore:-} ]]; then
        install -o root -g root -m 0644 "${BACKUP}" "${restore}" || true
        mv -fT "${restore}" "${FSTAB}" || true
      fi
      systemctl daemon-reload || true
      mount -o remount "${MOUNT_POINT}" || true
    fi
    if [[ ${STOPPED} -eq 1 ]]; then
      systemctl start "${SERVICES[@]}" || true
    fi
  fi
  [[ -z ${UPDATED} || ! -e ${UPDATED} ]] || rm -f -- "${UPDATED}"
  exit "${status}"
}
trap recover EXIT

[[ ${EUID} -eq 0 ]] || fail "Artifact mount hardening requires root"
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || \
  fail "usage: harden_artifact_mount.sh COMMIT"
EXPECTED_COMMIT=$1
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${EXPECTED_COMMIT}" ]] || \
  fail "source commit mismatch"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "working tree is not clean"
[[ -f ${FSTAB} && ! -L ${FSTAB} && "$(stat -c '%U:%G:%a' "${FSTAB}")" == root:root:644 ]] || \
  fail "fstab metadata is unsafe"
[[ -d ${ARTIFACT_ROOT} && ! -L ${ARTIFACT_ROOT} ]] || fail "Artifact root is unsafe"
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}" || fail "${service} is not active"
  systemctl is-enabled --quiet "${service}" || fail "${service} is not enabled"
done
if systemctl list-units --no-legend --state=activating,active,deactivating \
  'eom-worker-*@*.service' 'eom-hwpx-kordoc@*.service' 'eom-hwpx-builder@*.service' | grep -q .; then
  fail "a fixed child unit is active"
fi

install -d -o root -g root -m 0700 "${RELEASE_ROOT}"
BACKUP_DIR=$(mktemp -d "${RELEASE_ROOT}/${EXPECTED_COMMIT}.XXXXXX")
chmod 0700 "${BACKUP_DIR}"
BACKUP=${BACKUP_DIR}/fstab.before
install -o root -g root -m 0600 "${FSTAB}" "${BACKUP}"
UPDATED=$(mktemp /etc/.eom-fstab.XXXXXX)
chmod 0600 "${UPDATED}"
/srv/eom/conda/envs/eom-api/bin/python -I \
  "${REPOSITORY}/scripts/infra/artifact_mount_contract.py" \
  "${FSTAB}" "${UPDATED}" "${EXPECTED_SOURCE}" "${MOUNT_POINT}" \
  "$(id -u eom)" "$(getent group eom | cut -d: -f3)"
chown root:root "${UPDATED}"
chmod 0644 "${UPDATED}"
findmnt --verify --tab-file "${UPDATED}" >/dev/null

systemctl stop "${SERVICES[@]}"
STOPPED=1
mv -fT "${UPDATED}" "${FSTAB}"
UPDATED=
systemctl daemon-reload
mount -o remount "${MOUNT_POINT}"
verify_mount
systemctl start "${SERVICES[@]}"
STOPPED=0
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}"
  systemctl is-enabled --quiet "${service}"
done

printf 'source_commit=%s\n' "${EXPECTED_COMMIT}" >"${BACKUP_DIR}/deployment.txt"
printf 'deployed_at_utc=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" >>"${BACKUP_DIR}/deployment.txt"
printf 'mount_source=%s\n' "${EXPECTED_SOURCE}" >>"${BACKUP_DIR}/deployment.txt"
printf 'mount_contract=uid:eom,gid:eom,file:0640,dir:0750,nosuid,nodev,noexec\n' \
  >>"${BACKUP_DIR}/deployment.txt"
chown root:root "${BACKUP_DIR}/deployment.txt"
chmod 0600 "${BACKUP_DIR}/deployment.txt"
BACKUP=

echo "ARTIFACT_MOUNT_HARDENING=PASS"
echo "ARTIFACT_WORLD_ACCESS=DENIED"
echo "RUNTIME_GIT_DEPENDENCY=ABSENT"
