"""Byte-specific photo receipt; observation identity belongs to source admission."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_catalog_contracts.kakao_archive import KakaoBindingId
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MEDIA_BLOB_REF = "eom://schemas/kakao-archive/media-blob/1.0"
MEDIA_FORMAT_REF = "eom://formats/kakao-archive/source-image/1.0"
MAX_MEDIA_BYTES = 32 * 1024 * 1024
MAX_MEDIA_PIXELS = 50_000_000


class KakaoMediaBlobReceipt(FrozenModel):
    schema_version: Literal["kakao-media-blob/1.0"] = "kakao-media-blob/1.0"
    source_binding_id: KakaoBindingId
    source_sha256: Sha256
    source_bytes: int = Field(strict=True, ge=1, le=MAX_MEDIA_BYTES)
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    width_px: int = Field(strict=True, ge=1, le=30_000)
    height_px: int = Field(strict=True, ge=1, le=30_000)
    pixel_count: int = Field(strict=True, ge=1, le=MAX_MEDIA_PIXELS)
    original_bytes_preserved: Literal[True] = True

    @field_validator("original_bytes_preserved", mode="before")
    @classmethod
    def preserved(cls, value: object) -> object:
        if value is not True:
            raise ValueError("KAKAO_ARCHIVE_MEDIA_ORIGINAL_REQUIRED")
        return value

    @model_validator(mode="after")
    def exact_pixels(self) -> Self:
        if self.width_px * self.height_px != self.pixel_count:
            raise ValueError("KAKAO_ARCHIVE_MEDIA_DIMENSIONS_INVALID")
        validate_contract("kakao-media-blob-v1", self.model_dump(mode="json"))
        return self
