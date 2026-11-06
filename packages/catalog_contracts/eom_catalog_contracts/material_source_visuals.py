"""Exact PDF image derivations; native Hancom pictures use their original catalog."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.material_learning import MaterialArtifactMember, SourceRole
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

MATERIAL_VISUAL_SET_REF = "eom://schemas/material-learning/visual-set/1.0"


class MaterialPdfVisual(FrozenModel):
    source_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    input_index: int = Field(strict=True, ge=1, le=32)
    source_role: SourceRole
    physical_page: int = Field(strict=True, ge=1, le=2000)
    source_page: MaterialArtifactMember
    pdf: MaterialArtifactMember
    render_dpi: int = Field(strict=True, ge=120, le=400)
    pixel_box: tuple[int, int, int, int]
    member_path: str = Field(pattern=r"^images/extregion_[0-9a-f]{32}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    bytes: int = Field(strict=True, ge=1, le=16 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_geometry(self) -> Self:
        left, top, right, bottom = self.pixel_box
        if (
            not 0 <= left < right <= 10000
            or not 0 <= top < bottom <= 10000
            or (right - left, bottom - top) != (self.width_px, self.height_px)
            or self.member_path != f"images/{self.source_region_id}.png"
            or self.source_page.media_type != "image/png"
            or self.pdf.media_type != "application/pdf"
        ):
            raise ValueError("MATERIAL_VISUAL_GEOMETRY_INVALID")
        return self


class MaterialPdfVisualSet(FrozenModel):
    schema_version: Literal["material-learning-visual-set/1.0"] = "material-learning-visual-set/1.0"
    input_sha256: Sha256
    result_sha256: Sha256
    role_result: ArtifactMemberPointer
    pdftoppm_sha256: Sha256
    crops: tuple[MaterialPdfVisual, ...] = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_receipt(self) -> Self:
        validate_contract("material-learning-visual-set-v1", self.model_dump(mode="json"))
        keys = tuple(crop.source_region_id for crop in self.crops)
        if (
            keys != tuple(sorted(set(keys)))
            or self.role_result.schema_ref != "material-learning-result@1.0"
            or self.role_result.member_path != "result.json"
            or self.role_result.media_type != "application/json"
            or self.manifest_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        ):
            raise ValueError("MATERIAL_VISUAL_RECEIPT_INVALID")
        return self
