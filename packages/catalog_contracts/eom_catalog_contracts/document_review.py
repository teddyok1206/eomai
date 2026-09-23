"""Immutable Catalog contracts for PDF and Office document-review intake."""

from __future__ import annotations

from itertools import pairwise
from pathlib import PurePosixPath
from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER = "annotation-manifest.json"
DocumentId = Annotated[str, Field(pattern=r"^document_[0-9a-f]{32}$")]
DocumentRevisionId = Annotated[str, Field(pattern=r"^documentrev_[0-9a-f]{32}$")]
ArtifactId = Annotated[str, Field(pattern=r"^artifact_[0-9a-f]{32}$")]
ArtifactRevisionId = Annotated[str, Field(pattern=r"^rev_[0-9a-f]{32}$")]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class PdfReviewArtifactMemberPointer(FrozenModel):
    """One exact member of the immutable Catalog-owned review source Artifact."""

    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    member_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    sha256: Sha256
    schema_ref: str = Field(pattern=r"^eom://schemas/document-review/[a-z0-9-]+/1\.0$")
    media_type: Literal["application/pdf", "image/png", "application/json"]
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)

    @field_validator("member_path")
    @classmethod
    def require_safe_relative_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.startswith("/"):
            raise ValueError("PDF review Artifact member path is unsafe")
        return value


class PdfReviewPagePointer(FrozenModel):
    """One ordered page render used for worker and browser materialization."""

    page_number: int = Field(ge=1, le=2000)
    width_px: int = Field(ge=64, le=16384)
    height_px: int = Field(ge=64, le=16384)
    rotation_degrees: Literal[0, 90, 180, 270]
    page_image: PdfReviewArtifactMemberPointer
    text_layer: PdfReviewArtifactMemberPointer | None

    @model_validator(mode="after")
    def require_exact_member_contracts(self) -> PdfReviewPagePointer:
        expected_prefix = f"pages/page-{self.page_number:04d}"
        if (
            self.page_image.media_type != "image/png"
            or self.page_image.schema_ref != "eom://schemas/document-review/pdf-page-render/1.0"
            or self.page_image.member_path != f"{expected_prefix}.png"
        ):
            raise ValueError("PDF review page image pointer differs from its exact page contract")
        if self.text_layer is not None and (
            self.text_layer.media_type != "application/json"
            or self.text_layer.schema_ref != "eom://schemas/document-review/pdf-page-text/1.0"
            or self.text_layer.member_path != f"{expected_prefix}.text.json"
        ):
            raise ValueError("PDF review text pointer differs from its exact page contract")
        return self


class PdfReviewDocumentPointer(FrozenModel):
    """Immutable source and ordered derived pages for one PDF document revision."""

    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    source_pdf: PdfReviewArtifactMemberPointer
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfReviewPagePointer, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_document_members(self) -> PdfReviewDocumentPointer:
        if (
            self.source_pdf.media_type != "application/pdf"
            or self.source_pdf.schema_ref != "eom://schemas/document-review/pdf-source/1.0"
            or self.source_pdf.member_path != "source/original.pdf"
        ):
            raise ValueError("PDF source pointer differs from its exact source contract")
        if len(self.pages) != self.page_count:
            raise ValueError("PDF page count differs from the ordered page pointer count")
        page_numbers = tuple(page.page_number for page in self.pages)
        if page_numbers != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF page pointers must be complete and ordered from one")
        source_identity = (
            self.source_pdf.artifact_id,
            self.source_pdf.artifact_revision_id,
        )
        if any(
            (member.artifact_id, member.artifact_revision_id) != source_identity
            for page in self.pages
            for member in (page.page_image, page.text_layer)
            if member is not None
        ):
            raise ValueError("PDF review members must belong to the exact source Artifact revision")
        member_keys = [
            (page.page_image.artifact_revision_id, page.page_image.member_path)
            for page in self.pages
        ]
        member_keys.extend(
            (page.text_layer.artifact_revision_id, page.text_layer.member_path)
            for page in self.pages
            if page.text_layer is not None
        )
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("PDF review page members must be unique")
        return self


