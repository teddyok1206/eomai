#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCH="feat/observability-console-v0"
OBSERVE_PYTHON="/srv/eom/conda/envs/eom-observe/bin/python"
SERVICE="eom-observe.service"
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/eom-observe.service"
UNIT_TARGET="/etc/systemd/system/eom-observe.service"
STATE_ROOT="/var/lib/eom-observe/deployments"
ACTION="verify"
DRY_RUN=false
STAGING_DIR=""
PRE_SERVICE_ACTIVE="unknown"
PRE_SERVICE_ENABLED="unknown"
PRE_HEALTH_LIVE="false"

usage() {
  printf '%s\n' "usage: $0 [--build-only|--install|--verify|--dry-run]"
}

if (($# > 1)); then
  usage >&2
  exit 2
fi
if (($# == 1)); then
  case "$1" in
    --build-only) ACTION="build" ;;
    --install) ACTION="install" ;;
    --verify) ACTION="verify" ;;
    --dry-run) ACTION="install"; DRY_RUN=true ;;
    *) usage >&2; exit 2 ;;
  esac
fi

cleanup() {
  if [[ -n "${STAGING_DIR}" && -d "${STAGING_DIR}" ]]; then
    rm -rf "${STAGING_DIR}"
  fi
}
trap cleanup EXIT

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
[[ "$(git -C "${REPOSITORY_ROOT}" branch --show-current)" == "${EXPECTED_BRANCH}" ]] || \
  fail "branch mismatch"
[[ -x "${OBSERVE_PYTHON}" ]] || fail "observer Python is unavailable"

COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
VERSION="$(PYPROJECT="${REPOSITORY_ROOT}/apps/observe_console/pyproject.toml" \
  ${OBSERVE_PYTHON} -c \
  'import os,pathlib,tomllib; print(tomllib.loads(pathlib.Path(os.environ["PYPROJECT"]).read_text())["project"]["version"])' \
  2>/dev/null)"
BUILD_ROOT="/tmp/eom-observe-build/${COMMIT}"
DIST_DIR="${BUILD_ROOT}/dist"
WHEEL="${DIST_DIR}/eom_observe-${VERSION}-py3-none-any.whl"

