"""Operator CLI for bounded knowledge lifecycle operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Never

import typer
from eom_catalog_contracts import (
    LegacyRootAlias,
    LegacySourceInventoryV2,
    LegacySourceSelectionV2,
)
from eom_catalog_service.educational_document_service import (
    EducationalDocumentError,
    EducationalDocumentService,
    load_educational_document_registration_request,
    prepare_textbook_registration_request,
    write_educational_document_registration_request,
)
from eom_catalog_service.legacy_knowledge_intake_service import LegacyKnowledgeIntakeService
from eom_catalog_service.legacy_source_inventory import (
    LegacySourceInventoryError,
    load_inventory_manifest,
    load_inventory_policy,
    load_root_configuration,
    write_inventory_manifest,
)
from eom_catalog_service.legacy_source_selection_boundary import (
    LegacySelectionValidation,
    LegacySourceSelectionError,
)
from eom_catalog_service.legacy_source_selection_service import (
    LegacySourceSelectionService,
    load_source_selection,
)
from eom_content_intake import IntakeError
from eom_orchestrator.database import build_engine

knowledge_app = typer.Typer(no_args_is_help=True)
legacy_knowledge_app = typer.Typer(no_args_is_help=True)
legacy_inventory_app = typer.Typer(no_args_is_help=True)
legacy_selection_app = typer.Typer(no_args_is_help=True)
document_app = typer.Typer(no_args_is_help=True)
knowledge_app.add_typer(legacy_knowledge_app, name="legacy")
knowledge_app.add_typer(document_app, name="document")
legacy_knowledge_app.add_typer(legacy_inventory_app, name="inventory")
legacy_knowledge_app.add_typer(legacy_selection_app, name="selection")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _failure(
    exc: LegacySourceInventoryError | LegacySourceSelectionError | IntakeError,
) -> Never:
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


def _selection_summary(
    selection: LegacySourceSelectionV2,
    validation: LegacySelectionValidation | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "PASS",
        "schema_version": selection.schema_version,
        "selection_id": selection.selection_id,
        "selection_sha256": selection.selection_sha256,
        "inventory_id": selection.inventory_id,
        "inventory_sha256": selection.inventory_sha256,
        "selected_source_count": len(selection.selected_sources),
        "comparison_evidence_count": len(selection.comparison_evidence),
    }
    if validation is not None:
        result.update(
            {
                "intended_corpus_key": validation.intended_corpus_key,
                "source_owner_reference": validation.source_owner_reference,
                "selected_byte_count": validation.selected_byte_count,
                "rights_and_source_resolution": "PASS",
            }
        )
    return result


def _document_failure(exc: EducationalDocumentError) -> Never:
    _emit({"status": "FAILED", "error_code": exc.code})
    raise typer.Exit(1)


@document_app.command("prepare-textbook")
def document_prepare_textbook(
    source_file: Annotated[Path, typer.Option("--source-file", exists=True, dir_okay=False)],
    analysis_bundle: Annotated[
        Path, typer.Option("--analysis-bundle", exists=True, file_okay=False)
    ],
    document_key: Annotated[str, typer.Option("--document-key")],
    edition_label: Annotated[str, typer.Option("--edition-label")],
    registered_by: Annotated[str, typer.Option("--registered-by")],
    registration_key: Annotated[str, typer.Option("--registration-key")],
    confirmation_reference: Annotated[str, typer.Option("--confirmation-reference")],
    output_file: Annotated[Path, typer.Option("--output-file")],
    confirm_purchased_and_negotiated: Annotated[
        bool, typer.Option("--confirm-purchased-and-negotiated")
    ] = False,
) -> None:
    """Prepare a protected source-bound registration request without DB or NAS mutation."""

    if not confirm_purchased_and_negotiated:
        raise typer.BadParameter("explicit purchased-and-negotiated confirmation is required")
    try:
        request = prepare_textbook_registration_request(
            source_path=source_file,
            analysis_bundle_root=analysis_bundle,
            document_key=document_key,
            edition_label=edition_label,
            registered_by=registered_by,
            registration_key=registration_key,
            confirmation_reference=confirmation_reference,
        )
        write_educational_document_registration_request(output_file, request)
    except EducationalDocumentError as exc:
        _document_failure(exc)
    _emit(
        {
            "status": "PREPARED",
            "document_key": request.identity.document_key,
            "source_sha256": request.expected_source_sha256,
            "source_size_bytes": request.expected_source_size_bytes,
            "source_page_count": request.expected_source_page_count,
            "rights_state": request.rights.rights_state,
            "request_sha256": request.request_sha256,
            "output_created": True,
            "db_mutation": False,
            "nas_mutation": False,
        }
    )


@document_app.command("register-textbook")
def document_register_textbook(
    request_file: Annotated[Path, typer.Option("--request-file", exists=True, dir_okay=False)],
    source_file: Annotated[Path, typer.Option("--source-file", exists=True, dir_okay=False)],
    analysis_bundle: Annotated[
        Path, typer.Option("--analysis-bundle", exists=True, file_okay=False)
    ],
    confirm_request_sha256: Annotated[str, typer.Option("--confirm-request-sha256")],
) -> None:
    """Commit one reviewed document revision; it starts no worker or analysis workflow."""

    try:
        request = load_educational_document_registration_request(request_file)
        if request.request_sha256 != confirm_request_sha256:
            raise typer.BadParameter("request confirmation hash does not match")
        engine = build_engine()
        try:
            receipt = EducationalDocumentService(engine).register_textbook(
                request,
                source_path=source_file,
                analysis_bundle_root=analysis_bundle,
            )
        finally:
            engine.dispose()
    except EducationalDocumentError as exc:
        _document_failure(exc)
    _emit(
        {
            "status": "COMMITTED",
            **receipt.model_dump(mode="json"),
            "knowledge_analysis_started": False,
            "workflow_started": False,
        }
    )


@document_app.command("inspect")
def document_inspect(document_id_or_key: str) -> None:
    """Inspect bounded current-revision pointers without returning paths or bytes."""

    engine = build_engine()
    try:
        try:
            receipt = EducationalDocumentService(engine).inspect(document_id_or_key)
        except EducationalDocumentError as exc:
            _document_failure(exc)
    finally:
        engine.dispose()
    _emit(receipt.model_dump(mode="json"))


@document_app.command("list")
def document_list() -> None:
    """List bounded current document revision receipts in stable document-key order."""

    engine = build_engine()
    try:
        receipts = EducationalDocumentService(engine).list_current()
    finally:
        engine.dispose()
    _emit([receipt.model_dump(mode="json") for receipt in receipts])


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


@legacy_selection_app.command("inspect")
def legacy_selection_inspect(
    selection_file: Annotated[Path, typer.Option("--selection-file", exists=True, dir_okay=False)],
) -> None:
    """Validate a protected source-bound selection and emit only bounded metadata."""

    try:
        selection = load_source_selection(selection_file)
    except LegacySourceSelectionError as exc:
        _failure(exc)
    _emit(_selection_summary(selection))


@legacy_selection_app.command("validate")
def legacy_selection_validate(
    selection_file: Annotated[Path, typer.Option("--selection-file", exists=True, dir_okay=False)],
    inventory_file: Annotated[Path, typer.Option("--inventory-file", exists=True, dir_okay=False)],
    root_config_file: Annotated[
        Path, typer.Option("--root-config-file", exists=True, dir_okay=False)
    ],
) -> None:
    """Resolve rights and rehash originals without DB, NAS, or worker mutation."""

    try:
        selection = load_source_selection(selection_file)
        inventory = load_inventory_manifest(inventory_file)
        roots = load_root_configuration(root_config_file)
    except (LegacySourceInventoryError, LegacySourceSelectionError) as exc:
        _failure(exc)
    engine = build_engine()
    try:
        service = LegacySourceSelectionService.from_engine(engine)
        try:
            validation = service.validate(
                selection=selection,
                inventory=inventory,
                roots=roots,
            )
        except (LegacySourceSelectionError, IntakeError) as exc:
            _failure(exc)
        result = _selection_summary(selection, validation)
        result["mutation_boundary"] = "DISPOSABLE_LOCAL_MATERIALIZATION_ONLY"
        _emit(result)
    finally:
        engine.dispose()


@legacy_selection_app.command("intake")
def legacy_selection_intake(
    selection_file: Annotated[Path, typer.Option("--selection-file", exists=True, dir_okay=False)],
    inventory_file: Annotated[Path, typer.Option("--inventory-file", exists=True, dir_okay=False)],
    root_config_file: Annotated[
        Path, typer.Option("--root-config-file", exists=True, dir_okay=False)
    ],
    confirm_selection_sha256: Annotated[str, typer.Option("--confirm-selection-sha256")],
) -> None:
    """Create one reviewed Content Intake batch; it never starts Knowledge Analysis."""

    try:
        selection = load_source_selection(selection_file)
        inventory = load_inventory_manifest(inventory_file)
        roots = load_root_configuration(root_config_file)
    except (LegacySourceInventoryError, LegacySourceSelectionError) as exc:
        _failure(exc)
    if confirm_selection_sha256 != selection.selection_sha256:
        raise typer.BadParameter("selection confirmation does not match the document")
    engine = build_engine()
    try:
        try:
            result = LegacySourceSelectionService.from_engine(engine).create_intake(
                selection=selection,
                inventory=inventory,
                roots=roots,
            )
        except (LegacySourceSelectionError, IntakeError) as exc:
            _failure(exc)
        _emit(
            {
                **_selection_summary(selection, result.validation),
                "status": "INTAKE_CREATED",
                "intake_batch_id": result.intake.intake_batch_id,
                "intake_state": result.intake.state,
                "source_fingerprint": result.intake.source_fingerprint,
                "source_manifest_artifact_id": result.intake.source_manifest_artifact_id,
                "source_manifest_artifact_revision_id": (
                    result.intake.source_manifest_artifact_revision_id
                ),
                "selection_artifact_id": result.selection_artifact.artifact_id,
                "selection_artifact_revision_id": (result.selection_artifact.artifact_revision_id),
                "knowledge_analysis_started": False,
            }
        )
    finally:
        engine.dispose()
