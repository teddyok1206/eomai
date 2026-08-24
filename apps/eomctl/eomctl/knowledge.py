"""Operator CLI for bounded knowledge lifecycle operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Never

import typer
from eom_catalog_contracts import LegacyRootAlias, LegacySourceInventoryV2
from eom_catalog_service.legacy_knowledge_intake_service import LegacyKnowledgeIntakeService
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryError,
    load_inventory_manifest,
    load_inventory_policy,
    load_root_configuration,
    write_inventory_manifest,
)
from eom_orchestrator.database import build_engine

knowledge_app = typer.Typer(no_args_is_help=True)
legacy_knowledge_app = typer.Typer(no_args_is_help=True)
legacy_inventory_app = typer.Typer(no_args_is_help=True)
knowledge_app.add_typer(legacy_knowledge_app, name="legacy")
legacy_knowledge_app.add_typer(legacy_inventory_app, name="inventory")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _failure(exc: LegacySourceInventoryError) -> Never:
    _emit({"status": "FAILED", "error_code": exc.code})
    raise typer.Exit(1)


def _summary(inventory: LegacySourceInventoryV2) -> dict[str, object]:
    return {
        "status": "PASS",
        "schema_version": inventory.schema_version,
        "inventory_id": inventory.inventory_id,
        "root_alias": inventory.root_alias,
        "scanner_policy_revision_id": inventory.scanner_policy_revision_id,
        "source_set_sha256": inventory.source_set_sha256,
        "inventory_sha256": inventory.inventory_sha256,
        "summary": inventory.summary.model_dump(mode="json"),
    }


@legacy_inventory_app.command("dry-run")
def legacy_inventory_dry_run(
    root_alias: Annotated[LegacyRootAlias, typer.Option("--root-alias")],
    policy_file: Annotated[Path, typer.Option("--policy-file", exists=True, dir_okay=False)],
    root_config_file: Annotated[
        Path, typer.Option("--root-config-file", exists=True, dir_okay=False)
    ],
    manifest_file: Annotated[Path, typer.Option("--manifest-file")],
) -> None:
    """Observe one allowlisted root without DB, NAS, worker, or source mutation."""

    try:
        policy = load_inventory_policy(policy_file)
        roots = load_root_configuration(root_config_file)
        inventory = LegacyKnowledgeIntakeService().dry_run(
            policy=policy,
            roots=roots,
            root_alias=root_alias,
        )
        write_inventory_manifest(manifest_file, inventory)
    except LegacySourceInventoryError as exc:
        _failure(exc)
    result = _summary(inventory)
    result["manifest_created"] = True
    result["mutation_boundary"] = "LOCAL_PROTECTED_MANIFEST_ONLY"
    _emit(result)


@legacy_inventory_app.command("inspect")
def legacy_inventory_inspect(
    manifest_file: Annotated[Path, typer.Option("--manifest-file", exists=True, dir_okay=False)],
) -> None:
    """Validate a protected inventory manifest and emit only bounded metadata."""

    try:
        inventory = load_inventory_manifest(manifest_file)
    except LegacySourceInventoryError as exc:
        _failure(exc)
    _emit(_summary(inventory))


@legacy_inventory_app.command("commit")
def legacy_inventory_commit(
    manifest_file: Annotated[Path, typer.Option("--manifest-file", exists=True, dir_okay=False)],
    confirm_source_set_sha256: Annotated[str, typer.Option("--confirm-source-set-sha256")],
) -> None:
    """Commit only a validated inventory manifest through the Catalog Artifact boundary."""

    try:
        inventory = load_inventory_manifest(manifest_file)
    except LegacySourceInventoryError as exc:
        _failure(exc)
    if confirm_source_set_sha256 != inventory.source_set_sha256:
        raise typer.BadParameter("source-set confirmation does not match the manifest")
    engine = build_engine()
    try:
        result = LegacyKnowledgeIntakeService(engine).commit_inventory(inventory)
        _emit(
            {
                "status": "COMMITTED",
                "inventory_id": result.inventory_id,
                "source_set_sha256": result.source_set_sha256,
                "inventory_sha256": result.inventory_sha256,
                "artifact_id": result.artifact_id,
                "artifact_revision_id": result.artifact_revision_id,
                "artifact_content_sha256": result.artifact_content_sha256,
                "artifact_manifest_sha256": result.artifact_manifest_sha256,
                "legacy_source_bytes_committed": False,
            }
        )
    finally:
        engine.dispose()
