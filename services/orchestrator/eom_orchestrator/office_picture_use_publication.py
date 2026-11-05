"""Publish one original-image catalog and reuse its exact members in Items."""

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from eom_catalog_contracts.assessment_item import ImageBlock, MediaArtifactPointer
from eom_catalog_contracts.creative_source_draft import SourceImageBlock
from eom_catalog_contracts.creative_source_visuals import CREATIVE_SOURCE_VISUAL_IMAGE_REF
from eom_catalog_contracts.external_item_learning_result_v2 import (
    ExternalItemLearningResultV2,
    SourceItemLearningObservation,
)
from eom_catalog_contracts.office_item_learning import (
    OfficeItemLearningWorkInput,
    OfficePictureCatalogArtifact,
    OfficeVisualBindings,
    validate_office_visual_bindings,
    validate_source_office_visual_bindings,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImage
from eom_image_contracts.office_picture_uses import (
    OFFICE_PICTURE_USE_CATALOG_REF,
    OfficePictureUseCatalog,
    OfficePictureView,
)
from eom_protocol.artifact_members import ArtifactMemberPointer

from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import (
    ControlFileSetMember,
    ControlFileSetPublisher,
)
from eom_orchestrator.office_picture_use_extraction import ExtractedOfficePictureUses


def read_office_picture_catalog(
    publisher: ControlFileSetPublisher,
    artifact: OfficePictureCatalogArtifact,
    *,
    expected_source_sha256: str,
) -> OfficePictureUseCatalog:
    """Caller authorizes the actual source; owner verifies the complete immutable file set."""
    published = publisher.read_published_revision(
        artifact_revision_id=artifact.artifact_revision_id,
        artifact_type=artifact.artifact_type,
    )
    if (
        published.artifact_id != artifact.artifact_id
        or published.primary_file != artifact.member_path
        or published.primary_sha256 != artifact.sha256
        or published.manifest_sha256 != artifact.file_set_manifest_sha256
        or Path(published.nas_path)
        != publisher.settings.nas_artifact_root
        / artifact.artifact_id
        / artifact.artifact_revision_id
    ):
        raise ValueError("OFFICE_CATALOG_ARTIFACT_POINTER_MISMATCH")
    payload = resolve_control_artifact_member(
        publisher.engine,
        ArtifactMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.artifact_revision_id,
            member_path=artifact.member_path,
            schema_ref=artifact.schema_ref,
            media_type="application/json",
            sha256=artifact.sha256,
        ),
        maximum_bytes=8 * 1024 * 1024,
    )
    catalog = OfficePictureUseCatalog.model_validate_json(payload)
    if catalog.embedded_images.source_sha256 != expected_source_sha256:
        raise ValueError("OFFICE_CATALOG_SOURCE_MISMATCH")
    return catalog


def publish_office_picture_catalog(
    publisher: ControlFileSetPublisher,
    extracted: ExtractedOfficePictureUses,
    *,
    source_commit: str,
    authorize_source: Callable[[], None],
) -> OfficePictureCatalogArtifact:
    """One canonical image Artifact, not one copy per input/selection/registered Item."""
    authorize_source()
    catalog = OfficePictureUseCatalog.model_validate(extracted.catalog.model_dump(mode="json"))
    manifest = canonical_json_bytes(catalog.model_dump(mode="json"))
    key = (
        "office-picture-catalog:"
        + content_sha256(
            {
                "source_sha256": catalog.embedded_images.source_sha256,
                "profile": catalog.extractor_profile,
                "catalog_sha256": sha256_bytes(manifest),
            }
        )[7:]
    )
    try:
        published = publisher.find_published(
            idempotency_key=key, artifact_type="control_office_picture_use_catalog"
        )
    except ControlPlaneError as exc:
        if exc.code != "CONTROL_FILE_SET_INCOMPLETE":
            raise
        # Only the existing publication's supported resume may finish its bytes.
        # A FAILED or conflicting record is not treated as absent or successful.
        published = None
    if published is None:
        primary = extracted.workspace / "picture-use-catalog.json"
        if primary.is_symlink() or primary.read_bytes() != manifest:
            raise ValueError("OFFICE_CATALOG_LOCAL_MANIFEST_CHANGED")
        images: dict[str, OfficeEmbeddedImage | OfficePictureView] = {
            image.member_path: image for image in catalog.embedded_images.images
        }
        images.update({view.member_path: view for view in catalog.rendered_uses})
        if set(extracted.members) != {"picture-use-catalog.json", *images}:
            raise ValueError("OFFICE_CATALOG_LOCAL_CLOSURE_MISMATCH")
        members = [
            ControlFileSetMember(
                "picture-use-catalog.json",
                primary,
                sha256_bytes(manifest),
                len(manifest),
                OFFICE_PICTURE_USE_CATALOG_REF,
                "application/json",
            )
        ]
        members.extend(
            ControlFileSetMember(
                name,
                extracted.workspace / name,
                image.sha256,
                image.content_length,
                CREATIVE_SOURCE_VISUAL_IMAGE_REF,
                "image/png",
            )
            for name, image in images.items()
        )
        authorize_source()
        published = publisher.publish_first_observation(
            members=tuple(sorted(members, key=lambda member: member.file_name)),
            primary_file="picture-use-catalog.json",
            artifact_type="control_office_picture_use_catalog",
            manifest_version="office-picture-use-catalog-artifact/1.0",
            idempotency_key=key,
            source_commit=source_commit,
        )
    artifact = OfficePictureCatalogArtifact(
        artifact_id=published.artifact_id,
        artifact_revision_id=published.artifact_revision_id,
        sha256=published.primary_sha256,
        file_set_manifest_sha256=published.manifest_sha256,
    )
    authorize_source()
    if (
        read_office_picture_catalog(
            publisher, artifact, expected_source_sha256=catalog.embedded_images.source_sha256
        )
        != catalog
    ):
        raise ValueError("OFFICE_CATALOG_PUBLICATION_MISMATCH")
    return artifact


