#!/usr/bin/env bash
set -euo pipefail

CANONICAL_REPOSITORY_ROOT="/home/eom/EOM"
REPOSITORY_ROOT="$CANONICAL_REPOSITORY_ROOT"
PYTHON="/srv/eom/conda/envs/eom-hwpx/bin/python"
NODE="/srv/eom/conda/envs/eom-hwpx/bin/node"
NPM="/srv/eom/conda/envs/eom-hwpx/bin/npm"
KORDOC_TARGET="/srv/eom/conda/envs/eom-hwpx/share/eom-kordoc"
MODE="install"
MODE_SELECTED=false
SOURCE_SELECTED=false

usage() {
  printf 'Usage: %s [--build-only|--install|--verify|--normalize-python-layout|--normalize-node-layout|--normalize-node-libraries|--dry-run] [--source-root PATH]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      if [[ "$SOURCE_SELECTED" = true || $# -lt 2 ]]; then
        usage >&2
        exit 2
      fi
      REPOSITORY_ROOT="$2"
      SOURCE_SELECTED=true
      shift 2
      ;;
    --build-only|--install|--verify|--normalize-python-layout|--normalize-node-layout|--normalize-node-libraries|--dry-run)
      if [[ "$MODE_SELECTED" = true ]]; then
        usage >&2
        exit 2
      fi
      MODE_SELECTED=true
      case "$1" in
        --build-only) MODE="build" ;;
        --install) MODE="install" ;;
        --verify) MODE="verify" ;;
        --normalize-python-layout) MODE="normalize-python-layout" ;;
        --normalize-node-layout) MODE="normalize-node-layout" ;;
        --normalize-node-libraries) MODE="normalize-node-libraries" ;;
        --dry-run) MODE="dry-run" ;;
      esac
      shift
      ;;
    *) usage >&2; exit 2 ;;
  esac
done

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

# An inherited Git selector must not replace either repository identity.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
unset GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES

