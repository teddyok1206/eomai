"""Orchestrator-owned staging for one editorial compatibility worker proposal."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts import (
    LegacyItemEditorialCompatibilityProposal,
    LegacyItemEditorialCompatibilityRequest,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol import ErrorCode

from eom_orchestrator.artifacts import StagedFileSet, stage_file_set_artifact
from eom_orchestrator.errors import PlatformError


def stage_legacy_item_editorial_compatibility_proposal(
    *,
    proposal: LegacyItemEditorialCompatibilityProposal,
    request: LegacyItemEditorialCompatibilityRequest,
    job_id: str,
    logical_artifact_id: str,
    revision_id: str,
    staging: Path,
) -> StagedFileSet:
    """Validate the exact request echo and stage the raw proposal as one canonical member."""

    if (
        proposal.compatibility_request_id != request.compatibility_request_id
        or proposal.request_sha256 != request.request_sha256
        or proposal.source != request.source
        or proposal.authorities != request.authorities
        or proposal.renderer_profile != request.renderer_profile
    ):
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "editorial compatibility proposal does not match the pinned request",
        )
    document = proposal.model_dump(mode="json")
    validate_contract("legacy-item-editorial-compatibility-proposal", document)
    payload = canonical_json_bytes(document)
    source_directory = staging / "legacy-item-editorial-compatibility-source"
    artifact_stage = staging / "legacy-item-editorial-compatibility-artifact"
    if source_directory.exists() or artifact_stage.exists():
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "editorial compatibility proposal staging path already exists",
        )
    try:
        source_directory.mkdir(mode=0o750)
        proposal_path = source_directory / "result.json"
        proposal_path.write_bytes(payload)
        proposal_path.chmod(0o640)
        staged = stage_file_set_artifact(
            files={"result.json": proposal_path},
            primary_file="result.json",
            job_id=job_id,
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
            artifact_type="legacy-item-editorial-compatibility-proposal",
            staging=artifact_stage,
            manifest_version="legacy-item-editorial-compatibility-file-set/1.0",
            file_metadata={
                "result.json": {
                    "schema_ref": (
                        "eom://schemas/legacy-assessment/"
                        "legacy-item-editorial-compatibility-proposal/1.0"
                    ),
                    "media_type": "application/json",
                }
            },
            created_at=proposal.completed_at,
        )
    except OSError as exc:
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "editorial compatibility proposal staging failed",
        ) from exc
    if staged.primary_hash != sha256_bytes(payload):
        raise PlatformError(
            ErrorCode.ARTIFACT_HASH_MISMATCH,
            "editorial compatibility proposal staged checksum mismatch",
        )
    return staged
