"""Lossless, bounded exam metadata decoder; formulas are observed, never evaluated.

Unlike the content-placement template reader this input permits duplicate headers,
header offsets and unheaded external IDs. Those semantics cannot reuse its strict
template-only public API. This adapter owns metadata mapping, not Item registration.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import stat
import unicodedata
from collections import defaultdict
from io import BytesIO
from typing import Literal, cast
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from eom_catalog_contracts.native_exam_intake import (
    NativeExamCell,
    NativeExamColumn,
    NativeExamFormulaAttribute,
    NativeExamSemantic,
    NativeExamWorkbookDocument,
    NativeExamWorkbookRow,
    NativeExamWorksheet,
)
from pydantic import ValidationError

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_CELL = re.compile(r"^([A-Z]{1,3})([1-9][0-9]{0,6})$")
MAX_WORKBOOK_BYTES = 8 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
_HEADERS: dict[str, NativeExamSemantic] = {
    "문항번호": "QUESTION_NUMBER",
    "문항 번호": "QUESTION_NUMBER",
    "Tag(단원)": "UNIT",
    "단원": "UNIT",
    "소속 단원": "UNIT",
    "출처(파일명)": "SOURCE_LABEL",
    "출처": "SOURCE_LABEL",
    "콘텐츠(출제자명)": "AUTHOR",
    "출제자": "AUTHOR",
    "실제 배점": "POINTS",
    "배점": "POINTS",
    "난이도": "DIFFICULTY",
    "탐구 여부": "INQUIRY",
    "분류": "CLASSIFICATION",
    "학년": "GRADE",
    "과목": "SUBJECT",
    "고유번호": "EXTERNAL_NUMBER",
    "고유 번호": "EXTERNAL_NUMBER",
    "인덱스": "EXTERNAL_NUMBER",
}


class NativeExamWorkbookError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "NATIVE_EXAM_WORKBOOK_" + code
        super().__init__(self.code)


def _xml(archive: ZipFile, name: str) -> ET.Element:
    if archive.getinfo(name).file_size > MAX_XML_BYTES:
        raise NativeExamWorkbookError("LIMIT")
    raw = archive.read(name)
    if b"\x00" in raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise NativeExamWorkbookError("XML_INVALID")
    return ET.fromstring(raw)


def _validate(archive: ZipFile) -> None:
    infos = archive.infolist()
    if not 1 <= len(infos) <= 512:
        raise NativeExamWorkbookError("LIMIT")
    seen: set[str] = set()
    total = 0
    for i in infos:
        name = i.filename
        key = unicodedata.normalize("NFC", name).casefold()
        if (
            key in seen
            or name.startswith("/")
            or "\\" in name
            or ":" in name
            or any(p in {"", ".", ".."} for p in name.rstrip("/").split("/"))
            or any(ord(c) < 32 for c in name)
            or i.flag_bits & 1
            or stat.S_ISLNK(i.external_attr >> 16)
            or i.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or not 0 <= i.file_size <= MAX_XML_BYTES
            or i.file_size > 1000 * max(1, i.compress_size)
        ):
            raise NativeExamWorkbookError("PACKAGE_INVALID")
        seen.add(key)
        total += i.file_size
        if total > MAX_EXPANDED_BYTES:
            raise NativeExamWorkbookError("LIMIT")
        if any(p in key for p in ("vba", "externallinks/", "embeddings/")) or (
            key == "xl/connections.xml"
        ):
            raise NativeExamWorkbookError("ACTIVE_CONTENT_FORBIDDEN")
        if name.endswith(".rels"):
            rels = _xml(archive, name)
            if rels.tag != f"{{{_PKG}}}Relationships":
                raise NativeExamWorkbookError("PACKAGE_INVALID")
            if any(r.get("TargetMode") == "External" for r in rels):
                raise NativeExamWorkbookError("EXTERNAL_LINK_FORBIDDEN")
    required = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}
    if not required <= set(archive.namelist()):
        raise NativeExamWorkbookError("PACKAGE_INVALID")
    types = _xml(archive, "[Content_Types].xml")
    if any("macro" in n.get("ContentType", "").lower() for n in types):
        raise NativeExamWorkbookError("ACTIVE_CONTENT_FORBIDDEN")


def _worksheets(archive: ZipFile) -> tuple[tuple[str, str], ...]:
    wb = _xml(archive, "xl/workbook.xml")
    if wb.tag != f"{{{_NS}}}workbook":
        raise NativeExamWorkbookError("PACKAGE_INVALID")
    relations: dict[str, str] = {}
    seen: set[str] = set()
    names = set(archive.namelist())
    for r in _xml(archive, "xl/_rels/workbook.xml.rels"):
        key = r.get("Id", "")
        if not key or key in seen:
            raise NativeExamWorkbookError("PACKAGE_INVALID")
        seen.add(key)
        if r.get("Type") != _REL + "/worksheet":
            continue
        target = r.get("Target", "")
        if not target or "\\" in target or ":" in target or ".." in target.split("/"):
            raise NativeExamWorkbookError("PACKAGE_INVALID")
        member = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
        )
        if not member.startswith("xl/worksheets/") or member not in names:
            raise NativeExamWorkbookError("PACKAGE_INVALID")
        relations[key] = member
    result = []
    for s in wb.findall(f"{{{_NS}}}sheets/{{{_NS}}}sheet"):
        name = s.get("name", "")
        rid = s.get(f"{{{_REL}}}id", "")
        if not name or rid not in relations:
            raise NativeExamWorkbookError("PACKAGE_INVALID")
        result.append((name, relations[rid]))
    if not 1 <= len(result) <= 32 or len({p for _, p in result}) != len(result):
        raise NativeExamWorkbookError("SHEET_INVALID")
    return tuple(result)


def _text(element: ET.Element) -> str:
    text = "".join(n.text or "" for n in element.iter(f"{{{_NS}}}t"))
    if len(text) > 32767:
        raise NativeExamWorkbookError("CELL_LIMIT")
    return text


def _column_number(name: str) -> int:
    result = 0
    for c in name:
        result = result * 26 + ord(c) - ord("A") + 1
    return result


def _decode_cells(root: ET.Element, shared: tuple[str, ...]) -> tuple[NativeExamCell, ...]:
    if root.tag != f"{{{_NS}}}worksheet":
        raise NativeExamWorkbookError("PACKAGE_INVALID")
    result: list[NativeExamCell] = []
    previous = 0
    seen: set[str] = set()
    rows = root.findall(f"{{{_NS}}}sheetData/{{{_NS}}}row")
    if len(rows) > 10002:
        raise NativeExamWorkbookError("LIMIT")
    for row in rows:
        number = int(row.get("r", "0"))
        if not previous < number <= 1048576:
            raise NativeExamWorkbookError("ROW_ORDER_INVALID")
        previous = number
        for c in row.findall(f"{{{_NS}}}c"):
            ref = c.get("r", "")
            match = _CELL.fullmatch(ref)
            if (
                match is None
                or int(match[2]) != number
                or ref in seen
                or _column_number(match[1]) > 256
            ):
                raise NativeExamWorkbookError("CELL_INVALID")
            seen.add(ref)
            kind = c.get("t", "n")
            if kind not in {"n", "s", "inlineStr", "str", "b", "e", "d"}:
                raise NativeExamWorkbookError("CELL_INVALID")
            v = c.find(f"{{{_NS}}}v")
            raw = v.text if v is not None else None
            value = raw
            if kind == "s":
                if raw is None or not raw.isdigit() or not 0 <= int(raw) < len(shared):
                    raise NativeExamWorkbookError("CELL_INVALID")
                value = shared[int(raw)]
            elif kind == "inlineStr":
                inline = c.find(f"{{{_NS}}}is")
                value = _text(inline) if inline is not None else ""
            f = c.find(f"{{{_NS}}}f")
            result.append(
                NativeExamCell(
                    reference=ref,
                    value=value,
                    raw_value=raw,
                    storage_type=cast(Literal["n", "s", "inlineStr", "str", "b", "e", "d"], kind),
                    formula=(f.text or "") if f is not None else None,
                    formula_attributes=tuple(
                        NativeExamFormulaAttribute(name=k, value=v)
                        for k, v in sorted(f.attrib.items())
                    )
                    if f is not None
                    else (),
                )
            )
            if len(result) > 100000:
                raise NativeExamWorkbookError("LIMIT")
    return tuple(result)


def _mapping(name: str, member: str, cells: tuple[NativeExamCell, ...]) -> NativeExamWorksheet:
    by_row: dict[int, dict[str, NativeExamCell]] = defaultdict(dict)
    for cell in cells:
        match = _CELL.fullmatch(cell.reference)
        assert match is not None
        by_row[int(match[2])][match[1]] = cell
    headers = [
        (n, row)
        for n, row in by_row.items()
        if n <= 100
        and any(_HEADERS.get((c.value or "").strip()) == "QUESTION_NUMBER" for c in row.values())
    ]
    if len(headers) > 1:
        raise NativeExamWorkbookError("HEADER_AMBIGUOUS")
    if not headers:
        return NativeExamWorksheet(
            name=name,
            member_path=member,
            header_row=None,
            external_number_basis="ABSENT",
            columns=(),
            cells=cells,
            rows=(),
        )
    header_number, header = headers[0]
    columns: dict[str, NativeExamColumn] = {
        col: NativeExamColumn(
            column=col,
            header=c.value or "",
            semantic=_HEADERS.get((c.value or "").strip(), "UNMAPPED"),
        )
        for col, c in header.items()
    }
    mapped: dict[NativeExamSemantic, list[str]] = defaultdict(list)
    for col, descriptor in columns.items():
        mapped[descriptor.semantic].append(col)
    if len(mapped["QUESTION_NUMBER"]) != 1:
        raise NativeExamWorkbookError("QUESTION_COLUMN_AMBIGUOUS")
    qcol = mapped["QUESTION_NUMBER"][0]
    data = [
        (n, row)
        for n, row in by_row.items()
        if n > header_number
        and (
            (row.get(qcol) is not None and row[qcol].value not in {None, ""})
            or any(
                (row.get(col) is not None and row[col].value not in {None, ""})
                for key in cast(tuple[NativeExamSemantic, ...], ("SOURCE_LABEL", "UNIT"))
                for col in mapped[key]
            )
        )
    ]
    if not data:
        raise NativeExamWorkbookError("QUESTIONS_MISSING")
    basis: Literal["EXPLICIT_HEADER", "RIGHTMOST_UNTITLED_FIVE_DIGIT", "ABSENT"] = "ABSENT"
    if mapped["EXTERNAL_NUMBER"]:
        if len(mapped["EXTERNAL_NUMBER"]) != 1:
            raise NativeExamWorkbookError("EXTERNAL_NUMBER_AMBIGUOUS")
        basis = "EXPLICIT_HEADER"
    else:
        occupied = {c for _, row in data for c, cell in row.items() if cell.value not in {None, ""}}
        rightmost = max(occupied, key=_column_number)
        last_header = max(
            (_column_number(c) for c, d in columns.items() if d.header.strip()), default=0
        )
        candidate_values = [
            row[rightmost].value
            for _, row in data
            if rightmost in row and row[rightmost].value not in {None, ""}
        ]
        if (
            _column_number(rightmost) > last_header
            and candidate_values
            and all(v is not None and re.fullmatch(r"[0-9]{5}", v) for v in candidate_values)
        ):
            columns[rightmost] = NativeExamColumn(
                column=rightmost, header="", semantic="EXTERNAL_NUMBER"
            )
            mapped["EXTERNAL_NUMBER"] = [rightmost]
            basis = "RIGHTMOST_UNTITLED_FIVE_DIGIT"
        elif _column_number(rightmost) > last_header:
            raise NativeExamWorkbookError("UNTITLED_COLUMN_AMBIGUOUS")
    decoded = []
    for n, row in data:
        values: dict[str, str] = {}
        for semantic, cols in mapped.items():
            if semantic == "UNMAPPED" or not cols:
                continue
            observations = [row.get(c) for c in cols]
            if any(c is not None and c.formula is not None for c in observations):
                raise NativeExamWorkbookError("MAPPED_FORMULA_UNSUPPORTED")
            actual = [(c.value or "") if c is not None else "" for c in observations]
            if len(set(actual)) > 1:
                raise NativeExamWorkbookError("DUPLICATE_HEADER_CONFLICT")
            values[semantic] = actual[0]
        question = values.get("QUESTION_NUMBER", "")
        if not re.fullmatch(r"[1-9][0-9]{0,3}", question):
            raise NativeExamWorkbookError("QUESTION_NUMBER_INVALID")
        external = values.get("EXTERNAL_NUMBER", "") or None
        if external is not None and not re.fullmatch(r"[0-9]{5}", external):
            raise NativeExamWorkbookError("EXTERNAL_NUMBER_INVALID")
        unit = values.get("UNIT", "")
        decoded.append(
            NativeExamWorkbookRow(
                row_number=n,
                question_number=int(question),
                external_number=external,
                unit_raw=unit,
                unit_normalized=unicodedata.normalize("NFC", unit).strip(),
                source_label=values.get("SOURCE_LABEL", ""),
            )
        )
    return NativeExamWorksheet(
        name=name,
        member_path=member,
        header_row=header_number,
        external_number_basis=basis,
        columns=tuple(sorted(columns.values(), key=lambda c: _column_number(c.column))),
        cells=cells,
        rows=tuple(decoded),
    )


def read_native_exam_workbook(
    raw: bytes, *, source_sha256: str | None = None
) -> NativeExamWorkbookDocument:
    """Decode exact Artifact bytes while keeping raw cells separate from semantic mappings."""
    if not 8 <= len(raw) <= MAX_WORKBOOK_BYTES:
        raise NativeExamWorkbookError("FILE_INVALID")
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if source_sha256 is not None and source_sha256 != digest:
        raise NativeExamWorkbookError("HASH_MISMATCH")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            _validate(archive)
            shared: tuple[str, ...] = ()
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = _xml(archive, "xl/sharedStrings.xml").findall(f"{{{_NS}}}si")
                if len(strings) > 100000:
                    raise NativeExamWorkbookError("LIMIT")
                shared = tuple(_text(s) for s in strings)
            sheets = tuple(
                _mapping(name, member, _decode_cells(_xml(archive, member), shared))
                for name, member in _worksheets(archive)
            )
        return NativeExamWorkbookDocument(sha256=digest, bytes=len(raw), worksheets=sheets)
    except NativeExamWorkbookError:
        raise
    except (BadZipFile, KeyError, ValueError, ET.ParseError, RuntimeError, ValidationError) as exc:
        raise NativeExamWorkbookError("PACKAGE_INVALID") from exc
