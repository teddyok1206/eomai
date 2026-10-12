#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
IMAGE_ENV=/srv/eom/conda/envs/eom-image
CONTRACT_WHEEL=${1:-}
CONTRACT_SHA256=${2:-}
PROVIDER_WHEEL=${3:-}
PROVIDER_SHA256=${4:-}
PEFT_WHEEL=${5:-}
PEFT_SHA256=${6:-}
SOURCE_COMMIT=${7:-}
API_PYTHON=/srv/eom/conda/envs/eom-api/bin/python
DEPENDENCY_VERIFIER_SHA256=231089d320a70a41272c006ccca38e1c68014fccfba2ff61feb1515ca5699300
GPU_LEASE_WHEEL=
GPU_LEASE_SHA256=
UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-provider@.service
UNIT_TARGET=/etc/systemd/system/eom-image-provider@.service
REFERENCE_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-reference-acquirer@.service
REFERENCE_UNIT_TARGET=/etc/systemd/system/eom-image-reference-acquirer@.service
REFERENCE_DISCOVERY_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-reference-discoverer@.service
REFERENCE_DISCOVERY_UNIT_TARGET=/etc/systemd/system/eom-image-reference-discoverer@.service
REFERENCE_PROVIDER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-reference-provider@.service
REFERENCE_PROVIDER_UNIT_TARGET=/etc/systemd/system/eom-image-reference-provider@.service
REFERENCE_STYLE_PROVIDER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-reference-style-provider@.service
REFERENCE_STYLE_PROVIDER_UNIT_TARGET=/etc/systemd/system/eom-image-reference-style-provider@.service
REFERENCE_BASE_PROVIDER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-reference-base-provider@.service
REFERENCE_BASE_PROVIDER_UNIT_TARGET=/etc/systemd/system/eom-image-reference-base-provider@.service
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules
BINDING_SOURCE=${REPOSITORY}/config/local-image-provider.ssd1b.v6.json
BINDING_TARGET=/etc/eom/local-image-provider.json

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "LOCAL_IMAGE_RUNTIME_ROOT_REQUIRED"
if [[ $# -eq 11 ]]; then
  [[ "$8" == --gpu-lease-wheel && "${10}" == --gpu-lease-sha256 ]] || \
    fail "LOCAL_IMAGE_DEPENDENCY_ARGUMENTS_INVALID"
  GPU_LEASE_WHEEL=$9
  GPU_LEASE_SHA256=${11}
  [[ "${GPU_LEASE_SHA256}" =~ ^[0-9a-f]{64}$ && \
     "${GPU_LEASE_WHEEL}" == /tmp/eom-image-provider-build/*/dist/eom_gpu_lease-0.1.0-py3-none-any.whl ]] || \
    fail "LOCAL_IMAGE_GPU_LEASE_PIN_INVALID"
elif [[ $# -ne 7 ]]; then
  fail "LOCAL_IMAGE_DEPENDENCY_ARGUMENTS_INVALID"
fi
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_SOURCE_COMMIT_INVALID"
[[ "${CONTRACT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_WHEEL_HASH_INVALID"
[[ "${PROVIDER_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_WHEEL_HASH_INVALID"
[[ "${PEFT_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_WHEEL_HASH_INVALID"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || \
  fail "LOCAL_IMAGE_SOURCE_COMMIT_MISMATCH"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "LOCAL_IMAGE_SOURCE_TREE_DIRTY"
for wheel in "${CONTRACT_WHEEL}" "${PROVIDER_WHEEL}"; do
  [[ "${wheel}" == /tmp/eom-image-provider-build/*/*.whl ]] || \
    fail "LOCAL_IMAGE_WHEEL_PATH_INVALID"
  [[ -f "${wheel}" && ! -L "${wheel}" ]] || fail "LOCAL_IMAGE_WHEEL_INVALID"
done
[[ "${PEFT_WHEEL}" == /tmp/eom-image-trainer-build/*/dist/peft-0.17.1-*.whl ]] || \
  fail "LOCAL_IMAGE_DEPENDENCY_WHEEL_INVALID"
[[ -f "${PEFT_WHEEL}" && ! -L "${PEFT_WHEEL}" ]] || \
  fail "LOCAL_IMAGE_DEPENDENCY_WHEEL_INVALID"
[[ "$(sha256sum "${CONTRACT_WHEEL}" | cut -d' ' -f1)" == "${CONTRACT_SHA256}" ]] || \
  fail "LOCAL_IMAGE_WHEEL_HASH_MISMATCH"
[[ "$(sha256sum "${PROVIDER_WHEEL}" | cut -d' ' -f1)" == "${PROVIDER_SHA256}" ]] || \
  fail "LOCAL_IMAGE_WHEEL_HASH_MISMATCH"
[[ "$(sha256sum "${PEFT_WHEEL}" | cut -d' ' -f1)" == "${PEFT_SHA256}" ]] || \
  fail "LOCAL_IMAGE_WHEEL_HASH_MISMATCH"
[[ -f "${BINDING_SOURCE}" && ! -L "${BINDING_SOURCE}" ]] || \
  fail "LOCAL_IMAGE_BINDING_SOURCE_INVALID"
if systemctl list-units --type=service --state=activating,active --no-legend \
  'eom-image-provider@*.service' 'eom-image-reference-provider@*.service' \
  'eom-image-reference-style-provider@*.service' \
  'eom-image-reference-base-provider@*.service' \
  'eom-image-reference-acquirer@*.service' \
  'eom-image-reference-discoverer@*.service' | grep -q .; then
  fail "LOCAL_IMAGE_PROVIDER_ACTIVE"
fi

release_quarantine=$(mktemp -d /tmp/eom-image-provider-release.XXXXXXXX)
chmod 0700 "$release_quarantine"
release_helper="$release_quarantine/verify_release_dependency.py"
"$API_PYTHON" -I -B - "$REPOSITORY/scripts/image_provider/verify_release_dependency.py" \
  "$release_helper" "$DEPENDENCY_VERIFIER_SHA256" <<'PY_IMAGE_RELEASE_BOOTSTRAP'
import hashlib
import os
import stat
import sys
from pathlib import Path

source, target, expected = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
for member in (source, *source.parents, target.parent, *target.parent.parents):
    value = member.lstat()
    if stat.S_ISLNK(value.st_mode):
        raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_PATH_INVALID")
parent = target.parent.stat()
if parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) != 0o700:
    raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_STAGE_INVALID")
descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
def epoch(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
try:
    initial = os.fstat(descriptor)
    if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
        raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_FILE_INVALID")
    if not 0 < initial.st_size <= 128 * 1024:
        raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_FILE_INVALID")
    parts, total = [], 0
    while chunk := os.read(descriptor, 65536):
        total += len(chunk)
        if total > 128 * 1024:
            raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_FILE_INVALID")
        parts.append(chunk)
    payload = b"".join(parts)
    if total != initial.st_size or epoch(initial) != epoch(os.fstat(descriptor)):
        raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_SOURCE_CHANGED")
    if epoch(initial) != epoch(source.lstat()) or hashlib.sha256(payload).hexdigest() != expected:
        raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_HASH_MISMATCH")
finally:
    os.close(descriptor)
output = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
try:
    remaining = memoryview(payload)
    while remaining:
        count = os.write(output, remaining)
        if count <= 0:
            raise SystemExit("IMAGE_RELEASE_BOOTSTRAP_WRITE_FAILED")
        remaining = remaining[count:]
    os.fsync(output)
finally:
    os.close(output)
PY_IMAGE_RELEASE_BOOTSTRAP

release_exit() {
  local release_status=$?
  trap - EXIT
  if [[ "$release_status" -ne 0 ]]; then
    "$API_PYTHON" -I -B "$release_helper" recovery --profile provider \
      --stage "$release_quarantine" --source-commit "$SOURCE_COMMIT" || true
    printf 'IMAGE_RELEASE_RECOVERY_REQUIRED=YES\n' >&2
  fi
  printf 'IMAGE_RELEASE_QUARANTINE=%s\n' "$release_quarantine"
  return "$release_status"
}
trap release_exit EXIT
release_arguments=(prepare --profile provider --stage "$release_quarantine"
  --repository "$REPOSITORY" --source-commit "$SOURCE_COMMIT"
  --contract-wheel "$CONTRACT_WHEEL" --contract-sha256 "$CONTRACT_SHA256"
  --provider-wheel "$PROVIDER_WHEEL" --provider-sha256 "$PROVIDER_SHA256"
  --peft-wheel "$PEFT_WHEEL" --peft-sha256 "$PEFT_SHA256")

if [[ -n "$GPU_LEASE_WHEEL" ]]; then
  release_arguments+=(--gpu-lease-wheel "$GPU_LEASE_WHEEL" --gpu-lease-sha256 "$GPU_LEASE_SHA256")
fi
"$API_PYTHON" -I -B "$release_helper" "${release_arguments[@]}"
CONTRACT_WHEEL="$release_quarantine/wheels/$(basename "$CONTRACT_WHEEL")"
PROVIDER_WHEEL="$release_quarantine/wheels/$(basename "$PROVIDER_WHEEL")"
PEFT_WHEEL="$release_quarantine/wheels/$(basename "$PEFT_WHEEL")"

if [[ -n "$GPU_LEASE_WHEEL" ]]; then
  GPU_LEASE_WHEEL="$release_quarantine/wheels/eom_gpu_lease-0.1.0-py3-none-any.whl"
fi
"$API_PYTHON" -I -B "$release_helper" mark-mutation --profile provider \
  --stage "$release_quarantine" --source-commit "$SOURCE_COMMIT"

getent group eom-image >/dev/null || groupadd --system eom-image
if ! getent passwd eom-image >/dev/null; then
  useradd --system --gid eom-image --home-dir /var/lib/eom-image \
    --no-create-home --shell /usr/sbin/nologin eom-image
fi
[[ "$(id -gn eom-image)" == "eom-image" ]] || fail "LOCAL_IMAGE_IDENTITY_INVALID"
for forbidden in eom sudo docker lxd adm; do
  if id -nG eom-image | tr ' ' '\n' | grep -Fxq "${forbidden}"; then
    fail "LOCAL_IMAGE_IDENTITY_OVERPRIVILEGED"
  fi
done
getent group eom-image-reference >/dev/null || groupadd --system eom-image-reference
if ! getent passwd eom-image-reference >/dev/null; then
  useradd --system --gid eom-image-reference --home-dir /var/lib/eom-image-reference \
    --no-create-home --shell /usr/sbin/nologin eom-image-reference
fi
[[ "$(id -gn eom-image-reference)" == "eom-image-reference" ]] || \
  fail "LOCAL_IMAGE_REFERENCE_IDENTITY_INVALID"
for forbidden in eom sudo docker lxd adm eom-image; do
  if id -nG eom-image-reference | tr ' ' '\n' | grep -Fxq "${forbidden}"; then
    fail "LOCAL_IMAGE_REFERENCE_IDENTITY_OVERPRIVILEGED"
  fi
done
usermod --append --groups eom-image eom-workflow-runner
usermod --append --groups eom-image-reference eom-workflow-runner

[[ -d /etc/eom && ! -L /etc/eom ]] || fail "LOCAL_IMAGE_SHARED_CONFIG_ROOT_INVALID"
[[ "$(stat -c '%U:%G:%a' /etc/eom)" == "root:root:755" ]] || \
  fail "LOCAL_IMAGE_SHARED_CONFIG_ROOT_DRIFT"
binding_temporary=$(mktemp /etc/eom/.local-image-provider.XXXXXX)
install -o root -g root -m 0644 "${BINDING_SOURCE}" "${binding_temporary}"
mv -f "${binding_temporary}" "${BINDING_TARGET}"
install -d -o root -g eom-image -m 03770 /srv/eom/image-workspaces
install -d -o root -g eom-image-reference -m 03770 /srv/eom/image-reference-workspaces

if [[ -n "${GPU_LEASE_WHEEL}" ]]; then
  "${IMAGE_ENV}/bin/python" -I -B -m pip install --no-index --no-deps --no-compile --force-reinstall "${GPU_LEASE_WHEEL}"
fi
"${IMAGE_ENV}/bin/python" -I -B -m pip install --no-index --no-deps --force-reinstall \
  "${CONTRACT_WHEEL}" "${PROVIDER_WHEEL}" "${PEFT_WHEEL}"
"${IMAGE_ENV}/bin/python" "${REPOSITORY}/scripts/image_provider/normalize_runtime_permissions.py" \
  --binding "${BINDING_TARGET}" --model-store-root /srv/eom/models/image

install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
install -o root -g root -m 0644 "${REFERENCE_UNIT_SOURCE}" "${REFERENCE_UNIT_TARGET}"
install -o root -g root -m 0644 \
  "${REFERENCE_DISCOVERY_UNIT_SOURCE}" "${REFERENCE_DISCOVERY_UNIT_TARGET}"
install -o root -g root -m 0644 \
  "${REFERENCE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_PROVIDER_UNIT_TARGET}"
install -o root -g root -m 0644 \
  "${REFERENCE_STYLE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_STYLE_PROVIDER_UNIT_TARGET}"
install -o root -g root -m 0644 \
  "${REFERENCE_BASE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_BASE_PROVIDER_UNIT_TARGET}"
install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
systemctl daemon-reload
systemd-analyze verify "${UNIT_TARGET}"
systemd-analyze verify "${REFERENCE_UNIT_TARGET}"
systemd-analyze verify "${REFERENCE_DISCOVERY_UNIT_TARGET}"
systemd-analyze verify "${REFERENCE_PROVIDER_UNIT_TARGET}"
systemd-analyze verify "${REFERENCE_STYLE_PROVIDER_UNIT_TARGET}"
systemd-analyze verify "${REFERENCE_BASE_PROVIDER_UNIT_TARGET}"
cmp -s "${UNIT_SOURCE}" "${UNIT_TARGET}" || fail "LOCAL_IMAGE_UNIT_DRIFT"
cmp -s "${REFERENCE_UNIT_SOURCE}" "${REFERENCE_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_REFERENCE_UNIT_DRIFT"
cmp -s "${REFERENCE_DISCOVERY_UNIT_SOURCE}" "${REFERENCE_DISCOVERY_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_REFERENCE_DISCOVERY_UNIT_DRIFT"
cmp -s "${REFERENCE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_PROVIDER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_REFERENCE_PROVIDER_UNIT_DRIFT"
cmp -s "${REFERENCE_STYLE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_STYLE_PROVIDER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_REFERENCE_STYLE_PROVIDER_UNIT_DRIFT"
cmp -s "${REFERENCE_BASE_PROVIDER_UNIT_SOURCE}" "${REFERENCE_BASE_PROVIDER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_REFERENCE_BASE_PROVIDER_UNIT_DRIFT"
cmp -s "${POLKIT_SOURCE}" "${POLKIT_TARGET}" || fail "LOCAL_IMAGE_POLKIT_DRIFT"
cmp -s "${BINDING_SOURCE}" "${BINDING_TARGET}" || fail "LOCAL_IMAGE_BINDING_DRIFT"

"${API_PYTHON}" -I -B "${release_helper}" installed --profile provider \
  --stage "${release_quarantine}" --source-commit "${SOURCE_COMMIT}"
runuser -u eom-image -g eom-image -- env -i \
  HOME=/var/lib/eom-image PATH=${IMAGE_ENV}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 \
  "${IMAGE_ENV}/bin/python" -I -B -c \
  'import importlib.metadata; import eom_image_contracts, eom_image_provider; assert importlib.metadata.version("peft") == "0.17.1"; print("LOCAL_IMAGE_IMPORT=PASS")'

if [[ -n "${GPU_LEASE_WHEEL}" ]]; then
  "${IMAGE_ENV}/bin/python" -I -B -c \
    'import importlib.metadata, pathlib, sys; import eom_gpu_lease; assert importlib.metadata.version("eom-gpu-lease") == "0.1.0"; assert pathlib.Path(eom_gpu_lease.__file__).is_relative_to(sys.prefix); assert not {"torch", "transformers", "diffusers", "bitsandbytes"}.intersection(sys.modules)'
  printf 'GPU_LEASE_DEPENDENCY_INSTALLED=YES\n'
fi
printf 'GPU_SHARED_LEASE_MIGRATION_VERIFIED=NO\n'
printf 'GPU_DEFAULT_ACTIVATION_VERIFIED=NO\n'
printf 'LOCAL_IMAGE_RUNTIME_PREPARED=YES\n'
printf 'SOURCE_COMMIT=%s\n' "${SOURCE_COMMIT}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "${CONTRACT_SHA256}"
printf 'PROVIDER_WHEEL_SHA256=%s\n' "${PROVIDER_SHA256}"
printf 'PEFT_WHEEL_SHA256=%s\n' "${PEFT_SHA256}"
printf 'WORKSPACE_ROOT=root:eom-image:3770\n'
printf 'REFERENCE_WORKSPACE_ROOT=root:eom-image-reference:3770\n'
printf 'MODEL_STORE=root:eom-image:0750_0640\n'
printf 'RUNNER_RESTART_REQUIRED=YES\n'
printf 'CONTENT_PACK_ACTIVATION_REQUIRED=generated-knowledge-item@1.8.0\n'
