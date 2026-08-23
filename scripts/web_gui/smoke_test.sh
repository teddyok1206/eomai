#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${EOM_WEB_GUI_BASE_URL:-http://127.0.0.1:8790}"
[[ "${BASE_URL}" == "http://127.0.0.1:8790" ]] || {
  printf '%s\n' 'ERROR: Web GUI smoke test permits only 127.0.0.1:8790' >&2
  exit 2
}
for attempt in {1..30}; do
  if curl --fail --silent --show-error --max-time 1 \
    "${BASE_URL}/studio/api/v1/health/live" >/dev/null 2>&1 && \
    curl --fail --silent --show-error --max-time 1 \
      "${BASE_URL}/studio/login" >/dev/null 2>&1; then
    printf '%s\n' 'web_gui_smoke=PASS'
    exit 0
  fi
  sleep 0.5
done

printf '%s\n' 'ERROR: Scientific Studio did not become ready within 15 seconds' >&2
exit 1
