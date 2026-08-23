#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="/home/eom/EOM"
EXPECTED_BRANCHES=("main" "feat/application-api-v0" "feat/hwpx-application-api-v0")
API_PYTHON="/srv/eom/conda/envs/eom-api/bin/python"
API_PIP="${API_PYTHON} -m pip"
SERVICE="eom-api.service"
UNIT_SOURCE="${REPOSITORY_ROOT}/infra/systemd/eom-api.service"
UNIT_TARGET="/etc/systemd/system/eom-api.service"
METADATA_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_deployment_metadata.sh"
METADATA_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-deployment-metadata"
RUNTIME_VERIFIER_SOURCE="${REPOSITORY_ROOT}/scripts/api/verify_runtime_isolation.sh"
RUNTIME_VERIFIER_TARGET="/usr/local/libexec/eom-api/verify-runtime-isolation"
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
CURRENT_BRANCH="$(git -C "${REPOSITORY_ROOT}" branch --show-current)"
branch_allowed=false
for candidate in "${EXPECTED_BRANCHES[@]}"; do
  if [[ "${CURRENT_BRANCH}" == "${candidate}" ]]; then
    branch_allowed=true
    break
  fi
done
[[ "${branch_allowed}" == true ]] || fail "branch mismatch"
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
  printf 'application_api_release_wheel_dir=%s\n' "${DIST_DIR}"
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
        "eom_api/runtime_isolation_pidfd.py",
        "eom_api/runtime_isolation_verifier.py",
        "eom_api/openapi/eom-api-v1.openapi.json",
        "eom_api/openapi/eom-api-v1.sha256",
    }
    if missing := required - names:
        raise SystemExit(f"Application API wheel resources missing: {sorted(missing)}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    entry_point_source = archive.read(entry_points).decode()
    if "eom-api = eom_api.cli:main" not in entry_point_source:
        raise SystemExit("eom-api console entry point missing")
    if (
        "eom-api-runtime-isolation = eom_api.runtime_isolation_verifier:main"
        not in entry_point_source
    ):
        raise SystemExit("runtime isolation console entry point missing")
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
    if (
        len(schemas) != 7
        or "eom_api_contracts/schemas/hwpx.schema.json" not in schemas
        or "eom_api_contracts/schemas/items.schema.json" not in schemas
    ):
        raise SystemExit(f"expected 7 packaged API schemas including HWPX and Items, found {schemas}")

workflow_prefix = "eom_workflow/resources/"
canonical_workflow_root = Path(os.environ["REPOSITORY_ROOT"]) / "schemas/workflow"
workflow_resources = {
    path.relative_to(canonical_workflow_root).as_posix()
    for path in canonical_workflow_root.rglob("*.schema.json")
}
platform_wheel = by_prefix["eom_platform"]
with zipfile.ZipFile(platform_wheel) as archive:
    names = set(archive.namelist())
    worker_runtime = {
        "eom_orchestrator/capability_observer.py",
        "eom_orchestrator/capacity_controller.py",
        "eom_orchestrator/live_preflight.py",
        "eom_orchestrator/runtime_configuration.py",
        "eom_orchestrator/settings.py",
        "eom_orchestrator/worker.py",
        "eom_orchestrator/worker_auth.py",
        "eom_orchestrator/worker_auth_exec.py",
        "eom_orchestrator/worker_exec.py",
        "eom_orchestrator/worker_systemd.py",
    }
    actor_runtime = {
        "eom_workflow_runner/actor_authorization.py",
        "eom_workflow_runner/actor_authorization_adapters.py",
        "eom_workflow_runner/settings.py",
    }
    catalog_staging_runtime = {
        "eom_catalog_contracts/assessment_item.py",
        "eom_catalog_contracts/application.py",
        "eom_catalog_contracts/knowledge.py",
        "eom_catalog_contracts/validation.py",
        "eom_catalog_service/application_runner.py",
        "eom_catalog_service/application_server.py",
        "eom_catalog_service/generated_stimulus.py",
        "eom_catalog_service/item_content_import.py",
        "eom_catalog_service/knowledge_stimulus.py",
        "eom_catalog_service/settings.py",
        "eom_catalog_service/staging.py",
        "eom_catalog_service/registry_service.py",
    }
    hwpx_application_runtime = {
        "eom_hwpx_manager/application_adapter.py",
        "eom_hwpx_manager/application_service.py",
        "eom_hwpx_manager/application_state.py",
        "eom_hwpx_manager/capability.py",
        "eom_hwpx_manager/download_server.py",
        "eom_hwpx_manager/markdown_structure.py",
        "eom_hwpx_manager/question_template.py",
        "eom_hwpx_manager/question_template_service.py",
        "eom_hwpx_manager/runner.py",
        "eom_hwpx_manager/runtime_privileges.py",
    }
    if missing := (
        worker_runtime | actor_runtime | catalog_staging_runtime | hwpx_application_runtime
    ) - names:
        raise SystemExit(f"platform runtime missing from wheel: {sorted(missing)}")
    settings_source = archive.read("eom_orchestrator/settings.py")
    for forbidden in (
        b"parents[",
        b"worker-slots.example.yaml",
        b"/home/eom/EOM",
    ):
        if forbidden in settings_source:
            raise SystemExit("Orchestrator settings retain implicit source/install path inference")
    workflow_settings_source = archive.read("eom_workflow_runner/settings.py")
    for forbidden in (
        b"parents[",
        b".example.yaml",
        b"/home/eom/EOM",
    ):
        if forbidden in workflow_settings_source:
            raise SystemExit("workflow settings retain implicit source/install path inference")
    for required in (
        b"/etc/eom/workflows/generic-item-development.yaml",
        b"/etc/eom/human-actors.yaml",
        b"/etc/eom/workflow-runner.yaml",
        b"/etc/eom/workflow-prompts",
    ):
        if required not in workflow_settings_source:
            raise SystemExit("workflow settings operator path contract is missing")
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
    for member in sorted(worker_runtime):
        if member not in record:
            raise SystemExit(f"fixed worker runtime missing from RECORD: {member}")
    for member in sorted(actor_runtime):
        if member not in record:
            raise SystemExit(f"workflow actor runtime missing from RECORD: {member}")
    for member in sorted(catalog_staging_runtime):
        if member not in record:
            raise SystemExit(f"Catalog staging runtime missing from RECORD: {member}")
    for member in sorted(hwpx_application_runtime):
        if member not in record:
            raise SystemExit(f"HWPX application runtime missing from RECORD: {member}")
    entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
    if "eom-hwpx-application-runner = eom_hwpx_manager.runner:main" not in archive.read(
        entry_points
    ).decode():
        raise SystemExit("HWPX application runner console entry point missing")
    if "eom-catalog-application-runner = eom_catalog_service.application_runner:main" not in archive.read(
        entry_points
    ).decode():
        raise SystemExit("Catalog application runner console entry point missing")
    worker_exec_source = (
        Path(os.environ["REPOSITORY_ROOT"])
        / "services/orchestrator/eom_orchestrator/worker_exec.py"
    )
    if archive.read("eom_orchestrator/worker_exec.py") != worker_exec_source.read_bytes():
        raise SystemExit("root-installed worker executable source drift")
    worker_auth_exec_source = (
        Path(os.environ["REPOSITORY_ROOT"])
        / "services/orchestrator/eom_orchestrator/worker_auth_exec.py"
    )
    if archive.read("eom_orchestrator/worker_auth_exec.py") != worker_auth_exec_source.read_bytes():
        raise SystemExit("root-installed worker authentication executable source drift")
    for logical_name in sorted(workflow_resources):
        member = workflow_prefix + logical_name
        if archive.read(member) != (canonical_workflow_root / logical_name).read_bytes():
            raise SystemExit(f"workflow schema resource drift: {logical_name}")
        if member not in record:
            raise SystemExit(f"workflow schema resource missing from RECORD: {logical_name}")

catalog_prefix = "eom_catalog_contracts/resources/"
catalog_resources = {
    "catalog-application/catalog-application-request-v1.schema.json": "schemas/catalog-application/catalog-application-request-v1.schema.json",
    "catalog-application/catalog-application-response-v1.schema.json": "schemas/catalog-application/catalog-application-response-v1.schema.json",
    "content-intake/intake-manifest-v1.schema.json": "schemas/content-intake/intake-manifest-v1.schema.json",
    "content-intake/mapping-proposal-v1.schema.json": "schemas/content-intake/mapping-proposal-v1.schema.json",
    "content-intake/uncertainties-v1.schema.json": "schemas/content-intake/uncertainties-v1.schema.json",
    "content-intake/human-decision-v1.schema.json": "schemas/content-intake/human-decision-v1.schema.json",
    "content-pack/content-pack-v1.schema.json": "schemas/content-pack/content-pack-v1.schema.json",
    "content-pack/content-pack-v2.schema.json": "schemas/content-pack/content-pack-v2.schema.json",
    "content-pack/profile-v1.schema.json": "schemas/content-pack/profile-v1.schema.json",
    "content-pack/prompt-envelope-v1.schema.json": "schemas/content-pack/prompt-envelope-v1.schema.json",
    "item-registry/assessment-item-content-v1.schema.json": "schemas/item-registry/assessment-item-content-v1.schema.json",
    "item-registry/item-revision-manifest-v1.schema.json": "schemas/item-registry/item-revision-manifest-v1.schema.json",
    "knowledge/knowledge-types-v1.schema.json": "schemas/knowledge/knowledge-types-v1.schema.json",
    "knowledge/knowledge-analysis-request-v1.schema.json": "schemas/knowledge/knowledge-analysis-request-v1.schema.json",
    "knowledge/knowledge-analysis-result-v1.schema.json": "schemas/knowledge/knowledge-analysis-result-v1.schema.json",
    "knowledge/knowledge-graph-snapshot-manifest-v1.schema.json": "schemas/knowledge/knowledge-graph-snapshot-manifest-v1.schema.json",
    "knowledge/education-retrieval-request-v1.schema.json": "schemas/knowledge/education-retrieval-request-v1.schema.json",
    "knowledge/evidence-bundle-manifest-v1.schema.json": "schemas/knowledge/evidence-bundle-manifest-v1.schema.json",
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
    definitions = []
    for version in ("1.1", "1.2", "1.3", "1.4"):
        definition = root / f"generic-item-development.v{version}.yaml"
        definition.write_bytes(
            (
                Path(os.environ["REPOSITORY_ROOT"])
                / f"config/workflows/generic-item-development.v{version}.yaml"
            ).read_bytes()
        )
        definitions.append(definition)
    worker_config = root / "worker-slots.yaml"
    worker_config.write_bytes(
        (Path(os.environ["REPOSITORY_ROOT"]) / "config/worker-slots.example.yaml").read_bytes()
    )
    staging = root / "staging"
    workspace_root = root / "workspaces"
    staging.mkdir()
    (workspace_root / "eom-cdx-01").mkdir(parents=True)
    codex_binary = root / "codex"
    codex_binary.write_text("isolated non-live executable placeholder\n", encoding="utf-8")
    codex_binary.chmod(0o700)
    previous_umask = os.umask(0o022)
    try:
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
    finally:
        os.umask(previous_umask)
    for path in (installed_root, *installed_root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("installed simulation contains a symlink")
        expected_mode = (
            0o755 if path.is_dir() or path.parent == installed_root / "bin" else 0o644
        )
        if path.stat().st_mode & 0o777 != expected_mode:
            raise SystemExit(f"installed simulation mode mismatch: {path.name}")
    check = r'''
import importlib.util
import os
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository, definition_v1_1, definition_v1_2, definition_v1_3, definition_v1_4, worker_config, staging, workspace_root, codex_binary = sys.argv[2:]
sys.path.insert(0, str(installed_root))
os.environ["EOM_WORKER_CONFIG"] = worker_config
os.environ["EOM_STAGING_ROOT"] = staging
os.environ["EOM_WORKSPACE_ROOT"] = workspace_root
os.environ["EOM_CODEX_BINARY"] = codex_binary
from eom_workflow.compiler import compile_definition
from eom_workflow.schemas import (
    INPUT_SCHEMA_FILES,
    RESULT_SCHEMA_FILES,
    load_codex_result_schema,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
)
from eom_catalog_contracts import catalog_schema_inventory, load_schema, validate_contract
import eom_workflow_runner.actor_authorization
import eom_workflow_runner.actor_authorization_adapters
from eom_orchestrator.doctor import runtime_configuration_check
from eom_orchestrator.live_preflight import run_live_worker_preflight
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import DEFAULT_WORKER_CONFIG, Settings, WorkerConfigSource
from eom_orchestrator.worker_systemd import WorkerSystemdReadiness

spec = importlib.util.find_spec("eom_workflow")
if (
    spec is None
    or spec.origin is None
    or not Path(spec.origin).resolve().is_relative_to(installed_root)
    or repository in spec.origin
):
    raise SystemExit("workflow package was not imported from the release wheel")
orchestrator_spec = importlib.util.find_spec("eom_orchestrator")
if (
    orchestrator_spec is None
    or orchestrator_spec.origin is None
    or not Path(orchestrator_spec.origin).resolve().is_relative_to(installed_root)
    or repository in orchestrator_spec.origin
):
    raise SystemExit("Orchestrator package was not imported from the release wheel")
settings = Settings.from_environment()
if settings.worker_config != Path(worker_config).resolve():
    raise SystemExit("explicit worker configuration was not selected")
if settings.worker_config_source is not WorkerConfigSource.ENVIRONMENT:
    raise SystemExit("worker configuration source was not retained")
if DEFAULT_WORKER_CONFIG != Path("/etc/eom/worker-slots.yaml"):
    raise SystemExit("operator-owned worker configuration default drift")
if settings.worker_config == Path(sys.prefix) / "config" / "worker-slots.example.yaml":
    raise SystemExit("install-prefix worker configuration inference detected")
resolved = resolve_worker_configuration(settings)
if resolved.live_worker.slot_id != "01" or not runtime_configuration_check(settings).passed:
    raise SystemExit("installed worker configuration readiness failed")
def ready(_slot):
    return WorkerSystemdReadiness(True, "READY", "isolated non-live boundary")
preflight = run_live_worker_preflight(
    settings,
    package_roots=(installed_root,),
    systemd_contract=ready,
    authorization_probe=ready,
)
if not preflight.ready:
    raise SystemExit(f"installed non-live worker preflight failed: {preflight.failed_codes}")
load_definition_schema()
for role in INPUT_SCHEMA_FILES:
    load_role_input_schema(role)
    load_role_input_schema(role, "workflow-role/1.1.0")
    load_role_input_schema(role, "workflow-role/1.2.0")
    load_role_input_schema(role, "workflow-role/1.3.0")
for schema_id in RESULT_SCHEMA_FILES:
    load_role_result_schema(schema_id)
    load_codex_result_schema(schema_id)
compiled_versions = {
    compile_definition(
        Path(definition_path), {"authoring", "image", "review", "item_management"}
    ).definition.definition_version
    for definition_path in (definition_v1_1, definition_v1_2, definition_v1_3, definition_v1_4)
}
if compiled_versions != {"1.1.0", "1.2.0", "1.3.0", "1.4.0"}:
    raise SystemExit("generic workflow definition versions mismatch")
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
            *(str(definition) for definition in definitions),
            str(worker_config),
            str(staging),
            str(workspace_root),
            str(codex_binary),
        ],
        cwd=root,
        check=True,
    )

with tempfile.TemporaryDirectory(prefix="eom-api-verifier-wheel-check.") as temporary:
    root = Path(temporary)
    installed_root = root / "site-packages"
    previous_umask = os.umask(0o022)
    try:
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
                str(by_prefix["eom_application_api"]),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    finally:
        os.umask(previous_umask)
    for path in (installed_root, *installed_root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Application API installed simulation contains a symlink")
        expected_mode = (
            0o755 if path.is_dir() or path.parent == installed_root / "bin" else 0o644
        )
        if path.stat().st_mode & 0o777 != expected_mode:
            raise SystemExit(f"Application API installed simulation mode mismatch: {path.name}")
    capability_check = r'''
import importlib.util
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(installed_root))
spec = importlib.util.find_spec("eom_api.runtime_isolation_verifier")
if (
    spec is None
    or spec.origin is None
    or not Path(spec.origin).resolve().is_relative_to(installed_root)
    or Path(spec.origin).resolve().is_relative_to(repository)
):
    raise SystemExit("runtime-isolation verifier was not imported from the installed wheel")
sys.argv = ["eom-api-runtime-isolation", "--capabilities"]
from eom_api.runtime_isolation_verifier import main
main()
'''
    completed = subprocess.run(
        [
            os.environ["API_PYTHON"],
            "-I",
            "-c",
            capability_check,
            str(installed_root),
            os.environ["REPOSITORY_ROOT"],
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = set(completed.stdout.splitlines())
    if "runtime_isolation_verifier_capability=READY" not in lines:
        raise SystemExit("installed-wheel runtime-isolation capability is not ready")
    if not lines.intersection(
        {"selected_pidfd_backend=PYTHON_OS_PIDFD", "selected_pidfd_backend=LIBC_PIDFD"}
    ):
        raise SystemExit("installed-wheel runtime-isolation pidfd backend is unavailable")
    if "pidfd_policy=FAIL_CLOSED" not in lines or completed.stderr:
        raise SystemExit("installed-wheel runtime-isolation capability output mismatch")

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
  (
    umask 022
    ${API_PIP} install --no-deps --force-reinstall "${wheels[@]}" >/dev/null
  )
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
import stat
from pathlib import Path

site_roots = [Path(value).resolve() for value in site.getsitepackages()]
runtime_package_roots: set[Path] = set()
for module in (
    "eom_api",
    "eom_api_contracts",
    "eom_operator_identity",
    "eom_catalog_contracts",
    "eom_workflow",
    "eom_workflow_runner",
    "eom_catalog_service",
    "eom_hwpx_manager",
):
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise SystemExit(f"installed module is missing: {module}")
    origin = Path(spec.origin).resolve()
    if not any(origin.is_relative_to(root) for root in site_roots):
        raise SystemExit(f"module is outside site-packages: {module}")
    if str(origin).startswith(os.environ["REPOSITORY_ROOT"]):
        raise SystemExit(f"source checkout import detected: {module}")
    runtime_package_roots.add(origin.parent)

expected_uid = os.getuid()
expected_gid = os.getgid()
for root in sorted(runtime_package_roots):
    for path in (root, *root.rglob("*")):
        if path.is_symlink():
            raise SystemExit(f"runtime package contains a symlink: {path.name}")
        metadata = path.stat()
        if metadata.st_uid != expected_uid or metadata.st_gid != expected_gid:
            raise SystemExit(f"runtime package ownership mismatch: {path.name}")
        expected_mode = 0o755 if path.is_dir() else 0o644
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            raise SystemExit(f"runtime package mode mismatch: {path.name}")

for name in (
    "eom-api",
    "eom-api-runtime-isolation",
    "eom-hwpx-application-runner",
    "eom-catalog-application-runner",
):
    entrypoint = Path(os.environ.get("API_PYTHON", "/srv/eom/conda/envs/eom-api/bin/python"))
    entrypoint = entrypoint.resolve().parent / name
    metadata = entrypoint.stat()
    if (
        metadata.st_uid != expected_uid
        or metadata.st_gid != expected_gid
        or stat.S_IMODE(metadata.st_mode) != 0o755
    ):
        raise SystemExit(f"runtime entry point mode mismatch: {name}")
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
  "${API_PYTHON}" -I -m eom_api.runtime_isolation_verifier --capabilities
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
  sudo -n install -o root -g root -m 0755 \
    "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0755 \
    "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}"
  sudo -n install -o root -g root -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
  sudo -n "${METADATA_VERIFIER_TARGET}"
  sudo -n systemctl daemon-reload
  sudo -n systemctl enable "${SERVICE}" >/dev/null
  sudo -n systemctl restart "${SERVICE}"
  wait_for_health
  printf 'runtime_isolation_verifier_invocation=START\n'
  sudo -n "${RUNTIME_VERIFIER_TARGET}"
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
  cmp --silent "${METADATA_VERIFIER_SOURCE}" "${METADATA_VERIFIER_TARGET}" || \
    fail "installed metadata verifier source drift"
  cmp --silent "${RUNTIME_VERIFIER_SOURCE}" "${RUNTIME_VERIFIER_TARGET}" || \
    fail "installed runtime verifier source drift"
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
