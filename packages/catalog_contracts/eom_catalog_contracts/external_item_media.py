"""Pinned source-file media request on the existing private Catalog socket."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.models import FrozenModel

EXTERNAL_ITEM_DOCUMENT_MAX_BYTES = 100 * 1024 * 1024
EXTERNAL_ITEM_PREVIEW_MAX_BYTES = 256 * 1024 * 1024


class ExternalItemDocumentMediaQuery(FrozenModel):
    operation: Literal["GET_EXTERNAL_ITEM_DOCUMENT_MEDIA"] = "GET_EXTERNAL_ITEM_DOCUMENT_MEDIA"
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    edition: int = Field(ge=1, le=3)


class ExternalItemDocumentMediaResponse(FrozenModel):
    status: Literal["OK", "ERROR"]
    operation: Literal["GET_EXTERNAL_ITEM_DOCUMENT_MEDIA"] = "GET_EXTERNAL_ITEM_DOCUMENT_MEDIA"
    media_type: Literal[
        "application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"
    ] | None = None
    content_length: int | None = Field(default=None, ge=1, le=EXTERNAL_ITEM_DOCUMENT_MAX_BYTES)
    sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str | None) -> str | None:
        if value is not None and (
            any(ord(character) < 32 or ord(character) == 127 for character in value)
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("document filename is unsafe")
        return value

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        fields = (self.media_type, self.content_length, self.sha256, self.filename)
        if self.status == "OK" and all(value is not None for value in fields):
            if self.error_code is None:
                return self
        elif self.status == "ERROR" and self.error_code is not None and all(
            value is None for value in fields
        ):
            return self
        raise ValueError("external Item document media response is incomplete")


class ExternalItemPreviewMediaQuery(FrozenModel):
    operation: Literal["GET_EXTERNAL_ITEM_PREVIEW_MEDIA"] = "GET_EXTERNAL_ITEM_PREVIEW_MEDIA"
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    edition: int = Field(strict=True, ge=1, le=3)


class ExternalItemPreviewMediaResponse(FrozenModel):
    status: Literal["OK", "ERROR"]
    operation: Literal["GET_EXTERNAL_ITEM_PREVIEW_MEDIA"] = "GET_EXTERNAL_ITEM_PREVIEW_MEDIA"
    media_type: Literal["application/pdf"] | None = None
    content_length: int | None = Field(
        default=None, strict=True, ge=8, le=EXTERNAL_ITEM_PREVIEW_MAX_BYTES
    )
    sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        if self.status == "OK":
            if (
                self.media_type == "application/pdf"
                and self.content_length is not None
                and self.sha256 is not None
                and self.error_code is None
            ):
                return self
        elif (
            self.error_code is not None
            and self.media_type is None
            and self.content_length is None
            and self.sha256 is None
        ):
            return self
        raise ValueError("external Item preview media response is incomplete")


class ExternalItemPreviewPrepareCommand(FrozenModel):
    operation: Literal["PREPARE_EXTERNAL_ITEM_PREVIEW"] = "PREPARE_EXTERNAL_ITEM_PREVIEW"
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    edition: int = Field(strict=True, ge=1, le=3)


class ExternalItemPreviewPrepareResponse(FrozenModel):
    operation: Literal["PREPARE_EXTERNAL_ITEM_PREVIEW"] = "PREPARE_EXTERNAL_ITEM_PREVIEW"
    status: Literal["OK", "ERROR"]
    sha256: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        if self.status == "OK" and self.sha256 is not None and self.error_code is None:
            return self
        if self.status == "ERROR" and self.sha256 is None and self.error_code is not None:
            return self
        raise ValueError("external Item preview prepare response is incomplete")
