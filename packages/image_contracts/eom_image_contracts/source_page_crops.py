"""Reviewed literal source-page crops; old masked candidates remain immutable."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import ClassVar, Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.institutional_style_evaluation import INSTITUTIONAL_CROP_SCHEMA_REF
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_json_bytes,
    content_sha256,
    text_sha256,
)
from eom_image_contracts.science_corpus_visual import (
    LocalImageScienceCorpusTrainingAuthorization,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceObjectLineArtCropSet,
    LocalImageScienceVisualCampaignPatternInventory,
    ScienceVisualPageImage,
    ScienceVisualPilotSource,
)
from eom_image_contracts.sdxl_training_targets import TargetExpression
from eom_image_contracts.validation import validate_contract

_PREFIX = "eom://schemas/image-provider/local-image-"
SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF = _PREFIX + "science-source-page-crop-review/1.0"
SOURCE_PAGE_CROP_SET_SCHEMA_REF = _PREFIX + "science-source-page-crop-set/1.0"
SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF = _PREFIX + "science-source-page-crop-review/1.1"
SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF = _PREFIX + "science-source-page-crop-set/1.1"
SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF = _PREFIX + "science-source-page-crop-review/1.2"
SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF = _PREFIX + "science-source-page-crop-set/1.2"
SCIENCE_ORIGINAL_PAGE_SCHEMA_REF = _PREFIX + "science-corpus-visual-pilot-page-image/1.0"
SourcePageCropPartition = Literal["TRAIN", "VALIDATION", "HOLDOUT"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("source page crop timestamp must be UTC")
    return value


class ScienceSourcePageCropRegion(FrozenModel):
    """Shared immutable frame; detection is not an original page's identity."""

    selection_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    physical_page: int = Field(ge=1, le=512)
    source_document: ImageEvaluationArtifactMember
    source_page: ImageEvaluationArtifactMember
    page_width_px: int = Field(ge=100, le=10_000)
    page_height_px: int = Field(ge=100, le=10_000)
    page_render_dpi: Literal[144]
    pixel_box: tuple[int, int, int, int]
    exam_group_sha256: Sha256
    partition: SourcePageCropPartition
    depiction_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    caption_en: str = Field(
        min_length=3, max_length=180, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$"
    )
    caption_sha256: Sha256
    expression: TargetExpression

    @model_validator(mode="after")
    def exact_selection(self) -> Self:
        if self.source_document.media_type != "application/pdf" or (
            self.source_page.media_type != "image/png"
            or self.source_page.schema_ref != SCIENCE_ORIGINAL_PAGE_SCHEMA_REF
            or self.source_page.member_path
            != f"pages/{self.document_id}/page-{self.physical_page}.png"
        ):
            raise ValueError("source page crop pointer contract mismatch")
        left, top, right, bottom = self.pixel_box
        if not (
            0 <= left < right <= self.page_width_px
            and 0 <= top < bottom <= self.page_height_px
            and right - left >= 32
            and bottom - top >= 32
        ):
            raise ValueError("source page crop pixel box invalid")
        if self.caption_sha256 != text_sha256(self.caption_en):
            raise ValueError("source page crop caption hash mismatch")
        if self.selection_id != source_page_crop_selection_id(self.model_dump(mode="json")):
            raise ValueError("source page crop logical identity mismatch")
        return self


class ScienceSourcePageCropSelection(ScienceSourcePageCropRegion):
    candidate_id: str = Field(pattern=r"^imgsciviscandidate_[0-9a-f]{32}$")
    parent_candidate_sha256: Sha256


class ScienceSourcePageRegionSelection(ScienceSourcePageCropRegion):
    source_anchor: Literal["REVIEWED_ORIGINAL_PAGE"]


def source_page_crop_selection_id(value: dict[str, object]) -> str:
    """A corrected caption is revision content, not another independent drawing."""
    return (
        "imgsourcecrop_"
        + content_sha256(
            {
                key: value[key]
                for key in ("document_id", "physical_page", "source_page", "pixel_box")
            }
        )[7:39]
    )


