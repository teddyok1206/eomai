"""Native-size SDXL training contracts; released micro protocols remain immutable."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.sdxl_lineart_probe import (
    SdxlExperimentAuthorization,
    SdxlLineartStackPointer,
)
from eom_image_contracts.sdxl_lora_micro import SDXL_LORA_MICRO_STYLE_TRIGGER, sdxl_lora_adapter_ids
from eom_image_contracts.sdxl_native_training_targets import (
    NATIVE_TARGET_CANVASES,
    SDXL_EXTERIOR_TARGET_COMMAND_SCHEMA_REF,
    SDXL_EXTERIOR_TARGET_RESULT_SCHEMA_REF,
    SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF,
    SDXL_NATIVE_TARGET_PNG_SCHEMA_REF,
    SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF,
    NativeTargetCanvas,
)
from eom_image_contracts.sdxl_training_targets import TargetExpression
from eom_image_contracts.training import (
    LocalImageLoraAdapterFile,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
)
from eom_image_contracts.validation import validate_contract

_PREFIX = "eom://schemas/image-provider/local-image-"
SDXL_NATIVE_LORA_COMMAND_SCHEMA_REF = _PREFIX + "sdxl-native-lora-command/1.0"
SDXL_NATIVE_LORA_COMMAND_V2_SCHEMA_REF = _PREFIX + "sdxl-native-lora-command/1.1"
SDXL_NATIVE_LORA_RESULT_SCHEMA_REF = _PREFIX + "sdxl-native-lora-result/1.0"
SDXL_NATIVE_LORA_ADAPTER_SCHEMA_REF = _PREFIX + "sdxl-native-lora-adapter-manifest/1.0"
NativeLoraProfile = Literal["NATIVE_RESOLUTION_PILOT", "FULL_STYLE_TRAINING"]
NativeLoraComposition = Literal["ISOLATED_ON_WHITE", "AUTHORED_SCENE"]
_PROFILE_LIMITS: Mapping[NativeLoraProfile, tuple[int, int, int, int]] = MappingProxyType(
    {"NATIVE_RESOLUTION_PILOT": (12, 64, 20, 200), "FULL_STYLE_TRAINING": (100, 200, 200, 1000)}
)
_EXPRESSION_TEXT: Mapping[TargetExpression, str] = MappingProxyType(
    {
        "CLEAN_CONTOUR": "clean contour lines",
        "RESTRAINED_TONE": "contour lines with restrained gray tone",
        "FINE_HATCHING": "contour lines with fine hatching",
    }
)
_COMPOSITION_TEXT: Mapping[NativeLoraComposition, str] = MappingProxyType(
    {
        "ISOLATED_ON_WHITE": "plain white background",
        "AUTHORED_SCENE": "authored scene with its depicted background",
    }
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL_NATIVE_LORA_TIMESTAMP_NOT_UTC")
    return value


class SdxlNativeLoraConditioning(FrozenModel):
    literal_subject: str = Field(min_length=10, max_length=256, pattern=r"^[ -~]+$")
    expression: TargetExpression
    composition: NativeLoraComposition

    @field_validator("literal_subject")
    @classmethod
    def canonical_subject(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("SDXL_NATIVE_LORA_CAPTION_NOT_CANONICAL")
        return value

    @property
    def training_caption_en(self) -> str:
        return (
            SDXL_LORA_MICRO_STYLE_TRIGGER
            + self.literal_subject
            + ", "
            + _EXPRESSION_TEXT[self.expression]
            + ", "
            + _COMPOSITION_TEXT[self.composition]
        )


class SdxlNativeLoraTargetBatch(FrozenModel):
    command: ImageEvaluationArtifactMember
    result: ImageEvaluationArtifactMember
    _schema_pairs: ClassVar[tuple[tuple[str, str], ...]] = (
        (SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF, SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF),
    )

    @model_validator(mode="after")
    def exact_protocol(self) -> Self:
        if (self.command.schema_ref, self.result.schema_ref) not in self._schema_pairs:
            raise ValueError("SDXL_NATIVE_LORA_BATCH_POINTER_INVALID")
        for pointer, name in (
            (self.command, "command"),
            (self.result, "result"),
        ):
            if (
                pointer.member_path != f"manifests/sdxl-training-target-{name}.json"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL_NATIVE_LORA_BATCH_POINTER_INVALID")
        return self


class SdxlNativeLoraTargetBatchV2(SdxlNativeLoraTargetBatch):
    _schema_pairs: ClassVar[tuple[tuple[str, str], ...]] = (
        (SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF, SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF),
        (SDXL_EXTERIOR_TARGET_COMMAND_SCHEMA_REF, SDXL_EXTERIOR_TARGET_RESULT_SCHEMA_REF),
    )


class SdxlNativeLoraSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    target_id: str = Field(pattern=r"^imgsdxltarget_[0-9a-f]{32}$")
    target_revision_id: str = Field(pattern=r"^imgsdxltargetrev_[0-9a-f]{32}$")
    source_image: ImageEvaluationArtifactMember
    source_document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    exam_group_sha256: Sha256
    canvas: NativeTargetCanvas
    conditioning: SdxlNativeLoraConditioning
    training_caption_sha256: Sha256

    @model_validator(mode="after")
    def exact_target(self) -> Self:
        if (
            self.source_image.member_path != f"targets/{self.target_id}.png"
            or self.source_image.schema_ref != SDXL_NATIVE_TARGET_PNG_SCHEMA_REF
            or self.source_image.media_type != "image/png"
            or self.training_caption_sha256 != text_sha256(self.training_caption_en)
        ):
            raise ValueError("SDXL_NATIVE_LORA_TARGET_OR_CAPTION_INVALID")
        return self

    @property
    def training_caption_en(self) -> str:
        return self.conditioning.training_caption_en

    @property
    def width_height(self) -> tuple[int, int]:
        return NATIVE_TARGET_CANVASES[self.canvas]

    @property
    def staged_member_path(self) -> str:
        return f"inputs/targets/{self.sample_id}.png"


class SdxlNativeLoraHyperparameters(FrozenModel):
    adapter_type: Literal["UNET_LORA"]
    rank: Literal[8]
    alpha: Literal[8]
    train_batch_size: Literal[1]
    gradient_accumulation_steps: Literal[4]
    gradient_checkpointing: Literal[True]
    mixed_precision: Literal["fp16"]
    optimizer: Literal["adamw_8bit"]
    learning_rate: Literal["1e-4"]
    max_train_steps: int = Field(ge=20, le=1000)
    checkpointing_steps: Literal[0]
    random_flip: Literal[False]
    train_text_encoders: Literal[False]
    train_vae: Literal[False]


class SdxlNativeLoraBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=3_600_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)
    maximum_input_png_bytes: int = Field(ge=1, le=128 * 1024**2)


class _NativeLoraCommand(FrozenModel):
    schema_version: str
    training_run_id: str = Field(pattern=r"^imgsdxlnativetrainrun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_model: SdxlLineartStackPointer
    training_authorization: ImageEvaluationArtifactMember
    experiment_authorization: SdxlExperimentAuthorization
    target_batches: tuple[SdxlNativeLoraTargetBatch, ...] = Field(min_length=1, max_length=8)
    training_samples: tuple[SdxlNativeLoraSample, ...] = Field(min_length=12, max_length=200)
    profile: NativeLoraProfile
    review_scope: Literal["OWN_TRAIN_COHORT_SCREENING_NOT_INDEPENDENT"]
    screening_evidence: ImageEvaluationArtifactMember
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    caption_policy: Literal["REVIEWED_SUBJECT_EXPRESSION_COMPOSITION/1.0"]
    preprocessing_policy: Literal["EXACT_ADMITTED_PREPARED_NATIVE_RGB/1.0"]
    checkpoint_policy: Literal["TERMINAL_ONLY_NO_RESUME/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: SdxlNativeLoraHyperparameters
    budget: SdxlNativeLoraBudget
    seed: int = Field(ge=0, le=2**32 - 1)
    purpose: Literal["EVALUATION_ONLY_SDXL_NATIVE_STYLE_TRAINING"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at", "reviewed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def frozen_cohort(self) -> Self:
        lower, upper, minimum_steps, maximum_steps = _PROFILE_LIMITS[self.profile]
        if not lower <= len(self.training_samples) <= upper or not (
            minimum_steps <= self.hyperparameters.max_train_steps <= maximum_steps
        ):
            raise ValueError("SDXL_NATIVE_LORA_PROFILE_BUDGET_INVALID")
        if (
            "INTERNAL_SDXL_LORA_TRAINING" not in self.experiment_authorization.permitted_uses
            or not self.experiment_authorization.approved_at <= self.reviewed_at <= self.created_at
        ):
            raise ValueError("SDXL_NATIVE_LORA_APPROVAL_OR_REVIEW_CHRONOLOGY_INVALID")
        if (
            self.training_authorization.schema_ref
            != _PREFIX + "science-corpus-training-authorization/1.0"
            or self.training_authorization.member_path
            != "manifests/science-corpus-training-authorization.json"
            or self.training_authorization.media_type != "application/json"
            or self.screening_evidence.media_type != "text/plain"
            or self.screening_evidence.schema_ref != "eom://schemas/operations/plain-text-log/1.0"
            or not self.screening_evidence.member_path.startswith("reports/")
        ):
            raise ValueError("SDXL_NATIVE_LORA_AUTHORIZATION_OR_REVIEW_POINTER_INVALID")
        batches = tuple(
            (b.result.artifact_id, b.result.artifact_revision_id) for b in self.target_batches
        )
        ids = tuple(s.sample_id for s in self.training_samples)
        if batches != tuple(sorted(set(batches))) or ids != tuple(sorted(set(ids))):
            raise ValueError("SDXL_NATIVE_LORA_COHORT_ORDER_OR_DUPLICATES_INVALID")
        if len({s.target_id for s in self.training_samples}) != len(ids) or (
            len({s.source_image.sha256 for s in self.training_samples}) != len(ids)
        ):
            raise ValueError("SDXL_NATIVE_LORA_DUPLICATE_TARGET_OR_PIXELS")
        batch_ids = set(batches)
        used = {
            (s.source_image.artifact_id, s.source_image.artifact_revision_id)
            for s in self.training_samples
        }
        if used != batch_ids:
            raise ValueError("SDXL_NATIVE_LORA_SELECTED_BATCH_COVERAGE_INVALID")
        documents = Counter(s.source_document_id for s in self.training_samples)
        groups = Counter(s.exam_group_sha256 for s in self.training_samples)
        if max(documents.values()) > 3 or max(groups.values()) > 4:
            raise ValueError("SDXL_NATIVE_LORA_SOURCE_CONCENTRATION_EXCEEDED")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"training_run_id", "command_sha256"})
        )
        if self.training_run_id != "imgsdxlnativetrainrun_" + identity[7:39] or (
            self.command_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        ):
            raise ValueError("SDXL_NATIVE_LORA_COMMAND_IDENTITY_OR_HASH_INVALID")
        return self


class LocalImageSdxlNativeLoraCommand(_NativeLoraCommand):
    schema_version: Literal["local-image-sdxl-native-lora-command/1.0"]


class LocalImageSdxlNativeLoraCommandV2(_NativeLoraCommand):
    schema_version: Literal["local-image-sdxl-native-lora-command/1.1"]
    target_batches: tuple[SdxlNativeLoraTargetBatchV2, ...] = Field(min_length=1, max_length=8)


NativeLoraCommand = LocalImageSdxlNativeLoraCommand | LocalImageSdxlNativeLoraCommandV2


@dataclass(frozen=True, slots=True)
class NativeLoraCommandProtocol:
    contract: str
    model: type[LocalImageSdxlNativeLoraCommand] | type[LocalImageSdxlNativeLoraCommandV2]


_NATIVE_LORA_COMMAND_PROTOCOLS: Mapping[str, NativeLoraCommandProtocol] = MappingProxyType(
    {
        "local-image-sdxl-native-lora-command/1.0": NativeLoraCommandProtocol(
            "sdxl-native-lora-command",
            LocalImageSdxlNativeLoraCommand,
        ),
        "local-image-sdxl-native-lora-command/1.1": NativeLoraCommandProtocol(
            "sdxl-native-lora-command-v2",
            LocalImageSdxlNativeLoraCommandV2,
        ),
    }
)


def native_lora_command_protocol(version: str) -> NativeLoraCommandProtocol:
    try:
        return _NATIVE_LORA_COMMAND_PROTOCOLS[version]
    except KeyError as exc:
        raise ValueError("SDXL_NATIVE_LORA_COMMAND_PROTOCOL_UNSUPPORTED") from exc


class SdxlNativeLoraRealizedSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    target_png_sha256: Sha256
    training_caption_sha256: Sha256
    canvas: NativeTargetCanvas


class LocalImageSdxlNativeLoraAdapterManifest(FrozenModel):
    schema_version: Literal["local-image-sdxl-native-lora-adapter-manifest/1.0"]
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
    profile: NativeLoraProfile

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def immutable_adapter(self) -> Self:
        ids = sdxl_lora_adapter_ids(
            training_command_sha256=self.training_command_sha256,
            base_model=self.base_model,
            files=self.files,
        )
        if (self.adapter_id, self.adapter_revision_id) != ids or (
            self.manifest_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        ):
            raise ValueError("SDXL_NATIVE_LORA_ADAPTER_IDENTITY_OR_HASH_INVALID")
        return self


class LocalImageSdxlNativeLoraResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-native-lora-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgsdxlnativetrainrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    profile: NativeLoraProfile
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    error_code: str | None = Field(pattern=r"^IMAGE_TRAINING_[A-Z0-9_]{3,96}$")
    adapter_manifest: LocalImageSdxlNativeLoraAdapterManifest | None
    realized_samples: tuple[SdxlNativeLoraRealizedSample, ...] = Field(max_length=200)
    sample_set_sha256: Sha256 | None
    runtime: LocalImageLoraTrainingRuntime | None
    requested_steps: int = Field(ge=20, le=1000)
    completed_steps: int = Field(ge=0, le=1000)
    final_loss: float | None = Field(ge=0, le=1_000_000)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=3_660_000)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def terminal_evidence(self) -> Self:
        lower, upper, minimum_steps, maximum_steps = _PROFILE_LIMITS[self.profile]
        ids = tuple(s.sample_id for s in self.realized_samples)
        if (
            self.completed_at < self.started_at
            or not minimum_steps <= self.requested_steps <= maximum_steps
            or self.completed_steps > self.requested_steps
            or len(ids) > upper
            or ids != tuple(sorted(set(ids)))
            or len({s.target_png_sha256 for s in self.realized_samples}) != len(ids)
        ):
            raise ValueError("SDXL_NATIVE_LORA_TERMINAL_SCOPE_INVALID")
        expected = (
            content_sha256([s.model_dump(mode="json") for s in self.realized_samples])
            if ids
            else None
        )
        if self.sample_set_sha256 != expected:
            raise ValueError("SDXL_NATIVE_LORA_REALIZED_SET_HASH_INVALID")
        if self.status == "SUCCEEDED":
            if (
                self.error_code is not None
                or self.adapter_manifest is None
                or self.runtime is None
                or self.final_loss is None
                or self.completed_steps != self.requested_steps
                or len(ids) < lower
            ):
                raise ValueError("SDXL_NATIVE_LORA_SUCCESS_EVIDENCE_INCOMPLETE")
        elif self.error_code is None or self.adapter_manifest is not None:
            raise ValueError("SDXL_NATIVE_LORA_FAILURE_HAS_ACCEPTED_ADAPTER")
        if (self.status == "CANCELLED") != (self.error_code == "IMAGE_TRAINING_CANCELLED"):
            raise ValueError("SDXL_NATIVE_LORA_CANCELLATION_INVALID")
        if self.adapter_manifest is not None and (
            self.adapter_manifest.training_command_sha256 != self.command_sha256
            or self.adapter_manifest.sample_set_sha256 != self.sample_set_sha256
            or self.adapter_manifest.profile != self.profile
            or not self.started_at <= self.adapter_manifest.created_at <= self.completed_at
        ):
            raise ValueError("SDXL_NATIVE_LORA_ADAPTER_TERMINAL_BINDING_INVALID")
        if self.result_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"result_sha256"})
        ):
            raise ValueError("SDXL_NATIVE_LORA_RESULT_HASH_INVALID")
        return self


def validate_sdxl_native_lora_result(
    command: NativeLoraCommand, result: LocalImageSdxlNativeLoraResult
) -> None:
    """Bind terminal evidence to the exact cohort/recipe, not a protocol-name alias."""
    validate_contract("sdxl-native-lora-result", result.model_dump(mode="json"))
    if (
        result.training_run_id != command.training_run_id
        or result.command_sha256 != command.command_sha256
        or result.profile != command.profile
        or result.requested_steps != command.hyperparameters.max_train_steps
        or result.started_at < command.created_at
    ):
        raise ValueError("SDXL_NATIVE_LORA_RESULT_COMMAND_BINDING_INVALID")
    declared = {s.sample_id: s for s in command.training_samples}
    for realized in result.realized_samples:
        sample = declared.get(realized.sample_id)
        if sample is None or (
            realized.target_png_sha256 != sample.source_image.sha256
            or realized.training_caption_sha256 != sample.training_caption_sha256
            or realized.canvas != sample.canvas
        ):
            raise ValueError("SDXL_NATIVE_LORA_REALIZED_SAMPLE_BINDING_INVALID")
    if result.status == "SUCCEEDED" and tuple(
        s.sample_id for s in result.realized_samples
    ) != tuple(declared):
        raise ValueError("SDXL_NATIVE_LORA_RESULT_COHORT_INCOMPLETE")
    if (
        result.adapter_manifest is not None
        and result.adapter_manifest.base_model != command.base_model
    ):
        raise ValueError("SDXL_NATIVE_LORA_ADAPTER_BASE_MODEL_INVALID")
    if result.runtime is not None and any(
        getattr(result.runtime, name) != getattr(command.dependencies, name)
        for name in type(command.dependencies).model_fields
    ):
        raise ValueError("SDXL_NATIVE_LORA_RUNTIME_DEPENDENCY_DRIFT")
    if result.status == "SUCCEEDED" and (
        result.duration_ms > command.budget.maximum_duration_ms
        or result.runtime is None
        or result.runtime.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
    ):
        raise ValueError("SDXL_NATIVE_LORA_RESULT_RESOURCE_BUDGET_EXCEEDED")
