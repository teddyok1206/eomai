"""Generic document preparation without textbook licensing/volume assumptions."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialKind,
    MaterialPreparedSource,
    SourceRole,
)
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

_PAGE_TEXT = "eom://schemas/material-learning/page-text/1.0"
_PAGE_IMAGE = "eom://schemas/educational-document/page-image/1.0"
_PDF = "eom://schemas/educational-document/pdf-source/1.0"
MaterialDocumentKind = Literal["TEXTBOOK", "REFERENCE_BOOK", "GUIDANCE"]
_DOCUMENT_KINDS: Mapping[MaterialKind, MaterialDocumentKind] = MappingProxyType(
    {
        "TEXTBOOK": "TEXTBOOK",
        "REFERENCE_BOOK": "REFERENCE_BOOK",
        "WORKBOOK": "REFERENCE_BOOK",
        "MOCK_EXAM": "GUIDANCE",
        "OTHER": "GUIDANCE",
    }
)


def material_document_kind(kind: MaterialKind) -> MaterialDocumentKind:
    return _DOCUMENT_KINDS[kind]


def material_document_source_class(
    kind: MaterialDocumentKind,
) -> Literal["TEXTBOOK", "INTERNAL_GUIDE"]:
    return "TEXTBOOK" if kind == "TEXTBOOK" else "INTERNAL_GUIDE"


def _self_hash(model: FrozenModel, name: str) -> None:
    document = model.model_dump(mode="json")
    expected = document.pop(name)
    if content_sha256(document) != expected:
        raise ValueError("MATERIAL_LEARNING_PREPARATION_HASH_MISMATCH")


class MaterialExtractorIdentity(FrozenModel):
    implementation: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    implementation_sha256: Sha256
    options_sha256: Sha256


class MaterialPreparationProfile(FrozenModel):
    schema_version: Literal["material-learning-preparation-profile/1.0"] = (
        "material-learning-preparation-profile/1.0"
    )
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    extractor: MaterialExtractorIdentity
    office_tool_source_commit: str | None = Field(pattern=r"^[0-9a-f]{40}$")
    libreoffice_sha256: Sha256 | None
    h2orestart_sha256: Sha256 | None
    maximum_pages: int = Field(strict=True, ge=1, le=2000)
    maximum_rendered_bytes: int = Field(strict=True, ge=1, le=4 * 1024 * 1024 * 1024)
    chunk_page_limit: int = Field(strict=True, ge=1, le=256)
    chunk_soft_bytes: int = Field(strict=True, ge=64 * 1024 * 1024, le=512 * 1024 * 1024)
    profile_sha256: Sha256

    @model_validator(mode="after")
    def coherent_profile(self) -> Self:
        tools = (self.office_tool_source_commit, self.libreoffice_sha256, self.h2orestart_sha256)
        if any(value is None for value in tools) and not all(value is None for value in tools):
            raise ValueError("MATERIAL_LEARNING_OFFICE_PROFILE_INCOMPLETE")
        _self_hash(self, "profile_sha256")
        return self


class MaterialPreparationInput(FrozenModel):
    schema_version: Literal["material-learning-preparation-input/1.0"] = (
        "material-learning-preparation-input/1.0"
    )
    task_id: str = Field(pattern=r"^materialtask_[0-9a-f]{32}$")
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    intake_manifest: MaterialArtifactMember
    profile: MaterialPreparationProfile
    input_sha256: Sha256

    @model_validator(mode="after")
    def coherent_input(self) -> Self:
        validate_contract("material-learning-preparation-input-v1", self.model_dump(mode="json"))
        if (
            self.intake_manifest.schema_ref != "eom://schemas/material-learning/intake/1.0"
            or self.intake_manifest.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_PREPARATION_INTAKE_INVALID")
        _self_hash(self, "input_sha256")
        return self


class MaterialPageMember(FrozenModel):
    member_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^analysis/(?:pages|images)/page-[0-9]{6}\.(?:md|png)$",
    )
    schema_ref: str = Field(pattern=r"^eom://schemas/[A-Za-z0-9._/-]{1,220}$")
    media_type: Literal["text/markdown", "image/png"]
    sha256: Sha256
    bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)


class MaterialPreparedPage(FrozenModel):
    physical_page: int = Field(strict=True, ge=1, le=2000)
    text: MaterialPageMember
    image: MaterialPageMember
    width_pixels: int = Field(strict=True, ge=1, le=10000)
    height_pixels: int = Field(strict=True, ge=1, le=10000)
    render_dpi: int = Field(strict=True, ge=120, le=400)

    @model_validator(mode="after")
    def exact_page_members(self) -> Self:
        if (
            self.text.member_path != f"analysis/pages/page-{self.physical_page:06d}.md"
            or self.image.member_path != f"analysis/images/page-{self.physical_page:06d}.png"
            or self.text.media_type != "text/markdown"
            or self.text.schema_ref != _PAGE_TEXT
            or self.text.bytes > 2 * 1024 * 1024
            or self.image.media_type != "image/png"
            or self.image.schema_ref != _PAGE_IMAGE
        ):
            raise ValueError("MATERIAL_LEARNING_PAGE_MEMBER_MISMATCH")
        return self


class MaterialPdfProjection(FrozenModel):
    schema_version: Literal["material-learning-pdf-projection/1.0"] = (
        "material-learning-pdf-projection/1.0"
    )
    source_sha256: Sha256
    profile_sha256: Sha256
    conversion: OfficeDocumentReviewConversionIdentity
    pdf_bytes: int = Field(strict=True, ge=8, le=256 * 1024 * 1024)
    office_catalog: MaterialArtifactMember

    @model_validator(mode="after")
    def exact_office_projection(self) -> Self:
        validate_contract("material-learning-pdf-projection-v1", self.model_dump(mode="json"))
        if (
            self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF"
            or self.office_catalog.member_path != "picture-use-catalog.json"
            or self.office_catalog.schema_ref
            != "eom://schemas/image-provider/office-picture-use-catalog/1.0"
            or self.office_catalog.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_OFFICE_PROJECTION_INVALID")
        return self


class MaterialPageChunk(FrozenModel):
    schema_version: Literal["material-learning-page-chunk/1.0"] = "material-learning-page-chunk/1.0"
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    source_role: SourceRole
    pdf_sha256: Sha256
    profile_sha256: Sha256
    first_physical_page: int = Field(strict=True, ge=1, le=2000)
    last_physical_page: int = Field(strict=True, ge=1, le=2000)
    pages: tuple[MaterialPreparedPage, ...] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def exact_chunk_coverage(self) -> Self:
        validate_contract("material-learning-page-chunk-v1", self.model_dump(mode="json"))
        if tuple(page.physical_page for page in self.pages) != tuple(
            range(self.first_physical_page, self.last_physical_page + 1)
        ):
            raise ValueError("MATERIAL_LEARNING_CHUNK_COVERAGE_INVALID")
        if sum(page.text.bytes + page.image.bytes for page in self.pages) > 1024 * 1024 * 1024:
            raise ValueError("MATERIAL_LEARNING_CHUNK_BYTES_INVALID")
        return self


class MaterialPageChunkReference(FrozenModel):
    manifest: MaterialArtifactMember
    first_physical_page: int = Field(strict=True, ge=1, le=2000)
    last_physical_page: int = Field(strict=True, ge=1, le=2000)
    content_bytes: int = Field(strict=True, ge=1, le=1024 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_chunk_pointer(self) -> Self:
        if (
            self.first_physical_page > self.last_physical_page
            or self.last_physical_page - self.first_physical_page >= 256
        ):
            raise ValueError("MATERIAL_LEARNING_CHUNK_RANGE_INVALID")
        if (
            self.manifest.member_path != "analysis/chunk.json"
            or self.manifest.schema_ref != "eom://schemas/material-learning/page-chunk/1.0"
            or self.manifest.media_type != "application/json"
        ):
            raise ValueError("MATERIAL_LEARNING_CHUNK_POINTER_INVALID")
        return self


def material_chunk_member(
    manifest: MaterialArtifactMember, member: MaterialPageMember
) -> MaterialArtifactMember:
    """A chunk member retains its enclosing Artifact identity, never its own copy."""
    return MaterialArtifactMember(
        artifact_id=manifest.artifact_id,
        artifact_revision_id=manifest.artifact_revision_id,
        **member.model_dump(mode="json"),
    )


class MaterialPageBundle(FrozenModel):
    schema_version: Literal["material-learning-page-bundle/1.0"] = (
        "material-learning-page-bundle/1.0"
    )
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    source_role: SourceRole
    original: MaterialArtifactMember
    pdf: MaterialArtifactMember
    conversion: OfficeDocumentReviewConversionIdentity
    profile: MaterialPreparationProfile
    page_count: int = Field(strict=True, ge=1, le=2000)
    chunks: tuple[MaterialPageChunkReference, ...] = Field(min_length=1, max_length=2000)
    office_catalog: MaterialArtifactMember | None

    @model_validator(mode="after")
    def exact_book_coverage(self) -> Self:
        validate_contract("material-learning-page-bundle-v1", self.model_dump(mode="json"))
        if self.page_count > self.profile.maximum_pages:
            raise ValueError("MATERIAL_LEARNING_SOURCE_PAGE_LIMIT")
        next_page = 1
        identities = set()
        for chunk in self.chunks:
            if chunk.first_physical_page != next_page:
                raise ValueError("MATERIAL_LEARNING_BUNDLE_PAGE_GAP_OR_OVERLAP")
            next_page = chunk.last_physical_page + 1
            identities.add((chunk.manifest.artifact_id, chunk.manifest.artifact_revision_id))
        if next_page != self.page_count + 1 or len(identities) != len(self.chunks):
            raise ValueError("MATERIAL_LEARNING_BUNDLE_COVERAGE_INVALID")
        if sum(chunk.content_bytes for chunk in self.chunks) > self.profile.maximum_rendered_bytes:
            raise ValueError("MATERIAL_LEARNING_SOURCE_RENDER_LIMIT")
        if (
            self.pdf.media_type != "application/pdf"
            or self.pdf.schema_ref != _PDF
            or self.conversion.review_pdf_sha256 != self.pdf.sha256
        ):
            raise ValueError("MATERIAL_LEARNING_PDF_PROJECTION_INVALID")
        if self.original.media_type == "application/pdf":
            if (
                self.pdf != self.original
                or self.conversion.conversion_kind != "IDENTITY_PDF"
                or self.office_catalog is not None
            ):
                raise ValueError("MATERIAL_LEARNING_PDF_DUPLICATED")
        elif (
            self.original.media_type
            not in {"application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"}
            or self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF"
            or self.office_catalog is None
            or self.profile.office_tool_source_commit is None
            or self.profile.libreoffice_sha256 != self.conversion.libreoffice_sha256
            or self.profile.h2orestart_sha256 != self.conversion.h2orestart_sha256
        ):
            raise ValueError("MATERIAL_LEARNING_OFFICE_PROJECTION_INVALID")
        return self


class MaterialDocumentRevision(FrozenModel):
    schema_version: Literal["material-learning-document-revision/1.0"] = (
        "material-learning-document-revision/1.0"
    )
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    document_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    revision_number: Literal[1] = 1
    previous_revision_id: None = None
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    source_role: SourceRole
    document_kind: MaterialDocumentKind
    source_class: Literal["TEXTBOOK", "INTERNAL_GUIDE"]
    title: str = Field(min_length=1, max_length=200)
    source_description: str = Field(min_length=1, max_length=2000)
    publisher_key: None = None
    curriculum_volume: None = None
    edition_label: None = None
    original: MaterialArtifactMember
    source: MaterialArtifactMember
    source_page_count: int = Field(strict=True, ge=1, le=2000)
    analysis_bundle_manifest: MaterialArtifactMember
    rights_attestation: MaterialArtifactMember
    registered_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    registered_at: UtcDatetime
    registration_request_sha256: Sha256
    document_revision_sha256: Sha256

    @model_validator(mode="after")
    def coherent_document(self) -> Self:
        validate_contract("material-learning-document-revision-v1", self.model_dump(mode="json"))
        if self.source_class != material_document_source_class(self.document_kind):
            raise ValueError("MATERIAL_LEARNING_DOCUMENT_CLASS_INVALID")
        if self.source.media_type != "application/pdf" or self.source.schema_ref != _PDF:
            raise ValueError("MATERIAL_LEARNING_DOCUMENT_PDF_INVALID")
        if (
            self.analysis_bundle_manifest.schema_ref
            != "eom://schemas/material-learning/page-bundle/1.0"
            or self.analysis_bundle_manifest.member_path != "analysis/manifest.json"
        ):
            raise ValueError("MATERIAL_LEARNING_DOCUMENT_BUNDLE_INVALID")
        if self.rights_attestation.schema_ref != "eom://schemas/material-learning/rights/1.0":
            raise ValueError("MATERIAL_LEARNING_DOCUMENT_RIGHTS_INVALID")
        _self_hash(self, "document_revision_sha256")
        return self


class MaterialDocumentReceipt(FrozenModel):
    schema_version: Literal["material-learning-document-receipt/1.0"] = (
        "material-learning-document-receipt/1.0"
    )
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    revision_number: Literal[1] = 1
    registration_request_sha256: Sha256
    revision_manifest: MaterialArtifactMember
    original: MaterialArtifactMember
    source: MaterialArtifactMember
    analysis_bundle_manifest: MaterialArtifactMember
    rights_attestation: MaterialArtifactMember

    @model_validator(mode="after")
    def coherent_receipt(self) -> Self:
        validate_contract("material-learning-document-receipt-v1", self.model_dump(mode="json"))
        if (
            self.revision_manifest.schema_ref
            != "eom://schemas/material-learning/document-revision/1.0"
            or self.revision_manifest.member_path != "document/document-revision.json"
        ):
            raise ValueError("MATERIAL_LEARNING_DOCUMENT_MANIFEST_INVALID")
        return self


class MaterialPreparedArtifact(FrozenModel):
    schema_version: Literal["material-learning-prepared/1.0"] = "material-learning-prepared/1.0"
    material_id: str = Field(pattern=r"^material_[0-9a-f]{32}$")
    material_revision_id: str = Field(pattern=r"^materialrev_[0-9a-f]{32}$")
    intake_manifest: MaterialArtifactMember
    profile_sha256: Sha256
    sources: tuple[MaterialPreparedSource, ...] = Field(min_length=1, max_length=2)
    prepared_sha256: Sha256

    @model_validator(mode="after")
    def coherent_prepared_material(self) -> Self:
        validate_contract("material-learning-prepared-v1", self.model_dump(mode="json"))
        if tuple(source.source_role for source in self.sources) not in {
            ("MAIN",),
            ("MAIN", "SOLUTIONS"),
        }:
            raise ValueError("MATERIAL_LEARNING_SOURCE_ROLE_ORDER_INVALID")
        if self.intake_manifest.schema_ref != "eom://schemas/material-learning/intake/1.0":
            raise ValueError("MATERIAL_LEARNING_PREPARED_INTAKE_INVALID")
        if len({source.document_revision_id for source in self.sources}) != len(self.sources):
            raise ValueError("MATERIAL_LEARNING_PREPARED_DOCUMENT_DUPLICATE")
        _self_hash(self, "prepared_sha256")
        return self