class _SourcePageCropReview(FrozenModel):
    schema_version: str
    review_id: str = Field(pattern=r"^imgsourcecropreview_[0-9a-f]{32}$")
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:@-]+$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    basis_crop_set: ImageEvaluationArtifactMember
    training_authorization: ImageEvaluationArtifactMember
    selections: tuple[ScienceSourcePageCropRegion, ...] = Field(min_length=1, max_length=512)
    policy: Literal["REVIEWED_LITERAL_ORIGINAL_PAGE_PIXELS/1.0"]
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    activation_policy: Literal["FORBIDDEN"]
    review_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_review(self) -> Self:
        for pointer, family in (
            (self.basis_crop_set, "science-object-line-art-crop-set"),
            (self.training_authorization, "science-corpus-training-authorization"),
        ):
            if pointer.schema_ref != _PREFIX + family + "/1.0" or (
                pointer.media_type != "application/json"
            ):
                raise ValueError("source page crop basis contract mismatch")
        ids = tuple(selection.selection_id for selection in self.selections)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("source page crop selections must be uniquely sorted")
        documents = Counter(selection.document_id for selection in self.selections)
        groups = Counter(selection.exam_group_sha256 for selection in self.selections)
        if max(documents.values()) > 3 or max(groups.values()) > 4:
            raise ValueError("source page crop source concentration exceeds bounds")
        partitions: dict[str, SourcePageCropPartition] = {}
        pointers: dict[tuple[str, str, str], ImageEvaluationArtifactMember] = {}
        for selection in self.selections:
            for key in (selection.document_id, selection.exam_group_sha256):
                if partitions.setdefault(key, selection.partition) != selection.partition:
                    raise ValueError("source page crop partition leakage")
            for pointer in (selection.source_document, selection.source_page):
                pointer_key = (
                    pointer.artifact_id,
                    pointer.artifact_revision_id,
                    pointer.member_path,
                )
                if pointers.setdefault(pointer_key, pointer) != pointer:
                    raise ValueError("source page crop conflicting immutable pointers")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"review_id", "review_sha256"})
        )
        if self.review_id != "imgsourcecropreview_" + identity[7:39] or (
            self.review_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"review_sha256"}))
        ):
            raise ValueError("source page crop review identity/hash mismatch")
        return self


class LocalImageScienceSourcePageCropReview(_SourcePageCropReview):
    schema_version: Literal["local-image-science-source-page-crop-review/1.0"]
    selections: tuple[ScienceSourcePageCropSelection, ...] = Field(min_length=1, max_length=512)


class ScienceSourcePageCropMember(FrozenModel):
    selection_id: str = Field(pattern=r"^imgsourcecrop_[0-9a-f]{32}$")
    member_path: str = Field(pattern=r"^crops/imgsourcecrop_[0-9a-f]{32}\.png$")
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=8 * 1024**2)
    width_px: int = Field(ge=32, le=10_000)
    height_px: int = Field(ge=32, le=10_000)
    perceptual_hash: str = Field(pattern=r"^[0-9a-f]{16}$")

    @model_validator(mode="after")
    def exact_member(self) -> Self:
        if self.member_path != "crops/" + self.selection_id + ".png":
            raise ValueError("source page crop member identity mismatch")
        return self


