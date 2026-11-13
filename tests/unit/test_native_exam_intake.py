"""Synthetic native ZIP/metadata contracts, including observed workbook shape variations."""

from __future__ import annotations

import hashlib
import json
import stat
import struct
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from eom_catalog_contracts.native_exam_intake import NativeExamWorkbookDocument
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.native_exam_archive import (
    NativeExamArchiveError,
    read_native_exam_archive,
)
from eom_catalog_service.native_exam_workbook import (
    NativeExamWorkbookError,
    read_native_exam_workbook,
)
from pydantic import ValidationError

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_HWP = bytes.fromhex("d0cf11e0a1b11ae1") + b"synthetic-unvalidated-HWP"


def _zip(parts: dict[str, bytes]) -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as z:
        for name, value in parts.items():
            z.writestr(name, value)
    return stream.getvalue()


def _cell(row: ET.Element, col: str, value: str, *, number: bool = False) -> None:
    c = ET.SubElement(row, f"{{{_NS}}}c", r=col + row.attrib["r"], t="n" if number else "inlineStr")
    if number:
        ET.SubElement(c, f"{{{_NS}}}v").text = value
    else:
        ET.SubElement(ET.SubElement(c, f"{{{_NS}}}is"), f"{{{_NS}}}t").text = value


def _parts(
    *,
    offset: int = 2,
    shifted: bool = True,
    ids: bool = True,
    conflict: bool = False,
    bad_id: str | None = None,
) -> dict[str, bytes]:
    root = ET.Element(f"{{{_NS}}}worksheet")
    data = ET.SubElement(root, f"{{{_NS}}}sheetData")
    if offset == 2:
        title = ET.SubElement(data, f"{{{_NS}}}row", r="1")
        _cell(title, "A", "회차")
        _cell(title, "B", "합성01회")
    hdr = ET.SubElement(data, f"{{{_NS}}}row", r=str(offset))
    heads = [
        ("B", "실제 배점"),
        ("C", "난이도"),
        ("D", "탐구 여부"),
        ("E", "출처(파일명)"),
        ("F", "콘텐츠(출제자명)"),
    ]
    if shifted:
        heads += [
            ("G", "탐구 여부"),
            ("H", "문항번호"),
            ("I", "난이도"),
            ("J", "Tag(단원)"),
            ("K", "분류"),
            ("L", "학년"),
            ("M", "과목"),
        ]
    else:
        heads += [
            ("G", "문항번호"),
            ("H", "난이도"),
            ("I", "Tag(단원)"),
            ("J", "분류"),
            ("K", "학년"),
            ("L", "과목"),
        ]
    for col, text in heads:
        _cell(hdr, col, text)
    for q in range(1, 3):
        row = ET.SubElement(data, f"{{{_NS}}}row", r=str(offset + q))
        values = {"B": "2.5", "C": "3", "D": "X", "E": f"合成_{q:02d}번", "F": "합성"}
        values.update(
            {
                "G": "X",
                "H": str(q),
                "I": "2" if conflict else "3",
                "J": " 3.시스템과 상호작용",
                "K": "통합과학 - 창작",
                "L": "고3",
                "M": "통합과학",
            }
            if shifted
            else {
                "G": str(q),
                "H": "3",
                "I": " 3.시스템과 상호작용",
                "J": "통합과학 - 창작",
                "K": "고3",
                "L": "통합과학",
            }
        )
        if ids:
            values["N" if shifted else "M"] = bad_id or str(12340 + q)
        for col, value in values.items():
            _cell(row, col, value, number=col in {"B", "C", "H" if shifted else "G"})
    total = ET.SubElement(data, f"{{{_NS}}}row", r=str(offset + 3))
    _cell(total, "A", "배점 합계")
    cell = ET.SubElement(total, f"{{{_NS}}}c", r=f"B{offset + 3}")
    ET.SubElement(cell, f"{{{_NS}}}f", t="normal").text = f"SUM(B{offset + 1}:B{offset + 2})"
    ET.SubElement(cell, f"{{{_NS}}}v").text = "5"
    ET.SubElement(ET.SubElement(root, f"{{{_NS}}}mergeCells"), f"{{{_NS}}}mergeCell", ref="K1:M1")
    wb = ET.Element(f"{{{_NS}}}workbook")
    ET.SubElement(
        ET.SubElement(wb, f"{{{_NS}}}sheets"),
        f"{{{_NS}}}sheet",
        name="등록용",
        sheetId="1",
        attrib={f"{{{_REL}}}id": "rId1"},
    )
    rels = ET.Element(f"{{{_PKG}}}Relationships")
    ET.SubElement(
        rels,
        f"{{{_PKG}}}Relationship",
        Id="rId1",
        Type=_REL + "/worksheet",
        Target="worksheets/sheet1.xml",
    )
    return {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": ET.tostring(wb),
        "xl/_rels/workbook.xml.rels": ET.tostring(rels),
        "xl/worksheets/sheet1.xml": ET.tostring(root),
    }


