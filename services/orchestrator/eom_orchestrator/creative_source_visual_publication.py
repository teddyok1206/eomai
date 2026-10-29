"""Commit exact source crops through the existing Orchestrator file-set owner."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from eom_catalog_contracts.assessment_item import ImageBlock, MediaArtifactPointer
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.creative_source_visuals import (
    CREATIVE_SOURCE_VISUAL_IMAGE_REF,
    CREATIVE_SOURCE_VISUAL_SET_REF,
    CreativeSourceVisualSet,
    validate_creative_source_visual_set,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_learning_work import (
    ExternalItemLearningWorkInput,
    validate_external_item_learning_result_for_work,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_page_publication import (
    read_external_item_learning_page_artifact,
)
from eom_orchestrator.external_item_learning_page_render import render_creative_source_visuals
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
    PublishedControlFileSet,
)

CREATIVE_SOURCE_VISUAL_ARTIFACT_TYPE = "control_creative_source_visuals"
_PRIMARY = "visual-set.json"


@dataclass(frozen=True, slots=True)
class ResolvedCreativeSourceVisuals:
    publication: PublishedControlFileSet
    receipt: CreativeSourceVisualSet
    images: Mapping[str, ImageBlock]


def read_creative_source_visuals(
    publisher: ControlFileSetPublisher,
    publication: PublishedControlFileSet,
    *,
    work: ExternalItemLearningWorkInput,
    result: ExternalItemLearningResultV2,
    role_result: ArtifactMemberPointer,
) -> ResolvedCreativeSourceVisuals:
    """Reauthorize at the caller; verify exact Artifact and derivation here, not latest."""
    actual = publisher.read_published_revision(
        artifact_revision_id=publication.artifact_revision_id,
        artifact_type=CREATIVE_SOURCE_VISUAL_ARTIFACT_TYPE,
    )
    if actual != publication or actual.primary_file != _PRIMARY:
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_IDENTITY_MISMATCH")
    payload = resolve_control_artifact_member(
        publisher.engine,
        ArtifactMemberPointer(
            artifact_id=actual.artifact_id,
            artifact_revision_id=actual.artifact_revision_id,
            member_path=_PRIMARY,
            sha256=actual.primary_sha256,
            schema_ref=CREATIVE_SOURCE_VISUAL_SET_REF,
            media_type="application/json",
        ),
        maximum_bytes=128 * 1024,
    )
    receipt = CreativeSourceVisualSet.model_validate_json(payload)
    validate_creative_source_visual_set(receipt, work=work, result=result, role_result=role_result)
    assert result.proposal is not None
    crops = {crop.source_region_id: crop for crop in receipt.crops}
    images = {}
    for block in result.proposal.content.body:
        if not isinstance(block, SourceImageBlock):
            continue
        crop = crops[block.source_region_id]
        images[block.block_id] = ImageBlock(
            block_id=block.block_id,
            purpose=block.purpose,
            alt_text=block.alt_text,
            width_px=crop.width_px,
            height_px=crop.height_px,
            artifact=MediaArtifactPointer(
                artifact_id=actual.artifact_id,
                artifact_revision_id=actual.artifact_revision_id,
                artifact_member=crop.member_path,
                sha256=crop.sha256,
                media_type="image/png",
            ),
        )
    # read_published_revision validates all PNG member SHA/size/media declarations.
    # No second copy of PNG bytes is materialized just to construct typed pointers.
    return ResolvedCreativeSourceVisuals(actual, receipt, MappingProxyType(images))


def publish_creative_source_visuals(
    publisher: ControlFileSetPublisher,
    *,
    work: ExternalItemLearningWorkInput,
    result: ExternalItemLearningResultV2,
    role_result: ArtifactMemberPointer,
    pdf_bytes: bytes,
    workspace: Path,
    source_commit: str,
    authorize_source: Callable[[], None],
) -> ResolvedCreativeSourceVisuals | None:
    """Caller resolves completed role/source and reauthorizes before and after.

    The bounded PDF parser runs in the existing eom-image sandbox. The worker
    never supplies the published pointers. All NAS writes belong to the existing
    resumable publisher; incomplete commits reuse their exact idempotency key.
    """
    work = ExternalItemLearningWorkInput.model_validate(work.model_dump(mode="json"))
    result = ExternalItemLearningResultV2.model_validate(result.model_dump(mode="json"))
    validate_external_item_learning_result_for_work(result, work)
    if (
        role_result.schema_ref != "external-item-learning-result@2.0"
        or role_result.member_path != "result.json"
        or role_result.media_type != "application/json"
    ):
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_ROLE_INVALID")
    authorize_source()
    if result.proposal is None:
        raise ValueError("CREATIVE_VISUAL_PUBLICATION_PROPOSAL_MISSING")
    if not any(isinstance(block, SourceImageBlock) for block in result.proposal.content.body):
        return None
    read_external_item_learning_page_artifact(publisher, work.page_artifact)
    identity = {
        "schema_version": "creative-source-visual-set/1.0",
        "work_input_sha256": work.request_sha256,
        "result_sha256": result.result_sha256,
        "role_result": role_result.model_dump(mode="json"),
        "renderer": work.page_set.renderer.model_dump(mode="json"),
        "source_commit": source_commit,
    }
    key = "creative-visuals:" + content_sha256(identity)[7:]
    try:
        existing = publisher.find_published(
            idempotency_key=key, artifact_type=CREATIVE_SOURCE_VISUAL_ARTIFACT_TYPE
        )
    except ControlPlaneError as exc:
        if exc.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        # Recreate only the deterministic local input for the existing commit.
        # publish_first_observation still rejects FAILED/conflicting history and
        # a damaged SUCCEEDED Artifact. It cannot relabel either as successful.
        existing = None
    if existing is not None:
        resolved = read_creative_source_visuals(
            publisher, existing, work=work, result=result, role_result=role_result
        )
        authorize_source()
        return resolved
    outputs = render_creative_source_visuals(
        work.source, work.page_set, result, pdf_bytes, workspace=workspace
    )
    pages = {page.physical_page: page for page in work.page_set.pages}
    regions = {region.region_id: region for region in result.regions}
    value = {
        "schema_version": "creative-source-visual-set/1.0",
        "source_id": work.source.source_id,
        "source_revision_id": work.source.source_revision_id,
        "source_input_sha256": work.source.input_sha256,
        "work_input_sha256": work.request_sha256,
        "pdf_sha256": work.source.preview_manifest.pdf_sha256,
        "role_result": role_result.model_dump(mode="json"),
        "result_sha256": result.result_sha256,
        "page_artifact": work.page_artifact.model_dump(mode="json"),
        "renderer": work.page_set.renderer.model_dump(mode="json"),
        "crops": [
            {
                "source_region_id": output.source_region_id,
                "physical_page": output.physical_page,
                "source_page_member": pages[output.physical_page].member_path,
                "source_page_sha256": output.source_page_sha256,
                "bounding_box": regions[output.source_region_id].bounding_box.model_dump(
                    mode="json"
                ),
                "pixel_box": output.pixel_box,
                "member_path": output.member_path,
                "sha256": output.sha256,
                "width_px": output.width_px,
                "height_px": output.height_px,
                "content_length": output.content_length,
            }
            for output in sorted(outputs, key=lambda entry: entry.source_region_id)
        ],
    }
    receipt = CreativeSourceVisualSet.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    validate_creative_source_visual_set(receipt, work=work, result=result, role_result=role_result)
    payload = canonical_json_bytes(receipt.model_dump(mode="json"))
    primary = workspace / _PRIMARY
    with primary.open("xb") as stream:
        stream.write(payload)
    primary.chmod(0o400)
    authorize_source()
    publication = publisher.publish_first_observation(
        members=tuple(
            sorted(
                (
                    ControlFileSetMember(
                        _PRIMARY,
                        primary,
                        sha256_bytes(payload),
                        len(payload),
                        CREATIVE_SOURCE_VISUAL_SET_REF,
                        "application/json",
                    ),
                    *(
                        ControlFileSetMember(
                            output.member_path,
                            output.path,
                            output.sha256,
                            output.content_length,
                            CREATIVE_SOURCE_VISUAL_IMAGE_REF,
                            "image/png",
                        )
                        for output in outputs
                    ),
                ),
                key=lambda member: member.file_name,
            )
        ),
        primary_file=_PRIMARY,
        artifact_type=CREATIVE_SOURCE_VISUAL_ARTIFACT_TYPE,
        manifest_version=receipt.schema_version,
        idempotency_key=key,
        source_commit=source_commit,
    )
    authorize_source()
    return read_creative_source_visuals(
        publisher, publication, work=work, result=result, role_result=role_result
    )
