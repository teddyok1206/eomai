"""Bounded reads of source-only external Items through their published revision.

This is a Catalog repository projection, not an Item Registry lookup. The API
caller must authorize CONTENT_INTAKE_READ before invoking it; file bytes are
resolved separately through the existing authenticated media boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts import (
    ExternalItemCellObservation,
    ExternalItemRowObservation,
    ExternalItemWorkbookMapping,
)
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from eom_catalog_service.external_item_matching import ExternalItemMatchStatus
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ContentIntakeSourceFileRecord

_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_NUMBER = re.compile(r"^[0-9]{5}$")
_MAX_PAGE = 100
_COLUMNS = tuple(chr(ord("A") + index) for index in range(26)) + tuple(
    "A" + chr(ord("A") + index) for index in range(6)
)
_FILTER_FIELDS = frozenset((*_COLUMNS, "MATCH_STATUS"))
_VALUE_OPERATORS = frozenset(("EQ", "NE", "CONTAINS"))
_EMPTY_OPERATORS = frozenset(("IS_EMPTY", "IS_NOT_EMPTY"))


class ExternalItemReadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalItemMetadataPredicate:
    field: str
    operator: str
    value: str | None = None

    def __post_init__(self) -> None:
        if (
            self.field not in _FILTER_FIELDS
            or self.operator not in _VALUE_OPERATORS | _EMPTY_OPERATORS
            or (self.operator in _VALUE_OPERATORS) != (self.value is not None)
            or (self.value is not None and (not self.value or len(self.value) > 255))
            or (self.field == "MATCH_STATUS" and (
                self.operator not in ("EQ", "NE")
                or self.value not in ExternalItemMatchStatus.__members__
            ))
            or (self.field == "U" and self.operator in _EMPTY_OPERATORS)
        ):
            raise ExternalItemReadError("EXTERNAL_ITEM_QUERY_INVALID", "metadata filter is invalid")


@dataclass(frozen=True)
class ExternalItemListFilter:
    source_namespace: str
    limit: int = 50
    after_number: str | None = None
    exact_number: str | None = None
    major_unit: str | None = None
    field_label: str | None = None
    match_status: str | None = None
    match_mode: str = "ALL"
    conditions: tuple[ExternalItemMetadataPredicate, ...] = ()

    def __post_init__(self) -> None:
        if (
            _NAMESPACE.fullmatch(self.source_namespace) is None
            or type(self.limit) is not int
            or not 1 <= self.limit <= _MAX_PAGE
            or any(
                number is not None and _NUMBER.fullmatch(number) is None
                for number in (self.after_number, self.exact_number)
            )
            or any(
                value is not None and (not value or len(value) > 255)
                for value in (self.major_unit, self.field_label)
            )
            or (
                self.match_status is not None
                and self.match_status not in ExternalItemMatchStatus.__members__
            )
            or self.match_mode not in ("ALL", "ANY")
            or len(self.conditions) > 8
            or any(
                not isinstance(value, ExternalItemMetadataPredicate)
                for value in self.conditions
            )
        ):
            raise ExternalItemReadError("EXTERNAL_ITEM_QUERY_INVALID", "query is invalid")


@dataclass(frozen=True)
class ExternalItemListEntry:
    source_id: str
    source_revision_id: str
    external_number: str
    observation_sha256: str
    major_unit: str | None
    minor_unit: str | None
    field_label: str | None
    grade_label: str | None
    author_label: str | None
    match_status: str
    selected_filename: str | None
    selected_source_file_id: str | None


@dataclass(frozen=True)
class ExternalItemListPage:
    entries: tuple[ExternalItemListEntry, ...]
    next_after_number: str | None


@dataclass(frozen=True)
class ExternalItemDetail:
    entry: ExternalItemListEntry
    row: ExternalItemRowObservation
    edition_links: tuple[ExternalItemEditionView, ...]


@dataclass(frozen=True)
class ExternalItemExportEntry:
    external_number: str
    match_status: str
    selected_filename: str | None
    major_unit: str | None
    minor_unit: str | None
    field_label: str | None
    row: ExternalItemRowObservation


@dataclass(frozen=True)
class ExternalItemExportSnapshot:
    original_headers: tuple[str, ...]
    entries: tuple[ExternalItemExportEntry, ...]


@dataclass(frozen=True)
class ExternalItemEditionView:
    edition: int
    original_link: str
    match_status: str
    filename: str | None
    media_type: str | None
    source_file_id: str | None
    sha256: str | None


def _list_columns() -> tuple[Any, ...]:
    source = ExternalItemSourceRecord
    revision = ExternalItemSourceRevisionRecord
    file = ContentIntakeSourceFileRecord
    return (
        source.source_id,
        revision.revision_id,
        source.external_number,
        revision.observation_sha256,
        revision.unit_major,
        revision.unit_minor,
        revision.field_label,
        revision.grade_label,
        revision.author_label,
        revision.match_status,
        file.original_filename,
        revision.selected_source_file_id,
    )


def _base_query() -> Select[Any]:
    source = ExternalItemSourceRecord
    revision = ExternalItemSourceRevisionRecord
    return (
        select(*_list_columns())
        .join(revision, revision.revision_id == source.current_revision_id)
        .join(ExternalItemImportRecord, ExternalItemImportRecord.import_id == revision.import_id)
        .outerjoin(
            ContentIntakeSourceFileRecord,
            ContentIntakeSourceFileRecord.source_file_id == revision.selected_source_file_id,
        )
        .where(ExternalItemImportRecord.state == "COMPLETED")
    )


def _literal_pattern(value: str) -> str:
    return value.replace("~", "~~").replace("%", "~%").replace("_", "~_")


def _metadata_condition(value: ExternalItemMetadataPredicate) -> Any:
    source = ExternalItemSourceRecord
    revision = ExternalItemSourceRevisionRecord
    if value.field == "U":
        expression = source.external_number
    elif value.field == "MATCH_STATUS":
        expression = revision.match_status
    else:
        expression = revision.cells[_COLUMNS.index(value.field)]["raw_text"].as_string()
    if value.operator == "IS_EMPTY":
        return expression == ""
    if value.operator == "IS_NOT_EMPTY":
        return expression != ""
    assert value.value is not None
    pattern = _literal_pattern(value.value)
    if value.operator == "CONTAINS":
        return expression.ilike(f"%{pattern}%", escape="~")
    if value.operator == "EQ":
        return expression.ilike(pattern, escape="~")
    return ~expression.ilike(pattern, escape="~")


def _filtered_query(statement: Select[Any], query: ExternalItemListFilter) -> Select[Any]:
    source = ExternalItemSourceRecord
    revision = ExternalItemSourceRevisionRecord
    statement = statement.where(source.source_namespace == query.source_namespace)
    if query.after_number is not None:
        statement = statement.where(source.external_number > query.after_number)
    if query.exact_number is not None:
        statement = statement.where(source.external_number == query.exact_number)
    if query.major_unit is not None:
        statement = statement.where(revision.unit_major == query.major_unit)
    if query.field_label is not None:
        statement = statement.where(revision.field_label == query.field_label)
    if query.match_status is not None:
        statement = statement.where(revision.match_status == query.match_status)
    if query.conditions:
        expressions = tuple(_metadata_condition(value) for value in query.conditions)
        statement = statement.where(
            and_(*expressions) if query.match_mode == "ALL" else or_(*expressions)
        )
    return statement


def list_external_item_sources(
    session: Session, query: ExternalItemListFilter
) -> ExternalItemListPage:
    """Use the namespace/U unique index and a bounded keyset; never scan bytes."""

    query = ExternalItemListFilter(**query.__dict__)
    source = ExternalItemSourceRecord
    statement = _filtered_query(_base_query(), query)
    values = session.execute(
        statement.order_by(source.external_number).limit(query.limit + 1)
    ).all()
    page_values = values[: query.limit]
    entries = tuple(ExternalItemListEntry(*value) for value in page_values)
    next_after = entries[-1].external_number if len(values) > query.limit else None
    return ExternalItemListPage(entries=entries, next_after_number=next_after)


def export_external_item_sources(
    session: Session, query: ExternalItemListFilter, *, max_rows: int = 2000
) -> ExternalItemExportSnapshot:
    """Read one bounded statement snapshot with exact workbook observations."""

    query = ExternalItemListFilter(**query.__dict__)
    if query.after_number is not None or not 1 <= max_rows <= 2000:
        raise ExternalItemReadError("EXTERNAL_ITEM_QUERY_INVALID", "export query is invalid")
    source = ExternalItemSourceRecord
    revision = ExternalItemSourceRevisionRecord
    imported = ExternalItemImportRecord
    file = ContentIntakeSourceFileRecord
    statement = _filtered_query(
        select(
            source.external_number,
            revision.match_status,
            file.original_filename,
            revision.unit_major,
            revision.unit_minor,
            revision.field_label,
            revision.worksheet_name,
            revision.row_number,
            revision.observation_sha256,
            revision.cells,
            imported.workbook_artifact_id,
            imported.workbook_artifact_revision_id,
            imported.workbook_sha256,
            imported.mapping_revision_id,
            imported.mapping_sha256,
            imported.mapping_document,
        )
        .join(revision, revision.revision_id == source.current_revision_id)
        .join(imported, imported.import_id == revision.import_id)
        .outerjoin(file, file.source_file_id == revision.selected_source_file_id)
        .where(imported.state == "COMPLETED"),
        query,
    )
    values = session.execute(statement.order_by(source.external_number).limit(max_rows + 1)).all()
    if len(values) > max_rows:
        raise ExternalItemReadError("EXTERNAL_ITEM_EXPORT_TOO_LARGE", "export exceeds row limit")
    if not values:
        raise ExternalItemReadError("EXTERNAL_ITEM_EXPORT_EMPTY", "no rows match the export")
    first_mapping = values[0][15]
    try:
        mapping = ExternalItemWorkbookMapping.model_validate(first_mapping)
    except ValueError as exc:
        raise ExternalItemReadError(
            "EXTERNAL_ITEM_EXPORT_MAPPING_INVALID", "source mapping is invalid"
        ) from exc
    entries: list[ExternalItemExportEntry] = []
    for value in values:
        (
            number, status, filename, major, minor, field, worksheet, row_number,
            observation_sha256, cells, workbook_artifact_id,
            workbook_artifact_revision_id, workbook_sha256, mapping_revision_id,
            mapping_sha256, _mapping_document,
        ) = value
        if (
            mapping_revision_id != mapping.mapping_revision_id
            or mapping_sha256 != mapping.mapping_sha256
            or _mapping_document != first_mapping
        ):
            raise ExternalItemReadError(
                "EXTERNAL_ITEM_EXPORT_MAPPING_MIXED", "source mappings differ"
            )
        try:
            row = ExternalItemRowObservation.model_validate(
                {
                    "workbook_artifact_id": workbook_artifact_id,
                    "workbook_artifact_revision_id": workbook_artifact_revision_id,
                    "workbook_sha256": workbook_sha256,
                    "mapping_revision_id": mapping_revision_id,
                    "mapping_sha256": mapping_sha256,
                    "source_namespace": query.source_namespace,
                    "worksheet_name": worksheet,
                    "row_number": row_number,
                    "external_number": number,
                    "cells": tuple(
                        ExternalItemCellObservation.model_validate(cell) for cell in cells
                    ),
                    "observation_sha256": observation_sha256,
                }
            )
        except ValueError as exc:
            raise ExternalItemReadError(
                "EXTERNAL_ITEM_EXPORT_ROW_INVALID", "source row observation differs"
            ) from exc
        entries.append(
            ExternalItemExportEntry(
                external_number=number,
                match_status=status,
                selected_filename=filename,
                major_unit=major,
                minor_unit=minor,
                field_label=field,
                row=row,
            )
        )
    return ExternalItemExportSnapshot(
        original_headers=tuple(header.label for header in mapping.column_headers),
        entries=tuple(entries),
    )


def read_external_item_source(
    session: Session, *, source_namespace: str, external_number: str
) -> ExternalItemDetail | None:
    """Return exact current row only if its import is fully published and hash-valid."""

    query = ExternalItemListFilter(
        source_namespace=source_namespace, exact_number=external_number, limit=1
    )
    entry_page = list_external_item_sources(session, query)
    if not entry_page.entries:
        return None
    entry = entry_page.entries[0]
    revision = session.get(ExternalItemSourceRevisionRecord, entry.source_revision_id)
    if revision is None:
        raise ExternalItemReadError("EXTERNAL_ITEM_POINTER_INVALID", "source revision is missing")
    imported = session.get(ExternalItemImportRecord, revision.import_id)
    if imported is None:
        raise ExternalItemReadError("EXTERNAL_ITEM_POINTER_INVALID", "source import is missing")
    body = {
        "schema_version": "external-item-row-observation/1.0",
        "workbook_artifact_id": imported.workbook_artifact_id,
        "workbook_artifact_revision_id": imported.workbook_artifact_revision_id,
        "workbook_sha256": imported.workbook_sha256,
        "mapping_revision_id": imported.mapping_revision_id,
        "mapping_sha256": imported.mapping_sha256,
        "source_namespace": imported.source_namespace,
        "worksheet_name": revision.worksheet_name,
        "row_number": revision.row_number,
        "external_number": revision.external_number,
        "cells": tuple(ExternalItemCellObservation.model_validate(cell) for cell in revision.cells),
        "observation_sha256": revision.observation_sha256,
    }
    try:
        row = ExternalItemRowObservation.model_validate(body)
    except ValueError as exc:
        raise ExternalItemReadError(
            "EXTERNAL_ITEM_OBSERVATION_INVALID", "source observation differs"
        ) from exc
    if row.source_namespace != source_namespace or row.external_number != external_number:
        raise ExternalItemReadError("EXTERNAL_ITEM_POINTER_INVALID", "source identity differs")
    edition_rows = session.execute(
        select(
            ExternalItemEditionDocumentRecord,
            ContentIntakeSourceFileRecord.original_filename,
            ContentIntakeSourceFileRecord.media_type,
            ContentIntakeSourceFileRecord.sha256,
        )
        .outerjoin(
            ContentIntakeSourceFileRecord,
            ContentIntakeSourceFileRecord.source_file_id
            == ExternalItemEditionDocumentRecord.source_file_id,
        )
        .where(ExternalItemEditionDocumentRecord.source_revision_id == entry.source_revision_id)
        .order_by(ExternalItemEditionDocumentRecord.edition)
    ).all()
    links: list[ExternalItemEditionView] = []
    for binding, filename, media_type, document_sha256 in edition_rows:
        if binding.source_file_id is not None and (
            filename is None or document_sha256 != binding.document_sha256
        ):
            raise ExternalItemReadError(
                "EXTERNAL_ITEM_DOCUMENT_POINTER_INVALID", "editorial document differs"
            )
        links.append(
            ExternalItemEditionView(
                edition=binding.edition,
                original_link=row.cells[10 + binding.edition].raw_text,
                match_status=binding.match_status,
                filename=filename,
                media_type=media_type,
                source_file_id=binding.source_file_id,
                sha256=binding.document_sha256,
            )
        )
    expected = tuple(
        edition for edition, index in ((1, 11), (2, 12), (3, 13)) if row.cells[index].raw_text
    )
    if tuple(link.edition for link in links) != expected:
        raise ExternalItemReadError(
            "EXTERNAL_ITEM_EDITION_LINKS_INVALID", "editorial link set differs"
        )
    return ExternalItemDetail(entry=entry, row=row, edition_links=tuple(links))
