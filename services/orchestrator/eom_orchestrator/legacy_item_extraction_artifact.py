"""Orchestrator-owned validation and staging for one legacy item extraction result."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from eom_catalog_contracts import (
    AssessmentArtifactMemberPointer,
    LegacyItemExtractionReceipt,
    LegacyItemExtractionRequest,
    LegacyItemExtractionResult,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol import ErrorCode

from eom_orchestrator.artifacts import StagedFileSet, stage_file_set_artifact
from eom_orchestrator.errors import PlatformError


def _pointer_identity(pointer: AssessmentArtifactMemberPointer) -> tuple[str, ...]:
    return (
        pointer.artifact_id,
        pointer.artifact_revision_id,
        pointer.member_path,
        pointer.schema_ref,
        pointer.media_type,
        pointer.sha256,
    )


def _validate_closed_source_anchors(
    *, result: LegacyItemExtractionResult, request: LegacyItemExtractionRequest
) -> None:
    page_sources = {
        (_pointer_identity(page.image), page.source_role, page.physical_page)
        for page in request.page_inputs
    }
    materialized_sources = {
        (_pointer_identity(materialization.source), materialization.source_role)
        for materialization in request.source_materializations
    }
    for item in result.items:
        for anchor in item.source_anchors:
            identity = _pointer_identity(anchor.source)
            if anchor.source_role in {"PROBLEM_DOCUMENT", "ANSWER_EXPLANATION_DOCUMENT"}:
                if (
                    anchor.physical_page is None
                    or (
                        identity,
                        anchor.source_role,
                        anchor.physical_page,
                    )
                    not in page_sources
                ):
                    raise PlatformError(
                        ErrorCode.WORKER_RESULT_INVALID,
                        "legacy extraction page anchor is outside the pinned page inputs",
                    )
            elif (identity, anchor.source_role) not in materialized_sources:
                raise PlatformError(
                    ErrorCode.WORKER_RESULT_INVALID,
                    "legacy extraction source anchor is outside the pinned materializations",
                )


def stage_legacy_item_extraction_result(
    *,
    result: LegacyItemExtractionResult,
    request: LegacyItemExtractionRequest,
    completed_at: datetime,
    job_id: str,
    logical_artifact_id: str,
    revision_id: str,
    staging: Path,
) -> tuple[StagedFileSet, LegacyItemExtractionReceipt]:
    """Validate closed request coverage and stage only the inner canonical result value."""

    if (
        result.extraction_request_id != request.extraction_request_id
        or result.request_sha256 != request.request_sha256
    ):
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "legacy extraction result request identity does not match worker input",
        )
    expected_pages = tuple(page.page_input_id for page in request.page_inputs)
    if result.observed_page_input_ids != expected_pages:
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "legacy extraction result does not exactly cover the pinned page inputs",
        )
    item_numbers = tuple(item.item_number for item in result.items)
    if item_numbers != request.expected_item_numbers:
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "legacy extraction result does not exactly cover the expected items",
        )
    _validate_closed_source_anchors(result=result, request=request)

    source_directory = staging / "legacy-item-extraction-source"
    artifact_stage = staging / "legacy-item-extraction-artifact"
    if source_directory.exists() or artifact_stage.exists():
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "legacy extraction staging path already exists",
        )
    try:
        source_directory.mkdir(mode=0o750)
        payload = canonical_json_bytes(result)
        result_path = source_directory / "result.json"
        result_path.write_bytes(payload)
        result_path.chmod(0o640)
        staged = stage_file_set_artifact(
            files={"result.json": result_path},
            primary_file="result.json",
            job_id=job_id,
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
            artifact_type="legacy-item-extraction-result",
            staging=artifact_stage,
            manifest_version="legacy-item-extraction-file-set/1.0",
            file_metadata={
                "result.json": {
                    "schema_ref": (
                        "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0"
                    ),
                    "media_type": "application/json",
                }
            },
            created_at=completed_at,
        )
    except OSError as exc:
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "legacy extraction result staging failed",
        ) from exc
    if staged.primary_hash != sha256_bytes(payload):
        raise PlatformError(
            ErrorCode.ARTIFACT_HASH_MISMATCH,
            "legacy extraction staged result checksum mismatch",
        )
    receipt_document: dict[str, object] = {
        "schema_version": "legacy-item-extraction-receipt/1.0",
        "extraction_result_id": result.extraction_result_id,
        "extraction_request_id": request.extraction_request_id,
        "request_sha256": request.request_sha256,
        "result_artifact": {
            "artifact_id": logical_artifact_id,
            "artifact_revision_id": revision_id,
            "member_path": "result.json",
            "schema_ref": "eom://schemas/legacy-assessment/legacy-item-extraction-result/1.0",
            "media_type": "application/json",
            "sha256": staged.primary_hash,
        },
        "result_sha256": result.result_sha256,
        "observed_page_input_ids": list(result.observed_page_input_ids),
        "item_numbers": list(item_numbers),
        # Hash the same RFC 3339 value that Pydantic serializes for the receipt.
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "receipt_sha256": "sha256:" + "0" * 64,
    }
    receipt_document["receipt_sha256"] = content_sha256(
        {key: value for key, value in receipt_document.items() if key != "receipt_sha256"}
    )
    receipt = LegacyItemExtractionReceipt.model_validate(receipt_document)
    validate_contract("legacy-item-extraction-receipt", receipt.model_dump(mode="json"))
    return staged, receipt
