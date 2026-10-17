#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
CONDA=/home/eom/miniconda3/bin/conda
INFERENCE_ENV=/srv/eom/conda/envs/eom-image
TRAINER_ENV=/srv/eom/conda/envs/eom-image-trainer
CONTRACT_WHEEL=${1:-}
CONTRACT_SHA256=${2:-}
PROVIDER_WHEEL=${3:-}
PROVIDER_SHA256=${4:-}
TRAINER_WHEEL=${5:-}
TRAINER_SHA256=${6:-}
PEFT_WHEEL=${7:-}
PEFT_SHA256=${8:-}
BITSANDBYTES_WHEEL=${9:-}
BITSANDBYTES_SHA256=${10:-}
SOURCE_COMMIT=${11:-}
API_PYTHON=/srv/eom/conda/envs/eom-api/bin/python
DEPENDENCY_VERIFIER_SHA256=44f7e11f4e43f7fe78b485ced65f5e006b36d0c991b1822d40911104a52d00e8
GPU_LEASE_WHEEL=
GPU_LEASE_SHA256=
TRAINER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-trainer@.service
TRAINER_UNIT_TARGET=/etc/systemd/system/eom-image-trainer@.service
MICRO_PROBE_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-lora-micro-probe@.service
MICRO_PROBE_UNIT_TARGET=/etc/systemd/system/eom-image-lora-micro-probe@.service
SCIENCE_MICRO_PROBE_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-lora-micro-probe@.service
SCIENCE_MICRO_PROBE_UNIT_TARGET=/etc/systemd/system/eom-image-science-lora-micro-probe@.service
SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-campaign-lora-micro-probe@.service
SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_TARGET=/etc/systemd/system/eom-image-science-campaign-lora-micro-probe@.service
MICRO_EVALUATION_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-lora-micro-evaluation@.service
MICRO_EVALUATION_UNIT_TARGET=/etc/systemd/system/eom-image-lora-micro-evaluation@.service
SCIENCE_MICRO_EVALUATION_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-lora-micro-evaluation@.service
SCIENCE_MICRO_EVALUATION_UNIT_TARGET=/etc/systemd/system/eom-image-science-lora-micro-evaluation@.service
SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-campaign-lora-micro-evaluation@.service
SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_TARGET=/etc/systemd/system/eom-image-science-campaign-lora-micro-evaluation@.service
SCIENCE_SUBJECT_BENCHMARK_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-subject-benchmark@.service
SCIENCE_SUBJECT_BENCHMARK_UNIT_TARGET=/etc/systemd/system/eom-image-science-subject-benchmark@.service
SCIENCE_SUBJECT_MULTISEED_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-subject-multiseed@.service
SCIENCE_SUBJECT_MULTISEED_UNIT_TARGET=/etc/systemd/system/eom-image-science-subject-multiseed@.service
CROP_LOCATOR_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-crop-locator@.service
CROP_LOCATOR_UNIT_TARGET=/etc/systemd/system/eom-image-crop-locator@.service
SCIENCE_VISUAL_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-science-visual-pilot@.service
SCIENCE_VISUAL_UNIT_TARGET=/etc/systemd/system/eom-image-science-visual-pilot@.service
PROVIDER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-provider@.service
PROVIDER_UNIT_TARGET=/etc/systemd/system/eom-image-provider@.service
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "LOCAL_IMAGE_TRAINER_RUNTIME_ROOT_REQUIRED"
# Keep the legacy provisioning/rollback path, but never mix it with only part of
# the shared image GPU lifetime release. Use the coordinated release owner.
if [[ -e /usr/local/libexec/eom-image-runtime/watch_gpu_guard.py ]] || \
   /usr/bin/grep -Fq '/usr/local/libexec/eom-image-runtime/run_gpu_unit.py' "$TRAINER_UNIT_SOURCE"; then
  fail "LOCAL_IMAGE_COORDINATED_GPU_RELEASE_REQUIRED"
