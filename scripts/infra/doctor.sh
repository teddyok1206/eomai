#!/usr/bin/env bash
set -euo pipefail

PYTHON="${EOM_CORE_PYTHON:-/srv/eom/conda/envs/eom-core/bin/python}"
SCRIPT="/home/eom/EOM/scripts/infra/doctor.py"
ORCHESTRATOR_SOURCE="/home/eom/EOM/services/orchestrator"

[[ -x "${PYTHON}" ]] || {
  printf 'FAIL CORE_PYTHON_MISSING isolated eom-core Python is unavailable\n' >&2
  exit 1
}

export PYTHONPATH="${ORCHESTRATOR_SOURCE}${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON}" "${SCRIPT}" "$@"
