"""Evaluation-only LoRA micro-probe contracts for reviewed science visual crops."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.micro_training import LocalImageLoraMicroHyperparameters
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
)
from eom_image_contracts.science_corpus_visual import LocalImageScienceVisualCropSet
from eom_image_contracts.training import (
    LocalImageLoraAdapterFile,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
)

SCIENCE_CROP_SET_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop-set/1.0"
SCIENCE_MICRO_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-lora-micro-probe-plan/1.0"
)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _require_pointer(
    pointer: ImageEvaluationArtifactMember,
    *,
    schema_ref: str,
    member_path: str,
) -> None:
    if (
        pointer.schema_ref != schema_ref
        or pointer.media_type != "application/json"
        or pointer.member_path != member_path
    ):
        raise ValueError("science micro-probe artifact pointer contract mismatch")


class LocalImageScienceLoraMicroProbePlan(FrozenModel):
    schema_version: Literal["local-image-science-lora-micro-probe-plan/1.0"]
    probe_id: str = Field(pattern=r"^imgscimicroprobe_[0-9a-f]{32}$")
    crop_set: ImageEvaluationArtifactMember
    crop_set_sha256: Sha256
    base_model: LocalImageModelPointer
    training_member_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    validation_member_ids: tuple[str, ...] = Field(min_length=1, max_length=1)
    holdout_member_ids: tuple[str, ...] = Field(min_length=2, max_length=2)
    preprocessing_revision: Literal["local-image-science-crop-preprocess/1.0"]
    trainer_contract: Literal["eom-local-image-science-lora-micro-trainer/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraMicroHyperparameters
    seed: int = Field(ge=0, le=2**32 - 1)
    purpose: Literal["EVALUATION_ONLY_SCIENCE_MICRO_PROBE"]
    activation_policy: Literal["FORBIDDEN"]
    authorized_at: datetime
    authorized_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    authorization_reference_sha256: Sha256
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    plan_sha256: Sha256

    @field_validator("authorized_at", "created_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_plan_is_coherent(self) -> LocalImageScienceLoraMicroProbePlan:
        _require_pointer(
            self.crop_set,
            schema_ref=SCIENCE_CROP_SET_SCHEMA_REF,
            member_path="manifests/science-visual-crop-set.json",
        )
        if self.authorized_at > self.created_at:
            raise ValueError("science micro-probe authorization occurs after plan creation")
        member_sets: list[set[str]] = []
        for values, label in (
            (self.training_member_ids, "training members"),
            (self.validation_member_ids, "validation members"),
            (self.holdout_member_ids, "holdout members"),
        ):
            if values != tuple(sorted(set(values))) or any(
                not value.startswith("imgsciviscandidate_") or len(value) != 51 for value in values
            ):
                raise ValueError(f"science micro-probe {label} must be sorted and unique")
            member_sets.append(set(values))
        if any(member_sets[left] & member_sets[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("science micro-probe member partitions overlap")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"probe_id", "plan_sha256"})
        ).removeprefix("sha256:")
        if self.probe_id != "imgscimicroprobe_" + identity[:32]:
            raise ValueError("science micro-probe ID does not bind its plan inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science micro-probe plan hash mismatch")
        return self


class LocalImageScienceLoraMicroProbeCommand(FrozenModel):
    schema_version: Literal["local-image-science-lora-micro-probe-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgscimicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    probe_plan: LocalImageScienceLoraMicroProbePlan
    attempt: Literal[1]
    staged_plan_member: Literal["inputs/science-micro-probe-plan.json"]
    staged_crop_set_member: Literal["inputs/science-visual-crop-set.json"]
    staged_crops_root: Literal["inputs/crops"]
    runtime_dataset_root: Literal["runtime-dataset"]
    output_root_member: Literal["outputs"]
    checkpoint_root_member: Literal["checkpoints"]
    timeout_seconds: int = Field(ge=600, le=14_400)
    command_sha256: Sha256

    @property
    def training_plan(self) -> LocalImageScienceLoraMicroProbePlan:
        return self.probe_plan

    @property
    def training_plan_sha256(self) -> Sha256:
        return self.probe_plan_sha256

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> LocalImageScienceLoraMicroProbeCommand:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=SCIENCE_MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/science-micro-probe-plan.json",
        )
        if self.probe_plan_sha256 != self.probe_plan.plan_sha256:
            raise ValueError("science micro-probe command plan hash mismatch")
        identity = content_sha256(
            {
                "probe_plan_pointer": self.probe_plan_pointer.model_dump(mode="json"),
                "probe_plan_sha256": self.probe_plan_sha256,
                "attempt": self.attempt,
            }
        ).removeprefix("sha256:")
        if self.training_run_id != "imgscimicrotrainrun_" + identity[:32]:
            raise ValueError("science micro-probe run ID does not bind command inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("science micro-probe command hash mismatch")
        return self


class LocalImageScienceLoraMicroRealizedSample(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    exam_group_sha256: Sha256
    training_sample_id: str = Field(pattern=r"^imgtrainsample_[0-9a-f]{32}$")
    source_crop_sha256: Sha256
    realized_crop_sha256: Sha256
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


class LocalImageScienceLoraMicroAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-science-lora-micro-adapter-manifest/1.0"]
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    base_model: LocalImageModelPointer
    probe_plan: ImageEvaluationArtifactMember
    sample_set_sha256: Sha256
    files: tuple[LocalImageLoraAdapterFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_adapter_is_coherent(self) -> LocalImageScienceLoraMicroAdapterManifest:
        _require_pointer(
            self.probe_plan,
            schema_ref=SCIENCE_MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/science-micro-probe-plan.json",
        )
        if tuple(value.relative_path for value in self.files) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise ValueError("science micro-probe adapter files must be exact and sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("science micro-probe adapter manifest hash mismatch")
        return self


class LocalImageScienceLoraMicroProbeWorkerResult(FrozenModel):
    schema_version: Literal["local-image-science-lora-micro-probe-worker-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgscimicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    command_sha256: Sha256
    attempt: Literal[1]
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: LocalImageScienceLoraMicroAdapterManifest | None
    realized_samples: tuple[LocalImageScienceLoraMicroRealizedSample, ...] = Field(max_length=12)
    sample_set_sha256: Sha256 | None
    error_code: str | None = Field(pattern=r"^IMAGE_TRAINING_[A-Z0-9_]{3,96}$")
    runtime: LocalImageLoraTrainingRuntime | None
    completed_steps: int = Field(ge=0, le=200)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_result_is_coherent(self) -> LocalImageScienceLoraMicroProbeWorkerResult:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=SCIENCE_MICRO_PLAN_SCHEMA_REF,
            member_path="manifests/science-micro-probe-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("science micro-probe completion precedes start")
        if self.status == "SUCCEEDED":
            if (
                self.adapter_manifest is None
                or self.error_code is not None
                or self.runtime is None
                or self.sample_set_sha256 is None
                or self.completed_steps != 200
                or self.final_loss is None
                or len(self.realized_samples) != 12
            ):
                raise ValueError("successful science micro-probe result is incomplete")
            keys = tuple(value.training_sample_id for value in self.realized_samples)
            candidates = tuple(value.candidate_id for value in self.realized_samples)
            groups = tuple(value.exam_group_sha256 for value in self.realized_samples)
            source_hashes = tuple(value.source_crop_sha256 for value in self.realized_samples)
            realized_hashes = tuple(value.realized_crop_sha256 for value in self.realized_samples)
            if keys != tuple(sorted(set(keys))) or any(
                len(values) != len(set(values))
                for values in (candidates, groups, source_hashes, realized_hashes)
            ):
                raise ValueError("science micro-probe realized samples are not unique")
            expected_set = content_sha256(
                [value.model_dump(mode="json") for value in self.realized_samples]
            )
            if (
                self.sample_set_sha256 != expected_set
                or self.adapter_manifest.sample_set_sha256 != self.sample_set_sha256
            ):
                raise ValueError("science micro-probe sample set hash mismatch")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed science micro-probe result requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("science micro-probe result hash mismatch")
        return self


def validate_science_micro_probe_plan_sources(
    plan: LocalImageScienceLoraMicroProbePlan,
    crop_set: LocalImageScienceVisualCropSet,
) -> None:
    if plan.crop_set_sha256 != crop_set.crop_set_sha256:
        raise ValueError("science micro-probe crop-set semantic hash mismatch")
    members = {value.candidate_id: value for value in crop_set.members}
    expected = {
        "TRAIN": plan.training_member_ids,
        "VALIDATION": plan.validation_member_ids,
        "HOLDOUT": plan.holdout_member_ids,
    }
    for partition, identities in expected.items():
        if any(
            (member := members.get(identity)) is None or member.partition != partition
            for identity in identities
        ):
            raise ValueError("science micro-probe member partition binding mismatch")
    if set().union(*map(set, expected.values())) != set(members):
        raise ValueError("science micro-probe does not account for every crop-set member")


def validate_science_micro_probe_worker_result(
    command: LocalImageScienceLoraMicroProbeCommand,
    result: LocalImageScienceLoraMicroProbeWorkerResult,
) -> None:
    if (
        result.training_run_id != command.training_run_id
        or result.probe_plan_pointer != command.probe_plan_pointer
        or result.probe_plan_sha256 != command.probe_plan_sha256
        or result.command_sha256 != command.command_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("science micro-probe result does not bind the exact command")
    if result.status == "SUCCEEDED" and {
        value.candidate_id for value in result.realized_samples
    } != set(command.probe_plan.training_member_ids):
        raise ValueError("science micro-probe realized samples differ from training members")
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.probe_plan.base_model
        or result.adapter_manifest.probe_plan != command.probe_plan_pointer
    ):
        raise ValueError("science micro-probe adapter does not bind the exact plan")
