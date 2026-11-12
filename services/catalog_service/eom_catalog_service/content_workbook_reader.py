"""Bounded standard-template XLSX decoding; cells are data, never executable formulas."""

from __future__ import annotations

import os
import posixpath
import re
import stat
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path, PurePosixPath
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from eom_catalog_contracts.content_workbook_import import (
    CONTENT_WORKBOOK_MAX_BYTES,
    CONTENT_WORKBOOK_MAX_ROWS,
    ContentWorkbookDocument,
    ContentWorkbookMetadata,
    ContentWorkbookRow,
)
from eom_catalog_contracts.content_workbook_template import HEADERS, INFO
from pydantic import ValidationError

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAX_XML_BYTES = 16 * 1024 * 1024
_MAX_EXPANDED_BYTES = 64 * 1024 * 1024
_SHEETS = frozenset({"교재 정보", "문항 배치", "작성 안내"})
_CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})")
_TYPES: dict[str, Literal["TEXTBOOK", "MOCK_EXAM", "WEEKLY", "OTHER"]] = {
    "교재": "TEXTBOOK",
    "모의고사": "MOCK_EXAM",
    "주간지": "WEEKLY",
    "기타": "OTHER",
}
_PRINT: dict[str, Literal["PRINTED", "NOT_PRINTED", "UNKNOWN"]] = {
    "인쇄 완료": "PRINTED",
    "인쇄 전": "NOT_PRINTED",
    "확인 필요": "UNKNOWN",
}


class ContentWorkbookReadError(ValueError):
    """Only stable codes cross the input boundary; cell content is never logged."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Cell:
    value: str
    numeric: bool = False


_BLANK = _Cell("")


def _fail(code: str) -> ContentWorkbookReadError:
    return ContentWorkbookReadError("CONTENT_WORKBOOK_" + code)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mode,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_content_workbook(path: Path) -> ContentWorkbookDocument:
    """Read one immutable local upload, retaining actual worksheet row coordinates."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 8 <= before.st_size <= CONTENT_WORKBOOK_MAX_BYTES
            ):
                raise _fail("FILE_INVALID")
            with ZipFile(stream) as archive:
                _validate_archive(archive)
                worksheets = _worksheets(archive)
                shared = _shared_strings(archive)
                decoded = {
                    name: _rows(_xml(archive, member), shared)
                    for name, member in worksheets.items()
                }
                document = _document_v1(decoded)
            if _identity(before) != _identity(os.fstat(stream.fileno())) or _identity(
                before
            ) != _identity(path.lstat()):
                raise _fail("FILE_CHANGED")
            return document
    except ContentWorkbookReadError:
        raise
    except (OSError, BadZipFile, ET.ParseError, UnicodeError, KeyError, ValueError) as error:
        raise _fail("PACKAGE_INVALID") from error


def _xml(archive: ZipFile, member: str) -> ET.Element:
    info = archive.getinfo(member)
    if info.file_size > _MAX_XML_BYTES:
        raise _fail("PACKAGE_LIMIT")
    raw = archive.read(member)
    upper = raw.upper()
    if b"\x00" in raw or b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _fail("PACKAGE_INVALID")
    return ET.fromstring(raw)


