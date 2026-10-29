"""A bounded successor pin set referencing the original admitted source cohort."""

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


@dataclass(frozen=True, slots=True)
class CreativeLearningExecutionScope:
    """Ephemeral composition; the original targets remain a single canonical value."""

    cohort: CreativeLearningCohort
    continuation: CreativeLearningContinuation | None = None

    def __post_init__(self) -> None:
        if self.continuation is not None and (
            self.continuation.requested_by_operator_id != self.cohort.requested_by_operator_id
            or self.continuation.target_set_sha256 != self.cohort.target_set_sha256
            or self.continuation.cohort_id == self.cohort.cohort_id
        ):
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