@pytest.mark.parametrize("offset,shifted", [(2, False), (2, True), (1, True)])
@pytest.mark.parametrize("ids", [True, False])
def test_workbook_header_offsets_duplicate_columns_and_missing_ids(
    offset: int, shifted: bool, ids: bool
) -> None:
    raw = _zip(_parts(offset=offset, shifted=shifted, ids=ids))
    doc = read_native_exam_workbook(raw)
    sheet = doc.worksheets[0]
    assert sheet.header_row == offset
    assert [r.question_number for r in sheet.rows] == [1, 2]
    assert [r.external_number for r in sheet.rows] == (["12341", "12342"] if ids else [None, None])
    assert sheet.rows[0].unit_raw == " 3.시스템과 상호작용"
    assert sheet.rows[0].unit_normalized == "3.시스템과 상호작용"
    assert sheet.external_number_basis == ("RIGHTMOST_UNTITLED_FIVE_DIGIT" if ids else "ABSENT")
    assert sum(c.semantic == "DIFFICULTY" for c in sheet.columns) == 2
    formula = next(c for c in sheet.cells if c.formula is not None)
    assert formula.value == formula.raw_value == "5"
    assert formula.formula_attributes[0].value == "normal"
    assert NativeExamWorkbookDocument.model_validate_json(doc.model_dump_json()) == doc
    validate_contract("material-native-exam-v1", doc.model_dump(mode="json"))


def test_duplicate_semantic_columns_conflicting_values_rejected() -> None:
    with pytest.raises(NativeExamWorkbookError, match="DUPLICATE_HEADER_CONFLICT"):
        read_native_exam_workbook(_zip(_parts(conflict=True)))


@pytest.mark.parametrize("value", ["1234", "123456", "12341.0", "1234a"])
def test_untitled_column_never_guesses_invalid_external_numbers(value: str) -> None:
    with pytest.raises(NativeExamWorkbookError, match="UNTITLED_COLUMN_AMBIGUOUS"):
        read_native_exam_workbook(_zip(_parts(bad_id=value)))


def test_hash_mismatch_and_immutable_semantic_metadata() -> None:
    raw = _zip(_parts())
    with pytest.raises(NativeExamWorkbookError, match="HASH_MISMATCH"):
        read_native_exam_workbook(raw, source_sha256="sha256:" + "0" * 64)
    doc = read_native_exam_workbook(raw)
    with pytest.raises(ValidationError):
        doc.worksheets[0].rows[0].question_number = 2
    payload = json.loads(doc.model_dump_json())
    payload["worksheets"][0]["rows"][0]["unit_normalized"] = "changed"
    with pytest.raises(ValidationError, match="UNIT_NORMALIZATION_INVALID"):
        NativeExamWorkbookDocument.model_validate(payload)


def test_question_and_external_numbers_unique() -> None:
    parts = _parts()
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    cell = root.find(f".//{{{_NS}}}c[@r='N4']/{{{_NS}}}is/{{{_NS}}}t")
    assert cell is not None
    cell.text = "12341"
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    with pytest.raises(NativeExamWorkbookError, match="PACKAGE_INVALID"):
        read_native_exam_workbook(_zip(parts))


@pytest.mark.parametrize("mode", ["entity", "external", "vba", "traversal", "case_collision"])
def test_workbook_untrusted_package_rejected(mode: str) -> None:
    parts = _parts()
    if mode == "entity":
        parts["xl/workbook.xml"] = b'<!DOCTYPE x [<!ENTITY e "boom">]><x>&e;</x>'
    elif mode == "external":
        root = ET.fromstring(parts["xl/_rels/workbook.xml.rels"])
        root[0].set("TargetMode", "External")
        parts["xl/_rels/workbook.xml.rels"] = ET.tostring(root)
    elif mode == "vba":
        parts["xl/vbaProject.bin"] = b"forbidden"
    elif mode == "traversal":
        parts["../bad.xml"] = b"bad"
    else:
        parts["XL/workbook.xml"] = parts["xl/workbook.xml"]
    with pytest.raises(NativeExamWorkbookError):
        read_native_exam_workbook(_zip(parts))


