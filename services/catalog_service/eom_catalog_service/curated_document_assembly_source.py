"""Catalog-owned current-source resolution for a curated document placement.

The caller must authorize CONTENT_INTAKE_READ. This pins one validated Intake
member without promoting the source-only row to a canonical Item.
"""

from __future__ import annotations

from enum import StrEnum
from typing import cast

from eom_catalog_contracts import CuratedExternalDocumentPlacement, OriginArtifactMemberPointer
from eom_catalog_contracts.curated_document_assembly_draft import ExternalSourcePlacement
from eom_catalog_contracts.external_item_media import ExternalItemDocumentMediaQuery
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService
from eom_catalog_service.external_item_matching import ExternalItemMatchStatus
from eom_catalog_service.external_item_models import (
    USABLE_EXTERNAL_ITEM_INTAKE_STATES,
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ContentIntakeBatchRecord, ContentIntakeSourceFileRecord

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

type _SourceDocumentRow = tuple[
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
    ExternalItemImportRecord,
    ExternalItemEditionDocumentRecord,
    ContentIntakeSourceFileRecord,
]


class CuratedDocumentAssemblySourceError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _SourceAdmission(StrEnum):
    CURRENT_SELECTION = "CURRENT_SELECTION"
    PINNED_REVISION = "PINNED_REVISION"


def resolve_pinned_curated_external_documents(
    session: Session, selections: tuple[ExternalSourcePlacement, ...]
) -> tuple[CuratedExternalDocumentPlacement, ...]:
    """Resolve exact Intake metadata for a versioned content placement/copy.

    This never opens files. The output/materialization owner verifies bytes when
    they are actually used. Released private V1 still requires the current source.
    """
    return _resolve_external_metadata(session, selections, _SourceAdmission.PINNED_REVISION)


def resolve_curated_external_document(
    session: Session,
    media: ExternalItemDocumentMediaService,
    selection: ExternalSourcePlacement,
) -> CuratedExternalDocumentPlacement:
    """Validate the current edition and hash-check its exact Artifact member.

    The source pointer can advance after this read; the immutable selection is
    reauthorized again before any later build. A row lock would require UPDATE
    privilege on this read-only Catalog runtime boundary.
    """

    resolved = _resolve_external_metadata(session, (selection,))[0]
    opened = media.open(
        ExternalItemDocumentMediaQuery(
            source_id=resolved.source_id,
            source_revision_id=resolved.source_revision_id,
            edition=resolved.edition,
        )
    )
    try:
        pointer = resolved.document_artifact
        if (
            opened.source_file_id != resolved.source_file_id
            or opened.artifact_id != pointer.artifact_id
            or opened.artifact_revision_id != pointer.artifact_revision_id
            or opened.member_path != pointer.member_path
            or opened.media_type != pointer.media_type
            or opened.member.sha256 != pointer.sha256
            or opened.member.content_length != resolved.document_size_bytes
        ):
            raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_POINTER_INVALID")
        return resolved
    finally:
        opened.member.stream.close()


def reauthorize_curated_external_documents(
    session: Session,
    placements: tuple[CuratedExternalDocumentPlacement, ...],
) -> None:
    """Batch-check saved pointer metadata; bytes are checked at staging/download.

    A status poll must not reopen and rehash every source document. This read is
    bounded to one indexed source/edition join for the complete selection.
    """
    selections = tuple(
        ExternalSourcePlacement.model_validate(
            {name: getattr(row, name) for name in ExternalSourcePlacement.model_fields}
        )
        for row in placements
    )
    if _resolve_external_metadata(session, selections) != placements:
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_POINTER_INVALID")


def _resolve_external_metadata(
    session: Session,
    selections: tuple[ExternalSourcePlacement, ...],
    admission: _SourceAdmission = _SourceAdmission.CURRENT_SELECTION,
) -> tuple[CuratedExternalDocumentPlacement, ...]:
    if not selections:
        return ()
    keys = {(row.source_id, row.source_revision_id, row.edition) for row in selections}
    if len(keys) != len(selections) or len(selections) > 200:
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_SELECTION_INVALID")
    statement = (
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
            == ExternalItemSourceRecord.current_revision_id
            if admission is _SourceAdmission.CURRENT_SELECTION
            else ExternalItemSourceRevisionRecord.source_id == ExternalItemSourceRecord.source_id,
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
            tuple_(
                ExternalItemSourceRecord.source_id,
                ExternalItemSourceRevisionRecord.revision_id,
                ExternalItemEditionDocumentRecord.edition,
            ).in_(tuple(sorted(keys))),
        )
    )
    if admission is _SourceAdmission.PINNED_REVISION:
        statement = statement.join(
            ContentIntakeBatchRecord,
            ContentIntakeBatchRecord.intake_batch_id
            == ContentIntakeSourceFileRecord.intake_batch_id,
        ).where(
            ContentIntakeBatchRecord.state.in_(tuple(USABLE_EXTERNAL_ITEM_INTAKE_STATES)),
            ContentIntakeSourceFileRecord.declared_role == "DATA",
        )
    rows = session.execute(statement).all()
    by_key = {
        (row[0].source_id, row[1].revision_id, row[3].edition): cast(_SourceDocumentRow, tuple(row))
        for row in rows
    }
    if len(rows) != len(keys) or set(by_key) != keys:
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_STALE")
    return tuple(
        _validated_placement(
            by_key[(selection.source_id, selection.source_revision_id, selection.edition)],
            selection,
            admission,
        )
        for selection in selections
    )


def _validated_placement(
    row: _SourceDocumentRow,
    selection: ExternalSourcePlacement,
    admission: _SourceAdmission = _SourceAdmission.CURRENT_SELECTION,
) -> CuratedExternalDocumentPlacement:
    source, revision, imported, binding, document = row
    if (
        admission is _SourceAdmission.CURRENT_SELECTION
        and source.current_revision_id != selection.source_revision_id
    ):
        raise CuratedDocumentAssemblySourceError("CURATED_SOURCE_STALE")
    if (
        revision.revision_id != selection.source_revision_id
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
