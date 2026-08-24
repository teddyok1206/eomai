"""Bounded Office Open XML reader for untrusted legacy usage workbooks."""

from __future__ import annotations

import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from eom_catalog_contracts import LegacyUsageMappingContractRevision

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL_REFERENCE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 20000
_MAX_SHARED_STRINGS = 500000
_MAX_CELL_TEXT = 4096
_MAX_WORKSHEET_ROWS = 200000
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


class LegacyXlsxError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DecodedLegacyUsageRow:
    row_number: int
    values: dict[str, str]
    formula_fields: tuple[str, ...]


def read_legacy_usage_rows(
    path: Path, mapping: LegacyUsageMappingContractRevision
) -> tuple[DecodedLegacyUsageRow, ...]:
    """Decode only explicitly mapped cells without evaluating workbook formulas."""

    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not 0 < metadata.st_size <= _MAX_ARCHIVE_BYTES
    ):
        raise LegacyXlsxError("LEGACY_XLSX_FILE_INVALID", "workbook is not a bounded regular file")
    try:
        with zipfile.ZipFile(path) as archive:
            names = _validate_archive(archive)
            shared_strings = _shared_strings(archive, names)
            sheet_member = _worksheet_member(archive, mapping.worksheet_name)
            return _worksheet_rows(archive, sheet_member, shared_strings, mapping)
    except (zipfile.BadZipFile, ElementTree.ParseError, UnicodeError) as exc:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook package is invalid") from exc


def _validate_archive(archive: zipfile.ZipFile) -> frozenset[str]:
    infos = archive.infolist()
    if not 0 < len(infos) <= _MAX_ARCHIVE_MEMBERS:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook member count is invalid")
    names: set[str] = set()
    total_bytes = 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        unix_mode = info.external_attr >> 16
        if (
            name in names
            or "\\" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or (unix_mode != 0 and stat.S_ISLNK(unix_mode))
            or info.flag_bits & 0x1
            or info.compress_type not in _ALLOWED_COMPRESSION
            or info.file_size < 0
            or info.file_size > _MAX_MEMBER_BYTES
        ):
            raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook member is unsafe")
        names.add(name)
        total_bytes += info.file_size
        if total_bytes > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook expands beyond limit")
        folded = name.casefold()
        if "vbaproject" in folded or folded.startswith("xl/externallinks/"):
            raise LegacyXlsxError(
                "LEGACY_XLSX_ACTIVE_CONTENT_FORBIDDEN", "workbook active content is forbidden"
            )
    required = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    if not required.issubset(names):
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook package is incomplete")
    for name in names:
        if name.endswith(".rels"):
            root = _xml(archive, name)
            for relationship in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
                if relationship.attrib.get("TargetMode") == "External":
                    raise LegacyXlsxError(
                        "LEGACY_XLSX_EXTERNAL_LINK_FORBIDDEN",
                        "external workbook relationships are forbidden",
                    )
    return frozenset(names)


def _xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook member is missing") from exc
    if info.file_size > _MAX_MEMBER_BYTES:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook XML exceeds limit")
    payload = archive.read(info)
    if b"<!doctype" in payload.lower():
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "workbook XML declarations are unsafe")
    return ElementTree.fromstring(payload)


def _shared_strings(archive: zipfile.ZipFile, names: frozenset[str]) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in names:
        return ()
    root = _xml(archive, "xl/sharedStrings.xml")
    strings: list[str] = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        value = "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        strings.append(_normalize_cell(value))
        if len(strings) > _MAX_SHARED_STRINGS:
            raise LegacyXlsxError(
                "LEGACY_XLSX_SHARED_STRINGS_LIMIT", "workbook has too many shared strings"
            )
    return tuple(strings)


def _worksheet_member(archive: zipfile.ZipFile, worksheet_name: str) -> str:
    workbook = _xml(archive, "xl/workbook.xml")
    relation_id: str | None = None
    sheets = workbook.find(f"{{{_MAIN_NS}}}sheets")
    for sheet in () if sheets is None else sheets:
        if sheet.attrib.get("name") == worksheet_name:
            relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
            break
    if relation_id is None:
        raise LegacyXlsxError("LEGACY_XLSX_SHEET_MISSING", "mapped worksheet does not exist")
    relationships = _xml(archive, "xl/_rels/workbook.xml.rels")
    target: str | None = None
    for relationship in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        if relationship.attrib.get("Id") == relation_id:
            target = relationship.attrib.get("Target")
            break
    if target is None:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "worksheet relationship is missing")
    member = PurePosixPath("xl") / PurePosixPath(target)
    normalized = PurePosixPath(*[part for part in member.parts if part != "."])
    if normalized.is_absolute() or ".." in normalized.parts:
        raise LegacyXlsxError("LEGACY_XLSX_PACKAGE_INVALID", "worksheet path is unsafe")
    return str(normalized)


