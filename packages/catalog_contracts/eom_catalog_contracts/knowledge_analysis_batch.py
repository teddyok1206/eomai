"""Protocol-first contracts for durable Educational Document analysis batches."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import ActorId, FrozenModel, UtcDatetime

CurriculumUnitKey = Annotated[
    str,
    Field(
        pattern=(
            r"^(1-\([1-4]\)|2-\([1-6]\)|3-\([1-7]\)|4-\([1-7]\)|"
            r"5-\([1-7]\)|6-\([1-4]\))$"
        )
    ),
]


class KnowledgeAnalysisBatchSourceRange(FrozenModel):
    source_kind: Literal["DOCUMENT_REVISION"] = "DOCUMENT_REVISION"
    source_class: Literal["TEXTBOOK"] = "TEXTBOOK"
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    first_physical_page: int = Field(ge=1, le=10000)
    last_physical_page: int = Field(ge=1, le=10000)
    curriculum_unit_keys: tuple[CurriculumUnitKey, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def bounded_and_canonical(self) -> KnowledgeAnalysisBatchSourceRange:
        if self.last_physical_page < self.first_physical_page:
            raise ValueError("batch source page range is reversed")
        if self.last_physical_page - self.first_physical_page + 1 > 32:
            raise ValueError("batch source page range exceeds 32 pages")
        if self.curriculum_unit_keys != tuple(sorted(set(self.curriculum_unit_keys))):
            raise ValueError("batch curriculum keys must be sorted and unique")
        return self


class ExecuteKnowledgeAnalysisRange(FrozenModel):
    mode: Literal["EXECUTE"] = "EXECUTE"
    predecessor_analysis_run_id: str | None = Field(
        default=None, pattern=r"^analysisrun_[0-9a-f]{32}$"
    )


class ReuseAcceptedKnowledgeAnalysisRange(FrozenModel):
    mode: Literal["REUSE_ACCEPTED"] = "REUSE_ACCEPTED"
    accepted_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")


KnowledgeAnalysisBatchRangeExecution = Annotated[
    ExecuteKnowledgeAnalysisRange | ReuseAcceptedKnowledgeAnalysisRange,
    Field(discriminator="mode"),
]


class KnowledgeAnalysisBatchRangeRequest(FrozenModel):
    ordinal: int = Field(ge=0, le=999)
    source: KnowledgeAnalysisBatchSourceRange
    execution: KnowledgeAnalysisBatchRangeExecution


class KnowledgeAnalysisBatchRequest(FrozenModel):
    schema_version: Literal["knowledge-analysis-batch-request/1.0"] = (
        "knowledge-analysis-batch-request/1.0"
    )
    preset_key: Literal["knowledge-analysis"] = "knowledge-analysis"
    general_knowledge_mode: Literal["AUXILIARY_UNATTRIBUTED"] = "AUXILIARY_UNATTRIBUTED"
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    review_policy: Literal["PREAUTHORIZED_APPROVE_VALIDATED"] = "PREAUTHORIZED_APPROVE_VALIDATED"
    ranges: tuple[KnowledgeAnalysisBatchRangeRequest, ...] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def ordered_nonoverlapping_ranges(self) -> KnowledgeAnalysisBatchRequest:
        if tuple(item.ordinal for item in self.ranges) != tuple(range(len(self.ranges))):
            raise ValueError("batch range ordinals must be contiguous from zero")
        prior_by_revision: dict[str, KnowledgeAnalysisBatchSourceRange] = {}
        predecessor_ids: set[str] = set()
        accepted_ids: set[str] = set()
        for item in self.ranges:
            source = item.source
            prior = prior_by_revision.get(source.document_revision_id)
            if prior is not None and source.first_physical_page <= prior.last_physical_page:
                raise ValueError("batch document page ranges overlap or are unordered")
            prior_by_revision[source.document_revision_id] = source
            execution = item.execution
            if isinstance(execution, ExecuteKnowledgeAnalysisRange):
                predecessor = execution.predecessor_analysis_run_id
                if predecessor is not None:
                    if predecessor in predecessor_ids or predecessor in accepted_ids:
                        raise ValueError("batch analysis run pointers must be unique")
                    predecessor_ids.add(predecessor)
            else:
                accepted = execution.accepted_analysis_run_id
                if accepted in accepted_ids or accepted in predecessor_ids:
                    raise ValueError("batch analysis run pointers must be unique")
                accepted_ids.add(accepted)
        return self


class CreateKnowledgeAnalysisBatchCommand(FrozenModel):
    operation: Literal["CREATE_KNOWLEDGE_ANALYSIS_BATCH"] = "CREATE_KNOWLEDGE_ANALYSIS_BATCH"
    request: KnowledgeAnalysisBatchRequest
    requested_by: ActorId
    authorized_at: UtcDatetime
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[\x21-\x7e]+$")
    submission_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def command_hash_matches(self) -> CreateKnowledgeAnalysisBatchCommand:
        canonical = self.model_dump(
            mode="json",
            exclude={"operation", "authorized_at", "idempotency_key", "submission_sha256"},
        )
        if content_sha256(canonical) != self.submission_sha256:
            raise ValueError("batch command hash does not match canonical input")
        return self


class KnowledgeAnalysisBatchApplicationResult(FrozenModel):
    batch_id: str = Field(pattern=r"^analysisbatch_[0-9a-f]{32}$")
    state: Literal["QUEUED", "RUNNING", "BLOCKED", "SUCCEEDED", "CANCELLED"]
    resource_version: int = Field(ge=1)
    total_range_count: int = Field(ge=1, le=1000)
    accepted_range_count: int = Field(ge=0, le=1000)
    failed_range_count: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def coherent_counts(self) -> KnowledgeAnalysisBatchApplicationResult:
        if self.accepted_range_count + self.failed_range_count > self.total_range_count:
            raise ValueError("batch result terminal counts exceed total")
        if self.state == "SUCCEEDED" and self.accepted_range_count != self.total_range_count:
            raise ValueError("succeeded batch requires every range accepted")
        if self.state == "BLOCKED" and self.failed_range_count == 0:
            raise ValueError("blocked batch requires a failed range")
        return self