class PdfDocumentReviewRendererIdentity(FrozenModel):
    renderer_key: Literal["poppler-pdftoppm"] = "poppler-pdftoppm"
    pdfinfo_sha256: Sha256
    pdftoppm_sha256: Sha256
    scale_to_px: Literal[2400] = 2400
    output_format: Literal["PNG"] = "PNG"


class PdfDocumentReviewPageMember(FrozenModel):
    page_number: int = Field(ge=1, le=2000)
    member_path: str = Field(pattern=r"^pages/page-[0-9]{4}\.png$")
    sha256: Sha256
    content_length: int = Field(ge=1, le=64 * 1024 * 1024)
    width_px: int = Field(ge=64, le=2400)
    height_px: int = Field(ge=64, le=2400)
    rotation_degrees: Literal[0] = 0

    @model_validator(mode="after")
    def require_page_path(self) -> PdfDocumentReviewPageMember:
        if self.member_path != f"pages/page-{self.page_number:04d}.png":
            raise ValueError("PDF document-review page path differs from its page number")
        return self


class PdfDocumentReviewIntakeManifest(FrozenModel):
    schema_version: Literal["pdf-document-review-intake-manifest/1.0"] = (
        "pdf-document-review-intake-manifest/1.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.[Pp][Dd][Ff]$",
    )
    source_pdf_sha256: Sha256
    source_pdf_bytes: int = Field(ge=8, le=256 * 1024 * 1024)
    renderer: PdfDocumentReviewRendererIdentity
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfDocumentReviewPageMember, ...] = Field(min_length=1, max_length=2000)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_complete_pages_and_hash(self) -> PdfDocumentReviewIntakeManifest:
        if len(self.pages) != self.page_count:
            raise ValueError("PDF document-review manifest page count differs")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("PDF document-review manifest pages must be complete and ordered")
        paths = tuple(page.member_path for page in self.pages)
        if len(paths) != len(set(paths)):
            raise ValueError("PDF document-review manifest page paths must be unique")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("PDF document-review intake manifest hash differs")
        return self


OfficeDocumentSourceFormat = Literal["PDF", "HWP", "HWPX"]
OfficeDocumentMediaType = Literal[
    "application/pdf",
    "application/vnd.hancom.hwp",
    "application/vnd.hancom.hwpx",
    "image/png",
    "application/json",
]


class OfficeDocumentReviewMemberDescriptor(FrozenModel):
    """One member description before an Artifact revision identity is assigned."""

    member_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    sha256: Sha256
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)
    media_type: OfficeDocumentMediaType
    schema_ref: str = Field(pattern=r"^eom://schemas/document-review/[a-z0-9-]+/[12]\.0$")

    @field_validator("member_path")
    @classmethod
    def require_safe_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.startswith("/"):
            raise ValueError("Office review Artifact member path is unsafe")
        return value


class OfficeDocumentReviewMemberPointer(OfficeDocumentReviewMemberDescriptor):
    """One exact member in an immutable Office review Artifact revision."""

    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId


class OfficeDocumentReviewMemberPointerV2(FrozenModel):
    """Exact member pointer used by split-source Office review successors."""

    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    member_path: str = Field(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    sha256: Sha256
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)
    media_type: OfficeDocumentMediaType
    schema_ref: str = Field(pattern=r"^eom://schemas/document-review/[a-z0-9-]+/[123]\.0$")

    @field_validator("member_path")
    @classmethod
    def require_safe_member_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.startswith("/"):
            raise ValueError("Office review Artifact member path is unsafe")
        return value


