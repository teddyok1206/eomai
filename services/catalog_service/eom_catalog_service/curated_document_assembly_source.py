"""Catalog-owned current-source resolution for a curated document placement.

The caller must authorize CONTENT_INTAKE_READ. This pins one validated Intake
member without promoting the source-only row to a canonical Item.
"""

from __future__ import annotations

from eom_catalog_contracts import CuratedExternalDocumentPlacement, OriginArtifactMemberPointer
from eom_catalog_contracts.curated_document_assembly_draft import ExternalSourcePlacement
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService
from eom_catalog_service.external_item_matching import ExternalItemMatchStatus
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_SOURCE_MEDIA = {
    "HWP": "application/vnd.hancom.hwp",
    "HWPX": "application/vnd.hancom.hwpx",
}
_READY_STATES = frozenset(
    {
        ExternalItemMatchStatus.MATCHED.value,
        ExternalItemMatchStatus.MATCHED_DETECTED_HWPX.value,
        ExternalItemMatchStatus.MATCHED_IDENTICAL_COPIES.value,
    }
)


class CuratedDocumentAssemblySourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_curated_external_document(
    session: Session,
    media: ExternalItemDocumentMediaService,
    selection: ExternalSourcePlacement,
) -> CuratedExternalDocumentPlacement:
    """Lock current row, validate exact edition, then hash-check its Artifact member."""

    row = session.execute(
        select(
            ExternalItemSourceRecord,
            ExternalItemSourceRevisionRecord,
            ExternalItemImportRecord,
            ExternalItemEditionDocumentRecord,
            ContentIntakeSourceFileRecord,
        )
        .join(
            ExternalItemSourceRevisionRecord,
            ExternalItemSourceRevisionRecord.revision_id
            == ExternalItemSourceRecord.current_revision_id,
        )
        .join(
            ExternalItemImportRecord,
            ExternalItemImportRecord.import_id == ExternalItemSourceRevisionRecord.import_id,
        )
        .join(
            ExternalItemEditionDocumentRecord,
            ExternalItemEditionDocumentRecord.source_revision_id
            == ExternalItemSourceRevisionRecord.revision_id,
        )
        .join(
            ContentIntakeSourceFileRecord,
            ContentIntakeSourceFileRecord.source_file_id
            == ExternalItemEditionDocumentRecord.source_file_id,
        )
        .where(
            ExternalItemSourceRecord.source_id == selection.source_id,
            ExternalItemSourceRecord.current_revision_id == selection.source_revision_id,
            ExternalItemEditionDocumentRecord.edition == selection.edition,
        )
        .with_for_update(read=True, of=ExternalItemSourceRecord)
    ).one_or_none()
    if row is None:
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_STALE")
    source, revision, imported, binding, document = row
    if (
        source.current_revision_id != selection.source_revision_id
        or revision.source_id != source.source_id
        or revision.observation_sha256 != selection.observation_sha256
        or revision.external_number != source.external_number
        or revision.import_id != imported.import_id
        or imported.state != "COMPLETED"
        or source.source_namespace != imported.source_namespace
        or revision.match_status not in _READY_STATES
        or binding.source_file_id != revision.selected_source_file_id
        or binding.match_status != revision.match_status
        or binding.source_revision_id != revision.revision_id
        or binding.document_sha256 != document.sha256
        or document.media_type != _SOURCE_MEDIA[selection.source_format]
    ):
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_POINTER_INVALID")

    resolved = media.open(
        ExternalItemDocumentMediaQuery(
            source_id=source.source_id,
            source_revision_id=revision.revision_id,
            edition=selection.edition,
        )
    )
    try:
        if (
            resolved.source_file_id != document.source_file_id
            or resolved.artifact_id != document.artifact_id
            or resolved.artifact_revision_id != document.artifact_revision_id
            or resolved.member_path != document.relative_path
            or resolved.media_type != document.media_type
            or resolved.member.sha256 != document.sha256
            or resolved.member.content_length != document.size_bytes
        ):
            raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_POINTER_INVALID")
        return CuratedExternalDocumentPlacement(
            position=selection.position,
            source_id=source.source_id,
            source_revision_id=revision.revision_id,
            external_number=source.external_number,
            observation_sha256=revision.observation_sha256,
            edition=selection.edition,
            source_format=selection.source_format,
            source_file_id=document.source_file_id,
            document_artifact=OriginArtifactMemberPointer(
                artifact_id=document.artifact_id,
                artifact_revision_id=document.artifact_revision_id,
                member_path=document.relative_path,
                schema_ref="eom://schemas/content-intake/source-file/1.0",
                media_type=document.media_type,
                sha256=document.sha256,
            ),
            document_size_bytes=document.size_bytes,
        )
    finally:
        resolved.member.stream.close()