class LocalImageScienceSourcePageCropSet(FrozenModel):
    _review_schema_ref: ClassVar[str] = SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF
    schema_version: Literal["local-image-science-source-page-crop-set/1.0"]
    crop_set_id: str = Field(pattern=r"^imgsourcecropset_[0-9a-f]{32}$")
    crop_set_revision_id: str = Field(pattern=r"^imgsourcecropsetrev_[0-9a-f]{32}$")
    created_at: datetime
    review: ImageEvaluationArtifactMember
    pillow_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    members: tuple[ScienceSourcePageCropMember, ...] = Field(min_length=1, max_length=512)
    state: Literal["REVIEWED_SOURCE_DERIVATIVES"]
    activation_policy: Literal["FORBIDDEN"]
    crop_set_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def utc_created(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def exact_set(self) -> Self:
        if (
            self.review.schema_ref != self._review_schema_ref
            or self.review.media_type != "application/json"
        ):
            raise ValueError("source page crop review pointer mismatch")
        ids = tuple(member.selection_id for member in self.members)
        if ids != tuple(sorted(set(ids))) or len({member.sha256 for member in self.members}) != len(
            self.members
        ):
            raise ValueError("source page crop set repeats identities or exact pixels")
        if self.crop_set_id != "imgsourcecropset_" + content_sha256({"selection_ids": ids})[7:39]:
            raise ValueError("source page crop set logical identity mismatch")
        revision = content_sha256(
            self.model_dump(mode="json", exclude={"crop_set_revision_id", "crop_set_sha256"})
        )
        if self.crop_set_revision_id != "imgsourcecropsetrev_" + revision[7:39] or (
            self.crop_set_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"crop_set_sha256"}))
        ):
            raise ValueError("source page crop set revision/hash mismatch")
        return self


class ScienceSourcePageCropSupplementalPilot(FrozenModel):
    """Small immutable value pair; parsed plans/results own their semantic identities."""

    pilot_plan: ImageEvaluationArtifactMember
    pilot_result: ImageEvaluationArtifactMember

    @model_validator(mode="after")
    def exact_pair(self) -> Self:
        for pointer, schema_ref, member in (
            (
                self.pilot_plan,
                _PREFIX + "science-corpus-visual-pilot-plan/1.3",
                "manifests/visual-pilot-plan.json",
            ),
            (
                self.pilot_result,
                _PREFIX + "science-corpus-visual-pilot-result/1.0",
                "manifests/visual-pilot-result.json",
            ),
        ):
            if (
                pointer.schema_ref != schema_ref
                or pointer.media_type != "application/json"
                or pointer.member_path != member
            ):
                raise ValueError("source page crop supplemental pointer contract mismatch")
        return self


class LocalImageScienceSourcePageCropReviewV2(LocalImageScienceSourcePageCropReview):
    # This additive wire family intentionally narrows a different discriminator; V1 is unchanged.
    schema_version: Literal["local-image-science-source-page-crop-review/1.1"]  # type: ignore[assignment]
    supplemental_pilots: tuple[ScienceSourcePageCropSupplementalPilot, ...] = Field(
        min_length=2, max_length=4
    )

    @model_validator(mode="after")
    def exact_supplemental_population(self) -> Self:
        _validate_supplemental_pilots(self.supplemental_pilots)
        return self


