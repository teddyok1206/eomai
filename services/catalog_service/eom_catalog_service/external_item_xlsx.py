"""Read A:AF source observations from one untrusted external Item workbook.

This adapter does not register Items or resolve the linked documents. The source
workbook remains canonical; observations retain decoded text without normalization.
"""

from __future__ import annotations

import os
import re
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from eom_catalog_contracts import (
    EXTERNAL_ITEM_COLUMNS,
    ExternalItemCellObservation,
    ExternalItemWorkbookMapping,
)
from pydantic import ValidationError

from eom_catalog_service.legacy_xlsx import (
    LegacyXlsxError,
    _cell_text,
    _shared_strings,
    _validate_archive,
    _worksheet_member,
    _xml,
)

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
_EXTERNAL_NUMBER = re.compile(r"^[0-9]{5}$")
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_WORKSHEET_ROWS = 200000


class ExternalItemXlsxError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DecodedExternalItemRow:
    row_number: int
    external_number: str
    cells: tuple[ExternalItemCellObservation, ...]


def read_external_item_rows(
    path: Path, mapping: ExternalItemWorkbookMapping
) -> tuple[DecodedExternalItemRow, ...]:
    """Read every nonempty mapped row, preserving cell content and source shape."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= _MAX_ARCHIVE_BYTES
            ):
                raise ExternalItemXlsxError(
                    "EXTERNAL_ITEM_XLSX_FILE_INVALID", "workbook is not a bounded regular file"
                )
            with zipfile.ZipFile(source) as archive:
                names = _validate_archive(archive)
                shared_strings = _shared_strings(archive, names, normalize=False)
                sheet_member = _worksheet_member(archive, mapping.worksheet_name)
                worksheet = _xml(archive, sheet_member)
                rows = _decode_rows(worksheet, shared_strings, mapping)
            after = os.fstat(source.fileno())
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ExternalItemXlsxError(
                    "EXTERNAL_ITEM_XLSX_FILE_CHANGED", "workbook changed while reading"
                )
            return rows
    except OSError as exc:
        raise ExternalItemXlsxError(
            "EXTERNAL_ITEM_XLSX_FILE_INVALID", "workbook is unavailable"
        ) from exc
    except (
        zipfile.BadZipFile,
        ElementTree.ParseError,
        UnicodeError,
        LegacyXlsxError,
        ValidationError,
    ) as exc:
        code = (
            exc.code if isinstance(exc, LegacyXlsxError) else "EXTERNAL_ITEM_XLSX_PACKAGE_INVALID"
        )
        raise ExternalItemXlsxError(code, "external Item workbook is invalid") from exc


def _decode_rows(
    worksheet: ElementTree.Element,
    shared_strings: tuple[str, ...],
    mapping: ExternalItemWorkbookMapping,
) -> tuple[DecodedExternalItemRow, ...]:
    rows = worksheet.findall(f".//{{{_MAIN_NS}}}row")
    if len(rows) > _MAX_WORKSHEET_ROWS:
        raise ExternalItemXlsxError("EXTERNAL_ITEM_XLSX_ROW_LIMIT", "too many physical rows")
    decoded: list[DecodedExternalItemRow] = []
    seen_numbers: set[str] = set()
    previous_row = 0
    header_seen = False
    for row in rows:
        row_number = _positive_int(row.attrib.get("r"))
        if row_number <= previous_row:
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_ROW_ORDER_INVALID", "row positions are not unique and ordered"
            )
        previous_row = row_number
        cells = _decode_cells(row, row_number, shared_strings)
        if row_number == mapping.header_row:
            if tuple(cells[column].raw_text for column in EXTERNAL_ITEM_COLUMNS) != tuple(
                header.label for header in mapping.column_headers
            ):
                raise ExternalItemXlsxError(
                    "EXTERNAL_ITEM_XLSX_HEADER_MISMATCH", "workbook headers differ from mapping"
                )
            if any(cells[column].formula_text is not None for column in EXTERNAL_ITEM_COLUMNS):
                raise ExternalItemXlsxError(
                    "EXTERNAL_ITEM_XLSX_HEADER_INVALID", "header contains a formula"
                )
            header_seen = True
            continue
        if row_number < mapping.first_data_row or not cells:
            continue
        if not header_seen:
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_HEADER_MISSING", "mapped header row is missing"
            )
        if len(decoded) >= mapping.maximum_rows:
            raise ExternalItemXlsxError("EXTERNAL_ITEM_XLSX_ROW_LIMIT", "mapped row limit exceeded")
        number_cell = cells.get("U")
        if (
            number_cell is None
            or number_cell.formula_text is not None
            or _EXTERNAL_NUMBER.fullmatch(number_cell.raw_text) is None
        ):
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_NUMBER_INVALID", "U must be a literal five-digit number"
            )
        if number_cell.raw_text in seen_numbers:
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_NUMBER_DUPLICATE", "U is repeated in the workbook"
            )
        seen_numbers.add(number_cell.raw_text)
        decoded.append(
            DecodedExternalItemRow(
                row_number=row_number,
                external_number=number_cell.raw_text,
                cells=tuple(
                    cells.get(
                        column,
                        ExternalItemCellObservation(column=column, present=False, raw_text=""),
                    )
                    for column in EXTERNAL_ITEM_COLUMNS
                ),
            )
        )
    if not header_seen:
        raise ExternalItemXlsxError(
            "EXTERNAL_ITEM_XLSX_HEADER_MISSING", "mapped header row is missing"
        )
    return tuple(decoded)


def _decode_cells(
    row: ElementTree.Element, row_number: int, shared_strings: tuple[str, ...]
) -> dict[str, ExternalItemCellObservation]:
    cells: dict[str, ExternalItemCellObservation] = {}
    for cell in row.findall(f"{{{_MAIN_NS}}}c"):
        reference = cell.attrib.get("r", "")
        match = _CELL_REFERENCE.fullmatch(reference)
        if match is None or int(match.group(2)) != row_number:
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_CELL_INVALID", "cell coordinate is invalid"
            )
        column = match.group(1)
        if column not in EXTERNAL_ITEM_COLUMNS or column in cells:
            raise ExternalItemXlsxError(
                "EXTERNAL_ITEM_XLSX_CELL_INVALID", "cell is duplicated or outside A:AF"
            )
        formula = cell.find(f"{{{_MAIN_NS}}}f")
        style_text = cell.attrib.get("s")
        style_id = None if style_text is None else _nonnegative_int(style_text)
        cells[column] = ExternalItemCellObservation(
            column=column,
            present=True,
            cell_type=cell.attrib.get("t"),
            raw_text=_cell_text(cell, shared_strings, normalize=False),
            style_id=style_id,
            formula_text=None if formula is None else formula.text or "",
        )
    return cells


def _positive_int(value: str | None) -> int:
    try:
        result = int(value or "")
    except ValueError as exc:
        raise ExternalItemXlsxError(
            "EXTERNAL_ITEM_XLSX_ROW_INVALID", "row number is invalid"
        ) from exc
    if result < 1 or result > 1000000:
        raise ExternalItemXlsxError("EXTERNAL_ITEM_XLSX_ROW_INVALID", "row number is invalid")
    return result


def _nonnegative_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise ExternalItemXlsxError(
            "EXTERNAL_ITEM_XLSX_STYLE_INVALID", "style index is invalid"
        ) from exc
    if result < 0 or result > 1000000:
        raise ExternalItemXlsxError("EXTERNAL_ITEM_XLSX_STYLE_INVALID", "style index is invalid")
    return result
