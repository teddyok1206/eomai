"""Catalog-owned resolution of one published legacy edition to an immutable Intake member."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eom_catalog_contracts.external_item_media import (
    EXTERNAL_ITEM_DOCUMENT_MAX_BYTES,
    ExternalItemDocumentMediaQuery,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService, VerifiedArtifactMemberStream
from eom_catalog_service.external_item_models import (
    USABLE_EXTERNAL_ITEM_INTAKE_STATES,
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.intake_service import INTAKE_SOURCE_FILE_SCHEMA_REF
from eom_catalog_service.models import ContentIntakeBatchRecord, ContentIntakeSourceFileRecord

ExternalDocumentMediaType = Literal["application/vnd.hancom.hwp", "application/vnd.hancom.hwpx"]
_MEDIA_EXTENSIONS = {
    "application/vnd.hancom.hwp": ".hwp",
    "application/vnd.hancom.hwpx": ".hwpx",
}


class ExternalItemDocumentMediaError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedExternalItemDocumentMedia:
    member: VerifiedArtifactMemberStream
    media_type: ExternalDocumentMediaType
    filename: str
    source_file_id: str
    artifact_id: str
    artifact_revision_id: str
    member_path: str


class ExternalItemDocumentMediaService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine)

    def open(self, query: ExternalItemDocumentMediaQuery) -> ResolvedExternalItemDocumentMedia:
        """Reject stale source revisions and unresolved editorial links before opening bytes."""

        with self.sessions() as session:
            row = session.execute(
                select(
                    ExternalItemSourceRecord,
                    ExternalItemSourceRevisionRecord,
                    ExternalItemImportRecord,
                    ExternalItemEditionDocumentRecord,
                    ContentIntakeSourceFileRecord,
                    ContentIntakeBatchRecord,
                )
                .join(
                    ExternalItemSourceRevisionRecord,
                    ExternalItemSourceRevisionRecord.revision_id
                    == ExternalItemSourceRecord.current_revision_id,
                )
                .join(
                    ExternalItemImportRecord,
                    ExternalItemImportRecord.import_id
                    == ExternalItemSourceRevisionRecord.import_id,
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
                .join(
                    ContentIntakeBatchRecord,
                    ContentIntakeBatchRecord.intake_batch_id
                    == ContentIntakeSourceFileRecord.intake_batch_id,
                )
                .where(
                    ExternalItemSourceRecord.source_id == query.source_id,
                    ExternalItemSourceRecord.current_revision_id == query.source_revision_id,
                    ExternalItemEditionDocumentRecord.edition == query.edition,
                )
            ).one_or_none()
            if row is None:
                raise ExternalItemDocumentMediaError(
                    "EXTERNAL_ITEM_DOCUMENT_UNAVAILABLE", "source edition is not current"
                )
            source, revision, imported, edition, document, batch = row
            if (
                revision.source_id != source.source_id
                or revision.external_number != source.external_number
                or imported.source_namespace != source.source_namespace
                or imported.state != "COMPLETED"
                or edition.document_sha256 != document.sha256
                or edition.source_file_id != document.source_file_id
                or document.declared_role != "DATA"
                or batch.state not in USABLE_EXTERNAL_ITEM_INTAKE_STATES
                or document.media_type not in _MEDIA_EXTENSIONS
                or not 0 < document.size_bytes <= EXTERNAL_ITEM_DOCUMENT_MAX_BYTES
            ):
                raise ExternalItemDocumentMediaError(
                    "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "source document pointer differs"
                )
            filename = _effective_filename(document.original_filename, document.media_type)
            pointer = (
                document.artifact_id,
                document.artifact_revision_id,
                document.relative_path,
                document.sha256,
                document.media_type,
                document.size_bytes,
            )

        try:
            member = self.artifacts.open_verified_member(
                artifact_id=pointer[0],
                revision_id=pointer[1],
                member_path=pointer[2],
                sha256=pointer[3],
                media_type=pointer[4],
                schema_ref=INTAKE_SOURCE_FILE_SCHEMA_REF,
                max_bytes=EXTERNAL_ITEM_DOCUMENT_MAX_BYTES,
            )
        except (OSError, ValueError) as exc:
            raise ExternalItemDocumentMediaError(
                "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "source document member differs"
            ) from exc
        if member.content_length != pointer[5]:
            member.stream.close()
            raise ExternalItemDocumentMediaError(
                "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "source document size differs"
            )
        return ResolvedExternalItemDocumentMedia(
            member=member,
            media_type=document.media_type,
            filename=filename,
            source_file_id=document.source_file_id,
            artifact_id=pointer[0],
            artifact_revision_id=pointer[1],
            member_path=pointer[2],
        )


def _effective_filename(original: str, media_type: str) -> str:
    if (
        not original
        or any(ord(character) < 32 or ord(character) == 127 for character in original)
        or "/" in original
        or "\\" in original
    ):
        raise ExternalItemDocumentMediaError(
            "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "source filename is unsafe"
        )
    extension = _MEDIA_EXTENSIONS[media_type]
    name = Path(original).with_suffix(extension).name
    if len(name) > 255:
        raise ExternalItemDocumentMediaError(
            "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "source filename exceeds limit"
        )
    return name
