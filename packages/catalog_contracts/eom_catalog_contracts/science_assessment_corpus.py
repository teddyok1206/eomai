"""Contracts for a deduplicated public science-assessment PDF corpus."""

from __future__ import annotations

import unicodedata
from typing import Literal
from urllib.parse import urlsplit

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

SubjectFamily = Literal[
    "CHEMISTRY",
    "EARTH_SCIENCE",
    "GENERAL_SCIENCE",
    "INTEGRATED_SCIENCE",
    "LIFE_SCIENCE",
    "PHYSICS",
]
IssuerType = Literal["EDUCATION_AUTHORITY", "KICE"]
PublicationDisposition = Literal["NEW_INTAKE", "REUSED_EXISTING"]

_ISSUER_TYPES = ("EDUCATION_AUTHORITY", "KICE")
_SUBJECT_FAMILIES = (
    "CHEMISTRY",
    "EARTH_SCIENCE",
    "GENERAL_SCIENCE",
    "INTEGRATED_SCIENCE",
    "LIFE_SCIENCE",
    "PHYSICS",
)


def _require_https_url(value: str, *, host: str | None = None) -> None:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or (host is not None and parts.hostname != host)
    ):
        raise ValueError("corpus URL is not an allowed HTTPS URL")


def _require_canonical_filename(value: str) -> None:
    if (
        value != unicodedata.normalize("NFC", value)
        or value != value.strip()
        or value in {"", ".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("corpus filename is not canonical")


class ScienceAssessmentWebCorpusPlan(FrozenModel):
    schema_version: Literal["science-assessment-web-corpus-plan/1.0"]
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    source_site: Literal["https://legendstudy.com"]
    sitemap_url: Literal["https://legendstudy.com/sitemap.xml"]
    category_urls: tuple[str, ...] = Field(min_length=2, max_length=16)
    allowed_download_hosts: tuple[str, ...] = Field(min_length=1, max_length=16)
    scope: Literal["KICE_AND_EDUCATION_AUTHORITY_SCIENCE_ASSESSMENTS"]
    issuer_types: tuple[IssuerType, ...] = Field(min_length=2, max_length=2)
    subject_families: tuple[SubjectFamily, ...] = Field(min_length=6, max_length=6)
    document_roles: tuple[Literal["PROBLEM_DOCUMENT"], ...] = Field(min_length=1, max_length=1)
    crawl_delay_ms: int = Field(ge=1000, le=60000)
    max_post_pages: int = Field(ge=1, le=5000)
    max_pdf_bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    created_at: UtcDatetime
    plan_sha256: Sha256

    @model_validator(mode="after")
    def canonical_identity(self) -> ScienceAssessmentWebCorpusPlan:
        if (
            self.category_urls != tuple(sorted(set(self.category_urls)))
            or self.allowed_download_hosts != tuple(sorted(set(self.allowed_download_hosts)))
            or self.issuer_types != _ISSUER_TYPES
            or self.subject_families != _SUBJECT_FAMILIES
            or self.document_roles != ("PROBLEM_DOCUMENT",)
        ):
            raise ValueError("corpus plan collections are not canonical")
        for value in self.category_urls:
            _require_https_url(value, host="legendstudy.com")
            if not urlsplit(value).path.startswith("/category/"):
                raise ValueError("corpus category URL is outside the category boundary")
        for value in self.allowed_download_hosts:
            if value != value.casefold() or value.startswith(".") or value.endswith("."):
                raise ValueError("corpus download host is not canonical")
        identity_sha256 = content_sha256(
            self.model_dump(mode="json", exclude={"plan_id", "created_at", "plan_sha256"})
        )
        if self.plan_id != "sciencecorpusplan_" + identity_sha256.removeprefix("sha256:")[:32]:
            raise ValueError("corpus plan ID does not bind its immutable policy")
        if self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("corpus plan hash differs")
        return self


class ScienceAssessmentCorpusOrigin(FrozenModel):
    post_url: str = Field(min_length=8, max_length=4096)
    download_url: str = Field(min_length=8, max_length=4096)
    resolved_url: str = Field(min_length=8, max_length=4096)
    link_text: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def safe_urls(self) -> ScienceAssessmentCorpusOrigin:
        _require_https_url(self.post_url, host="legendstudy.com")
        _require_https_url(self.download_url)
        _require_https_url(self.resolved_url)
        if self.link_text != unicodedata.normalize("NFC", self.link_text):
            raise ValueError("corpus link text is not NFC")
        return self


class ScienceAssessmentCorpusSourcePointer(FrozenModel):
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    source_file_id: str = Field(pattern=r"^source_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(pattern=r"^source/[0-9a-f]{64}\.pdf$", max_length=80)
    sha256: Sha256

    @model_validator(mode="after")
    def exact_member(self) -> ScienceAssessmentCorpusSourcePointer:
        if self.member_path != f"source/{self.sha256.removeprefix('sha256:')}.pdf":
            raise ValueError("corpus source member does not bind its content hash")
        return self


class ScienceAssessmentCorpusDocument(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    sha256: Sha256
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)
    original_filename: str = Field(min_length=1, max_length=300)
    media_type: Literal["application/pdf"]
    document_role: Literal["PROBLEM_DOCUMENT"]
    subject_family: SubjectFamily
    subject_label: str = Field(min_length=1, max_length=128)
    issuer_type: IssuerType
    administration_year: int = Field(ge=1994, le=2200)
    grade: int = Field(ge=1, le=3)
    session_label: str = Field(min_length=1, max_length=128)
    publication_disposition: PublicationDisposition
    origins: tuple[ScienceAssessmentCorpusOrigin, ...] = Field(min_length=1, max_length=32)
    source: ScienceAssessmentCorpusSourcePointer

    @model_validator(mode="after")
    def canonical_document(self) -> ScienceAssessmentCorpusDocument:
        _require_canonical_filename(self.original_filename)
        if (
            self.document_id != "sciencedoc_" + self.sha256.removeprefix("sha256:")[:32]
            or self.source.sha256 != self.sha256
        ):
            raise ValueError("corpus document identity does not bind its bytes")
        origin_keys = tuple(
            (value.post_url, value.download_url, value.resolved_url, value.link_text)
            for value in self.origins
        )
        if origin_keys != tuple(sorted(set(origin_keys))):
            raise ValueError("corpus origins must be sorted and unique")
        return self


class ScienceAssessmentCorpusIntakeShard(FrozenModel):
    ordinal: int = Field(ge=1, le=64)
    intake_batch_id: str = Field(pattern=r"^intake_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_fingerprint: Sha256
    document_count: int = Field(ge=1, le=499)


class ScienceAssessmentCorpusSummary(FrozenModel):
    unique_document_count: int = Field(ge=1, le=5000)
    duplicate_observation_count: int = Field(ge=0)
    reused_existing_count: int = Field(ge=0)
    new_intake_count: int = Field(ge=0)
    total_bytes: int = Field(ge=1024)


class ScienceAssessmentCorpusPdfValidator(FrozenModel):
    qpdf_path: Literal["/usr/bin/qpdf"]
    qpdf_sha256: Sha256
    pdfinfo_path: Literal["/usr/bin/pdfinfo"]
    pdfinfo_sha256: Sha256


class ScienceAssessmentWebCorpusManifest(FrozenModel):
    schema_version: Literal["science-assessment-web-corpus-manifest/1.0"]
    corpus_id: str = Field(pattern=r"^sciencecorpus_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    observed_at: UtcDatetime
    pdf_validator: ScienceAssessmentCorpusPdfValidator
    documents: tuple[ScienceAssessmentCorpusDocument, ...] = Field(min_length=1, max_length=5000)
    intake_shards: tuple[ScienceAssessmentCorpusIntakeShard, ...] = Field(
        min_length=1, max_length=64
    )
    summary: ScienceAssessmentCorpusSummary
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def canonical_manifest(self) -> ScienceAssessmentWebCorpusManifest:
        document_hashes = tuple(value.sha256 for value in self.documents)
        if document_hashes != tuple(sorted(set(document_hashes))):
            raise ValueError("corpus documents must be sorted and content-unique")
        shard_ordinals = tuple(value.ordinal for value in self.intake_shards)
        if shard_ordinals != tuple(range(1, len(self.intake_shards) + 1)):
            raise ValueError("corpus intake shards must be consecutive and sorted")
        shard_ids = tuple(value.intake_batch_id for value in self.intake_shards)
        if len(shard_ids) != len(set(shard_ids)):
            raise ValueError("corpus intake shards must be unique")
        by_batch = {value.intake_batch_id: value for value in self.intake_shards}
        new_counts: dict[str, int] = {}
        pointer_ids: set[str] = set()
        for document in self.documents:
            if document.source.source_file_id in pointer_ids:
                raise ValueError("corpus source pointer is duplicated")
            pointer_ids.add(document.source.source_file_id)
            shard = by_batch.get(document.source.intake_batch_id)
            if document.publication_disposition == "NEW_INTAKE":
                if (
                    shard is None
                    or shard.artifact_id != document.source.artifact_id
                    or shard.artifact_revision_id != document.source.artifact_revision_id
                ):
                    raise ValueError("new corpus source is absent from its intake shard")
                new_counts[document.source.intake_batch_id] = (
                    new_counts.get(document.source.intake_batch_id, 0) + 1
                )
            elif shard is not None:
                raise ValueError("reused corpus source points into a newly created shard")
        if any(
            new_counts.get(value.intake_batch_id, 0) != value.document_count
            for value in self.intake_shards
        ):
            raise ValueError("corpus intake shard count differs from its documents")
        origin_count = sum(len(value.origins) for value in self.documents)
        reused = sum(value.publication_disposition == "REUSED_EXISTING" for value in self.documents)
        new = len(self.documents) - reused
        if (
            self.summary.unique_document_count != len(self.documents)
            or self.summary.duplicate_observation_count != origin_count - len(self.documents)
            or self.summary.reused_existing_count != reused
            or self.summary.new_intake_count != new
            or self.summary.total_bytes != sum(value.bytes for value in self.documents)
        ):
            raise ValueError("corpus summary differs from its documents")
        identity_sha256 = content_sha256(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "plan_sha256": self.plan_sha256,
                "document_sha256s": list(document_hashes),
            }
        )
        if self.corpus_id != "sciencecorpus_" + identity_sha256.removeprefix("sha256:")[:32]:
            raise ValueError("corpus ID does not bind its document set")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("corpus manifest hash differs")
        return self


def validate_science_corpus_manifest_against_plan(
    manifest: ScienceAssessmentWebCorpusManifest,
    plan: ScienceAssessmentWebCorpusPlan,
) -> None:
    """Validate network provenance against the exact immutable acquisition plan."""

    if manifest.plan_id != plan.plan_id or manifest.plan_sha256 != plan.plan_sha256:
        raise ValueError("corpus manifest references another acquisition plan")
    allowed_hosts = set(plan.allowed_download_hosts)
    for document in manifest.documents:
        if (
            document.subject_family not in plan.subject_families
            or document.issuer_type not in plan.issuer_types
            or document.document_role not in plan.document_roles
            or document.bytes > plan.max_pdf_bytes
        ):
            raise ValueError("corpus document is outside the plan scope")
        for origin in document.origins:
            if (
                urlsplit(origin.post_url).hostname != "legendstudy.com"
                or urlsplit(origin.download_url).hostname not in allowed_hosts
                or urlsplit(origin.resolved_url).hostname not in allowed_hosts
            ):
                raise ValueError("corpus origin host is outside the plan allowlist")
