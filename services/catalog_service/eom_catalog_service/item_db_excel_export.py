"""Deterministic XLSX presentation of an already-authorized DB read snapshot.

The caller owns authorization, snapshot pinning, and Artifact commit. This
adapter writes only to an exclusive local workspace file and emits no formulas.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import Literal
from xml.sax.saxutils import escape

from eom_catalog_contracts import EXTERNAL_ITEM_COLUMNS, ExternalItemCellObservation
from eom_identifiers import sha256_bytes, sha256_file

_MAX_ROWS = 2000
_MAX_METADATA_PAIRS = 100
_CELL_TEXT_LIMIT = 32767
_MAX_SOURCE_TEXT_BYTES = 24 * 1024 * 1024
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_TECHNICAL_LABEL = re.compile(r"(?:^|[_\s])(id|key|token|secret|path|uri)$", re.IGNORECASE)
_COMMON_HEADERS = ("순서", "고유번호", "종류", "제목", "단원", "출처", "상태", "파일명")


class ItemDbExcelExportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ItemDbExportRow:
    source_kind: Literal["EXTERNAL_SOURCE", "PAST_EXAM", "GENERATED_ITEM"]
    title: str
    unit_label: str
    source_label: str
    state_label: str
    filename: str
    external_number: str | None = None
    worksheet_name: str | None = None
    source_row_number: int | None = None
    public_metadata: tuple[tuple[str, str], ...] = ()
    original_cells: tuple[ExternalItemCellObservation, ...] | None = None


@dataclass(frozen=True)
class ItemDbExcelExportResult:
    path: Path
    size_bytes: int
    sha256: str
    row_count: int


@dataclass(frozen=True)
class ItemDbRenderedXlsx:
    payload: bytes
    sha256: str
    row_count: int


def render_item_database_xlsx(
    rows: tuple[ItemDbExportRow, ...], *, original_headers: tuple[str, ...]
) -> ItemDbRenderedXlsx:
    """Materialize a bounded, noncanonical XLSX for an authorized read response."""

    _validate_export(rows, original_headers)
    output = BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_archive(archive, rows, original_headers)
    payload = output.getvalue()
    if len(payload) > _MAX_OUTPUT_BYTES:
        raise ItemDbExcelExportError("ITEM_DB_EXPORT_TOO_LARGE", "export exceeds response limit")
    return ItemDbRenderedXlsx(
        payload=payload, sha256=sha256_bytes(payload), row_count=len(rows)
    )


def write_item_database_xlsx(
    output: Path,
    rows: tuple[ItemDbExportRow, ...],
    *,
    original_headers: tuple[str, ...],
) -> ItemDbExcelExportResult:
    """Write one bounded, formula-free XLSX from a pinned authorized result."""

    _validate_export(rows, original_headers)
    try:
        with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
            _write_archive(archive, rows, original_headers)
    except FileExistsError as exc:
        raise ItemDbExcelExportError(
            "ITEM_DB_EXPORT_OUTPUT_EXISTS", "export output already exists"
        ) from exc
    return ItemDbExcelExportResult(
        path=output,
        size_bytes=output.stat().st_size,
        sha256=sha256_file(output),
        row_count=len(rows),
    )


def _validate_export(rows: tuple[ItemDbExportRow, ...], headers: tuple[str, ...]) -> None:
    if len(headers) != 32 or not 0 < len(rows) <= _MAX_ROWS:
        raise ItemDbExcelExportError(
            "ITEM_DB_EXPORT_INPUT_INVALID", "export headers or row count is outside bounds"
        )
    for header in headers:
        _xml_text(header)
    source_bytes = sum(
        len(value.encode("utf-8"))
        for row in rows
        for value in (row.title, row.unit_label, row.source_label, row.state_label, row.filename)
    )
    for row in rows:
        _validate_row(row)
        source_bytes += sum(
            len(cell.raw_text.encode("utf-8"))
            + len((cell.formula_text or "").encode("utf-8"))
            for cell in row.original_cells or ()
        )
        source_bytes += sum(
            len(label.encode("utf-8")) + len(value.encode("utf-8"))
            for label, value in row.public_metadata
        )
        if source_bytes > _MAX_SOURCE_TEXT_BYTES:
            raise ItemDbExcelExportError("ITEM_DB_EXPORT_TOO_LARGE", "export exceeds text limit")


def _write_archive(
    archive: zipfile.ZipFile, rows: tuple[ItemDbExportRow, ...], headers: tuple[str, ...]
) -> None:
    _write_part(archive, "[Content_Types].xml", _content_types())
    _write_part(archive, "_rels/.rels", _root_relations())
    _write_part(archive, "xl/workbook.xml", _workbook())
    _write_part(archive, "xl/_rels/workbook.xml.rels", _workbook_relations())
    _write_sheet(archive, "xl/worksheets/sheet1.xml", _common_sheet(rows))
    _write_sheet(archive, "xl/worksheets/sheet2.xml", _original_metadata_sheet(rows, headers))
    _write_sheet(archive, "xl/worksheets/sheet3.xml", _cell_state_sheet(rows))
    _write_sheet(archive, "xl/worksheets/sheet4.xml", _other_metadata_sheet(rows))


def _validate_row(row: ItemDbExportRow) -> None:
    if row.source_kind not in {"EXTERNAL_SOURCE", "PAST_EXAM", "GENERATED_ITEM"}:
        raise ItemDbExcelExportError("ITEM_DB_EXPORT_INPUT_INVALID", "source kind is unsupported")
    for value in (row.title, row.unit_label, row.source_label, row.state_label, row.filename):
        _xml_text(value)
    if len(row.public_metadata) > _MAX_METADATA_PAIRS:
        raise ItemDbExcelExportError(
            "ITEM_DB_EXPORT_INPUT_INVALID", "too many public metadata fields"
        )
    labels: set[str] = set()
    for label, value in row.public_metadata:
        _xml_text(label)
        _xml_text(value)
        if not label or label in labels or _TECHNICAL_LABEL.search(label):
            raise ItemDbExcelExportError(
                "ITEM_DB_EXPORT_METADATA_UNSAFE", "metadata label is duplicate or technical"
            )
        labels.add(label)
    if row.source_kind == "EXTERNAL_SOURCE":
        if (
            row.original_cells is None
            or tuple(cell.column for cell in row.original_cells) != EXTERNAL_ITEM_COLUMNS
            or row.external_number is None
            or re.fullmatch(r"[0-9]{5}", row.external_number) is None
            or row.original_cells[20].raw_text != row.external_number
            or row.worksheet_name is None
            or not row.worksheet_name
            or row.source_row_number is None
            or row.source_row_number < 2
        ):
            raise ItemDbExcelExportError(
                "ITEM_DB_EXPORT_INPUT_INVALID", "external source requires exact A:AF cells"
            )
    elif (
        row.original_cells is not None
        or row.external_number is not None
        or row.worksheet_name is not None
        or row.source_row_number is not None
    ):
        raise ItemDbExcelExportError(
            "ITEM_DB_EXPORT_INPUT_INVALID", "registered Item cannot claim legacy source cells"
        )
    if row.original_cells is not None:
        _xml_text(row.worksheet_name or "")
        for cell in row.original_cells:
            _xml_text(cell.raw_text)
            if cell.formula_text is not None:
                _xml_text(cell.formula_text)


def _xml_text(value: str) -> str:
    if len(value) > _CELL_TEXT_LIMIT or any(
        (ord(char) < 32 and char not in "\t\n\r")
        or 0xD800 <= ord(char) <= 0xDFFF
        or ord(char) in {0xFFFE, 0xFFFF}
        for char in value
    ):
        raise ItemDbExcelExportError(
            "ITEM_DB_EXPORT_TEXT_INVALID", "cell text is not safe for XLSX"
        )
    return escape(value, {'"': "&quot;"})


def _column(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _cell(index: int, row: int, value: str) -> str:
    # inlineStr is essential: leading '=' and '+' remain text, not formulas.
    return (
        f'<c r="{_column(index)}{row}" t="inlineStr"><is>'
        f'<t xml:space="preserve">{_xml_text(value)}</t></is></c>'
    )


def _write_sheet(archive: zipfile.ZipFile, name: str, rows: Iterable[tuple[str, ...]]) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    with archive.open(info, "w") as sheet:
        sheet.write(f'<worksheet xmlns="{_MAIN_NS}"><sheetData>'.encode())
        for row_number, values in enumerate(rows, start=1):
            sheet.write(f'<row r="{row_number}">'.encode())
            for index, value in enumerate(values, start=1):
                sheet.write(_cell(index, row_number, value).encode())
            sheet.write(b"</row>")
        sheet.write(b"</sheetData></worksheet>")


def _common_sheet(rows: tuple[ItemDbExportRow, ...]) -> Iterable[tuple[str, ...]]:
    values = (
        (
            str(index),
            row.external_number or "",
            row.source_kind,
            row.title,
            row.unit_label,
            row.source_label,
            row.state_label,
            row.filename,
        )
        for index, row in enumerate(rows, start=1)
    )
    return chain((_COMMON_HEADERS,), values)


def _original_metadata_sheet(
    rows: tuple[ItemDbExportRow, ...], headers: tuple[str, ...]
) -> Iterable[tuple[str, ...]]:
    values = (
        (
            str(index),
            row.worksheet_name or "",
            str(row.source_row_number or ""),
            *(cell.raw_text for cell in row.original_cells or ()),
        )
        for index, row in enumerate(rows, start=1)
        if row.original_cells is not None
    )
    return chain((("순서", "원본 시트", "원본 행", *headers),), values)


def _cell_state_sheet(rows: tuple[ItemDbExportRow, ...]) -> Iterable[tuple[str, ...]]:
    values = (
        (
            str(index),
            cell.column,
            "예" if cell.present else "아니오",
            cell.cell_type or "",
            "" if cell.style_id is None else str(cell.style_id),
            cell.formula_text or "",
        )
        for index, row in enumerate(rows, start=1)
        for cell in row.original_cells or ()
    )
    return chain((("번호", "원본 열", "셀 존재", "셀 종류", "서식", "원본 수식"),), values)


def _other_metadata_sheet(rows: tuple[ItemDbExportRow, ...]) -> Iterable[tuple[str, ...]]:
    values = (
        (str(index), label, value)
        for index, row in enumerate(rows, start=1)
        for label, value in sorted(row.public_metadata)
    )
    return chain((("번호", "항목", "값"),), values)


def _write_part(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _content_types() -> bytes:
    parts = [
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    ]
    parts.extend(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, 5)
    )
    parts.append("</Types>")
    return "".join(parts).encode()


def _root_relations() -> bytes:
    return (
        f'<Relationships xmlns="{_PACKAGE_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    ).encode()


def _workbook() -> bytes:
    names = ("문항 목록", "원본 메타데이터", "원본 셀 상태", "기타 메타데이터")
    sheets = "".join(
        f'<sheet name="{_xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(names, start=1)
    )
    return (
        f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets>{sheets}</sheets></workbook>'
    ).encode()


def _workbook_relations() -> bytes:
    relationships = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, 5)
    )
    return f'<Relationships xmlns="{_PACKAGE_REL_NS}">{relationships}</Relationships>'.encode()
