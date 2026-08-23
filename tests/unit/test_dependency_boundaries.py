from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _imports(root: Path) -> set[str]:
    imported: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def _assert_prefixes_absent(imported: set[str], forbidden: tuple[str, ...]) -> None:
    violations = sorted(
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    )
    assert violations == []


def test_domain_and_platform_packages_do_not_import_catalog_infrastructure() -> None:
    forbidden = (
        "eom_catalog_service",
        "eom_content_intake",
        "eom_content_pack",
        "eom_item_registry",
    )
    for relative_root in (
        "packages/protocol",
        "packages/workflow",
        "packages/catalog_contracts",
        "services/orchestrator",
    ):
        _assert_prefixes_absent(_imports(REPOSITORY_ROOT / relative_root), forbidden)


def test_production_runtime_does_not_import_dev_reporter_or_observer() -> None:
    forbidden = ("eom_dev_reporter", "eom_observe", "eom_observe_contracts")
    for relative_root in (
        "packages/protocol",
        "packages/workflow",
        "services/orchestrator",
        "services/workflow_runner",
        "services/catalog_service",
        "apps/eomctl",
    ):
        _assert_prefixes_absent(_imports(REPOSITORY_ROOT / relative_root), forbidden)


def test_catalog_persistence_contains_no_large_binary_columns() -> None:
    persistence_sources = [
        REPOSITORY_ROOT / "services/catalog_service/eom_catalog_service/models.py",
        REPOSITORY_ROOT / "migrations/versions/20260817_0004_content_intake_pack.py",
        REPOSITORY_ROOT / "migrations/versions/20260817_0005_add_item_registry_and_usage_ledger.py",
    ]
    forbidden = ("LargeBinary", "BYTEA", "BLOB")
    for path in persistence_sources:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
