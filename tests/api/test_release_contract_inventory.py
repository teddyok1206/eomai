"""Keep the independent wheel boundary aligned with the canonical schema inventory."""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest
from eom_catalog_contracts import catalog_schema_inventory
from eom_workflow import WORKFLOW_ADMISSION_BY_IDENTITY, AgentStep
from eom_workflow.compiler import compile_definition
from eom_workflow.definition_execution_protocol import definition_execution_protocol

ROOT = Path(__file__).resolve().parents[2]


def release_inspector_source() -> str:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index("inspect_release() {")
    python_start = script.index("<<'PY'\n", start) + len("<<'PY'\n")
    python_end = script.index("\nPY\n", python_start)
    return script[python_start:python_end]


def installed_workflow_inspector_source() -> str:
    value = next(
        node.value.value
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "check"
        and isinstance(node.value, ast.Constant)
    )
    assert isinstance(value, str)
    return value


def test_embedded_release_inspector_has_no_undefined_names() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F821",
            "--stdin-filename",
            "release-inspector.py",
            "-",
        ],
        input=release_inspector_source(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_installed_release_compares_generated_routes_not_only_snapshot_hashes() -> None:
    source = installed_workflow_inspector_source()
    tree = ast.parse(source)
    comparisons = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
    assert any(
        isinstance(node.left, ast.Name)
        and node.left.id == "generated_openapi"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "packaged_openapi"
        for node in comparisons
    )
    assert "generated_openapi = create_app(contract_services).openapi()" in source
    assert '"postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid"' in source
    assert "contract_services.engine.dispose()" in source


def test_model_selection_runtime_is_required_in_release_wheel_inventory() -> None:
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"required_contract_runtime", "control_plane_runtime"}
        and isinstance(node.value, ast.Set)
    }
    assert "eom_api_contracts/preset_model_selection.py" in assignments["required_contract_runtime"]
    assert {
        "eom_orchestrator/preset_model_evidence.py",
        "eom_orchestrator/preset_model_release.py",
        "eom_orchestrator/preset_model_selection.py",
        "eom_orchestrator/preset_model_validation.py",
        "eom_orchestrator/preset_model_validation_processor.py",
        "eom_orchestrator/preset_policy.py",
        "eom_workflow/preset_model_validation.py",
    } <= assignments["control_plane_runtime"]


def test_query_preparation_http_runtime_is_required_in_release_wheels() -> None:
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"required", "required_contract_runtime"}
        and isinstance(node.value, ast.Set)
    }
    assert {
        "eom_api/routers/reference_queries.py",
        "eom_api/services/reference_query_preparation.py",
        "eom_api/services/reference_query_prepare_client.py",
    } <= assignments["required"]
    assert "eom_api_contracts/reference_queries.py" in assignments["required_contract_runtime"]


def test_async_reference_item_runtime_is_required_in_release_wheels() -> None:
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"required", "required_contract_runtime"}
        and isinstance(node.value, ast.Set)
    }
    assert {
        "eom_api/services/reference_item_start.py",
        "eom_api/services/reference_item_start_ports.py",
        "eom_api/services/reference_item_preparation.py",
    } <= assignments["required"]
    assert (
        "eom_api_contracts/workflow_reference_start.py" in assignments["required_contract_runtime"]
    )


