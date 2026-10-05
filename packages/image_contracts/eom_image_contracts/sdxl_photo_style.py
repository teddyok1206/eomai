"""Licensed photo authority is not institutional crop or worker dispatch authority."""

from __future__ import annotations

import hashlib
import json
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
from eom_image_contracts.sdxl_lineart_probe import SdxlLineartProbeCase
from eom_image_contracts.visual_reference import (
    LocalImageVisualReferenceBundle,
    LocalImageVisualReferenceIntent,
    LocalImageVisualReferencePointer,
    VisualReferenceBundleManifestPointer,
    VisualReferenceIntentArtifactPointer,
    VisualReferencePngArtifactPointer,
    validate_visual_reference_bundle_intent,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("photo style timestamps must use UTC")
    return value


class SdxlPhotoSourceReview(FrozenModel):
    """Own visual observation, not an independent quality or license approval."""

    source_kind: Literal["PHOTOGRAPH"]
    reviewed_at: datetime
    reviewed_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    reference_sha256: Sha256
    observation: str = Field(min_length=10, max_length=1000, pattern=r"^[ -~]+$")

    _review_utc = field_validator("reviewed_at")(_utc)


class SdxlPhotoStyleCase(FrozenModel):
    visual_reference: LocalImageVisualReferencePointer
    source_review: SdxlPhotoSourceReview
    case: SdxlLineartProbeCase

    @model_validator(mode="after")
    def exact_photo(self) -> Self:
        pointer = self.visual_reference.reference_member
        if (
            self.case.reference_image != photo_style_artifact_pointer(pointer)
            or self.source_review.reference_sha256 != pointer.sha256
            or (self.case.reference_width_px, self.case.reference_height_px) != (800, 504)
        ):
            raise ValueError("photo style case differs from reviewed normalized reference")
        return self


class SdxlPhotoStyleInitialization(FrozenModel):
    policy: Literal["FIT_GRAYSCALE_WHITE_RGB_832X512/1.0"]
    denoising_strength: float = Field(ge=0.7, le=0.7, strict=True)
    scheduler_steps: Literal[30]
    effective_denoising_steps: Literal[21]
    pillow_version: Literal["11.3.0"]


class SdxlPhotoStyleBudget(FrozenModel):
    maximum_duration_ms: int = Field(ge=1, le=600_000)
    maximum_peak_gpu_memory_bytes: int = Field(ge=1, le=16 * 1024**3)
    maximum_outputs: Literal[12] = 12
    maximum_dispatches: Literal[1] = 1
    automatic_retry: Literal[False] = False


class LocalImageSdxlPhotoStylePlan(FrozenModel):
    schema_version: Literal["local-image-sdxl-photo-style-plan/1.0"]
    plan_id: str = Field(pattern=r"^imgsdxlphotoplan_[0-9a-f]{32}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    created_at: datetime
    purpose: Literal["EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE"]
    dispatch_policy: Literal["PREPARATION_ONLY_NOT_A_WORKER_COMMAND"]
    activation_policy: Literal["FORBIDDEN"]
    source_population: Literal["LICENSED_MORPHOLOGY_REFERENCES_NOT_CORPUS_HOLDOUT"]
    configuration_anchor: ImageEvaluationArtifactMember
    cases: tuple[SdxlPhotoStyleCase, ...] = Field(min_length=1, max_length=6)
    seed: int = Field(ge=0, le=2**32 - 1)
    initialization: SdxlPhotoStyleInitialization
    budget: SdxlPhotoStyleBudget
    plan_sha256: Sha256

    _created_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        anchor = self.configuration_anchor
        if (
            anchor.schema_ref
            != "eom://schemas/image-provider/local-image-sdxl-canny-reference-command/1.2"
            or anchor.member_path != "manifests/sdxl-canny-reference-command.json"
            or anchor.media_type != "application/json"
        ):
            raise ValueError("photo style requires the pinned native1.2 configuration")
        ids = tuple(row.case.case_id for row in self.cases)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("photo style cases must be uniquely sorted")
        for values in (
            tuple(row.case.depiction_key for row in self.cases),
            tuple(row.case.reference_image.sha256 for row in self.cases),
            tuple(row.visual_reference.bundle_revision_id for row in self.cases),
            tuple(row.visual_reference.primary_reference_id for row in self.cases),
            tuple(row.visual_reference.bundle_manifest for row in self.cases),
        ):
            if len(set(values)) != len(ids):
                raise ValueError("photo style contains duplicated sources")
        if any(
            row.case.seeds != (self.seed,) or row.source_review.reviewed_at > self.created_at
            for row in self.cases
        ):
            raise ValueError("photo style seed or source review chronology mismatch")
        if self.plan_id != "imgsdxlphotoplan_" + content_sha256(
            self.model_dump(mode="json", exclude={"plan_id", "plan_sha256"})
        )[7:39] or self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("photo style plan identity/hash mismatch")
        return self


def photo_style_artifact_pointer(
    pointer: VisualReferenceBundleManifestPointer
    | VisualReferenceIntentArtifactPointer
    | VisualReferencePngArtifactPointer,
) -> ImageEvaluationArtifactMember:
    """Translate identity only; size remains an explicit materialization bound."""
    return ImageEvaluationArtifactMember.model_validate(
        pointer.model_dump(mode="json", exclude={"size_bytes"})
    )


@dataclass(frozen=True, slots=True)
class SdxlPhotoStyleSource:
    reference: LocalImageVisualReferencePointer
    bundle: LocalImageVisualReferenceBundle
    intent: LocalImageVisualReferenceIntent


def _metadata(raw: bytes, *, pointer: ImageEvaluationArtifactMember, maximum_bytes: int) -> object:
    if (
        not 0 < len(raw) <= maximum_bytes
        or "sha256:" + hashlib.sha256(raw).hexdigest() != pointer.sha256
    ):
        raise ValueError("photo style metadata size/hash mismatch")
    value = json.loads(raw)
    if content_json_bytes(value) != raw:
        raise ValueError("photo style metadata is noncanonical")
    return value


def parse_photo_style_bundle(
    reference: LocalImageVisualReferencePointer, raw: bytes
) -> LocalImageVisualReferenceBundle:
    from eom_image_contracts.validation import validate_contract

    pin = reference.bundle_manifest
    if len(raw) != pin.size_bytes:
        raise ValueError("photo style bundle exact size mismatch")
    value = _metadata(raw, pointer=photo_style_artifact_pointer(pin), maximum_bytes=2 * 1024**2)
    if not isinstance(value, dict):
        raise ValueError("photo style bundle object required")
    validate_contract("visual-reference-bundle", value)
    bundle = LocalImageVisualReferenceBundle.model_validate(value)
    member = bundle.normalized_member
    if (
        bundle.bundle_id != reference.bundle_id
        or bundle.bundle_revision_id != reference.bundle_revision_id
        or bundle.primary_reference_id != reference.primary_reference_id
        or member.sha256 != reference.reference_member.sha256
        or member.size_bytes != reference.reference_member.size_bytes
    ):
        raise ValueError("photo style reference differs from its canonical bundle")
    return bundle


def parse_photo_style_source(
    reference: LocalImageVisualReferencePointer, *, bundle_raw: bytes, intent_raw: bytes
) -> SdxlPhotoStyleSource:
    from eom_image_contracts.validation import validate_contract

    bundle = parse_photo_style_bundle(reference, bundle_raw)
    if len(intent_raw) != bundle.intent.size_bytes:
        raise ValueError("photo style intent exact size mismatch")
    value = _metadata(
        intent_raw, pointer=photo_style_artifact_pointer(bundle.intent), maximum_bytes=2 * 1024**2
    )
    if not isinstance(value, dict):
        raise ValueError("photo style intent object required")
    validate_contract("visual-reference-intent", value)
    intent = LocalImageVisualReferenceIntent.model_validate(value)
    validate_visual_reference_bundle_intent(bundle, intent)
    return SdxlPhotoStyleSource(reference, bundle, intent)


def validate_photo_style_sources(
    plan: LocalImageSdxlPhotoStylePlan,
    sources: tuple[SdxlPhotoStyleSource, ...],
    *,
    training_image_hashes: frozenset[str],
) -> None:
    """Metadata-only source closure; photo truth still requires actual visual inspection."""
    if tuple(row.reference for row in sources) != tuple(row.visual_reference for row in plan.cases):
        raise ValueError("photo style source closure/order mismatch")
    originals, pages = set(), set()
    for entry, source in zip(plan.cases, sources, strict=True):
        # Revalidate small immutable metadata without copying source image bytes.
        admitted = parse_photo_style_source(
            source.reference,
            bundle_raw=content_json_bytes(source.bundle.model_dump(mode="json")),
            intent_raw=content_json_bytes(source.intent.model_dump(mode="json")),
        )
        if admitted != source:
            raise ValueError("photo style source closure changed")
        primary = source.bundle.sources[0]
        if (
            source.bundle.observed_at > entry.source_review.reviewed_at
            or primary.original_sha256 in originals
            or primary.page_id in pages
            or primary.original_sha256 in training_image_hashes
            or source.bundle.normalized_member.sha256 in training_image_hashes
        ):
            raise ValueError("photo style source chronology/duplicate/training collision")
        originals.add(primary.original_sha256)
        pages.add(primary.page_id)
