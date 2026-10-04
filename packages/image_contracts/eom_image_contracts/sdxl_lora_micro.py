"""Evaluation-only SDXL UNet LoRA micro contracts, separate from released SSD-1B."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

if TYPE_CHECKING:
    from eom_image_contracts.sdxl_reviewed_micro import LocalImageSdxlReviewedMicroCommand

from eom_image_contracts.micro_training import LocalImageLoraMicroHyperparameters
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_campaign_micro_training import (
    validate_object_line_art_member_partitions,
)
from eom_image_contracts.science_corpus_visual import LocalImageScienceObjectLineArtCropSet
from eom_image_contracts.sdxl_lineart_probe import (
    SdxlExperimentAuthorization,
    SdxlLineartStackPointer,
)
from eom_image_contracts.training import (
    LocalImageLoraAdapterFile,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
)

SDXL_LORA_MICRO_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-lora-micro-command/1.0"
)
SDXL_LORA_MICRO_STYLE_TRIGGER = "eom exam line art, "
_PREFIX = "eom://schemas/image-provider/"
_CropId = Annotated[str, Field(pattern=r"^imgscivislineartcrop_[0-9a-f]{32}$")]


def _utc(value: datetime) -> datetime:
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL micro timestamp must use UTC")
    return value


class SdxlLoraMicroSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgscivislineartcrop_[0-9a-f]{32}$")
    source_image: ImageEvaluationArtifactMember
    source_width_px: int = Field(ge=1, le=4096)
    source_height_px: int = Field(ge=1, le=4096)
    source_caption_en: str = Field(min_length=10, max_length=320, pattern=r"^[ -~]+$")
    source_caption_sha256: Sha256
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        if (
            self.source_image.media_type != "image/png"
            or self.source_image.schema_ref != _PREFIX + "local-image-science-visual-crop/1.0"
            or self.source_image.member_path != "crops/" + self.sample_id + ".png"
            or self.source_caption_en != self.source_caption_en.strip()
            or text_sha256(self.source_caption_en) != self.source_caption_sha256
        ):
            raise ValueError("SDXL micro source/caption binding mismatch")
        boxes = tuple((box.left, box.top, box.right, box.bottom) for box in self.redaction_boxes)
        if boxes != tuple(sorted(set(boxes))):
            raise ValueError("SDXL micro redactions must be uniquely sorted")
        return self

    @property
    def staged_member_path(self) -> str:
        return "inputs/crops/" + self.sample_id + ".png"

    @property
    def training_caption_en(self) -> str:
        return SDXL_LORA_MICRO_STYLE_TRIGGER + self.source_caption_en


class SdxlLoraMicroBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=3_600_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)


class LocalImageSdxlLoraMicroCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-micro-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgsdxlmicrotrainrun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_model: SdxlLineartStackPointer
    crop_set: ImageEvaluationArtifactMember
    crop_set_semantic_sha256: Sha256
    training_authorization: ImageEvaluationArtifactMember
    experiment_authorization: SdxlExperimentAuthorization
    training_samples: tuple[SdxlLoraMicroSample, ...] = Field(min_length=16, max_length=16)
    validation_sample_ids: tuple[_CropId, ...] = Field(min_length=4, max_length=4)
    holdout_sample_ids: tuple[_CropId, ...] = Field(min_length=4, max_length=4)
    caption_policy: Literal["SOURCE_CAPTION_WITH_EXAM_STYLE_TRIGGER/1.0"]
    preprocessing_policy: Literal["GRAYSCALE_REDACT_FIT_768X512/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraMicroHyperparameters
    budget: SdxlLoraMicroBudget
    seed: int = Field(ge=0, le=2**32 - 1)
    purpose: Literal["EVALUATION_ONLY_SDXL_OBJECT_LINE_ART_MICRO"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_experiment(self) -> Self:
        if (
            "INTERNAL_SDXL_LORA_TRAINING" not in self.experiment_authorization.permitted_uses
            or self.experiment_authorization.approved_at > self.created_at
        ):
            raise ValueError("SDXL micro requires prior explicit SDXL training approval")
        for pointer, member, schema in (
            (
                self.crop_set,
                "manifests/science-object-line-art-crop-set.json",
                "local-image-science-object-line-art-crop-set/1.0",
            ),
            (
                self.training_authorization,
                "manifests/science-corpus-training-authorization.json",
                "local-image-science-corpus-training-authorization/1.0",
            ),
        ):
            if (
                pointer.member_path != member
                or pointer.schema_ref != _PREFIX + schema
                or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL micro metadata pointer contract mismatch")
        partitions = (
            tuple(sample.sample_id for sample in self.training_samples),
            self.validation_sample_ids,
            self.holdout_sample_ids,
        )
        seen: set[str] = set()
        for ids in partitions:
            if ids != tuple(sorted(set(ids))) or seen.intersection(ids):
                raise ValueError("SDXL micro partitions must be disjoint and uniquely sorted")
            seen.update(ids)
        references: set[ImageEvaluationArtifactMember] = set()
        for sample in self.training_samples:
            pointer = sample.source_image
            if (
                pointer.artifact_id != self.crop_set.artifact_id
                or pointer.artifact_revision_id != self.crop_set.artifact_revision_id
                or pointer in references
            ):
                raise ValueError("SDXL micro TRAIN reference does not bind crop revision")
            references.add(pointer)
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"training_run_id", "command_sha256"})
        )[7:39]
        if self.training_run_id != "imgsdxlmicrotrainrun_" + identity:
            raise ValueError("SDXL micro run ID does not bind experiment inputs")
        if self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("SDXL micro command hash mismatch")
        return self


def validate_sdxl_lora_micro_sources(
    command: LocalImageSdxlLoraMicroCommand, crop_set: LocalImageScienceObjectLineArtCropSet
) -> None:
    """Reuse partition ownership and bind each exact TRAIN image/caption in O(n)."""
    if (
        command.crop_set_semantic_sha256 != crop_set.crop_set_sha256
        or command.training_authorization != crop_set.training_authorization
    ):
        raise ValueError("SDXL micro source/authorization revision mismatch")
    validate_object_line_art_member_partitions(
        crop_set,
        training_ids=tuple(sample.sample_id for sample in command.training_samples),
        validation_ids=command.validation_sample_ids,
        holdout_ids=command.holdout_sample_ids,
    )
    members = {member.sample_id: member for member in crop_set.members}
    for sample in command.training_samples:
        member = members[sample.sample_id]
        if (
            sample.source_image.sha256 != member.sha256
            or (sample.source_width_px, sample.source_height_px)
            != (member.width_px, member.height_px)
            or sample.source_caption_en != member.caption_en
            or sample.source_caption_sha256 != member.caption_sha256
        ):
            raise ValueError("SDXL micro TRAIN image/caption differs from reviewed source")


class SdxlLoraMicroRealizedSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgscivislineartcrop_[0-9a-f]{32}$")
    source_crop_sha256: Sha256
    realized_crop_sha256: Sha256
    training_caption_sha256: Sha256


class LocalImageSdxlLoraMicroAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-micro-adapter-manifest/1.0"]
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    state: Literal["EVALUATION_ONLY"]
    activation_policy: Literal["FORBIDDEN"]
    base_model: SdxlLineartStackPointer
    training_command_sha256: Sha256
    sample_set_sha256: Sha256
    files: tuple[LocalImageLoraAdapterFile, ...] = Field(min_length=2, max_length=2)
    created_at: datetime
    manifest_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_adapter(self) -> Self:
        if tuple(file.relative_path for file in self.files) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise ValueError("SDXL adapter files must be exact and sorted")
        logical = content_sha256({"training_command_sha256": self.training_command_sha256})[7:39]
        revision = content_sha256(
            {
                "adapter_id": "imgadapter_" + logical,
                "base_model": self.base_model.model_dump(mode="json"),
                "files": [file.model_dump(mode="json") for file in self.files],
            }
        )[7:39]
        if (
            self.adapter_id != "imgadapter_" + logical
            or self.adapter_revision_id != "imgadapterrev_" + revision
            or self.manifest_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        ):
            raise ValueError("SDXL adapter immutable identity/hash mismatch")
        return self


class LocalImageSdxlLoraMicroResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-micro-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgsdxlmicrotrainrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    error_code: str | None = Field(pattern=r"^IMAGE_TRAINING_[A-Z0-9_]{3,96}$")
    adapter_manifest: LocalImageSdxlLoraMicroAdapterManifest | None
    realized_samples: tuple[SdxlLoraMicroRealizedSample, ...] = Field(max_length=16)
    sample_set_sha256: Sha256 | None
    runtime: LocalImageLoraTrainingRuntime | None
    completed_steps: int = Field(ge=0, le=200)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_660_000)
    result_sha256: Sha256

    def complete_sample_count_valid(self) -> bool:
        return len(self.realized_samples) == 16

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_result_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_terminal_result(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("SDXL micro completion precedes start")
        ids = tuple(sample.sample_id for sample in self.realized_samples)
        if ids != tuple(sorted(set(ids))) or len(
            {sample.realized_crop_sha256 for sample in self.realized_samples}
        ) != len(ids):
            raise ValueError(
                "SDXL realized samples must be uniquely sorted without duplicate pixels"
            )
        expected_set = (
            content_sha256([sample.model_dump(mode="json") for sample in self.realized_samples])
            if self.realized_samples
            else None
        )
        if self.sample_set_sha256 != expected_set:
            raise ValueError("SDXL realized sample set hash mismatch")
        if self.status == "SUCCEEDED":
            if (
                self.error_code is not None
                or self.adapter_manifest is None
                or self.runtime is None
                or self.completed_steps != 200
                or self.final_loss is None
                or not self.complete_sample_count_valid()
            ):
                raise ValueError("SDXL micro success requires complete training evidence")
        elif self.error_code is None or self.adapter_manifest is not None:
            raise ValueError("SDXL micro failure cannot carry an accepted adapter")
        if (self.status == "CANCELLED") != (self.error_code == "IMAGE_TRAINING_CANCELLED"):
            raise ValueError("SDXL micro cancellation outcome mismatch")
        if self.adapter_manifest is not None and (
            self.adapter_manifest.training_command_sha256 != self.command_sha256
            or self.adapter_manifest.sample_set_sha256 != self.sample_set_sha256
            or not self.started_at <= self.adapter_manifest.created_at <= self.completed_at
        ):
            raise ValueError("SDXL adapter does not bind terminal training evidence")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("SDXL micro result hash mismatch")
        return self


def validate_sdxl_lora_micro_result(
    command: LocalImageSdxlLoraMicroCommand | LocalImageSdxlReviewedMicroCommand,
    result: LocalImageSdxlLoraMicroResult,
) -> None:
    """Compare terminal evidence with the exact pinned command; never accept by name alone."""
    if (
        result.training_run_id != command.training_run_id
        or result.command_sha256 != command.command_sha256
        or result.started_at < command.created_at
        or result.schema_version.rsplit("/", 1)[1] != command.schema_version.rsplit("/", 1)[1]
    ):
        raise ValueError("SDXL micro result belongs to a different command")
    declared = {sample.sample_id: sample for sample in command.training_samples}
    for realized in result.realized_samples:
        source = declared.get(realized.sample_id)
        if (
            source is None
            or realized.source_crop_sha256 != source.source_image.sha256
            or realized.training_caption_sha256 != text_sha256(source.training_caption_en)
            or (
                command.schema_version.endswith("/1.1")
                and realized.realized_crop_sha256 != source.source_image.sha256
            )
        ):
            raise ValueError("SDXL realized sample differs from pinned TRAIN input")
    if result.status == "SUCCEEDED" and tuple(
        sample.sample_id for sample in result.realized_samples
    ) != tuple(declared):
        raise ValueError("SDXL micro success does not cover the frozen dataset")
    if (
        result.adapter_manifest is not None
        and result.adapter_manifest.base_model != command.base_model
    ):
        raise ValueError("SDXL adapter belongs to a different base stack")
    if result.runtime is not None and any(
        getattr(result.runtime, name) != getattr(command.dependencies, name)
        for name in type(command.dependencies).model_fields
    ):
        raise ValueError("SDXL training runtime dependency drift")
    if result.status == "SUCCEEDED" and (
        result.duration_ms > command.budget.maximum_duration_ms
        or result.runtime is None
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
    ):
        raise ValueError("SDXL micro success exceeded its frozen resource budget")