def resolve_office_source_images(
    publisher: ControlFileSetPublisher,
    *,
    work: OfficeItemLearningWorkInput,
    result: ExternalItemLearningResultV2,
    selection: OfficeVisualBindings,
) -> Mapping[str, ImageBlock]:
    """Main-body member pointers only; never call the historical PDF crop renderer."""
    catalog = read_office_picture_catalog(
        publisher,
        work.office_artifact,
        expected_source_sha256=work.source.preview_manifest.source_sha256,
    )
    validate_office_visual_bindings(selection, result=result, work=work, catalog=catalog)
    return _office_picture_image_blocks(
        result=result,
        selection=selection,
        catalog=catalog,
        artifact_id=work.office_artifact.artifact_id,
        artifact_revision_id=work.office_artifact.artifact_revision_id,
    )


def resolve_material_office_source_images(
    *,
    result: SourceItemLearningObservation,
    selection: OfficeVisualBindings,
    catalog: OfficePictureUseCatalog,
    catalog_pointer: ArtifactMemberPointer,
    expected_source_sha256: str,
) -> Mapping[str, ImageBlock]:
    """Reuse exact native USE pointers; caller resolves and authorizes the catalog bytes."""
    if catalog_pointer.schema_ref != OFFICE_PICTURE_USE_CATALOG_REF:
        raise ValueError("OFFICE_CATALOG_SCHEMA_INVALID")
    validate_source_office_visual_bindings(
        selection,
        result=result,
        catalog=catalog,
        expected_catalog_sha256=catalog_pointer.sha256,
        expected_source_sha256=expected_source_sha256,
    )
    return _office_picture_image_blocks(
        result=result,
        selection=selection,
        catalog=catalog,
        artifact_id=catalog_pointer.artifact_id,
        artifact_revision_id=catalog_pointer.artifact_revision_id,
    )


def _office_picture_image_blocks(
    *,
    result: SourceItemLearningObservation,
    selection: OfficeVisualBindings,
    catalog: OfficePictureUseCatalog,
    artifact_id: str,
    artifact_revision_id: str,
) -> Mapping[str, ImageBlock]:
    views = {view.use_id: view for view in catalog.rendered_uses}
    bindings = {binding.block_id: binding for binding in selection.bindings}
    images: dict[str, ImageBlock] = {}
    if result.proposal is not None:
        for block in result.proposal.content.body:
            if not isinstance(block, SourceImageBlock):
                continue
            view = views[bindings[block.block_id].picture_use_id]
            images[block.block_id] = ImageBlock(
                block_id=block.block_id,
                purpose=block.purpose,
                alt_text=block.alt_text,
                width_px=view.width_px,
                height_px=view.height_px,
                artifact=MediaArtifactPointer(
                    artifact_id=artifact_id,
                    artifact_revision_id=artifact_revision_id,
                    artifact_member=view.member_path,
                    sha256=view.sha256,
                    media_type="image/png",
                ),
            )
    return MappingProxyType(images)
