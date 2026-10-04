"""Evaluation-only SDXL successor using exact, reviewed literal-source target PNGs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.micro_training import LocalImageLoraMicroHyperparameters
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
from eom_image_contracts.sdxl_lora_micro import (
    LocalImageSdxlLoraMicroResult,
    SdxlLoraMicroBudget,
    SdxlLoraMicroRealizedSample,
    _utc,
)
from eom_image_contracts.sdxl_source_training_targets import (
    SDXL_SOURCE_TARGET_COMMAND_SCHEMA_REF,
    SDXL_SOURCE_TARGET_RESULT_SCHEMA_REF,
    LocalImageSdxlSourceTrainingTargetCommand,
    LocalImageSdxlSourceTrainingTargetResult,
    SdxlPreparedSourceTrainingTarget,
    parse_sdxl_source_training_target_sources,
    validate_sdxl_source_training_target_result,
)
from eom_image_contracts.sdxl_training_targets import _source_document
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_SET_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
)
from eom_image_contracts.training import LocalImageTrainerDependencies

SDXL_REVIEWED_MICRO_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-lora-micro-command/1.1"
)
SDXL_REVIEWED_MICRO_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-lora-micro-result/1.1"
)
_TARGET_PNG_REF = "eom://schemas/image-provider/local-image-sdxl-training-target-png/1.0"
_AUTH_REF = "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"


class SdxlTargetBatchPin(FrozenModel):
    command: ImageEvaluationArtifactMember
    result: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_metadata(self) -> Self:
        for pointer, member, schema in (
            (self.command, "sdxl-training-target-command", SDXL_SOURCE_TARGET_COMMAND_SCHEMA_REF),
            (self.result, "sdxl-training-target-result", SDXL_SOURCE_TARGET_RESULT_SCHEMA_REF),
        ):
            if pointer.member_path != "manifests/" + member + ".json" or (
                pointer.schema_ref != schema or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL reviewed batch pointer contract mismatch")
        return self


class SdxlReviewedMicroSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    target_id: str = Field(pattern=r"^imgsdxltarget_[0-9a-f]{32}$")
    target_revision_id: str = Field(pattern=r"^imgsdxltargetrev_[0-9a-f]{32}$")
    source_image: ImageEvaluationArtifactMember
    training_caption_en: str = Field(min_length=10, max_length=640, pattern=r"^[ -~]+$")
    training_caption_sha256: Sha256

    @model_validator(mode="after")
    def exact_target_member(self) -> Self:
        if (
            self.source_image.member_path != "targets/" + self.target_id + ".png"
            or self.source_image.schema_ref != _TARGET_PNG_REF
            or self.source_image.media_type != "image/png"
            or self.training_caption_sha256 != text_sha256(self.training_caption_en)
        ):
            raise ValueError("SDXL reviewed target pointer/caption mismatch")
        return self

    @property
    def staged_member_path(self) -> str:
        return "inputs/targets/" + self.sample_id + ".png"


class LocalImageSdxlReviewedMicroCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-lora-micro-command/1.1"]
    training_run_id: str = Field(pattern=r"^imgsdxlmicrotrainrun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    base_model: SdxlLineartStackPointer
    source_crop_set: ImageEvaluationArtifactMember
    training_authorization: ImageEvaluationArtifactMember
    experiment_authorization: SdxlExperimentAuthorization
    target_batches: tuple[SdxlTargetBatchPin, ...] = Field(min_length=1, max_length=8)
    training_samples: tuple[SdxlReviewedMicroSample, ...] = Field(min_length=1, max_length=96)
    review_scope: Literal["OWN_TRAIN_TARGET_SCREENING_NOT_INDEPENDENT"]
    caption_policy: Literal["EXACT_REVIEWED_TARGET_CAPTION/1.0"]
    preprocessing_policy: Literal["EXACT_PREPARED_RGB_768X512/1.0"]
    dependencies: LocalImageTrainerDependencies
    hyperparameters: LocalImageLoraMicroHyperparameters
    budget: SdxlLoraMicroBudget
    seed: int = Field(ge=0, le=4_294_967_295)
    purpose: Literal["EVALUATION_ONLY_SDXL_REVIEWED_LITERAL_TARGET_MICRO"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def frozen_dataset(self) -> Self:
        if (
            self.source_crop_set.schema_ref
            not in {SOURCE_PAGE_CROP_SET_SCHEMA_REF, SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF}
            or self.source_crop_set.member_path != "manifests/science-source-page-crop-set.json"
            or self.source_crop_set.media_type != "application/json"
            or self.training_authorization.schema_ref != _AUTH_REF
            or self.training_authorization.member_path
            != "manifests/science-corpus-training-authorization.json"
            or self.training_authorization.media_type != "application/json"
        ):
            raise ValueError("SDXL reviewed source pointer contract mismatch")
        if "INTERNAL_SDXL_LORA_TRAINING" not in self.experiment_authorization.permitted_uses or (
            self.created_at < self.experiment_authorization.approved_at
        ):
            raise ValueError("SDXL reviewed training requires prior explicit SDXL approval")
        batches = tuple(
            (pin.result.artifact_id, pin.result.artifact_revision_id) for pin in self.target_batches
        )
        ids = tuple(sample.sample_id for sample in self.training_samples)
        if batches != tuple(sorted(set(batches))) or ids != tuple(sorted(set(ids))):
            raise ValueError("SDXL reviewed batches/sources must be uniquely sorted")
        if len({sample.target_id for sample in self.training_samples}) != len(ids) or len(
            {sample.source_image.sha256 for sample in self.training_samples}
        ) != len(ids):
            raise ValueError("SDXL reviewed dataset contains duplicate targets/pixels")
        batch_ids = set(batches)
        if any(
            (sample.source_image.artifact_id, sample.source_image.artifact_revision_id)
            not in batch_ids
            for sample in self.training_samples
        ):
            raise ValueError("SDXL reviewed target does not bind a pinned batch revision")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"training_run_id", "command_sha256"})
        )
        if self.training_run_id != "imgsdxlmicrotrainrun_" + identity[7:39] or (
            self.command_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        ):
            raise ValueError("SDXL reviewed command immutable identity/hash mismatch")
        return self


class SdxlReviewedMicroRealizedSample(SdxlLoraMicroRealizedSample):
    sample_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")


class LocalImageSdxlReviewedMicroResult(LocalImageSdxlLoraMicroResult):
    schema_version: Literal["local-image-sdxl-lora-micro-result/1.1"]  # type: ignore[assignment]
    realized_samples: tuple[SdxlReviewedMicroRealizedSample, ...] = Field(max_length=96)

    def complete_sample_count_valid(self) -> bool:
        return bool(self.realized_samples)


def sdxl_reviewed_micro_metadata_pointers(
    command: LocalImageSdxlReviewedMicroCommand,
    crop_set_payload: bytes,
) -> dict[str, ImageEvaluationArtifactMember]:
    supplemental = command.source_crop_set.schema_ref == SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF
    crop_set = _source_document(
        command.source_crop_set,
        crop_set_payload,
        "science-source-page-crop-set-v2" if supplemental else "science-source-page-crop-set",
        LocalImageScienceSourcePageCropSetV2
        if supplemental
        else LocalImageScienceSourcePageCropSet,
    )
    return {
        "inputs/source-crop-set.json": command.source_crop_set,
        "inputs/source-review.json": crop_set.review,
        "inputs/authorization.json": command.training_authorization,
        **{
            f"inputs/target-batches/{index}/{name}.json": pointer
            for index, pin in enumerate(command.target_batches)
            for name, pointer in (("command", pin.command), ("result", pin.result))
        },
    }


def parse_sdxl_reviewed_micro_sources(
    command: LocalImageSdxlReviewedMicroCommand,
    metadata: Mapping[str, bytes],
) -> dict[str, SdxlPreparedSourceTrainingTarget]:
    """Validate one common frozen source snapshot and every selected derivative before pixels."""
    prepared_by_member = {}
    selected = {}
    used_batches: set[tuple[str, str]] = set()
    common_sources = None
    for index, pin in enumerate(command.target_batches):
        target_command = _source_document(
            pin.command,
            metadata[f"inputs/target-batches/{index}/command.json"],
            "sdxl-training-target-command-v2",
            LocalImageSdxlSourceTrainingTargetCommand,
        )
        target_result = _source_document(
            pin.result,
            metadata[f"inputs/target-batches/{index}/result.json"],
            "sdxl-training-target-result-v2",
            LocalImageSdxlSourceTrainingTargetResult,
        )
        if target_command.source_crop_set != command.source_crop_set or (
            target_command.training_authorization != command.training_authorization
            or target_result.status != "SUCCEEDED"
            or target_result.completed_at > command.created_at
        ):
            raise ValueError("SDXL reviewed target batch source/status/chronology mismatch")
        if common_sources is None:
            common_sources = parse_sdxl_source_training_target_sources(
                target_command,
                crop_set_payload=metadata["inputs/source-crop-set.json"],
                review_payload=metadata["inputs/source-review.json"],
                authorization_payload=metadata["inputs/authorization.json"],
            )
        else:
            # Each batch must cover the same immutable TRAIN source set, including DEFERs.
            if tuple(decision.sample_id for decision in target_command.decisions) != tuple(
                sample.sample_id for sample in common_sources.samples
            ):
                raise ValueError("SDXL reviewed batch source coverage mismatch")
            if common_sources.crop_set.created_at > target_command.created_at:
                raise ValueError("SDXL reviewed batch precedes frozen source publication")
        validate_sdxl_source_training_target_result(target_command, common_sources, target_result)
        for target in target_result.prepared_targets:
            key = (pin.result.artifact_id, pin.result.artifact_revision_id, target.sample_id)
            prepared_by_member[key] = target
    for sample in command.training_samples:
        identity = (sample.source_image.artifact_id, sample.source_image.artifact_revision_id)
        selected_target = prepared_by_member.get((*identity, sample.sample_id))
        if selected_target is None or (
            selected_target.target_id != sample.target_id
            or selected_target.target_revision_id != sample.target_revision_id
            or selected_target.sha256 != sample.source_image.sha256
            or selected_target.training_caption_en != sample.training_caption_en
            or selected_target.training_caption_sha256 != sample.training_caption_sha256
        ):
            raise ValueError(
                "SDXL reviewed selected target identity/revision/caption/hash mismatch"
            )
        used_batches.add(identity)
        selected[sample.sample_id] = selected_target
    if used_batches != {
        (pin.result.artifact_id, pin.result.artifact_revision_id) for pin in command.target_batches
    }:
        raise ValueError("SDXL reviewed batch is not used by the frozen dataset")
    return selected
