"""Contracts for a deduplicated public science-assessment PDF corpus."""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath
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
SubjectResolutionRule = Literal[
    "MULTI_SUBJECT_LIST",
    "EXPLICIT_INTEGRATED_SCIENCE",
    "EXPLICIT_SINGLE_SUBJECT",
    "GENERIC_SCIENCE_INQUIRY",
    "ACQUISITION_FALLBACK",
]
IssuerResolutionRule = Literal[
    "EXPLICIT_KICE",
    "EXPLICIT_EDUCATION_AUTHORITY",
    "ACQUISITION_FALLBACK",
]
YearResolutionRule = Literal[
    "EXPLICIT_ADMINISTRATION_YEAR",
    "EXPLICIT_CALENDAR_YEAR",
    "EXPLICIT_ACADEMIC_YEAR",
    "ACQUISITION_FALLBACK",
]
GradeResolutionRule = Literal[
    "KICE_FIXED_GRADE_3",
    "EXPLICIT_GRADE",
    "ACQUISITION_FALLBACK",
]
SessionResolutionRule = Literal[
    "EXPLICIT_KICE_CSAT",
    "EXPLICIT_MONTH",
    "ACQUISITION_FALLBACK",
]

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
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=12, max_length=512)
    sha256: Sha256

    @model_validator(mode="after")
    def exact_member(self) -> ScienceAssessmentCorpusSourcePointer:
        path = PurePosixPath(self.member_path)
        if (
            path.is_absolute()
            or path.parts[0] != "source"
            or len(path.parts) < 2
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in self.member_path
            or not self.member_path.casefold().endswith(".pdf")
            or self.member_path != unicodedata.normalize("NFC", self.member_path)
            or any(ord(character) < 32 or ord(character) == 127 for character in self.member_path)
        ):
            raise ValueError("corpus source member path is unsafe")
        return self


class ScienceAssessmentCorpusDocument(FrozenModel):
    document_id: str = Field(pattern=r"^sciencedoc_[0-9a-f]{32}$")
    sha256: Sha256
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)
    original_filename: str = Field(min_length=1, max_length=255)
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


class ScienceAssessmentCorpusAcquisitionFailure(FrozenModel):
    post_url: str = Field(min_length=8, max_length=4096)
    download_url: str = Field(min_length=8, max_length=4096)
    error_code: str = Field(pattern=r"^SCIENCE_CORPUS_[A-Z0-9_]{1,96}$")

    @model_validator(mode="after")
    def safe_urls(self) -> ScienceAssessmentCorpusAcquisitionFailure:
        _require_https_url(self.post_url, host="legendstudy.com")
        _require_https_url(self.download_url)
        return self


class ScienceAssessmentCorpusSummary(FrozenModel):
    unique_document_count: int = Field(ge=1, le=5000)
    scanned_post_count: int = Field(ge=1, le=5000)
    candidate_count: int = Field(ge=1, le=5000)
    acquisition_failure_count: int = Field(ge=0, le=5000)
    duplicate_observation_count: int = Field(ge=0)
    reused_existing_count: int = Field(ge=0)
    new_intake_count: int = Field(ge=0)
    total_bytes: int = Field(ge=1024)


class ScienceAssessmentCorpusPdfValidator(FrozenModel):
    qpdf_path: Literal["/usr/bin/qpdf"]
    qpdf_sha256: Sha256
    pdfinfo_path: Literal["/usr/bin/pdfinfo"]
    pdfinfo_sha256: Sha256


class ScienceAssessmentAcquisitionCandidate(FrozenModel):
    post_url: str = Field(min_length=8, max_length=4096)
    download_url: str = Field(min_length=8, max_length=4096)
    link_text: str = Field(min_length=1, max_length=512)
    original_filename: str = Field(min_length=1, max_length=255)
    subject_family: SubjectFamily
    subject_label: str = Field(min_length=1, max_length=128)
    issuer_type: IssuerType
    administration_year: int = Field(ge=1994, le=2200)
    grade: int = Field(ge=1, le=3)
    session_label: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def canonical_candidate(self) -> ScienceAssessmentAcquisitionCandidate:
        _require_https_url(self.post_url, host="legendstudy.com")
        _require_https_url(self.download_url)
        _require_canonical_filename(self.original_filename)
        if self.link_text != unicodedata.normalize("NFC", self.link_text):
            raise ValueError("acquisition link text is not NFC")
        return self