class OfficeDocumentReviewSourceUploadManifest(FrozenModel):
    """Canonical exact source admitted independently of conversion success."""

    schema_version: Literal["document-review-source-upload-manifest/1.0"] = (
        "document-review-source-upload-manifest/1.0"
    )
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["HWP", "HWPX"]
    original_source: OfficeDocumentReviewMemberDescriptor
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_source_and_hash(self) -> OfficeDocumentReviewSourceUploadManifest:
        suffix, media_type, schema_ref = {
            "PDF": (
                ".pdf",
                "application/pdf",
                "eom://schemas/document-review/pdf-source/1.0",
            ),
            "HWP": (
                ".hwp",
                "application/vnd.hancom.hwp",
                "eom://schemas/document-review/hwp-source/2.0",
            ),
            "HWPX": (
                ".hwpx",
                "application/vnd.hancom.hwpx",
                "eom://schemas/document-review/editable-hwpx/1.0",
            ),
        }[self.source_format]
        if (
            not self.original_filename.lower().endswith(suffix)
            or self.original_source.member_path != f"source/original{suffix}"
            or self.original_source.media_type != media_type
            or self.original_source.schema_ref != schema_ref
        ):
            raise ValueError("Office review upload manifest source identity differs")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("Office review upload manifest hash differs")
        return self


class PdfDocumentReviewResultMemberPointer(FrozenModel):
    """Exact committed role result used as correction authority."""

    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    member_path: Literal["result.json"] = "result.json"
    sha256: Sha256
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)
    media_type: Literal["application/json"] = "application/json"
    schema_ref: Literal[
        "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
    ] = "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"


class OfficeDocumentReviewConversionIdentity(FrozenModel):
    conversion_kind: Literal["IDENTITY_PDF", "LIBREOFFICE_H2ORESTART_PDF"]
    review_pdf_sha256: Sha256
    libreoffice_version: str | None = Field(default=None, min_length=1, max_length=128)
    libreoffice_sha256: Sha256 | None = None
    h2orestart_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def require_exact_converter_identity(self) -> OfficeDocumentReviewConversionIdentity:
        tool_identity = (
            self.libreoffice_version,
            self.libreoffice_sha256,
            self.h2orestart_sha256,
        )
        if self.conversion_kind == "IDENTITY_PDF":
            if any(value is not None for value in tool_identity):
                raise ValueError("PDF identity conversion cannot carry Office converter identity")
        elif any(value is None for value in tool_identity):
            raise ValueError("Office conversion requires exact LibreOffice and H2Orestart identity")
        return self