def test_transfer_source_candidate_is_complete_in_release_runtime_inventory() -> None:
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id
        in {
            "required",
            "required_contract_runtime",
            "control_plane_runtime",
            "catalog_staging_runtime",
        }
        and isinstance(node.value, ast.Set)
    }
    assert {
        "eom_api/routers/inference_transfer.py",
        "eom_api/services/inference_transfer_snapshot.py",
        "eom_api/services/inference_transfer_snapshot_port.py",
        "eom_api/services/inference_transfer_snapshot_client.py",
        "eom_api/services/inference_transfer_snapshot_staging.py",
        "eom_api/services/inference_transfer_submission.py",
        "eom_api/services/inference_transfer_start_adapter.py",
        "eom_api/services/inference_transfer_workflow_client.py",
        "eom_api/services/inference_transfer_workflow_read.py",
    } <= assignments["required"]
    assert "eom_api_contracts/inference_transfer.py" in assignments["required_contract_runtime"]
    for package, source_root, inventory in (
        ("eom_workflow", "packages/workflow/eom_workflow", "control_plane_runtime"),
        (
            "eom_workflow_runner",
            "services/workflow_runner/eom_workflow_runner",
            "control_plane_runtime",
        ),
        ("eom_orchestrator", "services/orchestrator/eom_orchestrator", "control_plane_runtime"),
        (
            "eom_catalog_contracts",
            "packages/catalog_contracts/eom_catalog_contracts",
            "catalog_staging_runtime",
        ),
        (
            "eom_catalog_service",
            "services/catalog_service/eom_catalog_service",
            "catalog_staging_runtime",
        ),
    ):
        expected = {
            f"{package}/{path.name}"
            for path in (ROOT / source_root).glob("*inference_transfer*.py")
        }
        assert expected and expected <= assignments[inventory]
    assert {
        "eom_workflow_runner/role_execution_port.py",
        "eom_workflow_runner/role_execution_binding.py",
        "eomctl/inference_transfer_controls.py",
    } <= assignments["control_plane_runtime"]


def test_transfer_owner_api_contract_dependency_is_optional() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert metadata["optional-dependencies"]["inference-transfer"] == ["eom-api-contracts==0.1.0"]
    assert not any(name.startswith("eom-api-contracts") for name in metadata["dependencies"])


def test_installed_support_admission_covers_materialized_workflow_contracts() -> None:
    outer = ast.parse(release_inspector_source())
    fixed_families = {
        "pdf-document-review",
        "legacy-item-extraction",
        "legacy-item-editorial-compatibility",
        "customer-support",
        "item-inference-transfer-comparison",
        "local-embedding-index",
        "local-embedding-reference-query",
        "local-embedding-private-chat-query",
    }
    fixed_prefixes = tuple(f"{name}." for name in sorted(fixed_families))
    staged = {
        assignment.targets[0].id: ROOT / "config/workflows" / assignment.value.right.value
        for assignment in ast.walk(outer)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.targets[0], ast.Name)
        and isinstance(assignment.value, ast.BinOp)
        and isinstance(assignment.value.right, ast.Constant)
        and isinstance(assignment.value.right.value, str)
        and assignment.value.right.value.startswith(fixed_prefixes)
    }
    check = installed_workflow_inspector_source()
    inner = ast.parse(check)
    admitted = next(
        assignment.value
        for assignment in ast.walk(inner)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "admitted_definitions"
    )
    admitted_names = {node.id for node in ast.walk(admitted) if isinstance(node, ast.Name)}
    launch = next(
        call.args[0]
        for call in ast.walk(outer)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "run"
        and call.args
        and isinstance(call.args[0], ast.List)
        and any(isinstance(value, ast.Name) and value.id == "check" for value in call.args[0].elts)
    )
    parsed = next(
        assignment.targets[0]
        for assignment in ast.walk(inner)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.targets[0], ast.Tuple)
        and isinstance(assignment.value, ast.Subscript)
        and ast.unparse(assignment.value) == "sys.argv[2:]"
    )
    launch_names = {node.id for node in ast.walk(launch) if isinstance(node, ast.Name)}
    parsed_names = {node.id for node in ast.walk(parsed) if isinstance(node, ast.Name)}
    assert staged.keys() <= admitted_names & launch_names & parsed_names
    actual = {}
    for path in staged.values():
        definition = compile_definition(path, {"support"}).definition
        actual[(definition.definition_key, definition.definition_version)] = (
            definition_execution_protocol(definition)
        )
    expected = {
        identity: admission.role_protocol_version
        for identity, admission in WORKFLOW_ADMISSION_BY_IDENTITY.items()
        if identity[0] in fixed_families
    }
    assert actual == expected


