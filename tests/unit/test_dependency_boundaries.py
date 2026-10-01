from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_KINDS = ("packages", "services", "apps")
RUNTIME_COMPOSITION_CLUSTER = frozenset(
    {
        "eom_catalog_service",
        "eom_identity_service",
        "eom_orchestrator",
        "eom_workflow_runner",
    }
)


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


def _first_party_roots() -> dict[str, tuple[str, Path]]:
    roots: dict[str, tuple[str, Path]] = {}
    for kind in SOURCE_KINDS:
        for path in sorted((REPOSITORY_ROOT / kind).glob("*/eom_*")):
            if path.is_dir():
                roots[path.name] = (kind, path)
    return roots


def _strongly_connected_components(edges: dict[str, set[str]]) -> tuple[frozenset[str], ...]:
    """Return package cycles in O(V + E) without adding a runtime dependency."""

    next_index = 0
    indexes: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[frozenset[str]] = []

    def visit(node: str) -> None:
        nonlocal next_index
        indexes[node] = next_index
        low_links[node] = next_index
        next_index += 1
        stack.append(node)
        on_stack.add(node)
        for target in edges[node]:
            if target not in indexes:
                visit(target)
                low_links[node] = min(low_links[node], low_links[target])
            elif target in on_stack:
                low_links[node] = min(low_links[node], indexes[target])
        if low_links[node] != indexes[node]:
            return
        component: set[str] = set()
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.add(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(frozenset(component))

    for node in sorted(edges):
        if node not in indexes:
            visit(node)
    return tuple(components)


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


def test_all_contract_and_domain_packages_remain_below_runtime_infrastructure() -> None:
    roots = _first_party_roots()
    runtime_roots = tuple(
        sorted(name for name, (kind, _path) in roots.items() if kind in {"services", "apps"})
    )
    infrastructure_roots = (
        *runtime_roots,
        "httpx",
        "psycopg",
        "requests",
        "sqlalchemy",
        "subprocess",
    )
    for _name, (kind, path) in roots.items():
        if kind == "packages":
            _assert_prefixes_absent(_imports(path), infrastructure_roots)


def test_services_never_depend_on_application_entrypoints() -> None:
    roots = _first_party_roots()
    application_roots = tuple(
        sorted(name for name, (kind, _path) in roots.items() if kind == "apps")
    )
    for _name, (kind, path) in roots.items():
        if kind == "services":
            _assert_prefixes_absent(_imports(path), application_roots)


def test_first_party_cycles_cannot_expand_beyond_the_reviewed_composition_cluster() -> None:
    roots = _first_party_roots()
    edges: dict[str, set[str]] = defaultdict(set)
    for source, (_kind, path) in roots.items():
        edges[source].update(target for target in _imports(path) if target in roots)
    cycles = _strongly_connected_components(edges)
    assert all(cycle <= RUNTIME_COMPOSITION_CLUSTER for cycle in cycles), cycles
    assert all(all(roots[name][0] == "services" for name in cycle) for cycle in cycles), cycles


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
