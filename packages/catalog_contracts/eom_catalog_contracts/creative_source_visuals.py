"""Immutable crop derivation receipt; source geometry is not a media pointer."""

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.external_item_learning_pages import ExternalItemLearningPageRenderer
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_learning_work import (
    ExternalItemLearningPageArtifact,
    ExternalItemLearningWorkInput,
    validate_external_item_learning_result_for_work,
)
from eom_catalog_contracts.legacy_assessment import NormalizedBoundingBox
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.validation import validate_contract

CREATIVE_SOURCE_VISUAL_SET_SCHEMA = "creative-source-visual-set-v1"
CREATIVE_SOURCE_VISUAL_SET_REF = "eom://schemas/external-item/creative-source-visual-set/1.0"
CREATIVE_SOURCE_VISUAL_IMAGE_REF = "eom://schemas/external-item/creative-source-visual-image/1.0"


class CreativeSourceVisualCrop(FrozenModel):
    source_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    physical_page: int = Field(strict=True, ge=1, le=32)
    source_page_member: str = Field(pattern=r"^pages/page-[0-9]{4}\.png$")
    source_page_sha256: Sha256
    bounding_box: NormalizedBoundingBox
    pixel_box: tuple[int, int, int, int]
    member_path: str = Field(pattern=r"^images/extregion_[0-9a-f]{32}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=2400)
    height_px: int = Field(strict=True, ge=1, le=2400)
    content_length: int = Field(strict=True, ge=24, le=16 * 1024 * 1024)

    @model_validator(mode="after")
    def exact_geometry(self) -> Self:
        left, top, right, bottom = self.pixel_box
        if (
            not 0 <= left < right <= 2400
            or not 0 <= top < bottom <= 2400
            or (right - left, bottom - top) != (self.width_px, self.height_px)
            or self.member_path != f"images/{self.source_region_id}.png"
            or self.source_page_member != f"pages/page-{self.physical_page:04d}.png"
        ):
            raise ValueError("CREATIVE_VISUAL_RECEIPT_GEOMETRY_INVALID")
        return self


class CreativeSourceVisualSet(FrozenModel):
    schema_version: Literal["creative-source-visual-set/1.0"] = "creative-source-visual-set/1.0"
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    source_input_sha256: Sha256
    work_input_sha256: Sha256
    pdf_sha256: Sha256
    role_result: ArtifactMemberPointer
    result_sha256: Sha256
    page_artifact: ExternalItemLearningPageArtifact
    renderer: ExternalItemLearningPageRenderer
    crops: tuple[CreativeSourceVisualCrop, ...] = Field(min_length=1, max_length=64)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_members_and_hash(self) -> Self:
        value = self.model_dump(mode="json")
        validate_contract(CREATIVE_SOURCE_VISUAL_SET_SCHEMA, value)
        regions = tuple(crop.source_region_id for crop in self.crops)
        if regions != tuple(sorted(set(regions))):
            raise ValueError("CREATIVE_VISUAL_RECEIPT_REGIONS_NOT_UNIQUE_ORDERED")
        if sum(crop.content_length for crop in self.crops) > 256 * 1024 * 1024:
            raise ValueError("CREATIVE_VISUAL_RECEIPT_TOO_LARGE")
        if self.manifest_sha256 != content_sha256(
            {key: item for key, item in value.items() if key != "manifest_sha256"}
        ):
            raise ValueError("CREATIVE_VISUAL_RECEIPT_HASH_MISMATCH")
        return self


def validate_creative_source_visual_set(
    receipt: CreativeSourceVisualSet,
    *,
    work: ExternalItemLearningWorkInput,
    result: ExternalItemLearningResultV2,
    role_result: ArtifactMemberPointer,
) -> None:
    """Bind every crop to an exact delivered page and a validated target recipe.

    Only metadata is inspected here; callers resolve Artifact lifecycle/media/SHA
    and parse PNG bytes at the existing materialization boundary. O(regions + crops).
    """
    receipt = CreativeSourceVisualSet.model_validate(receipt.model_dump(mode="json"))
    work = ExternalItemLearningWorkInput.model_validate(work.model_dump(mode="json"))
    result = ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json"))
    validate_external_item_learning_result_for_work(result, work)
    if result.proposal is None:
        raise ValueError("CREATIVE_VISUAL_RECEIPT_PROPOSAL_MISSING")
    if (
        receipt.source_id != work.source.source_id
        or receipt.source_revision_id != work.source.source_revision_id
        or receipt.source_input_sha256 != work.source.input_sha256
        or receipt.work_input_sha256 != work.request_sha256
        or receipt.pdf_sha256 != work.source.preview_manifest.pdf_sha256
        or receipt.page_artifact != work.page_artifact
        or receipt.renderer != work.page_set.renderer
        or receipt.role_result != role_result
        or receipt.result_sha256 != result.result_sha256
    ):
        raise ValueError("CREATIVE_VISUAL_RECEIPT_SOURCE_MISMATCH")
    expected = {
        block.source_region_id
        for block in result.proposal.content.body
        if isinstance(block, SourceImageBlock)
    }
    if {crop.source_region_id for crop in receipt.crops} != expected:
        raise ValueError("CREATIVE_VISUAL_RECEIPT_CROP_SET_MISMATCH")
    pages = {page.physical_page: page for page in work.page_set.pages}
    regions = {region.region_id: region for region in result.regions}
    for crop in receipt.crops:
        region = regions[crop.source_region_id]
        page = pages.get(region.physical_page)
        if page is None:
            raise ValueError("CREATIVE_VISUAL_RECEIPT_PAGE_MISSING")
        box = region.bounding_box
        expected_pixels = (
            box.left * page.width_px // 10000,
            box.top * page.height_px // 10000,
            (box.right * page.width_px + 9999) // 10000,
            (box.bottom * page.height_px + 9999) // 10000,
        )
        if (
            crop.physical_page != region.physical_page
            or crop.bounding_box != box
            or crop.source_page_member != page.member_path
            or crop.source_page_sha256 != page.sha256
            or crop.pixel_box != expected_pixels
        ):
            raise ValueError("CREATIVE_VISUAL_RECEIPT_PAGE_GEOMETRY_MISMATCH")
