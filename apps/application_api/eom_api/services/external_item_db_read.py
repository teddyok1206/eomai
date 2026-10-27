"""Permission-gated legacy source projection; it never creates Item revisions."""

from __future__ import annotations

import hashlib
import json

from eom_api_contracts.external_item_db import (
    ExternalItemDbCellView,
    ExternalItemDbDetailView,
    ExternalItemDbEditionView,
    ExternalItemDbEntryView,
    ExternalItemDbFilterRequest,
)
from eom_catalog_service.external_item_models import ExternalItemSourceRecord
from eom_catalog_service.external_item_read_service import (
    ExternalItemListEntry,
    ExternalItemListFilter,
    ExternalItemMetadataPredicate,
    ExternalItemReadError,
    export_external_item_sources,
    list_external_item_sources,
    read_external_item_source,
)
from eom_catalog_service.item_db_excel_export import (
    ItemDbExcelExportError,
    ItemDbExportRow,
    ItemDbRenderedXlsx,
    render_item_database_xlsx,
)
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine

from eom_api.errors import ApiError
from eom_api.services.pagination import CursorCodec, PageResult

_NAMESPACE = "notion-integrated-science"
_CURSOR_RESOURCE = "external-item-db-v1"


def _conditions(
    advanced: ExternalItemDbFilterRequest | None,
) -> tuple[ExternalItemMetadataPredicate, ...]:
    return (
        tuple(
            ExternalItemMetadataPredicate(
                field=condition.field,
                operator=condition.operator,
                value=condition.value,
            )
            for condition in advanced.conditions
        )
        if advanced else ()
    )


def _entry(value: ExternalItemListEntry) -> ExternalItemDbEntryView:
    return ExternalItemDbEntryView.model_validate(
        {
            "source_id": value.source_id,
            "source_revision_id": value.source_revision_id,
            "external_number": value.external_number,
            "observation_sha256": value.observation_sha256,
            "major_unit": value.major_unit,
            "minor_unit": value.minor_unit,
            "field_label": value.field_label,
            "grade_label": value.grade_label,
            "author_label": value.author_label,
            "match_status": value.match_status,
            "selected_filename": value.selected_filename,
        }
    )


class ExternalItemDbReadApplication:
    def __init__(self, engine: Engine, cursor_key: bytes) -> None:
        self.sessions = build_session_factory(engine)
        self.cursors = CursorCodec(cursor_key)

    def list(
        self,
        *,
        exact_number: str | None,
        major_unit: str | None,
        field_label: str | None,
        match_status: str | None,
        limit: int,
        cursor: str | None,
        advanced: ExternalItemDbFilterRequest | None = None,
    ) -> PageResult[ExternalItemDbEntryView]:
        scope = hashlib.sha256(
            json.dumps(
                {
                    "exact_number": exact_number,
                    "major_unit": major_unit,
                    "field_label": field_label,
                    "match_status": match_status,
                    "match_mode": advanced.match_mode if advanced else "ALL",
                    "conditions": (
                        [condition.model_dump(mode="json") for condition in advanced.conditions]
                        if advanced else []
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        last_number = (
            f"{self.cursors.decode_ordinal(cursor, _CURSOR_RESOURCE, scope):05d}"
            if cursor is not None
            else None
        )
        try:
            query = ExternalItemListFilter(
                source_namespace=_NAMESPACE,
                exact_number=exact_number,
                major_unit=major_unit,
                field_label=field_label,
                match_status=match_status,
                match_mode=advanced.match_mode if advanced else "ALL",
                conditions=_conditions(advanced),
                limit=limit,
                after_number=last_number,
            )
            with self.sessions() as session:
                page = list_external_item_sources(session, query)
        except ExternalItemReadError as exc:
            raise ApiError(422, exc.code, "Invalid item DB query", str(exc)) from exc
        return PageResult(
            data=tuple(_entry(value) for value in page.entries),
            next_cursor=(
                self.cursors.encode_ordinal(
                    _CURSOR_RESOURCE, scope, int(page.next_after_number)
                )
                if page.next_after_number is not None
                else None
            ),
            has_more=page.next_after_number is not None,
        )

    def export(self, filters: ExternalItemDbFilterRequest) -> ItemDbRenderedXlsx:
        if filters.cursor is not None:
            raise ApiError(
                422, "ITEM_DB_EXPORT_CURSOR_INVALID", "Invalid export", "Use full filter"
            )
        try:
            query = ExternalItemListFilter(
                source_namespace=_NAMESPACE,
                match_mode=filters.match_mode,
                conditions=_conditions(filters),
                limit=100,
            )
            with self.sessions() as session:
                snapshot = export_external_item_sources(session, query)
            rows = tuple(
                ItemDbExportRow(
                    source_kind="EXTERNAL_SOURCE",
                    title=entry.selected_filename or f"기존 문항 {entry.external_number}",
                    unit_label=" · ".join(
                        value for value in (entry.major_unit, entry.minor_unit) if value
                    ),
                    source_label="창작 원본",
                    state_label=entry.match_status,
                    filename=entry.selected_filename or "",
                    external_number=entry.external_number,
                    worksheet_name=entry.row.worksheet_name,
                    source_row_number=entry.row.row_number,
                    original_cells=entry.row.cells,
                    public_metadata=(
                        (("분야", entry.field_label),) if entry.field_label else ()
                    ),
                )
                for entry in snapshot.entries
            )
            return render_item_database_xlsx(
                rows, original_headers=snapshot.original_headers
            )
        except ExternalItemReadError as exc:
            status = 413 if exc.code == "EXTERNAL_ITEM_EXPORT_TOO_LARGE" else 409
            raise ApiError(status, exc.code, "Item DB export unavailable", str(exc)) from exc
        except ItemDbExcelExportError as exc:
            status = 413 if exc.code == "ITEM_DB_EXPORT_TOO_LARGE" else 409
            raise ApiError(status, exc.code, "Item DB export unavailable", str(exc)) from exc

    def detail(self, source_id: str) -> ExternalItemDbDetailView:
        with self.sessions() as session:
            source = session.get(ExternalItemSourceRecord, source_id)
            if source is None or source.source_namespace != _NAMESPACE:
                raise ApiError(404, "ITEM_DB_SOURCE_NOT_FOUND", "Item not found", "No such source")
            try:
                detail = read_external_item_source(
                    session,
                    source_namespace=_NAMESPACE,
                    external_number=source.external_number,
                )
            except ExternalItemReadError as exc:
                raise ApiError(409, exc.code, "Item source unavailable", str(exc)) from exc
        if detail is None or detail.entry.source_id != source_id:
            raise ApiError(404, "ITEM_DB_SOURCE_NOT_FOUND", "Item not found", "No such source")
        return ExternalItemDbDetailView(
            entry=_entry(detail.entry),
            worksheet_name=detail.row.worksheet_name,
            row_number=detail.row.row_number,
            cells=tuple(
                ExternalItemDbCellView.model_validate(cell.model_dump(mode="json"))
                for cell in detail.row.cells
            ),
            editions=tuple(
                ExternalItemDbEditionView(
                    edition=edition.edition,
                    match_status=edition.match_status,
                    filename=edition.filename,
                    media_type=edition.media_type,
                    available=edition.source_file_id is not None,
                )
                for edition in detail.edition_links
            ),
        )
