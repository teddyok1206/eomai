"""Pinned derivative preview of one external Item's existing Intake document."""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.document_review import OfficeDocumentReviewConversionIdentity
from eom_catalog_contracts.models import FrozenModel, Sha256

EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA = "external-item-preview-manifest-v1"
EXTERNAL_ITEM_PREVIEW_MANIFEST_SCHEMA_REF = "eom://schemas/external-item/preview-manifest/1.0"
EXTERNAL_ITEM_PREVIEW_PDF_SCHEMA_REF = "eom://schemas/external-item/preview-pdf/1.0"


class ExternalItemPreviewManifest(FrozenModel):
    """One PDF projection; original Office bytes remain only in Content Intake."""

    schema_version: Literal["external-item-preview-manifest/1.0"] = (
        "external-item-preview-manifest/1.0"
    )
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    edition: int = Field(strict=True, ge=1, le=3)
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    source_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    source_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    source_member_path: str = Field(min_length=8, max_length=512, pattern=r"^source/.+$")
    source_schema_ref: Literal["eom://schemas/content-intake/source-file/1.0"] = (
        "eom://schemas/content-intake/source-file/1.0"
    )
    source_sha256: Sha256
    source_media_type: Literal["application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"]
    source_bytes: int = Field(strict=True, ge=8, le=100 * 1024 * 1024)
    source_format: Literal["HWP", "HWPX"]
    pdf_member_path: Literal["preview/original.pdf"] = "preview/original.pdf"
    pdf_sha256: Sha256
    pdf_bytes: int = Field(strict=True, ge=8, le=256 * 1024 * 1024)
    conversion: OfficeDocumentReviewConversionIdentity
    manifest_sha256: Sha256

    @field_validator("source_member_path")
    @classmethod
    def safe_source_member(cls, value: str) -> str:
        if (
            "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("source member path is unsafe")
        return value

    @model_validator(mode="after")
    def exact_source_and_conversion(self) -> Self:
        media_by_format = {
            "HWP": "application/vnd.hancom.hwp",
            "HWPX": "application/vnd.hancom.hwpx",
        }
        if self.source_media_type != media_by_format[self.source_format]:
            raise ValueError("source media type differs from detected Office format")
        if (
            self.conversion.conversion_kind != "LIBREOFFICE_H2ORESTART_PDF"
            or self.conversion.review_pdf_sha256 != self.pdf_sha256
        ):
            raise ValueError("preview PDF differs from its converter receipt")
        if self.manifest_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"manifest_sha256"})
        ):
            raise ValueError("external Item preview manifest hash differs")
        return self
