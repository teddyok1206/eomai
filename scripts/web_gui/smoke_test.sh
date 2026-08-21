#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${EOM_WEB_GUI_BASE_URL:-http://127.0.0.1:8790}"
[[ "${BASE_URL}" == "http://127.0.0.1:8790" ]] || {
  printf '%s\n' 'ERROR: Web GUI smoke test permits only 127.0.0.1:8790' >&2
  exit 2
}
curl --fail --silent --show-error --max-time 3 \
  "${BASE_URL}/studio/api/v1/health/live" >/dev/null
curl --fail --silent --show-error --max-time 3 \
  "${BASE_URL}/studio/login" >/dev/null
printf '%s\n' 'web_gui_smoke=PASS'
