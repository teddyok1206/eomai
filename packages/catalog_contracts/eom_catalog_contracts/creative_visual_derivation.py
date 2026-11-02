"""Pure, linear-time visual-only rendering derivation; all scientific text stays exact."""

from eom_identifiers import content_sha256

from eom_catalog_contracts.assessment_item import AssessmentItemContent, ImageBlock
from eom_catalog_contracts.creative_visual_presentation import CreativeVisualPresentationManifest


def nonvisual_item_content_sha256(content: AssessmentItemContent) -> str:
    value = content.model_dump(mode="json")
    for block in value["body"]:
        if block["type"] == "image":
            for field in ("artifact", "width_px", "height_px"):
                block.pop(field)
    return content_sha256(value)


def derive_creative_visual_content(
    canonical: AssessmentItemContent,
    manifest: CreativeVisualPresentationManifest,
    *,
    artifact_id: str,
    artifact_revision_id: str,
) -> AssessmentItemContent:
    """Only named images change. Block order, alt text, labels and answers remain exact."""
    if nonvisual_item_content_sha256(canonical) != manifest.nonvisual_content_sha256:
        raise ValueError("CREATIVE_VISUAL_PRESENTATION_NONVISUAL_MISMATCH")
    replacements = {visual.canonical_block_id: visual for visual in manifest.visuals}
    source_images = {
        block.block_id: block for block in canonical.body if isinstance(block, ImageBlock)
    }
    if not replacements.keys() <= source_images.keys():
        raise ValueError("CREATIVE_VISUAL_PRESENTATION_BLOCK_MISSING")
    value = canonical.model_dump(mode="json")
    for block in value["body"]:
        visual = replacements.get(block["block_id"])
        if visual is None:
            continue
        block.update(
            block_id=visual.display_block_id,
            artifact={
                "artifact_id": artifact_id,
                "artifact_revision_id": artifact_revision_id,
                "artifact_member": visual.member_path,
                "sha256": visual.sha256,
                "media_type": "image/png",
            },
            width_px=visual.width_px,
            height_px=visual.height_px,
        )
    return AssessmentItemContent.model_validate(value)
