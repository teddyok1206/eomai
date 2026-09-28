#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=/home/eom/EOM
PYTHON=/srv/eom/conda/envs/eom-api/bin/python
PIP=/srv/eom/conda/envs/eom-api/bin/pip
OUTPUT_ROOT=/tmp/eom-image-candidate-build

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "IMAGE_CANDIDATE_BUILD_MUST_NOT_RUN_AS_ROOT"
head_commit=$(git -C "${REPOSITORY}" rev-parse HEAD)
[[ "${head_commit}" =~ ^[0-9a-f]{40}$ ]] || fail "IMAGE_CANDIDATE_SOURCE_COMMIT_INVALID"
[[ -z "$(git -C "${REPOSITORY}" status --porcelain --untracked-files=no)" ]] || \
  fail "IMAGE_CANDIDATE_SOURCE_TREE_DIRTY"
umask 077
mkdir -p "${OUTPUT_ROOT}"
chmod 0700 "${OUTPUT_ROOT}"
state=$(mktemp -d "${OUTPUT_ROOT}/${head_commit}.XXXXXX")
chmod 0700 "${state}"
mkdir "${state}/source" "${state}/dist"
git -C "${REPOSITORY}" archive "${head_commit}" \
  packages/image_contracts services/image_candidate_runner \
  | tar -x -C "${state}/source"
for project in packages/image_contracts services/image_candidate_runner; do
  "${PIP}" wheel --disable-pip-version-check --no-deps --no-build-isolation \
    --wheel-dir "${state}/dist" "${state}/source/${project}"
done
contract_wheel=$(find "${state}/dist" -maxdepth 1 -type f -name 'eom_image_contracts-*.whl' -print)
runner_wheel=$(find "${state}/dist" -maxdepth 1 -type f \
  -name 'eom_local_image_candidate_runner-*.whl' -print)
for wheel in "${contract_wheel}" "${runner_wheel}"; do
  [[ -n "${wheel}" && "${wheel}" != *$'\n'* ]] || fail "IMAGE_CANDIDATE_WHEEL_INVALID"
done
"${PYTHON}" - "${contract_wheel}" "${runner_wheel}" <<'PY'
import sys
import zipfile

contract, runner = sys.argv[1:]
with zipfile.ZipFile(contract) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_contracts/schemas/local-image-model-candidate-manifest-v1.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-plan-v1.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-command-v1.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-result-v1.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-plan-v2.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-command-v2.schema.json",
        "eom_image_contracts/schemas/local-image-flux2-reference-probe-result-v2.schema.json",
    }
    if not required.issubset(names):
        raise SystemExit("IMAGE_CANDIDATE_CONTRACT_WHEEL_INVALID")
with zipfile.ZipFile(runner) as archive:
    names = set(archive.namelist())
    required = {
        "eom_image_candidate_runner/backend.py",
        "eom_image_candidate_runner/cli.py",
        "eom_image_candidate_runner/runner.py",
        "eom_image_candidate_runner/layout_lock.py",
    }
    if not required.issubset(names):
        raise SystemExit("IMAGE_CANDIDATE_RUNNER_WHEEL_INVALID")
PY
printf 'SOURCE_COMMIT=%s\n' "${head_commit}"
printf 'BUILD_STATE=%s\n' "${state}"
printf 'CONTRACT_WHEEL=%s\n' "${contract_wheel}"
printf 'CONTRACT_WHEEL_SHA256=%s\n' "$(sha256sum "${contract_wheel}" | cut -d' ' -f1)"
printf 'RUNNER_WHEEL=%s\n' "${runner_wheel}"
printf 'RUNNER_WHEEL_SHA256=%s\n' "$(sha256sum "${runner_wheel}" | cut -d' ' -f1)"
