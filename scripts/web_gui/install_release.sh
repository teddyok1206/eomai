#!/usr/bin/env bash
set -euo pipefail

WEB_PYTHON="/srv/eom/conda/envs/eom-web/bin/python"
WEB_ENTRY="/srv/eom/conda/envs/eom-web/bin/eom-web-gui"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" -eq 0 ]] || fail "installation requires the reviewed privileged operator context"
[[ "$#" -eq 3 ]] || fail "usage: install_release.sh WHEEL EXPECTED_SHA256 EXPECTED_COMMIT"
WHEEL="$1"
EXPECTED_SHA256="$2"
EXPECTED_COMMIT="$3"

[[ "${WHEEL}" == /tmp/eom-web-gui-build/*/dist/eom_web_gui-0.1.0-py3-none-any.whl ]] || \
  fail "wheel path is outside the fixed build root"
[[ -f "${WHEEL}" && ! -L "${WHEEL}" ]] || fail "wheel must be a regular non-symlink file"
[[ "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid wheel SHA-256"
[[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "invalid expected source commit"
[[ "$(sha256sum "${WHEEL}" | awk '{print $1}')" == "${EXPECTED_SHA256}" ]] || \
  fail "wheel SHA-256 mismatch"
[[ -x "${WEB_PYTHON}" ]] || fail "dedicated eom-web Python is unavailable"

umask 0077
"${WEB_PYTHON}" -m pip install --no-deps --force-reinstall "${WHEEL}" >/dev/null

mapfile -t INSTALLED_PATHS < <("${WEB_PYTHON}" - <<'PY'
import importlib.metadata
from pathlib import Path

import eom_web_gui

site_root = Path(eom_web_gui.__file__).resolve().parent
distribution = importlib.metadata.distribution("eom-web-gui")
metadata_files = {
    Path(distribution.locate_file(entry)).resolve()
    for entry in distribution.files or ()
    if entry.name == "METADATA" and entry.parent.name.endswith(".dist-info")
}
dist_info_roots = {entry.parent for entry in metadata_files}
if len(dist_info_roots) != 1:
    raise SystemExit("installed distribution metadata root is not unique")
print(site_root)
print(dist_info_roots.pop())
PY
)
[[ "${#INSTALLED_PATHS[@]}" -eq 2 ]] || fail "installed path discovery mismatch"
SITE_ROOT="${INSTALLED_PATHS[0]}"
DIST_INFO_ROOT="${INSTALLED_PATHS[1]}"
[[ "${SITE_ROOT}" == /srv/eom/conda/envs/eom-web/lib/python3.12/site-packages/eom_web_gui ]] || \
  fail "installed package path mismatch"
[[ "${DIST_INFO_ROOT}" == \
  /srv/eom/conda/envs/eom-web/lib/python3.12/site-packages/eom_web_gui-0.1.0.dist-info ]] || \
  fail "installed distribution metadata path mismatch"
[[ -d "${SITE_ROOT}" && ! -L "${SITE_ROOT}" ]] || fail "installed package root is unsafe"
[[ -d "${DIST_INFO_ROOT}" && ! -L "${DIST_INFO_ROOT}" ]] || \
  fail "installed distribution metadata root is unsafe"
[[ -z "$(find "${SITE_ROOT}" "${DIST_INFO_ROOT}" -xdev -type l -print -quit)" ]] || \
  fail "installed distribution contains a symlink"

find "${SITE_ROOT}" -type d -exec chmod 0755 {} +
find "${SITE_ROOT}" -type f -exec chmod 0644 {} +
find "${DIST_INFO_ROOT}" -type d -exec chmod 0755 {} +
find "${DIST_INFO_ROOT}" -type f -exec chmod 0644 {} +
chmod 0755 "${WEB_ENTRY}"

(
cd /tmp
runuser -u eom-web -- env EXPECTED_COMMIT="${EXPECTED_COMMIT}" "${WEB_PYTHON}" - <<'PY'
import importlib.metadata
import json
import os
from importlib.resources import files
from pathlib import Path

import eom_web_gui

module = Path(eom_web_gui.__file__).resolve()
if "/home/eom/EOM" in str(module):
    raise SystemExit("installed package depends on the source checkout")
distribution = importlib.metadata.distribution("eom-web-gui")
if distribution.metadata["Name"] != "eom-web-gui" or distribution.version != "0.1.0":
    raise SystemExit("installed distribution metadata mismatch")
direct_url = distribution.read_text("direct_url.json")
if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
    raise SystemExit("installed package is editable")
build = json.loads(files("eom_web_gui").joinpath("build-info.json").read_text(encoding="ascii"))
if build["source_commit"] != os.environ["EXPECTED_COMMIT"]:
    raise SystemExit("installed source commit mismatch")
print("web_gui_service_identity_metadata=PASS")
PY
)

printf '%s\n' 'web_gui_install=PASS'
