"""DB XLSX export preserves metadata while hiding transport identities."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from eom_catalog_contracts import EXTERNAL_ITEM_COLUMNS, ExternalItemCellObservation
from eom_catalog_service.item_db_excel_export import (
    ItemDbExcelExportError,
    ItemDbExportRow,
    render_item_database_xlsx,
    write_item_database_xlsx,
)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_HEADERS = tuple(f"원본 {column}" for column in EXTERNAL_ITEM_COLUMNS)


def _legacy_row() -> ItemDbExportRow:
    values = {"C": "  어려움  ", "N": "문항_00042.hwp", "U": "00042"}
    return ItemDbExportRow(
        source_kind="EXTERNAL_SOURCE",
        title="지구과학 자료 해석",
        unit_label="지구과학",
        source_label="기존 등록 자료",
        state_label="원본 파일",
        filename="문항_00042.hwp",
        external_number="00042",
        worksheet_name="기존 문항",
        source_row_number=12,
        original_cells=tuple(
            ExternalItemCellObservation(
                column=column,
                present=column in values,
                cell_type="s" if column in values else None,
                raw_text=values.get(column, ""),
                style_id=2 if column in values else None,
            )
            for column in EXTERNAL_ITEM_COLUMNS
        ),
    )


def _generated_row() -> ItemDbExportRow:
    return ItemDbExportRow(
        source_kind="GENERATED_ITEM",
        title="=SUM(1,2)",
        unit_label="물질과 규칙성",
        source_label="EOM 생성 문항",
        state_label="승인 완료",
        filename="생성문항.hwpx",
        public_metadata=(("난이도", "중"), ("출제 요소", "입자 운동")),
    )


def _sheet_rows(archive: zipfile.ZipFile, name: str) -> list[list[str]]:
    root = ElementTree.fromstring(archive.read(name))
    return [
        [cell.find(f"{_NS}is/{_NS}t").text or "" for cell in row.findall(f"{_NS}c")]
        for row in root.findall(f".//{_NS}row")
    ]


def test_xlsx_export_preserves_original_cells_and_uses_literal_strings(tmp_path: Path) -> None:
    output = tmp_path / "item-db.xlsx"
    result = write_item_database_xlsx(
        output, (_legacy_row(), _generated_row()), original_headers=_HEADERS
    )
    assert result.row_count == 2
    assert result.sha256.startswith("sha256:")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        common = _sheet_rows(archive, "xl/worksheets/sheet1.xml")
        source = _sheet_rows(archive, "xl/worksheets/sheet2.xml")
        state = _sheet_rows(archive, "xl/worksheets/sheet3.xml")
        other = _sheet_rows(archive, "xl/worksheets/sheet4.xml")
        assert common[1][-1] == "문항_00042.hwp"
        assert common[1][1] == "00042"
        assert common[2][3] == "=SUM(1,2)"
        assert source[1][1:3] == ["기존 문항", "12"]
        assert source[1][5] == "  어려움  "
        assert source[1][23] == "00042"
        assert len(state) == 33
        assert other[1] == ["2", "난이도", "중"]
        assert all(b"<f>" not in archive.read(name) for name in archive.namelist())


def test_xlsx_output_is_deterministic_and_never_overwrites(tmp_path: Path) -> None:
    first = write_item_database_xlsx(
        tmp_path / "first.xlsx", (_legacy_row(),), original_headers=_HEADERS
    )
    second = write_item_database_xlsx(
        tmp_path / "second.xlsx", (_legacy_row(),), original_headers=_HEADERS
    )
    assert first.sha256 == second.sha256
    rendered = render_item_database_xlsx((_legacy_row(),), original_headers=_HEADERS)
    assert rendered.sha256 == first.sha256
    assert rendered.row_count == 1
    with pytest.raises(ItemDbExcelExportError) as captured:
        write_item_database_xlsx(first.path, (_legacy_row(),), original_headers=_HEADERS)
    assert captured.value.code == "ITEM_DB_EXPORT_OUTPUT_EXISTS"


def test_xlsx_rejects_technical_metadata_and_invalid_text(tmp_path: Path) -> None:
    generated = _generated_row()
    with pytest.raises(ItemDbExcelExportError) as captured:
        write_item_database_xlsx(
            tmp_path / "bad.xlsx",
            (
                ItemDbExportRow(
                    **{**generated.__dict__, "public_metadata": (("item_id", "secret"),)}
                ),
            ),
            original_headers=_HEADERS,
        )
    assert captured.value.code == "ITEM_DB_EXPORT_METADATA_UNSAFE"
    assert not (tmp_path / "bad.xlsx").exists()

    with pytest.raises(ItemDbExcelExportError) as captured:
        write_item_database_xlsx(
            tmp_path / "control.xlsx",
            (ItemDbExportRow(**{**generated.__dict__, "title": "bad\x00text"}),),
            original_headers=_HEADERS,
        )
    assert captured.value.code == "ITEM_DB_EXPORT_TEXT_INVALID"
