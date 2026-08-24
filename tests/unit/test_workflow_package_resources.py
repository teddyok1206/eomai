from __future__ import annotations

import subprocess
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from eom_workflow.control_schemas import control_schema_inventory, load_control_schema
from eom_workflow.schemas import (
    INPUT_SCHEMA_FILES,
    INPUT_SCHEMA_FILES_V1_4,
    RESULT_SCHEMA_FILES,
    WorkflowSchemaError,
    load_definition_schema,
    load_json_schema,
    load_knowledge_item_brief_schema,
    load_role_input_schema,
    load_role_result_schema,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SCHEMA_ROOT = REPOSITORY_ROOT / "schemas/workflow"
RESOURCE_ROOT = files("eom_workflow").joinpath("resources")
EXPECTED_RESOURCES = frozenset(
    path.relative_to(CANONICAL_SCHEMA_ROOT).as_posix()
    for path in CANONICAL_SCHEMA_ROOT.rglob("*.schema.json")
)


def test_workflow_schema_resources_match_canonical_sources() -> None:
    mapped_names = (
        *INPUT_SCHEMA_FILES.values(),
        *INPUT_SCHEMA_FILES_V1_4.values(),
        *RESULT_SCHEMA_FILES.values(),
    )
    assert len(mapped_names) == len(set(mapped_names))
    assert {
        "workflow-definition.schema.json",
        "knowledge-item-brief-v1.schema.json",
        *(f"roles/{name}" for name in mapped_names),
    } <= EXPECTED_RESOURCES
    actual = {
        path.relative_to(Path(str(RESOURCE_ROOT))).as_posix()
        for path in Path(str(RESOURCE_ROOT)).rglob("*.schema.json")
    }
    assert actual == EXPECTED_RESOURCES
    for logical_name in sorted(EXPECTED_RESOURCES):
        assert (
            RESOURCE_ROOT.joinpath(logical_name).read_bytes()
            == (CANONICAL_SCHEMA_ROOT / logical_name).read_bytes()
        )


def test_workflow_schemas_load_from_package_resources() -> None:
    assert load_definition_schema()["$id"].endswith("/workflow-definition.schema.json")
    assert load_knowledge_item_brief_schema()["$id"].endswith("knowledge-item-brief-v1")
    for role in INPUT_SCHEMA_FILES:
        assert load_role_input_schema(role)["$id"].endswith("-input.schema.json")
    for role in INPUT_SCHEMA_FILES_V1_4:
        assert load_role_input_schema(role, "workflow-role/1.4.0")["$id"].endswith(
            "-input-v1.schema.json"
        )
    for schema_id in RESULT_SCHEMA_FILES:
        assert "-result" in load_role_result_schema(schema_id)["$id"]
    for name, _ in control_schema_inventory():
        assert isinstance(load_control_schema(name), dict)


def test_missing_workflow_schema_is_a_typed_resource_error(tmp_path: Path) -> None:
    with pytest.raises(
        WorkflowSchemaError,
        match=(
            r"workflow schema resource unavailable: roles/missing.schema.json "
            r"\(package=eom_workflow, distribution=eom-platform@"
        ),
    ):
        load_json_schema(tmp_path / "missing.schema.json", "roles/missing.schema.json")


@pytest.fixture(scope="module")
def platform_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    wheel_dir = tmp_path_factory.mktemp("workflow-wheel")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(REPOSITORY_ROOT),
        ],
        cwd=wheel_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = tuple(wheel_dir.glob("eom_platform-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def installed_platform(platform_wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("installed-workflow-wheel")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--target",
            str(target),
            str(platform_wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return target


def test_built_wheel_contains_workflow_schemas(platform_wheel: Path) -> None:
    prefix = "eom_workflow/resources/"
    with zipfile.ZipFile(platform_wheel) as archive:
        names = set(archive.namelist())
        packaged = {
            name.removeprefix(prefix)
            for name in names
            if name.startswith(prefix) and name.endswith(".schema.json")
        }
        assert packaged == EXPECTED_RESOURCES
        record_name = next(name for name in names if name.endswith(".dist-info/RECORD"))
        record = archive.read(record_name).decode("utf-8")
        for logical_name in EXPECTED_RESOURCES:
            member = prefix + logical_name
            assert archive.read(member) == (CANONICAL_SCHEMA_ROOT / logical_name).read_bytes()
            assert member in record


def test_installed_wheel_loads_schemas_without_source_checkout(
    installed_platform: Path, tmp_path: Path
) -> None:
    definition = tmp_path / "generic-item-development.v1.1.yaml"
    definition.write_bytes(
        (REPOSITORY_ROOT / "config/workflows/generic-item-development.v1.1.yaml").read_bytes()
    )
    script = """
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository = sys.argv[2]
definition_path = Path(sys.argv[3])
sys.path.insert(0, str(installed_root))

from eom_workflow.compiler import compile_definition
from eom_workflow.control_schemas import control_schema_inventory, load_control_schema
from eom_workflow.schemas import (
    INPUT_SCHEMA_FILES,
    RESULT_SCHEMA_FILES,
    load_definition_schema,
    load_role_input_schema,
    load_role_result_schema,
)

spec = importlib.util.find_spec("eom_workflow")
assert spec is not None and spec.origin is not None
assert Path(spec.origin).resolve().is_relative_to(installed_root)
assert repository not in spec.origin
load_definition_schema()
for role in INPUT_SCHEMA_FILES:
    load_role_input_schema(role)
for schema_id in RESULT_SCHEMA_FILES:
    load_role_result_schema(schema_id)
for name, _ in control_schema_inventory():
    load_control_schema(name)
compiled = compile_definition(
    definition_path,
    {"authoring", "image", "review", "item_management"},
)
assert compiled.definition.definition_key == "generic-item-development"
assert compiled.definition.definition_version == "1.1.0"
print("installed_workflow_wheel_resources=PASS")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(installed_platform),
            str(REPOSITORY_ROOT),
            str(definition),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "installed_workflow_wheel_resources=PASS"


def test_installed_orchestrator_uses_explicit_external_worker_configuration(
    installed_platform: Path, tmp_path: Path
) -> None:
    worker_config = tmp_path / "worker-slots.yaml"
    worker_config.write_bytes((REPOSITORY_ROOT / "config/worker-slots.example.yaml").read_bytes())
    script = """
from __future__ import annotations
import importlib.util
import os
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository = sys.argv[2]
config = Path(sys.argv[3]).resolve()
sys.path.insert(0, str(installed_root))
os.environ["EOM_WORKER_CONFIG"] = str(config)

from eom_orchestrator.doctor import runtime_configuration_check
from eom_orchestrator.runtime_configuration import resolve_worker_configuration
from eom_orchestrator.settings import DEFAULT_WORKER_CONFIG, Settings, WorkerConfigSource

spec = importlib.util.find_spec("eom_orchestrator")
assert spec is not None and spec.origin is not None
assert Path(spec.origin).resolve().is_relative_to(installed_root)
assert repository not in spec.origin
settings = Settings.from_environment()
assert settings.worker_config == config
assert settings.worker_config_source is WorkerConfigSource.ENVIRONMENT
assert DEFAULT_WORKER_CONFIG == Path("/etc/eom/worker-slots.yaml")
assert settings.worker_config != Path(sys.prefix) / "config" / "worker-slots.example.yaml"
resolved = resolve_worker_configuration(settings)
assert resolved.live_worker.slot_id == "01"
assert runtime_configuration_check(settings).passed
print("installed_orchestrator_configuration=PASS")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(installed_platform),
            str(REPOSITORY_ROOT),
            str(worker_config),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "installed_orchestrator_configuration=PASS"


def test_installed_workflow_runner_uses_external_operator_configuration(
    installed_platform: Path, tmp_path: Path
) -> None:
    definition = tmp_path / "generic-item-development.yaml"
    actors = tmp_path / "human-actors.yaml"
    runner = tmp_path / "workflow-runner.yaml"
    prompts = tmp_path / "workflow-prompts"
    definition.write_bytes(
        (REPOSITORY_ROOT / "config/workflows/generic-item-development.v1.2.yaml").read_bytes()
    )
    actors.write_bytes((REPOSITORY_ROOT / "config/human-actors.example.yaml").read_bytes())
    runner.write_bytes((REPOSITORY_ROOT / "config/workflow-runner.example.yaml").read_bytes())
    prompts.mkdir()
    script = """
from __future__ import annotations
import importlib.util
import os
import sys
from pathlib import Path

installed_root = Path(sys.argv[1]).resolve()
repository = sys.argv[2]
definition, actors, runner, prompts = map(Path, sys.argv[3:])
sys.path.insert(0, str(installed_root))
os.environ["EOM_WORKFLOW_DEFINITION"] = str(definition)
os.environ["EOM_HUMAN_ACTOR_CONFIG"] = str(actors)
os.environ["EOM_WORKFLOW_RUNNER_CONFIG"] = str(runner)
os.environ["EOM_WORKFLOW_PROMPT_ROOT"] = str(prompts)

from eom_workflow import compile_definition_data
from eom_workflow_runner.settings import (
    DEFAULT_HUMAN_ACTOR_CONFIG,
    DEFAULT_WORKFLOW_DEFINITION,
    DEFAULT_WORKFLOW_PROMPT_ROOT,
    DEFAULT_WORKFLOW_RUNNER_CONFIG,
    WorkflowSettings,
    load_workflow_yaml,
)

spec = importlib.util.find_spec("eom_workflow_runner")
assert spec is not None and spec.origin is not None
assert Path(spec.origin).resolve().is_relative_to(installed_root)
assert repository not in spec.origin
settings = WorkflowSettings.from_environment()
assert settings.definition_path == definition
assert settings.actor_config_path == actors
assert settings.runner_config_path == runner
assert settings.prompt_root == prompts
assert settings.load_actors().role_for("reviewer_01") == "reviewer"
assert settings.load_runner().command_lease_seconds == 900
compiled = compile_definition_data(
    load_workflow_yaml(settings.definition_path),
    str(settings.definition_path),
    {"authoring", "image", "review", "item_management"},
)
assert compiled.definition.definition_version == "1.2.0"
assert DEFAULT_WORKFLOW_DEFINITION == Path("/etc/eom/workflows/generic-item-development.yaml")
assert DEFAULT_HUMAN_ACTOR_CONFIG == Path("/etc/eom/human-actors.yaml")
assert DEFAULT_WORKFLOW_RUNNER_CONFIG == Path("/etc/eom/workflow-runner.yaml")
assert DEFAULT_WORKFLOW_PROMPT_ROOT == Path("/etc/eom/workflow-prompts")
print("installed_workflow_runner_configuration=PASS")
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(installed_platform),
            str(REPOSITORY_ROOT),
            str(definition),
            str(actors),
            str(runner),
            str(prompts),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "installed_workflow_runner_configuration=PASS"
