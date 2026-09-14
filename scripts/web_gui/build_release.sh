#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCHES=("main" "feat/web-gui-v0" "feat/hwpx-application-api-v0")
BUILD_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -un)" == "eom" ]] || fail "release builds must run as eom"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
CURRENT_BRANCH="$(git -C "${REPOSITORY_ROOT}" branch --show-current)"
branch_allowed=false
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${CURRENT_BRANCH}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"
[[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
  fail "working tree must be clean before release build"
[[ -x "${BUILD_PYTHON}" ]] || fail "explicit Python 3.12 build environment is unavailable"

COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
VERSION="$(PYPROJECT="${REPOSITORY_ROOT}/apps/web_gui/pyproject.toml" ${BUILD_PYTHON} -c \
  'import os,pathlib,tomllib; print(tomllib.loads(pathlib.Path(os.environ["PYPROJECT"]).read_text())["project"]["version"])')"
BUILD_PARENT="/tmp/eom-web-gui-build"
mkdir -p "${BUILD_PARENT}"
BUILD_ROOT="$(mktemp -d "${BUILD_PARENT}/${COMMIT}.XXXXXX")"
STAGING="${BUILD_ROOT}/staging"
DIST="${BUILD_ROOT}/dist"
WHEEL="${DIST}/eom_web_gui-${VERSION}-py3-none-any.whl"

mkdir -p "${STAGING}/eom_web_gui" "${DIST}"
cp "${REPOSITORY_ROOT}/apps/web_gui/pyproject.toml" "${STAGING}/pyproject.toml"
rsync -a --exclude='__pycache__' \
  "${REPOSITORY_ROOT}/apps/web_gui/eom_web_gui/" "${STAGING}/eom_web_gui/"

BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
COMMIT="${COMMIT}" VERSION="${VERSION}" STAGING="${STAGING}" "${BUILD_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

target = Path(os.environ["STAGING"]) / "eom_web_gui" / "build-info.json"
target.write_text(
    json.dumps(
        {
            "build_timestamp_utc": os.environ["BUILD_TIMESTAMP"],
            "package_version": os.environ["VERSION"],
            "source_commit": os.environ["COMMIT"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="ascii",
)
PY

"${BUILD_PYTHON}" -m pip wheel \
  --no-deps --no-build-isolation --wheel-dir "${DIST}" "${STAGING}" >/dev/null
[[ -f "${WHEEL}" ]] || fail "expected Web GUI wheel was not produced"

WHEEL="${WHEEL}" COMMIT="${COMMIT}" VERSION="${VERSION}" STAGING="${STAGING}" \
  "${BUILD_PYTHON}" - <<'PY'
import base64
import csv
import hashlib
import io
import importlib.util
import json
import os
import sys
import zipfile

module_path = os.path.join(os.environ["STAGING"], "eom_web_gui", "release_integrity.py")
spec = importlib.util.spec_from_file_location("eom_web_release_integrity", module_path)
if spec is None or spec.loader is None:
    raise SystemExit("Web GUI release-integrity module cannot be loaded")
integrity = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = integrity
spec.loader.exec_module(integrity)

with zipfile.ZipFile(os.environ["WHEEL"]) as archive:
    names = set(archive.namelist())
    required = {f"eom_web_gui/{name}" for name in integrity.REQUIRED_RUNTIME_FILES}
    packaged = {
        name for name in names if name.startswith("eom_web_gui/") and not name.endswith("/")
    }
    if packaged != required:
        raise SystemExit(
            "Web GUI wheel package inventory mismatch: "
            f"missing={sorted(required - packaged)}, unknown={sorted(packaged - required)}"
        )
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    if "eom-web-gui = eom_web_gui.cli:main" not in archive.read(entry_points).decode():
        raise SystemExit("Web GUI console entry point missing")
    build = json.loads(archive.read("eom_web_gui/build-info.json"))
    if build != {
        "build_timestamp_utc": build["build_timestamp_utc"],
        "package_version": os.environ["VERSION"],
        "source_commit": os.environ["COMMIT"],
    }:
        raise SystemExit("Web GUI build metadata mismatch")
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    recorded = {row[0]: row[1:] for row in csv.reader(io.StringIO(archive.read(record_name).decode()))}
    if missing := required - set(recorded):
        raise SystemExit(f"Web GUI RECORD resources missing: {sorted(missing)}")
    for name in required:
        encoded_hash, encoded_size = recorded[name]
        expected_hash = "sha256=" + base64.urlsafe_b64encode(
            hashlib.sha256(archive.read(name)).digest()
        ).decode().rstrip("=")
        if encoded_hash != expected_hash or encoded_size != str(archive.getinfo(name).file_size):
            raise SystemExit(f"Web GUI RECORD descriptor mismatch: {name}")
    forbidden = (b"__editable__", b"/home/eom/EOM", b"from kordoc", b"import kordoc")
    for name in names:
        if name.endswith((".py", ".js", ".html", ".json", ".pth")):
            content = archive.read(name)
            if any(marker in content for marker in forbidden):
                raise SystemExit(f"forbidden runtime/source dependency in {name}")
print("web_gui_release_artifact=PASS")
PY

printf 'web_gui_source_commit=%s\n' "${COMMIT}"
printf 'web_gui_wheel=%s\n' "${WHEEL}"
printf 'web_gui_wheel_sha256=%s\n' "$(sha256sum "${WHEEL}" | awk '{print $1}')"

INSTALL_ROOT="${BUILD_ROOT}/installed"
"${BUILD_PYTHON}" -m venv --system-site-packages "${INSTALL_ROOT}"
"${INSTALL_ROOT}/bin/python" -m pip install --no-deps --force-reinstall "${WHEEL}" >/dev/null
(
  cd /tmp
  EXPECTED_COMMIT="${COMMIT}" "${INSTALL_ROOT}/bin/python" - <<'PY'
from pathlib import Path

import eom_web_gui
from eom_web_gui.release_integrity import verify_installed_web_gui

module_path = Path(eom_web_gui.__file__).resolve()
if "/home/eom/EOM" in str(module_path):
    raise SystemExit("installed Web GUI imported from source checkout")
result = verify_installed_web_gui(expected_commit=__import__("os").environ["EXPECTED_COMMIT"])
print(f"web_gui_installed_simulation=PASS verified_files={result.verified_file_count}")
PY
)
