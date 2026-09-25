#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-trainer-build

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "LOCAL_IMAGE_TRAINER_BUILD_MUST_NOT_RUN_AS_ROOT"
head_commit=$(git -C "${REPOSITORY}" rev-parse HEAD)
[[ "${head_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_TRAINER_SOURCE_COMMIT_INVALID"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "LOCAL_IMAGE_TRAINER_SOURCE_TREE_DIRTY"
umask 077
mkdir -p "${OUTPUT_ROOT}"
chmod 0700 "${OUTPUT_ROOT}"
state=$(mktemp -d "${OUTPUT_ROOT}/${head_commit}.XXXXXX")
chmod 0700 "${state}"
mkdir "${state}/source" "${state}/dist"
git -C "${REPOSITORY}" archive "${head_commit}" \
  packages/image_contracts services/image_provider services/image_trainer \
  | tar -x -C "${state}/source"
for project in packages/image_contracts services/image_provider services/image_trainer; do
  "${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
    --wheel-dir "${state}/dist" "${state}/source/${project}"
done
contract_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_image_contracts-*.whl' -print)
provider_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_provider-*.whl' -print)
trainer_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_trainer-*.whl' -print)
for wheel in "${contract_wheel}" "${provider_wheel}" "${trainer_wheel}"; do
  [[ -n "${wheel}" && "${wheel}" != *$'\n'* ]] || \
    fail "LOCAL_IMAGE_TRAINER_WHEEL_INVALID"
done
"${PYTHON}" - "${contract_wheel}" "${provider_wheel}" "${trainer_wheel}" <<'PY'
import sys
import zipfile

contract, provider, trainer = sys.argv[1:]
with zipfile.ZipFile(contract) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_contracts/schemas/local-image-training-eligibility-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-proposal-set-v1.schema.json",
        "eom_image_contracts/schemas/local-image-training-crop-review-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-checkpoint-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-lora-training-worker-result-v1.schema.json",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_TRAINER_CONTRACT_WHEEL_INVALID")
with zipfile.ZipFile(provider) as archive:
    if "eom_image_provider/provider.py" not in set(archive.namelist()):
        raise SystemExit("LOCAL_IMAGE_TRAINER_PROVIDER_WHEEL_INVALID")
with zipfile.ZipFile(trainer) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_trainer/checkpoints.py",
        "eom_image_trainer/cli.py",
        "eom_image_trainer/dataset_builder.py",
        "eom_image_trainer/diffusers_backend.py",
        "eom_image_trainer/runner.py",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_TRAINER_WHEEL_INVALID")
PY
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
for variable_and_wheel in \
  "CONTRACT:${contract_wheel}" \
  "PROVIDER:${provider_wheel}" \
  "TRAINER:${trainer_wheel}"; do
  variable=${variable_and_wheel%%:*}
  wheel=${variable_and_wheel#*:}
  sha=$(sha256sum "${wheel}" | cut -d' ' -f1)
  printf '%s_WHEEL=%s\n' "${variable}" "${wheel}"
  printf '%s_WHEEL_SHA256=%s\n' "${variable}" "${sha}"
done
