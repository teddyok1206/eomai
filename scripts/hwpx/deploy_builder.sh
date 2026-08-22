#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="/srv/eom/conda/envs/eom-hwpx/bin/python"
NODE="/srv/eom/conda/envs/eom-hwpx/bin/node"
NPM="/srv/eom/conda/envs/eom-hwpx/bin/npm"
KORDOC_SOURCE="$REPOSITORY_ROOT/services/hwpx_builder/kordoc_runtime"
KORDOC_TARGET="/srv/eom/conda/envs/eom-hwpx/share/eom-kordoc"
PYTHON_LAYOUT_HELPER="$REPOSITORY_ROOT/scripts/hwpx/python_runtime_layout.py"
MODE="install"

usage() {
  printf 'Usage: %s [--build-only|--install|--verify|--normalize-python-layout|--normalize-node-layout|--normalize-node-libraries|--dry-run]\n' "$0"
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  case "$1" in
    --build-only) MODE="build" ;;
    --install) MODE="install" ;;
    --verify) MODE="verify" ;;
    --normalize-python-layout) MODE="normalize-python-layout" ;;
    --normalize-node-layout) MODE="normalize-node-layout" ;;
    --normalize-node-libraries) MODE="normalize-node-libraries" ;;
    --dry-run) MODE="dry-run" ;;
    *) usage >&2; exit 2 ;;
  esac
fi

test "$(git -C "$REPOSITORY_ROOT" rev-parse --show-toplevel)" = "$REPOSITORY_ROOT"
test "$(id -un)" = "eom"
test -x "$PYTHON"
COMMIT="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
BUILD_ROOT=""
WHEEL_DIR=""
WORK_ROOT=""

