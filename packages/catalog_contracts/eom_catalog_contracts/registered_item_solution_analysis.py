"""Additive public solutions over real accepted registered-Item V2 analyses.

The original past-exam V9/V10 contracts stay closed. These values confer neither
source access nor execution permission; application owners resolve the pins.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_contract_values import raw_similarity_contract_value
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    FrozenModel,
    KnowledgeAnalysisBaseReferenceIndex,
    KnowledgeProposalArtifactMember,
    KnowledgeProposalCounts,
    KnowledgeProposalMembers,
    KnowledgeSolutionCounts,
    Sha256,
    _KnowledgeAnalysisRequestBase,
    _KnowledgeAnalysisResultBase,
    knowledge_proposal_member_set_sha256,
    knowledge_solution_content_set_sha256,
)
from eom_catalog_contracts.models import UtcDatetime
from eom_catalog_contracts.validation import CatalogSchemaError, validate_contract


def _wire(value: object, schema: str) -> dict[str, Any]:
    """Reuse the bounded raw-value guard; validate before Pydantic coercion."""
    document = raw_similarity_contract_value(value)
    if not isinstance(document, dict):
        raise ValueError("registered Item solution must be an object")
    try:
        validate_contract(schema, document)
    except (SchemaValidationError, CatalogSchemaError) as error:
        raise ValueError("registered Item solution schema differs") from error
    return document


class RegisteredItemAcceptedResultArtifactMember(KnowledgeProposalArtifactMember):
    """Accepted evidence is not a normalized proposal member."""

    member_path: Literal["evidence/accepted-result.json"] = "evidence/accepted-result.json"
    schema_ref: Literal["eom://schemas/knowledge/knowledge-analysis-result/2.0"] = (
        "eom://schemas/knowledge/knowledge-analysis-result/2.0"
    )
    media_type: Literal["application/json"] = "application/json"


class RegisteredItemSolutionBasePointer(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    analysis_result_id: str = Field(pattern=r"^knowledgeanalysisresult_[0-9a-f]{32}$")
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    # Result self-hash and Artifact member byte hash are deliberately distinct.
    # Only the resolving owner can compare this pin to the materialized result.
    accepted_result_sha256: Sha256
    accepted_result_artifact: RegisteredItemAcceptedResultArtifactMember
    proposal_receipt: KnowledgeProposalArtifactMember
    proposal_content_set_sha256: Sha256
    base_members: KnowledgeProposalMembers
    base_counts: KnowledgeProposalCounts
    reference_index: KnowledgeAnalysisBaseReferenceIndex

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, Any]:
        return _wire(value, "knowledge-analysis-solution-types-v2")

    @model_validator(mode="after")
    def exact_original_v2_base(self) -> Self:
        values = tuple(
            getattr(self.base_members, name) for name in type(self.base_members).model_fields
        )
        identities = {(member.artifact_id, member.artifact_revision_id) for member in values}
        if (
            len(identities) != 1
            or identities
            != {(self.proposal_receipt.artifact_id, self.proposal_receipt.artifact_revision_id)}
            or (
                self.accepted_result_artifact.artifact_id,
                self.accepted_result_artifact.artifact_revision_id,
            )
            in identities
            or knowledge_proposal_member_set_sha256(values) != self.proposal_content_set_sha256
        ):
            raise ValueError("registered solution base identities/content hash differ")
        return self


class KnowledgeAnalysisRequestV11(_KnowledgeAnalysisRequestBase):
    """Package-internal reuse of the original request fields, not V10 reinterpretation."""

    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    schema_version: Literal["knowledge-analysis-request/11.0"] = "knowledge-analysis-request/11.0"
    source: ApprovedItemKnowledgeSourceV2
    worker_proposal_schema_ref: Literal[
        "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0"
    ] = "eom://schemas/knowledge/knowledge-analysis-worker-proposal/8.0"
    accepted_result_schema_ref: Literal[
        "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    ] = "eom://schemas/knowledge/knowledge-analysis-result/11.0"
    predecessor_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    requested_outputs: tuple[Literal["SOLUTION_REPORT"], ...] = Field(  # type: ignore[assignment]
        min_length=1, max_length=1
    )
    base_analysis: RegisteredItemSolutionBasePointer

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, Any]:
        return _wire(value, "knowledge-analysis-request-v11")

    @model_validator(mode="after")
    def exact_outputs_and_hash(self) -> Self:
        # Override the original seven-output analysis rule for this explicit
        # one-report successor; do not broaden that released base's behavior.
        if (
            self.requested_outputs != ("SOLUTION_REPORT",)
            or self.predecessor_analysis_run_id != self.base_analysis.analysis_run_id
            or self.analysis_request_id == self.base_analysis.analysis_request_id
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("registered solution request differs from its pinned base/hash")
        return self


class KnowledgeAnalysisProposalReceiptV10(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    schema_version: Literal["knowledge-analysis-proposal-receipt/10.0"] = (
        "knowledge-analysis-proposal-receipt/10.0"
    )
    analysis_request_id: str = Field(pattern=r"^knowledgeanalysis_[0-9a-f]{32}$")
    source: ApprovedItemKnowledgeSourceV2
    base_analysis: RegisteredItemSolutionBasePointer
    status: Literal["PROPOSED_VALIDATED"] = "PROPOSED_VALIDATED"
    solution_report: KnowledgeProposalArtifactMember
    solution_counts: KnowledgeSolutionCounts
    general_knowledge_used: bool
    content_set_sha256: Sha256
    completed_at: UtcDatetime

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, Any]:
        return _wire(value, "knowledge-analysis-proposal-receipt-v10")

    @model_validator(mode="after")
    def exact_additive_content_set(self) -> Self:
        report = self.solution_report
        if (
            report.member_path != "normalized/solution-report.json"
            or report.schema_ref != "eom://schemas/knowledge/knowledge-analysis-solution-report/1.0"
            or report.media_type != "application/json"
            or report.bytes < 1
            or (report.artifact_id, report.artifact_revision_id)
            == (
                self.base_analysis.proposal_receipt.artifact_id,
                self.base_analysis.proposal_receipt.artifact_revision_id,
            )
            or knowledge_solution_content_set_sha256(self.base_analysis.base_members, report)
            != self.content_set_sha256
        ):
            raise ValueError("registered solution receipt member/content hash differ")
        return self


class KnowledgeAnalysisResultV11(_KnowledgeAnalysisResultBase):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    schema_version: Literal["knowledge-analysis-result/11.0"] = "knowledge-analysis-result/11.0"
    source: ApprovedItemKnowledgeSourceV2
    base_analysis: RegisteredItemSolutionBasePointer
    solution_counts: KnowledgeSolutionCounts

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> dict[str, Any]:
        return _wire(value, "knowledge-analysis-result-v11")

    @model_validator(mode="after")
    def exact_original_base_and_receipt(self) -> Self:
        if (
            self.proposal_receipt.schema_ref
            != "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/10.0"
            or self.counts != self.base_analysis.base_counts
            or self.analysis_request_id == self.base_analysis.analysis_request_id
        ):
            raise ValueError("registered solution result differs from its base/receipt")
        return self
