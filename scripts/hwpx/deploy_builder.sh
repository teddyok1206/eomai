#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
PYTHON="/srv/eom/conda/envs/eom-hwpx/bin/python"
MODE="install"

usage() {
  printf 'Usage: %s [--build-only|--install|--verify|--dry-run]\n' "$0"
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
    --dry-run) MODE="dry-run" ;;
    *) usage >&2; exit 2 ;;
  esac
fi

test "$(git -C "$REPOSITORY_ROOT" rev-parse --show-toplevel)" = "$REPOSITORY_ROOT"
test -x "$PYTHON"
COMMIT="$(git -C "$REPOSITORY_ROOT" rev-parse HEAD)"
BUILD_ROOT="/tmp/eom-hwpx-build/$COMMIT"
WHEEL_DIR="$BUILD_ROOT/wheels"
WORK_ROOT=""

cleanup() {
  if [[ -n "$WORK_ROOT" && -d "$WORK_ROOT" ]]; then
    find "$WORK_ROOT" -depth -type f -delete
    find "$WORK_ROOT" -depth -type l -delete
    find "$WORK_ROOT" -depth -type d -empty -delete
  fi
}
trap cleanup EXIT

verify_install() {
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
  "$PYTHON" -m eom_hwpx_builder doctor >/dev/null
}

if [[ "$MODE" = "verify" ]]; then
  verify_install
  exit 0
fi
if [[ "$MODE" = "dry-run" ]]; then
  printf 'Would build commit %s into %s and install only into eom-hwpx.\n' "$COMMIT" "$WHEEL_DIR"
  exit 0
fi

if [[ -n "$(git -C "$REPOSITORY_ROOT" status --porcelain)" ]]; then
  printf 'Working tree must be clean for an HWPX builder release.\n' >&2
  exit 1
fi

mkdir -p "$WHEEL_DIR"
find "$WHEEL_DIR" -mindepth 1 -maxdepth 1 -type f -delete
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
    },
    "eom_hwpx_builder": {
        "eom_hwpx_builder/__init__.py",
        "eom_hwpx_builder/renderer.py",
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
  printf 'Wheels: %s\n' "$WHEEL_DIR"
  exit 0
fi

mapfile -t WHEELS < <(find "$WHEEL_DIR" -maxdepth 1 -type f -name '*.whl' | sort)
PREVIOUS_BUILDER="$($PYTHON -m pip show eom-hwpx-builder 2>/dev/null | awk '/^Version:/{print $2}' || true)"
PREVIOUS_CONTRACTS="$($PYTHON -m pip show eom-hwpx-contracts 2>/dev/null | awk '/^Version:/{print $2}' || true)"
"$PYTHON" -m pip install --no-deps --no-cache-dir --force-reinstall "${WHEELS[@]}"
verify_install
install -d -o eom-hwpx -g eom-hwpx -m 0700 /var/lib/eom-hwpx/deployments
ROLLBACK_FILE="/var/lib/eom-hwpx/deployments/${COMMIT}.json"
"$PYTHON" - "$ROLLBACK_FILE" "$COMMIT" "$PREVIOUS_BUILDER" "$PREVIOUS_CONTRACTS" <<'PY'
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
    "wheel_directory": f"/tmp/eom-hwpx-build/{sys.argv[2]}/wheels",
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
chown eom-hwpx:eom-hwpx "$ROLLBACK_FILE"
printf 'HWPX builder release installed from commit %s.\n' "$COMMIT"