class ScienceAssessmentAcquisitionSuccess(ScienceAssessmentAcquisitionCandidate):
    resolved_url: str = Field(min_length=8, max_length=4096)
    member_path: str = Field(pattern=r"^documents/[0-9a-f]{64}\.pdf$")
    sha256: Sha256
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)

    @model_validator(mode="after")
    def exact_member(self) -> ScienceAssessmentAcquisitionSuccess:
        _require_https_url(self.resolved_url)
        if self.member_path != f"documents/{self.sha256.removeprefix('sha256:')}.pdf":
            raise ValueError("acquisition member path differs from its content hash")
        return self


class ScienceAssessmentAcquisitionFailureObservation(ScienceAssessmentAcquisitionCandidate):
    error_code: str = Field(pattern=r"^SCIENCE_CORPUS_[A-Z0-9_]{1,96}$")


class ScienceAssessmentAcquisitionSummary(FrozenModel):
    scanned_post_count: int = Field(ge=1, le=5000)
    candidate_count: int = Field(ge=1, le=5000)
    successful_observation_count: int = Field(ge=1, le=5000)
    failed_observation_count: int = Field(ge=0, le=5000)
    rejected_link_count: int = Field(ge=0)
    unique_pdf_count: int = Field(ge=1, le=5000)
    unique_pdf_bytes: int = Field(ge=1024)


class ScienceAssessmentWebAcquisition(FrozenModel):
    schema_version: Literal["science-assessment-web-acquisition/1.0"]
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    observed_at: UtcDatetime
    pdf_validator: ScienceAssessmentCorpusPdfValidator
    successful_observations: tuple[ScienceAssessmentAcquisitionSuccess, ...] = Field(
        min_length=1, max_length=5000
    )
    failed_observations: tuple[ScienceAssessmentAcquisitionFailureObservation, ...] = Field(
        max_length=5000
    )
    summary: ScienceAssessmentAcquisitionSummary
    acquisition_sha256: Sha256

    @model_validator(mode="after")
    def canonical_acquisition(self) -> ScienceAssessmentWebAcquisition:
        successful_keys = tuple(
            (value.post_url, value.download_url, value.link_text, value.sha256)
            for value in self.successful_observations
        )
        failed_keys = tuple(
            (value.post_url, value.download_url, value.link_text, value.error_code)
            for value in self.failed_observations
        )
        if successful_keys != tuple(sorted(set(successful_keys))):
            raise ValueError("successful acquisition observations are not canonical")
        if failed_keys != tuple(sorted(set(failed_keys))):
            raise ValueError("failed acquisition observations are not canonical")
        by_hash: dict[str, tuple[int, int]] = {}
        for observation in self.successful_observations:
            identity = (observation.bytes, observation.page_count)
            existing = by_hash.setdefault(observation.sha256, identity)
            if existing != identity:
                raise ValueError("acquisition content metadata conflicts")
        if (
            self.summary.successful_observation_count != len(self.successful_observations)
            or self.summary.failed_observation_count != len(self.failed_observations)
            or self.summary.candidate_count
            != len(self.successful_observations) + len(self.failed_observations)
            or self.summary.unique_pdf_count != len(by_hash)
            or self.summary.unique_pdf_bytes != sum(identity[0] for identity in by_hash.values())
        ):
            raise ValueError("acquisition summary differs from its observations")
        if self.acquisition_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"acquisition_sha256"})
        ):
            raise ValueError("acquisition manifest hash differs")
        return self