class OfficeDocumentReviewIntakeManifest(FrozenModel):
    """Immutable original, reviewed PDF projection, and page render manifest."""

    schema_version: Literal["document-review-intake-manifest/2.0"] = (
        "document-review-intake-manifest/2.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Pp][Dd][Ff]|[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: OfficeDocumentSourceFormat
    original_source: OfficeDocumentReviewMemberDescriptor
    review_pdf: OfficeDocumentReviewMemberDescriptor
    editable_hwpx: OfficeDocumentReviewMemberDescriptor | None
    conversion: OfficeDocumentReviewConversionIdentity
    renderer: PdfDocumentReviewRendererIdentity
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfDocumentReviewPageMember, ...] = Field(min_length=1, max_length=2000)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_office_members_and_hash(self) -> OfficeDocumentReviewIntakeManifest:
        suffix_by_format = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}
        media_by_format = {
            "PDF": "application/pdf",
            "HWP": "application/vnd.hancom.hwp",
            "HWPX": "application/vnd.hancom.hwpx",
        }
        schema_by_format = {
            "PDF": "eom://schemas/document-review/pdf-source/1.0",
            "HWP": "eom://schemas/document-review/hwp-source/2.0",
            "HWPX": "eom://schemas/document-review/editable-hwpx/1.0",
        }
        source_suffix = suffix_by_format[self.source_format]
        if not self.original_filename.lower().endswith(source_suffix):
            raise ValueError("Office review source filename differs from its declared format")
        if (
            self.original_source.member_path != f"source/original{source_suffix}"
            or self.original_source.media_type != media_by_format[self.source_format]
            or self.original_source.schema_ref != schema_by_format[self.source_format]
        ):
            raise ValueError("Office review original source differs from its exact member contract")
        if (
            self.review_pdf.member_path != "source/original.pdf"
            or self.review_pdf.media_type != "application/pdf"
            or self.review_pdf.schema_ref != "eom://schemas/document-review/pdf-source/1.0"
            or self.review_pdf.sha256 != self.conversion.review_pdf_sha256
        ):
            raise ValueError("Office review PDF differs from its exact projection contract")
        if self.source_format == "PDF":
            if self.editable_hwpx is not None or self.conversion.conversion_kind != "IDENTITY_PDF":
                raise ValueError(
                    "PDF review source must use identity conversion without HWPX editing"
                )
            if self.original_source != self.review_pdf:
                raise ValueError("PDF identity projection must reuse the exact source member")
        else:
            if self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF":
                raise ValueError("Office review source requires the pinned Office PDF converter")
            if self.source_format == "HWP":
                if self.editable_hwpx is not None:
                    raise ValueError("HWP review source cannot expose an editable HWPX pointer")
            elif self.editable_hwpx != self.original_source:
                raise ValueError("HWPX editing must pin the exact immutable uploaded member")
        if len(self.pages) != self.page_count:
            raise ValueError("Office review manifest page count differs")
        if tuple(page.page_number for page in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("Office review pages must be complete and ordered")
        paths = tuple(page.member_path for page in self.pages)
        if len(paths) != len(set(paths)):
            raise ValueError("Office review page members must be unique")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("Office document-review intake manifest hash differs")
        return self


class OfficeDocumentReviewIntakeManifestV3(FrozenModel):
    """Derived PDF/page projection pinned to a separate canonical Office source."""

    schema_version: Literal["document-review-intake-manifest/3.0"] = (
        "document-review-intake-manifest/3.0"
    )
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    original_filename: str = Field(
        min_length=5,
        max_length=240,
        pattern=r"^[^/\\\x00-\x1f]+\.(?:[Hh][Ww][Pp](?:[Xx])?)$",
    )
    source_format: Literal["HWP", "HWPX"]
    original_source: OfficeDocumentReviewMemberPointerV2
    review_pdf: OfficeDocumentReviewMemberDescriptor
    editable_hwpx: OfficeDocumentReviewMemberPointerV2 | None
    conversion: OfficeDocumentReviewConversionIdentity
    renderer: PdfDocumentReviewRendererIdentity
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[PdfDocumentReviewPageMember, ...] = Field(min_length=1, max_length=2000)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_projection_and_hash(self) -> OfficeDocumentReviewIntakeManifestV3:
        suffix, media_type, schema_ref = {
            "HWP": (
                ".hwp",
                "application/vnd.hancom.hwp",
                "eom://schemas/document-review/hwp-source/2.0",
            ),
            "HWPX": (
                ".hwpx",
                "application/vnd.hancom.hwpx",
                "eom://schemas/document-review/editable-hwpx/1.0",
            ),
        }[self.source_format]
        if (
            not self.original_filename.lower().endswith(suffix)
            or self.original_source.member_path != f"source/original{suffix}"
            or self.original_source.media_type != media_type
            or self.original_source.schema_ref != schema_ref
        ):
            raise ValueError("Office review V3 source pointer differs from its format")
        expected_editable = self.original_source if self.source_format == "HWPX" else None
        if self.editable_hwpx != expected_editable:
            raise ValueError("Office review V3 editable source pointer differs")
        if (
            self.review_pdf.member_path != "source/original.pdf"
            or self.review_pdf.media_type != "application/pdf"
            or self.review_pdf.schema_ref != "eom://schemas/document-review/pdf-source/1.0"
            or self.review_pdf.sha256 != self.conversion.review_pdf_sha256
            or self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF"
        ):
            raise ValueError("Office review V3 PDF projection differs")
        if len(self.pages) != self.page_count or tuple(
            page.page_number for page in self.pages
        ) != tuple(range(1, self.page_count + 1)):
            raise ValueError("Office review V3 pages must be complete and ordered")
        paths = tuple(page.member_path for page in self.pages)
        if len(paths) != len(set(paths)):
            raise ValueError("Office review V3 page paths must be unique")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("Office review V3 intake manifest hash differs")
        return self


OfficeDocumentConversionStage = Literal[
    "SOURCE_VALIDATION",
    "DEPENDENCY_VALIDATION",
    "EXTENSION_REGISTRATION",
    "LIBREOFFICE_EXECUTION",
    "OUTPUT_VALIDATION",
    "OUTPUT_VALIDATED",
]
OfficeDocumentConversionErrorCode = Literal[
    "OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID",
    "OFFICE_DOCUMENT_CONVERSION_EXTENSION_FAILED",
    "OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED",
    "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE",
    "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING",
    "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID",
    "OFFICE_DOCUMENT_CONVERSION_SOURCE_INVALID",
]


class OfficeDocumentConversionOutcome(FrozenModel):
    """Bounded machine-readable result written by the isolated converter."""

    schema_version: Literal["office-document-conversion-outcome/1.0"] = (
        "office-document-conversion-outcome/1.0"
    )
    instance_id: str = Field(pattern=r"^officeconv_[0-9a-f]{32}$")
    status: Literal["OK", "ERROR"]
    stage: OfficeDocumentConversionStage
    error_code: OfficeDocumentConversionErrorCode | None = None
    source_format: Literal["HWP", "HWPX"]
    source_sha256: Sha256
    source_bytes: int = Field(ge=8, le=256 * 1024 * 1024)
    h2orestart_sha256: Sha256
    stdout_sha256: Sha256
    stdout_bytes: int = Field(ge=0, le=256 * 1024)
    stderr_sha256: Sha256
    stderr_bytes: int = Field(ge=0, le=256 * 1024)
    output_sha256: Sha256 | None = None
    output_bytes: int | None = Field(default=None, ge=8, le=256 * 1024 * 1024)
    outcome_sha256: Sha256

    @model_validator(mode="after")
    def require_terminal_variant_and_hash(self) -> OfficeDocumentConversionOutcome:
        if self.status == "OK":
            if (
                self.stage != "OUTPUT_VALIDATED"
                or self.error_code is not None
                or "error_code" in self.model_fields_set
                or self.output_sha256 is None
                or self.output_bytes is None
            ):
                raise ValueError("successful Office conversion outcome is incomplete")
        elif (
            self.stage == "OUTPUT_VALIDATED"
            or self.error_code is None
            or self.output_sha256 is not None
            or self.output_bytes is not None
            or "output_sha256" in self.model_fields_set
            or "output_bytes" in self.model_fields_set
        ):
            raise ValueError("failed Office conversion outcome is inconsistent")
        if self.error_code is not None:
            expected_stage: dict[
                OfficeDocumentConversionErrorCode, OfficeDocumentConversionStage
            ] = {
                "OFFICE_DOCUMENT_CONVERSION_DEPENDENCY_INVALID": "DEPENDENCY_VALIDATION",
                "OFFICE_DOCUMENT_CONVERSION_EXTENSION_FAILED": "EXTENSION_REGISTRATION",
                "OFFICE_DOCUMENT_CONVERSION_EXECUTION_FAILED": "LIBREOFFICE_EXECUTION",
                "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE": "LIBREOFFICE_EXECUTION",
                "OFFICE_DOCUMENT_CONVERSION_OUTPUT_MISSING": "OUTPUT_VALIDATION",
                "OFFICE_DOCUMENT_CONVERSION_OUTPUT_INVALID": "OUTPUT_VALIDATION",
                "OFFICE_DOCUMENT_CONVERSION_SOURCE_INVALID": "SOURCE_VALIDATION",
            }
            if self.stage != expected_stage[self.error_code]:
                raise ValueError("Office conversion error code and stage differ")
        if (
            content_sha256(
                self.model_dump(
                    mode="json",
                    exclude={"outcome_sha256"},
                    exclude_none=True,
                )
            )
            != self.outcome_sha256
        ):
            raise ValueError("Office conversion outcome hash differs")
        return self


class DocumentReviewHwpxEditAddress(FrozenModel):
    section_member: str = Field(pattern=r"^Contents/section[0-9]+\.xml$")
    paragraph_ordinal: int = Field(ge=0, le=1_000_000)
    paragraph_sha256: Sha256
    start_offset: int = Field(ge=0, le=10_000_000)
    end_offset: int = Field(ge=1, le=10_000_000)
    source_char_property_id: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def require_nonempty_span(self) -> DocumentReviewHwpxEditAddress:
        if self.end_offset <= self.start_offset:
            raise ValueError("HWPX edit address must identify one non-empty span")
        return self


class DocumentReviewHwpxEdit(FrozenModel):
    finding_id: Annotated[str, Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")]
    finding_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    before_text: str = Field(min_length=1, max_length=2000)
    before_sha256: Sha256
    after_text: str = Field(min_length=1, max_length=2000)
    after_sha256: Sha256
    address: DocumentReviewHwpxEditAddress

    @model_validator(mode="after")
    def require_text_hashes(self) -> DocumentReviewHwpxEdit:
        if content_sha256(self.before_text) != self.before_sha256:
            raise ValueError("HWPX correction before-text hash differs")
        if content_sha256(self.after_text) != self.after_sha256:
            raise ValueError("HWPX correction after-text hash differs")
        if self.before_text == self.after_text:
            raise ValueError("HWPX correction replacement must change text")
        return self


class DocumentReviewHwpxCorrectionPlan(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-plan/1.0"] = (
        "document-review-hwpx-correction-plan/1.0"
    )
    correction_id: Annotated[str, Field(pattern=r"^doccorrection_[0-9a-f]{32}$")]
    workflow_id: Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
    review_result: PdfDocumentReviewResultMemberPointer
    base_hwpx: OfficeDocumentReviewMemberPointer
    text_color: Literal["#FF0000"] = "#FF0000"
    edits: tuple[DocumentReviewHwpxEdit, ...] = Field(min_length=1, max_length=32)
    plan_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_plan(self) -> DocumentReviewHwpxCorrectionPlan:
        if (
            self.base_hwpx.media_type != "application/vnd.hancom.hwpx"
            or self.base_hwpx.schema_ref != "eom://schemas/document-review/editable-hwpx/1.0"
            or self.base_hwpx.member_path != "source/original.hwpx"
        ):
            raise ValueError("HWPX correction base pointer differs")
        finding_ids = tuple(edit.finding_id for edit in self.edits)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("HWPX correction findings must be unique")
        addresses = tuple(
            (
                edit.address.section_member,
                edit.address.paragraph_ordinal,
                edit.address.start_offset,
                edit.address.end_offset,
            )
            for edit in self.edits
        )
        if addresses != tuple(sorted(addresses)):
            raise ValueError("HWPX correction edits must be in deterministic document order")
        for previous, current in pairwise(addresses):
            if previous[:2] == current[:2] and current[2] < previous[3]:
                raise ValueError("HWPX correction edit spans cannot overlap")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"plan_sha256"}))
            != self.plan_sha256
        ):
            raise ValueError("HWPX correction plan hash differs")
        return self