fi
if [[ $# -eq 15 ]]; then
  [[ "${12}" == --gpu-lease-wheel && "${14}" == --gpu-lease-sha256 ]] || \
    fail "LOCAL_IMAGE_TRAINER_DEPENDENCY_ARGUMENTS_INVALID"
  GPU_LEASE_WHEEL=${13}
  GPU_LEASE_SHA256=${15}
  [[ "${GPU_LEASE_SHA256}" =~ ^[0-9a-f]{64}$ && \
     "${GPU_LEASE_WHEEL}" == /tmp/eom-image-trainer-build/*/dist/eom_gpu_lease-0.1.0-py3-none-any.whl ]] || \
    fail "LOCAL_IMAGE_TRAINER_GPU_LEASE_PIN_INVALID"
elif [[ $# -ne 11 ]]; then
  fail "LOCAL_IMAGE_TRAINER_DEPENDENCY_ARGUMENTS_INVALID"
fi
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_INVALID"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_MISMATCH"
# Deployment consumes committed wheels and committed unit files only. Ignore unrelated untracked
# operator files while still rejecting any tracked or staged drift.
[[ -z "$(git -C "${REPOSITORY}" status --porcelain --untracked-files=no)" ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_TREE_DIRTY"
for hash in "${CONTRACT_SHA256}" "${PROVIDER_SHA256}" "${TRAINER_SHA256}" \
  "${PEFT_SHA256}" "${BITSANDBYTES_SHA256}"; do
  [[ "${hash}" =~ ^[0-9a-f]{64}$ ]] || fail "LOCAL_IMAGE_TRAINER_WHEEL_HASH_INVALID"
done
for wheel in "${CONTRACT_WHEEL}" "${PROVIDER_WHEEL}" "${TRAINER_WHEEL}" \
  "${PEFT_WHEEL}" "${BITSANDBYTES_WHEEL}"; do
  [[ "${wheel}" == /tmp/eom-image-trainer-build/*/*.whl ]] || \
    fail "LOCAL_IMAGE_TRAINER_WHEEL_PATH_INVALID"
  [[ -f "${wheel}" && ! -L "${wheel}" ]] || fail "LOCAL_IMAGE_TRAINER_WHEEL_INVALID"
done
for pair in \
  "${CONTRACT_WHEEL}:${CONTRACT_SHA256}" \
  "${PROVIDER_WHEEL}:${PROVIDER_SHA256}" \
  "${TRAINER_WHEEL}:${TRAINER_SHA256}" \
  "${PEFT_WHEEL}:${PEFT_SHA256}" \
  "${BITSANDBYTES_WHEEL}:${BITSANDBYTES_SHA256}"; do
  wheel=${pair%:*}
  expected=${pair##*:}
  [[ "$(sha256sum "${wheel}" | cut -d' ' -f1)" == "${expected}" ]] || \
    fail "LOCAL_IMAGE_TRAINER_WHEEL_HASH_MISMATCH"
done
[[ "$(basename "${PEFT_WHEEL}")" == peft-0.17.1-* ]] || \
  fail "LOCAL_IMAGE_TRAINER_DEPENDENCY_WHEEL_INVALID"
[[ "$(basename "${BITSANDBYTES_WHEEL}")" == bitsandbytes-0.47.0-* ]] || \
  fail "LOCAL_IMAGE_TRAINER_DEPENDENCY_WHEEL_INVALID"
if systemctl list-units --type=service --state=activating,active --no-legend \
  'eom-image-provider@*.service' 'eom-image-trainer@*.service' \
  'eom-image-lora-micro-probe@*.service' \
  'eom-image-science-lora-micro-probe@*.service' \
  'eom-image-science-campaign-lora-micro-probe@*.service' \
  'eom-image-lora-micro-evaluation@*.service' \
  'eom-image-science-lora-micro-evaluation@*.service' \
  'eom-image-science-campaign-lora-micro-evaluation@*.service' \
  'eom-image-science-subject-benchmark@*.service' \
  'eom-image-science-subject-multiseed@*.service' \
  'eom-image-crop-locator@*.service' \
  'eom-image-science-visual-pilot@*.service' | grep -q .; then
  fail "LOCAL_IMAGE_GPU_UNIT_ACTIVE"
fi

release_quarantine=$(mktemp -d /tmp/eom-image-trainer-release.XXXXXXXX)
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
    "$API_PYTHON" -I -B "$release_helper" recovery --profile trainer \
      --stage "$release_quarantine" --source-commit "$SOURCE_COMMIT" || true
    printf 'IMAGE_RELEASE_RECOVERY_REQUIRED=YES\n' >&2
  fi
  printf 'IMAGE_RELEASE_QUARANTINE=%s\n' "$release_quarantine"
  return "$release_status"
}
trap release_exit EXIT
release_arguments=(prepare --profile trainer --stage "$release_quarantine"
  --repository "$REPOSITORY" --source-commit "$SOURCE_COMMIT"
  --contract-wheel "$CONTRACT_WHEEL" --contract-sha256 "$CONTRACT_SHA256"
  --provider-wheel "$PROVIDER_WHEEL" --provider-sha256 "$PROVIDER_SHA256"
  --peft-wheel "$PEFT_WHEEL" --peft-sha256 "$PEFT_SHA256")
release_arguments+=(--trainer-wheel "$TRAINER_WHEEL" --trainer-sha256 "$TRAINER_SHA256"
  --bitsandbytes-wheel "$BITSANDBYTES_WHEEL" --bitsandbytes-sha256 "$BITSANDBYTES_SHA256")
if [[ -n "$GPU_LEASE_WHEEL" ]]; then
  release_arguments+=(--gpu-lease-wheel "$GPU_LEASE_WHEEL" --gpu-lease-sha256 "$GPU_LEASE_SHA256")
fi
"$API_PYTHON" -I -B "$release_helper" "${release_arguments[@]}"
CONTRACT_WHEEL="$release_quarantine/wheels/$(basename "$CONTRACT_WHEEL")"
PROVIDER_WHEEL="$release_quarantine/wheels/$(basename "$PROVIDER_WHEEL")"
PEFT_WHEEL="$release_quarantine/wheels/$(basename "$PEFT_WHEEL")"
TRAINER_WHEEL="$release_quarantine/wheels/$(basename "$TRAINER_WHEEL")"
BITSANDBYTES_WHEEL="$release_quarantine/wheels/$(basename "$BITSANDBYTES_WHEEL")"
if [[ -n "$GPU_LEASE_WHEEL" ]]; then
  GPU_LEASE_WHEEL="$release_quarantine/wheels/eom_gpu_lease-0.1.0-py3-none-any.whl"
fi
"$API_PYTHON" -I -B "$release_helper" mark-mutation --profile trainer \
  --stage "$release_quarantine" --source-commit "$SOURCE_COMMIT"

if [[ ! -d "${TRAINER_ENV}" ]]; then
  "${CONDA}" create --offline --yes --clone "${INFERENCE_ENV}" --prefix "${TRAINER_ENV}"
fi
[[ -x "${TRAINER_ENV}/bin/python" && -x "${TRAINER_ENV}/bin/pip" ]] || \
  fail "LOCAL_IMAGE_TRAINER_ENV_INVALID"
if [[ -n "${GPU_LEASE_WHEEL}" ]]; then
  "${TRAINER_ENV}/bin/python" -I -B -m pip install --no-index --no-deps --no-compile --force-reinstall "${GPU_LEASE_WHEEL}"
fi
"${TRAINER_ENV}/bin/python" -I -B -m pip install --no-index --no-deps --force-reinstall \
  "${CONTRACT_WHEEL}" "${PROVIDER_WHEEL}" "${PEFT_WHEEL}" \
  "${BITSANDBYTES_WHEEL}" "${TRAINER_WHEEL}"

getent passwd eom-image >/dev/null || fail "LOCAL_IMAGE_TRAINER_IDENTITY_MISSING"
[[ "$(id -gn eom-image)" == "eom-image" ]] || fail "LOCAL_IMAGE_TRAINER_IDENTITY_INVALID"
for forbidden in eom sudo docker lxd adm; do
  if id -nG eom-image | tr ' ' '\n' | grep -Fxq "${forbidden}"; then
    fail "LOCAL_IMAGE_TRAINER_IDENTITY_OVERPRIVILEGED"
  fi
done
install -d -o root -g eom-image -m 03770 /srv/eom/image-training-workspaces
install -o root -g root -m 0644 "${TRAINER_UNIT_SOURCE}" "${TRAINER_UNIT_TARGET}"
install -o root -g root -m 0644 "${MICRO_PROBE_UNIT_SOURCE}" "${MICRO_PROBE_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_MICRO_PROBE_UNIT_SOURCE}" "${SCIENCE_MICRO_PROBE_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_SOURCE}" "${SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_TARGET}"
install -o root -g root -m 0644 "${MICRO_EVALUATION_UNIT_SOURCE}" "${MICRO_EVALUATION_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_MICRO_EVALUATION_UNIT_SOURCE}" "${SCIENCE_MICRO_EVALUATION_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_SOURCE}" "${SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_SUBJECT_BENCHMARK_UNIT_SOURCE}" "${SCIENCE_SUBJECT_BENCHMARK_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_SUBJECT_MULTISEED_UNIT_SOURCE}" "${SCIENCE_SUBJECT_MULTISEED_UNIT_TARGET}"
install -o root -g root -m 0644 "${CROP_LOCATOR_UNIT_SOURCE}" "${CROP_LOCATOR_UNIT_TARGET}"
install -o root -g root -m 0644 "${SCIENCE_VISUAL_UNIT_SOURCE}" "${SCIENCE_VISUAL_UNIT_TARGET}"
install -o root -g root -m 0644 "${PROVIDER_UNIT_SOURCE}" "${PROVIDER_UNIT_TARGET}"
install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
systemctl daemon-reload
systemd-analyze verify "${TRAINER_UNIT_TARGET}" "${MICRO_PROBE_UNIT_TARGET}" \
  "${SCIENCE_MICRO_PROBE_UNIT_TARGET}" \
  "${SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_TARGET}" \
  "${MICRO_EVALUATION_UNIT_TARGET}" \
  "${SCIENCE_MICRO_EVALUATION_UNIT_TARGET}" \
  "${SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_TARGET}" \
  "${SCIENCE_SUBJECT_BENCHMARK_UNIT_TARGET}" \
  "${SCIENCE_SUBJECT_MULTISEED_UNIT_TARGET}" \
  "${CROP_LOCATOR_UNIT_TARGET}" \
  "${SCIENCE_VISUAL_UNIT_TARGET}" \
  "${PROVIDER_UNIT_TARGET}"
cmp -s "${TRAINER_UNIT_SOURCE}" "${TRAINER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_TRAINER_UNIT_DRIFT"
cmp -s "${MICRO_PROBE_UNIT_SOURCE}" "${MICRO_PROBE_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_MICRO_PROBE_UNIT_DRIFT"
cmp -s "${SCIENCE_MICRO_PROBE_UNIT_SOURCE}" "${SCIENCE_MICRO_PROBE_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_MICRO_PROBE_UNIT_DRIFT"
cmp -s "${SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_SOURCE}" \
  "${SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_CAMPAIGN_MICRO_PROBE_UNIT_DRIFT"
cmp -s "${MICRO_EVALUATION_UNIT_SOURCE}" "${MICRO_EVALUATION_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_MICRO_EVALUATION_UNIT_DRIFT"
cmp -s "${SCIENCE_MICRO_EVALUATION_UNIT_SOURCE}" "${SCIENCE_MICRO_EVALUATION_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_MICRO_EVALUATION_UNIT_DRIFT"
cmp -s "${SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_SOURCE}" \
  "${SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_CAMPAIGN_MICRO_EVALUATION_UNIT_DRIFT"
cmp -s "${SCIENCE_SUBJECT_BENCHMARK_UNIT_SOURCE}" \
  "${SCIENCE_SUBJECT_BENCHMARK_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_SUBJECT_BENCHMARK_UNIT_DRIFT"
cmp -s "${SCIENCE_SUBJECT_MULTISEED_UNIT_SOURCE}" \
  "${SCIENCE_SUBJECT_MULTISEED_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_SUBJECT_MULTISEED_UNIT_DRIFT"
cmp -s "${CROP_LOCATOR_UNIT_SOURCE}" "${CROP_LOCATOR_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_CROP_LOCATOR_UNIT_DRIFT"
cmp -s "${SCIENCE_VISUAL_UNIT_SOURCE}" "${SCIENCE_VISUAL_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_SCIENCE_VISUAL_UNIT_DRIFT"
cmp -s "${PROVIDER_UNIT_SOURCE}" "${PROVIDER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_PROVIDER_UNIT_DRIFT"
cmp -s "${POLKIT_SOURCE}" "${POLKIT_TARGET}" || \
  fail "LOCAL_IMAGE_TRAINER_POLKIT_DRIFT"

"${API_PYTHON}" -I -B "${release_helper}" installed --profile trainer \
  --stage "${release_quarantine}" --source-commit "${SOURCE_COMMIT}"
runuser -u eom-image -g eom-image -- env -i \
  HOME=/var/lib/eom-image PATH=${TRAINER_ENV}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 \
  "${TRAINER_ENV}/bin/python" -I -B - <<'PY'
from importlib import metadata
import eom_image_contracts
import eom_image_provider
import eom_image_trainer

expected = {
    "accelerate": "1.10.1",
    "bitsandbytes": "0.47.0",
    "diffusers": "0.35.2",
    "peft": "0.17.1",
    "torch": "2.7.1+cu128",
    "transformers": "4.56.2",
}
actual = {name: metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"LOCAL_IMAGE_TRAINER_RUNTIME_DRIFT:{actual!r}")
print("LOCAL_IMAGE_TRAINER_IMPORT=PASS")
PY

if [[ -n "${GPU_LEASE_WHEEL}" ]]; then
  "${TRAINER_ENV}/bin/python" -I -B -c \
    'import importlib.metadata, pathlib, sys; import eom_gpu_lease; assert importlib.metadata.version("eom-gpu-lease") == "0.1.0"; assert pathlib.Path(eom_gpu_lease.__file__).is_relative_to(sys.prefix); assert not {"torch", "transformers", "diffusers", "bitsandbytes"}.intersection(sys.modules)'
  printf 'GPU_LEASE_DEPENDENCY_INSTALLED=YES\n'
fi
printf 'GPU_SHARED_LEASE_MIGRATION_VERIFIED=NO\n'
printf 'GPU_DEFAULT_ACTIVATION_VERIFIED=NO\n'
printf 'LOCAL_IMAGE_TRAINER_RUNTIME_PREPARED=YES\n'
printf 'SOURCE_COMMIT=%s\n' "${SOURCE_COMMIT}"
printf 'TRAINER_WORKSPACE_ROOT=root:eom-image:3770\n'
printf 'GPU_CAPACITY_LOCK=/var/lib/eom-image/gpu0.lock\n'
printf 'TRAINING_AUTHORIZATION_REQUIRED=YES\n'
