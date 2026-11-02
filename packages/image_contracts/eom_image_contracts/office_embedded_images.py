"""Whole source raster identities; no file I/O, authority or document registration."""

from typing import Literal, Self

from pydantic import Field, model_validator

from eom_image_contracts.models import FrozenModel, Sha256, content_sha256
from eom_image_contracts.validation import validate_contract

OFFICE_EMBEDDED_IMAGE_SET_REF = "eom://schemas/image-provider/office-embedded-image-set/1.0"


class OfficeEmbeddedImage(FrozenModel):
    source_member: str = Field(min_length=1, max_length=256, pattern=r"^BinData/[^/\\]+$")
    source_member_sha256: Sha256
    source_format: Literal["PNG", "JPEG", "BMP", "GIF", "TIFF"]
    pixel_sha256: Sha256
    member_path: str = Field(pattern=r"^images/[0-9a-f]{64}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    content_length: int = Field(strict=True, ge=24, le=64 * 1024 * 1024)

    @model_validator(mode="after")
    def bounded_identity(self) -> Self:
        if (
            self.source_member.endswith(("/.", "/.."))
            or any(ord(char) < 32 for char in self.source_member)
            or self.member_path != f"images/{self.sha256[7:]}.png"
            or self.width_px * self.height_px > 20_000_000
        ):
            raise ValueError("OFFICE_EMBEDDED_IMAGE_INVALID")
        return self


class OfficeEmbeddedImageSet(FrozenModel):
    schema_version: Literal["office-embedded-image-set/1.0"] = "office-embedded-image-set/1.0"
    source_sha256: Sha256
    source_format: Literal["HWP5", "HWPX"]
    extractor_profile: Literal["WHOLE_EMBEDDED_RASTER_V1"] = "WHOLE_EMBEDDED_RASTER_V1"
    images: tuple[OfficeEmbeddedImage, ...] = Field(max_length=512)
    unsupported_members: tuple[str, ...] = Field(max_length=512)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def closed_manifest(self) -> Self:
        value = self.model_dump(mode="json")
        validate_contract("office-embedded-image-set", value)
        members = tuple(image.source_member for image in self.images)
        if (
            members != tuple(sorted(set(members)))
            or self.unsupported_members != tuple(sorted(set(self.unsupported_members)))
            or set(members) & set(self.unsupported_members)
            or sum(image.width_px * image.height_px for image in self.images) > 100_000_000
            or self.manifest_sha256
            != content_sha256({k: v for k, v in value.items() if k != "manifest_sha256"})
        ):
            raise ValueError("OFFICE_EMBEDDED_IMAGE_SET_INVALID")
        return self
