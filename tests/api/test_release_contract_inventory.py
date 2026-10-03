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


def test_installed_review_admission_covers_materialized_workflow_contracts() -> None:
    outer = ast.parse(release_inspector_source())
    staged = {
        assignment.targets[0].id: ROOT / "config/workflows" / assignment.value.right.value
        for assignment in ast.walk(outer)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.targets[0], ast.Name)
        and isinstance(assignment.value, ast.BinOp)
        and isinstance(assignment.value.right, ast.Constant)
        and isinstance(assignment.value.right.value, str)
        and assignment.value.right.value.startswith("pdf-document-review.")
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
        if identity[0] == "pdf-document-review"
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
