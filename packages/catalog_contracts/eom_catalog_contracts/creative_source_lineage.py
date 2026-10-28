"""Source-fidelity registration evidence, not a claim of scientific correctness."""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

CREATIVE_SOURCE_LINEAGE_SCHEMA = "creative-source-lineage-v1"
CREATIVE_SOURCE_LINEAGE_SCHEMA_REF = "eom://schemas/external-item/creative-source-lineage/1.0"
CREATIVE_SOURCE_REGISTRATION_POLICY = "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"
type CreativeSourceAnswerMode = Literal[
    "EDITORIAL_SOURCE", "MODEL_PROPOSAL_UNVERIFIED", "NOT_APPLICABLE"
]
type CreativeSourceNormalizationAction = Literal[
    "PRESERVED_EDITORIAL_ANSWER", "PRESERVED_EDITORIAL_EXPLANATION"
]


class CreativeSourceLineage(FrozenModel):
    schema_version: Literal["creative-source-lineage/1.0"] = "creative-source-lineage/1.0"
    lineage_id: str = Field(pattern=r"^extlineage_[0-9a-f]{32}$")
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    import_id: str = Field(pattern=r"^extimport_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    origin_kind: Literal["PAST_EXAM_VARIATION", "FREE_AUTHORING"]
    source_input_sha256: Sha256
    observation_sha256: Sha256
    selection: ExternalItemLearningRoleSelection
    role_result: ArtifactMemberPointer
    result_id: str = Field(pattern=r"^extlearnresult_[0-9a-f]{32}$")
    result_sha256: Sha256
    proposed_content_sha256: Sha256
    registered_content_sha256: Sha256
    source_answer_mode: CreativeSourceAnswerMode
    normalization_actions: tuple[CreativeSourceNormalizationAction, ...] = Field(max_length=4)
    warning_codes: tuple[str, ...] = Field(max_length=64)
    registration_policy: Literal["PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"] = (
        "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"
    )
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    lineage_sha256: Sha256

    @model_validator(mode="after")
    def exact_bounded_lineage(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract(CREATIVE_SOURCE_LINEAGE_SCHEMA, document)
        if self.lineage_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "lineage_sha256"}
        ):
            raise ValueError("creative source lineage hash differs")
        if len(self.normalization_actions) != len(set(self.normalization_actions)):
            raise ValueError("creative source normalization actions repeat")
        if self.warning_codes != tuple(sorted(set(self.warning_codes))):
            raise ValueError("creative source warnings must be sorted and unique")
        return self
