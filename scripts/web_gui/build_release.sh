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

WHEEL="${WHEEL}" COMMIT="${COMMIT}" VERSION="${VERSION}" "${BUILD_PYTHON}" - <<'PY'
import csv
import io
import json
import os
import zipfile

with zipfile.ZipFile(os.environ["WHEEL"]) as archive:
    names = set(archive.namelist())
    required = {
        "eom_web_gui/__init__.py",
        "eom_web_gui/app.py",
        "eom_web_gui/cli.py",
        "eom_web_gui/gateways.py",
        "eom_web_gui/build-info.json",
        "eom_web_gui/static/index.html",
        "eom_web_gui/static/login.html",
        "eom_web_gui/static/app.js",
        "eom_web_gui/static/curriculum-selector.js",
        "eom_web_gui/static/login.js",
        "eom_web_gui/static/presentation-vocabulary.ko-KR.json",
        "eom_web_gui/static/styles.css",
    }
    if missing := required - names:
        raise SystemExit(f"Web GUI wheel resources missing: {sorted(missing)}")
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
    recorded = {row[0] for row in csv.reader(io.StringIO(archive.read(record_name).decode()))}
    if missing := required - recorded:
        raise SystemExit(f"Web GUI RECORD resources missing: {sorted(missing)}")
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
import importlib.metadata
import json
from importlib.resources import files
from pathlib import Path

import eom_web_gui

module_path = Path(eom_web_gui.__file__).resolve()
if "/home/eom/EOM" in str(module_path):
    raise SystemExit("installed Web GUI imported from source checkout")
distribution = importlib.metadata.distribution("eom-web-gui")
direct_url = distribution.read_text("direct_url.json")
if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
    raise SystemExit("installed Web GUI is editable")
build = json.loads(files("eom_web_gui").joinpath("build-info.json").read_text(encoding="ascii"))
if build["source_commit"] != __import__("os").environ["EXPECTED_COMMIT"]:
    raise SystemExit("installed Web GUI source commit mismatch")
for name in (
    "index.html",
    "login.html",
    "app.js",
    "curriculum-selector.js",
    "login.js",
    "presentation-vocabulary.ko-KR.json",
    "styles.css",
):
    if not files("eom_web_gui").joinpath("static", name).is_file():
        raise SystemExit(f"installed Web GUI static resource missing: {name}")
print("web_gui_installed_simulation=PASS")
PY
)
