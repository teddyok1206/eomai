"""Keep the independent wheel boundary aligned with the canonical schema inventory."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from eom_catalog_contracts import catalog_schema_inventory
from eom_workflow import WORKFLOW_ADMISSION_BY_IDENTITY, AgentStep
from eom_workflow.compiler import compile_definition
from eom_workflow.schemas import result_schema_protocol

ROOT = Path(__file__).resolve().parents[2]


def release_inspector_source() -> str:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index("inspect_release() {")
    python_start = script.index("<<'PY'\n", start) + len("<<'PY'\n")
    python_end = script.index("\nPY\n", python_start)
    return script[python_start:python_end]


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


def test_transfer_source_candidate_is_complete_in_release_runtime_inventory() -> None:
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(ast.parse(release_inspector_source()))
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"required", "control_plane_runtime", "catalog_staging_runtime"}
        and isinstance(node.value, ast.Set)
    }
    assert {
        "eom_api/routers/inference_transfer.py",
        "eom_api/services/inference_transfer_snapshot.py",
        "eom_api/services/inference_transfer_snapshot_port.py",
        "eom_api/services/inference_transfer_snapshot_client.py",
    } <= assignments["required"]
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
    } <= assignments["control_plane_runtime"]


def test_installed_support_admission_covers_materialized_workflow_contracts() -> None:
    outer = ast.parse(release_inspector_source())
    fixed_families = {
        "pdf-document-review",
        "legacy-item-extraction",
        "legacy-item-editorial-compatibility",
        "customer-support",
        "item-inference-transfer-comparison",
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
    check = next(
        assignment.value.value
        for assignment in ast.walk(outer)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "check"
        and isinstance(assignment.value, ast.Constant)
    )
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
        protocols = {
            result_schema_protocol(step.result_schema)
            for step in definition.steps
            if isinstance(step, AgentStep)
        }
        assert len(protocols) == 1
        actual[(definition.definition_key, definition.definition_version)] = protocols.pop()
    expected = {
        identity: admission.role_protocol_version
        for identity, admission in WORKFLOW_ADMISSION_BY_IDENTITY.items()
        if identity[0] in fixed_families
    }
    assert actual == expected


def test_wheel_catalog_resource_inventory_matches_canonical_contracts() -> None:
    script = (ROOT / "scripts/api/deploy_release.sh").read_text()
    start = script.index("catalog_resources = {")
    end = script.index("\n}\n", start) + len("\n}")
    assignment = ast.parse(script[start:end]).body[0]
    assert isinstance(assignment, ast.Assign)
    actual = ast.literal_eval(assignment.value)
    expected = {
        resource.resource_path.removeprefix("resources/"): resource.canonical_path
        for _, resource in catalog_schema_inventory()
    }
    assert actual == expected


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
