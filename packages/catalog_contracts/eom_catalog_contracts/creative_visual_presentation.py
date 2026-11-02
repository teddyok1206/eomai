"""Source-bound visual renditions; canonical Item/Graph/solution identities do not change."""

from typing import Final, Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.assessment_item import AssessmentItemContentContract
from eom_catalog_contracts.legacy_assessment import NormalizedBoundingBox
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime

VISUAL_PRESENTATION_PROFILE: Final[Literal["WHOLE_HANCOM_SOURCE_IMAGES_V1"]] = (
    "WHOLE_HANCOM_SOURCE_IMAGES_V1"
)
VISUAL_PRESENTATION_ARTIFACT_TYPE = "control_creative_source_visual_presentation"
VISUAL_PRESENTATION_SCHEMA_REF = "eom://schemas/external-item/creative-visual-presentation/1.0"
VISUAL_PRESENTATION_CONTENT_SCHEMA_REF = "eom://schemas/item-registry/assessment-item-content-v1"
VISUAL_PRESENTATION_MEMBER = "visual-presentation.json"
VISUAL_PRESENTATION_CONTENT_MEMBER: Final[Literal["assessment-item-content.json"]] = (
    "assessment-item-content.json"
)


class EmbeddedSourceImageProof(FrozenModel):
    """One selected original stream, not a path to arbitrary worker bytes."""

    source_member: str = Field(pattern=r"^BinData/[^/\\]+$", max_length=256)
    source_member_sha256: Sha256
    pixel_sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    source_object_number: int = Field(strict=True, ge=1, le=1_000_000)


class RecoveredSourceVisual(FrozenModel):
    canonical_block_id: str = Field(pattern=r"^block_[a-z][a-z0-9_]{0,63}$")
    display_block_id: str = Field(pattern=r"^block_restored_[0-9a-f]{24}$")
    source_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    target_region_id: str = Field(pattern=r"^extregion_[0-9a-f]{32}$")
    physical_page: int = Field(strict=True, ge=1, le=32)
    target_box: NormalizedBoundingBox
    source_images: tuple[EmbeddedSourceImageProof, ...] = Field(min_length=1, max_length=64)
    member_path: str = Field(pattern=r"^images/[0-9a-f]{64}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    content_length: int = Field(strict=True, ge=24, le=16 * 1024 * 1024)
    source_image_crops: Literal[0] = 0
    page_captures: Literal[0] = 0
    reference_original_used: Literal[False] = False

    @model_validator(mode="after")
    def complete_group(self) -> Self:
        members = tuple(image.source_member for image in self.source_images)
        if (
            len(members) != len(set(members))
            or self.member_path != f"images/{self.sha256[7:]}.png"
            or self.width_px * self.height_px > 20_000_000
        ):
            raise ValueError("CREATIVE_RECOVERED_VISUAL_INVALID")
        return self


class CreativeVisualPresentationManifest(FrozenModel):
    schema_version: Literal["creative-visual-presentation/1.0"] = "creative-visual-presentation/1.0"
    profile: Literal["WHOLE_HANCOM_SOURCE_IMAGES_V1"] = VISUAL_PRESENTATION_PROFILE
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_id: str = Field(pattern=r"^extitem_[0-9a-f]{32}$")
    source_revision_id: str = Field(pattern=r"^extitemrev_[0-9a-f]{32}$")
    canonical_content: ArtifactMemberPointer
    source_document: ArtifactMemberPointer
    source_pdf: ArtifactMemberPointer
    role_result: ArtifactMemberPointer
    role_work_sha256: Sha256
    content_member: Literal["assessment-item-content.json"] = VISUAL_PRESENTATION_CONTENT_MEMBER
    content_sha256: Sha256
    nonvisual_content_sha256: Sha256
    visuals: tuple[RecoveredSourceVisual, ...] = Field(min_length=1, max_length=64)
    authorized_by_operator_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    verification: Literal["CODEX_OPERATOR_ASSISTED_SOURCE_COMPARISON"] = (
        "CODEX_OPERATOR_ASSISTED_SOURCE_COMPARISON"
    )
    created_at: UtcDatetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def exact_derivation(self) -> Self:
        original = tuple(visual.canonical_block_id for visual in self.visuals)
        displayed = tuple(visual.display_block_id for visual in self.visuals)
        value = self.model_dump(mode="json")
        if (
            len(original) != len(set(original))
            or len(displayed) != len(set(displayed))
            or set(original) & set(displayed)
            or self.canonical_content.media_type != "application/json"
            or self.source_document.media_type
            not in {"application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"}
            or self.source_pdf.media_type != "application/pdf"
            or self.role_result.media_type != "application/json"
            or self.manifest_sha256
            != content_sha256({k: v for k, v in value.items() if k != "manifest_sha256"})
        ):
            raise ValueError("CREATIVE_VISUAL_PRESENTATION_MANIFEST_INVALID")
        return self


class ItemVisualPresentationQuery(FrozenModel):
    operation: Literal["GET_ITEM_VISUAL_PRESENTATION"] = "GET_ITEM_VISUAL_PRESENTATION"
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")


class ItemVisualPresentation(FrozenModel):
    item_id: str = Field(pattern=r"^item_[a-z0-9]{8,59}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[a-z0-9]{8,55}$")
    source_content: ArtifactMemberPointer
    display_content: ArtifactMemberPointer
    recovery_manifest: ArtifactMemberPointer | None = None
    content: AssessmentItemContentContract

    @model_validator(mode="after")
    def identified_rendering(self) -> Self:
        if (
            self.source_content.media_type != "application/json"
            or self.display_content.media_type != "application/json"
            or (self.recovery_manifest is None) != (self.source_content == self.display_content)
            or (
                self.recovery_manifest is not None
                and (
                    self.recovery_manifest.schema_ref != VISUAL_PRESENTATION_SCHEMA_REF
                    or self.recovery_manifest.member_path != VISUAL_PRESENTATION_MEMBER
                    or self.recovery_manifest.artifact_id != self.display_content.artifact_id
                    or self.recovery_manifest.artifact_revision_id
                    != self.display_content.artifact_revision_id
                )
            )
        ):
            raise ValueError("ITEM_VISUAL_PRESENTATION_POINTER_INVALID")
        return self


class ItemVisualPresentationResponse(FrozenModel):
    operation: Literal["GET_ITEM_VISUAL_PRESENTATION"] = "GET_ITEM_VISUAL_PRESENTATION"
    status: Literal["OK", "ERROR"]
    presentation: ItemVisualPresentation | None = None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,127}$")

    @model_validator(mode="after")
    def exact_variant(self) -> Self:
        if (self.status == "OK" and (self.presentation is None or self.error_code is not None)) or (
            self.status == "ERROR" and (self.presentation is not None or self.error_code is None)
        ):
            raise ValueError("ITEM_VISUAL_PRESENTATION_RESPONSE_INVALID")
        return self


def visual_presentation_key(item_revision_id: str) -> str:
    ItemVisualPresentationQuery(item_revision_id=item_revision_id)
    return "creative-visual-presentation-v1:" + item_revision_id
