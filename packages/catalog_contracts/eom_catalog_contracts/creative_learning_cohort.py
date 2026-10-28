"""An admitted immutable source cohort, not a transferable browser/worker grant."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

CREATIVE_COHORT_SCHEMA_REF = "eom://schemas/external-item/creative-learning-cohort/1.0"


class CreativeCohortTarget(FrozenModel):
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    external_number: str = Field(pattern=r"^[0-9]{5}$")
    observation_sha256: Sha256
    selected_edition: Literal[2, 3]


class CreativeCohortPresetPin(FrozenModel):
    preset_id: str = Field(pattern=r"^execpreset_[0-9a-f]{32}$")
    preset_revision_id: str = Field(pattern=r"^execpresetrev_[0-9a-f]{32}$")
    sha256: Sha256


class CreativeLearningCohort(FrozenModel):
    schema_version: Literal["creative-learning-cohort/1.0"] = "creative-learning-cohort/1.0"
    cohort_id: str = Field(pattern=r"^creativecohort_[0-9a-f]{32}$")
    import_id: str = Field(pattern=r"^extimport_[0-9a-f]{32}$")
    requested_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: UtcDatetime
    targets: tuple[CreativeCohortTarget, ...] = Field(min_length=3, max_length=20000)
    target_set_sha256: Sha256
    seed_external_number: str = Field(pattern=r"^[0-9]{5}$")
    seed_selection: ExternalItemLearningRoleSelection
    extraction_preset: CreativeCohortPresetPin
    analysis_preset: CreativeCohortPresetPin
    capacity_policy_revision_id: str = Field(pattern=r"^capacityrev_[0-9a-f]{32}$")
    workflow_definition_sha256: Sha256
    content_pack_release_id: str = Field(pattern=r"^packrel_[0-9a-f]{32}$")
    risk_policy_revision_id: str = Field(pattern=r"^analysisriskrev_[0-9a-f]{32}$")
    risk_policy_sha256: Sha256
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    registration_policy: Literal["PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"] = (
        "PRESERVE_SOURCE_WITH_REVIEW_WARNINGS_V1"
    )
    cohort_sha256: Sha256

    @model_validator(mode="after")
    def exact_target_set(self) -> Self:
        document = self.model_dump(mode="json")
        validate_contract("creative-learning-cohort-v1", document)
        numbers = tuple(target.external_number for target in self.targets)
        if numbers != tuple(sorted(set(numbers))) or self.seed_external_number not in numbers:
            raise ValueError("creative cohort target order or seed differs")
        for attribute in ("source_id", "source_revision_id"):
            if len({getattr(target, attribute) for target in self.targets}) != len(self.targets):
                raise ValueError("creative cohort source repeats")
        if self.target_set_sha256 != content_sha256(document["targets"]):
            raise ValueError("creative cohort target hash differs")
        if self.cohort_sha256 != content_sha256(
            {key: value for key, value in document.items() if key != "cohort_sha256"}
        ):
            raise ValueError("creative cohort hash differs")
        return self
