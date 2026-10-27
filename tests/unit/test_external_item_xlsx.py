"""Untrusted workbook reading must retain source text without inventing Items."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from eom_catalog_contracts import EXTERNAL_ITEM_COLUMNS, ExternalItemWorkbookMapping
from eom_catalog_service.external_item_xlsx import (
    ExternalItemXlsxError,
    read_external_item_rows,
    read_external_item_rows_bytes,
)
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


def _cell(column: str, row: int, value: str, *, formula: str | None = None) -> str:
    expression = "" if formula is None else f"<f>{escape(formula)}</f>"
    return (
        f'<c r="{column}{row}" t="inlineStr" s="2">{expression}<is><t>{escape(value)}</t></is></c>'
    )


def _workbook(
    path: Path,
    *,
    second_number: str | None = None,
    number_formula: bool = False,
    wrong_header: bool = False,
    extra_column: bool = False,
) -> None:
    headers = "".join(
        _cell(column, 1, "틀린 제목" if wrong_header and column == "C" else f"원본 {column}")
        for column in EXTERNAL_ITEM_COLUMNS
    )
    data = _cell("U", 2, "00042", formula='TEXT(42,"00000")' if number_formula else None)
    data += _cell("C", 2, " 앞  뒤  ")
    data += _cell("N", 2, "파일_00042.hwp")
    if extra_column:
        data += _cell("AG", 2, "추가 메타데이터")
    next_row = "" if second_number is None else f'<row r="3">{_cell("U", 3, second_number)}</row>'
    worksheet = (
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData><row r="1">{headers}</row><row r="2">{data}</row>'
        f"{next_row}</sheetData></worksheet>"
    )
    members = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        ),
        "xl/workbook.xml": (
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="문항" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": worksheet,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)


def test_external_workbook_preserves_every_cell_and_leading_zero(tmp_path: Path) -> None:
    path = tmp_path / "source.xlsx"
    _workbook(path)
    rows = read_external_item_rows(path, _mapping())
    assert len(rows) == 1
    assert rows[0].external_number == "00042"
    assert len(rows[0].cells) == 32
    assert rows[0].cells[2].raw_text == " 앞  뒤  "
    assert rows[0].cells[2].style_id == 2
    assert rows[0].cells[0].present is False
    assert rows[0].cells[20].present is True
    assert read_external_item_rows_bytes(path.read_bytes(), _mapping()) == rows


@pytest.mark.parametrize(
    ("option", "code"),
    [
        ({"second_number": "00042"}, "EXTERNAL_ITEM_XLSX_NUMBER_DUPLICATE"),
        ({"number_formula": True}, "EXTERNAL_ITEM_XLSX_NUMBER_INVALID"),
        ({"wrong_header": True}, "EXTERNAL_ITEM_XLSX_HEADER_MISMATCH"),
        ({"extra_column": True}, "EXTERNAL_ITEM_XLSX_CELL_INVALID"),
    ],
)
def test_external_workbook_rejects_ambiguous_or_unmapped_data(
    tmp_path: Path, option: dict[str, object], code: str
) -> None:
    path = tmp_path / "source.xlsx"
    _workbook(path, **option)
    with pytest.raises(ExternalItemXlsxError) as captured:
        read_external_item_rows(path, _mapping())
    assert captured.value.code == code


def test_external_workbook_rejects_symlink(tmp_path: Path) -> None:
    path = tmp_path / "source.xlsx"
    _workbook(path)
    link = tmp_path / "source-link.xlsx"
    link.symlink_to(path)
    with pytest.raises(ExternalItemXlsxError) as captured:
        read_external_item_rows(link, _mapping())
    assert captured.value.code == "EXTERNAL_ITEM_XLSX_FILE_INVALID"
