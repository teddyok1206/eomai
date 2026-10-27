"""Only exact, committed Intake file pointers can enter the import manifest."""

from __future__ import annotations

import pytest
from eom_catalog_contracts import (
    EXTERNAL_ITEM_COLUMNS,
    ExternalItemCellObservation,
    ExternalItemWorkbookMapping,
)
from eom_catalog_service.external_item_archive import (
    ExternalItemArchiveInventory,
    ExternalItemDocumentMember,
)
from eom_catalog_service.external_item_import_preparation import (
    CommittedExternalItemSource,
    ExternalItemImportPreparationError,
    prepare_external_item_import,
)
from eom_catalog_service.external_item_observations import ExternalItemWorkbookPointer
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
        "worksheet_name": "통합과학 DB",
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
    values = {"N": "N제/2025_기구.hwp", "U": "00042"}
    return DecodedExternalItemRow(
        row_number=2,
        external_number="00042",
        cells=tuple(
            ExternalItemCellObservation(
                column=column,
                present=column in values,
                cell_type="s" if column in values else None,
                raw_text=values.get(column, ""),
            )
            for column in EXTERNAL_ITEM_COLUMNS
        ),
    )


def _inventory() -> ExternalItemArchiveInventory:
    document = ExternalItemDocumentMember(
        member_name="N제/2025_기구_00042.hwp",
        display_filename="2025_기구_00042.hwp",
        external_number="00042",
        declared_format="HWP",
        detected_format="HWPX_PACKAGE",
        size_bytes=12,
        sha256="sha256:" + "a" * 64,
    )
    return ExternalItemArchiveInventory(
        archive_sha256="sha256:" + "f" * 64,
        archive_size_bytes=100,
        total_member_count=1,
        skipped_member_count=0,
        documents=(document,),
    )


def _prepare(committed: tuple[CommittedExternalItemSource, ...]):
    return prepare_external_item_import(
        actor_id="guiadmin",
        mapping=_mapping(),
        workbook_source_file_id="sourcefile_" + "b" * 32,
        workbook=ExternalItemWorkbookPointer(
            artifact_id="artifact_" + "c" * 32,
            artifact_revision_id="rev_" + "d" * 32,
            sha256="sha256:" + "e" * 64,
        ),
        inventory=_inventory(),
        rows=(_row(),),
        committed_documents=committed,
    )


def test_import_preparation_keeps_actual_hwpx_detected_under_hwp_filename() -> None:
    result = _prepare(
        (
            CommittedExternalItemSource(
                source_file_id="sourcefile_" + "1" * 32,
                sha256="sha256:" + "a" * 64,
                original_filename="2025_기구_00042.hwp",
            ),
        )
    )
    assert result.rows[0].match_status == "MATCHED_DETECTED_HWPX"
    assert result.rows[0].selected_source_file_id == "sourcefile_" + "1" * 32
    assert result.rows[0].observation.cells[13].raw_text == "N제/2025_기구.hwp"


def test_import_preparation_never_substitutes_similar_filename_or_hash() -> None:
    for source in (
        CommittedExternalItemSource(
            "sourcefile_" + "1" * 32, "sha256:" + "b" * 64, "2025_기구_00042.hwp"
        ),
        CommittedExternalItemSource(
            "sourcefile_" + "1" * 32, "sha256:" + "a" * 64, "다른파일_00042.hwp"
        ),
    ):
        with pytest.raises(ExternalItemImportPreparationError) as captured:
            _prepare((source,))
        assert captured.value.code == "EXTERNAL_ITEM_IMPORT_FILE_MISSING"