def test_shared_string_raw_index_and_formula_cache_are_preserved() -> None:
    parts = _parts()
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    cell = root.find(f".//{{{_NS}}}c[@r='F3']")
    assert cell is not None
    cell.clear()
    cell.set("r", "F3")
    cell.set("t", "s")
    ET.SubElement(cell, f"{{{_NS}}}v").text = "0"
    parts["xl/sharedStrings.xml"] = f'<sst xmlns="{_NS}"><si><t>합성</t></si></sst>'.encode()
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    doc = read_native_exam_workbook(_zip(parts))
    observed = next(c for c in doc.worksheets[0].cells if c.reference == "F3")
    assert (observed.value, observed.raw_value, observed.storage_type) == ("합성", "0", "s")


def _exam_parts(book: bytes | None = None) -> dict[str, bytes]:
    parts = {"합성/제01회/문제지.hwp": _HWP, "합성/제01회/해설지.hwpx": _HWP}
    if book is not None:
        parts["합성/제01회/메타데이터.xlsx"] = book
    return parts


def test_archive_native_source_identity_unchanged_when_ids_supplied_later(tmp_path: Path) -> None:
    before = tmp_path / "before.zip"
    after = tmp_path / "after.zip"
    before.write_bytes(_zip(_exam_parts(_zip(_parts(ids=False)))))
    after.write_bytes(_zip(_exam_parts(_zip(_parts(ids=True)))))
    a = read_native_exam_archive(before)
    b = read_native_exam_archive(after)
    fa, fb = a.folders[0], b.folders[0]
    assert a.sha256 != b.sha256
    assert fa.workbook is not None and fb.workbook is not None
    assert fa.workbook.sha256 != fb.workbook.sha256
    assert (fa.folder_path, fa.question, fa.solutions) == (
        fb.folder_path,
        fb.question,
        fb.solutions,
    )
    assert fa.solutions.source_format == "HWP"  # container, not misleading extension
    assert a.sha256 == "sha256:" + hashlib.sha256(before.read_bytes()).hexdigest()


@pytest.mark.parametrize("extra", ["../evil.hwp", "/absolute.hwp", "x\\evil.hwp", "C:/evil.hwp"])
def test_archive_rejects_traversal_before_ignoring_metadata(tmp_path: Path, extra: str) -> None:
    parts = _exam_parts()
    parts[extra] = b"bad-source"
    path = tmp_path / "archive.zip"
    path.write_bytes(_zip(parts))
    with pytest.raises(NativeExamArchiveError, match="PATH_INVALID"):
        read_native_exam_archive(path)


@pytest.mark.parametrize("mode", ["case", "nfc", "role", "unknown", "incomplete"])
def test_archive_ambiguity_is_not_silently_repaired(tmp_path: Path, mode: str) -> None:
    parts = _exam_parts()
    if mode == "case":
        parts["합성/제01회/문제지.HWP"] = _HWP
    elif mode == "nfc":
        parts["합성/제01회/문제지.hwp"] = _HWP
    elif mode == "role":
        parts["합성/제01회/추가문제지.hwp"] = _HWP
    elif mode == "unknown":
        parts["합성/제01회/run.exe"] = b"bad-source"
    else:
        del parts["합성/제01회/해설지.hwpx"]
    path = tmp_path / "archive.zip"
    path.write_bytes(_zip(parts))
    with pytest.raises(NativeExamArchiveError):
        read_native_exam_archive(path)