def _validate_supplemental_pilots(
    pilots: tuple[ScienceSourcePageCropSupplementalPilot, ...],
) -> None:
    for pointers in (
        tuple(pilot.pilot_plan for pilot in pilots),
        tuple(pilot.pilot_result for pilot in pilots),
    ):
        identities = {
            (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
            for pointer in pointers
        }
        if len(identities) != len(pointers):
            raise ValueError("source page crop repeats supplemental pilot identity")


class LocalImageScienceSourcePageCropReviewV3(_SourcePageCropReview):
    schema_version: Literal["local-image-science-source-page-crop-review/1.2"]
    selections: tuple[ScienceSourcePageRegionSelection, ...] = Field(min_length=1, max_length=512)
    supplemental_pilots: tuple[ScienceSourcePageCropSupplementalPilot, ...] = Field(max_length=4)

    @model_validator(mode="after")
    def exact_supplemental_population(self) -> Self:
        if len(self.supplemental_pilots) == 1:
            raise ValueError("source page crop requires a complete supplemental campaign")
        _validate_supplemental_pilots(self.supplemental_pilots)
        return self


SourcePageCropReview = (
    LocalImageScienceSourcePageCropReview | LocalImageScienceSourcePageCropReviewV3
)


class LocalImageScienceSourcePageCropSetV2(LocalImageScienceSourcePageCropSet):
    schema_version: Literal["local-image-science-source-page-crop-set/1.1"]  # type: ignore[assignment]
    _review_schema_ref: ClassVar[str] = SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF


class LocalImageScienceSourcePageCropSetV3(LocalImageScienceSourcePageCropSet):
    schema_version: Literal["local-image-science-source-page-crop-set/1.2"]  # type: ignore[assignment]
    _review_schema_ref: ClassVar[str] = SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF


@dataclass(frozen=True, slots=True)
class SourcePageCropProtocol:
    review_contract: str
    review_schema_ref: str
    set_contract: str
    set_schema_ref: str
    set_schema_version: str
    set_model: type[LocalImageScienceSourcePageCropSet]


_PROTOCOLS: Mapping[type[SourcePageCropReview], SourcePageCropProtocol] = MappingProxyType(
    {
        LocalImageScienceSourcePageCropReview: SourcePageCropProtocol(
            "science-source-page-crop-review",
            SOURCE_PAGE_CROP_REVIEW_SCHEMA_REF,
            "science-source-page-crop-set",
            SOURCE_PAGE_CROP_SET_SCHEMA_REF,
            "local-image-science-source-page-crop-set/1.0",
            LocalImageScienceSourcePageCropSet,
        ),
        LocalImageScienceSourcePageCropReviewV2: SourcePageCropProtocol(
            "science-source-page-crop-review-v2",
            SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
            "science-source-page-crop-set-v2",
            SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
            "local-image-science-source-page-crop-set/1.1",
            LocalImageScienceSourcePageCropSetV2,
        ),
        LocalImageScienceSourcePageCropReviewV3: SourcePageCropProtocol(
            "science-source-page-crop-review-v3",
            SOURCE_PAGE_CROP_REVIEW_V3_SCHEMA_REF,
            "science-source-page-crop-set-v3",
            SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
            "local-image-science-source-page-crop-set/1.2",
            LocalImageScienceSourcePageCropSetV3,
        ),
    }
)


def source_page_crop_protocol(review: SourcePageCropReview) -> SourcePageCropProtocol:
    """Closed released versions, not implicit subclass compatibility or a plugin registry."""
    protocol = _PROTOCOLS.get(type(review))
    if protocol is None:
        raise ValueError("source page crop unsupported review protocol")
    return protocol


def parse_source_page_crop_review(
    pointer: ImageEvaluationArtifactMember, payload: bytes
) -> SourcePageCropReview:
    """Resolve only released review meanings, with exact canonical bytes and hash."""
    parser = next(
        (
            (model, protocol)
            for model, protocol in _PROTOCOLS.items()
            if protocol.review_schema_ref == pointer.schema_ref
        ),
        None,
    )
    if (
        parser is None
        or pointer.media_type != "application/json"
        or pointer.member_path != "manifests/science-source-page-crop-review.json"
        or "sha256:" + hashlib.sha256(payload).hexdigest() != pointer.sha256
    ):
        raise ValueError("SCIENCE_SOURCE_CROP_REVIEW_POINTER_INVALID")
    model, protocol = parser
    value = json.loads(payload)
    validate_contract(protocol.review_contract, value)
    review = model.model_validate(value)
    canonical = content_json_bytes(review.model_dump(mode="json"))
    if payload not in (canonical, canonical + b"\n"):
        raise ValueError("SCIENCE_SOURCE_CROP_REVIEW_NONCANONICAL")
    return review


def validate_source_page_crop_sources(
    review: LocalImageScienceSourcePageCropReview,
    *,
    crop_set: LocalImageScienceObjectLineArtCropSet,
    authorization: LocalImageScienceCorpusTrainingAuthorization,
    inventory: LocalImageScienceVisualCampaignPatternInventory,
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...],
) -> None:
    """Called after existing full-lineage admission; match every new selection before pixels."""
    if review.training_authorization != crop_set.training_authorization or (
        authorization.approved_at > review.created_at
    ):
        raise ValueError("source page crop authorization mismatch")
    if len(plans) != len(results) or len(results) != len(inventory.pilot_results):
        raise ValueError("source page crop campaign coverage mismatch")
    validate_source_page_crop_selection_sources(
        review,
        plans=plans,
        results=results,
        result_pointers=tuple(pilot.pilot_result for pilot in inventory.pilot_results),
    )


