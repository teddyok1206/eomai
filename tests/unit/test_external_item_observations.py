"""Pointer binding and search facets never normalize away source cells."""

from __future__ import annotations

from eom_catalog_contracts import (
    EXTERNAL_ITEM_COLUMNS,
    ExternalItemCellObservation,
    ExternalItemWorkbookMapping,
)
from eom_catalog_service.external_item_observations import (
    ExternalItemWorkbookPointer,
    bind_external_item_observation,
    external_item_search_facets,
)
from eom_catalog_service.external_item_xlsx import DecodedExternalItemRow
from eom_identifiers import content_sha256


def _mapping() -> ExternalItemWorkbookMapping:
    body: dict[str, object] = {
        "schema_version": "external-item-workbook-mapping/1.0",
        "mapping_id": "extitemmap_" + "1" * 32,
        "mapping_revision_id": "extitemmaprev_" + "2" * 32,
        "revision_number": 1,
        "state": "RELEASED",
        "source_namespace": "notion-integrated-science",
        "worksheet_name": "문항",
        "header_row": 1,
        "first_data_row": 2,
        "maximum_rows": 10,
        "column_headers": [
            {"column": column, "label": f"원본 {column}"} for column in EXTERNAL_ITEM_COLUMNS
        ],
        "external_number_column": "U",
        "edition_columns": {"draft": "L", "second": "M", "third": "N"},
        "rejection_column": "X",
        "normalization_policy": "external-item-notion-link/1.0",
        "released_at": "2026-10-27T00:00:00Z",
        "released_by": "guiadmin",
    }
    body["mapping_sha256"] = content_sha256(body)
    return ExternalItemWorkbookMapping.model_validate(body)


def _row() -> DecodedExternalItemRow:
    values = {"Q": "  물질과 규칙성  ", "Z": "물리학", "U": "00042"}
    return DecodedExternalItemRow(
        row_number=2,
        external_number="00042",
        cells=tuple(
            ExternalItemCellObservation(
                column=column,
                present=column in values,
                raw_text=values.get(column, ""),
                cell_type="s" if column in values else None,
            )
            for column in EXTERNAL_ITEM_COLUMNS
        ),
    )


def test_observation_pins_workbook_and_retains_original_text() -> None:
    mapping = _mapping()
    row = bind_external_item_observation(
        _row(),
        mapping=mapping,
        workbook=ExternalItemWorkbookPointer(
            artifact_id="artifact_" + "3" * 32,
            artifact_revision_id="rev_" + "4" * 32,
            sha256="sha256:" + "5" * 64,
        ),
    )
    assert row.workbook_artifact_revision_id == "rev_" + "4" * 32
    assert row.mapping_revision_id == mapping.mapping_revision_id
    assert row.cells[16].raw_text == "  물질과 규칙성  "
    assert external_item_search_facets(row).major_unit == "물질과 규칙성"
    assert external_item_search_facets(row).field == "물리학"
