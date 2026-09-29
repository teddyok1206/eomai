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
    LocalImageModelPointer,
    SamplerContract,
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


class LocalImageVisualReferenceDiscoveryCommand(FrozenModel):
    schema_version: Literal["local-image-visual-reference-discovery-command/1.0"] = (
        "local-image-visual-reference-discovery-command/1.0"
    )
    command_id: str = Field(pattern=r"^imgrefdiscover_[0-9a-f]{32}$")
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
    candidate_limit: Literal[5] = 5
    observed_at: datetime
    timeout_seconds: int = Field(ge=30, le=180)
    command_sha256: Sha256

    @field_validator("subject")
    @classmethod
    def safe_subject(cls, value: str) -> str:
        return _require_safe_text(value)

    @field_validator("query_terms")
    @classmethod
    def safe_query_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_require_safe_text(value) for value in values)

    @field_validator("observed_at")
    @classmethod
    def utc_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference discovery observation must be UTC")
        return value

    @model_validator(mode="after")
    def exact_identity_and_hash(self) -> LocalImageVisualReferenceDiscoveryCommand:
        if self.query_terms != tuple(sorted(set(self.query_terms))):
            raise ValueError("visual-reference discovery query terms must be sorted and unique")
        body = self.model_dump(mode="json", exclude={"command_id", "command_sha256"})
        identity = content_sha256(body).removeprefix("sha256:")
        if self.command_id != "imgrefdiscover_" + identity[:32]:
            raise ValueError("visual-reference discovery command ID mismatch")
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("visual-reference discovery command hash mismatch")
        return self