def _validate_archive(archive: ZipFile) -> None:
    infos = archive.infolist()
    if not 1 <= len(infos) <= 512:
        raise _fail("PACKAGE_LIMIT")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if (
            name in names
            or path.is_absolute()
            or "\\" in name
            or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
            or stat.S_ISLNK(info.external_attr >> 16)
            or info.flag_bits & 1
            or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or info.file_size > _MAX_XML_BYTES
        ):
            raise _fail("PACKAGE_INVALID")
        total += info.file_size
        if total > _MAX_EXPANDED_BYTES:
            raise _fail("PACKAGE_LIMIT")
        names.add(name)
        folded = name.lower()
        if any(value in folded for value in ("vba", "externallinks/", "embeddings/")) or folded in {
            "xl/connections.xml",
        }:
            raise _fail("ACTIVE_CONTENT_FORBIDDEN")
        if name.endswith(".rels"):
            relationships = _xml(archive, name)
            if relationships.tag != f"{{{_PKG}}}Relationships":
                raise _fail("PACKAGE_INVALID")
            if any(node.get("TargetMode") == "External" for node in relationships):
                raise _fail("EXTERNAL_LINK_FORBIDDEN")
    if not {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"} <= names:
        raise _fail("PACKAGE_INVALID")
    content_types = _xml(archive, "[Content_Types].xml")
    if any(
        "macro" in node.get("ContentType", "").lower()
        or "vba" in node.get("ContentType", "").lower()
        for node in content_types
    ):
        raise _fail("ACTIVE_CONTENT_FORBIDDEN")


def _worksheets(archive: ZipFile) -> dict[str, str]:
    workbook = _xml(archive, "xl/workbook.xml")
    if workbook.tag != f"{{{_NS}}}workbook":
        raise _fail("TEMPLATE_INVALID")
    relationships: dict[str, str] = {}
    relationship_ids: set[str] = set()
    archive_members = set(archive.namelist())
    for relation in _xml(archive, "xl/_rels/workbook.xml.rels"):
        key = relation.get("Id", "")
        if not key or key in relationship_ids:
            raise _fail("PACKAGE_INVALID")
        relationship_ids.add(key)
        if relation.get("Type") != f"{_REL}/worksheet":
            continue
        target = relation.get("Target", "")
        member = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        )
        if not member.startswith("xl/") or "\\" in target or member not in archive_members:
            raise _fail("PACKAGE_INVALID")
        relationships[key] = member
    result: dict[str, str] = {}
    for entry in workbook.findall(f"{{{_NS}}}sheets/{{{_NS}}}sheet"):
        name, relation_id = entry.get("name", ""), entry.get(f"{{{_REL}}}id", "")
        if name in result or name not in _SHEETS or relation_id not in relationships:
            raise _fail("TEMPLATE_INVALID")
        result[name] = relationships[relation_id]
    if set(result) != _SHEETS or len(set(result.values())) != 3:
        raise _fail("TEMPLATE_INVALID")
    return result


def _shared_strings(archive: ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = _xml(archive, "xl/sharedStrings.xml")
    entries = root.findall(f"{{{_NS}}}si")
    if len(entries) > 100000:
        raise _fail("PACKAGE_LIMIT")
    return tuple(_text(entry) for entry in entries)


def _text(element: ET.Element) -> str:
    value = "".join(node.text or "" for node in element.iter(f"{{{_NS}}}t"))
    if len(value) > 4096:
        raise _fail("CELL_LIMIT")
    return value


def _rows(root: ET.Element, shared: tuple[str, ...]) -> dict[int, dict[str, _Cell]]:
    if root.tag != f"{{{_NS}}}worksheet":
        raise _fail("PACKAGE_INVALID")
    if root.find(f".//{{{_NS}}}f") is not None:
        raise _fail("FORMULA_FORBIDDEN")
    if root.find(f".//{{{_NS}}}mergeCell") is not None:
        raise _fail("MERGED_CELLS_UNSUPPORTED")
    result: dict[int, dict[str, _Cell]] = {}
    previous = 0
    physical_rows = root.findall(f"{{{_NS}}}sheetData/{{{_NS}}}row")
    if len(physical_rows) > 50000:
        raise _fail("PACKAGE_LIMIT")
    for row in physical_rows:
        number = int(row.attrib["r"])
        if not previous < number <= 1048576:
            raise _fail("ROW_INVALID")
        previous = number
        values: dict[str, _Cell] = {}
        seen: set[str] = set()
        for cell in row.findall(f"{{{_NS}}}c"):
            reference = _CELL.fullmatch(cell.get("r", ""))
            if reference is None or int(reference[2]) != number or reference[1] in seen:
                raise _fail("CELL_INVALID")
            column = reference[1]
            seen.add(column)
            kind = cell.get("t", "n")
            raw = cell.findtext(f"{{{_NS}}}v", "")
            if kind == "inlineStr":
                value = _text(cell)
            elif kind == "s":
                if not re.fullmatch(r"[0-9]+", raw) or int(raw) >= len(shared):
                    raise _fail("CELL_INVALID")
                value = shared[int(raw)]
            elif kind in {"n", "str", "d"}:
                value = raw
            else:
                raise _fail("CELL_INVALID")
            if len(value) > 4096:
                raise _fail("CELL_LIMIT")
            if value.strip():
                values[column] = _Cell(value, kind == "n")
        if values:
            result[number] = values
            if len(result) > CONTENT_WORKBOOK_MAX_ROWS + 1:
                raise _fail("ROW_LIMIT")
    return result


def _headers(rows: dict[int, dict[str, _Cell]], expected: tuple[str, ...]) -> dict[str, str]:
    first = rows.get(1, {})
    names = [cell.value.strip() for cell in first.values()]
    if len(names) != len(expected) or set(names) != set(expected):
        raise _fail("TEMPLATE_INVALID")
    return {value.value.strip(): column for column, value in first.items()}


def _metadata(rows: dict[int, dict[str, _Cell]]) -> ContentWorkbookMetadata:
    columns = _headers(rows, ("교재 정보", "입력란", "작성 방법"))
    fields: dict[str, _Cell] = {}
    known = {label for label, _ in INFO}
    for number, cells in rows.items():
        if number == 1:
            continue
        label = cells.get(columns["교재 정보"], _BLANK).value.strip()
        if label not in known or label in fields or set(cells) - set(columns.values()):
            raise _fail("TEMPLATE_INVALID")
        fields[label] = cells.get(columns["입력란"], _BLANK)
    if set(fields) != known:
        raise _fail("TEMPLATE_INVALID")
    kind = fields["종류 *"].value.strip()
    print_state = fields["인쇄 여부 *"].value.strip()
    if kind not in _TYPES or print_state not in _PRINT:
        raise _fail("METADATA_INVALID")
    raw_year = fields["연도"].value.strip()
    year: int | None = None
    if raw_year:
        if re.fullmatch(r"[0-9]{4}", raw_year) is None:
            raise _fail("YEAR_INVALID")
        year = int(raw_year)
    raw_date = fields["인쇄일"].value.strip()
    printed_on: date | None = None
    if raw_date:
        if (
            fields["인쇄일"].numeric
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date) is None
        ):
            raise _fail("DATE_INVALID")
        try:
            printed_on = date.fromisoformat(raw_date)
        except ValueError as error:
            raise _fail("DATE_INVALID") from error
    try:
        return ContentWorkbookMetadata(
            content_title=fields["교재명 *"].value.strip(),
            content_type=_TYPES[kind],
            edition_label=fields["판 이름 *"].value.strip(),
            academic_year=year,
            print_status=_PRINT[print_state],
            printed_on=printed_on,
        )
    except ValidationError as error:
        raise _fail("METADATA_INVALID") from error


