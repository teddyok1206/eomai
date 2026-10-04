"""Reviewed CPU target derivatives; original TRAIN snapshots remain immutable."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Self, TypeVar

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    ImageEvaluationBoundingBox,
    Sha256,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_corpus_visual import (
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceObjectLineArtCropSet,
)
from eom_image_contracts.sdxl_lora_micro import (
    SDXL_LORA_MICRO_STYLE_TRIGGER,
    LocalImageSdxlLoraMicroCommand,
    LocalImageSdxlLoraMicroResult,
    SdxlLoraMicroSample,
    validate_sdxl_lora_micro_result,
    validate_sdxl_lora_micro_sources,
)

SDXL_TARGET_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-command/1.0"
)
SDXL_TARGET_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-result/1.0"
)
_PREFIX = "eom://schemas/image-provider/local-image-"
_SampleId = Annotated[str, Field(pattern=r"^imgscivislineartcrop_[0-9a-f]{32}$")]
_Document = TypeVar("_Document", bound=FrozenModel)
TargetExpression = Literal["CLEAN_CONTOUR", "RESTRAINED_TONE", "FINE_HATCHING"]
TargetErrorCode = Literal[
    "SDXL_TARGET_INPUT_INVALID",
    "SDXL_TARGET_SOURCE_INVALID",
    "SDXL_TARGET_RUNTIME_MISMATCH",
    "SDXL_TARGET_PREPARATION_FAILED",
    "SDXL_TARGET_OUTPUT_INVALID",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("SDXL target timestamp must be UTC")
    return value


class SdxlPrepareTargetDecision(FrozenModel):
    sample_id: _SampleId
    disposition: Literal["PREPARE"]
    framing_box: ImageEvaluationBoundingBox
    redaction_boxes: tuple[ImageEvaluationBoundingBox, ...] = Field(max_length=32)
    expression: TargetExpression

    @model_validator(mode="after")
    def exact_masks(self) -> Self:
        boxes = tuple((box.left, box.top, box.right, box.bottom) for box in self.redaction_boxes)
        if boxes != tuple(sorted(set(boxes))):
            raise ValueError("SDXL target masks must be uniquely sorted")
        frame = self.framing_box
        if any(
            not (
                frame.left <= box.left < box.right <= frame.right
                and frame.top <= box.top < box.bottom <= frame.bottom
            )
            for box in self.redaction_boxes
        ):
            raise ValueError("SDXL target mask must lie inside reviewed frame")
        return self


class SdxlDeferTargetDecision(FrozenModel):
    sample_id: _SampleId
    disposition: Literal["DEFER"]
    reason: Literal[
        "SOURCE_PART_MISSING",
        "MASK_INTERRUPTS_OBJECT",
        "DENSE_TEXTURE_SEPARATE_TRACK",
        "SCIENTIFIC_GEOMETRY_NATIVE",
    ]


SdxlTargetDecision = Annotated[
    SdxlPrepareTargetDecision | SdxlDeferTargetDecision, Field(discriminator="disposition")
]


class LocalImageSdxlTrainingTargetCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-command/1.0"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    original_training_command: ImageEvaluationArtifactMember
    original_training_result: ImageEvaluationArtifactMember
    decisions: tuple[SdxlTargetDecision, ...] = Field(min_length=16, max_length=16)
    policy: Literal["REVIEWED_GRAY_MASK_RATIONAL_FIT_768X512_MARGIN32/1.0"]
    maximum_upscale_milli: int = Field(ge=1000, le=4000)
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    purpose: Literal["CPU_ONLY_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_command(self) -> Self:
        for pointer, family in (
            (self.original_training_command, "sdxl-lora-micro-command"),
            (self.original_training_result, "sdxl-lora-micro-result"),
        ):
            if (
                pointer.member_path != "manifests/" + family + ".json"
                or pointer.schema_ref != _PREFIX + family + "/1.0"
                or pointer.media_type != "application/json"
            ):
                raise ValueError("SDXL target original pointer mismatch")
        ids = tuple(decision.sample_id for decision in self.decisions)
        if ids != tuple(sorted(set(ids))) or not any(
            decision.disposition == "PREPARE" for decision in self.decisions
        ):
            raise ValueError("SDXL target decisions must be unique, sorted and include preparation")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )
        if self.run_id != "imgsdxltargetpreprun_" + identity[7:39] or self.command_sha256 != (
            content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        ):
            raise ValueError("SDXL target command identity/hash mismatch")
        return self


class SdxlTargetPlacement(FrozenModel):
    source_pixel_box: tuple[int, int, int, int]
    resized_width_px: int = Field(ge=1, le=704)
    resized_height_px: int = Field(ge=1, le=448)
    offset_x_px: int = Field(ge=32, le=383)
    offset_y_px: int = Field(ge=32, le=255)

    @model_validator(mode="after")
    def exact_geometry(self) -> Self:
        left, top, right, bottom = self.source_pixel_box
        if not (0 <= left < right <= 4096 and 0 <= top < bottom <= 4096):
            raise ValueError("SDXL target source pixel box invalid")
        if (self.offset_x_px, self.offset_y_px) != (
            (768 - self.resized_width_px) // 2,
            (512 - self.resized_height_px) // 2,
        ):
            raise ValueError("SDXL target placement is not centered")
        return self


def sdxl_target_placement(
    sample: SdxlLoraMicroSample,
    decision: SdxlPrepareTargetDecision,
    *,
    maximum_upscale_milli: int,
) -> SdxlTargetPlacement:
    """Exact rational fit; no filesystem/image dependency or implicit foreground recropping."""
    if sample.sample_id != decision.sample_id or not 1000 <= maximum_upscale_milli <= 4000:
        raise ValueError("SDXL target placement source/scale invalid")
    return sdxl_reviewed_target_placement(
        width=sample.source_width_px,
        height=sample.source_height_px,
        framing_box=decision.framing_box,
        maximum_upscale_milli=maximum_upscale_milli,
    )


def sdxl_reviewed_target_placement(
    *,
    width: int,
    height: int,
    framing_box: ImageEvaluationBoundingBox,
    maximum_upscale_milli: int,
) -> SdxlTargetPlacement:
    """Shared fixed geometry; identity admission belongs to each released source protocol."""
    if not (1 <= width <= 4096 and 1 <= height <= 4096) or not (
        1000 <= maximum_upscale_milli <= 4000
    ):
        raise ValueError("SDXL target placement dimensions/scale invalid")
    frame = framing_box
    left, top = frame.left * width // 10_000, frame.top * height // 10_000
    right = (frame.right * width + 9_999) // 10_000
    bottom = (frame.bottom * height + 9_999) // 10_000
    crop_width, crop_height = right - left, bottom - top
    if crop_width < 16 or crop_height < 16:
        raise ValueError("SDXL target reviewed frame is too small")
    numerator, denominator = 704, crop_width
    for candidate_numerator, candidate_denominator in (
        (448, crop_height),
        (maximum_upscale_milli, 1000),
    ):
        if candidate_numerator * denominator < numerator * candidate_denominator:
            numerator, denominator = candidate_numerator, candidate_denominator
    resized_width = max(1, crop_width * numerator // denominator)
    resized_height = max(1, crop_height * numerator // denominator)
    return SdxlTargetPlacement(
        source_pixel_box=(left, top, right, bottom),
        resized_width_px=resized_width,
        resized_height_px=resized_height,
        offset_x_px=(768 - resized_width) // 2,
        offset_y_px=(512 - resized_height) // 2,
    )


def sdxl_target_caption(sample: SdxlLoraMicroSample, decision: SdxlPrepareTargetDecision) -> str:
    if sample.sample_id != decision.sample_id:
        raise ValueError("SDXL target caption source mismatch")
    return sdxl_reviewed_target_caption(sample.source_caption_en, decision.expression)


def sdxl_reviewed_target_caption(source_caption: str, target_expression: TargetExpression) -> str:
    expression: str
    match target_expression:
        case "CLEAN_CONTOUR":
            expression = "clean contour lines"
        case "RESTRAINED_TONE":
            expression = "contour lines with restrained gray tone"
        case "FINE_HATCHING":
            expression = "contour lines with fine hatching"
    return (
        SDXL_LORA_MICRO_STYLE_TRIGGER
        + source_caption
        + ", "
        + expression
        + ", plain white background"
    )


def sdxl_target_id(
    command: LocalImageSdxlTrainingTargetCommand,
    sample: SdxlLoraMicroSample,
    decision: SdxlPrepareTargetDecision,
) -> str:
    return (
        "imgsdxltarget_"
        + content_sha256(
            {
                "source": sample.model_dump(mode="json", exclude={"redaction_boxes"}),
                "decision": decision.model_dump(mode="json"),
                "policy": command.policy,
                "maximum_upscale_milli": command.maximum_upscale_milli,
            }
        )[7:39]
    )


class SdxlPreparedTrainingTarget(FrozenModel):
    sample_id: _SampleId
    target_id: str = Field(pattern=r"^imgsdxltarget_[0-9a-f]{32}$")
    target_revision_id: str = Field(pattern=r"^imgsdxltargetrev_[0-9a-f]{32}$")
    source_crop_sha256: Sha256
    member_path: str = Field(pattern=r"^targets/imgsdxltarget_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=8 * 1024**2)
    width_px: Literal[768]
    height_px: Literal[512]
    mode: Literal["RGB"]
    training_caption_en: str = Field(min_length=10, max_length=512, pattern=r"^[ -~]+$")
    training_caption_sha256: Sha256
    placement: SdxlTargetPlacement

    @model_validator(mode="after")
    def exact_output(self) -> Self:
        revision = content_sha256(
            {
                "target_id": self.target_id,
                "sha256": self.sha256,
                "training_caption_sha256": self.training_caption_sha256,
                "placement": self.placement.model_dump(mode="json"),
            }
        )[7:39]
        if (
            self.member_path != "targets/" + self.target_id + ".png"
            or self.target_revision_id != "imgsdxltargetrev_" + revision
            or self.training_caption_en != self.training_caption_en.strip()
            or text_sha256(self.training_caption_en) != self.training_caption_sha256
        ):
            raise ValueError("SDXL target revision/member/caption mismatch")
        return self


class LocalImageSdxlTrainingTargetResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-result/1.0"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    original_training_command_sha256: Sha256
    original_training_result_sha256: Sha256
    state: Literal["UNREVIEWED_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: TargetErrorCode | None
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    prepared_targets: tuple[SdxlPreparedTrainingTarget, ...] = Field(max_length=16)
    deferred_sample_ids: tuple[_SampleId, ...] = Field(max_length=15)
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
        deferred = self.deferred_sample_ids
        if (self.status == "SUCCEEDED") != (self.error_code is None) or (
            self.status == "SUCCEEDED" and not prepared
        ):
            raise ValueError("SDXL target status/error/coverage mismatch")
        if (
            prepared != tuple(sorted(set(prepared)))
            or deferred != tuple(sorted(set(deferred)))
            or set(prepared).intersection(deferred)
            or len({target.target_id for target in self.prepared_targets}) != len(prepared)
            or self.completed_at < self.started_at
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("SDXL target order/time/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlTrainingTargetSources:
    training_command: LocalImageSdxlLoraMicroCommand
    training_result: LocalImageSdxlLoraMicroResult
    crop_set: LocalImageScienceObjectLineArtCropSet
    authorization: LocalImageScienceCorpusTrainingAuthorization


# Python 3.11 is the isolated trainer runtime; PEP 695 would fail at import there.
def _source_document(  # noqa: UP047
    pointer: ImageEvaluationArtifactMember,
    raw: bytes,
    contract: str,
    model: type[_Document],
) -> _Document:
    from eom_image_contracts.validation import validate_contract

    if len(raw) > 2 * 1024**2 or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256:
        raise ValueError("SDXL target original source bytes mismatch")
    value = json.loads(raw)
    validate_contract(contract, value)
    document = model.model_validate(value)
    canonical = content_json_bytes(document.model_dump(mode="json"))
    if raw not in (canonical, canonical + b"\n"):
        raise ValueError("SDXL target original source is noncanonical")
    return document


def parse_sdxl_training_target_sources(
    command: LocalImageSdxlTrainingTargetCommand,
    *,
    training_command_payload: bytes,
    training_result_payload: bytes,
    crop_set_payload: bytes,
    authorization_payload: bytes,
) -> SdxlTrainingTargetSources:
    """One pure shared original-source admission for Orchestrator and worker boundaries."""
    original = _source_document(
        command.original_training_command,
        training_command_payload,
        "sdxl-lora-micro-command",
        LocalImageSdxlLoraMicroCommand,
    )
    result = _source_document(
        command.original_training_result,
        training_result_payload,
        "sdxl-lora-micro-result",
        LocalImageSdxlLoraMicroResult,
    )
    crop_set = _source_document(
        original.crop_set,
        crop_set_payload,
        "science-object-line-art-crop-set",
        LocalImageScienceObjectLineArtCropSet,
    )
    authorization = _source_document(
        original.training_authorization,
        authorization_payload,
        "science-corpus-training-authorization",
        LocalImageScienceCorpusTrainingAuthorization,
    )
    validate_sdxl_lora_micro_sources(original, crop_set)
    validate_sdxl_lora_micro_result(original, result)
    if result.status != "SUCCEEDED" or command.created_at < result.completed_at:
        raise ValueError("SDXL target predecessor is not a prior successful training run")
    if tuple(decision.sample_id for decision in command.decisions) != tuple(
        sample.sample_id for sample in original.training_samples
    ):
        raise ValueError("SDXL target decisions do not cover the exact original TRAIN snapshot")
    samples = {sample.sample_id: sample for sample in original.training_samples}
    for decision in command.decisions:
        if isinstance(decision, SdxlPrepareTargetDecision):
            sdxl_target_placement(
                samples[decision.sample_id],
                decision,
                maximum_upscale_milli=command.maximum_upscale_milli,
            )
    return SdxlTrainingTargetSources(original, result, crop_set, authorization)


def validate_sdxl_training_target_result(
    command: LocalImageSdxlTrainingTargetCommand,
    sources: SdxlTrainingTargetSources,
    result: LocalImageSdxlTrainingTargetResult,
) -> None:
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.original_training_command_sha256 != sources.training_command.command_sha256
        or result.original_training_result_sha256 != sources.training_result.result_sha256
        or result.started_at < command.created_at
    ):
        raise ValueError("SDXL target result differs from admitted command/source/runtime")
    if (result.pillow_version != command.pillow_version) != (
        result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH"
    ) or (result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH" and result.prepared_targets):
        raise ValueError("SDXL target actual Pillow drift must fail before transformation")
    decisions = tuple(
        decision
        for decision in command.decisions
        if isinstance(decision, SdxlPrepareTargetDecision)
    )
    expected = tuple(decision.sample_id for decision in decisions)
    observed = tuple(target.sample_id for target in result.prepared_targets)
    deferred = tuple(
        decision.sample_id
        for decision in command.decisions
        if isinstance(decision, SdxlDeferTargetDecision)
    )
    if result.deferred_sample_ids != deferred or observed != (
        expected if result.status == "SUCCEEDED" else expected[: len(observed)]
    ):
        raise ValueError("SDXL target result coverage is not the declared success/prefix")
    by_id = {sample.sample_id: sample for sample in sources.training_command.training_samples}
    by_decision = {decision.sample_id: decision for decision in decisions}
    for target in result.prepared_targets:
        sample, decision = by_id[target.sample_id], by_decision[target.sample_id]
        if (
            target.source_crop_sha256 != sample.source_image.sha256
            or target.target_id != sdxl_target_id(command, sample, decision)
            or target.training_caption_en != sdxl_target_caption(sample, decision)
            or target.placement
            != sdxl_target_placement(
                sample, decision, maximum_upscale_milli=command.maximum_upscale_milli
            )
        ):
            raise ValueError("SDXL target derivative differs from reviewed recipe")