class DocumentReviewHwpxOutputMember(FrozenModel):
    member_path: Literal["corrected/document-review-redline.hwpx"] = (
        "corrected/document-review-redline.hwpx"
    )
    sha256: Sha256
    content_length: int = Field(ge=1, le=256 * 1024 * 1024)
    media_type: Literal["application/vnd.hancom.hwpx"] = "application/vnd.hancom.hwpx"


class DocumentReviewHwpxCorrectionResult(FrozenModel):
    schema_version: Literal["document-review-hwpx-correction-result/1.0"] = (
        "document-review-hwpx-correction-result/1.0"
    )
    correction_id: Annotated[str, Field(pattern=r"^doccorrection_[0-9a-f]{32}$")]
    workflow_id: Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
    plan_sha256: Sha256
    base_hwpx_sha256: Sha256
    output_member: DocumentReviewHwpxOutputMember
    applied_finding_ids: tuple[
        Annotated[str, Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")], ...
    ] = Field(min_length=1, max_length=32)
    text_color: Literal["#FF0000"] = "#FF0000"
    result_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_result(self) -> DocumentReviewHwpxCorrectionResult:
        if len(self.applied_finding_ids) != len(set(self.applied_finding_ids)):
            raise ValueError("HWPX correction result findings must be unique")
        if self.output_member.sha256 == self.base_hwpx_sha256:
            raise ValueError("HWPX correction output must differ from its immutable base")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
            != self.result_sha256
        ):
            raise ValueError("HWPX correction result hash differs")
        return self


