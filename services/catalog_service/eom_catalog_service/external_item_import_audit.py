"""Read-only reconciliation of immutable external Item rows with their source workbook."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from eom_catalog_contracts import ExternalItemWorkbookMapping, validate_contract
from eom_orchestrator.database import build_session_factory
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine, select

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.external_item_observations import (
    ExternalItemWorkbookPointer,
    bind_external_item_observation,
    external_item_search_facets,
)
from eom_catalog_service.external_item_xlsx import (
    DecodedExternalItemRow,
    read_external_item_rows_bytes,
)
from eom_catalog_service.intake_service import INTAKE_SOURCE_FILE_SCHEMA_REF
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_IMPORT_ID = re.compile(r"^extimport_[0-9a-f]{32}$")
_MATCHED = frozenset({"MATCHED", "MATCHED_DETECTED_HWPX", "MATCHED_IDENTICAL_COPIES"})


class ExternalItemImportAuditError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalItemImportAuditResult:
    import_id: str
    workbook_sha256: str
    row_count: int
    edition_link_count: int
    selected_document_count: int
    status_counts: tuple[tuple[str, int], ...]


def _verify_rows(
    decoded: tuple[DecodedExternalItemRow, ...],
    revisions: tuple[tuple[ExternalItemSourceRevisionRecord, ExternalItemSourceRecord], ...],
    *,
    mapping: ExternalItemWorkbookMapping,
    workbook: ExternalItemWorkbookPointer,
) -> Counter[str]:
    if len(decoded) != len(revisions):
        raise ExternalItemImportAuditError("EXTERNAL_ITEM_AUDIT_ROW_COUNT", "row count differs")
    counts: Counter[str] = Counter()
    for row, (revision, source) in zip(decoded, revisions, strict=True):
        observed = bind_external_item_observation(row, mapping=mapping, workbook=workbook)
        facets = external_item_search_facets(observed)
        if (
            revision.row_number != row.row_number
            or revision.external_number != row.external_number
            or source.source_id != revision.source_id
            or source.external_number != row.external_number
            or source.source_namespace != mapping.source_namespace
            or revision.worksheet_name != observed.worksheet_name
            or revision.observation_sha256 != observed.observation_sha256
            or revision.cells != [cell.model_dump(mode="json") for cell in observed.cells]
            or (
                revision.unit_major,
                revision.unit_minor,
                revision.field_label,
                revision.grade_label,
                revision.author_label,
            )
            != (facets.major_unit, facets.minor_unit, facets.field, facets.grade, facets.author)
        ):
            raise ExternalItemImportAuditError(
                "EXTERNAL_ITEM_AUDIT_ROW_MISMATCH",
                f"immutable workbook observation differs at row {row.row_number}",
            )
        counts[revision.match_status] += 1
    return counts


def _verify_editions(
    decoded: tuple[DecodedExternalItemRow, ...],
    revisions: tuple[tuple[ExternalItemSourceRevisionRecord, ExternalItemSourceRecord], ...],
    edition_rows: tuple[
        tuple[ExternalItemEditionDocumentRecord, ContentIntakeSourceFileRecord | None], ...
    ],
) -> None:
    by_revision: dict[str, list[ExternalItemEditionDocumentRecord]] = {}
    for edition, file in edition_rows:
        if edition.source_file_id is not None and (
            file is None or file.sha256 != edition.document_sha256
        ):
            raise ExternalItemImportAuditError(
                "EXTERNAL_ITEM_AUDIT_DOCUMENT_POINTER", "edition file pointer differs"
            )
        by_revision.setdefault(edition.source_revision_id, []).append(edition)
    for row, (revision, _) in zip(decoded, revisions, strict=True):
        links = by_revision.get(revision.revision_id, [])
        expected = tuple(
            number for number, column in ((1, 11), (2, 12), (3, 13)) if row.cells[column].raw_text
        )
        if tuple(link.edition for link in links) != expected:
            raise ExternalItemImportAuditError(
                "EXTERNAL_ITEM_AUDIT_EDITION_SET",
                f"edition observations differ at row {row.row_number}",
            )
        selected = [
            link
            for link in links
            if link.source_file_id == revision.selected_source_file_id
            and link.source_file_id is not None
            and link.edition in (2, 3)
        ]
        if (revision.match_status in _MATCHED) != bool(selected) or (
            revision.match_status not in _MATCHED and revision.selected_source_file_id is not None
        ):
            raise ExternalItemImportAuditError(
                "EXTERNAL_ITEM_AUDIT_SELECTED_DOCUMENT",
                f"selected document differs at row {row.row_number}",
            )


class ExternalItemImportAuditService:
    """Compare one completed import against its NAS workbook, without changing state."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)
        self.artifacts = CatalogArtifactService(engine)

    def verify(self, import_id: str) -> ExternalItemImportAuditResult:
        if _IMPORT_ID.fullmatch(import_id) is None:
            raise ExternalItemImportAuditError(
                "EXTERNAL_ITEM_AUDIT_ID_INVALID", "import ID is invalid"
            )
        with self.sessions() as session:
            imported = session.get(ExternalItemImportRecord, import_id)
            if imported is None or imported.state != "COMPLETED":
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_IMPORT_UNAVAILABLE", "completed import is unavailable"
                )
            try:
                validate_contract("external-item-workbook-mapping-v1", imported.mapping_document)
                mapping = ExternalItemWorkbookMapping.model_validate(imported.mapping_document)
            except (ValueError, JsonSchemaValidationError) as exc:
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_MAPPING_INVALID", "stored mapping is invalid"
                ) from exc
            if (
                mapping.mapping_revision_id != imported.mapping_revision_id
                or mapping.mapping_sha256 != imported.mapping_sha256
                or mapping.source_namespace != imported.source_namespace
            ):
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_MAPPING_INVALID", "stored mapping identity differs"
                )
            workbook_source = session.get(
                ContentIntakeSourceFileRecord, imported.workbook_source_file_id
            )
            if (
                workbook_source is None
                or workbook_source.artifact_id != imported.workbook_artifact_id
                or workbook_source.artifact_revision_id != imported.workbook_artifact_revision_id
                or workbook_source.sha256 != imported.workbook_sha256
            ):
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_WORKBOOK_POINTER", "workbook pointer differs"
                )
            try:
                payload = self.artifacts.read_member(
                    artifact_id=workbook_source.artifact_id,
                    revision_id=workbook_source.artifact_revision_id,
                    member_path=workbook_source.relative_path,
                    sha256=workbook_source.sha256,
                    media_type=workbook_source.media_type,
                    schema_ref=INTAKE_SOURCE_FILE_SCHEMA_REF,
                    max_bytes=100 * 1024 * 1024,
                )
                decoded = read_external_item_rows_bytes(payload, mapping)
            except (OSError, ValueError) as exc:
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_WORKBOOK_UNAVAILABLE", "pinned workbook cannot be read"
                ) from exc
            revisions = tuple(
                (revision, source)
                for revision, source in session.execute(
                    select(ExternalItemSourceRevisionRecord, ExternalItemSourceRecord)
                    .join(
                        ExternalItemSourceRecord,
                        ExternalItemSourceRecord.source_id
                        == ExternalItemSourceRevisionRecord.source_id,
                    )
                    .where(ExternalItemSourceRevisionRecord.import_id == import_id)
                    .order_by(ExternalItemSourceRevisionRecord.row_number)
                )
            )
            if imported.row_count != len(decoded):
                raise ExternalItemImportAuditError(
                    "EXTERNAL_ITEM_AUDIT_ROW_COUNT", "declared row count differs"
                )
            pointer = ExternalItemWorkbookPointer(
                artifact_id=imported.workbook_artifact_id,
                artifact_revision_id=imported.workbook_artifact_revision_id,
                sha256=imported.workbook_sha256,
            )
            counts = _verify_rows(decoded, revisions, mapping=mapping, workbook=pointer)
            editions = tuple(
                (edition, file)
                for edition, file in session.execute(
                    select(ExternalItemEditionDocumentRecord, ContentIntakeSourceFileRecord)
                    .join(
                        ExternalItemSourceRevisionRecord,
                        ExternalItemSourceRevisionRecord.revision_id
                        == ExternalItemEditionDocumentRecord.source_revision_id,
                    )
                    .outerjoin(
                        ContentIntakeSourceFileRecord,
                        ContentIntakeSourceFileRecord.source_file_id
                        == ExternalItemEditionDocumentRecord.source_file_id,
                    )
                    .where(ExternalItemSourceRevisionRecord.import_id == import_id)
                    .order_by(
                        ExternalItemEditionDocumentRecord.source_revision_id,
                        ExternalItemEditionDocumentRecord.edition,
                    )
                )
            )
            _verify_editions(decoded, revisions, editions)
            return ExternalItemImportAuditResult(
                import_id=import_id,
                workbook_sha256=imported.workbook_sha256,
                row_count=len(decoded),
                edition_link_count=len(editions),
                selected_document_count=sum(counts[status] for status in _MATCHED),
                status_counts=tuple(sorted(counts.items())),
            )
