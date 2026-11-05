"""Actual document page positions stay distinct from the ordered worker inputs."""

from typing import Literal, Self

from eom_catalog_contracts.material_learning import MaterialLearningWork, SourceRole
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_workflow.control_schemas import validate_control_contract


def material_page_path(role: SourceRole, physical_page: int, *, suffix: str = "png") -> str:
    if suffix not in {"png", "md"} or not 1 <= physical_page <= 2000:
        raise ValueError("MATERIAL_LEARNING_PAGE_PATH_INVALID")
    return f"source/material/{role.lower()}/page-{physical_page:06d}.{suffix}"


class MaterialCodexImageInput(FrozenModel):
    input_index: int = Field(strict=True, ge=1, le=32)
    source_role: SourceRole
    physical_page: int = Field(strict=True, ge=1, le=2000)
    relative_path: str = Field(
        pattern=r"^source/material/(?:main|solutions)/page-[0-9]{6}\.png$", max_length=80
    )
    media_type: Literal["image/png"] = "image/png"
    sha256: Sha256
    bytes: int = Field(strict=True, ge=24, le=16 * 1024 * 1024)
    width_pixels: int = Field(strict=True, ge=1, le=10000)
    height_pixels: int = Field(strict=True, ge=1, le=10000)

    @model_validator(mode="after")
    def source_path(self) -> Self:
        if self.relative_path != material_page_path(self.source_role, self.physical_page):
            raise ValueError("MATERIAL_LEARNING_IMAGE_SOURCE_PATH_MISMATCH")
        if self.width_pixels * self.height_pixels > 64_000_000:
            raise ValueError("MATERIAL_LEARNING_IMAGE_PIXELS_EXCEEDED")
        return self


class MaterialCodexImageManifest(FrozenModel):
    schema_version: Literal["codex-image-input-manifest/5.0"] = "codex-image-input-manifest/5.0"
    plan_id: str = Field(pattern=r"^execplan_[0-9a-f]{32}$")
    images: tuple[MaterialCodexImageInput, ...] = Field(min_length=1, max_length=32)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def ordered_and_bounded(self) -> Self:
        validate_control_contract("codex-image-input-manifest-v5", self.model_dump(mode="json"))
        if tuple(image.input_index for image in self.images) != tuple(
            range(1, len(self.images) + 1)
        ):
            raise ValueError("MATERIAL_LEARNING_IMAGE_INPUT_ORDER_INVALID")
        positions = {(image.source_role, image.physical_page) for image in self.images}
        if len(positions) != len(self.images):
            raise ValueError("MATERIAL_LEARNING_IMAGE_PAGE_DUPLICATE")
        if (
            sum(image.bytes for image in self.images) > 128 * 1024 * 1024
            or sum(image.width_pixels * image.height_pixels for image in self.images) > 256_000_000
        ):
            raise ValueError("MATERIAL_LEARNING_IMAGE_TOTAL_EXCEEDED")
        if (
            content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
            != self.manifest_sha256
        ):
            raise ValueError("MATERIAL_LEARNING_IMAGE_MANIFEST_HASH_MISMATCH")
        return self


def material_image_manifest(plan_id: str, work: MaterialLearningWork) -> MaterialCodexImageManifest:
    body = {
        "schema_version": "codex-image-input-manifest/5.0",
        "plan_id": plan_id,
        "images": [
            {
                "input_index": page.input_index,
                "source_role": page.source_role,
                "physical_page": page.physical_page,
                "relative_path": material_page_path(page.source_role, page.physical_page),
                "media_type": page.image.media_type,
                "sha256": page.image.sha256,
                "bytes": page.image.bytes,
                "width_pixels": page.width_pixels,
                "height_pixels": page.height_pixels,
            }
            for page in work.pages
        ],
    }
    return MaterialCodexImageManifest.model_validate(
        {**body, "manifest_sha256": content_sha256(body)}
    )