def _external_number(cell: _Cell) -> str:
    raw = cell.value.strip()
    if not cell.numeric and re.fullmatch(r"[0-9]{5}", raw):
        return raw
    if cell.numeric:
        try:
            value = Decimal(raw)
            if value.is_finite() and 10000 <= value <= 99999 and value == value.to_integral():
                return str(int(value))
        except InvalidOperation:
            pass
    raise _fail("NUMBER_INVALID")


def _points(cell: _Cell) -> int | None:
    raw = cell.value.strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
        if not value.is_finite() or not 0 <= value <= 1000:
            raise _fail("POINTS_INVALID")
        # Do not round away a long fractional tail using the default Decimal precision.
        with localcontext() as context:
            context.prec = max(28, len(value.as_tuple().digits) + 4)
            scaled = value * 1000
            if scaled != scaled.to_integral():
                raise _fail("POINTS_INVALID")
            return int(scaled)
    except InvalidOperation as error:
        raise _fail("POINTS_INVALID") from error


def _document_v1(sheets: dict[str, dict[int, dict[str, _Cell]]]) -> ContentWorkbookDocument:
    guide = sheets["작성 안내"]
    versions = [
        cells.get("B", _BLANK).value.strip()
        for cells in guide.values()
        if cells.get("A", _BLANK).value.strip() == "양식 버전"
    ]
    if versions != ["EOM 콘텐츠 배치 입력 양식 1.0"]:
        raise _fail("VERSION_UNSUPPORTED")
    metadata = _metadata(sheets["교재 정보"])
    rows = sheets["문항 배치"]
    columns = _headers(rows, HEADERS)
    placements: list[ContentWorkbookRow] = []
    for number, cells in rows.items():
        if number == 1:
            continue
        if set(cells) - set(columns.values()):
            raise _fail("TEMPLATE_INVALID")
        values = {label: cells.get(column, _BLANK) for label, column in columns.items()}
        try:
            placements.append(
                ContentWorkbookRow(
                    row_number=number,
                    group_label=values["묶음"].value.strip(),
                    section_label=values["회차·단원"].value.strip(),
                    display_number=values["문항 번호"].value.strip() or None,
                    external_number=_external_number(values["고유번호 *"]),
                    points_milli=_points(values["배점"]),
                    note=values["메모"].value.strip(),
                )
            )
        except ValidationError as error:
            raise _fail("ROW_INVALID") from error
    if not placements:
        raise _fail("ROWS_EMPTY")
    try:
        return ContentWorkbookDocument(metadata=metadata, rows=tuple(placements))
    except ValidationError as error:
        raise _fail("ORDER_INVALID") from error
