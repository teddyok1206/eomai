"""Immutable contracts for Internet-grounded local image conditioning."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eom_image_contracts.models import (
    LocalImageCompositeReceipt,
    LocalImageCompositeRequest,
    content_sha256,
)

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
EnglishSubject = Annotated[
    str,
    Field(
        min_length=3,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$",
    ),
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_safe_text(value: str) -> str:
    if value != value.strip() or value != unicodedata.normalize("NFC", value):
        raise ValueError("visual-reference text must be trimmed NFC")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("visual-reference text contains a control character")
    return value


def _require_url(
    value: str,
    *,
    hosts: frozenset[str],
    path_prefix: str = "/",
    allow_query: bool = False,
) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path.startswith(path_prefix)
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        raise ValueError("visual-reference URL is outside the reviewed boundary")
    return value


class VisualReferenceIntentCandidate(FrozenModel):
    rank: int = Field(ge=1, le=5)
    provider: Literal["WIKIMEDIA_COMMONS"] = "WIKIMEDIA_COMMONS"
    page_id: int = Field(ge=1)
    file_title: str = Field(
        min_length=6,
        max_length=240,
        pattern=r"^File:[^\x00-\x1f\x7f]+$",
    )
    canonical_page_url: str = Field(min_length=1, max_length=1000)
    selection_rationale: str = Field(min_length=1, max_length=500)
    intended_use: Literal["SUBJECT_MORPHOLOGY_REFERENCE"] = "SUBJECT_MORPHOLOGY_REFERENCE"
    license_expectation: Literal["PUBLIC_DOMAIN_OR_CC0"] = "PUBLIC_DOMAIN_OR_CC0"

    @field_validator("file_title", "selection_rationale")
    @classmethod
    def safe_text(cls, value: str) -> str:
        return _require_safe_text(value)

    @field_validator("canonical_page_url")
    @classmethod
    def exact_commons_page(cls, value: str) -> str:
        return _require_url(
            value,
            hosts=frozenset({"commons.wikimedia.org"}),
            path_prefix="/wiki/File:",
        )


class LocalImageVisualReferenceIntent(FrozenModel):
    schema_version: Literal["local-image-visual-reference-intent/1.0"] = (
        "local-image-visual-reference-intent/1.0"
    )
    intent_id: str = Field(pattern=r"^imgrefintent_[0-9a-f]{32}$")
    workflow_id: str = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    image_step_run_id: str = Field(pattern=r"^steprun_[0-9a-f]{32}$")
    image_job_id: str = Field(pattern=r"^job_[0-9a-f]{32}$")
    visual_ordinal: int = Field(ge=0, le=1)
    drawing_sha256: Sha256
    subject: EnglishSubject
    query_terms: tuple[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=80,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9 .()/_-]{0,79}$",
            ),
        ],
        ...,
    ] = Field(min_length=1, max_length=8)
    candidates: tuple[VisualReferenceIntentCandidate, ...] = Field(min_length=1, max_length=5)
    primary_candidate_page_id: int = Field(ge=1)
    intent_sha256: Sha256

    @field_validator("subject")
    @classmethod
    def safe_subject(cls, value: str) -> str:
        return _require_safe_text(value)

    @field_validator("query_terms")
    @classmethod
    def safe_query_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_safe_text(value) for value in values)

    @model_validator(mode="after")
    def canonical_candidates_and_hash(self) -> LocalImageVisualReferenceIntent:
        if self.query_terms != tuple(sorted(set(self.query_terms))):
            raise ValueError("visual-reference query terms must be sorted and unique")
        ranks = tuple(candidate.rank for candidate in self.candidates)
        if ranks != tuple(range(1, len(self.candidates) + 1)):
            raise ValueError("visual-reference candidate ranks must be contiguous")
        for values, label in (
            (tuple(candidate.page_id for candidate in self.candidates), "page IDs"),
            (tuple(candidate.file_title for candidate in self.candidates), "file titles"),
            (
                tuple(candidate.canonical_page_url for candidate in self.candidates),
                "page URLs",
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"visual-reference candidate {label} must be unique")
        if self.primary_candidate_page_id != self.candidates[0].page_id:
            raise ValueError("visual-reference primary candidate must be rank one")
        expected = content_sha256(self.model_dump(mode="json", exclude={"intent_sha256"}))
        if self.intent_sha256 != expected:
            raise ValueError("visual-reference intent hash mismatch")
        return self


class VisualReferenceIntentArtifactPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["manifests/visual-reference-intent.json"] = (
        "manifests/visual-reference-intent.json"
    )
    schema_ref: Literal["eom://schemas/image-provider/local-image-visual-reference-intent/1.0"] = (
        "eom://schemas/image-provider/local-image-visual-reference-intent/1.0"
    )
    media_type: Literal["application/json"] = "application/json"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)


class VisualReferenceSource(FrozenModel):
    reference_id: str = Field(pattern=r"^imgref_[0-9a-f]{32}$")
    rank: int = Field(ge=1, le=5)
    provider: Literal["WIKIMEDIA_COMMONS"] = "WIKIMEDIA_COMMONS"
    page_id: int = Field(ge=1)
    page_revision_id: int = Field(ge=1)
    file_title: str = Field(
        min_length=6,
        max_length=240,
        pattern=r"^File:[^\x00-\x1f\x7f]+$",
    )
    canonical_page_url: str = Field(min_length=1, max_length=1000)
    original_file_url: str = Field(min_length=1, max_length=2000)
    original_media_type: Literal["image/jpeg", "image/png", "image/webp"]
    original_size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    original_sha256: Sha256
    original_width_px: int = Field(ge=64, le=12_000)
    original_height_px: int = Field(ge=64, le=12_000)
    license_id: Literal["CC0-1.0", "PUBLIC-DOMAIN"]
    license_url: str = Field(min_length=1, max_length=1000)
    license_short_name: str = Field(min_length=1, max_length=80)
    attribution_required: Literal[False] = False
    intended_use: Literal["SUBJECT_MORPHOLOGY_REFERENCE"] = "SUBJECT_MORPHOLOGY_REFERENCE"
    disposition: Literal["PRIMARY_CONDITIONING", "VERIFIED_ALTERNATE"]

    @field_validator("file_title", "license_short_name")
    @classmethod
    def safe_text(cls, value: str) -> str:
        return _require_safe_text(value)

    @field_validator("canonical_page_url")
    @classmethod
    def exact_commons_page(cls, value: str) -> str:
        return _require_url(
            value,
            hosts=frozenset({"commons.wikimedia.org"}),
            path_prefix="/wiki/File:",
        )

    @field_validator("original_file_url")
    @classmethod
    def exact_commons_file(cls, value: str) -> str:
        return _require_url(
            value,
            hosts=frozenset({"upload.wikimedia.org"}),
            path_prefix="/",
        )

    @field_validator("license_url")
    @classmethod
    def reviewed_license_url(cls, value: str) -> str:
        return _require_url(
            value,
            hosts=frozenset(
                {
                    "creativecommons.org",
                    "www.creativecommons.org",
                    "commons.wikimedia.org",
                }
            ),
            path_prefix="/",
        )


class NormalizedVisualReferenceMember(FrozenModel):
    member_path: Literal["references/primary.png"] = "references/primary.png"
    schema_ref: Literal["eom://schemas/image-provider/normalized-visual-reference/1.0"] = (
        "eom://schemas/image-provider/normalized-visual-reference/1.0"
    )
    media_type: Literal["image/png"] = "image/png"
    width_px: Literal[800] = 800
    height_px: Literal[504] = 504
    mode: Literal["RGB"] = "RGB"
    size_bytes: int = Field(ge=1, le=8 * 1024 * 1024)
    sha256: Sha256


class LocalImageVisualReferenceBundle(FrozenModel):
    schema_version: Literal["local-image-visual-reference-bundle/1.0"] = (
        "local-image-visual-reference-bundle/1.0"
    )
    bundle_id: str = Field(pattern=r"^imgrefbundle_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^imgrefbundlerev_[0-9a-f]{32}$")
    state: Literal["APPROVED"] = "APPROVED"
    intent: VisualReferenceIntentArtifactPointer
    subject: EnglishSubject
    provider_api_revision: Literal["wikimedia-commons-api/1.0"] = "wikimedia-commons-api/1.0"
    observed_at: datetime
    sources: tuple[VisualReferenceSource, ...] = Field(min_length=1, max_length=5)
    primary_reference_id: str = Field(pattern=r"^imgref_[0-9a-f]{32}$")
    normalization_policy: Literal["reference-raster-normalization/1.0"] = (
        "reference-raster-normalization/1.0"
    )
    normalized_member: NormalizedVisualReferenceMember
    bundle_sha256: Sha256

    @field_validator("subject")
    @classmethod
    def safe_subject(cls, value: str) -> str:
        return _require_safe_text(value)

    @field_validator("observed_at")
    @classmethod
    def utc_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference observation must be UTC")
        return value

    @model_validator(mode="after")
    def canonical_sources_and_hash(self) -> LocalImageVisualReferenceBundle:
        ranks = tuple(source.rank for source in self.sources)
        if ranks != tuple(range(1, len(self.sources) + 1)):
            raise ValueError("visual-reference source ranks must be contiguous")
        for values, label in (
            (tuple(source.reference_id for source in self.sources), "reference IDs"),
            (tuple(source.page_id for source in self.sources), "page IDs"),
            (tuple(source.canonical_page_url for source in self.sources), "page URLs"),
            (tuple(source.original_file_url for source in self.sources), "file URLs"),
            (tuple(source.original_sha256 for source in self.sources), "original hashes"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"visual-reference source {label} must be unique")
        primary = tuple(
            source for source in self.sources if source.disposition == "PRIMARY_CONDITIONING"
        )
        if len(primary) != 1 or primary[0] != self.sources[0]:
            raise ValueError("visual-reference bundle requires the rank-one primary source")
        if self.primary_reference_id != primary[0].reference_id:
            raise ValueError("visual-reference primary ID differs from the primary source")
        expected = content_sha256(self.model_dump(mode="json", exclude={"bundle_sha256"}))
        if self.bundle_sha256 != expected:
            raise ValueError("visual-reference bundle hash mismatch")
        return self


class VisualReferenceBundleManifestPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["manifests/visual-reference-bundle.json"] = (
        "manifests/visual-reference-bundle.json"
    )
    schema_ref: Literal["eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"] = (
        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0"
    )
    media_type: Literal["application/json"] = "application/json"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)


class VisualReferencePngArtifactPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["references/primary.png"] = "references/primary.png"
    schema_ref: Literal["eom://schemas/image-provider/normalized-visual-reference/1.0"] = (
        "eom://schemas/image-provider/normalized-visual-reference/1.0"
    )
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)


class LocalImageVisualReferencePointer(FrozenModel):
    bundle_id: str = Field(pattern=r"^imgrefbundle_[0-9a-f]{32}$")
    bundle_revision_id: str = Field(pattern=r"^imgrefbundlerev_[0-9a-f]{32}$")
    bundle_manifest: VisualReferenceBundleManifestPointer
    primary_reference_id: str = Field(pattern=r"^imgref_[0-9a-f]{32}$")
    reference_member: VisualReferencePngArtifactPointer

    @model_validator(mode="after")
    def exact_artifact_revision(self) -> LocalImageVisualReferencePointer:
        manifest = self.bundle_manifest
        member = self.reference_member
        if (
            manifest.artifact_id != member.artifact_id
            or manifest.artifact_revision_id != member.artifact_revision_id
        ):
            raise ValueError("visual-reference members must share one Artifact Revision")
        return self


class LocalImageReferenceConditioning(FrozenModel):
    contract: Literal["sdxl-img2img/1.0"] = "sdxl-img2img/1.0"
    strength: float = Field(default=0.35, ge=0.35, le=0.35)
    fit_policy: Literal["CONTAIN_WHITE_NO_UPSCALE"] = "CONTAIN_WHITE_NO_UPSCALE"


class LocalImageReferenceConditionedCompositeRequest(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-request/1.0"] = (
        "local-image-reference-conditioned-composite-request/1.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageReferenceConditioning
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageReferenceConditionedCompositeRequest:
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceipt(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-receipt/1.0"] = (
        "local-image-reference-conditioned-composite-receipt/1.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageReferenceConditioning
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceipt:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned completion precedes image composition")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned receipt hash mismatch")
        return self


def validate_reference_conditioned_receipt(
    request: LocalImageReferenceConditionedCompositeRequest,
    receipt: LocalImageReferenceConditionedCompositeReceipt,
) -> None:
    """Bind a provider receipt to the exact wrapped request and reference pointer."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
    ):
        raise ValueError("reference-conditioned receipt differs from its request")


def safe_visual_reference_member_path(value: str) -> str:
    """Reject paths that cannot be safely materialized beneath one provider workspace."""

    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("visual-reference member path is unsafe")
    return value
