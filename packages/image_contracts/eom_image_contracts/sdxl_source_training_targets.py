"""Successor CPU targets from registered literal TRAIN crops, never old micro identities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
)
from eom_image_contracts.science_corpus_visual import LocalImageScienceCorpusTrainingAuthorization
from eom_image_contracts.sdxl_training_targets import (
    SdxlPreparedTrainingTarget,
    SdxlPrepareTargetDecision,
    SdxlTargetPlacement,
    TargetErrorCode,
    _source_document,
    sdxl_reviewed_target_caption,
    sdxl_reviewed_target_placement,
)
from eom_image_contracts.source_page_crops import (
    SOURCE_PAGE_CROP_SET_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
    source_page_crop_pointer,
    source_page_crop_protocol,
    validate_source_page_crop_set,
)

_SampleId = Annotated[str, Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")]
_AUTH_REF = "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0"
SDXL_SOURCE_TARGET_COMMAND_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-command/1.1"
)
SDXL_SOURCE_TARGET_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-sdxl-training-target-result/1.1"
)


class SdxlSourcePrepareTargetDecision(SdxlPrepareTargetDecision):
    sample_id: _SampleId


class SdxlSourceDeferTargetDecision(FrozenModel):
    sample_id: _SampleId
    disposition: Literal["DEFER"]
    reason: Literal[
        "SOURCE_PART_MISSING",
        "MASK_INTERRUPTS_OBJECT",
        "DENSE_TEXTURE_SEPARATE_TRACK",
        "SCIENTIFIC_GEOMETRY_NATIVE",
        "SOURCE_ANNOTATION_REQUIRES_REPAIR",
        "REFERENCE_ONLY",
    ]


SdxlSourceTargetDecision = Annotated[
    SdxlSourcePrepareTargetDecision | SdxlSourceDeferTargetDecision,
    Field(discriminator="disposition"),
]


class LocalImageSdxlSourceTrainingTargetCommand(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-command/1.1"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_crop_set: ImageEvaluationArtifactMember
    training_authorization: ImageEvaluationArtifactMember
    decisions: tuple[SdxlSourceTargetDecision, ...] = Field(min_length=1, max_length=512)
    policy: Literal["REVIEWED_GRAY_MASK_RATIONAL_FIT_768X512_MARGIN32/1.0"]
    maximum_upscale_milli: int = Field(ge=1000, le=4000)
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    purpose: Literal["CPU_ONLY_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    command_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("SDXL source target timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_command(self) -> Self:
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
            raise ValueError("SDXL source target pointer contract mismatch")
        ids = tuple(decision.sample_id for decision in self.decisions)
        if ids != tuple(sorted(set(ids))) or not any(
            decision.disposition == "PREPARE" for decision in self.decisions
        ):
            raise ValueError(
                "SDXL source target decisions must be unique, sorted and include preparation"
            )
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"run_id", "command_sha256"})
        )
        if self.run_id != "imgsdxltargetpreprun_" + identity[7:39] or self.command_sha256 != (
            content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        ):
            raise ValueError("SDXL source target command identity/hash mismatch")
        return self


class SdxlPreparedSourceTrainingTarget(SdxlPreparedTrainingTarget):
    sample_id: _SampleId


class LocalImageSdxlSourceTrainingTargetResult(FrozenModel):
    schema_version: Literal["local-image-sdxl-training-target-result/1.1"]
    run_id: str = Field(pattern=r"^imgsdxltargetpreprun_[0-9a-f]{32}$")
    command_sha256: Sha256
    source_snapshot_sha256: Sha256
    state: Literal["UNREVIEWED_TRAIN_TARGET_CANDIDATES"]
    activation_policy: Literal["FORBIDDEN"]
    status: Literal["SUCCEEDED", "FAILED"]
    error_code: TargetErrorCode | None
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    prepared_targets: tuple[SdxlPreparedSourceTrainingTarget, ...] = Field(max_length=512)
    deferred_sample_ids: tuple[_SampleId, ...] = Field(max_length=511)
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        return LocalImageSdxlSourceTrainingTargetCommand.utc_created(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        prepared = tuple(target.sample_id for target in self.prepared_targets)
        deferred = self.deferred_sample_ids
        if (self.status == "SUCCEEDED") != (self.error_code is None) or (
            self.status == "SUCCEEDED" and not prepared
        ):
            raise ValueError("SDXL source target status/error/coverage mismatch")
        if (
            prepared != tuple(sorted(set(prepared)))
            or deferred != tuple(sorted(set(deferred)))
            or set(prepared).intersection(deferred)
            or len({target.target_id for target in self.prepared_targets}) != len(prepared)
            or self.completed_at < self.started_at
            or self.result_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        ):
            raise ValueError("SDXL source target order/time/hash mismatch")
        return self


@dataclass(frozen=True, slots=True)
class SdxlSourceTargetSample:
    """Derived workspace input; no independent persistence or duplicated source payload."""

    sample_id: str
    source_image: ImageEvaluationArtifactMember
    source_width_px: int
    source_height_px: int
    source_caption_en: str
    size_bytes: int

    @property
    def staged_member_path(self) -> str:
        return "inputs/source-crops/" + self.sample_id + ".png"


@dataclass(frozen=True, slots=True)
class SdxlSourceTrainingTargetSources:
    crop_set: LocalImageScienceSourcePageCropSet
    review: LocalImageScienceSourcePageCropReview
    authorization: LocalImageScienceCorpusTrainingAuthorization
    samples: tuple[SdxlSourceTargetSample, ...]
    snapshot_sha256: str


def parse_sdxl_source_training_target_sources(
    command: LocalImageSdxlSourceTrainingTargetCommand,
    *,
    crop_set_payload: bytes,
    review_payload: bytes,
    authorization_payload: bytes,
) -> SdxlSourceTrainingTargetSources:
    supplemental = command.source_crop_set.schema_ref == SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF
    crop_set = _source_document(
        command.source_crop_set,
        crop_set_payload,
        "science-source-page-crop-set-v2" if supplemental else "science-source-page-crop-set",
        LocalImageScienceSourcePageCropSetV2
        if supplemental
        else LocalImageScienceSourcePageCropSet,
    )
    review = _source_document(
        crop_set.review,
        review_payload,
        "science-source-page-crop-review-v2" if supplemental else "science-source-page-crop-review",
        LocalImageScienceSourcePageCropReviewV2
        if supplemental
        else LocalImageScienceSourcePageCropReview,
    )
    authorization = _source_document(
        command.training_authorization,
        authorization_payload,
        "science-corpus-training-authorization",
        LocalImageScienceCorpusTrainingAuthorization,
    )
    if crop_set.review.member_path != "manifests/science-source-page-crop-review.json" or (
        crop_set.review.schema_ref != source_page_crop_protocol(review).review_schema_ref
    ):
        raise ValueError("SDXL source target review pointer contract mismatch")
    validate_source_page_crop_set(review, crop_set)
    if (
        review.training_authorization != command.training_authorization
        or authorization.approved_at > review.created_at
        or crop_set.created_at > command.created_at
        or any(selection.partition != "TRAIN" for selection in review.selections)
        or tuple(decision.sample_id for decision in command.decisions)
        != tuple(selection.selection_id for selection in review.selections)
    ):
        raise ValueError("SDXL source target authorization/chronology/TRAIN coverage mismatch")
    samples = tuple(
        SdxlSourceTargetSample(
            selection.selection_id,
            source_page_crop_pointer(command.source_crop_set, member),
            member.width_px,
            member.height_px,
            selection.caption_en,
            member.size_bytes,
        )
        for selection, member in zip(review.selections, crop_set.members, strict=True)
    )
    by_id = {sample.sample_id: sample for sample in samples}
    for decision in command.decisions:
        if isinstance(decision, SdxlSourcePrepareTargetDecision):
            sdxl_source_target_placement(
                by_id[decision.sample_id],
                decision,
                maximum_upscale_milli=command.maximum_upscale_milli,
            )
    return SdxlSourceTrainingTargetSources(
        crop_set,
        review,
        authorization,
        samples,
        content_sha256(
            {
                "source_crop_set": command.source_crop_set.model_dump(mode="json"),
                "source_review": crop_set.review.model_dump(mode="json"),
                "training_authorization": command.training_authorization.model_dump(mode="json"),
            }
        ),
    )


def sdxl_source_target_placement(
    sample: SdxlSourceTargetSample,
    decision: SdxlSourcePrepareTargetDecision,
    *,
    maximum_upscale_milli: int,
) -> SdxlTargetPlacement:
    if sample.sample_id != decision.sample_id:
        raise ValueError("SDXL source target placement identity mismatch")
    return sdxl_reviewed_target_placement(
        width=sample.source_width_px,
        height=sample.source_height_px,
        framing_box=decision.framing_box,
        maximum_upscale_milli=maximum_upscale_milli,
    )


def sdxl_source_target_caption(
    sample: SdxlSourceTargetSample, decision: SdxlSourcePrepareTargetDecision
) -> str:
    if sample.sample_id != decision.sample_id:
        raise ValueError("SDXL source target caption identity mismatch")
    return sdxl_reviewed_target_caption(sample.source_caption_en, decision.expression)


def sdxl_source_target_id(
    command: LocalImageSdxlSourceTrainingTargetCommand,
    sample: SdxlSourceTargetSample,
    decision: SdxlSourcePrepareTargetDecision,
) -> str:
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


def validate_sdxl_source_training_target_result(
    command: LocalImageSdxlSourceTrainingTargetCommand,
    sources: SdxlSourceTrainingTargetSources,
    result: LocalImageSdxlSourceTrainingTargetResult,
) -> None:
    if (
        result.run_id != command.run_id
        or result.command_sha256 != command.command_sha256
        or result.source_snapshot_sha256 != sources.snapshot_sha256
        or result.started_at < command.created_at
    ):
        raise ValueError("SDXL source target result differs from admitted command/source")
    if (result.pillow_version != command.pillow_version) != (
        result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH"
    ) or (result.error_code == "SDXL_TARGET_RUNTIME_MISMATCH" and result.prepared_targets):
        raise ValueError("SDXL source target Pillow drift must fail before transformation")
    decisions = tuple(
        decision
        for decision in command.decisions
        if isinstance(decision, SdxlSourcePrepareTargetDecision)
    )
    expected = tuple(decision.sample_id for decision in decisions)
    observed = tuple(target.sample_id for target in result.prepared_targets)
    deferred = tuple(
        decision.sample_id for decision in command.decisions if decision.disposition == "DEFER"
    )
    if result.deferred_sample_ids != deferred or observed != (
        expected if result.status == "SUCCEEDED" else expected[: len(observed)]
    ):
        raise ValueError("SDXL source target result coverage is not declared success/prefix")
    samples = {sample.sample_id: sample for sample in sources.samples}
    recipes = {decision.sample_id: decision for decision in decisions}
    for target in result.prepared_targets:
        sample, recipe = samples[target.sample_id], recipes[target.sample_id]
        if (
            target.source_crop_sha256 != sample.source_image.sha256
            or target.target_id != sdxl_source_target_id(command, sample, recipe)
            or target.training_caption_en != sdxl_source_target_caption(sample, recipe)
            or target.placement
            != sdxl_source_target_placement(
                sample, recipe, maximum_upscale_milli=command.maximum_upscale_milli
            )
        ):
            raise ValueError("SDXL source target derivative differs from reviewed recipe")
