"""Own-reviewed object support is input evidence, never publication approval.

No image decoding or pointer resolution here: the owning application must resolve
access/lifecycle and recompute immutable pixel observations before consumption.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_json_bytes,
    content_sha256,
)

PREFIX = "eom://schemas/image-provider/local-image-"
REVIEW_SCHEMA = PREFIX + "photo-object-support-review/1.0"


class PhotoObjectSupportPixelObservation(FrozenModel):
    """Small immutable claims; a future pixel consumer must recompute all counts."""

    width_px: Literal[832] = 832
    height_px: Literal[512] = 512
    mask_mode: Literal["L"] = "L"
    control_mode: Literal["RGB"] = "RGB"
    mask_tones: tuple[Literal[0], Literal[255]] = (0, 255)
    control_polarity: Literal["WHITE_EDGES_ON_BLACK_RGB"] = "WHITE_EDGES_ON_BLACK_RGB"
    support_area_pixels: int = Field(ge=1, lt=832 * 512, strict=True)
    original_edges: int = Field(ge=2, lt=832 * 512, strict=True)
    retained_edges: int = Field(ge=1, lt=832 * 512, strict=True)
    deleted_edges: int = Field(ge=1, lt=832 * 512, strict=True)
    added_edges: Literal[0] = 0

    @field_validator("added_edges", mode="before")
    @classmethod
    def integer_zero(cls, value: object) -> int:
        if type(value) is not int or value != 0:
            raise ValueError("OBJECT_SUPPORT_ADDED_EDGES_NOT_INTEGER_ZERO")
        return value

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if (
            self.original_edges != self.retained_edges + self.deleted_edges
            or self.retained_edges > self.support_area_pixels
        ):
            raise ValueError("OBJECT_SUPPORT_PIXEL_COUNTS_INVALID")
        return self


class PhotoObjectSupportReview(FrozenModel):
    schema_version: Literal["local-image-photo-object-support-review/1.0"]
    review_id: str = Field(pattern=r"^imgphotosupportreview_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_OBJECT_SUPPORT"]
    activation_policy: Literal["FORBIDDEN"]
    context_policy: Literal["SUBJECT_MORPHOLOGY_ONLY_IRRELEVANT_BACKDROP"]
    source_kind: Literal["PHOTOGRAPH"]
    source_population: Literal["LICENSED_MORPHOLOGY_REFERENCES_NOT_CORPUS_HOLDOUT"]
    source_coordinate_system: Literal["NORMALIZED_PHOTO_PIXELS_800X504"]
    mask_coordinate_system: Literal["CANNY_CANVAS_PIXELS_832X512"]
    source: ImageEvaluationArtifactMember
    prior_control: ImageEvaluationArtifactMember
    support_mask: ImageEvaluationArtifactMember
    candidate_control: ImageEvaluationArtifactMember
    pixel_observation: PhotoObjectSupportPixelObservation
    own_review_evidence: ImageEvaluationArtifactMember
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    decision: Literal["OWN_INPUT_ACCEPTED_FOR_BOUNDED_COMPARISON_NOT_PUBLICATION"]
    review_independence: Literal["OWN_NOT_BLIND"]
    preserved_features: tuple[str, ...] = Field(min_length=2, max_length=16)
    observation: str = Field(min_length=10, max_length=1000, pattern=r"^[ -~]+$")
    review_sha256: Sha256

    @field_validator("created_at", "reviewed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("OBJECT_SUPPORT_TIMESTAMP_NOT_UTC")
        return value

    @field_validator("preserved_features")
    @classmethod
    def exact_feature_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            len(set(value)) != len(value)
            or value != tuple(sorted(value))
            or not {"ORIENTATION_POSITION", "WHOLE_SILHOUETTE"}.issubset(value)
            or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", tag) for tag in value)
        ):
            raise ValueError("OBJECT_SUPPORT_FEATURE_TAGS_INVALID")
        return value

    @model_validator(mode="after")
    def exact_review(self) -> Self:
        expected = (
            (
                self.source,
                "eom://schemas/image-provider/normalized-visual-reference/1.0",
                "references/primary.png",
            ),
            (self.support_mask, PREFIX + "photo-object-support-mask/1.0", "masks/foreground.png"),
            (
                self.candidate_control,
                PREFIX + "photo-object-support-conditioning/1.0",
                "conditionings/candidate.png",
            ),
        )
        if any(
            p.schema_ref != schema or p.media_type != "image/png" or p.member_path != path
            for p, schema, path in expected
        ) or (
            self.prior_control.schema_ref != PREFIX + "sdxl-canny-conditioning-output/1.0"
            or self.prior_control.media_type != "image/png"
            or not re.fullmatch(
                r"conditionings/imgsdxlcase_[0-9a-f]{32}\.png", self.prior_control.member_path
            )
        ):
            raise ValueError("OBJECT_SUPPORT_POINTER_KIND_INVALID")
        pins = (self.source, self.prior_control, self.support_mask, self.candidate_control)
        identities = {(p.artifact_id, p.artifact_revision_id, p.member_path) for p in pins}
        if len(identities) != 4 or len({p.sha256 for p in pins}) != 4:
            raise ValueError("OBJECT_SUPPORT_BINARY_IDENTITY_DUPLICATE")
        evidence = self.own_review_evidence
        if (
            evidence.schema_ref != "eom://schemas/operations/plain-text-log/1.0"
            or evidence.media_type != "text/plain"
            or evidence.member_path != "reports/own-review.json"
        ):
            raise ValueError("OBJECT_SUPPORT_OWN_EVIDENCE_KIND_INVALID")
        if self.reviewed_at > self.created_at:
            raise ValueError("OBJECT_SUPPORT_REVIEW_CHRONOLOGY_INVALID")
        value = self.model_dump(mode="json")
        if self.review_id != "imgphotosupportreview_" + content_sha256(
            {key: v for key, v in value.items() if key not in {"review_id", "review_sha256"}}
        )[7:39] or self.review_sha256 != content_sha256(
            {key: v for key, v in value.items() if key != "review_sha256"}
        ):
            raise ValueError("OBJECT_SUPPORT_REVIEW_IDENTITY_HASH_INVALID")
        return self


def parse_photo_object_support_review(
    pointer: ImageEvaluationArtifactMember, raw: bytes
) -> PhotoObjectSupportReview:
    """Validate already-resolved metadata; never dereference a path or a pointer."""
    from eom_image_contracts.validation import validate_contract

    if (
        pointer.schema_ref != REVIEW_SCHEMA
        or pointer.media_type != "application/json"
        or pointer.member_path != "manifests/photo-object-support-review.json"
    ):
        raise ValueError("OBJECT_SUPPORT_REVIEW_POINTER_KIND_INVALID")
    if (
        not 0 < len(raw) <= 128 * 1024
        or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
    ):
        raise ValueError("OBJECT_SUPPORT_REVIEW_BOUND_HASH_INVALID")
    value = json.loads(raw)
    validate_contract("photo-object-support-review", value)
    review = PhotoObjectSupportReview.model_validate(value)
    if raw != content_json_bytes(review.model_dump(mode="json")):
        raise ValueError("OBJECT_SUPPORT_REVIEW_NONCANONICAL")
    return review


class PhotoObjectSupportParents(FrozenModel):
    """Small immutable metadata pins, not loaded parent payloads or latest aliases."""

    review: ImageEvaluationArtifactMember
    prior_plan: ImageEvaluationArtifactMember
    prior_result: ImageEvaluationArtifactMember
    baseline_plan: ImageEvaluationArtifactMember
    baseline_result: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_kinds(self) -> Self:
        pins = (
            (self.review, REVIEW_SCHEMA, "photo-object-support-review"),
            *(
                (
                    pin,
                    "eom://schemas/image-provider/local-image-sdxl-photo-style-" + family + "/1.5",
                    "sdxl-photo-style-" + family,
                )
                for pin, family in (
                    (self.prior_plan, "plan"),
                    (self.prior_result, "result"),
                    (self.baseline_plan, "plan"),
                    (self.baseline_result, "result"),
                )
            ),
        )
        if any(
            pin.schema_ref != schema
            or pin.member_path != "manifests/" + filename + ".json"
            or pin.media_type != "application/json"
            for pin, schema, filename in pins
        ):
            raise ValueError("OBJECT_SUPPORT_PARENT_POINTER_KIND_INVALID")
        # The same parent can legitimately be both control provenance and baseline;
        # conflicting claims about one immutable member cannot.
        claims: dict[tuple[str, str, str], ImageEvaluationArtifactMember] = {}
        for pin, _, _ in pins:
            identity = (pin.artifact_id, pin.artifact_revision_id, pin.member_path)
            if identity in claims and claims[identity] != pin:
                raise ValueError("OBJECT_SUPPORT_PARENT_IDENTITY_CONFLICT")
            claims[identity] = pin
        return self


@dataclass(frozen=True, slots=True)
class PhotoObjectSupportParentDocuments:
    """One bounded input materialization; no binary PNG payloads in this value."""

    review: bytes
    prior_plan: bytes
    prior_result: bytes
    baseline_plan: bytes
    baseline_result: bytes


class PhotoBaselineReuse(FrozenModel):
    """Explicit previous object-supported BASE, not its old adapter or image bytes."""

    prior_plan: ImageEvaluationArtifactMember
    prior_result: ImageEvaluationArtifactMember
    prior_configuration: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_roles(self) -> Self:
        for pin, family, version in (
            (self.prior_plan, "sdxl-photo-style-plan", "1.6"),
            (self.prior_result, "sdxl-photo-style-result", "1.6"),
            (self.prior_configuration, "sdxl-canny-reference-command", "1.3"),
        ):
            if (
                pin.schema_ref != PREFIX + family + "/" + version
                or pin.member_path != "manifests/" + family + ".json"
                or pin.media_type != "application/json"
            ):
                raise ValueError("PHOTO_BASELINE_REUSE_POINTER_KIND_INVALID")
        return self


@dataclass(frozen=True, slots=True)
class PhotoBaselineReuseDocuments:
    prior_plan: bytes
    prior_result: bytes
    prior_configuration: bytes
    prior_geometry: bytes
