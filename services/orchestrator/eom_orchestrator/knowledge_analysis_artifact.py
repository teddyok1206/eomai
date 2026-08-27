"""Pure proposal serialization and Orchestrator-owned Artifact staging."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisProposalReceiptV5,
    KnowledgeAnalysisProposalReceiptV6,
    KnowledgeAnalysisProposalReceiptV7,
    KnowledgeAnalysisRequestV2,
    KnowledgeAnalysisRequestV3,
    KnowledgeAnalysisRequestV4,
    KnowledgeAnalysisRequestV5,
    KnowledgeAnalysisRequestV6,
    KnowledgeAnalysisRequestV7,
    KnowledgeAnalysisRequestV8,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
    KnowledgeAnalysisWorkerProposalV4,
    KnowledgeAnalysisWorkerProposalV5,
    KnowledgeAnalysisWorkerProposalV6,
    KnowledgeProposalArtifactMember,
    KnowledgeProposalCounts,
    KnowledgeProposalCountsV2,
    KnowledgeProposalMembers,
    KnowledgeProposalMembersV2,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol import ErrorCode

from eom_orchestrator.artifacts import StagedFileSet, stage_file_set_artifact
from eom_orchestrator.errors import PlatformError

ProposalMediaType = Literal["text/markdown", "application/x-ndjson", "application/json"]

PROPOSAL_MEMBERS: tuple[tuple[str, str, ProposalMediaType, str], ...] = (
    (
        "normalized_markdown",
        "normalized/document.md",
        "text/markdown",
        "eom://schemas/knowledge/normalized-markdown/1.0",
    ),
    (
        "anchors",
        "normalized/anchors.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/source-anchor/2.0",
    ),
    (
        "nodes",
        "normalized/nodes.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/proposed-node/2.0",
    ),
    (
        "edges",
        "normalized/edges.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/proposed-edge/2.0",
    ),
    (
        "claims",
        "normalized/claims.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/proposed-claim/2.0",
    ),
    (
        "component_observations",
        "normalized/components.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/component-observation/2.0",
    ),
    (
        "unresolved_ambiguities",
        "normalized/ambiguities.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/ambiguity/2.0",
    ),
)
MULTIMODAL_PROPOSAL_MEMBERS: tuple[tuple[str, str, ProposalMediaType, str], ...] = (
    *PROPOSAL_MEMBERS[:-1],
    (
        "page_image_observations",
        "normalized/page-images.jsonl",
        "application/x-ndjson",
        "eom://schemas/knowledge/page-image-observation/1.0",
    ),
    PROPOSAL_MEMBERS[-1],
)
_DOCUMENT_ANCHOR_LOCATOR = re.compile(r"^physical_page=([1-9][0-9]{0,5})(?:;.{1,220})?$")


def stage_knowledge_analysis_proposal(
    *,
    proposal: (
        KnowledgeAnalysisWorkerProposal
        | KnowledgeAnalysisWorkerProposalV2
        | KnowledgeAnalysisWorkerProposalV3
        | KnowledgeAnalysisWorkerProposalV4
        | KnowledgeAnalysisWorkerProposalV5
        | KnowledgeAnalysisWorkerProposalV6
    ),
    request: (
        KnowledgeAnalysisRequestV2
        | KnowledgeAnalysisRequestV3
        | KnowledgeAnalysisRequestV4
        | KnowledgeAnalysisRequestV5
        | KnowledgeAnalysisRequestV6
        | KnowledgeAnalysisRequestV7
        | KnowledgeAnalysisRequestV8
    ),
    job_id: str,
    logical_artifact_id: str,
    revision_id: str,
    staging: Path,
) -> tuple[
    StagedFileSet,
    KnowledgeAnalysisProposalReceipt
    | KnowledgeAnalysisProposalReceiptV2
    | KnowledgeAnalysisProposalReceiptV3
    | KnowledgeAnalysisProposalReceiptV4
    | KnowledgeAnalysisProposalReceiptV5
    | KnowledgeAnalysisProposalReceiptV6
    | KnowledgeAnalysisProposalReceiptV7,
]:
    """Split one bounded worker value into deterministic immutable Artifact members."""

    if proposal.analysis_request_id != request.analysis_request_id:
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "knowledge proposal request identity does not match worker input",
        )
    pinned_source = request.source.artifact_member
    if any(
        anchor.artifact_revision_id != pinned_source.artifact_revision_id
        or anchor.member_path != pinned_source.member_path
        for anchor in proposal.anchors
    ):
        raise PlatformError(
            ErrorCode.WORKER_RESULT_INVALID,
            "knowledge proposal source anchor does not match the pinned source",
        )
    if isinstance(
        request,
        (
            KnowledgeAnalysisRequestV3,
            KnowledgeAnalysisRequestV4,
            KnowledgeAnalysisRequestV5,
            KnowledgeAnalysisRequestV6,
            KnowledgeAnalysisRequestV7,
            KnowledgeAnalysisRequestV8,
        ),
    ):
        first_page = request.source.first_physical_page
        last_page = request.source.last_physical_page
        for anchor in proposal.anchors:
            locator = _DOCUMENT_ANCHOR_LOCATOR.fullmatch(anchor.locator)
            if locator is None or not first_page <= int(locator.group(1)) <= last_page:
                raise PlatformError(
                    ErrorCode.WORKER_RESULT_INVALID,
                    "document source anchor is outside the selected physical-page range",
                )
    if isinstance(
        request,
        (KnowledgeAnalysisRequestV6, KnowledgeAnalysisRequestV7, KnowledgeAnalysisRequestV8),
    ):
        expected_proposal = (
            KnowledgeAnalysisWorkerProposalV6
            if isinstance(request, KnowledgeAnalysisRequestV8)
            else (
                KnowledgeAnalysisWorkerProposalV5
                if isinstance(request, KnowledgeAnalysisRequestV7)
                else KnowledgeAnalysisWorkerProposalV4
            )
        )
        if not isinstance(proposal, expected_proposal):
            raise PlatformError(
                ErrorCode.WORKER_RESULT_INVALID,
                "multimodal analysis requires a multimodal worker proposal",
            )
        expected_images = tuple(
            member
            for member in request.source.materialization_members
            if member.member_kind == "PAGE_IMAGE"
        )
        observed = proposal.page_image_observations
        if tuple((item.physical_page, item.image_sha256) for item in observed) != tuple(
            (member.physical_page, member.sha256) for member in expected_images
        ):
            raise PlatformError(
                ErrorCode.WORKER_RESULT_INVALID,
                "page-image observations do not match the exact attached source images",
            )
    source_directory = staging / "knowledge-proposal-source"
    artifact_stage = staging / "knowledge-proposal-artifact"
    if source_directory.exists() or artifact_stage.exists():
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "knowledge proposal staging path already exists",
        )
    source_directory.mkdir(mode=0o750)
    files: dict[str, Path] = {}
    metadata: dict[str, dict[str, str]] = {}
    member_values: dict[str, KnowledgeProposalArtifactMember] = {}
    descriptors: list[dict[str, object]] = []
    try:
        member_specs = (
            MULTIMODAL_PROPOSAL_MEMBERS
            if isinstance(proposal, KnowledgeAnalysisWorkerProposalV4)
            else PROPOSAL_MEMBERS
        )
        for field_name, member_path, media_type, schema_ref in member_specs:
            value = getattr(proposal, field_name)
            if field_name == "nodes" and isinstance(proposal, KnowledgeAnalysisWorkerProposalV5):
                schema_ref = (
                    "eom://schemas/knowledge/proposed-node/4.0"
                    if isinstance(proposal, KnowledgeAnalysisWorkerProposalV6)
                    else "eom://schemas/knowledge/proposed-node/3.0"
                )
            if field_name == "edges" and isinstance(
                proposal,
                (
                    KnowledgeAnalysisWorkerProposalV2,
                    KnowledgeAnalysisWorkerProposalV3,
                    KnowledgeAnalysisWorkerProposalV4,
                ),
            ):
                schema_ref = "eom://schemas/knowledge/proposed-edge/3.0"
                if isinstance(proposal, KnowledgeAnalysisWorkerProposalV5):
                    schema_ref = "eom://schemas/knowledge/proposed-edge/4.0"
            if field_name == "unresolved_ambiguities" and isinstance(
                proposal, (KnowledgeAnalysisWorkerProposalV3, KnowledgeAnalysisWorkerProposalV4)
            ):
                schema_ref = "eom://schemas/knowledge/ambiguity/3.0"
            if field_name == "normalized_markdown":
                payload = value.encode("utf-8")
            else:
                payload = b"".join(canonical_json_bytes(item) + b"\n" for item in value)
            target = source_directory / Path(member_path).name
            target.write_bytes(payload)
            target.chmod(0o640)
            digest = sha256_bytes(payload)
            member = KnowledgeProposalArtifactMember(
                artifact_id=logical_artifact_id,
                artifact_revision_id=revision_id,
                member_path=member_path,
                sha256=digest,
                bytes=len(payload),
                schema_ref=schema_ref,
                media_type=media_type,
                logical_name=Path(member_path).name,
            )
            files[member_path] = target
            metadata[member_path] = {"schema_ref": schema_ref, "media_type": media_type}
            member_values[field_name] = member
            descriptors.append(
                {
                    "member_path": member_path,
                    "sha256": digest,
                    "bytes": len(payload),
                    "schema_ref": schema_ref,
                    "media_type": media_type,
                }
            )
        confidence_values = [
            *(edge.confidence_milli for edge in proposal.edges),
            *(claim.confidence_milli for claim in proposal.claims),
            *(item.confidence_milli for item in proposal.component_observations),
        ]
        receipt_value = {
            "analysis_request_id": request.analysis_request_id,
            "source": request.source.model_dump(mode="json"),
            "members": (
                KnowledgeProposalMembersV2.model_validate(member_values).model_dump(mode="json")
                if isinstance(proposal, KnowledgeAnalysisWorkerProposalV4)
                else KnowledgeProposalMembers.model_validate(member_values).model_dump(mode="json")
            ),
            "counts": (
                KnowledgeProposalCountsV2(
                    anchors=len(proposal.anchors),
                    nodes=len(proposal.nodes),
                    edges=len(proposal.edges),
                    claims=len(proposal.claims),
                    component_observations=len(proposal.component_observations),
                    page_image_observations=len(proposal.page_image_observations),
                    ambiguities=len(proposal.unresolved_ambiguities),
                ).model_dump(mode="json")
                if isinstance(proposal, KnowledgeAnalysisWorkerProposalV4)
                else KnowledgeProposalCounts(
                    anchors=len(proposal.anchors),
                    nodes=len(proposal.nodes),
                    edges=len(proposal.edges),
                    claims=len(proposal.claims),
                    component_observations=len(proposal.component_observations),
                    ambiguities=len(proposal.unresolved_ambiguities),
                ).model_dump(mode="json")
            ),
            "general_knowledge_used": proposal.general_knowledge_used,
            "minimum_confidence_milli": min(confidence_values) if confidence_values else None,
            "blocking_ambiguity_count": sum(
                1 for item in proposal.unresolved_ambiguities if item.blocking
            ),
            "content_set_sha256": content_sha256(
                sorted(descriptors, key=lambda item: str(item["member_path"]))
            ),
            "completed_at": proposal.completed_at,
        }
        receipt: (
            KnowledgeAnalysisProposalReceipt
            | KnowledgeAnalysisProposalReceiptV2
            | KnowledgeAnalysisProposalReceiptV3
            | KnowledgeAnalysisProposalReceiptV4
            | KnowledgeAnalysisProposalReceiptV5
            | KnowledgeAnalysisProposalReceiptV6
            | KnowledgeAnalysisProposalReceiptV7
        )
        if isinstance(request, KnowledgeAnalysisRequestV8):
            receipt = KnowledgeAnalysisProposalReceiptV7.model_validate(receipt_value)
        elif isinstance(request, KnowledgeAnalysisRequestV7):
            receipt = KnowledgeAnalysisProposalReceiptV6.model_validate(receipt_value)
        elif isinstance(request, KnowledgeAnalysisRequestV6):
            receipt = KnowledgeAnalysisProposalReceiptV5.model_validate(receipt_value)
        elif isinstance(request, KnowledgeAnalysisRequestV5):
            receipt = KnowledgeAnalysisProposalReceiptV4.model_validate(receipt_value)
        elif isinstance(request, KnowledgeAnalysisRequestV4):
            receipt = KnowledgeAnalysisProposalReceiptV3.model_validate(receipt_value)
        elif isinstance(request, KnowledgeAnalysisRequestV3):
            receipt = KnowledgeAnalysisProposalReceiptV2.model_validate(receipt_value)
        else:
            receipt = KnowledgeAnalysisProposalReceipt.model_validate(receipt_value)
        receipt_path = source_directory / "proposal-receipt.json"
        receipt_path.write_bytes(canonical_json_bytes(receipt))
        receipt_path.chmod(0o640)
        receipt_member = "normalized/proposal-receipt.json"
        files[receipt_member] = receipt_path
        metadata[receipt_member] = {
            "schema_ref": (
                "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/7.0"
                if isinstance(receipt, KnowledgeAnalysisProposalReceiptV7)
                else (
                    "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/6.0"
                    if isinstance(receipt, KnowledgeAnalysisProposalReceiptV6)
                    else (
                        "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/5.0"
                        if isinstance(receipt, KnowledgeAnalysisProposalReceiptV5)
                        else (
                            "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/4.0"
                            if isinstance(receipt, KnowledgeAnalysisProposalReceiptV4)
                            else (
                                "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/3.0"
                                if isinstance(receipt, KnowledgeAnalysisProposalReceiptV3)
                                else (
                                    "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/2.0"
                                    if isinstance(receipt, KnowledgeAnalysisProposalReceiptV2)
                                    else "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0"
                                )
                            )
                        )
                    )
                )
            ),
            "media_type": "application/json",
        }
        staged = stage_file_set_artifact(
            files=files,
            primary_file=receipt_member,
            job_id=job_id,
            logical_artifact_id=logical_artifact_id,
            revision_id=revision_id,
            artifact_type="knowledge-analysis-proposal",
            staging=artifact_stage,
            manifest_version="knowledge-analysis-proposal-file-set/1.0",
            file_metadata=metadata,
            created_at=proposal.completed_at,
        )
        if staged.primary_hash != sha256_bytes(canonical_json_bytes(receipt)):
            raise PlatformError(
                ErrorCode.ARTIFACT_HASH_MISMATCH,
                "knowledge proposal receipt checksum mismatch",
            )
        return staged, receipt
    except OSError as exc:
        raise PlatformError(
            ErrorCode.ARTIFACT_COMMIT_FAILED,
            "knowledge proposal staging failed",
        ) from exc
