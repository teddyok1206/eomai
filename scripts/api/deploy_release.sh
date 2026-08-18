#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCH="feat/application-api-v0"
API_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
API_PIP="${API_PYTHON} -m pip"
SERVICE="eom-api.service"
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/eom-api.service"
UNIT_TARGET="/etc/systemd/system/eom-api.service"
VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_deployment_metadata.sh"
VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-deployment-metadata"
ACTION="verify"
STAGING_ROOT=""

usage() {
  printf '%s\n' "usage: $0 [--build-only|--install|--verify]"
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
    *) usage >&2; exit 2 ;;
  esac
fi

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

cleanup() {
  if [[ -n "${STAGING_ROOT}" && -d "${STAGING_ROOT}" ]]; then
    rm -rf "${STAGING_ROOT}"
  fi
}
trap cleanup EXIT

[[ "$(id -un)" == "eom" ]] || fail "release builds must run as eom"
[[ "$(git -C "${REPOSITORY_ROOT}" rev-parse --show-toplevel)" == "${REPOSITORY_ROOT}" ]] || \
  fail "repository root mismatch"
[[ "$(git -C "${REPOSITORY_ROOT}" branch --show-current)" == "${EXPECTED_BRANCH}" ]] || \
  fail "branch mismatch"
[[ -x "${API_PYTHON}" ]] || fail "isolated eom-api Python is unavailable"

COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
VERSION="$(PYPROJECT="${REPOSITORY_ROOT}/apps/application_api/pyproject.toml" \
  "${API_PYTHON}" -c \
  'import os,pathlib,tomllib; print(tomllib.loads(pathlib.Path(os.environ["PYPROJECT"]).read_text())["project"]["version"])')"
BUILD_PARENT="/tmp/eom-api-build"
BUILD_ROOT=""
DIST_DIR=""

require_clean_tree() {
  [[ -z "$(git -C "${REPOSITORY_ROOT}" status --porcelain)" ]] || \
    fail "working tree must be clean before a release build"
}

