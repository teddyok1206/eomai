"""Resolve accepted additive solution reports for graph retrieval without N+1 queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceiptV9,
    KnowledgeAnalysisRequestV10,
    KnowledgeAnalysisResultV10,
    KnowledgeAnalysisSolutionReport,
    KnowledgeArtifactMemberPointer,
    KnowledgeProposalArtifactMember,
    KnowledgeSolutionEvidencePointer,
    validate_contract,
    validate_knowledge_solution_report_references,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.knowledge_proposal_resolution import (
    KnowledgeProposalResolutionError,
    resolve_knowledge_solution_proposal,
)


class SolutionEvidenceResolutionError(ValueError):
    """An accepted solution successor or one of its immutable pointers is invalid."""


@dataclass(frozen=True, slots=True)
class ResolvedSolutionEvidence:
    pointer: KnowledgeSolutionEvidencePointer
    report: KnowledgeAnalysisSolutionReport


def _manifest_member(
    revision: ArtifactRevisionRecord,
    *,
    artifact_id: str,
    member_path: str,
    logical_name: str,
    schema_ref: str,
) -> tuple[KnowledgeArtifactMemberPointer, int]:
    files = revision.manifest.get("files")
    matches = (
        [
            value
            for value in files
            if isinstance(value, dict) and value.get("file_name") == member_path
        ]
        if isinstance(files, list)
        else []
    )
    if (
        len(matches) != 1
        or matches[0].get("sha256") is None
        or not isinstance(matches[0].get("bytes"), int)
        or matches[0].get("schema_ref") != schema_ref
        or matches[0].get("media_type") != "application/json"
    ):
        raise SolutionEvidenceResolutionError("solution Artifact member descriptor differs")
    return (
        KnowledgeArtifactMemberPointer(
            artifact_id=artifact_id,
            artifact_revision_id=revision.revision_id,
            sha256=str(matches[0]["sha256"]),
            schema_ref=schema_ref,
            media_type="application/json",
            logical_name=logical_name,
            member_path=member_path,
        ),
        int(matches[0]["bytes"]),
    )


def _proposal_pointer(
    pointer: KnowledgeArtifactMemberPointer, *, bytes_count: int
) -> KnowledgeProposalArtifactMember:
    return KnowledgeProposalArtifactMember(
        artifact_id=pointer.artifact_id,
        artifact_revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        bytes=bytes_count,
        schema_ref=pointer.schema_ref,
        media_type="application/json",
        logical_name=pointer.logical_name,
    )


def _resolve_row(
    artifacts: CatalogArtifactService,
    row: tuple[
        KnowledgeAnalysisRunRecord,
        ArtifactRevisionRecord,
        ArtifactRecord,
        ArtifactRevisionRecord,
        ArtifactRecord,
    ],
) -> ResolvedSolutionEvidence:
    run, accepted_revision, accepted_artifact, proposal_revision, proposal_artifact = row
    try:
        request = KnowledgeAnalysisRequestV10.model_validate(run.canonical_request)
        validate_contract("knowledge-analysis-result-v10", accepted_revision.result)
        accepted = KnowledgeAnalysisResultV10.model_validate(accepted_revision.result)
        validate_contract("knowledge-analysis-proposal-receipt-v9", proposal_revision.result)
        receipt = KnowledgeAnalysisProposalReceiptV9.model_validate(proposal_revision.result)

        accepted_pointer, accepted_bytes = _manifest_member(
            accepted_revision,
            artifact_id=accepted_artifact.logical_artifact_id,
            member_path="evidence/accepted-result.json",
            logical_name="accepted-result.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-result/10.0",
        )
        receipt_pointer, receipt_bytes = _manifest_member(
            proposal_revision,
            artifact_id=proposal_artifact.logical_artifact_id,
            member_path="normalized/proposal-receipt.json",
            logical_name="proposal-receipt.json",
            schema_ref=("eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"),
        )
        report_pointer, report_bytes = _manifest_member(
            proposal_revision,
            artifact_id=proposal_artifact.logical_artifact_id,
            member_path="normalized/solution-report.json",
            logical_name="solution-report.json",
            schema_ref="eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
        )
        if (
            run.state != "ACCEPTED"
            or run.predecessor_analysis_run_id is None
            or run.accepted_result_artifact_id != accepted_artifact.logical_artifact_id
            or run.accepted_result_artifact_revision_id != accepted_revision.revision_id
            or run.accepted_result_sha256 != accepted_revision.content_hash
            or run.proposal_artifact_id != proposal_artifact.logical_artifact_id
            or run.proposal_artifact_revision_id != proposal_revision.revision_id
            or not accepted_artifact.approved
            or not accepted_revision.approved
            or not proposal_artifact.approved
            or not proposal_revision.approved
            or accepted_revision.logical_artifact_id != accepted_artifact.logical_artifact_id
            or proposal_revision.logical_artifact_id != proposal_artifact.logical_artifact_id
            or accepted_revision.manifest.get("artifact_type")
            != "knowledge-analysis-accepted-result"
            or accepted_revision.manifest.get("primary_file") != "evidence/accepted-result.json"
            or proposal_revision.manifest.get("artifact_type") != "knowledge-analysis-proposal"
            or proposal_revision.manifest.get("primary_file") != "normalized/proposal-receipt.json"
            or accepted_pointer.sha256 != accepted_revision.content_hash
            or accepted_bytes != accepted_revision.content_bytes
            or receipt_pointer.sha256 != proposal_revision.content_hash
            or receipt_bytes != proposal_revision.content_bytes
            or report_bytes < 1
            or sha256_bytes(canonical_json_bytes(accepted)) != accepted_revision.content_hash
            or sha256_bytes(canonical_json_bytes(receipt)) != proposal_revision.content_hash
            or accepted.analysis_request_id != run.analysis_request_id
            or accepted.analysis_request_sha256 != run.request_sha256
            or accepted.source != request.source
            or accepted.base_analysis != request.base_analysis
            or accepted.base_analysis.analysis_run_id != run.predecessor_analysis_run_id
            or receipt.analysis_request_id != run.analysis_request_id
            or receipt.source != request.source
            or receipt.base_analysis != request.base_analysis
            or receipt.content_set_sha256 != run.proposal_content_set_sha256
            or accepted.proposal_content_set_sha256 != receipt.content_set_sha256
            or accepted.proposal_receipt
            != _proposal_pointer(receipt_pointer, bytes_count=receipt_bytes)
            or receipt.solution_report
            != _proposal_pointer(report_pointer, bytes_count=report_bytes)
        ):
            raise SolutionEvidenceResolutionError("accepted solution evidence chain differs")
        proposal = resolve_knowledge_solution_proposal(artifacts, receipt)
        validate_knowledge_solution_report_references(request, proposal)
        if (
            proposal.analysis_request_id != run.analysis_request_id
            or proposal.base_analysis_result_id != accepted.base_analysis.analysis_result_id
        ):
            raise SolutionEvidenceResolutionError("solution report identity differs")
        pointer_value: dict[str, Any] = {
            "schema_version": "knowledge-solution-evidence-pointer/1.0",
            "base_analysis_run_id": run.predecessor_analysis_run_id,
            "base_analysis_result_id": accepted.base_analysis.analysis_result_id,
            "solution_analysis_run_id": run.analysis_run_id,
            "solution_analysis_result_id": accepted.analysis_result_id,
            "solution_result_sha256": accepted.result_sha256,
            "accepted_result_artifact": accepted_pointer.model_dump(mode="json"),
            "proposal_receipt": receipt_pointer.model_dump(mode="json"),
            "solution_report": report_pointer.model_dump(mode="json"),
            "proposal_content_set_sha256": receipt.content_set_sha256,
            "pointer_sha256": "sha256:" + "0" * 64,
        }
        pointer_value["pointer_sha256"] = content_sha256(
            {key: value for key, value in pointer_value.items() if key != "pointer_sha256"}
        )
        return ResolvedSolutionEvidence(
            pointer=KnowledgeSolutionEvidencePointer.model_validate(pointer_value),
            report=proposal.solution_report,
        )
    except (KnowledgeProposalResolutionError, ValidationError, ValueError) as exc:
        if isinstance(exc, SolutionEvidenceResolutionError):
            raise
        raise SolutionEvidenceResolutionError("accepted solution evidence is invalid") from exc


def resolve_solution_evidence_by_base_run(
    session: Session,
    artifacts: CatalogArtifactService,
    *,
    base_analysis_run_ids: tuple[str, ...],
) -> dict[str, ResolvedSolutionEvidence]:
    """Resolve accepted V10 successors using one indexed relational query."""

    base_ids = tuple(sorted(set(base_analysis_run_ids)))
    if not base_ids:
        return {}
    accepted_revision = aliased(ArtifactRevisionRecord)
    accepted_artifact = aliased(ArtifactRecord)
    proposal_revision = aliased(ArtifactRevisionRecord)
    proposal_artifact = aliased(ArtifactRecord)
    rows = session.execute(
        select(
            KnowledgeAnalysisRunRecord,
            accepted_revision,
            accepted_artifact,
            proposal_revision,
            proposal_artifact,
        )
        .join(
            accepted_revision,
            accepted_revision.revision_id
            == KnowledgeAnalysisRunRecord.accepted_result_artifact_revision_id,
        )
        .join(
            accepted_artifact,
            accepted_artifact.logical_artifact_id
            == KnowledgeAnalysisRunRecord.accepted_result_artifact_id,
        )
        .join(
            proposal_revision,
            proposal_revision.revision_id
            == KnowledgeAnalysisRunRecord.proposal_artifact_revision_id,
        )
        .join(
            proposal_artifact,
            proposal_artifact.logical_artifact_id
            == KnowledgeAnalysisRunRecord.proposal_artifact_id,
        )
        .where(
            KnowledgeAnalysisRunRecord.state == "ACCEPTED",
            KnowledgeAnalysisRunRecord.predecessor_analysis_run_id.in_(base_ids),
            KnowledgeAnalysisRunRecord.canonical_request["schema_version"].astext
            == "knowledge-analysis-request/10.0",
        )
        .order_by(KnowledgeAnalysisRunRecord.predecessor_analysis_run_id)
    ).all()
    resolved: dict[str, ResolvedSolutionEvidence] = {}
    for row in rows:
        run, accepted_rev, accepted_logical, proposal_rev, proposal_logical = row
        value = _resolve_row(
            artifacts,
            (run, accepted_rev, accepted_logical, proposal_rev, proposal_logical),
        )
        base_id = value.pointer.base_analysis_run_id
        if base_id in resolved:
            raise SolutionEvidenceResolutionError(
                "base analysis has more than one accepted solution successor"
            )
        resolved[base_id] = value
    return resolved
