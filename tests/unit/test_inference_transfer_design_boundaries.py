from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PURE_MODULES = (
    "packages/catalog_contracts/eom_catalog_contracts/item_inference_transfer.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_experiment.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_snapshot.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_snapshot_binding.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_metadata.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_human_review.py",
    "packages/catalog_contracts/eom_catalog_contracts/inference_transfer_text.py",
    "packages/workflow/eom_workflow/inference_transfer.py",
    "packages/workflow/eom_workflow/inference_transfer_control.py",
    "packages/workflow/eom_workflow/inference_transfer_bootstrap_contract.py",
    "packages/workflow/eom_workflow/inference_transfer_control_invocation.py",
    "packages/workflow/eom_workflow/inference_transfer_materialization.py",
    "packages/workflow/eom_workflow/inference_transfer_workflow.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_comparison.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_evaluation.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_experiment.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_ports.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_projection.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_item_projection.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_service.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_snapshot_service.py",
    "services/orchestrator/eom_orchestrator/inference_transfer_snapshot_staging.py",
    "services/orchestrator/eom_orchestrator/inference_transfer_human_review.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_scope.py",
    "services/catalog_service/eom_catalog_service/inference_transfer_vectors.py",
)


def test_user_requested_verbatim_design_is_unchanged() -> None:
    original = ROOT / "docs/architecture/ITEM_INFERENCE_TRANSFER_DESIGN_ORIGINAL.md"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == (
        "f4adc8c7cf8197f3d310f8bb3463b79b54229dae6e2257b0b1c39005c7632e4a"
    )


@pytest.mark.parametrize("relative", PURE_MODULES)
def test_transfer_pure_values_and_use_cases_do_not_import_infrastructure(relative: str) -> None:
    # Keep optional numerical/SQL/filesystem ownership in adapters, not the new core.
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
    forbidden = {
        "sqlalchemy",
        "psycopg",
        "subprocess",
        "pathlib",
        "requests",
        "urllib",
        "torch",
        "transformers",
        "numpy",
        "eom_catalog_service.inference_transfer_catalog_adapter",
        "eom_catalog_service.local_embedding_adapter",
        "eom_orchestrator.database",
        "eom_orchestrator.artifacts",
        "eom_orchestrator.orchestrator",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    }, relative


def test_embedding_dependencies_are_not_added_to_platform_core() -> None:
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]
    assert not any(
        dependency.lower().startswith(("torch", "transformers", "sentence-transformers", "numpy"))
        for dependency in dependencies
    )


def test_all_29_predecessor_workflow_bundle_hashes_remain_unchanged() -> None:
    from eom_identifiers import content_sha256
    from eom_workflow.schemas import role_schema_bundle_hash

    # Read and cross-checked against the installed API wheel on 2026-10-10.
    # Include an explicit predecessor set, not a mutable "all except latest" rule.
    versions = ("workflow-role/1.0.1", *(f"workflow-role/1.{number}.0" for number in range(1, 29)))
    assert content_sha256({version: role_schema_bundle_hash(version) for version in versions}) == (
        "sha256:9ef59f0a5a690f886d45cd51be59debe69b53b410fc86818a94a3193b6c49c5d"
    )
