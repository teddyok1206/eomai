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
TRAINER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-trainer@.service
TRAINER_UNIT_TARGET=/etc/systemd/system/eom-image-trainer@.service
MICRO_PROBE_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-lora-micro-probe@.service
MICRO_PROBE_UNIT_TARGET=/etc/systemd/system/eom-image-lora-micro-probe@.service
MICRO_EVALUATION_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-lora-micro-evaluation@.service
MICRO_EVALUATION_UNIT_TARGET=/etc/systemd/system/eom-image-lora-micro-evaluation@.service
CROP_LOCATOR_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-crop-locator@.service
CROP_LOCATOR_UNIT_TARGET=/etc/systemd/system/eom-image-crop-locator@.service
PROVIDER_UNIT_SOURCE=${REPOSITORY}/infra/systemd/eom-image-provider@.service
PROVIDER_UNIT_TARGET=/etc/systemd/system/eom-image-provider@.service
POLKIT_SOURCE=${REPOSITORY}/infra/polkit/50-eom-worker-units.rules
POLKIT_TARGET=/etc/polkit-1/rules.d/50-eom-worker-units.rules

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "LOCAL_IMAGE_TRAINER_RUNTIME_ROOT_REQUIRED"
[[ "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_INVALID"
[[ "$(git -C "${REPOSITORY}" rev-parse HEAD)" == "${SOURCE_COMMIT}" ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_MISMATCH"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
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
  'eom-image-lora-micro-evaluation@*.service' \
  'eom-image-crop-locator@*.service' | grep -q .; then
  fail "LOCAL_IMAGE_GPU_UNIT_ACTIVE"
fi

if [[ ! -d "${TRAINER_ENV}" ]]; then
  "${CONDA}" create --offline --yes --clone "${INFERENCE_ENV}" --prefix "${TRAINER_ENV}"
fi
[[ -x "${TRAINER_ENV}/bin/python" && -x "${TRAINER_ENV}/bin/pip" ]] || \
  fail "LOCAL_IMAGE_TRAINER_ENV_INVALID"
"${TRAINER_ENV}/bin/python" -m pip install --no-deps --force-reinstall \
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
install -o root -g root -m 0644 "${MICRO_EVALUATION_UNIT_SOURCE}" "${MICRO_EVALUATION_UNIT_TARGET}"
install -o root -g root -m 0644 "${CROP_LOCATOR_UNIT_SOURCE}" "${CROP_LOCATOR_UNIT_TARGET}"
install -o root -g root -m 0644 "${PROVIDER_UNIT_SOURCE}" "${PROVIDER_UNIT_TARGET}"
install -o root -g root -m 0644 "${POLKIT_SOURCE}" "${POLKIT_TARGET}"
systemctl daemon-reload
systemd-analyze verify "${TRAINER_UNIT_TARGET}" "${MICRO_PROBE_UNIT_TARGET}" \
  "${MICRO_EVALUATION_UNIT_TARGET}" \
  "${CROP_LOCATOR_UNIT_TARGET}" \
  "${PROVIDER_UNIT_TARGET}"
cmp -s "${TRAINER_UNIT_SOURCE}" "${TRAINER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_TRAINER_UNIT_DRIFT"
cmp -s "${MICRO_PROBE_UNIT_SOURCE}" "${MICRO_PROBE_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_MICRO_PROBE_UNIT_DRIFT"
cmp -s "${MICRO_EVALUATION_UNIT_SOURCE}" "${MICRO_EVALUATION_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_MICRO_EVALUATION_UNIT_DRIFT"
cmp -s "${CROP_LOCATOR_UNIT_SOURCE}" "${CROP_LOCATOR_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_CROP_LOCATOR_UNIT_DRIFT"
cmp -s "${PROVIDER_UNIT_SOURCE}" "${PROVIDER_UNIT_TARGET}" || \
  fail "LOCAL_IMAGE_PROVIDER_UNIT_DRIFT"
cmp -s "${POLKIT_SOURCE}" "${POLKIT_TARGET}" || \
  fail "LOCAL_IMAGE_TRAINER_POLKIT_DRIFT"

runuser -u eom-image -g eom-image -- env -i \
  HOME=/var/lib/eom-image PATH=${TRAINER_ENV}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 \
  "${TRAINER_ENV}/bin/python" -I - <<'PY'
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

printf 'LOCAL_IMAGE_TRAINER_RUNTIME_PREPARED=YES\n'
printf 'SOURCE_COMMIT=%s\n' "${SOURCE_COMMIT}"
printf 'TRAINER_WORKSPACE_ROOT=root:eom-image:3770\n'
printf 'GPU_CAPACITY_LOCK=/var/lib/eom-image/gpu0.lock\n'
printf 'TRAINING_AUTHORIZATION_REQUIRED=YES\n'
