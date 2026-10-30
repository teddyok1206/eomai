"""A bounded successor pin set referencing the original admitted source cohort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.creative_learning_cohort import (
    CreativeCohortPresetPin,
    CreativeLearningCohort,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

CREATIVE_CONTINUATION_REF = "eom://schemas/external-item/creative-learning-continuation/1.0"
CREATIVE_PARALLEL_CONTINUATION_REF = (
    "eom://schemas/external-item/creative-learning-continuation/1.1"
)


class CreativeLearningContinuation(FrozenModel):
    schema_version: Literal["creative-learning-continuation/1.0"] = (
        "creative-learning-continuation/1.0"
    )
    cohort_id: str = Field(pattern=r"^creativecohort_[0-9a-f]{32}$")
    parent_cohort: ArtifactMemberPointer
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    target_set_sha256: Sha256
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    workflow_definition_version: Literal["2.0.0"] = "2.0.0"
    workflow_definition_sha256: Sha256
    extraction_preset: CreativeCohortPresetPin
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    continuation_reason: Literal["SOURCE_VISUAL_CONTRACT_SUCCESSOR"] = (
        "SOURCE_VISUAL_CONTRACT_SUCCESSOR"
    )
    cohort_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract("creative-learning-continuation-v1", document)
        if self.cohort_sha256 != content_sha256(
            {k: v for k, v in document.items() if k != "cohort_sha256"}
        ):
            raise ValueError("CREATIVE_CONTINUATION_HASH_MISMATCH")
        return self


def validate_creative_continuation_parent(
    continuation: CreativeLearningContinuation,
    parent: CreativeLearningCohort,
    actual_parent: ArtifactMemberPointer,
) -> None:
    if (
        continuation.parent_cohort != actual_parent
        or continuation.cohort_id == parent.cohort_id
        or continuation.requested_by_operator_id != parent.requested_by_operator_id
        or continuation.target_set_sha256 != parent.target_set_sha256
    ):
        raise ValueError("CREATIVE_CONTINUATION_PARENT_MISMATCH")


class CreativeParallelCapacityPin(FrozenModel):
    capacity_policy_id: str = Field(pattern=r"^capacity_[0-9a-f]{32}$")
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    schema_ref: Literal["eom://schemas/workflow/worker-capacity-policy/1.4"]
    sha256: Sha256


class CreativeLearningParallelContinuation(FrozenModel):
    """Six bounded source states, at most three workers and one Graph batch owner."""

    schema_version: Literal["creative-learning-continuation/1.1"]
    cohort_id: str = Field(pattern=r"^creativecohort_[0-9a-f]{32}$")
    parent_cohort: ArtifactMemberPointer
    predecessor_execution: ArtifactMemberPointer
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    target_set_sha256: Sha256
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    workflow_definition_version: Literal["2.0.0"]
    workflow_definition_sha256: Sha256
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    extraction_preset: CreativeCohortPresetPin
    analysis_preset: CreativeCohortPresetPin
    extraction_preset_key: Literal["creative-source-learning-parallel"]
    analysis_preset_key: Literal["creative-knowledge-analysis-parallel"]
    capacity_policy: CreativeParallelCapacityPin
    max_in_flight_sources: Literal[6]
    max_report_workers: Literal[3]
    graph_publication_batch_size: Literal[3]
    continuation_reason: Literal["THREE_SLOT_REPORT_CAPACITY_SUCCESSOR"]
    cohort_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract("creative-learning-parallel-continuation-v1", document)
        if self.cohort_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "cohort_sha256"}
        ):
            raise ValueError("CREATIVE_PARALLEL_CONTINUATION_HASH_MISMATCH")
        return self


@dataclass(frozen=True, slots=True)
class CreativeLearningExecutionScope:
    """Ephemeral composition; the original targets remain a single canonical value."""

    cohort: CreativeLearningCohort
    continuation: CreativeLearningContinuation | CreativeLearningParallelContinuation | None = None
    predecessor_scope: CreativeLearningExecutionScope | None = None

    def __post_init__(self) -> None:
        if self.continuation is not None and (
            self.continuation.requested_by_operator_id != self.cohort.requested_by_operator_id
            or self.continuation.target_set_sha256 != self.cohort.target_set_sha256
            or self.continuation.cohort_id == self.cohort.cohort_id
        ):
            raise ValueError("CREATIVE_CONTINUATION_PARENT_MISMATCH")
        if isinstance(self.continuation, CreativeLearningParallelContinuation):
            previous = self.predecessor_scope
            if (
                previous is None
                or not isinstance(previous.continuation, CreativeLearningContinuation)
                or previous.cohort.cohort_id != self.cohort.cohort_id
                or previous.cohort.cohort_sha256 != self.cohort.cohort_sha256
            ):
                raise ValueError("CREATIVE_PARALLEL_CONTINUATION_PARENT_MISMATCH")
            # Composition checks values, not storage existence/authority. The
            # owner must still resolve and compare the actual predecessor pointer.
            validate_creative_parallel_predecessor(
                self.continuation, previous, self.continuation.predecessor_execution
            )
        elif self.predecessor_scope is not None:
            raise ValueError("CREATIVE_CONTINUATION_PARENT_MISMATCH")

    @property
    def cohort_id(self) -> str:
        return (self.continuation or self.cohort).cohort_id

    @property
    def source_commit(self) -> str:
        return (self.continuation or self.cohort).source_commit

    @property
    def extraction_preset(self) -> CreativeCohortPresetPin:
        return (self.continuation or self.cohort).extraction_preset

    @property
    def workflow_definition_version(self) -> str:
        return "2.0.0" if self.continuation else "1.0.0"

    @property
    def workflow_definition_sha256(self) -> str:
        return (self.continuation or self.cohort).workflow_definition_sha256

    @property
    def content_pack_release_id(self) -> str:
        return (self.continuation or self.cohort).content_pack_release_id

    @property
    def analysis_preset(self) -> CreativeCohortPresetPin:
        return (
            self.continuation.analysis_preset
            if isinstance(self.continuation, CreativeLearningParallelContinuation)
            else self.cohort.analysis_preset
        )

    @property
    def capacity_policy_revision_id(self) -> str:
        return (
            self.continuation.capacity_policy.capacity_policy_revision_id
            if isinstance(self.continuation, CreativeLearningParallelContinuation)
            else self.cohort.capacity_policy_revision_id
        )

    @property
    def max_in_flight_sources(self) -> int:
        return (
            self.continuation.max_in_flight_sources
            if isinstance(self.continuation, CreativeLearningParallelContinuation)
            else 1
        )

    @property
    def extraction_preset_key(self) -> str:
        if isinstance(self.continuation, CreativeLearningParallelContinuation):
            return self.continuation.extraction_preset_key
        return "creative-source-learning" if self.continuation else "external-item-learning"

    @property
    def analysis_preset_key(self) -> str:
        if isinstance(self.continuation, CreativeLearningParallelContinuation):
            return self.continuation.analysis_preset_key
        return "creative-knowledge-analysis"

    @property
    def history_scopes(self) -> tuple[CreativeLearningExecutionScope, ...]:
        """Newest first, at most three exact admitted scopes; no latest lookup."""
        if self.predecessor_scope is not None:
            return (self, *self.predecessor_scope.history_scopes)
        if self.continuation is not None:
            return (self, CreativeLearningExecutionScope(self.cohort))
        return (self,)


def validate_creative_parallel_predecessor(
    continuation: CreativeLearningParallelContinuation,
    predecessor: CreativeLearningExecutionScope,
    actual_predecessor: ArtifactMemberPointer,
) -> None:
    serial = predecessor.continuation
    if (
        not isinstance(serial, CreativeLearningContinuation)
        or continuation.predecessor_execution != actual_predecessor
        or continuation.parent_cohort != serial.parent_cohort
        or continuation.requested_by_operator_id != predecessor.cohort.requested_by_operator_id
        or continuation.target_set_sha256 != predecessor.cohort.target_set_sha256
        or continuation.cohort_id in {predecessor.cohort_id, predecessor.cohort.cohort_id}
        or continuation.workflow_definition_version != predecessor.workflow_definition_version
        or continuation.workflow_definition_sha256 != predecessor.workflow_definition_sha256
        or continuation.content_pack_release_id != predecessor.content_pack_release_id
        or continuation.capacity_policy.capacity_policy_revision_id
        == predecessor.capacity_policy_revision_id
        or continuation.extraction_preset.preset_id == predecessor.extraction_preset.preset_id
        or continuation.analysis_preset.preset_id == predecessor.analysis_preset.preset_id
    ):
        raise ValueError("CREATIVE_PARALLEL_CONTINUATION_PARENT_MISMATCH")
