#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
CONDA="/home/eom/miniconda3/bin/conda"
ENVIRONMENT_PREFIX="/srv/eom/conda/envs/eom-image-test"
ENVIRONMENT_FILE="${REPOSITORY_ROOT}/infra/conda/eom-image-test.environment.yml"
REQUIREMENTS_FILE="${REPOSITORY_ROOT}/infra/conda/eom-image-test.requirements.lock"

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[[ "${EUID}" -ne 0 ]] || fail "image test environment must not be provisioned as root"
[[ -x "${CONDA}" ]] || fail "Conda executable is unavailable"
[[ -f "${ENVIRONMENT_FILE}" ]] || fail "image test Conda definition is unavailable"
[[ -f "${REQUIREMENTS_FILE}" ]] || fail "image test requirement lock is unavailable"

if [[ -e "${ENVIRONMENT_PREFIX}" && ! -d "${ENVIRONMENT_PREFIX}" ]]; then
  fail "image test environment path is not a directory"
fi
if [[ -L "${ENVIRONMENT_PREFIX}" ]]; then
  fail "image test environment path must not be a symlink"
fi

if [[ ! -x "${ENVIRONMENT_PREFIX}/bin/python" ]]; then
  "${CONDA}" env create --yes --prefix "${ENVIRONMENT_PREFIX}" --file "${ENVIRONMENT_FILE}"
fi

PYTHONNOUSERSITE=1 "${ENVIRONMENT_PREFIX}/bin/python" -m pip install \
  --disable-pip-version-check \
  --requirement "${REQUIREMENTS_FILE}"

PYTHONNOUSERSITE=1 "${ENVIRONMENT_PREFIX}/bin/python" - <<'PY'
import importlib.metadata
import platform

expected = {
    "numpy": "2.4.6",
    "pillow": "12.3.0",
    "pydantic": "2.13.4",
    "pytest": "8.4.2",
}
assert platform.python_version() == "3.12.13", platform.python_version()
for distribution, version in expected.items():
    assert importlib.metadata.version(distribution) == version
import numpy  # noqa: F401
from PIL import Image  # noqa: F401

print("image_test_environment=READY")
PY