class ScienceAssessmentMetadataResolutionPolicy(FrozenModel):
    schema_version: Literal["science-assessment-metadata-resolution-policy/1.0"]
    policy_id: str = Field(pattern=r"^sciencecorpuspolicy_[0-9a-f]{32}$")
    algorithm: Literal["EOM_SCIENCE_METADATA_RESOLVER_2026_09_25_A"]
    subject_rules: tuple[SubjectResolutionRule, ...]
    issuer_rules: tuple[IssuerResolutionRule, ...]
    year_rules: tuple[YearResolutionRule, ...]
    grade_rules: tuple[GradeResolutionRule, ...]
    session_rules: tuple[SessionResolutionRule, ...]
    policy_sha256: Sha256

    @model_validator(mode="after")
    def canonical_policy(self) -> ScienceAssessmentMetadataResolutionPolicy:
        expected = {
            "subject_rules": (
                "MULTI_SUBJECT_LIST",
                "EXPLICIT_INTEGRATED_SCIENCE",
                "EXPLICIT_SINGLE_SUBJECT",
                "GENERIC_SCIENCE_INQUIRY",
                "ACQUISITION_FALLBACK",
            ),
            "issuer_rules": (
                "EXPLICIT_KICE",
                "EXPLICIT_EDUCATION_AUTHORITY",
                "ACQUISITION_FALLBACK",
            ),
            "year_rules": (
                "EXPLICIT_ADMINISTRATION_YEAR",
                "EXPLICIT_CALENDAR_YEAR",
                "EXPLICIT_ACADEMIC_YEAR",
                "ACQUISITION_FALLBACK",
            ),
            "grade_rules": (
                "KICE_FIXED_GRADE_3",
                "EXPLICIT_GRADE",
                "ACQUISITION_FALLBACK",
            ),
            "session_rules": (
                "EXPLICIT_KICE_CSAT",
                "EXPLICIT_MONTH",
                "ACQUISITION_FALLBACK",
            ),
        }
        if any(getattr(self, key) != value for key, value in expected.items()):
            raise ValueError("science metadata resolution policy rules differ")
        identity = content_sha256(
            self.model_dump(mode="json", exclude={"policy_id", "policy_sha256"})
        )
        if self.policy_id != "sciencecorpuspolicy_" + identity.removeprefix("sha256:")[:32]:
            raise ValueError("science metadata resolution policy ID differs")
        if self.policy_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"policy_sha256"})
        ):
            raise ValueError("science metadata resolution policy hash differs")
        return self


class ScienceAssessmentResolvedDocumentMetadata(FrozenModel):
    sha256: Sha256
    bytes: int = Field(ge=1024, le=100 * 1024 * 1024)
    page_count: int = Field(ge=1, le=512)
    original_filename: str = Field(min_length=1, max_length=255)
    subject_family: SubjectFamily
    subject_label: str = Field(min_length=1, max_length=128)
    subject_rule: SubjectResolutionRule
    issuer_type: IssuerType
    issuer_rule: IssuerResolutionRule
    administration_year: int = Field(ge=1994, le=2200)
    year_rule: YearResolutionRule
    grade: int = Field(ge=1, le=3)
    grade_rule: GradeResolutionRule
    session_label: str = Field(min_length=1, max_length=128)
    session_rule: SessionResolutionRule
    observation_count: int = Field(ge=1, le=32)
    had_metadata_conflict: bool
    metadata_changed: bool

    @model_validator(mode="after")
    def canonical_metadata(self) -> ScienceAssessmentResolvedDocumentMetadata:
        _require_canonical_filename(self.original_filename)
        return self


class ScienceAssessmentMetadataResolutionSummary(FrozenModel):
    unique_document_count: int = Field(ge=1, le=5000)
    successful_observation_count: int = Field(ge=1, le=5000)
    conflicting_document_count: int = Field(ge=0, le=5000)
    normalized_document_count: int = Field(ge=0, le=5000)


class ScienceAssessmentMetadataResolution(FrozenModel):
    schema_version: Literal["science-assessment-metadata-resolution/1.0"]
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    acquisition_sha256: Sha256
    policy: ScienceAssessmentMetadataResolutionPolicy
    documents: tuple[ScienceAssessmentResolvedDocumentMetadata, ...] = Field(
        min_length=1, max_length=5000
    )
    summary: ScienceAssessmentMetadataResolutionSummary
    resolution_sha256: Sha256

    @model_validator(mode="after")
    def canonical_resolution(self) -> ScienceAssessmentMetadataResolution:
        hashes = tuple(value.sha256 for value in self.documents)
        if hashes != tuple(sorted(set(hashes))):
            raise ValueError("science metadata resolution documents are not canonical")
        if (
            self.summary.unique_document_count != len(self.documents)
            or self.summary.successful_observation_count
            != sum(value.observation_count for value in self.documents)
            or self.summary.conflicting_document_count
            != sum(value.had_metadata_conflict for value in self.documents)
            or self.summary.normalized_document_count
            != sum(value.metadata_changed for value in self.documents)
        ):
            raise ValueError("science metadata resolution summary differs")
        if self.resolution_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"resolution_sha256"})
        ):
            raise ValueError("science metadata resolution hash differs")
        return self