def _worksheet_rows(
    archive: zipfile.ZipFile,
    sheet_member: str,
    shared_strings: tuple[str, ...],
    mapping: LegacyUsageMappingContractRevision,
) -> tuple[DecodedLegacyUsageRow, ...]:
    root = _xml(archive, sheet_member)
    row_elements = root.findall(f".//{{{_MAIN_NS}}}row")
    if len(row_elements) > _MAX_WORKSHEET_ROWS:
        raise LegacyXlsxError("LEGACY_XLSX_ROW_LIMIT", "workbook has too many physical rows")
    header_columns: dict[str, int] | None = None
    data: list[DecodedLegacyUsageRow] = []
    mapped_columns = mapping.columns.model_dump(mode="python")
    for row in row_elements:
        row_number = _positive_int(row.attrib.get("r"), "LEGACY_XLSX_ROW_INVALID")
        values: dict[int, str] = {}
        formulas: set[int] = set()
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            reference = cell.attrib.get("r", "")
            match = _CELL_REFERENCE.fullmatch(reference)
            if match is None or int(match.group(2)) != row_number:
                raise LegacyXlsxError("LEGACY_XLSX_CELL_INVALID", "cell reference is invalid")
            column = _column_number(match.group(1))
            if column in values:
                raise LegacyXlsxError("LEGACY_XLSX_CELL_INVALID", "cell reference is duplicated")
            if cell.find(f"{{{_MAIN_NS}}}f") is not None:
                formulas.add(column)
            values[column] = _cell_text(cell, shared_strings)
        if row_number == mapping.header_row:
            header_columns = {}
            for column, value in values.items():
                if not value or value in header_columns:
                    raise LegacyXlsxError(
                        "LEGACY_XLSX_HEADER_INVALID", "headers are blank or duplicate"
                    )
                header_columns[value] = column
            missing = sorted(set(mapped_columns.values()) - set(header_columns))
            if missing:
                raise LegacyXlsxError(
                    "LEGACY_XLSX_COLUMN_MISSING", "mapped workbook column is missing"
                )
            continue
        if row_number < mapping.first_data_row:
            continue
        if len(data) >= mapping.maximum_rows:
            raise LegacyXlsxError("LEGACY_XLSX_ROW_LIMIT", "workbook exceeds mapped row limit")
        if not values:
            continue
        if header_columns is None:
            raise LegacyXlsxError("LEGACY_XLSX_HEADER_MISSING", "mapped header row is missing")
        field_values = {
            field: values.get(header_columns[header], "")
            for field, header in mapped_columns.items()
        }
        if not any(field_values.values()):
            continue
        formula_fields = tuple(
            sorted(
                field
                for field, header in mapped_columns.items()
                if header_columns[header] in formulas
            )
        )
        data.append(
            DecodedLegacyUsageRow(
                row_number=row_number,
                values=field_values,
                formula_fields=formula_fields,
            )
        )
    if header_columns is None:
        raise LegacyXlsxError("LEGACY_XLSX_HEADER_MISSING", "mapped header row is missing")
    return tuple(data)


def _cell_text(cell: ElementTree.Element, shared_strings: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find(f"{{{_MAIN_NS}}}is")
        value = (
            ""
            if inline is None
            else "".join(node.text or "" for node in inline.iter(f"{{{_MAIN_NS}}}t"))
        )
    else:
        value_node = cell.find(f"{{{_MAIN_NS}}}v")
        raw = "" if value_node is None else value_node.text or ""
        if cell_type == "s":
            index = _positive_int(raw, "LEGACY_XLSX_SHARED_STRING_INVALID", allow_zero=True)
            try:
                value = shared_strings[index]
            except IndexError as exc:
                raise LegacyXlsxError(
                    "LEGACY_XLSX_SHARED_STRING_INVALID", "shared string index is invalid"
                ) from exc
        elif cell_type in {None, "n", "str", "b"}:
            value = raw
        elif cell_type in {"e", "d"}:
            raise LegacyXlsxError("LEGACY_XLSX_CELL_TYPE_UNSUPPORTED", "cell type is unsupported")
        else:
            raise LegacyXlsxError("LEGACY_XLSX_CELL_TYPE_UNSUPPORTED", "cell type is unsupported")
    return _normalize_cell(value)


def _normalize_cell(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", value).strip().split())
    if len(normalized) > _MAX_CELL_TEXT or any(ord(character) < 32 for character in normalized):
        raise LegacyXlsxError("LEGACY_XLSX_CELL_INVALID", "cell text is invalid")
    return normalized


def _positive_int(value: str | None, code: str, *, allow_zero: bool = False) -> int:
    try:
        parsed = int(value or "")
    except ValueError as exc:
        raise LegacyXlsxError(code, "workbook integer is invalid") from exc
    if parsed < (0 if allow_zero else 1):
        raise LegacyXlsxError(code, "workbook integer is invalid")
    return parsed


def _column_number(value: str) -> int:
    result = 0
    for character in value:
        result = result * 26 + ord(character) - ord("A") + 1
    return result
