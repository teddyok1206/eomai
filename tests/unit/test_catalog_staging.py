from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from eom_catalog_service.errors import CatalogError, CatalogErrorCode
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import (
    CATALOG_FIXED_STAGING_ROOTS,
    CatalogSettings,
    CatalogStagingArea,
)
from eom_catalog_service.staging import (
    stage_content_team_item_materialization,
    stage_registry_item_content,
    stage_registry_manifest,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

ROOT = Path(__file__).resolve().parents[2]


def _settings(tmp_path: Path) -> CatalogSettings:
    catalog = tmp_path / "catalog"
    catalog.mkdir(mode=0o750)
    catalog.chmod(0o750)
    for definition in CATALOG_FIXED_STAGING_ROOTS:
        path = definition.path_beneath(catalog)
        path.mkdir(mode=0o750)
        path.chmod(0o750)
    return CatalogSettings(
        staging_root=catalog,
        nas_artifact_root=tmp_path / "artifacts",
        intake_root=tmp_path / "intake",
        placeholder_pack_source=tmp_path / "pack",
    )


def test_fixed_catalog_staging_inventory_is_complete_and_unique() -> None:
    assert tuple(definition.area for definition in CATALOG_FIXED_STAGING_ROOTS) == (
        CatalogStagingArea.CONTENT_PACKS,
        CatalogStagingArea.REGISTRY,
        CatalogStagingArea.WORKFLOW_PROMPTS,
    )
    assert len({definition.area for definition in CATALOG_FIXED_STAGING_ROOTS}) == 3
    assert len({definition.check_name for definition in CATALOG_FIXED_STAGING_ROOTS}) == 3
    assert len({definition.failure_code for definition in CATALOG_FIXED_STAGING_ROOTS}) == 3


def test_catalog_runtime_code_has_no_literal_fixed_root_bypass() -> None:
    service_root = ROOT / "services/catalog_service/eom_catalog_service"
    bypasses: list[str] = []
    for source_path in service_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
                continue
            if not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, str):
                continue
            left = node.left
            if isinstance(left, ast.Attribute) and left.attr == "staging_root":
                bypasses.append(f"{source_path}:{node.lineno}:{node.right.value}")
    assert bypasses == []


def test_registry_manifest_uses_prepared_fixed_root(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    manifest_path = stage_registry_manifest(
        settings,
        "registry-" + "1" * 64,
        {"schema_version": "1.0", "placeholder": True},
    )

    assert manifest_path.parent.parent == settings.registry_staging_root
    assert manifest_path.lstat().st_mode & 0o777 == 0o640
    assert manifest_path.read_bytes() == canonical_json_bytes(
        {"schema_version": "1.0", "placeholder": True}
    )


@pytest.mark.parametrize("mode", [0o550, 0o755])
def test_registry_manifest_rejects_invalid_fixed_root_mode(tmp_path: Path, mode: int) -> None:
    settings = _settings(tmp_path)
    settings.registry_staging_root.chmod(mode)

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(settings, "registry-" + "2" * 64, {"schema_version": "1.0"})

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not (settings.registry_staging_root / ("registry-" + "2" * 64)).exists()


def test_registry_manifest_rejects_missing_fixed_root_without_creating_it(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.registry_staging_root.rmdir()

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(settings, "registry-" + "3" * 64, {"schema_version": "1.0"})

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not settings.registry_staging_root.exists()


def test_registry_service_reports_typed_staging_failure_without_partial_manifest(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.registry_staging_root.chmod(0o550)
    service = object.__new__(RegistryService)
    service.settings = settings
    registration_key = "registry-" + "a" * 64

    with pytest.raises(CatalogError) as captured:
        service._stage_registration_manifest(
            registration_key,
            {"schema_version": "1.0"},
        )

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not (settings.registry_staging_root / registration_key).exists()


def test_registry_manifest_rejects_fixed_root_symlink(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.registry_staging_root.rmdir()
    settings.registry_staging_root.symlink_to(settings.content_pack_staging_root)

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(settings, "registry-" + "4" * 64, {"schema_version": "1.0"})

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not list(settings.content_pack_staging_root.iterdir())


@pytest.mark.parametrize(
    "registration_key",
    ("../escape", "registry key", "registry/key", "registry.$(id)", ""),
)
def test_registry_manifest_rejects_unsafe_operation_identity(
    tmp_path: Path,
    registration_key: str,
) -> None:
    settings = _settings(tmp_path)

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(settings, registration_key, {"schema_version": "1.0"})

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not list(settings.registry_staging_root.iterdir())


def test_registry_manifest_never_overwrites_existing_operation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    registration_key = "registry-" + "5" * 64
    first = stage_registry_manifest(
        settings,
        registration_key,
        {"schema_version": "1.0", "value": "first"},
    )
    first_bytes = first.read_bytes()

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(
            settings,
            registration_key,
            {"schema_version": "1.0", "value": "second"},
        )

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert first.read_bytes() == first_bytes
    assert os.path.samefile(first.parent, settings.registry_staging_root / registration_key)


def test_registry_manifest_serialization_failure_leaves_no_partial_operation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    registration_key = "registry-" + "6" * 64

    with pytest.raises(CatalogError) as captured:
        stage_registry_manifest(
            settings,
            registration_key,
            {"schema_version": "1.0", "forbidden_float": 1.5},
        )

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert not (settings.registry_staging_root / registration_key).exists()


def test_registry_item_content_staging_is_hash_keyed_and_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    content = {"schema_version": "1.0", "title": "검토된 문항"}

    first, first_hash = stage_registry_item_content(settings, content)
    second, second_hash = stage_registry_item_content(settings, content)

    assert first == second
    assert first_hash == second_hash == content_sha256(content)
    assert first.parent.name == f"item-content-{first_hash.removeprefix('sha256:')}"
    assert first.lstat().st_mode & 0o777 == 0o640
    assert first.read_bytes() == canonical_json_bytes(content)


def test_registry_item_content_staging_rejects_stale_or_unsafe_materialization(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    content = {"schema_version": "1.0", "title": "검토된 문항"}
    path, _ = stage_registry_item_content(settings, content)
    path.chmod(0o600)

    with pytest.raises(CatalogError) as captured:
        stage_registry_item_content(settings, content)

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
    assert path.lstat().st_mode & 0o777 == 0o600


def test_content_team_staging_keeps_json_and_markdown_in_one_hash_keyed_boundary(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    content = {"schema_version": "2.0", "item_number": 19}
    markdown = "19. 요청으로 정해지는 문항\n".encode()

    first = stage_content_team_item_materialization(settings, content, markdown)
    second = stage_content_team_item_materialization(settings, content, markdown)

    assert first == second
    content_path, content_hash, markdown_path, markdown_hash = first
    assert content_path.parent == markdown_path.parent
    assert content_path.read_bytes() == canonical_json_bytes(content)
    assert markdown_path.read_bytes() == markdown
    assert content_hash == content_sha256(content)
    assert markdown_hash == sha256_bytes(markdown)
    assert markdown_path.lstat().st_mode & 0o777 == 0o640


def test_content_team_staging_rejects_a_stale_markdown_sidecar(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    content = {"schema_version": "2.0", "item_number": 23}
    staged = stage_content_team_item_materialization(settings, content, b"original\n")
    staged[2].chmod(0o600)

    with pytest.raises(CatalogError) as captured:
        stage_content_team_item_materialization(settings, content, b"original\n")

    assert captured.value.code == CatalogErrorCode.CATALOG_REGISTRY_STAGING_INVALID.value
