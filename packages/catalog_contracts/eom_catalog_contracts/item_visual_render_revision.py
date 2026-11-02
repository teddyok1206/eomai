"""Explicit HWPX read projection; source Revision approval and identity stay pinned."""

from typing import Any

from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_catalog_contracts.creative_visual_presentation import ItemVisualPresentation


def item_visual_render_revision(
    revision: dict[str, Any], presentation: ItemVisualPresentation
) -> dict[str, Any]:
    if (
        revision.get("item_id") != presentation.item_id
        or revision.get("item_revision_id") != presentation.item_revision_id
    ):
        raise ValueError("ITEM_VISUAL_RENDER_REVISION_MISMATCH")
    components = revision.get("components")
    if not isinstance(components, list):
        raise ValueError("ITEM_VISUAL_RENDER_COMPONENT_INVALID")
    contents = [
        v
        for v in components
        if isinstance(v, dict)
        and v.get("component_type") == "ITEM_CONTENT"
        and v.get("ordinal") == 0
    ]
    if len(contents) != 1:
        raise ValueError("ITEM_VISUAL_RENDER_COMPONENT_INVALID")
    component = contents[0]
    original = ArtifactMemberPointer(
        artifact_id=component["artifact_id"],
        artifact_revision_id=component["artifact_revision_id"],
        member_path=component["logical_name"],
        schema_ref=component["schema_ref"],
        media_type=component["media_type"],
        sha256=component["sha256"],
    )
    if original != presentation.source_content:
        raise ValueError("ITEM_VISUAL_RENDER_SOURCE_MISMATCH")
    if presentation.recovery_manifest is None:
        return revision
    pointer = presentation.display_content
    updated = dict(component) | {
        "artifact_id": pointer.artifact_id,
        "artifact_revision_id": pointer.artifact_revision_id,
        "logical_name": pointer.member_path,
        "schema_ref": pointer.schema_ref,
        "media_type": pointer.media_type,
        "sha256": pointer.sha256,
        "metadata": dict(component.get("metadata", {}))
        | {
            "visual_presentation": presentation.recovery_manifest.model_dump(mode="json"),
            "canonical_content": presentation.source_content.model_dump(mode="json"),
        },
    }
    return dict(revision) | {
        "components": [updated if value is component else value for value in components],
    }