def test_archive_symlink_and_local_symlink_rejected(tmp_path: Path) -> None:
    path = tmp_path / "archive.zip"
    with ZipFile(path, "w") as z:
        info = ZipInfo("__MACOSX/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, b"/etc/passwd")
    with pytest.raises(NativeExamArchiveError, match="MEMBER_INVALID"):
        read_native_exam_archive(path)
    link = tmp_path / "symlink.zip"
    link.symlink_to(path)
    with pytest.raises(NativeExamArchiveError):
        read_native_exam_archive(link)


def test_archive_unflagged_utf8_recovery_and_metadata_exclusion(tmp_path: Path) -> None:
    parts = _exam_parts()
    parts["__MACOSX/._question.hwp"] = b"finder-metadata"
    raw = bytearray(_zip(parts))
    for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        start = 0
        while (start := raw.find(signature, start)) != -1:
            flags = struct.unpack_from("<H", raw, start + offset)[0]
            struct.pack_into("<H", raw, start + offset, flags & ~0x800)
            start += 4
    path = tmp_path / "archive.zip"
    path.write_bytes(raw)
    inventory = read_native_exam_archive(path)
    assert inventory.folders[0].folder_path == "합성/제01회"
    assert inventory.folders[0].question.zip_member != inventory.folders[0].question.member_path
    assert inventory.ignored_metadata_count == 1


def test_archive_hwpx_requires_actual_native_package(tmp_path: Path) -> None:
    parts = _exam_parts()
    parts["합성/제01회/문제지.hwp"] = _zip({"not-hwpx.txt": b"not an editable package"})
    path = tmp_path / "archive.zip"
    path.write_bytes(_zip(parts))
    with pytest.raises(NativeExamArchiveError, match="SOURCE_FORMAT_INVALID"):
        read_native_exam_archive(path)


def test_native_hwpx_detected_even_when_extension_is_hwp(tmp_path: Path) -> None:
    parts = _exam_parts()
    parts["합성/제01회/문제지.hwp"] = _zip(
        {"mimetype": b"application/hwp+zip", "Contents/content.hpf": b"<package/>"}
    )
    path = tmp_path / "archive.zip"
    path.write_bytes(_zip(parts))
    assert read_native_exam_archive(path).folders[0].question.source_format == "HWPX"


@pytest.mark.parametrize("case", ["duplicate_row", "duplicate_cell", "missing_number", "formula"])
def test_workbook_row_evidence_errors_are_explicit(case: str) -> None:
    parts = _parts()
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    data = root.find(f"{{{_NS}}}sheetData")
    assert data is not None
    if case == "duplicate_row":
        data[3].set("r", "3")
    elif case == "duplicate_cell":
        ET.SubElement(data[2], f"{{{_NS}}}c", r="B3")
    elif case == "missing_number":
        cell = root.find(f".//{{{_NS}}}c[@r='H3']")
        assert cell is not None
        cell.clear()
        cell.set("r", "H3")
    else:
        cell = root.find(f".//{{{_NS}}}c[@r='H3']")
        assert cell is not None
        ET.SubElement(cell, f"{{{_NS}}}f").text = "1+0"
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    with pytest.raises(NativeExamWorkbookError):
        read_native_exam_workbook(_zip(parts))


def test_semantic_row_cannot_be_changed_independently_of_cells() -> None:
    doc = read_native_exam_workbook(_zip(_parts()))
    payload = json.loads(doc.model_dump_json())
    payload["worksheets"][0]["rows"][0]["external_number"] = "99999"
    with pytest.raises(ValidationError, match="ROW_OBSERVATION_MISMATCH"):
        NativeExamWorkbookDocument.model_validate(payload)


def test_explicit_id_header_keeps_partial_missing_numbers() -> None:
    parts = _parts()
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    header = root.find(f".//{{{_NS}}}row[@r='2']")
    assert header is not None
    _cell(header, "N", "고유번호")
    cell = root.find(f".//{{{_NS}}}c[@r='N4']")
    assert cell is not None
    cell.clear()
    cell.set("r", "N4")
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root)
    doc = read_native_exam_workbook(_zip(parts))
    assert [r.external_number for r in doc.worksheets[0].rows] == ["12341", None]
    assert doc.worksheets[0].external_number_basis == "EXPLICIT_HEADER"


def test_archive_encrypted_flag_and_member_limit_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eom_catalog_service import native_exam_archive

    raw = bytearray(_zip(_exam_parts()))
    for signature, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        start = 0
        while (start := raw.find(signature, start)) != -1:
            flags = struct.unpack_from("<H", raw, start + offset)[0]
            struct.pack_into("<H", raw, start + offset, flags | 1)
            start += 4
    path = tmp_path / "archive.zip"
    path.write_bytes(raw)
    with pytest.raises(NativeExamArchiveError, match="MEMBER_INVALID"):
        read_native_exam_archive(path)
    path.write_bytes(_zip(_exam_parts()))
    monkeypatch.setattr(native_exam_archive, "MAX_ARCHIVE_MEMBERS", 1)
    with pytest.raises(NativeExamArchiveError, match="LIMIT"):
        read_native_exam_archive(path)


def test_archive_hardlinked_input_rejected(tmp_path: Path) -> None:
    import os

    path = tmp_path / "archive.zip"
    path.write_bytes(_zip(_exam_parts()))
    os.link(path, tmp_path / "linked.zip")
    with pytest.raises(NativeExamArchiveError, match="FILE_INVALID"):
        read_native_exam_archive(path)
