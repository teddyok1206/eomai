#!/usr/bin/env bash
set -euo pipefail

CONFIG=/etc/eom/web-gui.yaml
BACKUP_ROOT=/var/lib/eom-deploy/web-gui-config
PYTHON=/srv/eom/conda/envs/eom-web/bin/python

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail "runtime configuration migration requires root"
[[ -f ${CONFIG} && ! -L ${CONFIG} ]] || fail "runtime configuration is unsafe"
[[ "$(stat -c '%U:%G:%a' "${CONFIG}")" == root:root:644 ]] || \
  fail "runtime configuration metadata mismatch"
[[ -x ${PYTHON} ]] || fail "dedicated Web GUI Python is unavailable"

install -d -o root -g root -m 0700 "${BACKUP_ROOT}"
BACKUP=$(mktemp --tmpdir="${BACKUP_ROOT}" web-gui.yaml.XXXXXXXX)
install -o root -g root -m 0600 "${CONFIG}" "${BACKUP}"
TEMP=$(mktemp --tmpdir=/etc/eom web-gui.yaml.XXXXXXXX)
trap 'rm -f -- "${TEMP}"' EXIT

"${PYTHON}" - "${CONFIG}" "${TEMP}" <<'PY'
from pathlib import Path
import sys

import yaml

source = Path(sys.argv[1])
target = Path(sys.argv[2])
value = yaml.safe_load(source.read_text(encoding="utf-8"))
if not isinstance(value, dict):
    raise SystemExit("runtime configuration must be a mapping")
sessions = value.get("sessions")
if not isinstance(sessions, dict) or sessions.get("cookie_secure") is not True:
    raise SystemExit("public runtime requires secure session cookies")
legacy = value.pop("hwpx", None)
if legacy is not None and legacy != {
    "renderer_key": "kordoc-4.9.0",
    "deployment_state": "PREPARED_NOT_DEPLOYED",
}:
    raise SystemExit("unknown HWPX configuration drift")
target.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
PY

install -o root -g root -m 0644 "${TEMP}" "${CONFIG}"
(
  cd /tmp
  runuser -u eom-web -- env EOM_WEB_GUI_CONFIG="${CONFIG}" "${PYTHON}" -I - <<'PY'
from eom_web_gui.settings import load_settings

settings = load_settings()
if not settings.sessions.cookie_secure:
    raise SystemExit("secure session cookies are not enabled")
if hasattr(settings, "hwpx"):
    raise SystemExit("HWPX capability must not be duplicated in GUI configuration")
print("web_gui_runtime_config=PASS")
PY
)

trap - EXIT
rm -f -- "${TEMP}"
printf 'WEB_GUI_CONFIG_BACKUP=%s\n' "${BACKUP}"
