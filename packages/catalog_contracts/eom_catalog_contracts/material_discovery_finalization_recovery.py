"""Explicit native discovery finalization successor, not a model retry command."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialOperatorId, MaterialRunState
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract


class RecoverNativeMaterialDiscoveryFinalizationCommand(FrozenModel):
    schema_version: Literal["material-native-discovery-finalization-recovery/1.0"] = (
        "material-native-discovery-finalization-recovery/1.0"
    )
    operation: Literal["RECOVER_NATIVE_MATERIAL_DISCOVERY_FINALIZATION"] = (
        "RECOVER_NATIVE_MATERIAL_DISCOVERY_FINALIZATION"
    )
    actor_id: MaterialOperatorId
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    expected_updated_at: UtcDatetime
    expected_prepared_sha256: Sha256
    target_source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def closed_command(self) -> Self:
        validate_contract(
            "material-native-discovery-finalization-recovery-v1", self.model_dump(mode="json")
        )
        return self


class NativeMaterialDiscoveryFinalizationRecoveryResult(FrozenModel):
    schema_version: Literal["material-native-discovery-finalization-recovery-result/1.0"] = (
        "material-native-discovery-finalization-recovery-result/1.0"
    )
    predecessor_run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    prepared: MaterialArtifactMember
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    reused_tasks: int = Field(strict=True, ge=1, le=1_000_000)
    state: MaterialRunState
    replayed: bool

    @model_validator(mode="after")
    def exact_native_successor(self) -> Self:
        if self.predecessor_run_id == self.run_id:
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_SUCCESSOR_INVALID")
        if (
            self.prepared.schema_ref != "eom://schemas/material-learning/prepared/2.0"
            or self.prepared.member_path != "material/prepared.json"
            or self.prepared.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_NATIVE_FINALIZATION_PREPARED_POINTER_INVALID")
        validate_contract(
            "material-native-discovery-finalization-recovery-result-v1",
            self.model_dump(mode="json"),
        )
        return self
