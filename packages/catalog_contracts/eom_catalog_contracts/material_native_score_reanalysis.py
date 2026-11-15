"""One explicit original-score repair target, not a worker authority or new queue."""

from typing import Literal, Self
from uuid import NAMESPACE_URL, uuid5

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_intake import MaterialIdempotencyKey
from eom_catalog_contracts.material_native_files import NATIVE_ITEM_DOCUMENT_REF
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.source_score import (
    HalfSourcePoints,
    IntegerSourcePoints,
    PrintedSourceScoreV2,
    source_score_decimal,
)
from eom_catalog_contracts.validation import validate_contract

NATIVE_SCORE_REANALYSIS_REF = "eom://schemas/material-learning/native-score-reanalysis/1.0"
NATIVE_SCORE_REANALYSIS_MEMBER = "score-reanalysis.json"
NATIVE_SCORE_REANALYSIS_ARTIFACT = "control_material_native_score_reanalysis"
NATIVE_SCORE_REANALYSIS_EVENT = "MATERIAL_NATIVE_SCORE_REANALYSIS_STARTED"


class ReanalyzeNativeMaterialScoresCommand(FrozenModel):
    schema_version: Literal["material-native-score-reanalysis-command/1.0"] = (
        "material-native-score-reanalysis-command/1.0"
    )
    operation: Literal["REANALYZE_NATIVE_MATERIAL_SCORES"] = "REANALYZE_NATIVE_MATERIAL_SCORES"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    idempotency_key: MaterialIdempotencyKey
    run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    expected_updated_at: UtcDatetime

    @model_validator(mode="after")
    def declared_command(self) -> Self:
        validate_contract("material-native-score-reanalysis-v1", self.model_dump(mode="json"))
        return self


def native_score_reanalysis_run_id(command: ReanalyzeNativeMaterialScoresCommand) -> str:
    return (
        "materialrun_"
        + uuid5(
            NAMESPACE_URL,
            "eom:native-score-reanalysis:" + content_sha256(command.model_dump(mode="json")),
        ).hex
    )


class NativeScorePriorItem(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    manifest_sha256: Sha256
    content: ArtifactMemberPointer
    points: IntegerSourcePoints | HalfSourcePoints


class NativeScoreReanalysisTarget(FrozenModel):
    schema_version: Literal["material-native-score-reanalysis-target/1.0"] = (
        "material-native-score-reanalysis-target/1.0"
    )
    command: ReanalyzeNativeMaterialScoresCommand
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    successor_run_id: str = Field(pattern=r"^materialrun_[0-9a-f]{32}$")
    prepared: MaterialArtifactMember
    source_tasks_sha256: Sha256
    source_task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    unit_key: str = Field(min_length=1, max_length=128)
    native_binding_sha256: Sha256
    question: MaterialArtifactMember
    expected_score: PrintedSourceScoreV2
    source_work: MaterialArtifactMember
    source_result: ArtifactMemberPointer
    prior_item: NativeScorePriorItem | None
    reason: Literal["REGISTERED_SCORE_MISMATCH", "LEGACY_SCORE_CONTRACT"]
    target_sha256: Sha256

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        validate_contract("material-native-score-reanalysis-v1", self.model_dump(mode="json"))
        if (
            self.successor_run_id != native_score_reanalysis_run_id(self.command)
            or self.question.schema_ref != NATIVE_ITEM_DOCUMENT_REF
            or self.question.media_type != "application/vnd.hancom.hwpx"
            or self.source_work.schema_ref != "eom://schemas/material-learning/extraction-work/1.0"
            or self.source_work.member_path != "material/work.json"
            or self.source_work.media_type != "application/json"
            or self.source_result.schema_ref
            not in {"material-learning-result@1.0", "material-learning-result@2.0"}
            or self.source_result.member_path != "result.json"
            or self.source_result.media_type != "application/json"
            or self.reason
            != ("REGISTERED_SCORE_MISMATCH" if self.prior_item else "LEGACY_SCORE_CONTRACT")
            or self.target_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"target_sha256"}))
        ):
            raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_SCOPE_INVALID")
        if self.prior_item is not None:
            prior = self.prior_item
            if (
                prior.content.media_type != "application/json"
                or prior.content.schema_ref
                not in {
                    "eom.assessment.item-content/1.0",
                    "eom.assessment.item-content/1.1",
                    "eom://schemas/item-registry/assessment-item-content-v1",
                    "eom://schemas/item-registry/assessment-item-content-v1_1",
                }
                or source_score_decimal(PrintedSourceScoreV2(state="PRINTED", points=prior.points))
                == source_score_decimal(self.expected_score)
            ):
                raise ValueError("MATERIAL_NATIVE_SCORE_REANALYSIS_MISMATCH_REQUIRED")
        return self


def native_score_reanalysis_target_key(run_id: str, source_task_id: str) -> str:
    """Explicit indexed publication identity; no inferred filesystem path or latest."""
    return (
        "native-score-reanalysis:"
        + content_sha256({"run_id": run_id, "source_task_id": source_task_id})[7:]
    )
