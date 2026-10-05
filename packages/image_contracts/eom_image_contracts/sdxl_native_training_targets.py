"""Explicit native source target geometry; frozen predecessors and source pixels stay intact."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.institutional_style_evaluation import INSTITUTIONAL_CROP_SCHEMA_REF
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    Sha256,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_corpus_visual import LocalImageScienceCorpusTrainingAuthorization
from eom_image_contracts.sdxl_source_training_targets import (
    SdxlSourcePrepareTargetDecision,
    SdxlSourceTargetSample,
)
from eom_image_contracts.sdxl_training_targets import (
    TargetErrorCode,
    _source_document,
    _utc,
    reviewed_target_geometry,
    sdxl_reviewed_target_caption,
)
from eom_image_contracts.source_page_crops import (
    SourcePageCropReview,
    parse_source_page_crop_review,
)
from eom_image_contracts.source_pdf_crops import (
    SOURCE_PDF_CROP_COMMAND_SCHEMA_REF,
    SOURCE_PDF_CROP_SET_SCHEMA_REF,
    LocalImageScienceSourcePdfCropCommand,
    LocalImageScienceSourcePdfCropSet,
    select_native_source_pdf_regions,
    validate_native_source_pdf_crop_set,
)
from eom_image_contracts.validation import validate_contract

SDXL_NATIVE_TARGET_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-command/1.2"
)
SDXL_NATIVE_TARGET_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-result/1.2"
)
SDXL_NATIVE_TARGET_PNG_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-png/1.1"
)
NativeTargetCanvas = Literal["SQUARE_1024", "PORTRAIT_768X1024", "LANDSCAPE_1024X768"]
NATIVE_TARGET_CANVASES: Mapping[NativeTargetCanvas, tuple[int, int]] = MappingProxyType(
    {
        "SQUARE_1024": (1024, 1024),
        "PORTRAIT_768X1024": (768, 1024),
        "LANDSCAPE_1024X768": (1024, 768),
    }
)
_SampleId = Annotated[str, Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")]


class SdxlNativePrepareTargetDecision(SdxlSourcePrepareTargetDecision):
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...] = Field(max_length=0)
    canvas: NativeTargetCanvas
    reviewed_caption_en: str = Field(min_length=10, max_length=256, pattern=r"^[ -~]+$")

    @field_validator("reviewed_caption_en")
    @classmethod
    def literal_caption(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("native target reviewed caption is not canonical")
        return value


class SdxlNativeDeferTargetDecision(FrozenModel):
    sample_id: _SampleId
    disposition: Literal["DEFER"]
    reason: Literal[
        "SOURCE_PART_MISSING",
        "MASK_INTERRUPTS_OBJECT",
        "DENSE_TEXTURE_SEPARATE_TRACK",
        "SCIENTIFIC_GEOMETRY_NATIVE",
        "SOURCE_ANNOTATION_REQUIRES_REPAIR",
        "REFERENCE_ONLY",
        "SOURCE_RESOLUTION_LIMITED",
        "CAPTION_UNCERTAIN",
        "MARGIN_REVIEW_NEEDED",
    ]


SdxlNativeTargetDecision = Annotated[
    SdxlNativePrepareTargetDecision | SdxlNativeDeferTargetDecision,
    Field(discriminator="disposition"),
]


class LocalImageSdxlNativeTrainingTargetCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-command/1.2"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_crop_set: ImageEvaluationArtifactMember
    training_authorization: ImageEvaluationArtifactMember
    decisions: tuple[SdxlNativeTargetDecision, ...] = Field(min_length=1, max_length=32)
    policy: Literal["REVIEWED_NATIVE_GRAY_RATIONAL_FIT_MARGIN32_NO_MASK/1.0"]
    maximum_upscale_milli: int = Field(ge=1000, le=2000)
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    purpose: Literal["CPU_ONLY_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        if (
            self.source_crop_set.schema_ref != SOURCE_PDF_CROP_SET_SCHEMA_REF
            or self.source_crop_set.media_type != "application/json"
            or self.source_crop_set.member_path != "manifests/science-source-pdf-crop-set.json"
            or self.training_authorization.schema_ref
            != "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
            or self.training_authorization.media_type != "application/json"
            or self.training_authorization.member_path
            != "manifests/science-corpus-training-authorization.json"
        ):
            raise ValueError("SDXL_NATIVE_TARGET_POINTER_INVALID")
        ids = tuple(decision.sample_id for decision in self.decisions)
        if ids != tuple(sorted(set(ids))) or not any(
            d.disposition == "PREPARE" for d in self.decisions
        ):
            raise ValueError("SDXL_NATIVE_TARGET_DECISIONS_INVALID")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )
        if self.run_id != "imgsdxltargetpreprun_" + identity[
            7:39
        ] or self.command_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"command_sha256"})
        ):
            raise ValueError("SDXL_NATIVE_TARGET_COMMAND_IDENTITY_INVALID")
        return self


class SdxlNativeTargetPlacement(FrozenModel):
    source_pixel_box: tuple[int, int, int, int]
    resized_width_px: int = Field(ge=1, le=960)
    resized_height_px: int = Field(ge=1, le=960)
    offset_x_px: int = Field(ge=32, le=511)
    offset_y_px: int = Field(ge=32, le=511)
    canvas: NativeTargetCanvas

    @model_validator(mode="after")
    def exact_geometry(self) -> Self:
        left, top, right, bottom = self.source_pixel_box
        width, height = NATIVE_TARGET_CANVASES[self.canvas]
        if not (0 <= left < right <= 4096 and 0 <= top < bottom <= 4096) or (
            self.resized_width_px > width - 64
            or self.resized_height_px > height - 64
            or (self.offset_x_px, self.offset_y_px)
            != ((width - self.resized_width_px) // 2, (height - self.resized_height_px) // 2)
        ):
            raise ValueError("SDXL_NATIVE_TARGET_PLACEMENT_INVALID")
        return self


class SdxlPreparedNativeTrainingTarget(FrozenModel):
    sample_id: _SampleId
    target_id: str = Field(pattern=r"^imgsdxltarget_[0-9a-f]{32}$")
    target_revision_id: str = Field(pattern=r"^imgsdxltargetrev_[0-9a-f]{32}$")
    source_crop_sha256: Sha256
    member_path: str = Field(pattern=r"^targets/imgsdxltarget_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=8 * 1024**2)
    width_px: Literal[768, 1024]
    height_px: Literal[768, 1024]
    mode: Literal["RGB"]
    training_caption_en: str = Field(min_length=10, max_length=512, pattern=r"^[ -~]+$")
    training_caption_sha256: Sha256
    placement: SdxlNativeTargetPlacement

    @model_validator(mode="after")
    def exact_output(self) -> Self:
        revision = content_sha256(
            {
                "target_id": self.target_id,
                "sha256": self.sha256,
                "training_caption_sha256": self.training_caption_sha256,
                "placement": self.placement.model_dump(mode="json"),
            }
        )
        if (
            self.member_path != "targets/" + self.target_id + ".png"
            or self.target_revision_id != "imgsdxltargetrev_" + revision[7:39]
            or (self.width_px, self.height_px) != NATIVE_TARGET_CANVASES[self.placement.canvas]
            or self.training_caption_en != self.training_caption_en.strip()
            or text_sha256(self.training_caption_en) != self.training_caption_sha256
        ):
            raise ValueError("SDXL_NATIVE_TARGET_OUTPUT_IDENTITY_INVALID")
        return self


class LocalImageSdxlNativeTrainingTargetResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-result/1.2"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    source_snapshot_sha256: Sha256
    state: Literal["UNREVIEWED_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: TargetErrorCode | None
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    prepared_targets: tuple[SdxlPreparedNativeTrainingTarget, ...] = Field(max_length=32)
    deferred_sample_ids: tuple[_SampleId, ...] = Field(max_length=31)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        prepared = tuple(target.sample_id for target in self.prepared_targets)
        if (
            (self.status == "SUCCEEDED") != (self.error_code is None)
            or (self.status == "SUCCEEDED" and not prepared)
            or prepared != tuple(sorted(set(prepared)))
            or self.deferred_sample_ids != tuple(sorted(set(self.deferred_sample_ids)))
            or set(prepared).intersection(self.deferred_sample_ids)
            or len({t.target_id for t in self.prepared_targets}) != len(prepared)
            or len({t.sha256 for t in self.prepared_targets}) != len(prepared)
            or self.completed_at < self.started_at
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("SDXL_NATIVE_TARGET_RESULT_INVALID")
        return self


@dataclass(frozen=True, slots=True)
class SdxlNativeTrainingTargetSources:
    crop_set: LocalImageScienceSourcePdfCropSet
    source_command: LocalImageScienceSourcePdfCropCommand
    review: SourcePageCropReview
    authorization: LocalImageScienceCorpusTrainingAuthorization
    samples: tuple[SdxlSourceTargetSample, ...]
    snapshot_sha256: str


def parse_sdxl_native_training_target_sources(
    command: LocalImageSdxlNativeTrainingTargetCommand,
    *,
    crop_set_payload: bytes,
    source_command_payload: bytes,
    review_payload: bytes,
    authorization_payload: bytes,
) -> SdxlNativeTrainingTargetSources:
    crop_set = _source_document(
        command.source_crop_set,
        crop_set_payload,
        "science-source-pdf-crop-set",
        LocalImageScienceSourcePdfCropSet,
    )
    source_command = _source_document(
        crop_set.command,
        source_command_payload,
        "science-source-pdf-crop-command",
        LocalImageScienceSourcePdfCropCommand,
    )
    if crop_set_payload != content_json_bytes(crop_set.model_dump(mode="json")) or (
        source_command_payload != content_json_bytes(source_command.model_dump(mode="json"))
    ):
        raise ValueError("SDXL_NATIVE_TARGET_SOURCE_NONCANONICAL")
    if crop_set.command.schema_ref != SOURCE_PDF_CROP_COMMAND_SCHEMA_REF:
        raise ValueError("SDXL_NATIVE_TARGET_SOURCE_COMMAND_INVALID")
    review = parse_source_page_crop_review(source_command.source_review, review_payload)
    authorization = _source_document(
        command.training_authorization,
        authorization_payload,
        "science-corpus-training-authorization",
        LocalImageScienceCorpusTrainingAuthorization,
    )
    return validate_sdxl_native_training_target_sources(
        command,
        crop_set=crop_set,
        source_command=source_command,
        review=review,
        authorization=authorization,
    )


def validate_sdxl_native_training_target_sources(
    command: LocalImageSdxlNativeTrainingTargetCommand,
    *,
    crop_set: LocalImageScienceSourcePdfCropSet,
    source_command: LocalImageScienceSourcePdfCropCommand,
    review: SourcePageCropReview,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
) -> SdxlNativeTrainingTargetSources:
    """Share already decoded immutable metadata at a new admission boundary."""
    validate_native_source_pdf_crop_set(
        source_command, review, crop_set, command_pointer=crop_set.command
    )
    selections = select_native_source_pdf_regions(source_command, review)
    samples = tuple(
        SdxlSourceTargetSample(
            selection.selection_id,
            ImageEvaluationArtifactMember(
                artifact_id=command.source_crop_set.artifact_id,
                artifact_revision_id=command.source_crop_set.artifact_revision_id,
                member_path=member.member_path,
                schema_ref=INSTITUTIONAL_CROP_SCHEMA_REF,
                media_type="image/png",
                sha256=member.sha256,
            ),
            member.width_px,
            member.height_px,
            selection.caption_en,
            member.size_bytes,
        )
        for selection, member in zip(selections, crop_set.members, strict=True)
    )
    sources = SdxlNativeTrainingTargetSources(
        crop_set,
        source_command,
        review,
        authorization,
        samples,
        content_sha256(
            {
                "source_crop_set": command.source_crop_set.model_dump(mode="json"),
                "source_crop_command": crop_set.command.model_dump(mode="json"),
                "source_review": source_command.source_review.model_dump(mode="json"),
                "training_authorization": command.training_authorization.model_dump(mode="json"),
            }
        ),
    )
    validate_sdxl_native_training_target_command_sources(command, sources)
    return sources


def validate_sdxl_native_training_target_command_sources(
    command: LocalImageSdxlNativeTrainingTargetCommand,
    sources: SdxlNativeTrainingTargetSources,
) -> None:
    """Check a batch recipe against a decoded, previously validated source snapshot."""
    if (
        sources.review.training_authorization != command.training_authorization
        or sources.authorization.approved_at > sources.review.created_at
        or sources.crop_set.created_at > command.created_at
        or sources.source_command.pillow_version != command.pillow_version
        or tuple(d.sample_id for d in command.decisions)
        != tuple(m.selection_id for m in sources.crop_set.members)
        or any(
            (sample.source_image.artifact_id, sample.source_image.artifact_revision_id)
            != (command.source_crop_set.artifact_id, command.source_crop_set.artifact_revision_id)
            for sample in sources.samples
        )
    ):
        raise ValueError("SDXL_NATIVE_TARGET_SOURCE_SCOPE_INVALID")
    by_id = {sample.sample_id: sample for sample in sources.samples}
    for decision in command.decisions:
        if isinstance(decision, SdxlNativePrepareTargetDecision):
            sdxl_native_target_placement(
                by_id[decision.sample_id],
                decision,
                maximum_upscale_milli=command.maximum_upscale_milli,
            )


def sdxl_native_target_placement(
    sample: SdxlSourceTargetSample,
    decision: SdxlNativePrepareTargetDecision,
    *,
    maximum_upscale_milli: int,
) -> SdxlNativeTargetPlacement:
    if sample.sample_id != decision.sample_id or not 1000 <= maximum_upscale_milli <= 2000:
        raise ValueError("SDXL_NATIVE_TARGET_SAMPLE_INVALID")
    fit = reviewed_target_geometry(
        width=sample.source_width_px,
        height=sample.source_height_px,
        framing_box=decision.framing_box,
        maximum_upscale_milli=maximum_upscale_milli,
        canvas_size=NATIVE_TARGET_CANVASES[decision.canvas],
    )
    return SdxlNativeTargetPlacement(
        source_pixel_box=fit.source_pixel_box,
        resized_width_px=fit.resized_width_px,
        resized_height_px=fit.resized_height_px,
        offset_x_px=fit.offset_x_px,
        offset_y_px=fit.offset_y_px,
        canvas=decision.canvas,
    )


def sdxl_native_target_id(
    command: LocalImageSdxlNativeTrainingTargetCommand,
    sample: SdxlSourceTargetSample,
    decision: SdxlNativePrepareTargetDecision,
) -> str:
    if sample.sample_id != decision.sample_id:
        raise ValueError("SDXL_NATIVE_TARGET_SAMPLE_INVALID")
    return (
        "imgsdxltarget_"
        + content_sha256(
            {
                "source_selection_id": sample.sample_id,
                "decision": decision.model_dump(mode="json"),
                "policy": command.policy,
                "maximum_upscale_milli": command.maximum_upscale_milli,
            }
        )[7:39]
    )


def validate_sdxl_native_training_target_result(
    command: LocalImageSdxlNativeTrainingTargetCommand,
    sources: SdxlNativeTrainingTargetSources,
    result: LocalImageSdxlNativeTrainingTargetResult,
) -> None:
    validate_contract("sdxl-training-target-result-v3", result.model_dump(mode="json"))
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.source_snapshot_sha256 != sources.snapshot_sha256
        or result.started_at < command.created_at
        or (result.pillow_version != command.pillow_version)
        != (result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH")
        or (result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH" and result.prepared_targets)
    ):
        raise ValueError("SDXL_NATIVE_TARGET_RESULT_SOURCE_INVALID")
    decisions = {
        d.sample_id: d for d in command.decisions if isinstance(d, SdxlNativePrepareTargetDecision)
    }
    samples = {sample.sample_id: sample for sample in sources.samples}
    expected = tuple(decisions)
    observed = tuple(target.sample_id for target in result.prepared_targets)
    if result.deferred_sample_ids != tuple(
        d.sample_id for d in command.decisions if d.disposition == "DEFER"
    ) or (observed != (expected if result.status == "SUCCEEDED" else expected[: len(observed)])):
        raise ValueError("SDXL_NATIVE_TARGET_RESULT_COVERAGE_INVALID")
    for target in result.prepared_targets:
        sample, decision = samples[target.sample_id], decisions[target.sample_id]
        if (
            target.source_crop_sha256 != sample.source_image.sha256
            or target.target_id != sdxl_native_target_id(command, sample, decision)
            or target.training_caption_en
            != sdxl_reviewed_target_caption(decision.reviewed_caption_en, decision.expression)
            or target.placement
            != sdxl_native_target_placement(
                sample, decision, maximum_upscale_milli=command.maximum_upscale_milli
            )
        ):
            raise ValueError("SDXL_NATIVE_TARGET_RESULT_RECIPE_INVALID")
