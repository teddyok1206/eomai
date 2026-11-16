#!/usr/bin/env bash
set -euo pipefail

WEB_PYTHON="/srv/eom/conda/envs/eom-web/bin/python"
WEB_ENTRY="/srv/eom/conda/envs/eom-web/bin/eom-web-gui"
SCRIPT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_ROOT="$(cd -- "${SCRIPT_ROOT}/../.." && pwd -P)"
CLOSURE_HELPER="${SCRIPT_ROOT}/wheel_closure.py"
RUNTIME_LOCK="${SOURCE_ROOT}/infra/conda/eom-web.requirements.lock"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

verify_protected_member() {
  local member="$1" expected_sha="$2" current="$1" metadata
  [[ -f "${member}" && ! -L "${member}" ]] || fail "protected release member is unsafe"
  [[ "$(/usr/bin/stat -c %h -- "${member}")" == 1 ]] || fail "protected release member is linked"
  while :; do
    [[ -e "${current}" && ! -L "${current}" ]] || fail "protected release ancestor is unsafe"
    metadata="$(/usr/bin/stat -c '%u %a' -- "${current}")"
    [[ "${metadata%% *}" == 0 ]] && (( (8#${metadata##* } & 8#022) == 0 )) || \
      fail "release source must be a root-protected snapshot"
    [[ "${current}" != / ]] || break
    current="$(/usr/bin/dirname -- "${current}")"
  done
  if [[ -n "${expected_sha}" ]]; then
    [[ "${expected_sha}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid release member SHA-256"
    [[ "$(/usr/bin/sha256sum -- "${member}" | /usr/bin/cut -d ' ' -f 1)" == "${expected_sha}" ]] || \
      fail "protected release member SHA-256 mismatch"
  fi
}

[[ "$(id -u)" -eq 0 ]] || fail "installation requires the reviewed privileged operator context"
[[ "$#" -eq 6 ]] || \
  fail "usage: install_release.sh WHEEL EXPECTED_SHA256 EXPECTED_COMMIT EXPECTED_CLOSURE_SHA256 HELPER_SHA256 PINS_SHA256"
WHEEL="$1"
EXPECTED_SHA256="$2"
EXPECTED_COMMIT="$3"
EXPECTED_CLOSURE_SHA256="$4"
EXPECTED_HELPER_SHA256="$5"
EXPECTED_PINS_SHA256="$6"

# The operator verifies this script before Bash executes it. Its source tree, helper and exact
# dependency pins must then remain protected; directly executing a mutable checkout is forbidden.
verify_protected_member "${SCRIPT_ROOT}/install_release.sh" ""
verify_protected_member "${CLOSURE_HELPER}" "${EXPECTED_HELPER_SHA256}"
verify_protected_member "${RUNTIME_LOCK}" "${EXPECTED_PINS_SHA256}"

[[ "${WHEEL}" == /tmp/eom-web-gui-build/*/dist/eom_web_gui-0.1.0-py3-none-any.whl ]] || \
  fail "wheel path is outside the fixed build root"
[[ -f "${WHEEL}" && ! -L "${WHEEL}" ]] || fail "wheel must be a regular non-symlink file"
[[ "${EXPECTED_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid wheel SHA-256"
[[ "${EXPECTED_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || fail "invalid expected source commit"
[[ "${EXPECTED_CLOSURE_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail "invalid closure SHA-256"
[[ "$(sha256sum "${WHEEL}" | awk '{print $1}')" == "${EXPECTED_SHA256}" ]] || \
  fail "wheel SHA-256 mismatch"
[[ -x "${WEB_PYTHON}" ]] || fail "dedicated eom-web Python is unavailable"

umask 0077
PROTECTED_ROOT="$(mktemp -d /tmp/eom-web-install.XXXXXXXX)"
"${WEB_PYTHON}" -I "${CLOSURE_HELPER}" stage \
  --pins "${RUNTIME_LOCK}" --directory "$(dirname -- "${WHEEL}")" \
  --destination "${PROTECTED_ROOT}" --lock-sha256 "${EXPECTED_CLOSURE_SHA256}" \
  --web-sha256 "${EXPECTED_SHA256}" --commit "${EXPECTED_COMMIT}"

# All dependency resolution/import failures occur in this private throwaway environment first.
# A missing wheel must never trigger live network installation or reuse the API build environment.
"${WEB_PYTHON}" -m venv "${PROTECTED_ROOT}/preflight"
"${PROTECTED_ROOT}/preflight/bin/python" -m pip --isolated --disable-pip-version-check install \
  --no-index --only-binary=:all: --require-hashes --find-links "${PROTECTED_ROOT}" \
  --requirement "${PROTECTED_ROOT}/release.requirements.lock" >/dev/null
"${PROTECTED_ROOT}/preflight/bin/python" -m pip --isolated --disable-pip-version-check check
EXPECTED_COMMIT="${EXPECTED_COMMIT}" "${PROTECTED_ROOT}/preflight/bin/python" -I - <<'PY'
import os
from eom_web_gui.app import create_app
from eom_web_gui.release_integrity import verify_installed_web_gui
from eom_kakao_archive_contracts.kakao_remote import validate_remote_transport

assert callable(create_app) and callable(validate_remote_transport)
verify_installed_web_gui(expected_commit=os.environ["EXPECTED_COMMIT"])
print("web_gui_offline_preflight=PASS")
PY

# Staging stays root-private; installed distribution files must be readable by eom-web.
umask 0022
"${WEB_PYTHON}" -m pip --isolated --disable-pip-version-check install \
  --no-index --only-binary=:all: --require-hashes --force-reinstall \
  --find-links "${PROTECTED_ROOT}" --requirement "${PROTECTED_ROOT}/release.requirements.lock" >/dev/null
"${WEB_PYTHON}" -m pip --isolated --disable-pip-version-check check

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
import os
from pathlib import Path

import eom_web_gui
from eom_web_gui.app import create_app
from eom_web_gui.release_integrity import verify_installed_web_gui
from eom_kakao_archive_contracts.kakao_remote import validate_remote_transport

module = Path(eom_web_gui.__file__).resolve()
if "/home/eom/EOM" in str(module):
    raise SystemExit("installed package depends on the source checkout")
result = verify_installed_web_gui(expected_commit=os.environ["EXPECTED_COMMIT"])
assert callable(create_app) and callable(validate_remote_transport)
print(f"web_gui_service_identity_metadata=PASS verified_files={result.verified_file_count}")
PY
)

printf '%s\n' 'web_gui_install=PASS'
printf 'web_gui_protected_closure=%s\n' "${PROTECTED_ROOT}"