class LocalImageVisualReferenceDiscoveryResult(FrozenModel):
    schema_version: Literal["local-image-visual-reference-discovery-result/1.0"] = (
        "local-image-visual-reference-discovery-result/1.0"
    )
    command_id: str = Field(pattern=r"^imgrefdiscover_[0-9a-f]{32}$")
    command_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    candidates: tuple[VisualReferenceIntentCandidate, ...] = Field(max_length=5)
    error_code: (
        Literal[
            "VISUAL_REFERENCE_INPUT_INVALID",
            "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
            "VISUAL_REFERENCE_SOURCE_REJECTED",
            "VISUAL_REFERENCE_LICENSE_REJECTED",
        ]
        | None
    )
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=180_000)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference discovery timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def coherent_result(self) -> LocalImageVisualReferenceDiscoveryResult:
        if self.completed_at < self.started_at:
            raise ValueError("visual-reference discovery completion precedes start")
        if self.status == "SUCCEEDED":
            if not self.candidates or self.error_code is not None:
                raise ValueError("successful visual-reference discovery is incomplete")
            ranks = tuple(value.rank for value in self.candidates)
            if ranks != tuple(range(1, len(self.candidates) + 1)):
                raise ValueError("visual-reference discovery ranks must be contiguous")
            for values, label in (
                (tuple(value.page_id for value in self.candidates), "page IDs"),
                (tuple(value.file_title for value in self.candidates), "file titles"),
                (
                    tuple(value.canonical_page_url for value in self.candidates),
                    "page URLs",
                ),
            ):
                if len(values) != len(set(values)):
                    raise ValueError(f"visual-reference discovery {label} must be unique")
        elif self.candidates or self.error_code is None:
            raise ValueError("failed visual-reference discovery has invalid outputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("visual-reference discovery result hash mismatch")
        return self


def validate_visual_reference_discovery(
    command: LocalImageVisualReferenceDiscoveryCommand,
    result: LocalImageVisualReferenceDiscoveryResult,
) -> None:
    if result.command_id != command.command_id or result.command_sha256 != command.command_sha256:
        raise ValueError("visual-reference discovery result differs from its command")
    if result.status == "SUCCEEDED" and len(result.candidates) > command.candidate_limit:
        raise ValueError("visual-reference discovery exceeds its candidate limit")


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

    @model_validator(mode="after")
    def bounded_pixel_population(self) -> VisualReferenceSource:
        # Width and height are independently bounded by JSON Schema.  Their product is
        # the actual decompression risk and therefore belongs in the semantic model.
        if self.original_width_px * self.original_height_px > 40_000_000:
            raise ValueError("visual-reference source exceeds the reviewed pixel bound")
        return self


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


class LocalImageVisualReferenceAcquisitionCommand(FrozenModel):
    schema_version: Literal["local-image-visual-reference-acquisition-command/1.0"] = (
        "local-image-visual-reference-acquisition-command/1.0"
    )
    command_id: str = Field(pattern=r"^imgrefcmd_[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^imgrefattempt_[0-9a-f]{32}$")
    intent: VisualReferenceIntentArtifactPointer
    intent_member_path: Literal["input/visual-reference-intent.json"] = (
        "input/visual-reference-intent.json"
    )
    observed_at: datetime
    max_original_bytes: Literal[16_777_216] = 16_777_216
    timeout_seconds: int = Field(ge=30, le=180)
    command_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def utc_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference acquisition timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageVisualReferenceAcquisitionCommand:
        expected = content_sha256(self.model_dump(mode="json", exclude={"command_sha256"}))
        if self.command_sha256 != expected:
            raise ValueError("visual-reference acquisition command hash mismatch")
        return self


class VisualReferenceAcquisitionOutputFile(FrozenModel):
    member_path: Literal[
        "manifests/visual-reference-bundle.json",
        "references/primary.png",
    ]
    schema_ref: Literal[
        "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0",
        "eom://schemas/image-provider/normalized-visual-reference/1.0",
    ]
    media_type: Literal["application/json", "image/png"]
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    sha256: Sha256

    @model_validator(mode="after")
    def exact_member_contract(self) -> VisualReferenceAcquisitionOutputFile:
        expected = {
            "manifests/visual-reference-bundle.json": (
                "eom://schemas/image-provider/local-image-visual-reference-bundle/1.0",
                "application/json",
            ),
            "references/primary.png": (
                "eom://schemas/image-provider/normalized-visual-reference/1.0",
                "image/png",
            ),
        }[self.member_path]
        if (self.schema_ref, self.media_type) != expected:
            raise ValueError("visual-reference acquisition output contract mismatch")
        return self


VisualReferenceAcquisitionErrorCode = Literal[
    "VISUAL_REFERENCE_INPUT_INVALID",
    "VISUAL_REFERENCE_SOURCE_UNAVAILABLE",
    "VISUAL_REFERENCE_SOURCE_REJECTED",
    "VISUAL_REFERENCE_LICENSE_REJECTED",
    "VISUAL_REFERENCE_IMAGE_INVALID",
    "VISUAL_REFERENCE_OUTPUT_INVALID",
]


class LocalImageVisualReferenceAcquisitionResult(FrozenModel):
    schema_version: Literal["local-image-visual-reference-acquisition-result/1.0"] = (
        "local-image-visual-reference-acquisition-result/1.0"
    )
    command_id: str = Field(pattern=r"^imgrefcmd_[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^imgrefattempt_[0-9a-f]{32}$")
    command_sha256: Sha256
    status: Literal["SUCCEEDED", "FAILED"]
    bundle: LocalImageVisualReferenceBundle | None
    output_files: tuple[VisualReferenceAcquisitionOutputFile, ...] = Field(max_length=2)
    error_code: VisualReferenceAcquisitionErrorCode | None
    started_at: datetime
    completed_at: datetime
    duration_ms: int = Field(ge=1, le=180_000)
    result_sha256: Sha256

    @field_validator("started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference acquisition timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def exact_status_outputs_and_hash(self) -> LocalImageVisualReferenceAcquisitionResult:
        if self.completed_at < self.started_at:
            raise ValueError("visual-reference acquisition completion precedes start")
        paths = tuple(output.member_path for output in self.output_files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("visual-reference acquisition output files must be sorted and unique")
        if self.status == "SUCCEEDED":
            if (
                self.bundle is None
                or self.error_code is not None
                or paths
                != (
                    "manifests/visual-reference-bundle.json",
                    "references/primary.png",
                )
            ):
                raise ValueError("successful visual-reference acquisition is incomplete")
            primary_file = self.output_files[1]
            if (
                primary_file.sha256 != self.bundle.normalized_member.sha256
                or primary_file.size_bytes != self.bundle.normalized_member.size_bytes
            ):
                raise ValueError("visual-reference primary output differs from the bundle")
        elif self.bundle is not None or self.output_files or self.error_code is None:
            raise ValueError("failed visual-reference acquisition has invalid outputs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
        if self.result_sha256 != expected:
            raise ValueError("visual-reference acquisition result hash mismatch")
        return self


def validate_visual_reference_acquisition(
    command: LocalImageVisualReferenceAcquisitionCommand,
    intent: LocalImageVisualReferenceIntent,
    result: LocalImageVisualReferenceAcquisitionResult,
) -> None:
    """Bind an acquisition result to its staged intent and exact candidate population."""

    if (
        result.command_id != command.command_id
        or result.attempt_id != command.attempt_id
        or result.command_sha256 != command.command_sha256
    ):
        raise ValueError("visual-reference acquisition result differs from its command")
    if result.status == "FAILED":
        return
    bundle = result.bundle
    assert bundle is not None
    if bundle.intent != command.intent or bundle.subject != intent.subject:
        raise ValueError("visual-reference bundle differs from its intent")
    if bundle.observed_at != command.observed_at:
        raise ValueError("visual-reference bundle observation differs from its command")
    if len(bundle.sources) != len(intent.candidates):
        raise ValueError("visual-reference bundle candidate coverage differs")
    for candidate, source in zip(intent.candidates, bundle.sources, strict=True):
        if (
            candidate.rank != source.rank
            or candidate.page_id != source.page_id
            or candidate.file_title != source.file_title
            or candidate.canonical_page_url != source.canonical_page_url
        ):
            raise ValueError("visual-reference verified source differs from its candidate")
    primary = bundle.sources[0]
    if primary.page_id != intent.primary_candidate_page_id:
        raise ValueError("visual-reference acquired primary differs from its intent")


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


class VisualReferenceImageResultArtifactPointer(FrozenModel):
    logical_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    content_hash: Sha256
    result_schema: Literal["image-result@12.0"] = "image-result@12.0"


class VisualReferencePublicationEntry(FrozenModel):
    visual_ordinal: int = Field(ge=0, le=1)
    drawing_sha256: Sha256
    subject_sha256: Sha256
    discovery_command_sha256: Sha256
    discovery_result_sha256: Sha256
    intent_sha256: Sha256
    acquisition_command_sha256: Sha256
    acquisition_result_sha256: Sha256
    visual_reference: LocalImageVisualReferencePointer


class LocalImageVisualReferencePublicationReceipt(FrozenModel):
    schema_version: Literal["local-image-visual-reference-publication-receipt/1.0"] = (
        "local-image-visual-reference-publication-receipt/1.0"
    )
    image_result_artifact: VisualReferenceImageResultArtifactPointer
    entries: tuple[VisualReferencePublicationEntry, ...] = Field(min_length=1, max_length=2)
    published_at: datetime
    receipt_sha256: Sha256

    @field_validator("published_at")
    @classmethod
    def utc_publication(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("visual-reference publication must be UTC")
        return value

    @model_validator(mode="after")
    def exact_order_uniqueness_and_hash(self) -> LocalImageVisualReferencePublicationReceipt:
        ordinals = tuple(value.visual_ordinal for value in self.entries)
        if ordinals != tuple(sorted(set(ordinals))):
            raise ValueError("visual-reference publication ordinals must be sorted and unique")
        for values, label in (
            (tuple(value.drawing_sha256 for value in self.entries), "drawing hashes"),
            (
                tuple(value.visual_reference.bundle_revision_id for value in self.entries),
                "bundle revisions",
            ),
            (
                tuple(value.visual_reference.primary_reference_id for value in self.entries),
                "reference IDs",
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"visual-reference publication {label} must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("visual-reference publication receipt hash mismatch")
        return self


class LocalImageReferenceConditioning(FrozenModel):
    contract: Literal["sdxl-img2img/1.0"] = "sdxl-img2img/1.0"
    strength: float = Field(default=0.35, ge=0.35, le=0.35)
    fit_policy: Literal["CONTAIN_WHITE_NO_UPSCALE"] = "CONTAIN_WHITE_NO_UPSCALE"


class ProductionStyleAdapterSourceManifestPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["manifests/adapter-manifest.json"] = "manifests/adapter-manifest.json"
    schema_ref: Literal[
        "eom://schemas/image-provider/local-image-science-campaign-lora-micro-adapter-manifest/1.1"
    ] = "eom://schemas/image-provider/local-image-science-campaign-lora-micro-adapter-manifest/1.1"
    media_type: Literal["application/json"] = "application/json"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)


class ProductionStyleAdapterEvaluationPointer(FrozenModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: Literal["result.json"] = "result.json"
    schema_ref: Literal[
        "eom://schemas/image-provider/local-image-science-campaign-lora-micro-evaluation-result/1.1"
    ] = "eom://schemas/image-provider/local-image-science-campaign-lora-micro-evaluation-result/1.1"
    media_type: Literal["application/json"] = "application/json"
    sha256: Sha256
    size_bytes: int = Field(ge=1, le=16 * 1024 * 1024)


class ProductionStyleAdapterFile(FrozenModel):
    relative_path: Literal["adapter_config.json", "adapter_model.safetensors"]
    size_bytes: int = Field(ge=1, le=1024 * 1024 * 1024)
    sha256: Sha256


class LocalImageProductionStyleAdapterRelease(FrozenModel):
    """Human-approved immutable promotion of one evaluated style-only adapter."""

    schema_version: Literal["local-image-style-adapter-release/1.0"] = (
        "local-image-style-adapter-release/1.0"
    )
    release_id: str = Field(pattern=r"^imgstylerelease_[0-9a-f]{32}$")
    release_revision_id: str = Field(pattern=r"^imgstylereleaserev_[0-9a-f]{32}$")
    state: Literal["RELEASED"] = "RELEASED"
    adapter_contract: Literal["eom-assessment-style-lora/1.0"] = "eom-assessment-style-lora/1.0"
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    base_model: LocalImageModelPointer
    source_adapter_manifest: ProductionStyleAdapterSourceManifestPointer
    evaluation_result: ProductionStyleAdapterEvaluationPointer
    files: tuple[ProductionStyleAdapterFile, ...] = Field(min_length=2, max_length=2)
    lora_scale: float = Field(default=0.8, ge=0.8, le=0.8)
    approved_at: datetime
    approved_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    release_sha256: Sha256

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("style-adapter approval must be UTC")
        return value

    @model_validator(mode="after")
    def exact_files_and_hash(self) -> LocalImageProductionStyleAdapterRelease:
        if tuple(value.relative_path for value in self.files) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise ValueError("style-adapter files must be exact and ordered")
        if len({value.sha256 for value in self.files}) != 2:
            raise ValueError("style-adapter file hashes must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"release_sha256"}))
        if self.release_sha256 != expected:
            raise ValueError("style-adapter release hash mismatch")
        return self


class LocalImageProductionStyleAdapterReleaseV2(FrozenModel):
    """Same immutable adapter bytes with the reviewed reduced inference scale."""

    schema_version: Literal["local-image-style-adapter-release/2.0"] = (
        "local-image-style-adapter-release/2.0"
    )
    release_id: str = Field(pattern=r"^imgstylerelease_[0-9a-f]{32}$")
    release_revision_id: str = Field(pattern=r"^imgstylereleaserev_[0-9a-f]{32}$")
    state: Literal["RELEASED"] = "RELEASED"
    adapter_contract: Literal["eom-assessment-style-lora/1.0"] = "eom-assessment-style-lora/1.0"
    adapter_id: str = Field(pattern=r"^imgadapter_[0-9a-f]{32}$")
    adapter_revision_id: str = Field(pattern=r"^imgadapterrev_[0-9a-f]{32}$")
    base_model: LocalImageModelPointer
    source_adapter_manifest: ProductionStyleAdapterSourceManifestPointer
    evaluation_result: ProductionStyleAdapterEvaluationPointer
    files: tuple[ProductionStyleAdapterFile, ...] = Field(min_length=2, max_length=2)
    lora_scale: float = Field(default=0.45, ge=0.45, le=0.45)
    approved_at: datetime
    approved_by: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    release_sha256: Sha256

    @field_validator("approved_at")
    @classmethod
    def utc_approval(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("style-adapter approval must be UTC")
        return value

    @model_validator(mode="after")
    def exact_files_and_hash(self) -> LocalImageProductionStyleAdapterReleaseV2:
        if tuple(value.relative_path for value in self.files) != (
            "adapter_config.json",
            "adapter_model.safetensors",
        ):
            raise ValueError("style-adapter files must be exact and ordered")
        if len({value.sha256 for value in self.files}) != 2:
            raise ValueError("style-adapter file hashes must be unique")
        expected = content_sha256(self.model_dump(mode="json", exclude={"release_sha256"}))
        if self.release_sha256 != expected:
            raise ValueError("style-adapter release hash mismatch")
        return self


class LocalImageVisualReferencePolicy(FrozenModel):
    intent_source: Literal["DRAWING_ALT_TEXT"] = "DRAWING_ALT_TEXT"
    provider: Literal["WIKIMEDIA_COMMONS"] = "WIKIMEDIA_COMMONS"
    license_policy: Literal["PUBLIC_DOMAIN_OR_CC0"] = "PUBLIC_DOMAIN_OR_CC0"
    candidate_limit: Literal[5] = 5
    conditioning_contract: Literal["sdxl-img2img/1.0"] = "sdxl-img2img/1.0"
    conditioning_strength: float = Field(default=0.35, ge=0.35, le=0.35)
    failure_policy: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"


class LocalImageReferenceSimplification(FrozenModel):
    contract: Literal["local-image-reference-simplification/1.1"] = (
        "local-image-reference-simplification/1.1"
    )
    output_member: Literal["reference-conditioning.png"] = "reference-conditioning.png"
    color_policy: Literal["GRAYSCALE_WHITE_BACKGROUND"] = "GRAYSCALE_WHITE_BACKGROUND"
    denoise_policy: Literal["MAX_5_MEDIAN_7_GAUSSIAN_2_0"] = "MAX_5_MEDIAN_7_GAUSSIAN_2_0"
    tone_policy: Literal["SIX_LEVEL_LIGHT_TONE_CONTOUR"] = "SIX_LEVEL_LIGHT_TONE_CONTOUR"
    foreground_luma_threshold: Literal[245] = 245
    border_width_px: Literal[24] = 24
    foreground_ratio_min: float = Field(default=0.005, ge=0.005, le=0.005)
    foreground_ratio_max: float = Field(default=0.8, ge=0.8, le=0.8)
    border_foreground_ratio_max: float = Field(default=0.12, ge=0.12, le=0.12)


class LocalImageReferenceSimplificationV2(FrozenModel):
    """Adaptive policy that preserves already-clean line art without weakening photo gates."""

    contract: Literal["local-image-reference-simplification/1.2"] = (
        "local-image-reference-simplification/1.2"
    )
    output_member: Literal["reference-conditioning.png"] = "reference-conditioning.png"
    color_policy: Literal["GRAYSCALE_WHITE_BACKGROUND"] = "GRAYSCALE_WHITE_BACKGROUND"
    denoise_policy: Literal["ADAPTIVE_PRESERVE_LINE_ART_OR_REDUCE_PHOTO"] = (
        "ADAPTIVE_PRESERVE_LINE_ART_OR_REDUCE_PHOTO"
    )
    tone_policy: Literal["SIX_LEVEL_LIGHT_TONE_CONTOUR"] = "SIX_LEVEL_LIGHT_TONE_CONTOUR"
    foreground_luma_threshold: Literal[245] = 245
    border_width_px: Literal[24] = 24
    foreground_ratio_min: float = Field(default=0.005, ge=0.005, le=0.005)
    foreground_ratio_max: float = Field(default=0.8, ge=0.8, le=0.8)
    border_foreground_ratio_max: float = Field(default=0.12, ge=0.12, le=0.12)
    line_art_channel_spread_max: Literal[8] = 8
    line_art_near_monochrome_ratio_min: float = Field(default=0.98, ge=0.98, le=0.98)
    line_art_white_background_ratio_min: float = Field(default=0.7, ge=0.7, le=0.7)
    line_art_dark_luma_threshold: Literal[96] = 96
    line_art_dark_foreground_fraction_min: float = Field(default=0.5, ge=0.5, le=0.5)


class LocalImageMorphologyConditioning(FrozenModel):
    contract: Literal["sdxl-morphology-img2img/2.1"] = "sdxl-morphology-img2img/2.1"
    strength: float = Field(default=0.35, ge=0.35, le=0.35)
    fit_policy: Literal["EXACT_NORMALIZED_CANVAS"] = "EXACT_NORMALIZED_CANVAS"
    simplification: LocalImageReferenceSimplification = Field(
        default_factory=LocalImageReferenceSimplification
    )


class LocalImageMorphologyConditioningV2(FrozenModel):
    contract: Literal["sdxl-morphology-img2img/2.2"] = "sdxl-morphology-img2img/2.2"
    strength: float = Field(default=0.35, ge=0.35, le=0.35)
    fit_policy: Literal["EXACT_NORMALIZED_CANVAS"] = "EXACT_NORMALIZED_CANVAS"
    simplification: LocalImageReferenceSimplificationV2 = Field(
        default_factory=LocalImageReferenceSimplificationV2
    )


class LocalImageVisualReferencePolicyV3(FrozenModel):
    intent_source: Literal["DRAWING_ALT_TEXT"] = "DRAWING_ALT_TEXT"
    provider: Literal["WIKIMEDIA_COMMONS"] = "WIKIMEDIA_COMMONS"
    license_policy: Literal["PUBLIC_DOMAIN_OR_CC0"] = "PUBLIC_DOMAIN_OR_CC0"
    candidate_limit: Literal[5] = 5
    conditioning: LocalImageMorphologyConditioningV2 = Field(
        default_factory=LocalImageMorphologyConditioningV2
    )
    authority_boundary: Literal["MORPHOLOGY_ONLY_DETERMINISTIC_OVERLAY"] = (
        "MORPHOLOGY_ONLY_DETERMINISTIC_OVERLAY"
    )
    failure_policy: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"


class LocalImageVisualReferencePolicyV2(FrozenModel):
    intent_source: Literal["DRAWING_ALT_TEXT"] = "DRAWING_ALT_TEXT"
    provider: Literal["WIKIMEDIA_COMMONS"] = "WIKIMEDIA_COMMONS"
    license_policy: Literal["PUBLIC_DOMAIN_OR_CC0"] = "PUBLIC_DOMAIN_OR_CC0"
    candidate_limit: Literal[5] = 5
    conditioning: LocalImageMorphologyConditioning = Field(
        default_factory=LocalImageMorphologyConditioning
    )
    authority_boundary: Literal["MORPHOLOGY_ONLY_DETERMINISTIC_OVERLAY"] = (
        "MORPHOLOGY_ONLY_DETERMINISTIC_OVERLAY"
    )
    failure_policy: Literal["FAIL_CLOSED"] = "FAIL_CLOSED"


class LocalImageAssessmentLineArtPostprocess(FrozenModel):
    """Exact deterministic cleanup applied after local morphology-conditioned inference."""

    contract: Literal["local-image-assessment-line-art-postprocess/1.0"] = (
        "local-image-assessment-line-art-postprocess/1.0"
    )
    raw_member: Literal["generated-background-raw.png"] = "generated-background-raw.png"
    median_filter_size: Literal[3] = 3
    mask_blur_radius: Literal[12] = 12
    mask_luma_threshold: Literal[224] = 224
    mask_expand_size: Literal[25] = 25
    mask_contract_size: Literal[17] = 17
    edge_mid_threshold: Literal[48] = 48
    edge_dark_threshold: Literal[92] = 92
    output_tones: tuple[Literal[48], Literal[160], Literal[255]] = (48, 160, 255)
    horizontal_border_px: Literal[40] = 40
    vertical_border_px: Literal[8] = 8
    foreground_luma_threshold: Literal[245] = 245
    foreground_ratio_min: float = Field(default=0.01, ge=0.01, le=0.01)
    foreground_ratio_max: float = Field(default=0.25, ge=0.25, le=0.25)
    border_foreground_ratio_max: float = Field(default=0.01, ge=0.01, le=0.01)
    edge_density_min: float = Field(default=0.01, ge=0.01, le=0.01)
    edge_density_max: float = Field(default=0.3, ge=0.3, le=0.3)


class LocalImageProviderBindingV2(FrozenModel):
    schema_version: Literal["local-image-provider-binding/2.0"] = "local-image-provider-binding/2.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-reference-conditioned-background/2.0"] = (
        "eom-local-reference-conditioned-background/2.0"
    )
    model: LocalImageModelPointer
    style_adapter: LocalImageProductionStyleAdapterRelease
    reference_policy: LocalImageVisualReferencePolicy
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_model_and_hash(self) -> LocalImageProviderBindingV2:
        if self.style_adapter.base_model != self.model:
            raise ValueError("style-adapter base model differs from provider model")
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider V2 binding hash mismatch")
        return self


class LocalImageProviderBindingV3(FrozenModel):
    schema_version: Literal["local-image-provider-binding/3.0"] = "local-image-provider-binding/3.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-morphology-conditioned-line-art/3.0"] = (
        "eom-local-morphology-conditioned-line-art/3.0"
    )
    model: LocalImageModelPointer
    style_adapter: LocalImageProductionStyleAdapterReleaseV2
    reference_policy: LocalImageVisualReferencePolicyV2
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_model_and_hash(self) -> LocalImageProviderBindingV3:
        if self.style_adapter.base_model != self.model:
            raise ValueError("style-adapter base model differs from provider model")
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider V3 binding hash mismatch")
        return self


class LocalImageProviderBindingV4(FrozenModel):
    """Base-only production binding with pinned reference simplification and monochrome output."""

    schema_version: Literal["local-image-provider-binding/4.0"] = "local-image-provider-binding/4.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-morphology-conditioned-base-line-art/4.0"] = (
        "eom-local-morphology-conditioned-base-line-art/4.0"
    )
    model: LocalImageModelPointer
    reference_policy: LocalImageVisualReferencePolicyV2
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageProviderBindingV4:
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider V4 binding hash mismatch")
        return self


class LocalImageProviderBindingV5(FrozenModel):
    """Base-only production binding with pinned assessment line-art cleanup."""

    schema_version: Literal["local-image-provider-binding/5.0"] = "local-image-provider-binding/5.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-morphology-conditioned-base-line-art/5.0"] = (
        "eom-local-morphology-conditioned-base-line-art/5.0"
    )
    model: LocalImageModelPointer
    reference_policy: LocalImageVisualReferencePolicyV2
    postprocess: LocalImageAssessmentLineArtPostprocess = Field(
        default_factory=LocalImageAssessmentLineArtPostprocess
    )
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageProviderBindingV5:
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider V5 binding hash mismatch")
        return self


class LocalImageProviderBindingV6(FrozenModel):
    """Base-only binding with adaptive reference preservation and retention validation."""

    schema_version: Literal["local-image-provider-binding/6.0"] = "local-image-provider-binding/6.0"
    state: Literal["ENABLED"] = "ENABLED"
    route_contract: Literal["eom-local-morphology-conditioned-base-line-art/6.0"] = (
        "eom-local-morphology-conditioned-base-line-art/6.0"
    )
    model: LocalImageModelPointer
    reference_policy: LocalImageVisualReferencePolicyV3
    postprocess: LocalImageAssessmentLineArtPostprocess = Field(
        default_factory=LocalImageAssessmentLineArtPostprocess
    )
    morphology_retention_ratio_min: float = Field(default=0.25, ge=0.25, le=0.25)
    sampler: SamplerContract
    timeout_seconds: int = Field(ge=30, le=900)
    binding_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageProviderBindingV6:
        expected = content_sha256(self.model_dump(mode="json", exclude={"binding_sha256"}))
        if self.binding_sha256 != expected:
            raise ValueError("local image provider V6 binding hash mismatch")
        return self


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


class LocalImageReferenceConditionedCompositeRequestV2(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-request/2.0"] = (
        "local-image-reference-conditioned-composite-request/2.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageReferenceConditioning
    style_adapter: LocalImageProductionStyleAdapterRelease
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_model_and_hash(self) -> LocalImageReferenceConditionedCompositeRequestV2:
        if self.style_adapter.base_model != self.composite_request.generation.model:
            raise ValueError("conditioned request style-adapter base model differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned V2 request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceiptV2(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-receipt/2.0"] = (
        "local-image-reference-conditioned-composite-receipt/2.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageReferenceConditioning
    style_adapter: LocalImageProductionStyleAdapterRelease
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned V2 completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceiptV2:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned V2 completion precedes image composition")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned V2 receipt hash mismatch")
        return self


class LocalImageReferenceConditioningOutput(FrozenModel):
    member_path: Literal["reference-conditioning.png"] = "reference-conditioning.png"
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    size_bytes: int = Field(ge=64, le=8 * 1024 * 1024)
    width_px: Literal[800] = 800
    height_px: Literal[504] = 504


class LocalImageReferenceSimplificationMetrics(FrozenModel):
    source_foreground_ratio: float = Field(ge=0, le=1)
    conditioning_foreground_ratio: float = Field(ge=0, le=1)
    border_foreground_ratio: float = Field(ge=0, le=1)
    source_edge_density: float = Field(ge=0, le=1)
    conditioning_edge_density: float = Field(ge=0, le=1)
    edge_density_ratio: float = Field(ge=0, le=16)


class LocalImageReferenceSimplificationMetricsV2(LocalImageReferenceSimplificationMetrics):
    selected_mode: Literal["PRESERVE_LINE_ART", "REDUCE_PHOTOGRAPHIC_DETAIL"]
    near_monochrome_ratio: float = Field(ge=0, le=1)
    white_background_ratio: float = Field(ge=0, le=1)
    dark_foreground_fraction: float = Field(ge=0, le=1)


class LocalImageReferenceSimplifierRuntime(FrozenModel):
    contract: Literal["local-image-reference-simplifier/1.0"] = (
        "local-image-reference-simplifier/1.0"
    )
    pillow_version: str = Field(min_length=1, max_length=64)


class LocalImageAssessmentLineArtMetrics(FrozenModel):
    input_foreground_ratio: float = Field(ge=0, le=1)
    output_foreground_ratio: float = Field(ge=0, le=1)
    output_border_foreground_ratio: float = Field(ge=0, le=1)
    input_edge_density: float = Field(ge=0, le=1)
    output_edge_density: float = Field(ge=0, le=1)


class LocalImageAssessmentLineArtRuntime(FrozenModel):
    contract: Literal["local-image-assessment-line-art-postprocessor/1.0"] = (
        "local-image-assessment-line-art-postprocessor/1.0"
    )
    pillow_version: str = Field(min_length=1, max_length=64)


class LocalImageReferenceConditionedCompositeRequestV3(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-request/3.0"] = (
        "local-image-reference-conditioned-composite-request/3.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    style_adapter: LocalImageProductionStyleAdapterReleaseV2
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_model_and_hash(self) -> LocalImageReferenceConditionedCompositeRequestV3:
        if self.style_adapter.base_model != self.composite_request.generation.model:
            raise ValueError("conditioned request style-adapter base model differs")
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned V3 request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceiptV3(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-receipt/3.0"] = (
        "local-image-reference-conditioned-composite-receipt/3.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    style_adapter: LocalImageProductionStyleAdapterReleaseV2
    conditioning_output: LocalImageReferenceConditioningOutput
    simplification_metrics: LocalImageReferenceSimplificationMetrics
    simplifier_runtime: LocalImageReferenceSimplifierRuntime
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned V3 completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_metrics_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceiptV3:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned V3 completion precedes image composition")
        policy = self.conditioning.simplification
        metrics = self.simplification_metrics
        for ratio in (
            metrics.source_foreground_ratio,
            metrics.conditioning_foreground_ratio,
        ):
            if ratio < policy.foreground_ratio_min or ratio > policy.foreground_ratio_max:
                raise ValueError("reference simplification foreground ratio is outside policy")
        if metrics.border_foreground_ratio > policy.border_foreground_ratio_max:
            raise ValueError("reference simplification border ratio is outside policy")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned V3 receipt hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeRequestV4(FrozenModel):
    """Base-only request that pins the exact morphology simplification policy."""

    schema_version: Literal["local-image-reference-conditioned-composite-request/4.0"] = (
        "local-image-reference-conditioned-composite-request/4.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageReferenceConditionedCompositeRequestV4:
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned V4 request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceiptV4(FrozenModel):
    """Receipt for one simplified base-model generation and deterministic monochrome output."""

    schema_version: Literal["local-image-reference-conditioned-composite-receipt/4.0"] = (
        "local-image-reference-conditioned-composite-receipt/4.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    conditioning_output: LocalImageReferenceConditioningOutput
    simplification_metrics: LocalImageReferenceSimplificationMetrics
    simplifier_runtime: LocalImageReferenceSimplifierRuntime
    output_palette: Literal["ASSESSMENT_GRAYSCALE"] = "ASSESSMENT_GRAYSCALE"
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_metrics_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceiptV4:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned V4 completion precedes image composition")
        policy = self.conditioning.simplification
        metrics = self.simplification_metrics
        if metrics.source_foreground_ratio < policy.foreground_ratio_min:
            raise ValueError("reference source foreground ratio is below policy minimum")
        if (
            metrics.conditioning_foreground_ratio < policy.foreground_ratio_min
            or metrics.conditioning_foreground_ratio > policy.foreground_ratio_max
        ):
            raise ValueError("reference conditioning foreground ratio is outside policy")
        if metrics.border_foreground_ratio > policy.border_foreground_ratio_max:
            raise ValueError("reference simplification border ratio is outside policy")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned V4 receipt hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeRequestV5(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-request/5.0"] = (
        "local-image-reference-conditioned-composite-request/5.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    postprocess: LocalImageAssessmentLineArtPostprocess
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageReferenceConditionedCompositeRequestV5:
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned V5 request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceiptV5(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-receipt/5.0"] = (
        "local-image-reference-conditioned-composite-receipt/5.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioning
    conditioning_output: LocalImageReferenceConditioningOutput
    simplification_metrics: LocalImageReferenceSimplificationMetrics
    simplifier_runtime: LocalImageReferenceSimplifierRuntime
    postprocess: LocalImageAssessmentLineArtPostprocess
    postprocess_metrics: LocalImageAssessmentLineArtMetrics
    postprocessor_runtime: LocalImageAssessmentLineArtRuntime
    output_palette: Literal["ASSESSMENT_LINE_ART"] = "ASSESSMENT_LINE_ART"
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned V5 completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_metrics_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceiptV5:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned V5 completion precedes image composition")
        simplification = self.conditioning.simplification
        simplified = self.simplification_metrics
        if simplified.source_foreground_ratio < simplification.foreground_ratio_min:
            raise ValueError("reference source foreground ratio is below policy minimum")
        if not (
            simplification.foreground_ratio_min
            <= simplified.conditioning_foreground_ratio
            <= simplification.foreground_ratio_max
        ):
            raise ValueError("reference conditioning foreground ratio is outside policy")
        if simplified.border_foreground_ratio > simplification.border_foreground_ratio_max:
            raise ValueError("reference simplification border ratio is outside policy")
        metrics = self.postprocess_metrics
        if not (
            self.postprocess.foreground_ratio_min
            <= metrics.output_foreground_ratio
            <= self.postprocess.foreground_ratio_max
        ):
            raise ValueError("assessment line-art foreground ratio is outside policy")
        if metrics.output_border_foreground_ratio > self.postprocess.border_foreground_ratio_max:
            raise ValueError("assessment line-art border ratio is outside policy")
        if not (
            self.postprocess.edge_density_min
            <= metrics.output_edge_density
            <= self.postprocess.edge_density_max
        ):
            raise ValueError("assessment line-art edge density is outside policy")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned V5 receipt hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeRequestV6(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-request/6.0"] = (
        "local-image-reference-conditioned-composite-request/6.0"
    )
    composite_request: LocalImageCompositeRequest
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioningV2
    postprocess: LocalImageAssessmentLineArtPostprocess
    morphology_retention_ratio_min: float = Field(ge=0.25, le=0.25)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_hash(self) -> LocalImageReferenceConditionedCompositeRequestV6:
        expected = content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        if self.request_sha256 != expected:
            raise ValueError("reference-conditioned V6 request hash mismatch")
        return self


class LocalImageReferenceConditionedCompositeReceiptV6(FrozenModel):
    schema_version: Literal["local-image-reference-conditioned-composite-receipt/6.0"] = (
        "local-image-reference-conditioned-composite-receipt/6.0"
    )
    request_sha256: Sha256
    composite_receipt: LocalImageCompositeReceipt
    visual_reference: LocalImageVisualReferencePointer
    conditioning: LocalImageMorphologyConditioningV2
    conditioning_output: LocalImageReferenceConditioningOutput
    simplification_metrics: LocalImageReferenceSimplificationMetricsV2
    simplifier_runtime: LocalImageReferenceSimplifierRuntime
    postprocess: LocalImageAssessmentLineArtPostprocess
    postprocess_metrics: LocalImageAssessmentLineArtMetrics
    postprocessor_runtime: LocalImageAssessmentLineArtRuntime
    morphology_retention_ratio_min: float = Field(ge=0.25, le=0.25)
    output_palette: Literal["ASSESSMENT_LINE_ART"] = "ASSESSMENT_LINE_ART"
    completed_at: datetime
    receipt_sha256: Sha256

    @field_validator("completed_at")
    @classmethod
    def utc_completion(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("reference-conditioned completion must be UTC")
        return value

    @model_validator(mode="after")
    def exact_metrics_hash_and_order(self) -> LocalImageReferenceConditionedCompositeReceiptV6:
        if self.completed_at < self.composite_receipt.completed_at:
            raise ValueError("reference-conditioned V6 completion precedes image composition")
        simplification = self.conditioning.simplification
        simplified = self.simplification_metrics
        if simplified.source_foreground_ratio < simplification.foreground_ratio_min:
            raise ValueError("reference source foreground ratio is below policy minimum")
        if not (
            simplification.foreground_ratio_min
            <= simplified.conditioning_foreground_ratio
            <= simplification.foreground_ratio_max
        ):
            raise ValueError("reference conditioning foreground ratio is outside policy")
        if simplified.border_foreground_ratio > simplification.border_foreground_ratio_max:
            raise ValueError("reference simplification border ratio is outside policy")
        metrics = self.postprocess_metrics
        if not (
            self.postprocess.foreground_ratio_min
            <= metrics.output_foreground_ratio
            <= self.postprocess.foreground_ratio_max
        ):
            raise ValueError("assessment line-art foreground ratio is outside policy")
        if metrics.output_border_foreground_ratio > self.postprocess.border_foreground_ratio_max:
            raise ValueError("assessment line-art border ratio is outside policy")
        if not (
            self.postprocess.edge_density_min
            <= metrics.output_edge_density
            <= self.postprocess.edge_density_max
        ):
            raise ValueError("assessment line-art edge density is outside policy")
        retention = metrics.output_foreground_ratio / simplified.conditioning_foreground_ratio
        if retention < self.morphology_retention_ratio_min:
            raise ValueError("assessment line-art morphology retention is below policy")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("reference-conditioned V6 receipt hash mismatch")
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


def validate_reference_conditioned_receipt_v2(
    request: LocalImageReferenceConditionedCompositeRequestV2,
    receipt: LocalImageReferenceConditionedCompositeReceiptV2,
) -> None:
    """Bind a LoRA-style provider receipt to its exact reference and immutable release."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
        or receipt.style_adapter != request.style_adapter
    ):
        raise ValueError("reference-conditioned V2 receipt differs from its request")


def validate_reference_conditioned_receipt_v3(
    request: LocalImageReferenceConditionedCompositeRequestV3,
    receipt: LocalImageReferenceConditionedCompositeReceiptV3,
) -> None:
    """Bind a simplified-morphology receipt to its exact source, policy, and release."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
        or receipt.style_adapter != request.style_adapter
        or receipt.conditioning_output.member_path
        != request.conditioning.simplification.output_member
    ):
        raise ValueError("reference-conditioned V3 receipt differs from its request")


def validate_reference_conditioned_receipt_v4(
    request: LocalImageReferenceConditionedCompositeRequestV4,
    receipt: LocalImageReferenceConditionedCompositeReceiptV4,
) -> None:
    """Bind a base-only simplified receipt to its exact source and policy."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
        or receipt.conditioning_output.member_path
        != request.conditioning.simplification.output_member
    ):
        raise ValueError("reference-conditioned V4 receipt differs from its request")


def validate_reference_conditioned_receipt_v5(
    request: LocalImageReferenceConditionedCompositeRequestV5,
    receipt: LocalImageReferenceConditionedCompositeReceiptV5,
) -> None:
    """Bind an assessment-line-art receipt to its exact source and policies."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
        or receipt.conditioning_output.member_path
        != request.conditioning.simplification.output_member
        or receipt.postprocess != request.postprocess
    ):
        raise ValueError("reference-conditioned V5 receipt differs from its request")


def validate_reference_conditioned_receipt_v6(
    request: LocalImageReferenceConditionedCompositeRequestV6,
    receipt: LocalImageReferenceConditionedCompositeReceiptV6,
) -> None:
    """Bind an adaptive line-art receipt to its exact source and policies."""

    if (
        receipt.request_sha256 != request.request_sha256
        or receipt.composite_receipt.composite_request_sha256
        != request.composite_request.composite_request_sha256
        or receipt.visual_reference != request.visual_reference
        or receipt.conditioning != request.conditioning
        or receipt.conditioning_output.member_path
        != request.conditioning.simplification.output_member
        or receipt.postprocess != request.postprocess
        or receipt.morphology_retention_ratio_min != request.morphology_retention_ratio_min
    ):
        raise ValueError("reference-conditioned V6 receipt differs from its request")


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
