#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-provider-build

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "LOCAL_IMAGE_BUILD_MUST_NOT_RUN_AS_ROOT"
head_commit=$(git -C "${REPOSITORY}" rev-parse HEAD)
[[ "${head_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "LOCAL_IMAGE_SOURCE_COMMIT_INVALID"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain)" ]] || \
  fail "LOCAL_IMAGE_SOURCE_TREE_DIRTY"
umask 077
mkdir -p "${OUTPUT_ROOT}"
chmod 0700 "${OUTPUT_ROOT}"
state=$(mktemp -d "${OUTPUT_ROOT}/${head_commit}.XXXXXX")
chmod 0700 "${state}"
mkdir "${state}/source" "${state}/dist"
git -C "${REPOSITORY}" archive "${head_commit}" packages/image_contracts services/image_provider \
  | tar -x -C "${state}/source"
"${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/packages/image_contracts"
"${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
  --wheel-dir "${state}/dist" "${state}/source/services/image_provider"
contract_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_image_contracts-*.whl' -print)
provider_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_provider-*.whl' -print)
[[ -n "${contract_wheel}" && "${contract_wheel}" != *$'\n'* ]] || \
  fail "LOCAL_IMAGE_CONTRACT_WHEEL_INVALID"
[[ -n "${provider_wheel}" && "${provider_wheel}" != *$'\n'* ]] || \
  fail "LOCAL_IMAGE_PROVIDER_WHEEL_INVALID"
"${PYTHON}" - "${contract_wheel}" "${provider_wheel}" <<'PY'
import sys
import zipfile

contract, provider = sys.argv[1:]
with zipfile.ZipFile(contract) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_contracts/schemas/local-image-provider-binding-v1.schema.json",
        "eom_image_contracts/schemas/local-image-composite-request-v1.schema.json",
        "eom_image_contracts/schemas/local-image-composite-receipt-v1.schema.json",
    }
    if not required.issubset(names):
        raise SystemExit("LOCAL_IMAGE_CONTRACT_WHEEL_INVALID")
with zipfile.ZipFile(provider) as archive:
    names = set(archive.namelist())
    if not {
        "eom_image_provider/cli.py",
        "eom_image_provider/provider.py",
        "eom_image_provider/diffusers_backend.py",
    }.issubset(names):
        raise SystemExit("LOCAL_IMAGE_PROVIDER_WHEEL_INVALID")
PY
contract_sha=$(sha256sum "${contract_wheel}" | cut -d' ' -f1)
provider_sha=$(sha256sum "${provider_wheel}" | cut -d' ' -f1)
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
printf 'CONTRACT_WHEEL=%s\n' "${contract_wheel}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "${contract_sha}"
printf 'PROVIDER_WHEEL=%s\n' "${provider_wheel}"
printf 'PROVIDER_WHEEL_SHA256=%s\n' "${provider_sha}"