def validate_source_page_crop_selection_sources(
    review: LocalImageScienceSourcePageCropReview,
    *,
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...],
    result_pointers: tuple[ImageEvaluationArtifactMember, ...],
) -> None:
    """Shared literal selection rule, after complete original or supplemental admission."""
    if (
        not 2 <= len(plans) <= 4
        or len(plans) != len(results)
        or len(results) != len(result_pointers)
    ):
        raise ValueError("source page crop campaign coverage mismatch")
    sources = {source.document_id: source for plan in plans for source in plan.selected_sources}
    if len(sources) != sum(len(plan.selected_sources) for plan in plans):
        raise ValueError("source page crop campaign repeats sources")
    by_candidate = {}
    for plan, result, result_pointer in zip(plans, results, result_pointers, strict=True):
        if result.completed_at > review.created_at:
            raise ValueError("source page crop source is newer than review")
        pages = {(page.document_id, page.physical_page): page for page in result.page_images}
        for candidate in result.visual_candidates:
            if candidate.candidate_id in by_candidate:
                raise ValueError("source page crop campaign repeats parent candidates")
            by_candidate[candidate.candidate_id] = (candidate, pages, result_pointer, plan)
    for selection in review.selections:
        found = by_candidate.get(selection.candidate_id)
        if found is None:
            raise ValueError("source page crop parent missing")
        candidate, pages, result_pointer, plan = found
        source = sources[candidate.document_id]
        page = pages[(candidate.document_id, candidate.physical_page)]
        box = candidate.bounding_box
        parent_box = (
            box.left * page.width_px // 10_000,
            box.top * page.height_px // 10_000,
            (box.right * page.width_px + 9_999) // 10_000,
            (box.bottom * page.height_px + 9_999) // 10_000,
        )
        left, top, right, bottom = selection.pixel_box
        if max(left, parent_box[0]) >= min(right, parent_box[2]) or max(top, parent_box[1]) >= min(
            bottom, parent_box[3]
        ):
            raise ValueError("source page crop frame does not intersect its declared candidate")
        if (
            selection.document_id != candidate.document_id
            or selection.physical_page != candidate.physical_page
            or selection.parent_candidate_sha256 != candidate.sha256
            or candidate.page_image_sha256 != page.sha256
        ):
            raise ValueError("source page crop immutable source/partition mismatch")
        _validate_region_source(selection, source, page, result_pointer, plan)


def _validate_region_source(
    selection: ScienceSourcePageCropRegion,
    source: ScienceVisualPilotSource,
    page: ScienceVisualPageImage,
    result_pointer: ImageEvaluationArtifactMember,
    plan: LocalImageScienceCorpusVisualPilotPlanV3,
) -> None:
    expected_page = ImageEvaluationArtifactMember(
        artifact_id=result_pointer.artifact_id,
        artifact_revision_id=result_pointer.artifact_revision_id,
        member_path=page.member_path,
        schema_ref=SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
        media_type="image/png",
        sha256=page.sha256,
    )
    if (
        selection.document_id != source.document_id
        or selection.document_id != page.document_id
        or selection.physical_page != page.physical_page
        or selection.source_page != expected_page
        or selection.source_document != source.pdf
        or selection.exam_group_sha256 != source.exam_group_sha256
        or selection.partition != source.partition
        or selection.page_width_px != page.width_px
        or selection.page_height_px != page.height_px
        or selection.page_render_dpi != plan.page_render_dpi
    ):
        raise ValueError("source page crop immutable source/partition mismatch")


