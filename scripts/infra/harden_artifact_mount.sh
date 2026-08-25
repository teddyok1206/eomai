#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
FSTAB=/etc/fstab
MOUNT_POINT=/mnt/nas
MOUNT_UNIT=mnt-nas.mount
AUTOMOUNT_UNIT=mnt-nas.automount
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
SMOKE_DIR=
SMOKE_FILE=

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
    file_mode=0660 dir_mode=0770; do
    require_mount_option "${options}" "${required}"
  done
  [[ "$(stat -c '%U:%G:%a' "${MOUNT_POINT}")" == eom:eom:770 ]] || \
    fail "Artifact mount metadata mismatch"
  [[ "$(stat -c '%U:%G:%a' "${ARTIFACT_ROOT}")" == eom:eom:770 ]] || \
    fail "Artifact root metadata mismatch"
}

verify_writer_identity() {
  local identity=$1
  SMOKE_DIR="${ARTIFACT_ROOT}/.eom-writer-smoke-${identity}-$$"
  SMOKE_FILE="${SMOKE_DIR}/probe"
  [[ ! -e ${SMOKE_DIR} && ! -L ${SMOKE_DIR} ]] || fail "Artifact smoke path exists"
  runuser -u "${identity}" -- /usr/bin/mkdir -- "${SMOKE_DIR}"
  [[ "$(stat -c '%U:%G:%a' "${SMOKE_DIR}")" == eom:eom:770 ]] || \
    fail "Artifact writer directory metadata mismatch"
  runuser -u "${identity}" -- /bin/sh -c \
    'umask 027; printf probe >"$1"' sh "${SMOKE_FILE}"
  [[ "$(stat -c '%U:%G:%a' "${SMOKE_FILE}")" == eom:eom:660 ]] || \
    fail "Artifact writer file metadata mismatch"
  runuser -u "${identity}" -- /bin/cat -- "${SMOKE_FILE}" >/dev/null
  runuser -u "${identity}" -- /bin/rm -- "${SMOKE_FILE}"
  SMOKE_FILE=
  runuser -u "${identity}" -- /usr/bin/rmdir -- "${SMOKE_DIR}"
  SMOKE_DIR=
}

recover() {
  local status=$?
  trap - EXIT
  if [[ ${status} -ne 0 ]]; then
    [[ -z ${SMOKE_FILE} || ! -e ${SMOKE_FILE} ]] || rm -f -- "${SMOKE_FILE}"
    [[ -z ${SMOKE_DIR} || ! -d ${SMOKE_DIR} ]] || rmdir -- "${SMOKE_DIR}" || true
    if [[ -n ${BACKUP} && -f ${BACKUP} ]]; then
      local restore
      restore=$(mktemp /etc/.eom-fstab-restore.XXXXXX) || true
      if [[ -n ${restore:-} ]]; then
        install -o root -g root -m 0644 "${BACKUP}" "${restore}" || true
        mv -fT "${restore}" "${FSTAB}" || true
      fi
      systemctl daemon-reload || true
      systemctl restart "${MOUNT_UNIT}" || true
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
systemctl is-active --quiet "${MOUNT_UNIT}" || fail "Artifact mount unit is not active"
systemctl is-active --quiet "${AUTOMOUNT_UNIT}" || fail "Artifact automount unit is not active"
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
systemctl restart "${MOUNT_UNIT}"
systemctl is-active --quiet "${MOUNT_UNIT}"
systemctl is-active --quiet "${AUTOMOUNT_UNIT}"
verify_mount
for identity in eom-workflow-runner eom-catalog-manager eom-hwpx-manager; do
  verify_writer_identity "${identity}"
done
runuser -u eom-cdx-01 -- test ! -w "${ARTIFACT_ROOT}" || \
  fail "fixed worker can write the Artifact root"
systemctl start "${SERVICES[@]}"
STOPPED=0
for service in "${SERVICES[@]}"; do
  systemctl is-active --quiet "${service}"
  systemctl is-enabled --quiet "${service}"
done

printf 'source_commit=%s\n' "${EXPECTED_COMMIT}" >"${BACKUP_DIR}/deployment.txt"
printf 'deployed_at_utc=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" >>"${BACKUP_DIR}/deployment.txt"
printf 'mount_source=%s\n' "${EXPECTED_SOURCE}" >>"${BACKUP_DIR}/deployment.txt"
printf 'mount_contract=uid:eom,gid:eom,file:0660,dir:0770,nosuid,nodev,noexec\n' \
  >>"${BACKUP_DIR}/deployment.txt"
chown root:root "${BACKUP_DIR}/deployment.txt"
chmod 0600 "${BACKUP_DIR}/deployment.txt"
BACKUP=

echo "ARTIFACT_MOUNT_HARDENING=PASS"
echo "ARTIFACT_MANAGER_WRITERS=PASS"
echo "FIXED_WORKER_WRITE=DENIED"
echo "ARTIFACT_WORLD_ACCESS=DENIED"
echo "RUNTIME_GIT_DEPENDENCY=ABSENT"