def test_actual_installed_admission_comparison_rejects_an_omitted_private_graph() -> None:
    """Run only the real pure compiler/comparison, never wheel installation or deployment."""
    outer = ast.parse(release_inspector_source())
    bindings = {
        node.targets[0].id: str(ROOT / "config/workflows" / node.value.right.value)
        for node in ast.walk(outer)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.BinOp)
        and isinstance(node.value.left, ast.Name)
        and node.value.left.id == "root"
        and isinstance(node.value.right, ast.Constant)
        and isinstance(node.value.right.value, str)
        and node.value.right.value.endswith(".yaml")
    }
    for version in range(1, 17):
        bindings[f"definition_v1_{version}"] = str(
            ROOT / f"config/workflows/generic-item-development.v1.{version}.yaml"
        )
    for version in range(1, 11):
        bindings[f"analysis_v{version}"] = str(
            ROOT / f"config/workflows/knowledge-analysis.v{version}.yaml"
        )
    inner = ast.parse(installed_workflow_inspector_source())
    assignment = next(
        node
        for node in inner.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "admitted_definitions"
    )
    comparison = next(
        node
        for node in inner.body
        if isinstance(node, ast.If) and "WORKFLOW_ADMISSION_BY_IDENTITY" in ast.unparse(node.test)
    )
    namespace = {
        "Path": Path,
        "compile_definition": compile_definition,
        "definition_execution_protocol": definition_execution_protocol,
        "WORKFLOW_ADMISSION_BY_IDENTITY": WORKFLOW_ADMISSION_BY_IDENTITY,
        **bindings,
    }
    exec(
        compile(ast.Module(body=[assignment, comparison], type_ignores=[]), "admission", "exec"),
        namespace,
    )
    omitted = deepcopy(assignment)
    assert isinstance(omitted.value, ast.Tuple)
    count = len(omitted.value.elts)
    omitted.value.elts = [
        value
        for value in omitted.value.elts
        if not any(
            isinstance(node, ast.Name) and node.id == "private_chat_query_definition"
            for node in ast.walk(value)
        )
    ]
    assert len(omitted.value.elts) == count - 1
    with pytest.raises(SystemExit, match="admission policy does not match"):
        exec(
            compile(
                ast.Module(body=[omitted, comparison], type_ignores=[]),
                "omitted private admission",
                "exec",
            ),
            namespace,
        )


@pytest.mark.parametrize(
    ("filename", "variable", "protocol"),
    (
        ("local-embedding-index.v1.yaml", "local_embedding_definition", "local-embedding/1.0"),
        (
            "local-embedding-reference-query.v1.yaml",
            "reference_query_definition",
            "reference-query/1.0",
        ),
        (
            "local-embedding-private-chat-query.v1.yaml",
            "private_chat_query_definition",
            "private-chat-query/1.0",
        ),
    ),
)
def test_installed_admission_uses_native_definition_protocol_without_codex_role(
    filename: str, variable: str, protocol: str
) -> None:
    """Application-only definitions must be inspected, not omitted or inferred as a role."""
    compiled = compile_definition(ROOT / "config/workflows" / filename, set())
    assert not any(isinstance(step, AgentStep) for step in compiled.definition.steps)
    assert definition_execution_protocol(compiled.definition) == protocol
    source = installed_workflow_inspector_source()
    assert "definition_execution_protocol(compiled.definition)" in source
    assert f"compile_definition(Path({variable}), set())" in source


def test_wheel_catalog_resource_inventory_matches_canonical_contracts() -> None:
    registry = ROOT / "packages/catalog_contracts/eom_catalog_contracts/validation.py"
    actual = catalog_inventory_reader()(registry.read_text())
    expected = {
        resource.resource_path.removeprefix("resources/"): resource.canonical_path
        for _, resource in catalog_schema_inventory()
    }
    assert actual == expected
    assert {
        "knowledge/item-inference-transfer-invocation-v1_1.schema.json",
        "knowledge/item-inference-transfer-pair-result-v1_1.schema.json",
        "knowledge/item-inference-transfer-workflow-binding-v1_1.schema.json",
    } <= actual.keys()


def catalog_inventory_reader() -> Callable[[str], dict[str, str]]:
    function = next(
        node
        for node in ast.parse(release_inspector_source()).body
        if isinstance(node, ast.FunctionDef) and node.name == "catalog_resources_from_registry"
    )
    namespace: dict[str, object] = {"ast": ast}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "Catalog inventory", "exec"),
        namespace,
    )
    return cast(Callable[[str], dict[str, str]], namespace[function.name])