def validate_source_page_region_sources(
    review: LocalImageScienceSourcePageCropReviewV3,
    *,
    plans: tuple[LocalImageScienceCorpusVisualPilotPlanV3, ...],
    results: tuple[LocalImageScienceCorpusVisualPilotResult, ...],
    result_pointers: tuple[ImageEvaluationArtifactMember, ...],
) -> None:
    """Page-indexed admission, independent of detector recall, after full lineage admission."""
    if (
        not 2 <= len(plans) <= 8
        or len(plans) != len(results)
        or len(results) != len(result_pointers)
    ):
        raise ValueError("source page crop campaign coverage mismatch")
    sources: dict[str, ScienceVisualPilotSource] = {}
    hashes: set[str] = set()
    partitions: dict[str, SourcePageCropPartition] = {}
    pages = {}
    for plan, result, pointer in zip(plans, results, result_pointers, strict=True):
        if result.completed_at > review.created_at:
            raise ValueError("source page crop source is newer than review")
        local_sources = {source.document_id: source for source in plan.selected_sources}
        for source in plan.selected_sources:
            if source.document_id in sources or source.pdf.sha256 in hashes:
                raise ValueError("source page crop campaign repeats sources")
            sources[source.document_id] = source
            hashes.add(source.pdf.sha256)
            if (
                partitions.setdefault(source.exam_group_sha256, source.partition)
                != source.partition
            ):
                raise ValueError("source page crop source partition leakage")
        for page in result.page_images:
            key = (page.document_id, page.physical_page)
            if key in pages or page.document_id not in local_sources:
                raise ValueError("source page crop repeats or invents source pages")
            pages[key] = (local_sources[page.document_id], page, pointer, plan)
    for selection in review.selections:
        matched = pages.get((selection.document_id, selection.physical_page))
        if matched is None:
            raise ValueError("source page crop original page missing")
        _validate_region_source(selection, *matched)


def validate_source_page_crop_set(
    review: SourcePageCropReview, crop_set: LocalImageScienceSourcePageCropSet
) -> None:
    protocol = source_page_crop_protocol(review)
    if (
        type(crop_set) is not protocol.set_model
        or crop_set.review.schema_ref != protocol.review_schema_ref
    ):
        raise ValueError("source page crop review/output protocol mismatch")
    if (
        crop_set.review.sha256
        != "sha256:"
        + hashlib.sha256(content_json_bytes(review.model_dump(mode="json"))).hexdigest()
    ):
        raise ValueError("source page crop reviewed recipe hash mismatch")
    if crop_set.created_at < review.created_at or crop_set.pillow_version != review.pillow_version:
        raise ValueError("source page crop execution provenance mismatch")
    if tuple(member.selection_id for member in crop_set.members) != tuple(
        selection.selection_id for selection in review.selections
    ):
        raise ValueError("source page crop output coverage mismatch")
    for selection, member in zip(review.selections, crop_set.members, strict=True):
        left, top, right, bottom = selection.pixel_box
        if (member.width_px, member.height_px) != (right - left, bottom - top):
            raise ValueError("source page crop output is not the reviewed literal rectangle")


def source_page_crop_pointer(
    crop_set_pointer: ImageEvaluationArtifactMember, member: ScienceSourcePageCropMember
) -> ImageEvaluationArtifactMember:
    if (
        crop_set_pointer.schema_ref
        not in {
            SOURCE_PAGE_CROP_SET_SCHEMA_REF,
            SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
            SOURCE_PAGE_CROP_SET_V3_SCHEMA_REF,
        }
        or crop_set_pointer.media_type != "application/json"
    ):
        raise ValueError("source page crop set pointer contract mismatch")
    return ImageEvaluationArtifactMember(
        artifact_id=crop_set_pointer.artifact_id,
        artifact_revision_id=crop_set_pointer.artifact_revision_id,
        member_path=member.member_path,
        schema_ref=INSTITUTIONAL_CROP_SCHEMA_REF,
        media_type="image/png",
        sha256=member.sha256,
    )
