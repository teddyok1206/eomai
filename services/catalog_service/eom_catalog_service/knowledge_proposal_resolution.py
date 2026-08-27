"""Resolve one immutable Knowledge Analysis proposal Artifact into typed content."""

from __future__ import annotations

import json
from typing import Any, Literal

from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisProposalReceiptV2,
    KnowledgeAnalysisProposalReceiptV3,
    KnowledgeAnalysisProposalReceiptV4,
    KnowledgeAnalysisWorkerProposal,
    KnowledgeAnalysisWorkerProposalV2,
    KnowledgeAnalysisWorkerProposalV3,
)
from pydantic import ValidationError

from eom_catalog_service.artifacts import CatalogArtifactService

type KnowledgeAnalysisReceipt = (
    KnowledgeAnalysisProposalReceipt
    | KnowledgeAnalysisProposalReceiptV2
    | KnowledgeAnalysisProposalReceiptV3
    | KnowledgeAnalysisProposalReceiptV4
)


class KnowledgeProposalResolutionError(ValueError):
    """An immutable proposal member or its typed aggregate is invalid."""

    def __init__(self, kind: Literal["POINTER_INVALID", "CONTENT_INVALID"], message: str) -> None:
        self.kind = kind
        super().__init__(message)


def resolve_knowledge_analysis_proposal(
    artifacts: CatalogArtifactService,
    receipt: KnowledgeAnalysisReceipt,
) -> (
    KnowledgeAnalysisWorkerProposal
    | KnowledgeAnalysisWorkerProposalV2
    | KnowledgeAnalysisWorkerProposalV3
):
    """Dereference every pinned member once and reconstruct the typed proposal."""

    values: dict[str, Any] = {}
    for field_name in receipt.members.__class__.model_fields:
        pointer = getattr(receipt.members, field_name)
        try:
            raw = artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max(1, pointer.bytes),
            )
        except (OSError, ValueError) as exc:
            raise KnowledgeProposalResolutionError(
                "POINTER_INVALID", "analysis proposal member does not resolve"
            ) from exc
        if len(raw) != pointer.bytes:
            raise KnowledgeProposalResolutionError(
                "POINTER_INVALID", "analysis proposal member byte count differs"
            )
        if field_name == "normalized_markdown":
            try:
                values[field_name] = raw.decode("utf-8")
            except UnicodeError as exc:
                raise KnowledgeProposalResolutionError(
                    "CONTENT_INVALID", "normalized Markdown is not UTF-8"
                ) from exc
            continue
        rows: list[dict[str, Any]] = []
        try:
            for line in raw.splitlines():
                value: object = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("proposal JSONL row is not an object")
                rows.append(value)
        except (ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeProposalResolutionError(
                "CONTENT_INVALID", "analysis proposal JSONL is invalid"
            ) from exc
        values[field_name] = rows

    proposal_value = {
        "schema_version": (
            "knowledge-analysis-worker-proposal/3.0"
            if isinstance(receipt, KnowledgeAnalysisProposalReceiptV4)
            else (
                "knowledge-analysis-worker-proposal/2.0"
                if isinstance(receipt, KnowledgeAnalysisProposalReceiptV3)
                else "knowledge-analysis-worker-proposal/1.0"
            )
        ),
        "analysis_request_id": receipt.analysis_request_id,
        **values,
        "general_knowledge_used": receipt.general_knowledge_used,
        "completed_at": receipt.completed_at,
    }
    try:
        proposal: (
            KnowledgeAnalysisWorkerProposal
            | KnowledgeAnalysisWorkerProposalV2
            | KnowledgeAnalysisWorkerProposalV3
        )
        if isinstance(receipt, KnowledgeAnalysisProposalReceiptV4):
            proposal = KnowledgeAnalysisWorkerProposalV3.model_validate(proposal_value)
        elif isinstance(receipt, KnowledgeAnalysisProposalReceiptV3):
            proposal = KnowledgeAnalysisWorkerProposalV2.model_validate(proposal_value)
        else:
            proposal = KnowledgeAnalysisWorkerProposal.model_validate(proposal_value)
    except ValidationError as exc:
        raise KnowledgeProposalResolutionError(
            "CONTENT_INVALID", "analysis proposal is structurally invalid"
        ) from exc
    actual_counts = (
        len(proposal.anchors),
        len(proposal.nodes),
        len(proposal.edges),
        len(proposal.claims),
        len(proposal.component_observations),
        len(proposal.unresolved_ambiguities),
    )
    expected_counts = (
        receipt.counts.anchors,
        receipt.counts.nodes,
        receipt.counts.edges,
        receipt.counts.claims,
        receipt.counts.component_observations,
        receipt.counts.ambiguities,
    )
    if actual_counts != expected_counts:
        raise KnowledgeProposalResolutionError("CONTENT_INVALID", "analysis proposal counts differ")
    return proposal