class ScienceAssessmentWebCorpusManifest(FrozenModel):
    schema_version: Literal["science-assessment-web-corpus-manifest/1.0"]
    corpus_id: str = Field(pattern=r"^sciencecorpus_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    acquisition_sha256: Sha256
    observed_at: UtcDatetime
    pdf_validator: ScienceAssessmentCorpusPdfValidator
    documents: tuple[ScienceAssessmentCorpusDocument, ...] = Field(min_length=1, max_length=5000)
    failures: tuple[ScienceAssessmentCorpusAcquisitionFailure, ...] = Field(max_length=5000)
    intake_shards: tuple[ScienceAssessmentCorpusIntakeShard, ...] = Field(max_length=64)
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
        failure_keys = tuple(
            (value.post_url, value.download_url, value.error_code) for value in self.failures
        )
        if failure_keys != tuple(sorted(set(failure_keys))):
            raise ValueError("corpus acquisition failures must be sorted and unique")
        reused = sum(value.publication_disposition == "REUSED_EXISTING" for value in self.documents)
        new = len(self.documents) - reused
        if (
            self.summary.unique_document_count != len(self.documents)
            or self.summary.candidate_count != origin_count + len(self.failures)
            or self.summary.acquisition_failure_count != len(self.failures)
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
                "acquisition_sha256": self.acquisition_sha256,
            }
        )
        if self.corpus_id != "sciencecorpus_" + identity_sha256.removeprefix("sha256:")[:32]:
            raise ValueError("corpus ID does not bind its document set")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("corpus manifest hash differs")
        return self


class ScienceAssessmentWebCorpusManifestV2(FrozenModel):
    schema_version: Literal["science-assessment-web-corpus-manifest/2.0"]
    corpus_id: str = Field(pattern=r"^sciencecorpus_[0-9a-f]{32}$")
    plan_id: str = Field(pattern=r"^sciencecorpusplan_[0-9a-f]{32}$")
    plan_sha256: Sha256
    acquisition_sha256: Sha256
    resolution_sha256: Sha256
    resolution_policy_id: str = Field(pattern=r"^sciencecorpuspolicy_[0-9a-f]{32}$")
    resolution_policy_sha256: Sha256
    observed_at: UtcDatetime
    pdf_validator: ScienceAssessmentCorpusPdfValidator
    documents: tuple[ScienceAssessmentCorpusDocument, ...] = Field(min_length=1, max_length=5000)
    failures: tuple[ScienceAssessmentCorpusAcquisitionFailure, ...] = Field(max_length=5000)
    intake_shards: tuple[ScienceAssessmentCorpusIntakeShard, ...] = Field(max_length=64)
    summary: ScienceAssessmentCorpusSummary
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def canonical_manifest(self) -> ScienceAssessmentWebCorpusManifestV2:
        _validate_corpus_collections(
            documents=self.documents,
            failures=self.failures,
            intake_shards=self.intake_shards,
            summary=self.summary,
        )
        identity_sha256 = content_sha256(
            {
                "schema_version": self.schema_version,
                "plan_id": self.plan_id,
                "plan_sha256": self.plan_sha256,
                "acquisition_sha256": self.acquisition_sha256,
                "resolution_sha256": self.resolution_sha256,
                "resolution_policy_id": self.resolution_policy_id,
                "resolution_policy_sha256": self.resolution_policy_sha256,
            }
        )
        if self.corpus_id != "sciencecorpus_" + identity_sha256.removeprefix("sha256:")[:32]:
            raise ValueError("corpus ID does not bind its resolved document set")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("corpus manifest hash differs")
        return self