def test_catalog_inventory_reads_only_registry_data_and_accepts_additive_resources() -> None:
    source = """
raise RuntimeError("source module must never execute")
CATALOG_SCHEMA_RESOURCES: Mapping[str, CatalogSchemaResource] = MappingProxyType({
    "successor": CatalogSchemaResource(
        "schemas/knowledge/successor.schema.json",
        "resources/knowledge/successor.schema.json", "2.0", "sha256:synthetic"
    ),
})
"""
    assert catalog_inventory_reader()(source) == {
        "knowledge/successor.schema.json": "schemas/knowledge/successor.schema.json"
    }


@pytest.mark.parametrize(
    "source",
    (
        "CATALOG_SCHEMA_RESOURCES = {}",
        "CATALOG_SCHEMA_RESOURCES: object = mutable_registry()",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType([])",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({**other_registry})",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': arbitrary_resource()})",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': "
        "CatalogSchemaResource('../bad', 'resources/good', '1', 'hash')})",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': "
        "CatalogSchemaResource('schemas/good', '../bad', '1', 'hash')})",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': "
        "CatalogSchemaResource('schemas/../../bad', 'resources/good', '1', 'hash')})",
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': "
        "CatalogSchemaResource('schemas/good', 'resources/../bad', '1', 'hash')})",
    ),
)
def test_catalog_inventory_rejects_nonliteral_or_missing_source_registry(source: str) -> None:
    with pytest.raises(SystemExit, match="Catalog Contract source"):
        catalog_inventory_reader()(source)


