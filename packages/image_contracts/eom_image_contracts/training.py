"""Immutable contracts for bounded local-image LoRA training."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    ImageEvaluationSourceSnapshot,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
    text_sha256,
)

AUTHORIZATION_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-authorization/1.0"
DATASET_SCHEMA_REF = "eom://schemas/image-provider/local-image-training-dataset-manifest/1.0"
CANDIDATE_INVENTORY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-training-candidate-inventory/1.0"
)
TRAINING_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-lora-training-plan/1.0"
ADAPTER_MANIFEST_SCHEMA_REF = "eom://schemas/image-provider/local-image-lora-adapter-manifest/1.0"
EVALUATION_PLAN_SCHEMA_REF = "eom://schemas/image-provider/local-image-quality-evaluation-plan/1.0"


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
        raise ValueError("artifact pointer contract mismatch")


class ImageTrainingRightsPolicy(FrozenModel):
    rights_policy_id: str = Field(pattern=r"^rightspolicy_[0-9a-f]{32}$")
    rights_policy_revision_id: str = Field(pattern=r"^rightspolicyrev_[0-9a-f]{32}$")
    rights_policy_sha256: Sha256


class LocalImageTrainingAuthorization(FrozenModel):
    schema_version: Literal["local-image-training-authorization/1.0"]
    authorization_id: str = Field(pattern=r"^imgtrainauth_[0-9a-f]{32}$")
    authorization_revision_id: str = Field(pattern=r"^imgtrainauthrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgtrainauthrev_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    rights_policies: tuple[ImageTrainingRightsPolicy, ...] = Field(
        min_length=1,
        max_length=100,
    )
    permitted_use: Literal["INTERNAL_LORA_TRAINING"]
    derivative_output: Literal["LORA_ADAPTER_ONLY"]
    state: Literal["APPROVED"]
    approved_at: datetime
    approved_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    authorization_sha256: Sha256

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def revision_and_hash_are_coherent(self) -> LocalImageTrainingAuthorization:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("training authorization revision chain is inconsistent")
        revision_ids = tuple(policy.rights_policy_revision_id for policy in self.rights_policies)
        if revision_ids != tuple(sorted(revision_ids)) or len(revision_ids) != len(
            set(revision_ids)
        ):
            raise ValueError("training rights policies must be uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"authorization_sha256"}))
        if self.authorization_sha256 != expected:
            raise ValueError("training authorization hash mismatch")
        return self


class LocalImageTrainingCropMember(FrozenModel):
    member_path: str = Field(
        pattern=r"^samples/imgtrainsample_[0-9a-f]{32}\.png$",
    )
    media_type: Literal["image/png"]
    width_px: Literal[768]
    height_px: Literal[512]
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageTrainingSample(FrozenModel):
    training_sample_id: str = Field(pattern=r"^imgtrainsample_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    source_page_image: ImageEvaluationArtifactMember
    bounding_box: ImageEvaluationBoundingBox
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal["COMPOSITE", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER"]
    crop_member: LocalImageTrainingCropMember
    caption_en: str = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def source_and_crop_are_coherent(self) -> LocalImageTrainingSample:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("training source page image must be PNG")
        expected_member = f"samples/{self.training_sample_id}.png"
        if self.crop_member.member_path != expected_member:
            raise ValueError("training crop path does not bind the sample identity")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("training caption hash mismatch")
        return self


class LocalImageTrainingCandidate(FrozenModel):
    candidate_id: str = Field(pattern=r"^imgtraincandidate_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    extraction_result: ImageEvaluationArtifactMember
    source_anchor_id: str = Field(pattern=r"^assessmentanchor_[0-9a-f]{32}$")
    source_page_image: ImageEvaluationArtifactMember
    physical_page: int = Field(ge=1, le=100_000)
    bounding_box: ImageEvaluationBoundingBox
    rights_policy: ImageTrainingRightsPolicy
    representation_kind: Literal["COMPOSITE", "PHOTOGRAPH"]
    rendering_mode: Literal["MIXED", "RASTER"]
    caption_en: str = Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    )
    caption_sha256: Sha256

    @model_validator(mode="after")
    def candidate_is_coherent(self) -> LocalImageTrainingCandidate:
        if self.source_page_image.media_type != "image/png":
            raise ValueError("training candidate source page image must be PNG")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("training candidate caption hash mismatch")
        return self


class LocalImageTrainingCandidateInventory(FrozenModel):
    schema_version: Literal["local-image-training-candidate-inventory/1.0"]
    inventory_id: str = Field(pattern=r"^imgtraininventory_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    candidates: tuple[LocalImageTrainingCandidate, ...] = Field(min_length=1, max_length=537)
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    inventory_sha256: Sha256

    @field_validator("holdout_sample_ids")
    @classmethod
    def valid_holdout_samples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^imgsample_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout sample identity")
        return value

    @field_validator("holdout_source_anchor_ids")
    @classmethod
    def valid_holdout_anchors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^assessmentanchor_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout source anchor identity")
        return value

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_inventory_is_coherent(self) -> LocalImageTrainingCandidateInventory:
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        for values, label in (
            (self.holdout_sample_ids, "holdout samples"),
            (self.holdout_source_anchor_ids, "holdout source anchors"),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{label} must be uniquely sorted")
        candidate_ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if candidate_ids != tuple(sorted(candidate_ids)) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("training candidates must be uniquely sorted")
        anchors = tuple(candidate.source_anchor_id for candidate in self.candidates)
        if len(anchors) != len(set(anchors)):
            raise ValueError("training candidate source anchors must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"inventory_sha256"}))
        if self.inventory_sha256 != expected:
            raise ValueError("training candidate inventory hash mismatch")
        return self


class LocalImageTrainingDatasetManifest(FrozenModel):
    schema_version: Literal["local-image-training-dataset-manifest/1.0"]
    dataset_id: str = Field(pattern=r"^imgdataset_[0-9a-f]{32}$")
    dataset_revision_id: str = Field(pattern=r"^imgdatasetrev_[0-9a-f]{32}$")
    revision_number: int = Field(ge=1, le=100_000)
    previous_revision_id: str | None = Field(pattern=r"^imgdatasetrev_[0-9a-f]{32}$")
    source_snapshot: ImageEvaluationSourceSnapshot
    training_authorization: ImageEvaluationArtifactMember
    candidate_inventory: ImageEvaluationArtifactMember
    base_model: LocalImageModelPointer
    eligibility_policy_revision: Literal["local-image-lora-eligibility/1.0"]
    holdout_evaluation_plan: ImageEvaluationArtifactMember
    holdout_sample_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    holdout_source_anchor_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    samples: tuple[LocalImageTrainingSample, ...] = Field(min_length=100, max_length=200)
    sample_set_sha256: Sha256
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    dataset_sha256: Sha256

    @field_validator("holdout_sample_ids")
    @classmethod
    def valid_holdout_samples(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^imgsample_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout sample identity")
        return value

    @field_validator("holdout_source_anchor_ids")
    @classmethod
    def valid_holdout_anchors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        pattern = re.compile(r"^assessmentanchor_[0-9a-f]{32}$")
        if any(pattern.fullmatch(item) is None for item in value):
            raise ValueError("invalid holdout source anchor identity")
        return value

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_dataset_is_coherent(self) -> LocalImageTrainingDatasetManifest:
        if (self.revision_number == 1) != (self.previous_revision_id is None):
            raise ValueError("training dataset revision chain is inconsistent")
        _require_pointer(
            self.training_authorization,
            schema_ref=AUTHORIZATION_SCHEMA_REF,
            member_path="manifests/training-authorization.json",
        )
        _require_pointer(
            self.candidate_inventory,
            schema_ref=CANDIDATE_INVENTORY_SCHEMA_REF,
            member_path="manifests/training-candidates.json",
        )
        _require_pointer(
            self.holdout_evaluation_plan,
            schema_ref=EVALUATION_PLAN_SCHEMA_REF,
            member_path="manifests/evaluation-plan.json",
        )
        if self.holdout_sample_ids != tuple(sorted(self.holdout_sample_ids)) or len(
            self.holdout_sample_ids
        ) != len(set(self.holdout_sample_ids)):
            raise ValueError("holdout samples must be uniquely sorted")
        if self.holdout_source_anchor_ids != tuple(sorted(self.holdout_source_anchor_ids)) or len(
            self.holdout_source_anchor_ids
        ) != len(set(self.holdout_source_anchor_ids)):
            raise ValueError("holdout source anchors must be uniquely sorted")
        sample_ids = tuple(sample.training_sample_id for sample in self.samples)
        if sample_ids != tuple(sorted(sample_ids)) or len(sample_ids) != len(set(sample_ids)):
            raise ValueError("training samples must be uniquely sorted")
        source_anchors = tuple(sample.source_anchor_id for sample in self.samples)
        if len(source_anchors) != len(set(source_anchors)):
            raise ValueError("training source anchors must be unique")
        if set(source_anchors) & set(self.holdout_source_anchor_ids):
            raise ValueError("training dataset contains a holdout source anchor")
        crop_hashes = tuple(sample.crop_member.sha256 for sample in self.samples)
        if len(crop_hashes) != len(set(crop_hashes)):
            raise ValueError("training dataset contains duplicate crop bytes")
        expected_sample_set = content_sha256(
            [sample.model_dump(mode="json") for sample in self.samples]
        )
        if self.sample_set_sha256 != expected_sample_set:
            raise ValueError("training sample-set hash mismatch")
        expected_dataset = content_sha256(self.model_dump(mode="json", exclude={"dataset_sha256"}))
        if self.dataset_sha256 != expected_dataset:
            raise ValueError("training dataset hash mismatch")
        return self


class LocalImageTrainerDependencies(FrozenModel):
    python_version: str = Field(min_length=1, max_length=64)
    torch_version: str = Field(min_length=1, max_length=64)
    diffusers_version: str = Field(min_length=1, max_length=64)
    transformers_version: str = Field(min_length=1, max_length=64)
    accelerate_version: str = Field(min_length=1, max_length=64)
    peft_version: str = Field(min_length=1, max_length=64)
    bitsandbytes_version: str = Field(min_length=1, max_length=64)


class LocalImageLoraHyperparameters(FrozenModel):
    adapter_type: Literal["UNET_LORA"]
    rank: Literal[8]
    alpha: Literal[8]
    resolution_width: Literal[768]
    resolution_height: Literal[512]
    train_batch_size: Literal[1]
    gradient_accumulation_steps: Literal[4]
    gradient_checkpointing: Literal[True]
    mixed_precision: Literal["fp16"]
    optimizer: Literal["adamw_8bit"]
    learning_rate: Literal["1e-4"]
    max_train_steps: int = Field(ge=200, le=2000)
    checkpointing_steps: int = Field(ge=100, le=500)
    random_flip: Literal[False]
    train_text_encoders: Literal[False]
    train_vae: Literal[False]


class LocalImageLoraTrainingPlan(FrozenModel):
    schema_version: Literal["local-image-lora-training-plan/1.0"]
    training_plan_id: str = Field(pattern=r"^imgtrainplan_[0-9a-f]{32}$")
    dataset_manifest: ImageEvaluationArtifactMember
    base_model: LocalImageModelPointer
    trainer_contract: Literal["eom-local-image-lora-trainer/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraHyperparameters
    seed: int = Field(ge=0, le=2**32 - 1)
    created_at: datetime
    created_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_plan_is_coherent(self) -> LocalImageLoraTrainingPlan:
        _require_pointer(
            self.dataset_manifest,
            schema_ref=DATASET_SCHEMA_REF,
            member_path="manifests/training-dataset.json",
        )
        if self.hyperparameters.checkpointing_steps > self.hyperparameters.max_train_steps:
            raise ValueError("checkpoint interval exceeds total training steps")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("LoRA training plan hash mismatch")
        return self


class LocalImageLoraAdapterFile(FrozenModel):
    relative_path: Literal["adapter_config.json", "adapter_model.safetensors"]
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    sha256: Sha256


class LocalImageLoraAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-lora-adapter-manifest/1.0"]
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    state: Literal["CANDIDATE"]
    base_model: LocalImageModelPointer
    dataset_manifest: ImageEvaluationArtifactMember
    training_plan: ImageEvaluationArtifactMember
    files: tuple[LocalImageLoraAdapterFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_creation(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def immutable_adapter_is_coherent(self) -> LocalImageLoraAdapterManifest:
        _require_pointer(
            self.dataset_manifest,
            schema_ref=DATASET_SCHEMA_REF,
            member_path="manifests/training-dataset.json",
        )
        _require_pointer(
            self.training_plan,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        paths = tuple(item.relative_path for item in self.files)
        if paths != ("adapter_config.json", "adapter_model.safetensors"):
            raise ValueError("LoRA adapter files must be exact and uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("LoRA adapter manifest hash mismatch")
        return self


class LocalImageLoraTrainingRuntime(LocalImageTrainerDependencies):
    cuda_version: str = Field(min_length=1, max_length=128)
    gpu_name: str = Field(min_length=1, max_length=128)
    compute_capability: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    peak_gpu_memory_bytes: int = Field(ge=1)


class LocalImageLoraTrainingReceipt(FrozenModel):
    schema_version: Literal["local-image-lora-training-receipt/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan: ImageEvaluationArtifactMember
    attempt: int = Field(ge=1, le=10)
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: ImageEvaluationArtifactMember | None
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    runtime: LocalImageLoraTrainingRuntime
    completed_steps: int = Field(ge=0, le=2000)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_receipt_is_coherent(self) -> LocalImageLoraTrainingReceipt:
        _require_pointer(
            self.training_plan,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("LoRA training completion precedes start")
        if self.status == "SUCCEEDED":
            if self.adapter_manifest is None or self.error_code is not None:
                raise ValueError("successful LoRA training requires only an adapter manifest")
            _require_pointer(
                self.adapter_manifest,
                schema_ref=ADAPTER_MANIFEST_SCHEMA_REF,
                member_path="manifests/adapter-manifest.json",
            )
            if self.completed_steps < 200 or self.final_loss is None:
                raise ValueError("successful LoRA training receipt is incomplete")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed or cancelled LoRA training requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("LoRA training receipt hash mismatch")
        return self


class LocalImageLoraTrainingCommand(FrozenModel):
    schema_version: Literal["local-image-lora-training-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan_pointer: ImageEvaluationArtifactMember
    training_plan_sha256: Sha256
    training_plan: LocalImageLoraTrainingPlan
    attempt: int = Field(ge=1, le=10)
    staged_plan_member: Literal["inputs/training-plan.json"]
    staged_dataset_root: Literal["inputs/dataset"]
    output_root_member: Literal["outputs"]
    checkpoint_root_member: Literal["checkpoints"]
    timeout_seconds: int = Field(ge=600, le=86_400)
    command_sha256: Sha256

    @model_validator(mode="after")
    def command_is_coherent(self) -> LocalImageLoraTrainingCommand:
        _require_pointer(
            self.training_plan_pointer,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.training_plan_sha256 != self.training_plan.plan_sha256:
            raise ValueError("LoRA training command plan hash mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("LoRA training command hash mismatch")
        return self


class LocalImageLoraTrainingWorkerResult(FrozenModel):
    schema_version: Literal["local-image-lora-training-worker-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgtrainrun_[0-9a-f]{32}$")
    training_plan_pointer: ImageEvaluationArtifactMember
    training_plan_sha256: Sha256
    attempt: int = Field(ge=1, le=10)
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: LocalImageLoraAdapterManifest | None
    error_code: str | None = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    runtime: LocalImageLoraTrainingRuntime
    completed_steps: int = Field(ge=0, le=2000)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def worker_result_is_coherent(self) -> LocalImageLoraTrainingWorkerResult:
        _require_pointer(
            self.training_plan_pointer,
            schema_ref=TRAINING_PLAN_SCHEMA_REF,
            member_path="manifests/training-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("LoRA worker completion precedes start")
        if self.status == "SUCCEEDED":
            if self.adapter_manifest is None or self.error_code is not None:
                raise ValueError("successful LoRA worker requires only an adapter manifest")
            if self.completed_steps < 200 or self.final_loss is None:
                raise ValueError("successful LoRA worker result is incomplete")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError("failed or cancelled LoRA worker requires only an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("LoRA worker result hash mismatch")
        return self


def validate_training_dataset_authorization(
    dataset: LocalImageTrainingDatasetManifest,
    authorization: LocalImageTrainingAuthorization,
) -> None:
    """Validate a dataset against the exact approved rights and source snapshot."""

    if dataset.source_snapshot != authorization.source_snapshot:
        raise ValueError("training dataset source snapshot is not authorized")
    authorized = {
        policy.rights_policy_revision_id: policy for policy in authorization.rights_policies
    }
    for sample in dataset.samples:
        if authorized.get(sample.rights_policy.rights_policy_revision_id) != sample.rights_policy:
            raise ValueError("training sample lacks an exact authorized rights policy")


def validate_training_dataset_inventory(
    dataset: LocalImageTrainingDatasetManifest,
    inventory: LocalImageTrainingCandidateInventory,
) -> None:
    """Validate that every dataset sample came from one exact candidate inventory."""

    if (
        dataset.source_snapshot != inventory.source_snapshot
        or dataset.holdout_evaluation_plan != inventory.holdout_evaluation_plan
        or dataset.holdout_sample_ids != inventory.holdout_sample_ids
        or dataset.holdout_source_anchor_ids != inventory.holdout_source_anchor_ids
    ):
        raise ValueError("training dataset and candidate inventory pins do not match")
    candidates = {candidate.source_anchor_id: candidate for candidate in inventory.candidates}
    for sample in dataset.samples:
        candidate = candidates.get(sample.source_anchor_id)
        if candidate is None:
            raise ValueError("training sample is absent from the candidate inventory")
        if (
            sample.item_revision_id != candidate.item_revision_id
            or sample.extraction_result != candidate.extraction_result
            or sample.source_page_image != candidate.source_page_image
            or sample.bounding_box != candidate.bounding_box
            or sample.rights_policy != candidate.rights_policy
            or sample.representation_kind != candidate.representation_kind
            or sample.rendering_mode != candidate.rendering_mode
            or sample.caption_en != candidate.caption_en
            or sample.caption_sha256 != candidate.caption_sha256
        ):
            raise ValueError("training sample drifts from its candidate inventory")


def validate_lora_training_plan(
    plan: LocalImageLoraTrainingPlan,
    dataset: LocalImageTrainingDatasetManifest,
) -> None:
    """Validate a plan against the exact immutable dataset and base model."""

    if plan.base_model != dataset.base_model:
        raise ValueError("LoRA training plan base model does not match the dataset")


def validate_lora_training_receipt(
    receipt: LocalImageLoraTrainingReceipt,
    plan: LocalImageLoraTrainingPlan,
    adapter: LocalImageLoraAdapterManifest | None,
) -> None:
    """Validate terminal receipt linkage without resolving implicit latest revisions."""

    if receipt.status == "SUCCEEDED":
        if adapter is None or adapter.base_model != plan.base_model:
            raise ValueError("LoRA adapter does not bind the training plan base model")
    elif adapter is not None:
        raise ValueError("non-successful LoRA training cannot publish an adapter")


def validate_lora_training_worker_result(
    command: LocalImageLoraTrainingCommand,
    result: LocalImageLoraTrainingWorkerResult,
) -> None:
    """Validate one worker result against its exact orchestrator command."""

    if (
        result.training_run_id != command.training_run_id
        or result.training_plan_pointer != command.training_plan_pointer
        or result.training_plan_sha256 != command.training_plan_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("LoRA worker result does not bind the exact command")
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.training_plan.base_model
        or result.adapter_manifest.dataset_manifest != command.training_plan.dataset_manifest
        or result.adapter_manifest.training_plan != command.training_plan_pointer
    ):
        raise ValueError("LoRA worker adapter manifest drifts from the command")
