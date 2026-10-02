"""Contracts for blinded institutional science-illustration style evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
)

INSTITUTIONAL_STYLE_PLAN_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-institutional-style-evaluation-plan/1.0"
)
INSTITUTIONAL_STYLE_RESULT_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-institutional-style-evaluation-result/1.0"
)
INSTITUTIONAL_STYLE_REVIEW_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-institutional-style-evaluation-review/1.0"
)
INSTITUTIONAL_STYLE_REVIEW_PACKET_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-institutional-style-review-packet/1.0"
)
INSTITUTIONAL_STYLE_ANSWER_KEY_SCHEMA_REF = (
    "eom://schemas/image-provider/local-image-institutional-style-answer-key/1.0"
)
INSTITUTIONAL_STYLE_BLIND_PNG_SCHEMA_REF: Final = (
    "eom://schemas/image-provider/local-image-institutional-style-blind-presentation-png/1.0"
)
INSTITUTIONAL_CROP_SCHEMA_REF = "eom://schemas/image-provider/local-image-science-visual-crop/1.0"
GENERATED_RASTER_SCHEMA_REF = "eom://schemas/generated-item/semantic-raster-png/1.0"

InstitutionalStyleSubjectFamily = Literal[
    "EARTH_SPACE",
    "LAB_APPARATUS",
    "LIVING_ORGANISM",
    "NATURAL_OBJECT",
    "PHYSICAL_OBJECT",
    "REAL_WORLD_SCENE",
]
InstitutionalStyleOrigin = Literal["GENERATED", "INSTITUTIONAL"]
InstitutionalStyleTrack = Literal["OBJECT_LINE_ART", "RASTER_TEXTURE_SCENE"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("institutional-style timestamp must be UTC")
    return value


def _require_image(pointer: ImageEvaluationArtifactMember, *, schema_ref: str) -> None:
    if pointer.schema_ref != schema_ref or pointer.media_type != "image/png":
        raise ValueError("institutional-style image pointer contract mismatch")


class InstitutionalStyleEvaluationCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgstylecase_[0-9a-f]{32}$")
    subject_family: InstitutionalStyleSubjectFamily
    depiction_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    institutional_image: ImageEvaluationArtifactMember
    generated_image: ImageEvaluationArtifactMember
    generated_request_sha256: Sha256
    generated_receipt_sha256: Sha256
    left_origin: InstitutionalStyleOrigin
    presentation_token: str = Field(pattern=r"^blind_[0-9a-f]{32}$")

    @model_validator(mode="after")
    def exact_identity_and_images(self) -> Self:
        _require_image(self.institutional_image, schema_ref=INSTITUTIONAL_CROP_SCHEMA_REF)
        _require_image(self.generated_image, schema_ref=GENERATED_RASTER_SCHEMA_REF)
        identity = content_sha256(
            {
                "subject_family": self.subject_family,
                "depiction_key": self.depiction_key,
                "institutional_image": self.institutional_image.model_dump(mode="json"),
                "generated_image": self.generated_image.model_dump(mode="json"),
                "generated_request_sha256": self.generated_request_sha256,
                "generated_receipt_sha256": self.generated_receipt_sha256,
            }
        ).removeprefix("sha256:")[:32]
        if self.case_id != f"imgstylecase_{identity}":
            raise ValueError("institutional-style case ID mismatch")
        return self


class LocalImageInstitutionalStyleEvaluationPlan(FrozenModel):
    schema_version: Literal["local-image-institutional-style-evaluation-plan/1.0"]
    evaluation_id: str = Field(pattern=r"^imgstyleeval_[0-9a-f]{32}$")
    created_at: datetime
    selection_method: Literal["SUBJECT_MATCHED_SINGLE_TRACK_ORIGIN_BLIND_V1"]
    blinding_method: Literal["CSPRNG_128_BIT_TOKEN_V1"]
    style_track: InstitutionalStyleTrack
    presentation_policy: Literal["FOREGROUND_BBOX_FIT_800X500_V1"]
    provider_binding_sha256: Sha256
    maximum_generated_origin_identification_rate: float = Field(ge=0.5, le=0.75)
    minimum_mean_institutional_style_score: float = Field(ge=3, le=5)
    cases: tuple[InstitutionalStyleEvaluationCase, ...] = Field(min_length=12, max_length=32)
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        keys = tuple(case.case_id for case in self.cases)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("institutional-style cases must be uniquely sorted")
        institutional = {case.institutional_image.sha256 for case in self.cases}
        generated = {case.generated_image.sha256 for case in self.cases}
        if len(institutional) != len(self.cases) or len(generated) != len(self.cases):
            raise ValueError("institutional-style plan repeats an image")
        if institutional & generated:
            raise ValueError("institutional-style origins share an image hash")
        depiction_keys = {case.depiction_key for case in self.cases}
        if len(depiction_keys) != len(self.cases):
            raise ValueError("institutional-style plan repeats a depiction key")
        presentation_tokens = {case.presentation_token for case in self.cases}
        if len(presentation_tokens) != len(self.cases):
            raise ValueError("institutional-style plan repeats a presentation token")
        if len({case.subject_family for case in self.cases}) < 4:
            raise ValueError("institutional-style plan requires at least four subject families")
        left_counts = {
            origin: sum(case.left_origin == origin for case in self.cases)
            for origin in ("GENERATED", "INSTITUTIONAL")
        }
        if abs(left_counts["GENERATED"] - left_counts["INSTITUTIONAL"]) > 1:
            raise ValueError("institutional-style presentation order is unbalanced")
        identity = content_sha256(
            {
                "selection_method": self.selection_method,
                "blinding_method": self.blinding_method,
                "style_track": self.style_track,
                "presentation_policy": self.presentation_policy,
                "provider_binding_sha256": self.provider_binding_sha256,
                "maximum_generated_origin_identification_rate": (
                    self.maximum_generated_origin_identification_rate
                ),
                "minimum_mean_institutional_style_score": (
                    self.minimum_mean_institutional_style_score
                ),
                "cases": [case.model_dump(mode="json") for case in self.cases],
            }
        ).removeprefix("sha256:")[:32]
        if self.evaluation_id != f"imgstyleeval_{identity}":
            raise ValueError("institutional-style evaluation ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
        if self.plan_sha256 != expected:
            raise ValueError("institutional-style plan hash mismatch")
        return self


class InstitutionalStyleImageMetrics(FrozenModel):
    foreground_fraction_milli: int = Field(ge=0, le=1000)
    dark_fraction_milli: int = Field(ge=0, le=1000)
    mid_tone_fraction_milli: int = Field(ge=0, le=1000)
    edge_fraction_milli: int = Field(ge=0, le=1000)
    border_foreground_fraction_milli: int = Field(ge=0, le=1000)
    fine_detail_fraction_milli: int = Field(ge=0, le=1000)
    tiny_component_fraction_milli: int = Field(ge=0, le=1000)
    component_count: int = Field(ge=0, le=400_000)


class InstitutionalStyleCaseResult(FrozenModel):
    case_id: str = Field(pattern=r"^imgstylecase_[0-9a-f]{32}$")
    institutional_metrics: InstitutionalStyleImageMetrics
    generated_metrics: InstitutionalStyleImageMetrics
    metric_distance_milli: int = Field(ge=0, le=7000)

    @model_validator(mode="after")
    def exact_distance(self) -> Self:
        fields = (
            "foreground_fraction_milli",
            "dark_fraction_milli",
            "mid_tone_fraction_milli",
            "edge_fraction_milli",
            "border_foreground_fraction_milli",
            "fine_detail_fraction_milli",
            "tiny_component_fraction_milli",
        )
        expected = sum(
            abs(getattr(self.institutional_metrics, field) - getattr(self.generated_metrics, field))
            for field in fields
        )
        if self.metric_distance_milli != expected:
            raise ValueError("institutional-style metric distance mismatch")
        return self


class LocalImageInstitutionalStyleEvaluationResult(FrozenModel):
    schema_version: Literal["local-image-institutional-style-evaluation-result/1.0"]
    evaluation_id: str = Field(pattern=r"^imgstyleeval_[0-9a-f]{32}$")
    plan_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    case_results: tuple[InstitutionalStyleCaseResult, ...] = Field(max_length=32)
    completed_at: datetime
    result_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_result(self) -> Self:
        keys = tuple(result.case_id for result in self.case_results)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("institutional-style results must be uniquely sorted")
        if self.status == "FAILED" and self.case_results:
            raise ValueError("failed institutional-style result must be empty")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("institutional-style result hash mismatch")
        return self


class InstitutionalStyleBlindPresentationMember(FrozenModel):
    member_path: str = Field(pattern=r"^presentation/[0-9a-f]{64}\.png$")
    schema_ref: Literal[
        "eom://schemas/image-provider/local-image-institutional-style-blind-presentation-png/1.0"
    ] = INSTITUTIONAL_STYLE_BLIND_PNG_SCHEMA_REF
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[500] = 500
    size_bytes: int = Field(ge=64, le=8 * 1024 * 1024)
    sha256: Sha256

    @model_validator(mode="after")
    def content_addressed_path(self) -> Self:
        expected = f"presentation/{self.sha256.removeprefix('sha256:')}.png"
        if self.member_path != expected:
            raise ValueError("institutional-style blind member path mismatch")
        return self


class InstitutionalStyleReviewPacketCase(FrozenModel):
    case_id: str = Field(pattern=r"^imgstylecase_[0-9a-f]{32}$")
    subject_family: InstitutionalStyleSubjectFamily
    depiction_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    presentation_token: str = Field(pattern=r"^blind_[0-9a-f]{32}$")
    left_image: InstitutionalStyleBlindPresentationMember
    right_image: InstitutionalStyleBlindPresentationMember


class LocalImageInstitutionalStyleReviewPacket(FrozenModel):
    schema_version: Literal["local-image-institutional-style-review-packet/1.0"]
    evaluation_id: str = Field(pattern=r"^imgstyleeval_[0-9a-f]{32}$")
    plan_sha256: Sha256
    presentation_policy: Literal["FOREGROUND_BBOX_FIT_800X500_V1"]
    cases: tuple[InstitutionalStyleReviewPacketCase, ...] = Field(min_length=12, max_length=32)
    packet_sha256: Sha256

    @model_validator(mode="after")
    def exact_packet(self) -> Self:
        case_ids = tuple(case.case_id for case in self.cases)
        tokens = tuple(case.presentation_token for case in self.cases)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("institutional-style packet cases must be uniquely sorted")
        if len(set(tokens)) != len(tokens):
            raise ValueError("institutional-style packet repeats a presentation token")
        expected = content_sha256(self.model_dump(mode="json", exclude={"packet_sha256"}))
        if self.packet_sha256 != expected:
            raise ValueError("institutional-style packet hash mismatch")
        return self


class InstitutionalStyleAnswerKeyEntry(FrozenModel):
    case_id: str = Field(pattern=r"^imgstylecase_[0-9a-f]{32}$")
    presentation_token: str = Field(pattern=r"^blind_[0-9a-f]{32}$")
    left_origin: InstitutionalStyleOrigin


class LocalImageInstitutionalStyleAnswerKey(FrozenModel):
    schema_version: Literal["local-image-institutional-style-answer-key/1.0"]
    evaluation_id: str = Field(pattern=r"^imgstyleeval_[0-9a-f]{32}$")
    plan_sha256: Sha256
    entries: tuple[InstitutionalStyleAnswerKeyEntry, ...] = Field(min_length=12, max_length=32)
    answer_key_sha256: Sha256

    @model_validator(mode="after")
    def exact_answer_key(self) -> Self:
        case_ids = tuple(entry.case_id for entry in self.entries)
        tokens = tuple(entry.presentation_token for entry in self.entries)
        if case_ids != tuple(sorted(set(case_ids))):
            raise ValueError("institutional-style answer entries must be uniquely sorted")
        if len(set(tokens)) != len(tokens):
            raise ValueError("institutional-style answer key repeats a presentation token")
        expected = content_sha256(self.model_dump(mode="json", exclude={"answer_key_sha256"}))
        if self.answer_key_sha256 != expected:
            raise ValueError("institutional-style answer key hash mismatch")
        return self


InstitutionalStyleDefect = Literal[
    "BORDER_CLUTTER",
    "COMPOSITION_DRIFT",
    "EXCESSIVE_DETAIL",
    "EXTRA_OBJECT",
    "INSUFFICIENT_DETAIL",
    "LINE_WEIGHT_MISMATCH",
    "PSEUDOTEXT",
    "SEMANTIC_DEFECT",
    "TONE_MISMATCH",
    "TOO_PHOTOGRAPHIC",
    "TOO_STYLIZED",
    "WHITESPACE_MISMATCH",
]


class InstitutionalStyleSideReview(FrozenModel):
    institutional_style_score: int = Field(ge=1, le=5)
    semantic_suitability_score: int = Field(ge=1, le=5)
    composition_score: int = Field(ge=1, le=5)
    usability: Literal["REJECT", "USABLE_AFTER_DETERMINISTIC_OVERLAY", "USABLE_AS_IS"]
    defects: tuple[InstitutionalStyleDefect, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def sorted_defects(self) -> Self:
        if self.defects != tuple(sorted(set(self.defects))):
            raise ValueError("institutional-style defects must be uniquely sorted")
        return self


class InstitutionalStyleCaseReview(FrozenModel):
    case_id: str = Field(pattern=r"^imgstylecase_[0-9a-f]{32}$")
    guessed_generated_side: Literal["LEFT", "RIGHT", "UNSURE"]
    confidence: int = Field(ge=1, le=5)
    left: InstitutionalStyleSideReview
    right: InstitutionalStyleSideReview


class LocalImageInstitutionalStyleEvaluationReview(FrozenModel):
    schema_version: Literal["local-image-institutional-style-evaluation-review/1.0"]
    evaluation_id: str = Field(pattern=r"^imgstyleeval_[0-9a-f]{32}$")
    plan_sha256: Sha256
    result_sha256: Sha256
    reviewer_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    reviews: tuple[InstitutionalStyleCaseReview, ...] = Field(min_length=12, max_length=32)
    generated_origin_identification_rate: float = Field(ge=0, le=1)
    generated_mean_institutional_style_score: float = Field(ge=1, le=5)
    critical_generated_defect_count: int = Field(ge=0, le=32)
    verdict: Literal["CANDIDATE_CANARY_ELIGIBLE", "REJECTED"]
    reviewed_at: datetime
    review_sha256: Sha256

    @field_validator("reviewed_at")
    @classmethod
    def utc_reviewed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_hash(self) -> Self:
        keys = tuple(review.case_id for review in self.reviews)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("institutional-style reviews must be uniquely sorted")
        expected = content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        if self.review_sha256 != expected:
            raise ValueError("institutional-style review hash mismatch")
        return self


def validate_institutional_style_result(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    result: LocalImageInstitutionalStyleEvaluationResult,
) -> None:
    if result.evaluation_id != plan.evaluation_id or result.plan_sha256 != plan.plan_sha256:
        raise ValueError("institutional-style plan/result mismatch")
    if result.status == "SUCCEEDED" and tuple(case.case_id for case in plan.cases) != tuple(
        case.case_id for case in result.case_results
    ):
        raise ValueError("institutional-style result coverage mismatch")


def validate_institutional_style_review_packet(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    packet: LocalImageInstitutionalStyleReviewPacket,
    answer_key: LocalImageInstitutionalStyleAnswerKey,
) -> None:
    if (
        packet.evaluation_id != plan.evaluation_id
        or packet.plan_sha256 != plan.plan_sha256
        or packet.presentation_policy != plan.presentation_policy
        or answer_key.evaluation_id != plan.evaluation_id
        or answer_key.plan_sha256 != plan.plan_sha256
    ):
        raise ValueError("institutional-style review packet pointer chain mismatch")
    packet_by_id = {case.case_id: case for case in packet.cases}
    answer_by_id = {entry.case_id: entry for entry in answer_key.entries}
    plan_ids = tuple(case.case_id for case in plan.cases)
    if tuple(packet_by_id) != plan_ids or tuple(answer_by_id) != plan_ids:
        raise ValueError("institutional-style review packet coverage mismatch")
    for case in plan.cases:
        presented = packet_by_id[case.case_id]
        answer = answer_by_id[case.case_id]
        if (
            presented.subject_family != case.subject_family
            or presented.depiction_key != case.depiction_key
            or presented.presentation_token != case.presentation_token
            or answer.presentation_token != case.presentation_token
            or answer.left_origin != case.left_origin
        ):
            raise ValueError("institutional-style review packet case mismatch")


def validate_institutional_style_review(
    plan: LocalImageInstitutionalStyleEvaluationPlan,
    result: LocalImageInstitutionalStyleEvaluationResult,
    review: LocalImageInstitutionalStyleEvaluationReview,
) -> None:
    validate_institutional_style_result(plan, result)
    if result.status != "SUCCEEDED":
        raise ValueError("institutional-style review requires a successful result")
    if (
        review.evaluation_id != plan.evaluation_id
        or review.plan_sha256 != plan.plan_sha256
        or review.result_sha256 != result.result_sha256
    ):
        raise ValueError("institutional-style review pointer chain mismatch")
    case_by_id = {case.case_id: case for case in plan.cases}
    if tuple(case_by_id) != tuple(entry.case_id for entry in review.reviews):
        raise ValueError("institutional-style review coverage mismatch")
    correct = 0
    style_total = 0
    critical = 0
    generated_reviews: list[InstitutionalStyleSideReview] = []
    for entry in review.reviews:
        case = case_by_id[entry.case_id]
        generated_side = "LEFT" if case.left_origin == "GENERATED" else "RIGHT"
        if entry.guessed_generated_side == generated_side:
            correct += 1
        generated = entry.left if generated_side == "LEFT" else entry.right
        generated_reviews.append(generated)
        style_total += generated.institutional_style_score
        if set(generated.defects) & {
            "COMPOSITION_DRIFT",
            "EXTRA_OBJECT",
            "PSEUDOTEXT",
            "SEMANTIC_DEFECT",
        }:
            critical += 1
    rate = round(correct / len(review.reviews), 8)
    mean_style = round(style_total / len(review.reviews), 8)
    if (
        review.generated_origin_identification_rate != rate
        or review.generated_mean_institutional_style_score != mean_style
        or review.critical_generated_defect_count != critical
    ):
        raise ValueError("institutional-style review aggregates mismatch")
    eligible = (
        rate <= plan.maximum_generated_origin_identification_rate
        and mean_style >= plan.minimum_mean_institutional_style_score
        and critical == 0
        and all(
            entry.semantic_suitability_score >= 3
            and entry.composition_score >= 3
            and entry.usability != "REJECT"
            for entry in generated_reviews
        )
    )
    expected = "CANDIDATE_CANARY_ELIGIBLE" if eligible else "REJECTED"
    if review.verdict != expected:
        raise ValueError("institutional-style verdict mismatch")
