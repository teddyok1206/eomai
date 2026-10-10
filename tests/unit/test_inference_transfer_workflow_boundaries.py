from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "relative",
    (
        "packages/workflow/eom_workflow/inference_transfer_workflow.py",
        "services/workflow_runner/eom_workflow_runner/inference_transfer_admission.py",
    ),
)
def test_wrapper_and_pure_admission_have_no_infrastructure_or_execution_dependency(
    relative: str,
) -> None:
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    forbidden = (
        "sqlalchemy",
        "psycopg",
        "subprocess",
        "pathlib",
        "requests",
        "urllib",
        "eom_orchestrator",
        "eom_catalog_service",
        "eom_workflow_runner.engine",
        "eom_workflow_runner.repository",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {
        value
        for value in imported
        if any(value == prefix or value.startswith(prefix + ".") for prefix in forbidden)
    }
