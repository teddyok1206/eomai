"""Ordered original image inputs for one concept phase, not a source-access grant."""

from typing import Literal, Self

from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from .control_schemas import validate_control_contract
from .kakao_concept_request import KakaoConceptWork


def concept_image_path(relative_path: str) -> str:
    return f"source/concepts/files/{relative_path}"


class ConceptCodexImageInput(FrozenModel):
    input_index: int = Field(strict=True, ge=1, le=72)
    relative_path: str = Field(
        pattern=r"^source/concepts/files/[A-Za-z0-9_-]+(?:[/.][A-Za-z0-9_-]+)*$", max_length=262
    )
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    sha256: Sha256
    bytes: int = Field(strict=True, ge=1, le=64 * 1024 * 1024)
    width_pixels: int = Field(strict=True, ge=1, le=30_000)
    height_pixels: int = Field(strict=True, ge=1, le=30_000)

    @model_validator(mode="after")
    def bounded_image(self) -> Self:
        if (
            any(part in {"", ".", ".."} for part in self.relative_path.split("/"))
            or self.width_pixels * self.height_pixels > 64_000_000
        ):
            raise ValueError("KAKAO_CONCEPT_IMAGE_INVALID")
        return self


class ConceptCodexImageManifest(FrozenModel):
    schema_version: Literal["codex-image-input-manifest/6.0"] = "codex-image-input-manifest/6.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    images: tuple[ConceptCodexImageInput, ...] = Field(min_length=1, max_length=72)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_order_hash_and_bounds(self) -> Self:
        validate_control_contract("codex-image-input-manifest-v6", self.model_dump(mode="json"))
        if (
            tuple(image.input_index for image in self.images)
            != tuple(range(1, len(self.images) + 1))
            or len({image.relative_path for image in self.images}) != len(self.images)
            or sum(image.bytes for image in self.images) > 128 * 1024 * 1024
            or sum(image.width_pixels * image.height_pixels for image in self.images) > 256_000_000
        ):
            raise ValueError("KAKAO_CONCEPT_IMAGE_SET_INVALID")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("KAKAO_CONCEPT_IMAGE_MANIFEST_HASH_MISMATCH")
        return self


def concept_image_manifest(
    plan_id: str, work: KakaoConceptWork
) -> ConceptCodexImageManifest | None:
    if not work.files:
        return None
    body = {
        "schema_version": "codex-image-input-manifest/6.0",
        "plan_id": plan_id,
        "images": [
            {
                "input_index": index,
                "relative_path": concept_image_path(file.relative_path),
                "media_type": file.source.media_type,
                "sha256": file.source.sha256,
                "bytes": file.size_bytes,
                "width_pixels": file.width_pixels,
                "height_pixels": file.height_pixels,
            }
            for index, file in enumerate(work.files, 1)
        ],
    }
    return ConceptCodexImageManifest.model_validate(
        {**body, "manifest_sha256": content_sha256(body)}
    )
