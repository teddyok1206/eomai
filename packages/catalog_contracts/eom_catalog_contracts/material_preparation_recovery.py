"""Explicit failed preparation successor, not arbitrary runtime replacement authority."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialOperatorId, MaterialRunState
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract


class RecoverMaterialPreparationCommand(FrozenModel):
    schema_version: Literal["material-learning-preparation-recovery/1.0"] = (
        "material-learning-preparation-recovery/1.0"
    )
    operation: Literal["RECOVER_MATERIAL_PREPARATION"] = "RECOVER_MATERIAL_PREPARATION"
    actor_id: MaterialOperatorId
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    expected_updated_at: UtcDatetime
    expected_input_sha256: Sha256
    target_profile_sha256: Sha256
    error_code: Literal["CREATIVE_PAGE_RENDERER_FAILED", "MATERIAL_LEARNING_SOURCE_FILE_INVALID"]

    @model_validator(mode="after")
    def closed_command(self) -> Self:
        validate_contract("material-learning-preparation-recovery-v1", self.model_dump(mode="json"))
        return self


class MaterialPreparationRecoveryResult(FrozenModel):
    schema_version: Literal["material-learning-preparation-recovery-result/1.0"] = (
        "material-learning-preparation-recovery-result/1.0"
    )
    predecessor_run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    predecessor_task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    old_input: MaterialArtifactMember
    new_input: MaterialArtifactMember
    old_profile_sha256: Sha256
    new_profile_sha256: Sha256
    state: MaterialRunState
    replayed: bool

    @model_validator(mode="after")
    def exact_successor(self) -> Self:
        if (
            self.predecessor_run_id == self.run_id
            or self.predecessor_task_id == self.task_id
            or self.old_input == self.new_input
            or self.old_input.sha256 == self.new_input.sha256
            or self.old_profile_sha256 == self.new_profile_sha256
            or self.old_input.schema_ref != self.new_input.schema_ref
        ):
            raise ValueError("MATERIAL_PREPARATION_RECOVERY_SUCCESSOR_INVALID")
        validate_contract(
            "material-learning-preparation-recovery-result-v1", self.model_dump(mode="json")
        )
        return self
