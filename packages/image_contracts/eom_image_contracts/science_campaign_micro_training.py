"""Evaluation-only LoRA micro-probe contracts for a reviewed science campaign."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.micro_training import LocalImageLoraMicroHyperparameters
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    LocalImageModelPointer,
    Sha256,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_corpus_visual import (
    LocalImageScienceVisualCampaignCropSet,
    LocalImageScienceVisualCampaignCropSetV2,
)
from eom_image_contracts.training import (
    LocalImageLoraAdapterFile,
    LocalImageLoraTrainingRuntime,
    LocalImageTrainerDependencies,
)

CAMPAIGN_CROP_SET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-campaign-crop-set/1.0"
)
CAMPAIGN_MICRO_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-campaign-lora-micro-probe-plan/1.0"
)
CAMPAIGN_CROP_SET_V2_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-visual-campaign-crop-set/1.1"
)
CAMPAIGN_MICRO_PLAN_V2_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-science-campaign-lora-micro-probe-plan/1.1"
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
        raise ValueError("science campaign micro-probe artifact pointer contract mismatch")


class LocalImageScienceCampaignLoraMicroProbePlan(FrozenModel):
    crop_set_schema_ref: ClassVar[str] = CAMPAIGN_CROP_SET_SCHEMA_REF

    schema_version: Literal["local-image-science-campaign-lora-micro-probe-plan/1.0"]
    probe_id: str = Field(pattern=r"^imgscicampaignmicroprobe_[0-9a-f]{32}$")
    crop_set: ImageEvaluationArtifactMember
    crop_set_sha256: Sha256
    base_model: LocalImageModelPointer
    training_member_ids: tuple[str, ...] = Field(min_length=12, max_length=12)
    validation_member_ids: tuple[str, ...] = Field(min_length=1, max_length=1)
    holdout_member_ids: tuple[str, ...] = Field(min_length=2, max_length=2)
    preprocessing_revision: Literal["local-image-science-crop-preprocess/1.0"]
    trainer_contract: Literal["eom-local-image-science-campaign-lora-micro-trainer/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraMicroHyperparameters
    seed: int = Field(ge=0, le=2**32 - 1)
    purpose: Literal["EVALUATION_ONLY_SCIENCE_CAMPAIGN_MICRO_PROBE"]
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
    def immutable_plan_is_coherent(self) -> LocalImageScienceCampaignLoraMicroProbePlan:
        _require_pointer(
            self.crop_set,
            schema_ref=self.crop_set_schema_ref,
            member_path="manifests/science-visual-campaign-crop-set.json",
        )
        if self.authorized_at > self.created_at:
            raise ValueError(
                "science campaign micro-probe authorization occurs after plan creation"
            )
        member_sets: list[set[str]] = []
        for values, label in (
            (self.training_member_ids, "training members"),
            (self.validation_member_ids, "validation members"),
            (self.holdout_member_ids, "holdout members"),
        ):
            if values != tuple(sorted(set(values))) or any(
                not value.startswith("imgsciviscampaigncrop_") or len(value) != 54
                for value in values
            ):
                raise ValueError(f"science campaign micro-probe {label} must be sorted and unique")
            member_sets.append(set(values))
        if any(member_sets[left] & member_sets[right] for left, right in ((0, 1), (0, 2), (1, 2))):
            raise ValueError("science campaign micro-probe member partitions overlap")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"probe_id", "plan_sha256"})
        ).removeprefix("sha256:")
        if self.probe_id != "imgscicampaignmicroprobe_" + identity[:32]:
            raise ValueError("science campaign micro-probe ID does not bind its plan inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("science campaign micro-probe plan hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroProbePlanV2(LocalImageScienceCampaignLoraMicroProbePlan):
    """Expanded 16/4/4 evaluation-only campaign plan."""

    crop_set_schema_ref: ClassVar[str] = CAMPAIGN_CROP_SET_V2_SCHEMA_REF

    # Pydantic successor models narrow immutable wire discriminators/constants.
    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-probe-plan/1.1"
    ]
    training_member_ids: tuple[str, ...] = Field(min_length=16, max_length=16)
    validation_member_ids: tuple[str, ...] = Field(min_length=4, max_length=4)
    holdout_member_ids: tuple[str, ...] = Field(min_length=4, max_length=4)
    trainer_contract: Literal[  # type: ignore[assignment]
        "eom-local-image-science-campaign-lora-micro-trainer/1.1"
    ]
    purpose: Literal[  # type: ignore[assignment]
        "EVALUATION_ONLY_SCIENCE_CAMPAIGN_EXPANDED_PROBE"
    ]


class LocalImageScienceCampaignLoraMicroProbeCommand(FrozenModel):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_SCHEMA_REF

    schema_version: Literal["local-image-science-campaign-lora-micro-probe-command/1.0"]
    training_run_id: str = Field(pattern=r"^imgscicampaignmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    probe_plan: LocalImageScienceCampaignLoraMicroProbePlan
    attempt: Literal[1]
    staged_plan_member: Literal["inputs/science-campaign-micro-probe-plan.json"]
    staged_crop_set_member: Literal["inputs/science-visual-campaign-crop-set.json"]
    staged_crops_root: Literal["inputs/crops"]
    runtime_dataset_root: Literal["runtime-dataset"]
    output_root_member: Literal["outputs"]
    checkpoint_root_member: Literal["checkpoints"]
    timeout_seconds: int = Field(ge=600, le=14_400)
    command_sha256: Sha256

    @property
    def training_plan(self) -> LocalImageScienceCampaignLoraMicroProbePlan:
        return self.probe_plan

    @property
    def training_plan_sha256(self) -> Sha256:
        return self.probe_plan_sha256

    @model_validator(mode="after")
    def immutable_command_is_coherent(self) -> LocalImageScienceCampaignLoraMicroProbeCommand:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=self.plan_schema_ref,
            member_path="manifests/science-campaign-micro-probe-plan.json",
        )
        if self.probe_plan_sha256 != self.probe_plan.plan_sha256:
            raise ValueError("science campaign micro-probe command plan hash mismatch")
        identity = content_sha256(
            {
                "probe_plan_pointer": self.probe_plan_pointer.model_dump(mode="json"),
                "probe_plan_sha256": self.probe_plan_sha256,
                "attempt": self.attempt,
            }
        ).removeprefix("sha256:")
        if self.training_run_id != "imgscicampaignmicrotrainrun_" + identity[:32]:
            raise ValueError("science campaign micro-probe run ID does not bind command inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("science campaign micro-probe command hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroProbeCommandV2(
    LocalImageScienceCampaignLoraMicroProbeCommand
):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_V2_SCHEMA_REF

    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-probe-command/1.1"
    ]
    probe_plan: LocalImageScienceCampaignLoraMicroProbePlanV2


class LocalImageScienceCampaignLoraMicroRealizedSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsciviscampaigncrop_[0-9a-f]{32}$")
    parent_candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    exam_group_sha256: Sha256
    training_sample_id: str = Field(pattern=r"^imgtrainsample_[0-9a-f]{32}$")
    source_crop_sha256: Sha256
    realized_crop_sha256: Sha256
    caption_sha256: Sha256
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")


class LocalImageScienceCampaignLoraMicroAdapterManifest(FrozenModel):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_SCHEMA_REF

    schema_version: Literal["local-image-science-campaign-lora-micro-adapter-manifest/1.0"]
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
    def immutable_adapter_is_coherent(
        self,
    ) -> LocalImageScienceCampaignLoraMicroAdapterManifest:
        _require_pointer(
            self.probe_plan,
            schema_ref=self.plan_schema_ref,
            member_path="manifests/science-campaign-micro-probe-plan.json",
        )
        if tuple(value.relative_path for value in self.files) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise ValueError("science campaign micro-probe adapter files must be exact and sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("science campaign micro-probe adapter manifest hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroAdapterManifestV2(
    LocalImageScienceCampaignLoraMicroAdapterManifest
):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_V2_SCHEMA_REF

    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-adapter-manifest/1.1"
    ]


class LocalImageScienceCampaignLoraMicroProbeWorkerResult(FrozenModel):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_SCHEMA_REF
    expected_realized_sample_count: ClassVar[int] = 12
    require_unique_exam_groups: ClassVar[bool] = True

    schema_version: Literal["local-image-science-campaign-lora-micro-probe-worker-result/1.0"]
    training_run_id: str = Field(pattern=r"^imgscicampaignmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    command_sha256: Sha256
    attempt: Literal[1]
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    adapter_manifest: LocalImageScienceCampaignLoraMicroAdapterManifest | None
    realized_samples: tuple[LocalImageScienceCampaignLoraMicroRealizedSample, ...] = Field(
        max_length=12
    )
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
    def terminal_result_is_coherent(
        self,
    ) -> LocalImageScienceCampaignLoraMicroProbeWorkerResult:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=self.plan_schema_ref,
            member_path="manifests/science-campaign-micro-probe-plan.json",
        )
        if self.completed_at < self.started_at:
            raise ValueError("science campaign micro-probe completion precedes start")
        if self.status == "SUCCEEDED":
            if (
                self.adapter_manifest is None
                or self.error_code is not None
                or self.runtime is None
                or self.sample_set_sha256 is None
                or self.completed_steps != 200
                or self.final_loss is None
                or len(self.realized_samples) != self.expected_realized_sample_count
            ):
                raise ValueError("successful science campaign micro-probe result is incomplete")
            sequences = [
                tuple(value.training_sample_id for value in self.realized_samples),
                tuple(value.sample_id for value in self.realized_samples),
                tuple(value.parent_candidate_id for value in self.realized_samples),
                tuple(value.source_crop_sha256 for value in self.realized_samples),
                tuple(value.realized_crop_sha256 for value in self.realized_samples),
            ]
            if self.require_unique_exam_groups:
                sequences.append(tuple(value.exam_group_sha256 for value in self.realized_samples))
            if sequences[0] != tuple(sorted(set(sequences[0]))) or any(
                len(values) != len(set(values)) for values in sequences[1:]
            ):
                raise ValueError("science campaign micro-probe realized samples are not unique")
            expected_set = content_sha256(
                [value.model_dump(mode="json") for value in self.realized_samples]
            )
            if (
                self.sample_set_sha256 != expected_set
                or self.adapter_manifest.sample_set_sha256 != self.sample_set_sha256
            ):
                raise ValueError("science campaign micro-probe sample set hash mismatch")
        elif self.adapter_manifest is not None or self.error_code is None:
            raise ValueError(
                "failed science campaign micro-probe result requires only an error code"
            )
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("science campaign micro-probe result hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroProbeWorkerResultV2(
    LocalImageScienceCampaignLoraMicroProbeWorkerResult
):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_V2_SCHEMA_REF
    expected_realized_sample_count: ClassVar[int] = 16
    require_unique_exam_groups: ClassVar[bool] = False

    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-probe-worker-result/1.1"
    ]
    adapter_manifest: LocalImageScienceCampaignLoraMicroAdapterManifestV2 | None
    realized_samples: tuple[LocalImageScienceCampaignLoraMicroRealizedSample, ...] = Field(
        max_length=16
    )


class LocalImageScienceCampaignLoraMicroEvaluationCase(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsciviscampaigncrop_[0-9a-f]{32}$")
    parent_candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    exam_group_sha256: Sha256
    positive_prompt: str = Field(min_length=1, max_length=4000)
    positive_prompt_sha256: Sha256
    negative_prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt_sha256: Sha256
    seed: int = Field(ge=0, le=2**32 - 1)

    @field_validator("positive_prompt", "negative_prompt")
    @classmethod
    def prompt_is_bounded_text(cls, value: str) -> str:
        if value != value.strip() or value != unicodedata.normalize("NFC", value):
            raise ValueError("science campaign evaluation prompt must be trimmed NFC text")
        if any(
            character not in {"\n", "\t"} and unicodedata.category(character).startswith("C")
            for character in value
        ):
            raise ValueError("science campaign evaluation prompt contains a control character")
        return value

    @model_validator(mode="after")
    def prompt_hashes_match(self) -> LocalImageScienceCampaignLoraMicroEvaluationCase:
        if self.positive_prompt_sha256 != text_sha256(
            self.positive_prompt
        ) or self.negative_prompt_sha256 != text_sha256(self.negative_prompt):
            raise ValueError("science campaign evaluation prompt hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroEvaluationCommand(FrozenModel):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_SCHEMA_REF
    crop_set_schema_ref: ClassVar[str] = CAMPAIGN_CROP_SET_SCHEMA_REF
    require_unique_source_groups: ClassVar[bool] = True

    schema_version: Literal["local-image-science-campaign-lora-micro-evaluation-command/1.0"]
    evaluation_run_id: str = Field(pattern=r"^imgscicampaignmicroevalrun_[0-9a-f]{32}$")
    training_run_id: str = Field(pattern=r"^imgscicampaignmicrotrainrun_[0-9a-f]{32}$")
    probe_plan_pointer: ImageEvaluationArtifactMember
    probe_plan_sha256: Sha256
    crop_set: ImageEvaluationArtifactMember
    crop_set_sha256: Sha256
    training_result_sha256: Sha256
    adapter_manifest: LocalImageScienceCampaignLoraMicroAdapterManifest
    cases: tuple[LocalImageScienceCampaignLoraMicroEvaluationCase, ...] = Field(
        min_length=2, max_length=2
    )
    inference_steps: Literal[20]
    guidance_scale: float = Field(ge=7.5, le=7.5)
    generation_width: Literal[800]
    generation_height: Literal[504]
    delivery_width: Literal[800]
    delivery_height: Literal[500]
    staged_adapter_root: Literal["inputs/adapter"]
    output_root_member: Literal["outputs"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    timeout_seconds: int = Field(ge=600, le=3600)
    command_sha256: Sha256

    @model_validator(mode="after")
    def immutable_command_is_coherent(
        self,
    ) -> LocalImageScienceCampaignLoraMicroEvaluationCommand:
        _require_pointer(
            self.probe_plan_pointer,
            schema_ref=self.plan_schema_ref,
            member_path="manifests/science-campaign-micro-probe-plan.json",
        )
        _require_pointer(
            self.crop_set,
            schema_ref=self.crop_set_schema_ref,
            member_path="manifests/science-visual-campaign-crop-set.json",
        )
        if (
            self.adapter_manifest.probe_plan != self.probe_plan_pointer
            or self.adapter_manifest.state != "EVALUATION_ONLY"
            or self.adapter_manifest.activation_policy != "FORBIDDEN"
        ):
            raise ValueError("science campaign evaluation adapter binding mismatch")
        sample_ids = tuple(value.sample_id for value in self.cases)
        unique_sequences = [tuple(value.parent_candidate_id for value in self.cases)]
        if self.require_unique_source_groups:
            unique_sequences.extend(
                (
                    tuple(value.document_id for value in self.cases),
                    tuple(value.exam_group_sha256 for value in self.cases),
                )
            )
        if sample_ids != tuple(sorted(set(sample_ids))) or any(
            len(values) != len(set(values)) for values in unique_sequences
        ):
            raise ValueError("science campaign evaluation cases must be sorted and unique")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"evaluation_run_id", "command_sha256"})
        ).removeprefix("sha256:")
        if self.evaluation_run_id != "imgscicampaignmicroevalrun_" + identity[:32]:
            raise ValueError("science campaign evaluation ID does not bind command inputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("science campaign evaluation command hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroEvaluationCommandV2(
    LocalImageScienceCampaignLoraMicroEvaluationCommand
):
    plan_schema_ref: ClassVar[str] = CAMPAIGN_MICRO_PLAN_V2_SCHEMA_REF
    crop_set_schema_ref: ClassVar[str] = CAMPAIGN_CROP_SET_V2_SCHEMA_REF
    require_unique_source_groups: ClassVar[bool] = False

    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-evaluation-command/1.1"
    ]
    adapter_manifest: LocalImageScienceCampaignLoraMicroAdapterManifestV2
    cases: tuple[LocalImageScienceCampaignLoraMicroEvaluationCase, ...] = Field(
        min_length=4,
        max_length=4,
    )


class LocalImageScienceCampaignLoraMicroEvaluationOutput(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsciviscampaigncrop_[0-9a-f]{32}$")
    variant: Literal["ADAPTER", "BASE"]
    member_path: str = Field(
        pattern=r"^outputs/imgsciviscampaigncrop_[0-9a-f]{32}-(adapter|base)\.png$"
    )
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=64 * 1024 * 1024)
    width_px: Literal[800]
    height_px: Literal[500]

    @model_validator(mode="after")
    def member_path_matches_identity(
        self,
    ) -> LocalImageScienceCampaignLoraMicroEvaluationOutput:
        if self.member_path != f"outputs/{self.sample_id}-{self.variant.lower()}.png":
            raise ValueError("science campaign evaluation output path mismatch")
        return self


class LocalImageScienceCampaignLoraMicroEvaluationResult(FrozenModel):
    expected_output_count: ClassVar[int] = 4

    schema_version: Literal["local-image-science-campaign-lora-micro-evaluation-result/1.0"]
    evaluation_run_id: str = Field(pattern=r"^imgscicampaignmicroevalrun_[0-9a-f]{32}$")
    command_sha256: Sha256
    training_result_sha256: Sha256
    adapter_manifest_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    outputs: tuple[LocalImageScienceCampaignLoraMicroEvaluationOutput, ...] = Field(max_length=4)
    error_code: str | None = Field(pattern=r"^IMAGE_EVALUATION_[A-Z0-9_]{3,96}$")
    started_at: datetime
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def terminal_result_is_coherent(
        self,
    ) -> LocalImageScienceCampaignLoraMicroEvaluationResult:
        if self.completed_at < self.started_at:
            raise ValueError("science campaign evaluation completion precedes start")
        keys = tuple((value.sample_id, value.variant) for value in self.outputs)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("science campaign evaluation outputs must be sorted and unique")
        if self.status == "SUCCEEDED":
            if len(self.outputs) != self.expected_output_count or self.error_code is not None:
                raise ValueError("successful science campaign evaluation is incomplete")
        elif self.error_code is None:
            raise ValueError("failed science campaign evaluation requires an error code")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("science campaign evaluation result hash mismatch")
        return self


class LocalImageScienceCampaignLoraMicroEvaluationResultV2(
    LocalImageScienceCampaignLoraMicroEvaluationResult
):
    expected_output_count: ClassVar[int] = 8

    schema_version: Literal[  # type: ignore[assignment]
        "local-image-science-campaign-lora-micro-evaluation-result/1.1"
    ]
    outputs: tuple[LocalImageScienceCampaignLoraMicroEvaluationOutput, ...] = Field(max_length=8)


def validate_science_campaign_micro_probe_plan_sources(
    plan: LocalImageScienceCampaignLoraMicroProbePlan,
    crop_set: LocalImageScienceVisualCampaignCropSet,
) -> None:
    if (
        plan.crop_set_sha256 != crop_set.crop_set_sha256
        or plan.crop_set.sha256 == plan.crop_set_sha256
    ):
        raise ValueError("science campaign micro-probe crop-set hash binding mismatch")
    members = {value.sample_id: value for value in crop_set.members}
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
            raise ValueError("science campaign micro-probe member partition binding mismatch")
    if set().union(*map(set, expected.values())) != set(members):
        raise ValueError("science campaign micro-probe does not account for every crop-set member")


def validate_science_campaign_micro_probe_worker_result(
    command: LocalImageScienceCampaignLoraMicroProbeCommand,
    result: LocalImageScienceCampaignLoraMicroProbeWorkerResult,
) -> None:
    if (
        result.training_run_id != command.training_run_id
        or result.probe_plan_pointer != command.probe_plan_pointer
        or result.probe_plan_sha256 != command.probe_plan_sha256
        or result.command_sha256 != command.command_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("science campaign micro-probe result does not bind the exact command")
    if result.status == "SUCCEEDED" and {
        value.sample_id for value in result.realized_samples
    } != set(command.probe_plan.training_member_ids):
        raise ValueError(
            "science campaign micro-probe realized samples differ from training members"
        )
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.probe_plan.base_model
        or result.adapter_manifest.probe_plan != command.probe_plan_pointer
    ):
        raise ValueError("science campaign micro-probe adapter does not bind the exact plan")


def validate_science_campaign_micro_evaluation_command(
    plan: LocalImageScienceCampaignLoraMicroProbePlan,
    crop_set: LocalImageScienceVisualCampaignCropSet,
    training_result: LocalImageScienceCampaignLoraMicroProbeWorkerResult,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand,
) -> None:
    if (
        command.training_run_id != training_result.training_run_id
        or command.probe_plan_pointer != training_result.probe_plan_pointer
        or command.probe_plan_sha256 != training_result.probe_plan_sha256
        or command.crop_set != plan.crop_set
        or command.crop_set_sha256 != plan.crop_set_sha256
        or command.training_result_sha256 != training_result.result_sha256
        or training_result.adapter_manifest is None
        or command.adapter_manifest != training_result.adapter_manifest
    ):
        raise ValueError("science campaign evaluation does not bind exact training inputs")
    members = {value.sample_id: value for value in crop_set.members}
    if {value.sample_id for value in command.cases} != set(plan.holdout_member_ids):
        raise ValueError("science campaign evaluation lacks exact holdout coverage")
    for case in command.cases:
        member = members.get(case.sample_id)
        if member is None or member.partition != "HOLDOUT":
            raise ValueError("science campaign evaluation case is not a holdout member")
        if (
            case.parent_candidate_id != member.parent_candidate_id
            or case.document_id != member.document_id
            or case.exam_group_sha256 != member.exam_group_sha256
            or case.positive_prompt != member.caption_en
            or case.positive_prompt_sha256 != member.caption_sha256
        ):
            raise ValueError("science campaign evaluation case binding mismatch")


def validate_science_campaign_micro_evaluation_result(
    command: LocalImageScienceCampaignLoraMicroEvaluationCommand,
    result: LocalImageScienceCampaignLoraMicroEvaluationResult,
) -> None:
    if (
        result.evaluation_run_id != command.evaluation_run_id
        or result.command_sha256 != command.command_sha256
        or result.training_result_sha256 != command.training_result_sha256
        or result.adapter_manifest_sha256 != command.adapter_manifest.manifest_sha256
    ):
        raise ValueError("science campaign evaluation result command binding mismatch")
    if result.status != "SUCCEEDED":
        return
    planned = {
        (case.sample_id, variant) for case in command.cases for variant in ("ADAPTER", "BASE")
    }
    actual = {(value.sample_id, value.variant) for value in result.outputs}
    if actual != planned:
        raise ValueError("science campaign evaluation result lacks exact paired coverage")


def validate_science_campaign_micro_probe_plan_sources_v2(
    plan: LocalImageScienceCampaignLoraMicroProbePlanV2,
    crop_set: LocalImageScienceVisualCampaignCropSetV2,
) -> None:
    """Bind every expanded plan member to the immutable V2 crop set in O(n)."""

    if (
        plan.crop_set_sha256 != crop_set.crop_set_sha256
        or plan.crop_set.sha256 == plan.crop_set_sha256
    ):
        raise ValueError("expanded science campaign probe crop-set hash binding mismatch")
    members = {value.sample_id: value for value in crop_set.members}
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
            raise ValueError("expanded science campaign probe member partition binding mismatch")
    if set().union(*map(set, expected.values())) != set(members):
        raise ValueError("expanded science campaign probe omits a crop-set member")


def validate_science_campaign_micro_probe_worker_result_v2(
    command: LocalImageScienceCampaignLoraMicroProbeCommandV2,
    result: LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
) -> None:
    if (
        result.training_run_id != command.training_run_id
        or result.probe_plan_pointer != command.probe_plan_pointer
        or result.probe_plan_sha256 != command.probe_plan_sha256
        or result.command_sha256 != command.command_sha256
        or result.attempt != command.attempt
    ):
        raise ValueError("expanded science campaign result does not bind the exact command")
    if result.status == "SUCCEEDED" and {
        value.sample_id for value in result.realized_samples
    } != set(command.probe_plan.training_member_ids):
        raise ValueError("expanded science campaign realized samples differ from training members")
    if result.adapter_manifest is not None and (
        result.adapter_manifest.base_model != command.probe_plan.base_model
        or result.adapter_manifest.probe_plan != command.probe_plan_pointer
    ):
        raise ValueError("expanded science campaign adapter does not bind the exact plan")


def validate_science_campaign_micro_evaluation_command_v2(
    plan: LocalImageScienceCampaignLoraMicroProbePlanV2,
    crop_set: LocalImageScienceVisualCampaignCropSetV2,
    training_result: LocalImageScienceCampaignLoraMicroProbeWorkerResultV2,
    command: LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
) -> None:
    if (
        command.training_run_id != training_result.training_run_id
        or command.probe_plan_pointer != training_result.probe_plan_pointer
        or command.probe_plan_sha256 != training_result.probe_plan_sha256
        or command.crop_set != plan.crop_set
        or command.crop_set_sha256 != plan.crop_set_sha256
        or command.training_result_sha256 != training_result.result_sha256
        or training_result.adapter_manifest is None
        or command.adapter_manifest != training_result.adapter_manifest
    ):
        raise ValueError("expanded science campaign evaluation inputs differ")
    members = {value.sample_id: value for value in crop_set.members}
    if {value.sample_id for value in command.cases} != set(plan.holdout_member_ids):
        raise ValueError("expanded science campaign evaluation lacks exact holdout coverage")
    for case in command.cases:
        member = members.get(case.sample_id)
        if member is None or member.partition != "HOLDOUT":
            raise ValueError("expanded science campaign evaluation case is not a holdout member")
        if (
            case.parent_candidate_id != member.parent_candidate_id
            or case.document_id != member.document_id
            or case.exam_group_sha256 != member.exam_group_sha256
            or case.positive_prompt != member.caption_en
            or case.positive_prompt_sha256 != member.caption_sha256
        ):
            raise ValueError("expanded science campaign evaluation case binding mismatch")


def validate_science_campaign_micro_evaluation_result_v2(
    command: LocalImageScienceCampaignLoraMicroEvaluationCommandV2,
    result: LocalImageScienceCampaignLoraMicroEvaluationResultV2,
) -> None:
    if (
        result.evaluation_run_id != command.evaluation_run_id
        or result.command_sha256 != command.command_sha256
        or result.training_result_sha256 != command.training_result_sha256
        or result.adapter_manifest_sha256 != command.adapter_manifest.manifest_sha256
    ):
        raise ValueError("expanded science campaign evaluation result binding mismatch")
    if result.status != "SUCCEEDED":
        return
    planned = {
        (case.sample_id, variant) for case in command.cases for variant in ("ADAPTER", "BASE")
    }
    actual = {(value.sample_id, value.variant) for value in result.outputs}
    if actual != planned:
        raise ValueError("expanded science campaign evaluation lacks exact paired coverage")
