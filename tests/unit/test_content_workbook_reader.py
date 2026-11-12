"""Standard XLSX structure, bounded input and immutable proposal contracts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from eom_catalog_contracts.content_workbook_import import (
    ContentWorkbookDocument,
    ContentWorkbookError,
    ContentWorkbookPreview,
    ContentWorkbookPreviewRow,
    ContentWorkbookProposal,
    ContentWorkbookResolution,
    PrepareContentWorkbookRequest,
    ReadContentWorkbookRequest,
    check_content_workbook_reply,
    parse_content_workbook_reply,
    parse_content_workbook_request,
)
from eom_catalog_contracts.content_workbook_template import render_template
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.content_workbook_reader import (
    ContentWorkbookReadError,
    read_content_workbook,
)
from pydantic import ValidationError

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SH = "xl/worksheets/sheet"
Rewrite = Callable[[dict[str, bytes]], None]


def _cell(root: ET.Element, reference: str, value: str | None, *, numeric: bool = False) -> None:
    element = root.find(f".//{{{NS}}}c[@r='{reference}']")
    if element is None:
        data = root.find(f"{{{NS}}}sheetData")
        assert data is not None
        row_number = "".join(character for character in reference if character.isdigit())
        row = data.find(f"{{{NS}}}row[@r='{row_number}']")
        if row is None:
            row = ET.SubElement(data, f"{{{NS}}}row", r=row_number)
        element = ET.SubElement(row, f"{{{NS}}}c", r=reference)
    element.clear()
    element.set("r", reference)
    if value is None:
        return
    if numeric:
        ET.SubElement(element, f"{{{NS}}}v").text = value
    else:
        element.set("t", "inlineStr")
        ET.SubElement(ET.SubElement(element, f"{{{NS}}}is"), f"{{{NS}}}t").text = value


def _change(parts: dict[str, bytes], sheet: int, change: Callable[[ET.Element], None]) -> None:
    key = f"{SH}{sheet}.xml"
    root = ET.fromstring(parts[key])
    change(root)
    parts[key] = ET.tostring(root, encoding="utf-8")


def _book(tmp_path: Path, mutate: Rewrite | None = None) -> Path:
    with ZipFile(BytesIO(render_template())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}

    def metadata(root: ET.Element) -> None:
        for reference, value in {
            "B2": "합성 교재",
            "B3": "교재",
            "B4": "초판",
            "B5": "2026",
            "B6": "인쇄 완료",
            "B7": "2026-01-02",
        }.items():
            _cell(root, reference, value)

    def placement(root: ET.Element) -> None:
        _cell(root, "D2", "00123")
        _cell(root, "D3", "10321", numeric=True)
        _cell(root, "D4", "00123")
        _cell(root, "E2", "2.125", numeric=True)
        _cell(root, "F2", "메모\n두 번째 줄")

    _change(parts, 1, metadata)
    _change(parts, 2, placement)
    if mutate is not None:
        mutate(parts)
    output = tmp_path / "book.xlsx"
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return output


def test_read_exact_numbers_duplicate_occurrences_and_optional_blanks(tmp_path: Path) -> None:
    document = read_content_workbook(_book(tmp_path))
    assert document.metadata.content_title == "합성 교재"
    assert document.metadata.printed_on is not None
    assert document.metadata.printed_on.isoformat() == "2026-01-02"
    assert [row.external_number for row in document.rows] == ["00123", "10321", "00123"]
    assert [row.row_number for row in document.rows] == [2, 3, 4]
    assert document.rows[0].points_milli == 2125
    assert document.rows[1].points_milli is None
    assert document.rows[0].group_label == document.rows[0].section_label == ""
    assert document.rows[0].display_number is None
    assert document.rows[0].note == "메모\n두 번째 줄"
    validate_contract("content-workbook-document-v1", document.model_dump(mode="json"))


@pytest.mark.parametrize(
    "numeric,value",
    [
        (True, "123"),
        (True, "00123"),
        (False, "123"),
        (False, "1.0321E4"),
        (False, "10321/2"),
        (False, "\uff11\uff12\uff13\uff14\uff15"),
        (False, ""),
    ],
)
def test_no_guessed_external_numbers(tmp_path: Path, numeric: bool, value: str) -> None:
    path = _book(
        tmp_path,
        lambda parts: _change(parts, 2, lambda root: _cell(root, "D2", value, numeric=numeric)),
    )
    with pytest.raises(ContentWorkbookReadError, match="NUMBER_INVALID"):
        read_content_workbook(path)


@pytest.mark.parametrize("value", ["10321.0", "1.0321E4"])
def test_exact_numeric_cells_can_have_spreadsheet_numeric_spelling(
    tmp_path: Path, value: str
) -> None:
    path = _book(
        tmp_path,
        lambda parts: _change(parts, 2, lambda root: _cell(root, "D2", value, numeric=True)),
    )
    assert read_content_workbook(path).rows[0].external_number == "10321"


@pytest.mark.parametrize(
    "value",
    ["-1", "1000.001", "1.0001", "NaN", "Infinity", "1/2", "2.0000000000000000000000000000001"],
)
def test_invalid_points(tmp_path: Path, value: str) -> None:
    path = _book(tmp_path, lambda parts: _change(parts, 2, lambda root: _cell(root, "E2", value)))
    with pytest.raises(ContentWorkbookReadError, match="POINTS_INVALID"):
        read_content_workbook(path)


@pytest.mark.parametrize("value", ["2026-02-30", "2026/01/01", "2026-1-1", "50000"])
def test_no_date_inference(tmp_path: Path, value: str) -> None:
    path = _book(tmp_path, lambda parts: _change(parts, 1, lambda root: _cell(root, "B7", value)))
    with pytest.raises(ContentWorkbookReadError, match="DATE_INVALID"):
        read_content_workbook(path)


def test_unknown_print_does_not_invent_print_date(tmp_path: Path) -> None:
    def change(root: ET.Element) -> None:
        _cell(root, "B6", "확인 필요")
        _cell(root, "B7", None)

    document = read_content_workbook(_book(tmp_path, lambda parts: _change(parts, 1, change)))
    assert document.metadata.print_status == "UNKNOWN" and document.metadata.printed_on is None


def test_unconfirmed_print_with_date_is_rejected(tmp_path: Path) -> None:
    path = _book(
        tmp_path, lambda parts: _change(parts, 1, lambda root: _cell(root, "B6", "인쇄 전"))
    )
    with pytest.raises(ContentWorkbookReadError, match="METADATA_INVALID"):
        read_content_workbook(path)


@pytest.mark.parametrize("column", ["A", "B"])
def test_interleaved_groups_or_sections_are_not_reordered(tmp_path: Path, column: str) -> None:
    def change(root: ET.Element) -> None:
        for number, value in enumerate(("첫 구간", "둘째 구간", "첫 구간"), 2):
            _cell(root, f"{column}{number}", value)

    path = _book(tmp_path, lambda parts: _change(parts, 2, change))
    with pytest.raises(ContentWorkbookReadError, match="ORDER_INVALID"):
        read_content_workbook(path)


def test_header_mapping_uses_names_not_fixed_column_letters(tmp_path: Path) -> None:
    def change(root: ET.Element) -> None:
        for cell in root.findall(f".//{{{NS}}}c"):
            reference = cell.attrib["r"]
            if reference.startswith("A"):
                cell.set("r", "D" + reference[1:])
            elif reference.startswith("D"):
                cell.set("r", "A" + reference[1:])

    document = read_content_workbook(_book(tmp_path, lambda parts: _change(parts, 2, change)))
    assert document.rows[0].external_number == "00123"


def test_metadata_rows_match_labels_not_positions(tmp_path: Path) -> None:
    def change(root: ET.Element) -> None:
        _cell(root, "A2", "판 이름 *")
        _cell(root, "B2", "초판")
        _cell(root, "A4", "교재명 *")
        _cell(root, "B4", "합성 교재")

    document = read_content_workbook(_book(tmp_path, lambda parts: _change(parts, 1, change)))
    assert document.metadata.content_title == "합성 교재"


def test_formulas_forbidden_but_validation_formulas_allowed(tmp_path: Path) -> None:
    assert read_content_workbook(_book(tmp_path)).rows

    def change(root: ET.Element) -> None:
        cell = root.find(f".//{{{NS}}}c[@r='D2']")
        assert cell is not None
        ET.SubElement(cell, f"{{{NS}}}f").text = '"00123"'

    path = _book(tmp_path, lambda parts: _change(parts, 2, change))
    with pytest.raises(ContentWorkbookReadError, match="FORMULA_FORBIDDEN"):
        read_content_workbook(path)


@pytest.mark.parametrize(
    "member", ["xl/vbaProject.bin", "xl/externalLinks/a.xml", "xl/embeddings/a.bin"]
)
def test_active_content_forbidden(tmp_path: Path, member: str) -> None:
    path = _book(tmp_path, lambda parts: parts.update({member: b"blocked"}))
    with pytest.raises(ContentWorkbookReadError, match="ACTIVE_CONTENT_FORBIDDEN"):
        read_content_workbook(path)


@pytest.mark.parametrize("member", ["../outside", "/outside", "xl\\outside"])
def test_unsafe_archive_paths(tmp_path: Path, member: str) -> None:
    path = _book(tmp_path, lambda parts: parts.update({member: b"blocked"}))
    with pytest.raises(ContentWorkbookReadError, match="PACKAGE_INVALID"):
        read_content_workbook(path)


def test_external_relationship_is_never_followed(tmp_path: Path) -> None:
    def change(parts: dict[str, bytes]) -> None:
        key = "xl/_rels/workbook.xml.rels"
        parts[key] = parts[key].replace(
            b'Target="styles.xml"', b'Target="https://example.invalid/a" TargetMode="External"'
        )

    with pytest.raises(ContentWorkbookReadError, match="EXTERNAL_LINK_FORBIDDEN"):
        read_content_workbook(_book(tmp_path, change))


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_doctype_is_rejected_in_all_accepted_encodings(tmp_path: Path, encoding: str) -> None:
    def change(parts: dict[str, bytes]) -> None:
        text = parts[f"{SH}2.xml"].decode()
        parts[f"{SH}2.xml"] = ('<!DOCTYPE worksheet [<!ENTITY test "bad">]>' + text).encode(
            encoding
        )

    with pytest.raises(ContentWorkbookReadError, match="PACKAGE_INVALID"):
        read_content_workbook(_book(tmp_path, change))


def test_missing_ids_are_not_silently_dropped(tmp_path: Path) -> None:
    path = _book(tmp_path, lambda parts: _change(parts, 2, lambda root: _cell(root, "D2", None)))
    with pytest.raises(ContentWorkbookReadError, match="NUMBER_INVALID"):
        read_content_workbook(path)


def test_blank_template_is_not_a_ready_import(tmp_path: Path) -> None:
    path = tmp_path / "blank.xlsx"
    path.write_bytes(render_template())
    with pytest.raises(ContentWorkbookReadError, match="METADATA_INVALID"):
        read_content_workbook(path)


def test_symlink_and_hardlink_inputs_are_rejected(tmp_path: Path) -> None:
    original = _book(tmp_path)
    link = tmp_path / "symlink.xlsx"
    link.symlink_to(original)
    with pytest.raises(ContentWorkbookReadError):
        read_content_workbook(link)
    hardlink = tmp_path / "hardlink.xlsx"
    hardlink.hardlink_to(original)
    with pytest.raises(ContentWorkbookReadError, match="FILE_INVALID"):
        read_content_workbook(hardlink)


def test_proposal_schema_and_resolution_binding(tmp_path: Path) -> None:
    document = read_content_workbook(_book(tmp_path))
    resolutions = tuple(
        ContentWorkbookResolution(
            row_number=row.row_number, status="MISSING", title=None, target=None
        )
        for row in document.rows
    )
    proposal = ContentWorkbookProposal(
        uploaded_by="operator_" + "1" * 32,
        original_filename="합성.xlsx",
        workbook_sha256="sha256:" + "1" * 64,
        workbook_bytes=100,
        document=document,
        resolutions=resolutions,
    )
    validate_contract("content-workbook-proposal-v1", proposal.model_dump(mode="json"))
    with pytest.raises(ValidationError, match="match source rows"):
        ContentWorkbookProposal.model_validate(
            proposal.model_dump() | {"resolutions": resolutions[:-1]}
        )
    with pytest.raises(ValidationError, match="exact target"):
        ContentWorkbookResolution(row_number=2, status="MATCHED", title="문항", target=None)


def test_private_request_and_reply_correlation(tmp_path: Path) -> None:
    document: ContentWorkbookDocument = read_content_workbook(_book(tmp_path))
    identity = {
        "actor_id": "operator_" + "1" * 32,
        "session_id": "apisession_" + "1" * 32,
        "request_id": "request-test",
        "authentication_time": datetime.now(UTC),
    }
    prepare = PrepareContentWorkbookRequest.model_validate(
        identity
        | {
            "original_filename": "합성.xlsx",
            "content_length": 100,
            "sha256": "sha256:" + "1" * 64,
            "idempotency_key": "workbook-test-prepare",
        }
    )
    assert parse_content_workbook_request(prepare.model_dump(mode="json")) == prepare
    pointer = OriginArtifactMemberPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "1" * 32,
        member_path="proposal.json",
        schema_ref="eom://schemas/content-planning/workbook-proposal/1.0",
        media_type="application/json",
        sha256="sha256:" + "2" * 64,
    )
    preview = ContentWorkbookPreview(
        proposal=pointer,
        original_filename=prepare.original_filename,
        workbook_sha256=prepare.sha256,
        metadata=document.metadata,
        total_rows=3,
        matched_rows=0,
        unresolved_rows=3,
        duplicate_uses=1,
        can_commit=False,
        offset=0,
        rows=tuple(
            ContentWorkbookPreviewRow(
                row=row,
                resolution=ContentWorkbookResolution(
                    row_number=row.row_number, status="MISSING", title=None, target=None
                ),
            )
            for row in document.rows
        ),
        next_offset=None,
    )
    assert parse_content_workbook_reply(preview.model_dump(mode="json")) == preview
    check_content_workbook_reply(prepare, preview)
    query = ReadContentWorkbookRequest.model_validate(
        identity | {"proposal": pointer, "offset": 0, "limit": 3}
    )
    check_content_workbook_reply(query, preview)
    with pytest.raises(ValueError, match="requested page"):
        check_content_workbook_reply(query.model_copy(update={"limit": 2}), preview)
    with pytest.raises(ValidationError, match="counts"):
        ContentWorkbookPreview.model_validate(preview.model_dump() | {"can_commit": True})
    error = ContentWorkbookError(error_code="CONTENT_WORKBOOK_PERMISSION_DENIED")
    assert parse_content_workbook_reply(error.model_dump(mode="json")) == error