def _validate_corpus_collections(
    *,
    documents: tuple[ScienceAssessmentCorpusDocument, ...],
    failures: tuple[ScienceAssessmentCorpusAcquisitionFailure, ...],
    intake_shards: tuple[ScienceAssessmentCorpusIntakeShard, ...],
    summary: ScienceAssessmentCorpusSummary,
) -> None:
    document_hashes = tuple(value.sha256 for value in documents)
    if document_hashes != tuple(sorted(set(document_hashes))):
        raise ValueError("corpus documents must be sorted and content-unique")
    shard_ordinals = tuple(value.ordinal for value in intake_shards)
    if shard_ordinals != tuple(range(1, len(intake_shards) + 1)):
        raise ValueError("corpus intake shards must be consecutive and sorted")
    shard_ids = tuple(value.intake_batch_id for value in intake_shards)
    if len(shard_ids) != len(set(shard_ids)):
        raise ValueError("corpus intake shards must be unique")
    by_batch = {value.intake_batch_id: value for value in intake_shards}
    new_counts: dict[str, int] = {}
    pointer_ids: set[str] = set()
    for document in documents:
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
        new_counts.get(value.intake_batch_id, 0) != value.document_count for value in intake_shards
    ):
        raise ValueError("corpus intake shard count differs from its documents")
    origin_count = sum(len(value.origins) for value in documents)
    failure_keys = tuple(
        (value.post_url, value.download_url, value.error_code) for value in failures
    )
    if failure_keys != tuple(sorted(set(failure_keys))):
        raise ValueError("corpus acquisition failures must be sorted and unique")
    reused = sum(value.publication_disposition == "REUSED_EXISTING" for value in documents)
    new = len(documents) - reused
    if (
        summary.unique_document_count != len(documents)
        or summary.candidate_count != origin_count + len(failures)
        or summary.acquisition_failure_count != len(failures)
        or summary.duplicate_observation_count != origin_count - len(documents)
        or summary.reused_existing_count != reused
        or summary.new_intake_count != new
        or summary.total_bytes != sum(value.bytes for value in documents)
    ):
        raise ValueError("corpus summary differs from its documents")


def validate_science_corpus_manifest_against_acquisition(
    manifest: ScienceAssessmentWebCorpusManifest,
    acquisition: ScienceAssessmentWebAcquisition,
) -> None:
    """Bind the published corpus projection to its exact acquisition checkpoint."""

    if (
        manifest.acquisition_sha256 != acquisition.acquisition_sha256
        or manifest.plan_id != acquisition.plan_id
        or manifest.plan_sha256 != acquisition.plan_sha256
        or manifest.observed_at != acquisition.observed_at
        or manifest.pdf_validator != acquisition.pdf_validator
    ):
        raise ValueError("corpus manifest references another acquisition")
    observations_by_hash: dict[str, list[ScienceAssessmentAcquisitionSuccess]] = {}
    for observation in acquisition.successful_observations:
        observations_by_hash.setdefault(observation.sha256, []).append(observation)
    if {value.sha256 for value in manifest.documents} != set(observations_by_hash):
        raise ValueError("corpus documents differ from the acquisition")
    for document in manifest.documents:
        observations = observations_by_hash[document.sha256]
        first = observations[0]
        identities = {
            (
                value.bytes,
                value.page_count,
                value.subject_family,
                value.issuer_type,
                value.administration_year,
                value.grade,
                value.session_label,
            )
            for value in observations
        }
        expected_origins = tuple(
            sorted(
                {
                    ScienceAssessmentCorpusOrigin(
                        post_url=value.post_url,
                        download_url=value.download_url,
                        resolved_url=value.resolved_url,
                        link_text=value.link_text,
                    )
                    for value in observations
                },
                key=lambda value: (
                    value.post_url,
                    value.download_url,
                    value.resolved_url,
                    value.link_text,
                ),
            )
        )
        if len(identities) != 1 or (
            document.bytes,
            document.page_count,
            document.original_filename,
            document.subject_family,
            document.subject_label,
            document.issuer_type,
            document.administration_year,
            document.grade,
            document.session_label,
            document.origins,
        ) != (
            first.bytes,
            first.page_count,
            min(value.original_filename for value in observations),
            first.subject_family,
            min(value.subject_label for value in observations),
            first.issuer_type,
            first.administration_year,
            first.grade,
            first.session_label,
            expected_origins,
        ):
            raise ValueError("corpus document metadata differs from the acquisition")
    if {(value.post_url, value.download_url, value.error_code) for value in manifest.failures} != {
        (value.post_url, value.download_url, value.error_code)
        for value in acquisition.failed_observations
    }:
        raise ValueError("corpus failures differ from the acquisition")
    if (
        manifest.summary.scanned_post_count != acquisition.summary.scanned_post_count
        or manifest.summary.candidate_count != acquisition.summary.candidate_count
        or manifest.summary.acquisition_failure_count
        != acquisition.summary.failed_observation_count
    ):
        raise ValueError("corpus summary differs from the acquisition")


