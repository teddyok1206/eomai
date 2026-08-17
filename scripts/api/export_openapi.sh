#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="${EOM_API_PYTHON:-/srv/eom/conda/envs/eom-api/bin/python}"
OUTPUT="${1:-${REPOSITORY_ROOT}/api/openapi/eom-api-v1.openapi.json}"

[[ "$(id -un)" == "eom" ]] || {
  printf 'OpenAPI export must run as eom.\n' >&2
  exit 1
}
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || {
  printf 'Repository root mismatch.\n' >&2
  exit 1
}
[[ -x "${PYTHON}" ]] || {
  printf 'The isolated eom-api Python is unavailable.\n' >&2
  exit 1
}

export EOM_API_CONFIG="${REPOSITORY_ROOT}/config/api.example.yaml"
export EOM_API_DATABASE_URL="postgresql+psycopg://contract-export.invalid/eom"
export EOM_API_TOKEN_HASH_KEY="contract-export-token-key-not-a-runtime-secret"
export EOM_API_FINGERPRINT_KEY="contract-export-fingerprint-key-not-a-runtime-secret"

"${PYTHON}" -m eom_api openapi export --output "${OUTPUT}"