DocumentReviewAnnotationRole = Literal["DOCUMENT", "QUESTION", "SOLUTION"]


class DocumentReviewResultMemberPointer(FrozenModel):
    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId
    member_path: Literal["result.json"] = "result.json"
    sha256: Sha256
    content_length: int = Field(ge=1, le=16 * 1024 * 1024)
    media_type: Literal["application/json"] = "application/json"
    schema_ref: Literal[
        "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json",
        "https://eom.local/schemas/workflow/roles/paired-document-review-result-v2.schema.json",
    ]


class DocumentReviewAnnotationRegion(FrozenModel):
    x_ppm: int = Field(ge=0, le=999999)
    y_ppm: int = Field(ge=0, le=999999)
    width_ppm: int = Field(ge=1, le=1000000)
    height_ppm: int = Field(ge=1, le=1000000)

    @model_validator(mode="after")
    def require_bounded_region(self) -> DocumentReviewAnnotationRegion:
        if self.x_ppm + self.width_ppm > 1_000_000:
            raise ValueError("annotation region exceeds page width")
        if self.y_ppm + self.height_ppm > 1_000_000:
            raise ValueError("annotation region exceeds page height")
        return self


class DocumentReviewAnnotationPage(FrozenModel):
    page_number: int = Field(ge=1, le=2000)
    page_image: PdfReviewArtifactMemberPointer

    @model_validator(mode="after")
    def require_page_image(self) -> DocumentReviewAnnotationPage:
        if (
            self.page_image.member_path != f"pages/page-{self.page_number:04d}.png"
            or self.page_image.media_type != "image/png"
            or self.page_image.schema_ref != "eom://schemas/document-review/pdf-page-render/1.0"
        ):
            raise ValueError("annotation page image differs from its page number")
        return self