def validate_science_corpus_manifest_against_plan(
    manifest: ScienceAssessmentWebCorpusManifest,
    plan: ScienceAssessmentWebCorpusPlan,
) -> None:
    """Validate network provenance against the exact immutable acquisition plan."""

    if manifest.plan_id != plan.plan_id or manifest.plan_sha256 != plan.plan_sha256:
        raise ValueError("corpus manifest references another acquisition plan")
    if manifest.summary.scanned_post_count > plan.max_post_pages:
        raise ValueError("corpus manifest exceeds the plan post limit")
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
    for failure in manifest.failures:
        if urlsplit(failure.download_url).hostname not in allowed_hosts:
            raise ValueError("corpus failure host is outside the plan allowlist")


def validate_science_acquisition_against_plan(
    acquisition: ScienceAssessmentWebAcquisition,
    plan: ScienceAssessmentWebCorpusPlan,
) -> None:
    """Validate a local acquisition checkpoint against its immutable network plan."""

    if acquisition.plan_id != plan.plan_id or acquisition.plan_sha256 != plan.plan_sha256:
        raise ValueError("science acquisition references another plan")
    if acquisition.summary.scanned_post_count > plan.max_post_pages:
        raise ValueError("science acquisition exceeds the plan post limit")
    allowed_hosts = set(plan.allowed_download_hosts)
    for observation in (*acquisition.successful_observations, *acquisition.failed_observations):
        if (
            observation.subject_family not in plan.subject_families
            or observation.issuer_type not in plan.issuer_types
            or urlsplit(observation.post_url).hostname != "legendstudy.com"
            or urlsplit(observation.download_url).hostname not in allowed_hosts
        ):
            raise ValueError("science acquisition observation is outside the plan")
        if isinstance(observation, ScienceAssessmentAcquisitionSuccess) and (
            urlsplit(observation.resolved_url).hostname not in allowed_hosts
            or observation.bytes > plan.max_pdf_bytes
        ):
            raise ValueError("science acquisition result is outside the plan")


def validate_science_metadata_resolution_against_acquisition(
    resolution: ScienceAssessmentMetadataResolution,
    acquisition: ScienceAssessmentWebAcquisition,
) -> None:
    """Bind publication metadata to the exact immutable acquisition observation set."""

    if (
        resolution.plan_id != acquisition.plan_id
        or resolution.plan_sha256 != acquisition.plan_sha256
        or resolution.acquisition_sha256 != acquisition.acquisition_sha256
    ):
        raise ValueError("science metadata resolution references another acquisition")
    observations_by_hash: dict[str, list[ScienceAssessmentAcquisitionSuccess]] = {}
    for observation in acquisition.successful_observations:
        observations_by_hash.setdefault(observation.sha256, []).append(observation)
    if {value.sha256 for value in resolution.documents} != set(observations_by_hash):
        raise ValueError("science metadata resolution document set differs")
    for document in resolution.documents:
        observations = observations_by_hash[document.sha256]
        byte_identities = {(value.bytes, value.page_count) for value in observations}
        raw_metadata = {
            (
                value.subject_family,
                value.issuer_type,
                value.administration_year,
                value.grade,
                value.session_label,
            )
            for value in observations
        }
        if (
            byte_identities != {(document.bytes, document.page_count)}
            or document.original_filename != min(value.original_filename for value in observations)
            or document.observation_count != len(observations)
            or document.had_metadata_conflict != (len(raw_metadata) > 1)
            or document.metadata_changed
            != any(
                (
                    value.subject_family,
                    value.subject_label,
                    value.issuer_type,
                    value.administration_year,
                    value.grade,
                    value.session_label,
                )
                != (
                    document.subject_family,
                    document.subject_label,
                    document.issuer_type,
                    document.administration_year,
                    document.grade,
                    document.session_label,
                )
                for value in observations
            )
        ):
            raise ValueError("science metadata resolution differs from acquisition observations")