require_clean_tree() {
  [[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
    fail "working tree must be clean before release build"
}

build_wheel() {
  require_clean_tree
  command -v rsync >/dev/null || fail "rsync is required"
  ${OBSERVE_PYTHON} -c 'import build' >/dev/null 2>&1 || fail "Python build package is unavailable"
  mkdir -p "${BUILD_ROOT}" "${DIST_DIR}"
  STAGING_DIR="$(mktemp -d "${BUILD_ROOT}/.staging.XXXXXX")"
  mkdir -p \
    "${STAGING_DIR}/eom_observe" \
    "${STAGING_DIR}/eom_observe_contracts/schemas"
  cp "${REPOSITORY_ROOT}/apps/observe_console/pyproject.toml" "${STAGING_DIR}/pyproject.toml"
  rsync -a --exclude='__pycache__' \
    "${REPOSITORY_ROOT}/apps/observe_console/eom_observe/" \
    "${STAGING_DIR}/eom_observe/"
  rsync -a --exclude='__pycache__' \
    "${REPOSITORY_ROOT}/packages/observe_contracts/eom_observe_contracts/" \
    "${STAGING_DIR}/eom_observe_contracts/"
  cp "${REPOSITORY_ROOT}"/schemas/observe/*.json \
    "${STAGING_DIR}/eom_observe_contracts/schemas/"
  mkdir -p "${STAGING_DIR}/eom_observe/resources"
  cp "${REPOSITORY_ROOT}/config/worker-slots.example.yaml" \
    "${STAGING_DIR}/eom_observe/resources/worker-slots.example.yaml"
  BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  COMMIT="${COMMIT}" VERSION="${VERSION}" BUILD_TIMESTAMP="${BUILD_TIMESTAMP}" \
    STAGING_DIR="${STAGING_DIR}" "${OBSERVE_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

target = Path(os.environ["STAGING_DIR"]) / "eom_observe" / "build-info.json"
target.write_text(
    json.dumps(
        {
            "source_commit": os.environ["COMMIT"],
            "package_version": os.environ["VERSION"],
            "build_timestamp_utc": os.environ["BUILD_TIMESTAMP"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="utf-8",
)
PY
  rm -f "${DIST_DIR}"/*.whl
  "${OBSERVE_PYTHON}" -m build --wheel --no-isolation \
    --outdir "${DIST_DIR}" "${STAGING_DIR}" >/dev/null
  [[ -f "${WHEEL}" ]] || fail "expected wheel was not produced"
  inspect_wheel "${WHEEL}"
  printf 'Built and inspected: %s\n' "$(basename "${WHEEL}")"
}

inspect_wheel() {
  local wheel="$1"
  WHEEL_PATH="${wheel}" EXPECTED_COMMIT="${COMMIT}" EXPECTED_VERSION="${VERSION}" \
    "${OBSERVE_PYTHON}" - <<'PY'
import json
import os
import zipfile

wheel = os.environ["WHEEL_PATH"]
with zipfile.ZipFile(wheel) as archive:
    names = set(archive.namelist())
    required = {
        "eom_observe/__init__.py",
        "eom_observe/build_info.py",
        "eom_observe/build-info.json",
        "eom_observe/resources/worker-slots.example.yaml",
        "eom_observe/static/index.html",
        "eom_observe/static/login.html",
        "eom_observe/static/app.js",
        "eom_observe/static/graph.js",
        "eom_observe/static/api.js",
        "eom_observe/static/state.js",
        "eom_observe/static/styles.css",
        "eom_observe/static/icons.svg",
        "eom_observe_contracts/__init__.py",
    }
    schemas = {name for name in names if name.startswith("eom_observe_contracts/schemas/") and name.endswith(".json")}
    if missing := required - names:
        raise SystemExit(f"wheel resource missing: {sorted(missing)}")
    if len(schemas) != 8:
        raise SystemExit(f"expected 8 schemas, found {len(schemas)}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    metadata = next(name for name in names if name.endswith(".dist-info/METADATA"))
    if "eom-observe = eom_observe.cli:main" not in archive.read(entry_points).decode():
        raise SystemExit("console entry point missing")
    metadata_text = archive.read(metadata).decode()
    if "Name: eom-observe\n" not in metadata_text or f"Version: {os.environ['EXPECTED_VERSION']}\n" not in metadata_text:
        raise SystemExit("wheel metadata mismatch")
    build_info = json.loads(archive.read("eom_observe/build-info.json"))
    if build_info["source_commit"] != os.environ["EXPECTED_COMMIT"]:
        raise SystemExit("build commit mismatch")
    if build_info["package_version"] != os.environ["EXPECTED_VERSION"]:
        raise SystemExit("build version mismatch")
    forbidden = (b"__editable__", b"git rev-parse", b'joinpath(".git")')
    for name in names:
        if name.endswith((".py", ".json", ".pth")):
            content = archive.read(name)
            if any(value in content for value in forbidden):
                raise SystemExit(f"wheel contains forbidden source dependency: {name}")
PY
}

record_rollback() {
  local timestamp record unit_backup
  timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
  mkdir -p "${STATE_ROOT}"
  record="${STATE_ROOT}/${timestamp}_${COMMIT}.json"
  unit_backup="${STATE_ROOT}/${timestamp}_eom-observe.service"
  if [[ -f "${UNIT_TARGET}" ]]; then
    cp "${UNIT_TARGET}" "${unit_backup}"
    chmod 0600 "${unit_backup}"
  fi
  RECORD_PATH="${record}" COMMIT="${COMMIT}" VERSION="${VERSION}" \
    WHEEL_NAME="$(basename "${WHEEL}")" UNIT_BACKUP="${unit_backup}" \
    WHEEL_SHA256="$(sha256sum "${WHEEL}" | cut -d' ' -f1)" \
    PRE_SERVICE_ACTIVE="${PRE_SERVICE_ACTIVE}" PRE_SERVICE_ENABLED="${PRE_SERVICE_ENABLED}" \
    PRE_HEALTH_LIVE="${PRE_HEALTH_LIVE}" \
    "${OBSERVE_PYTHON}" - <<'PY'
import importlib.metadata
import json
import os
from datetime import UTC, datetime
from pathlib import Path

previous = {}
previous_modes = {}
for name in ("eom-observe", "eom-observe-contracts"):
    try:
        distribution = importlib.metadata.distribution(name)
        previous[name] = distribution.version
        direct_url = distribution.read_text("direct_url.json")
        editable = bool(
            direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True
        )
        previous_modes[name] = "editable" if editable else "non-editable"
    except importlib.metadata.PackageNotFoundError:
        previous[name] = None
        previous_modes[name] = "absent"
payload = {
    "deployed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "source_commit": os.environ["COMMIT"],
    "package_version": os.environ["VERSION"],
    "wheel": os.environ["WHEEL_NAME"],
    "wheel_sha256": os.environ["WHEEL_SHA256"],
    "previous_distributions": previous,
    "previous_install_modes": previous_modes,
    "previous_unit_backup": os.environ["UNIT_BACKUP"],
    "previous_service_active": os.environ["PRE_SERVICE_ACTIVE"],
    "previous_service_enabled": os.environ["PRE_SERVICE_ENABLED"],
    "previous_health_live": os.environ["PRE_HEALTH_LIVE"] == "true",
}
Path(os.environ["RECORD_PATH"]).write_text(json.dumps(payload, indent=2) + "\n")
PY
  chmod 0600 "${record}"
}

remove_observer_editables() {
  mapfile -t editable_names < <("${OBSERVE_PYTHON}" - <<'PY'
import importlib.metadata
import json

for name in ("eom-observe", "eom-observe-contracts"):
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        continue
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
        print(name)
PY
)
  if ((${#editable_names[@]})); then
    "${OBSERVE_PYTHON}" -m pip uninstall -y "${editable_names[@]}" >/dev/null
  fi
}

verify_release() {
  inspect_wheel "${WHEEL}"
  EXPECTED_COMMIT="${COMMIT}" EXPECTED_VERSION="${VERSION}" \
    "${OBSERVE_PYTHON}" - <<'PY'
import importlib.metadata
import importlib.util
import json
import os
import site
from pathlib import Path

from eom_observe.build_info import get_build_info
from eom_observe.resources import static_resource, worker_slot_resource
from eom_observe_contracts.validation import SCHEMA_FILES, schema_resource

spec = importlib.util.find_spec("eom_observe")
if spec is None or spec.origin is None:
    raise SystemExit("eom_observe import missing")
origin = Path(spec.origin).resolve()
site_roots = [Path(path).resolve() for path in site.getsitepackages()]
if not any(origin.is_relative_to(root) for root in site_roots):
    raise SystemExit("eom_observe import is outside site-packages")
if "/home/eom/EOM" in str(origin):
    raise SystemExit("source checkout import detected")
for name in ("eom-observe", "eom-observe-contracts"):
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        continue
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
        raise SystemExit(f"editable distribution remains: {name}")
for root in site_roots:
    for path in root.glob("*eom_observe*"):
        if path.name.startswith("__editable__") or "finder" in path.name:
            raise SystemExit(f"editable metadata remains: {path.name}")
for name in ("index.html", "login.html", "app.js", "graph.js", "api.js", "state.js", "styles.css", "icons.svg"):
    if not static_resource(name).is_file():
        raise SystemExit(f"static resource missing: {name}")
if not worker_slot_resource().is_file():
    raise SystemExit("worker resource missing")
for filename in SCHEMA_FILES.values():
    if not schema_resource(filename).is_file():
        raise SystemExit(f"schema resource missing: {filename}")
build = get_build_info()
if build.source_commit != os.environ["EXPECTED_COMMIT"] or build.package_version != os.environ["EXPECTED_VERSION"]:
    raise SystemExit("installed build metadata mismatch")
print(origin)
PY
  [[ "$(systemctl show "${SERVICE}" --property=WorkingDirectory --value)" == "/var/lib/eom-observe" ]] || \
    fail "service working directory mismatch"
  ! systemctl show "${SERVICE}" --property=Environment --value | grep -q '/home/eom/EOM' || \
    fail "repository path appears in service environment"
  systemctl is-active --quiet "${SERVICE}" || fail "service is not active"
  systemctl is-enabled --quiet "${SERVICE}" || fail "service is not enabled"
  ss -lnt | grep -q '127.0.0.1:8780' || fail "loopback listener missing"
  ! ss -lnt | grep -Eq '(^|[[:space:]])(0\.0\.0\.0|\[::\]):8780' || fail "public listener detected"
  curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:8780/observe/api/v1/health/live >/dev/null
  TOKEN_PATH="/home/eom/.eom-observe-initial-token" "${OBSERVE_PYTHON}" - <<'PY'
import http.cookiejar
import json
import os
import urllib.request
from pathlib import Path

token_path = Path(os.environ["TOKEN_PATH"])
if not token_path.is_file():
    raise SystemExit("one-time token file unavailable for deployment authentication check")
token = token_path.read_text(encoding="utf-8").strip()
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
request = urllib.request.Request(
    "http://127.0.0.1:8780/observe/api/v1/session",
    data=json.dumps({"token": token}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with opener.open(request, timeout=5) as response:
    if response.status != 204:
        raise SystemExit("authentication check failed")
for path in (
    "/observe/",
    "/observe/assets/styles.css",
    "/observe/assets/app.js",
    "/observe/assets/icons.svg",
    "/observe/api/v1/health/ready",
):
    with opener.open("http://127.0.0.1:8780" + path, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(f"authenticated resource check failed: {path}")
with opener.open("http://127.0.0.1:8780/observe/api/v1/stream", timeout=5) as response:
    lines = []
    while len(lines) < 20:
        line = response.readline().decode("utf-8")
        if not line:
            break
        lines.append(line)
        if line == "\n":
            break
    if not any(line.startswith("event: snapshot") for line in lines):
        raise SystemExit("SSE snapshot check failed")
PY
  "${OBSERVE_PYTHON}" -m eom_observe.cli verify-readonly >/dev/null
  "${OBSERVE_PYTHON}" -m eom_observe.cli doctor >/dev/null
  "${OBSERVE_PYTHON}" -m pip check >/dev/null
  pid="$(systemctl show "${SERVICE}" --property=MainPID --value)"
  [[ "${pid}" =~ ^[1-9][0-9]*$ ]] || fail "service PID unavailable"
  ! nsenter --target "${pid}" --mount -- runuser -u eom-observe -- \
    test -r /home/eom/EOM/apps/observe_console || fail "source checkout readable in service sandbox"
  for path in /mnt/nas /root/.codex /srv/eom/worker-homes /var/run/docker.sock; do
    ! nsenter --target "${pid}" --mount -- runuser -u eom-observe -- test -r "${path}" || \
      fail "restricted path is readable: ${path}"
  done
  printf '%s\n' "Release verification passed"
}

if [[ "${DRY_RUN}" == true ]]; then
  require_clean_tree
  printf 'Dry run: build %s from commit %s, install into eom-observe only, restart %s\n' \
    "eom-observe-${VERSION}-py3-none-any.whl" "${COMMIT:0:12}" "${SERVICE}"
  exit 0
fi

case "${ACTION}" in
  build)
    build_wheel
    ;;
  install)
    [[ "${EUID}" -eq 0 ]] || fail "--install requires root"
    PRE_SERVICE_ACTIVE="$(systemctl is-active "${SERVICE}" 2>/dev/null || true)"
    PRE_SERVICE_ENABLED="$(systemctl is-enabled "${SERVICE}" 2>/dev/null || true)"
    if curl --fail --silent --max-time 5 \
      http://127.0.0.1:8780/observe/api/v1/health/live >/dev/null; then
      PRE_HEALTH_LIVE="true"
    fi
    build_wheel
    record_rollback
    systemctl stop "${SERVICE}"
    remove_observer_editables
    "${OBSERVE_PYTHON}" -m pip install --no-deps --no-cache-dir --force-reinstall \
      "${WHEEL}" >/dev/null
    install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
    systemctl daemon-reload
    systemctl enable "${SERVICE}" >/dev/null
    systemctl start "${SERVICE}"
    verify_release
    ;;
  verify)
    [[ -f "${WHEEL}" ]] || fail "release wheel not found; run --build-only first"
    verify_release
    ;;
esac
