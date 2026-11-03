"""Authorize one exact original Office input before isolated native-image extraction."""

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from eom_catalog_contracts.external_item_learning_source import ExternalItemLearningSource
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from eom_catalog_contracts.office_item_learning import OfficePictureCatalogArtifact
from eom_identifiers import sha256_bytes
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.office_picture_use_extraction import extract_office_picture_use_input
from eom_orchestrator.office_picture_use_publication import publish_office_picture_catalog
from eom_orchestrator.settings import Settings
from sqlalchemy import Engine

from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService


def prepare_office_item_learning_input(
    engine: Engine,
    *,
    source: ExternalItemLearningSource,
    publisher: ControlFileSetPublisher,
    settings: Settings,
    source_commit: str,
    authorize_source: Callable[[], None],
) -> OfficePictureCatalogArtifact:
    """No row locks span parsing; no permission is inferred from a file or a model.

    The existing original-document reader owns Intake lifecycle/member checks.
    Only the Orchestrator's existing publisher commits validated local results.
    """
    if settings.office_image_tool_root is None:
        raise ValueError("OFFICE_PICTURE_TOOLS_NOT_CONFIGURED")
    authorize_source()
    document = ExternalItemDocumentMediaService(engine).open(
        ExternalItemDocumentMediaQuery(
            source_id=source.source_id,
            source_revision_id=source.source_revision_id,
            edition=source.selected_edition,
        )
    )
    expected = source.preview_manifest
    try:
        if (
            document.source_file_id != expected.source_file_id
            or document.artifact_id != expected.source_artifact_id
            or document.artifact_revision_id != expected.source_artifact_revision_id
            or document.member_path != expected.source_member_path
            or document.member.sha256 != expected.source_sha256
            or document.member.content_length != expected.source_bytes
            or document.media_type != expected.source_media_type
            or not 0 < expected.source_bytes <= 256 * 1024 * 1024
        ):
            raise ValueError("OFFICE_PICTURE_ORIGINAL_POINTER_MISMATCH")
        payload = document.member.stream.read(expected.source_bytes + 1)
    finally:
        document.member.stream.close()
    if len(payload) != expected.source_bytes or sha256_bytes(payload) != expected.source_sha256:
        raise ValueError("OFFICE_PICTURE_ORIGINAL_HASH_MISMATCH")
    authorize_source()
    with TemporaryDirectory(prefix="office-item-input-", dir=settings.staging_root) as temporary:
        extracted = extract_office_picture_use_input(
            payload,
            expected_sha256=expected.source_sha256,
            tool_root=settings.office_image_tool_root,
            workspace=Path(temporary) / "extracted",
        )
        return publish_office_picture_catalog(
            publisher,
            extracted,
            source_commit=source_commit,
            authorize_source=authorize_source,
        )