class DocumentReviewAnnotationSource(FrozenModel):
    role: DocumentReviewAnnotationRole
    document_id: DocumentId
    document_revision_id: DocumentRevisionId
    source_pdf: PdfReviewArtifactMemberPointer
    page_count: int = Field(ge=1, le=2000)
    pages: tuple[DocumentReviewAnnotationPage, ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_exact_source(self) -> DocumentReviewAnnotationSource:
        if (
            self.source_pdf.member_path != "source/original.pdf"
            or self.source_pdf.media_type != "application/pdf"
            or self.source_pdf.schema_ref != "eom://schemas/document-review/pdf-source/1.0"
        ):
            raise ValueError("annotation source PDF pointer differs")
        if len(self.pages) != self.page_count:
            raise ValueError("annotation source page count differs")
        if tuple(value.page_number for value in self.pages) != tuple(range(1, self.page_count + 1)):
            raise ValueError("annotation source pages must be complete and ordered")
        source_identity = (
            self.source_pdf.artifact_id,
            self.source_pdf.artifact_revision_id,
        )
        if any(
            (value.page_image.artifact_id, value.page_image.artifact_revision_id) != source_identity
            for value in self.pages
        ):
            raise ValueError("annotation source pages differ from the source Artifact")
        return self


class DocumentReviewPdfAnnotationMark(FrozenModel):
    finding_id: Annotated[str, Field(pattern=r"^reviewfinding_[0-9a-f]{32}$")]
    anchor_id: Annotated[str, Field(pattern=r"^reviewanchor_[0-9a-f]{32}$")]
    ordinal: int = Field(ge=1, le=512)
    document_role: DocumentReviewAnnotationRole
    page_number: int = Field(ge=1, le=2000)
    page_image_sha256: Sha256
    region: DocumentReviewAnnotationRegion


class DocumentReviewPdfAnnotationRenderer(FrozenModel):
    renderer_key: Literal["qpdf-rsvg-document-review-annotation"] = (
        "qpdf-rsvg-document-review-annotation"
    )
    qpdf_version: str = Field(min_length=1, max_length=128)
    qpdf_sha256: Sha256
    rsvg_convert_version: str = Field(min_length=1, max_length=128)
    rsvg_convert_sha256: Sha256
    pdfinfo_version: str = Field(min_length=1, max_length=128)
    pdfinfo_sha256: Sha256
    stroke_color: Literal["#D70015"] = "#D70015"


class DocumentReviewAnnotatedPdfMember(FrozenModel):
    document_role: DocumentReviewAnnotationRole
    member_path: Literal[
        "annotated/document.pdf",
        "annotated/question.pdf",
        "annotated/solution.pdf",
    ]
    sha256: Sha256
    content_length: int = Field(ge=1, le=512 * 1024 * 1024)
    media_type: Literal["application/pdf"] = "application/pdf"
    schema_ref: Literal["eom://schemas/document-review/annotated-pdf/1.0"] = (
        "eom://schemas/document-review/annotated-pdf/1.0"
    )

    @model_validator(mode="after")
    def require_role_path(self) -> DocumentReviewAnnotatedPdfMember:
        expected = {
            "DOCUMENT": "annotated/document.pdf",
            "QUESTION": "annotated/question.pdf",
            "SOLUTION": "annotated/solution.pdf",
        }[self.document_role]
        if self.member_path != expected:
            raise ValueError("annotated PDF path differs from its document role")
        return self


class DocumentReviewAnnotatedPdfPointer(DocumentReviewAnnotatedPdfMember):
    artifact_id: ArtifactId
    artifact_revision_id: ArtifactRevisionId


class DocumentReviewPdfAnnotationManifest(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-manifest/1.0"] = (
        "document-review-pdf-annotation-manifest/1.0"
    )
    annotation_id: Annotated[str, Field(pattern=r"^docannotation_[0-9a-f]{32}$")]
    workflow_id: Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
    request_sha256: Sha256
    review_result_sha256: Sha256
    sources: tuple[DocumentReviewAnnotationSource, ...] = Field(min_length=1, max_length=2)
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...] = Field(
        min_length=1,
        max_length=4096,
    )
    annotation_set_sha256: Sha256
    renderer: DocumentReviewPdfAnnotationRenderer
    outputs: tuple[DocumentReviewAnnotatedPdfMember, ...] = Field(min_length=1, max_length=2)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_manifest(self) -> DocumentReviewPdfAnnotationManifest:
        source_roles = tuple(value.role for value in self.sources)
        if source_roles not in {("DOCUMENT",), ("QUESTION", "SOLUTION")}:
            raise ValueError("annotation manifest source roles are invalid")
        if tuple(value.document_role for value in self.outputs) != source_roles:
            raise ValueError("annotation manifest outputs differ from source roles")
        if content_sha256([value.model_dump(mode="json") for value in self.annotations]) != (
            self.annotation_set_sha256
        ):
            raise ValueError("annotation manifest set hash differs")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("annotation manifest self-hash differs")
        return self


class DocumentReviewPdfAnnotationResult(FrozenModel):
    schema_version: Literal["document-review-pdf-annotation-result/1.0"] = (
        "document-review-pdf-annotation-result/1.0"
    )
    annotation_id: Annotated[str, Field(pattern=r"^docannotation_[0-9a-f]{32}$")]
    workflow_id: Annotated[str, Field(pattern=r"^workflow_[0-9a-f]{32}$")]
    request_sha256: Sha256
    review_result_sha256: Sha256
    annotation_set_sha256: Sha256
    outputs: tuple[DocumentReviewAnnotatedPdfMember, ...] = Field(min_length=1, max_length=2)
    manifest_sha256: Sha256
    result_sha256: Sha256

    @model_validator(mode="after")
    def require_exact_result(self) -> DocumentReviewPdfAnnotationResult:
        roles = tuple(value.document_role for value in self.outputs)
        if roles not in {("DOCUMENT",), ("QUESTION", "SOLUTION")}:
            raise ValueError("annotation result output roles are invalid")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"result_sha256"}))
            != self.result_sha256
        ):
            raise ValueError("annotation result self-hash differs")
        return self