validate_source_root() {
  [[ "$REPOSITORY_ROOT" = /* && "$REPOSITORY_ROOT" != / ]] || \
    fail 'HWPX source root must be an absolute non-root directory.'
  [[ ! "$REPOSITORY_ROOT" =~ [[:cntrl:]] ]] || fail 'HWPX source root contains control characters.'
  [[ -d "$REPOSITORY_ROOT" && ! -L "$REPOSITORY_ROOT" ]] || fail 'HWPX source root is unsafe.'
  [[ "$(realpath -e -- "$REPOSITORY_ROOT")" = "$REPOSITORY_ROOT" ]] || \
    fail 'HWPX source root must be canonical and contain no symbolic links.'
  [[ "$(stat -c '%U' -- "$REPOSITORY_ROOT")" = eom ]] || fail 'HWPX source root must be owned by eom.'
  [[ "$(id -un)" = eom ]] || fail 'HWPX deployment must run as eom.'
  [[ "$(git -C "$REPOSITORY_ROOT" rev-parse --show-toplevel)" = "$REPOSITORY_ROOT" ]] || \
    fail 'HWPX source root must be an exact Git worktree root.'
  local expected_common selected_common
  expected_common="$(git -C "$CANONICAL_REPOSITORY_ROOT" rev-parse --path-format=absolute --git-common-dir)"
  selected_common="$(git -C "$REPOSITORY_ROOT" rev-parse --path-format=absolute --git-common-dir)"
  [[ "$(realpath -e -- "$selected_common")" = "$(realpath -e -- "$expected_common")" ]] || \
    fail 'HWPX source worktree must belong to the canonical EOM repository.'
  COMMIT="$(git -C "$REPOSITORY_ROOT" rev-parse --verify 'HEAD^{commit}')"
  [[ "$COMMIT" =~ ^[a-f0-9]{40}$ ]] || fail 'HWPX source commit must be a full 40-character SHA.'
  if [[ "$MODE" = install || "$MODE" = build || "$MODE" = dry-run || "$SOURCE_SELECTED" = true ]]; then
    [[ -z "$(git -C "$REPOSITORY_ROOT" status --porcelain --untracked-files=all)" ]] || \
      fail 'Working tree must be clean for an HWPX builder release.'
  fi
}

validate_source_root
test -x "$PYTHON"
KORDOC_SOURCE="$REPOSITORY_ROOT/services/hwpx_builder/kordoc_runtime"
PYTHON_LAYOUT_HELPER="$REPOSITORY_ROOT/scripts/hwpx/python_runtime_layout.py"
VERIFY_SOURCE_ROOT="$REPOSITORY_ROOT"
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
  "$PYTHON" - "$VERIFY_SOURCE_ROOT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

import eom_hwpx_builder
import eom_hwpx_contracts
from eom_hwpx_builder.cli import CONTENT_TEAM_EXAM_REQUEST_SCHEMA_VERSIONS
from eom_hwpx_builder.content_team_exam_renderer import EXAM_RENDERER_VERSION_V3
from eom_hwpx_contracts import ContentTeamExamRenderRequestV3

repository = Path(sys.argv[1]).resolve()
installed_builder = Path(eom_hwpx_builder.__file__).resolve().parent
installed_contracts = Path(eom_hwpx_contracts.__file__).resolve().parent
source_pairs = (
    (installed_builder / "cli.py", repository / "services/hwpx_builder/eom_hwpx_builder/cli.py"),
    (
        installed_builder / "content_team_renderer.py",
        repository / "services/hwpx_builder/eom_hwpx_builder/content_team_renderer.py",
    ),
    (
        installed_builder / "content_team_exam_renderer.py",
        repository / "services/hwpx_builder/eom_hwpx_builder/content_team_exam_renderer.py",
    ),
    (
        installed_contracts / "models.py",
        repository / "packages/hwpx_contracts/eom_hwpx_contracts/models.py",
    ),
    (
        installed_contracts / "__init__.py",
        repository / "packages/hwpx_contracts/eom_hwpx_contracts/__init__.py",
    ),
    (
        installed_builder / "content_team_images.py",
        repository / "services/hwpx_builder/eom_hwpx_builder/content_team_images.py",
    ),
    (
        installed_builder / "reference.py",
        repository / "services/hwpx_builder/eom_hwpx_builder/reference.py",
    ),
    (
        installed_contracts / "picture_geometry.py",
        repository / "packages/hwpx_contracts/eom_hwpx_contracts/picture_geometry.py",
    ),
    (
        installed_contracts / "schemas/hwpx-content-team-exam-render-request-v3.schema.json",
        repository / "schemas/hwpx/hwpx-content-team-exam-render-request-v3.schema.json",
    ),
    (
        installed_contracts / "schemas/hwpx-content-team-exam-build-result-v3.schema.json",
        repository / "schemas/hwpx/hwpx-content-team-exam-build-result-v3.schema.json",
    ),
)
for installed, source in source_pairs:
    if installed.read_bytes() != source.read_bytes():
        raise SystemExit(f"installed HWPX V3 source drift: {installed.name}")
schema_payload = {
    "content-team-exam-render-request-v3": source_pairs[-2][0].read_text(encoding="utf-8"),
    "content-team-exam-build-result-v3": source_pairs[-1][0].read_text(encoding="utf-8"),
}
schema_bundle_hash = "sha256:" + hashlib.sha256(
    json.dumps(
        schema_payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()
if schema_bundle_hash != (
    "sha256:43b7659bb96845f97fc2c29f5b26eaf561b4ba36ed0a1ee811088aa7cd9675a8"
):
    raise SystemExit("installed HWPX V3 schema bundle mismatch")
if CONTENT_TEAM_EXAM_REQUEST_SCHEMA_VERSIONS != {
    "content-team-exam-render-request/1.0",
    "content-team-exam-render-request/2.0",
    "content-team-exam-render-request/3.0",
}:
    raise SystemExit("installed HWPX CLI request-family admission mismatch")
if (
    ContentTeamExamRenderRequestV3.model_fields["schema_version"].default
    != "content-team-exam-render-request/3.0"
    or EXAM_RENDERER_VERSION_V3 != "3.0.0"
):
    raise SystemExit("installed HWPX V3 renderer profile mismatch")
print("CONTENT_TEAM_EXAM_V3_RUNTIME=READY")
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
  test "$($NODE -p 'Number(process.versions.node.split(".")[0]) === 22')" = true
  test -f "$KORDOC_TARGET/node_modules/kordoc/LICENSE"
  test -f "$KORDOC_TARGET/node_modules/kordoc/NOTICE"
  test -d "$KORDOC_TARGET/node_modules/kordoc/THIRD_PARTY"
  "$PYTHON" -m eom_hwpx_builder kordoc-capabilities >/dev/null
}

# Legacy verification/normalization compares the selected checkout, not release evidence.
# Only build/install below materializes the immutable commit for installation and verification.
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

if [[ "$MODE" = "install" ]] && ! sudo -n true; then
  printf 'HWPX builder installation requires noninteractive operator authorization.\n' >&2
  exit 1
fi

BUILD_ROOT="$(mktemp -d "/tmp/eom-hwpx-build.${COMMIT}.XXXXXXXX")"
WHEEL_DIR="$BUILD_ROOT/wheels"
mkdir -p "$WHEEL_DIR"
# Materialize only the pinned commit, not ignored files or a changing checkout.
WORK_ROOT="$(mktemp -d /tmp/eom-hwpx-wheel-source.XXXXXX)"
git -C "$REPOSITORY_ROOT" archive --format=tar "$COMMIT" \
  packages/hwpx_contracts services/hwpx_builder schemas/hwpx \
  scripts/hwpx/python_runtime_layout.py | tar --extract --directory="$WORK_ROOT" --no-same-owner
VERIFY_SOURCE_ROOT="$WORK_ROOT"
KORDOC_SOURCE="$WORK_ROOT/services/hwpx_builder/kordoc_runtime"
PYTHON_LAYOUT_HELPER="$WORK_ROOT/scripts/hwpx/python_runtime_layout.py"
test -x "$NODE"
test -x "$NPM"
test "$($NODE -p 'Number(process.versions.node.split(".")[0]) === 22')" = true
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
"$PYTHON" -m build --wheel --no-isolation \
  --outdir "$WHEEL_DIR" "$WORK_ROOT/packages/hwpx_contracts"
"$PYTHON" -m build --wheel --no-isolation \
  --outdir "$WHEEL_DIR" "$WORK_ROOT/services/hwpx_builder"

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
        "eom_hwpx_contracts/picture_geometry.py",
        "eom_hwpx_contracts/schemas/hwpx-item-document-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-render-request-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-template-binding-manifest-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-kordoc-render-request-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-kordoc-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-kordoc-bridge-report-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-render-request-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-render-request-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-build-result-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-editorial-question-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-render-request-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-build-result-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v1.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v2.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-render-request-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-content-team-exam-build-result-v3.schema.json",
        "eom_hwpx_contracts/schemas/hwpx-manager-download-v1.schema.json",
    },
    "eom_hwpx_builder": {
        "eom_hwpx_builder/__init__.py",
        "eom_hwpx_builder/cli.py",
        "eom_hwpx_builder/content_team_handoff.py",
        "eom_hwpx_builder/content_team_renderer.py",
        "eom_hwpx_builder/content_team_exam_renderer.py",
        "eom_hwpx_builder/content_team_images.py",
        "eom_hwpx_builder/handoff.py",
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