build_release() {
  require_clean_tree
  mkdir -p "${BUILD_PARENT}"
  BUILD_ROOT="$(mktemp -d "${BUILD_PARENT}/${COMMIT}.XXXXXX")"
  DIST_DIR="${BUILD_ROOT}/dist"
  mkdir -p "${DIST_DIR}"
  STAGING_ROOT="$(mktemp -d "${BUILD_ROOT}/staging.XXXXXX")"

  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${REPOSITORY_ROOT}" >/dev/null

  mkdir -p "${STAGING_ROOT}/contracts/eom_api_contracts/schemas"
  cp "${REPOSITORY_ROOT}/packages/api_contracts/pyproject.toml" \
    "${STAGING_ROOT}/contracts/pyproject.toml"
  cp -a "${REPOSITORY_ROOT}/packages/api_contracts/eom_api_contracts/." \
    "${STAGING_ROOT}/contracts/eom_api_contracts/"
  find "${STAGING_ROOT}/contracts/eom_api_contracts" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  cp "${REPOSITORY_ROOT}"/schemas/api/v1/*.schema.json \
    "${STAGING_ROOT}/contracts/eom_api_contracts/schemas/"
  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${STAGING_ROOT}/contracts" >/dev/null

  mkdir -p "${STAGING_ROOT}/application/eom_api"
  cp "${REPOSITORY_ROOT}/apps/application_api/pyproject.toml" \
    "${STAGING_ROOT}/application/pyproject.toml"
  cp -a "${REPOSITORY_ROOT}/apps/application_api/eom_api/." \
    "${STAGING_ROOT}/application/eom_api/"
  find "${STAGING_ROOT}/application/eom_api" -type d -name __pycache__ \
    -prune -exec rm -rf {} +
  mkdir -p "${STAGING_ROOT}/application/eom_api/openapi"
  cp "${REPOSITORY_ROOT}/api/openapi/eom-api-v1.openapi.json" \
    "${REPOSITORY_ROOT}/api/openapi/eom-api-v1.sha256" \
    "${STAGING_ROOT}/application/eom_api/openapi/"
  BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
    COMMIT="${COMMIT}" VERSION="${VERSION}" STAGING_ROOT="${STAGING_ROOT}" \
    "${API_PYTHON}" - <<'PY'
import json
import os
from pathlib import Path

target = Path(os.environ["STAGING_ROOT"]) / "application" / "eom_api" / "build-info.json"
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
  "${API_PYTHON}" -m pip wheel \
    --no-deps --no-build-isolation --wheel-dir "${DIST_DIR}" \
    "${STAGING_ROOT}/application" >/dev/null

  inspect_release
  printf 'Built and inspected EOM Application API %s from %s.\n' "${VERSION}" "${COMMIT}"
}

inspect_release() {
  DIST_DIR="${DIST_DIR}" EXPECTED_COMMIT="${COMMIT}" EXPECTED_VERSION="${VERSION}" \
    REPOSITORY_ROOT="${REPOSITORY_ROOT}" API_PYTHON="${API_PYTHON}" \
    "${API_PYTHON}" - <<'PY'
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

dist = Path(os.environ["DIST_DIR"])
wheels = sorted(dist.glob("*.whl"))
if len(wheels) != 3:
    raise SystemExit(f"expected 3 wheels, found {len(wheels)}")
by_prefix = {wheel.name.split("-", 1)[0]: wheel for wheel in wheels}
required_wheels = {"eom_platform", "eom_api_contracts", "eom_application_api"}
if set(by_prefix) != required_wheels:
    raise SystemExit(f"unexpected wheel set: {sorted(by_prefix)}")

with zipfile.ZipFile(by_prefix["eom_application_api"]) as archive:
    names = set(archive.namelist())
    required = {
        "eom_api/__init__.py",
        "eom_api/app.py",
        "eom_api/build_info.py",
        "eom_api/build-info.json",
        "eom_api/cli.py",
        "eom_api/openapi/eom-api-v1.openapi.json",
        "eom_api/openapi/eom-api-v1.sha256",
    }
    if missing := required - names:
        raise SystemExit(f"Application API wheel resources missing: {sorted(missing)}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    if "eom-api = eom_api.cli:main" not in archive.read(entry_points).decode():
        raise SystemExit("eom-api console entry point missing")
    build = json.loads(archive.read("eom_api/build-info.json"))
    if build["source_commit"] != os.environ["EXPECTED_COMMIT"]:
        raise SystemExit("Application API wheel source commit mismatch")
    if build["package_version"] != os.environ["EXPECTED_VERSION"]:
        raise SystemExit("Application API wheel version mismatch")

with zipfile.ZipFile(by_prefix["eom_api_contracts"]) as archive:
    schemas = [
        name
        for name in archive.namelist()
        if name.startswith("eom_api_contracts/schemas/") and name.endswith(".schema.json")
    ]
    if len(schemas) != 5:
        raise SystemExit(f"expected 5 packaged API schemas, found {len(schemas)}")

workflow_prefix = "eom_workflow/resources/"
workflow_resources = {
    "workflow-definition.schema.json",
    "roles/authoring-input.schema.json",
    "roles/authoring-result.schema.json",
    "roles/image-input.schema.json",
    "roles/image-result.schema.json",
    "roles/registration-input.schema.json",
    "roles/registration-result.schema.json",
    "roles/review-input.schema.json",
    "roles/review-result.schema.json",
}
platform_wheel = by_prefix["eom_platform"]
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    packaged = {
        name.removeprefix(workflow_prefix)
        for name in names
        if name.startswith(workflow_prefix) and name.endswith(".schema.json")
    }
    if packaged != workflow_resources:
        raise SystemExit(
            "workflow schema wheel resources mismatch: "
            f"expected={sorted(workflow_resources)} actual={sorted(packaged)}"
        )
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    canonical_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/workflow"
    for logical_name in sorted(workflow_resources):
        member = workflow_prefix + logical_name
        if archive.read(member) != (canonical_root / logical_name).read_bytes():
            raise SystemExit(f"workflow schema resource drift: {logical_name}")
        if member not in record:
            raise SystemExit(f"workflow schema resource missing from RECORD: {logical_name}")

catalog_prefix = "eom_catalog_contracts/resources/"
catalog_resources = {
    "content-intake/intake-manifest-v1.schema.json": "schemas/content-intake/intake-manifest-v1.schema.json",
    "content-intake/mapping-proposal-v1.schema.json": "schemas/content-intake/mapping-proposal-v1.schema.json",
    "content-intake/uncertainties-v1.schema.json": "schemas/content-intake/uncertainties-v1.schema.json",
    "content-intake/human-decision-v1.schema.json": "schemas/content-intake/human-decision-v1.schema.json",
    "content-pack/content-pack-v1.schema.json": "schemas/content-pack/content-pack-v1.schema.json",
    "content-pack/profile-v1.schema.json": "schemas/content-pack/profile-v1.schema.json",
    "content-pack/prompt-envelope-v1.schema.json": "schemas/content-pack/prompt-envelope-v1.schema.json",
    "item-registry/item-revision-manifest-v1.schema.json": "schemas/item-registry/item-revision-manifest-v1.schema.json",
}
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    packaged = {
        name.removeprefix(catalog_prefix)
        for name in names
        if name.startswith(catalog_prefix) and name.endswith(".schema.json")
    }
    expected = set(catalog_resources)
    if packaged != expected:
        raise SystemExit(
            "Catalog Contract schema wheel resources mismatch: "
            f"expected={sorted(expected)} actual={sorted(packaged)}"
        )
    record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
    record = archive.read(record_name).decode("utf-8")
    repository_root = Path(os.environ["REPOSITORY_ROOT"])
    for resource_name, canonical_name in sorted(catalog_resources.items()):
        member = catalog_prefix + resource_name
        if archive.read(member) != (repository_root / canonical_name).read_bytes():
            raise SystemExit(f"Catalog Contract schema resource drift: {resource_name}")
        if member not in record:
            raise SystemExit(f"Catalog Contract resource missing from RECORD: {resource_name}")

with tempfile.TemporaryDirectory(prefix="eom-workflow-wheel-check.") as temporary:
    root = Path(temporary)
    installed_root = root / "site-packages"
    definition = root / "generic-item-development.v1.1.yaml"
    definition.write_bytes(
        (
            Path(os.environ["REPOSITORY_ROOT"])
            / "config/workflows/generic-item-development.v1.1.yaml"
        ).read_bytes()
    )
    subprocess.run(
        [
            os.environ["API_PYTHON"],
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--target",
            str(installed_root),
            str(platform_wheel),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    check = r'''
import importlib.util
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository, definition_path = sys.argv[2:]
sys.path.insert(0, str(installed_root))
from eom_workflow.compiler import compile_definition
from eom_workflow.schemas import (
    INPUT_SCHEMA_FILES,
    RESULT_SCHEMA_FILES,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
)
from eom_catalog_contracts import catalog_schema_inventory, load_schema, validate_contract

spec = importlib.util.find_spec("eom_workflow")
if (
    spec is None
    or spec.origin is None
    or not Path(spec.origin).resolve().is_relative_to(installed_root)
    or repository in spec.origin
):
    raise SystemExit("workflow package was not imported from the release wheel")
load_definition_schema()
for role in INPUT_SCHEMA_FILES:
    load_role_input_schema(role)
for schema_id in RESULT_SCHEMA_FILES:
    load_role_result_schema(schema_id)
compiled = compile_definition(
    Path(definition_path), {"authoring", "image", "review", "item_management"}
)
if compiled.definition.definition_version != "1.1.0":
    raise SystemExit("generic workflow definition version mismatch")
for name, _ in catalog_schema_inventory():
    load_schema(name)
validate_contract(
    "prompt-envelope",
    {
        "schema_version": "1.0",
        "pack_release_id": "packrel_" + "0" * 32,
        "pack_release_sha256": "sha256:" + "0" * 64,
        "profile_key": "authoring-default",
        "profile_version": "0.1.0",
        "profile_sha256": "sha256:" + "0" * 64,
        "template_path": "prompt-templates/authoring.md",
        "template_sha256": "sha256:" + "0" * 64,
        "render_context_sha256": "sha256:" + "0" * 64,
        "rendered_prompt_sha256": "sha256:" + "0" * 64,
        "workflow_id": "workflow_" + "0" * 32,
        "step_run_id": "steprun_" + "0" * 32,
        "source_intake_batch_ids": ["intake_" + "0" * 32],
    },
)
'''
    subprocess.run(
        [
            os.environ["API_PYTHON"],
            "-I",
            "-c",
            check,
            str(installed_root),
            os.environ["REPOSITORY_ROOT"],
            str(definition),
        ],
        cwd=root,
        check=True,
    )

for wheel in wheels:
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.endswith((".py", ".json", ".pth")):
                content = archive.read(name)
                if b"__editable__" in content:
                    raise SystemExit(f"wheel contains editable metadata: {wheel.name}:{name}")
                if name.endswith(".pth") and b"/home/eom/EOM" in content:
                    raise SystemExit(
                        f"wheel contains a source-checkout path mapping: {wheel.name}:{name}"
                    )
PY
}

install_wheels() {
  mapfile -t wheels < <(find "${DIST_DIR}" -maxdepth 1 -type f -name '*.whl' | sort)
  ((${#wheels[@]} == 3)) || fail "release wheels are unavailable"
  ${API_PIP} install --no-deps --force-reinstall "${wheels[@]}" >/dev/null
  ${API_PIP} check
  verify_install_mode
}

verify_install_mode() {
  REPOSITORY_ROOT="${REPOSITORY_ROOT}" "${API_PYTHON}" - <<'PY'
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import site
from pathlib import Path

site_roots = [Path(value).resolve() for value in site.getsitepackages()]
for module in (
    "eom_api",
    "eom_api_contracts",
    "eom_operator_identity",
    "eom_catalog_contracts",
    "eom_workflow",
    "eom_workflow_runner",
    "eom_catalog_service",
):
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise SystemExit(f"installed module is missing: {module}")
    origin = Path(spec.origin).resolve()
    if not any(origin.is_relative_to(root) for root in site_roots):
        raise SystemExit(f"module is outside site-packages: {module}")
    if str(origin).startswith(os.environ["REPOSITORY_ROOT"]):
        raise SystemExit(f"source checkout import detected: {module}")
for name in ("eom-application-api", "eom-api-contracts", "eom-platform"):
    distribution = importlib.metadata.distribution(name)
    direct_url = distribution.read_text("direct_url.json")
    if direct_url and json.loads(direct_url).get("dir_info", {}).get("editable") is True:
        raise SystemExit(f"editable distribution detected: {name}")
for root in site_roots:
    for path in root.glob("__editable__*"):
        raise SystemExit(f"editable metadata detected: {path.name}")

from eom_catalog_contracts import catalog_schema_inventory, load_schema

for name, _ in catalog_schema_inventory():
    load_schema(name)
PY
}

record_release() {
  local record temporary
  temporary="$(mktemp)"
  record="/var/lib/eom-api/deployments/${COMMIT}.json"
  COMMIT="${COMMIT}" VERSION="${VERSION}" DIST_DIR="${DIST_DIR}" RECORD="${temporary}" \
    "${API_PYTHON}" - <<'PY'
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

dist = Path(os.environ["DIST_DIR"])
wheels = {}
for path in sorted(dist.glob("*.whl")):
    wheels[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
payload = {
    "deployed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    "source_commit": os.environ["COMMIT"],
    "package_version": os.environ["VERSION"],
    "wheels": wheels,
    "rollback": (
        "Reinstall the three retained wheels for the prior source commit, restore the prior "
        "unit if it changed, then run deploy_release.sh --verify."
    ),
}
Path(os.environ["RECORD"]).write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
PY
  sudo -n install -d -o eom-api -g eom-api -m 0700 /var/lib/eom-api/deployments
  sudo -n install -o eom-api -g eom-api -m 0600 "${temporary}" "${record}"
  rm -f "${temporary}"
  printf 'Rollback record: %s\n' "${record}"
}

wait_for_health() {
  local attempt
  for attempt in {1..30}; do
    if curl --fail --silent --max-time 1 \
      http://127.0.0.1:8765/api/v1/health/live >/dev/null && \
      curl --fail --silent --max-time 1 \
      http://127.0.0.1:8765/api/v1/health/ready >/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  fail "Application API did not become healthy within 15 seconds"
}

install_service() {
  id eom-api >/dev/null 2>&1 || fail "eom-api system user is absent"
  systemd-analyze verify "${UNIT_SOURCE}"
  sudo -n install -d -o root -g root -m 0755 /usr/local/libexec/eom-api
  sudo -n install -o root -g root -m 0755 "${VERIFIER_SOURCE}" "${VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
  sudo -n "${VERIFIER_TARGET}"
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable "${SERVICE}" >/dev/null
  sudo -n systemctl restart "${SERVICE}"
  wait_for_health
  record_release
  if [[ -n "${EOM_API_SMOKE_USERNAME:-}" && -n "${EOM_API_SMOKE_PASSWORD_FILE:-}" ]]; then
    "${REPOSITORY_ROOT}/scripts/api/smoke_test.sh"
  else
    printf 'Authenticated smoke deferred until EOM_API_SMOKE_USERNAME and '
    printf 'EOM_API_SMOKE_PASSWORD_FILE are set.\n'
  fi
}

verify_service() {
  verify_install_mode
  systemctl is-active --quiet "${SERVICE}" || fail "eom-api.service is not active"
  systemctl is-enabled --quiet "${SERVICE}" || fail "eom-api.service is not enabled"
  wait_for_health
  "${REPOSITORY_ROOT}/scripts/api/smoke_test.sh" --health-only
  printf 'Installed EOM Application API release verified.\n'
}

case "${ACTION}" in
  build)
    build_release
    ;;
  install)
    sudo -n true || fail "noninteractive privileged access is required before installation"
    build_release
    install_wheels
    install_service
    ;;
  verify)
    verify_service
    ;;
esac