def test_catalog_inventory_never_executes_resource_expressions(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-be-created"
    source = (
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({'x': CatalogSchemaResource("
        f"__import__('pathlib').Path({str(marker)!r}).touch(), "
        "'resources/good', '1', 'hash')})"
    )
    with pytest.raises(ValueError, match="malformed node"):
        catalog_inventory_reader()(source)
    assert not marker.exists()


def test_catalog_inventory_rejects_duplicate_family_and_conflicting_resource_identity() -> None:
    resource = "CatalogSchemaResource('schemas/good', 'resources/good', '1', 'hash')"
    duplicate = (
        f"CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({{'x': {resource}, 'x': {resource}}})"
    )
    with pytest.raises(SystemExit, match="family identity"):
        catalog_inventory_reader()(duplicate)
    conflict = (
        "CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({"
        f"'x': {resource}, "
        "'y': CatalogSchemaResource('schemas/other', 'resources/good', '1', 'hash')})"
    )
    with pytest.raises(SystemExit, match="resource identity conflicts"):
        catalog_inventory_reader()(conflict)
    alias = (
        f"CATALOG_SCHEMA_RESOURCES: object = MappingProxyType({{'x': {resource}, 'y': {resource}}})"
    )
    assert catalog_inventory_reader()(alias) == {"good": "schemas/good"}


def test_installed_catalog_inventory_is_compared_with_the_authoritative_source() -> None:
    check = installed_workflow_inspector_source()
    inner = ast.parse(check)
    assignment = next(
        node
        for node in inner.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "installed_catalog_resources"
    )
    expression = compile(ast.Expression(assignment.value), "installed Catalog inventory", "eval")
    actual = eval(expression, {"catalog_schema_inventory": catalog_schema_inventory})
    registry = ROOT / "packages/catalog_contracts/eom_catalog_contracts/validation.py"
    assert actual == catalog_inventory_reader()(registry.read_text())
    assert "installed_catalog_resources != json.loads(expected_catalog_resources_json)" in check
    assert "expected_catalog_resources_json" in ast.unparse(inner)
    required = next(
        ast.literal_eval(node)
        for node in ast.walk(inner)
        if isinstance(node, ast.Set)
        and any(
            isinstance(value, ast.Constant)
            and value.value == "item-inference-transfer-pair-result-v1.1"
            for value in node.elts
        )
    )
    assert {
        "item-inference-transfer",
        "item-inference-transfer-invocation",
        "item-inference-transfer-workflow-binding",
        "item-inference-transfer-invocation-v1.1",
        "item-inference-transfer-pair-result-v1.1",
        "item-inference-transfer-workflow-binding-v1.1",
    } <= required


def test_installed_transfer_successor_loads_exact_protocol_and_control_families() -> None:
    check = installed_workflow_inspector_source()
    inner = ast.parse(check)
    loaded = {
        tuple(ast.literal_eval(arg) for arg in node.args)
        for node in ast.walk(inner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_role_input_schema"
        and all(isinstance(arg, ast.Constant) for arg in node.args)
    }
    assert {("support", "workflow-role/1.29.0"), ("support", "workflow-role/1.30.0")} <= loaded
    required = next(
        ast.literal_eval(node)
        for node in ast.walk(inner)
        if isinstance(node, ast.Set)
        and any(
            isinstance(value, ast.Constant)
            and value.value == "inference-transfer-control-bootstrap"
            for value in node.elts
        )
    )
    assert {
        "inference-transfer-control-bootstrap",
        "inference-transfer-control-bootstrap-v1.1",
        "inference-transfer-control-invocation",
        "inference-transfer-control-invocation-v1.1",
        "resolved-execution-plan-v21",
        "resolved-execution-plan-v22",
    } <= required


def test_wheel_api_schema_inventory_has_one_canonical_source(tmp_path: Path) -> None:
    source = release_inspector_source()
    tree = ast.parse(source)
    assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "expected_api_schemas"
    )
    assert isinstance(assignment.value, ast.SetComp)
    expression = compile(ast.Expression(assignment.value), "API schema inventory", "eval")
    actual = eval(
        expression,
        {"canonical_api_root": ROOT / "schemas/api/v1"},
    )
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas"
    assert actual == {
        "eom_api_contracts/schemas/" + path.name
        for path in (ROOT / "schemas/api/v1").glob("*.schema.json")
    }
    assert "eom_api_contracts/schemas/general-chat-v1.schema.json" in actual
    for path in packaged.glob("*.schema.json"):
        assert "eom_api_contracts/schemas/" + path.name in actual
        assert path.read_bytes() == (ROOT / "schemas/api/v1" / path.name).read_bytes()
    # The builder stages all canonical files, including base contracts that are
    # not checked in twice. New files must not require editing a second list.
    (tmp_path / "successor.schema.json").write_bytes(b"{}")
    assert eval(expression, {"canonical_api_root": tmp_path}) == {
        "eom_api_contracts/schemas/successor.schema.json"
    }


def test_chat_wheel_runtime_inventory_uses_canonical_module_roots(tmp_path: Path) -> None:
    tree = ast.parse(release_inspector_source())
    assignment = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "chat_runtime"
    )
    expression = compile(ast.Expression(assignment.value), "chat runtime inventory", "eval")
    context = {
        "chat_source_root": ROOT / "services/orchestrator/eom_orchestrator",
        "chat_protocol_root": ROOT / "packages/protocol/eom_protocol",
    }
    expected = {
        prefix + path.name
        for key, prefix in (
            ("chat_source_root", "eom_orchestrator/"),
            ("chat_protocol_root", "eom_protocol/"),
        )
        for path in context[key].glob("general_chat*.py")
    }
    actual = eval(expression, context)
    assert actual == expected
    assert "eom_protocol/general_chat_worker_messages.py" in actual
    assert "eom_orchestrator/general_chat_worker_client.py" in actual
    source, protocol = tmp_path / "source", tmp_path / "protocol"
    source.mkdir()
    protocol.mkdir()
    (source / "general_chat_successor.py").write_text("# synthetic successor\n")
    (protocol / "general_chat_successor.py").write_text("# synthetic successor\n")
    assert eval(expression, {"chat_source_root": source, "chat_protocol_root": protocol}) == {
        "eom_orchestrator/general_chat_successor.py",
        "eom_protocol/general_chat_successor.py",
    }


def test_privileged_migration_preflight_is_read_only_for_git_index(tmp_path: Path) -> None:
    source = (ROOT / "scripts/api/migrate_release.sh").read_text()
    assert 'git --no-optional-locks -C "${REPOSITORY_ROOT}" status --porcelain' in source
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("original\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    index = tmp_path / ".git/index"
    before = index.stat(), index.read_bytes()
    tracked.touch()
    subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(tmp_path),
            "status",
            "--porcelain",
        ],
        check=True,
        capture_output=True,
    )
    assert (index.stat(), index.read_bytes()) == before