def validate_science_corpus_manifest_v2_against_inputs(
    manifest: ScienceAssessmentWebCorpusManifestV2,
    acquisition: ScienceAssessmentWebAcquisition,
    resolution: ScienceAssessmentMetadataResolution,
) -> None:
    """Bind a published v2 corpus to its exact raw and resolved metadata inputs."""

    validate_science_metadata_resolution_against_acquisition(resolution, acquisition)
    if (
        manifest.acquisition_sha256 != acquisition.acquisition_sha256
        or manifest.resolution_sha256 != resolution.resolution_sha256
        or manifest.resolution_policy_id != resolution.policy.policy_id
        or manifest.resolution_policy_sha256 != resolution.policy.policy_sha256
        or manifest.plan_id != acquisition.plan_id
        or manifest.plan_sha256 != acquisition.plan_sha256
        or manifest.observed_at != acquisition.observed_at
        or manifest.pdf_validator != acquisition.pdf_validator
    ):
        raise ValueError("corpus manifest v2 references another input")
    resolved_by_hash = {value.sha256: value for value in resolution.documents}
    observations_by_hash: dict[str, list[ScienceAssessmentAcquisitionSuccess]] = {}
    for observation in acquisition.successful_observations:
        observations_by_hash.setdefault(observation.sha256, []).append(observation)
    if {value.sha256 for value in manifest.documents} != set(resolved_by_hash):
        raise ValueError("corpus manifest v2 document set differs")
    for document in manifest.documents:
        resolved = resolved_by_hash[document.sha256]
        observations = observations_by_hash[document.sha256]
        expected_origins = tuple(
            sorted(
                {
                    ScienceAssessmentCorpusOrigin(
                        post_url=value.post_url,
                        download_url=value.download_url,
                        resolved_url=value.resolved_url,
                        link_text=value.link_text,
                    )
                    for value in observations
                },
                key=lambda value: (
                    value.post_url,
                    value.download_url,
                    value.resolved_url,
                    value.link_text,
                ),
            )
        )
        if (
            document.bytes,
            document.page_count,
            document.original_filename,
            document.subject_family,
            document.subject_label,
            document.issuer_type,
            document.administration_year,
            document.grade,
            document.session_label,
            document.origins,
        ) != (
            resolved.bytes,
            resolved.page_count,
            resolved.original_filename,
            resolved.subject_family,
            resolved.subject_label,
            resolved.issuer_type,
            resolved.administration_year,
            resolved.grade,
            resolved.session_label,
            expected_origins,
        ):
            raise ValueError("corpus manifest v2 metadata differs from resolution")
    if {(value.post_url, value.download_url, value.error_code) for value in manifest.failures} != {
        (value.post_url, value.download_url, value.error_code)
        for value in acquisition.failed_observations
    }:
        raise ValueError("corpus manifest v2 failures differ from acquisition")
    if (
        manifest.summary.scanned_post_count != acquisition.summary.scanned_post_count
        or manifest.summary.candidate_count != acquisition.summary.candidate_count
        or manifest.summary.acquisition_failure_count
        != acquisition.summary.failed_observation_count
    ):
        raise ValueError("corpus manifest v2 summary differs from acquisition")


def validate_science_corpus_manifest_v2_against_plan(
    manifest: ScienceAssessmentWebCorpusManifestV2,
    plan: ScienceAssessmentWebCorpusPlan,
) -> None:
    """Validate a v2 corpus network provenance against its immutable crawl plan."""

    if manifest.plan_id != plan.plan_id or manifest.plan_sha256 != plan.plan_sha256:
        raise ValueError("corpus manifest v2 references another acquisition plan")
    if manifest.summary.scanned_post_count > plan.max_post_pages:
        raise ValueError("corpus manifest v2 exceeds the plan post limit")
    allowed_hosts = set(plan.allowed_download_hosts)
    for document in manifest.documents:
        if (
            document.subject_family not in plan.subject_families
            or document.issuer_type not in plan.issuer_types
            or document.document_role not in plan.document_roles
            or document.bytes > plan.max_pdf_bytes
        ):
            raise ValueError("corpus document v2 is outside the plan scope")
        for origin in document.origins:
            if (
                urlsplit(origin.post_url).hostname != "legendstudy.com"
                or urlsplit(origin.download_url).hostname not in allowed_hosts
                or urlsplit(origin.resolved_url).hostname not in allowed_hosts
            ):
                raise ValueError("corpus origin v2 host is outside the plan allowlist")
    for failure in manifest.failures:
        if urlsplit(failure.download_url).hostname not in allowed_hosts:
            raise ValueError("corpus failure v2 host is outside the plan allowlist")