cleanup() {
  if [[ -n "$WORK_ROOT" && -d "$WORK_ROOT" ]]; then
    find "$WORK_ROOT" -depth -type f -delete
    find "$WORK_ROOT" -depth -type l -delete
    find "$WORK_ROOT" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT

python_layout_roots() {
  "$PYTHON" "$PYTHON_LAYOUT_HELPER" verify
}

verify_python_layout() {
  python_layout_roots >/dev/null
}

normalize_python_layout() {
  "$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize
}

normalize_node_layout() {
  "$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize-node
}

normalize_node_libraries() {
  "$PYTHON" "$PYTHON_LAYOUT_HELPER" normalize-node-libraries
}

verify_install() {
  verify_python_layout
  "$PYTHON" - <<'PY'
import importlib.metadata
from pathlib import Path

import eom_hwpx_builder
import eom_hwpx_contracts

for name in ("eom-hwpx-builder", "eom-hwpx-contracts"):
    distribution = importlib.metadata.distribution(name)
    direct_url = distribution.read_text("direct_url.json") or ""
    if '"editable": true' in direct_url:
        raise SystemExit(f"editable install detected: {name}")
    location = Path(distribution.locate_file("")).resolve()
    for candidate in location.glob("__editable__*eom_hwpx*"):
        raise SystemExit(f"editable finder detected: {candidate.name}")
for module in (eom_hwpx_builder, eom_hwpx_contracts):
    path = Path(module.__file__).resolve()
    if "site-packages" not in path.parts or str(path).startswith("/home/eom/EOM/"):
        raise SystemExit(f"source checkout import detected: {path}")
print("NON_EDITABLE_IMPORT=PASS")
PY
  "$PYTHON" - "$KORDOC_TARGET" "$KORDOC_SOURCE/package-lock.json" <<'PY'
import os
import stat
import sys
from itertools import chain
from pathlib import Path

root = Path(sys.argv[1])
expected_lock = Path(sys.argv[2])
try:
    root_stat = root.lstat()
except OSError as exc:
    raise SystemExit("Kordoc runtime root is unavailable") from exc
if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink():
    raise SystemExit("Kordoc runtime root is unsafe")
for path in chain((root,), root.rglob("*")):
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise SystemExit("Kordoc runtime contains a symbolic link")
    if stat.S_ISDIR(metadata.st_mode):
        expected_mode = 0o755
    elif stat.S_ISREG(metadata.st_mode):
        expected_mode = 0o644
    else:
        raise SystemExit("Kordoc runtime contains a non-file entry")
    if metadata.st_uid != os.getuid() or metadata.st_gid != os.getgid() or stat.S_IMODE(metadata.st_mode) != expected_mode:
        raise SystemExit("Kordoc runtime ownership or mode is invalid")
if (root / "package-lock.json").read_bytes() != expected_lock.read_bytes():
    raise SystemExit("installed Kordoc lock does not match the reviewed source lock")
print("KORDOC_RUNTIME_LAYOUT=PASS")
PY
  "$PYTHON" -m eom_hwpx_builder doctor >/dev/null
  test -x "$NODE"
  test "$($NODE -p 'Number(process.versions.node.split(".")[0]) >= 20')" = true
  test -f "$KORDOC_TARGET/node_modules/kordoc/LICENSE"
  test -f "$KORDOC_TARGET/node_modules/kordoc/NOTICE"
  test -d "$KORDOC_TARGET/node_modules/kordoc/THIRD_PARTY"
  "$PYTHON" -m eom_hwpx_builder kordoc-capabilities >/dev/null
}

if [[ "$MODE" = "verify" ]]; then
  verify_install
  exit 0
fi
if [[ "$MODE" = "normalize-python-layout" ]]; then
  normalize_python_layout
  verify_install
  printf 'HWPX_PYTHON_RUNTIME_LAYOUT=REPAIRED_AND_VERIFIED\n'
  exit 0
fi
if [[ "$MODE" = "normalize-node-layout" ]]; then
  normalize_node_layout
  verify_install
  printf 'HWPX_NODE_RUNTIME_LAYOUT=REPAIRED_AND_VERIFIED\n'
  exit 0
fi
if [[ "$MODE" = "normalize-node-libraries" ]]; then
  normalize_node_libraries
  verify_install
  printf 'HWPX_NODE_SHARED_LIBRARY_LAYOUT=REPAIRED_AND_VERIFIED\n'
  exit 0
fi
if [[ "$MODE" = "dry-run" ]]; then
  printf 'Would build commit %s in a unique protected temporary root with pinned Kordoc runtime and install only into eom-hwpx.\n' "$COMMIT"
  exit 0
fi

if [[ -n "$(git -C "$REPOSITORY_ROOT" status --porcelain)" ]]; then
  printf 'Working tree must be clean for an HWPX builder release.\n' >&2
  exit 1
fi
if [[ "$MODE" = "install" ]] && ! sudo -n true; then
  printf 'HWPX builder installation requires noninteractive operator authorization.\n' >&2
  exit 1
fi

BUILD_ROOT="$(mktemp -d "/tmp/eom-hwpx-build.${COMMIT}.XXXXXXXX")"
WHEEL_DIR="$BUILD_ROOT/wheels"
mkdir -p "$WHEEL_DIR"
test -x "$NODE"
test -x "$NPM"
test "$($NODE -p 'Number(process.versions.node.split(".")[0]) >= 20')" = true
RUNTIME_BUILD="$BUILD_ROOT/kordoc-runtime"
if [[ -d "$RUNTIME_BUILD" ]]; then
  find "$RUNTIME_BUILD" -depth -type f -delete
  find "$RUNTIME_BUILD" -depth -type l -delete
  find "$RUNTIME_BUILD" -depth -type d -empty -delete
fi
mkdir -p "$RUNTIME_BUILD"
cp "$KORDOC_SOURCE/package.json" "$KORDOC_SOURCE/package-lock.json" "$RUNTIME_BUILD/"
"$NODE" "$NPM" ci --omit=optional --ignore-scripts --no-audit --no-fund \
  --prefix "$RUNTIME_BUILD"
if [[ -d "$RUNTIME_BUILD/node_modules/.bin" ]]; then
  find "$RUNTIME_BUILD/node_modules/.bin" -type l -delete
  rmdir "$RUNTIME_BUILD/node_modules/.bin"
fi
if find "$RUNTIME_BUILD" -type l -print -quit | grep -q .; then
  printf 'Kordoc runtime contains an unexpected symbolic link.\n' >&2
  exit 1
fi
test -f "$RUNTIME_BUILD/node_modules/kordoc/LICENSE"
test -f "$RUNTIME_BUILD/node_modules/kordoc/NOTICE"
test -d "$RUNTIME_BUILD/node_modules/kordoc/THIRD_PARTY"
EOM_KORDOC_RUNTIME="$RUNTIME_BUILD" "$NODE" - <<'JS'
const runtime = process.env.EOM_KORDOC_RUNTIME
const manifest = require(`${runtime}/node_modules/kordoc/package.json`)
if (manifest.version !== "4.9.0") process.exit(1)
JS
WORK_ROOT="$(mktemp -d /tmp/eom-hwpx-wheel-source.XXXXXX)"
mkdir -p "$WORK_ROOT/contracts" "$WORK_ROOT/builder"
cp -a "$REPOSITORY_ROOT/packages/hwpx_contracts/." "$WORK_ROOT/contracts/"
cp -a "$REPOSITORY_ROOT/services/hwpx_builder/." "$WORK_ROOT/builder/"
find "$WORK_ROOT" -depth \
  \( -path '*/build/*' -o -name build -o -path '*/*.egg-info/*' -o -name '*.egg-info' \
     -o -path '*/__pycache__/*' -o -name __pycache__ \) -delete
"$PYTHON" -m build --wheel --no-isolation \
  --outdir "$WHEEL_DIR" "$WORK_ROOT/contracts"
"$PYTHON" -m build --wheel --no-isolation \
  --outdir "$WHEEL_DIR" "$WORK_ROOT/builder"

"$PYTHON" - "$WHEEL_DIR" <<'PY'
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
wheels = sorted(root.glob("*.whl"))
if len(wheels) != 2:
    raise SystemExit("expected exactly two wheels")
required = {
    "eom_hwpx_contracts": {
        "eom_hwpx_contracts/__init__.py",
        "eom_hwpx_contracts/schemas/hwpx-item-document-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-kordoc-render-request-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-kordoc-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-manager-download-v1.schema.json",
    },
    "eom_hwpx_builder": {
        "eom_hwpx_builder/__init__.py",
        "eom_hwpx_builder/renderer.py",
        "eom_hwpx_builder/kordoc_bridge.mjs",
        "eom_hwpx_builder/kordoc_renderer.py",
        "eom_hwpx_builder/kordoc_runtime.py",
    },
}
for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    package = next((name for name in required if name in wheel.name), None)
    if package is None or not required[package].issubset(names):
        raise SystemExit(f"wheel content inspection failed: {wheel.name}")
    if not any(name.endswith("entry_points.txt") for name in names) and package == "eom_hwpx_builder":
        raise SystemExit("builder console entry point is missing")
print("WHEEL_CONTENT=PASS")
PY

if [[ "$MODE" = "build" ]]; then
  printf 'Wheels: %s\nKordoc runtime: %s\n' "$WHEEL_DIR" "$RUNTIME_BUILD"
  exit 0
fi

mapfile -t WHEELS < <(find "$WHEEL_DIR" -maxdepth 1 -type f -name '*.whl' | sort)
PREVIOUS_BUILDER="$($PYTHON -m pip show eom-hwpx-builder 2>/dev/null | awk '/^Version:/{print $2}' || true)"
PREVIOUS_CONTRACTS="$($PYTHON -m pip show eom-hwpx-contracts 2>/dev/null | awk '/^Version:/{print $2}' || true)"
"$PYTHON" -m pip install --no-deps --no-cache-dir --force-reinstall "${WHEELS[@]}"
normalize_python_layout
KORDOC_STAGE="${KORDOC_TARGET}.stage-${COMMIT}"
KORDOC_PREVIOUS="${KORDOC_TARGET}.previous-${COMMIT}"
KORDOC_FAILED="${KORDOC_TARGET}.failed-${COMMIT}"
test ! -e "$KORDOC_STAGE"
test ! -e "$KORDOC_PREVIOUS"
test ! -e "$KORDOC_FAILED"
mkdir -p "$KORDOC_STAGE"
cp -a "$RUNTIME_BUILD/." "$KORDOC_STAGE/"
find "$KORDOC_STAGE" -type d -exec chmod 0755 {} +
find "$KORDOC_STAGE" -type f -exec chmod 0644 {} +
if [[ -e "$KORDOC_TARGET" ]]; then
  mv "$KORDOC_TARGET" "$KORDOC_PREVIOUS"
fi
mv "$KORDOC_STAGE" "$KORDOC_TARGET"
if ! verify_install; then
  mv "$KORDOC_TARGET" "$KORDOC_FAILED"
  if [[ -e "$KORDOC_PREVIOUS" ]]; then
    mv "$KORDOC_PREVIOUS" "$KORDOC_TARGET"
  fi
  printf 'HWPX builder verification failed; Kordoc runtime evidence was preserved.\n' >&2
  exit 1
fi
sudo -n install -d -o eom-hwpx -g eom-hwpx -m 0700 /var/lib/eom-hwpx/deployments
ROLLBACK_FILE="/var/lib/eom-hwpx/deployments/${COMMIT}.json"
ROLLBACK_TEMP="$BUILD_ROOT/deployment-record.json"
"$PYTHON" - "$ROLLBACK_TEMP" "$COMMIT" "$PREVIOUS_BUILDER" "$PREVIOUS_CONTRACTS" "$WHEEL_DIR" <<'PY'
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

path = Path(sys.argv[1])
value = {
    "source_commit": sys.argv[2],
    "previous_builder_version": sys.argv[3] or None,
    "previous_contracts_version": sys.argv[4] or None,
    "installed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "wheel_directory": sys.argv[5],
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
sudo -n install -o eom-hwpx -g eom-hwpx -m 0600 "$ROLLBACK_TEMP" "$ROLLBACK_FILE"
printf 'HWPX builder release installed from commit %s.\n' "$COMMIT"
