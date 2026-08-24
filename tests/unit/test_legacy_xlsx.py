from __future__ import annotations

import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts import LegacyUsageMappingContractRevision
from eom_catalog_service.legacy_xlsx import LegacyXlsxError, read_legacy_usage_rows

HEADERS = (
    "source_row_key",
    "deliverable_id",
    "deliverable_revision_id",
    "assessment_form_id",
    "assessment_form_revision_id",
    "assessment_form_revision_number",
    "assessment_form_key",
    "assessment_form_ordinal",
    "assessment_form_label",
    "item_id",
    "item_revision_id",
    "item_manifest_sha256",
    "section_key",
    "section_ordinal",
    "position",
    "display_number",
    "points_milli",
    "usage_role",
    "publication_id",
    "publication_revision_id",
    "publication_revision_number",
    "publication_key",
    "publication_date",
)


def _mapping() -> LegacyUsageMappingContractRevision:
    return LegacyUsageMappingContractRevision(
        schema_version="legacy-usage-mapping-contract/1.0",
        mapping_contract_id="legacymap_" + "1" * 32,
        mapping_contract_revision_id="legacymaprev_" + "2" * 32,
        revision_number=1,
        state="RELEASED",
        workbook_media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        worksheet_name="placements",
        header_row=1,
        first_data_row=2,
        maximum_rows=10,
        columns={header: header for header in HEADERS},
        normalization_policy="legacy-usage-normalization/1.0",
        contract_sha256="sha256:" + "3" * 64,
        released_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
        released_by="operator_" + "4" * 32,
    )


def _column(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(ord("A") + remainder) + value
    return value


def _xlsx(
    path: Path,
    *,
    formula: bool = False,
    external: bool = False,
    duplicate_cell: bool = False,
    doctype: bool = False,
) -> None:
    values = (
        "row-001",
        "deliverable_" + "1" * 32,
        "delivrev_" + "2" * 32,
        "form_" + "3" * 32,
        "formrev_" + "4" * 32,
        "1",
        "form-01",
        "1",
        "1회",
        "item_" + "5" * 32,
        "itemrev_" + "6" * 32,
        "sha256:" + "7" * 64,
        "main",
        "1",
        "12",
        "12",
        "3000",
        "PRIMARY",
        "publication_" + "8" * 32,
        "publicationrev_" + "9" * 32,
        "1",
        "2026-release",
        "2026-08-24",
    )
    header_cells = "".join(
        f'<c r="{_column(index)}1" t="inlineStr"><is><t>{value}</t></is></c>'
        for index, value in enumerate(HEADERS, 1)
    )
    data_cells = []
    for index, value in enumerate(values, 1):
        formula_xml = "<f>1+1</f>" if formula and HEADERS[index - 1] == "position" else ""
        data_cells.append(
            f'<c r="{_column(index)}2" t="inlineStr">{formula_xml}<is><t>{value}</t></is></c>'
        )
    if duplicate_cell:
        data_cells.append('<c r="A2" t="inlineStr"><is><t>duplicate</t></is></c>')
    relation_mode = ' TargetMode="External"' if external else ""
    relation_target = "https://example.invalid/sheet.xml" if external else "worksheets/sheet1.xml"
    members = {
        "[Content_Types].xml": (
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>'
        ),
        "xl/workbook.xml": (
            ("<!DOCTYPE workbook [<!ENTITY unsafe 'x'>]>" if doctype else "")
            + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="placements" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="worksheet" Target="{relation_target}"{relation_mode}/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData><row r="1">{header_cells}</row><row r="2">'
            f"{''.join(data_cells)}</row></sheetData></worksheet>"
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_reader_decodes_only_explicit_mapped_values(tmp_path: Path) -> None:
    workbook = tmp_path / "usage.xlsx"
    _xlsx(workbook)
    rows = read_legacy_usage_rows(workbook, _mapping())
    assert len(rows) == 1
    assert rows[0].row_number == 2
    assert rows[0].values["position"] == "12"
    assert rows[0].values["item_revision_id"] == "itemrev_" + "6" * 32
    assert rows[0].formula_fields == ()


def test_reader_flags_mapped_formula_without_evaluating_it(tmp_path: Path) -> None:
    workbook = tmp_path / "formula.xlsx"
    _xlsx(workbook, formula=True)
    rows = read_legacy_usage_rows(workbook, _mapping())
    assert rows[0].formula_fields == ("position",)
    assert rows[0].values["position"] == "12"


def test_reader_rejects_external_relationships(tmp_path: Path) -> None:
    workbook = tmp_path / "external.xlsx"
    _xlsx(workbook, external=True)
    with pytest.raises(LegacyXlsxError) as captured:
        read_legacy_usage_rows(workbook, _mapping())
    assert captured.value.code == "LEGACY_XLSX_EXTERNAL_LINK_FORBIDDEN"


def test_reader_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "usage.xlsx"
    _xlsx(target)
    link = tmp_path / "usage-link.xlsx"
    link.symlink_to(target)
    with pytest.raises(LegacyXlsxError) as captured:
        read_legacy_usage_rows(link, _mapping())
    assert captured.value.code == "LEGACY_XLSX_FILE_INVALID"


@pytest.mark.parametrize(
    ("member_name", "unix_mode", "expected_code"),
    (
        ("../escape.xml", stat.S_IFREG | 0o600, "LEGACY_XLSX_PACKAGE_INVALID"),
        ("xl/linked.xml", stat.S_IFLNK | 0o777, "LEGACY_XLSX_PACKAGE_INVALID"),
        ("xl/vbaProject.bin", stat.S_IFREG | 0o600, "LEGACY_XLSX_ACTIVE_CONTENT_FORBIDDEN"),
    ),
)
def test_reader_rejects_unsafe_archive_members(
    tmp_path: Path, member_name: str, unix_mode: int, expected_code: str
) -> None:
    workbook = tmp_path / "unsafe.xlsx"
    _xlsx(workbook)
    member = zipfile.ZipInfo(member_name)
    member.create_system = 3
    member.external_attr = unix_mode << 16
    with zipfile.ZipFile(workbook, "a") as archive:
        archive.writestr(member, b"unsafe")
    with pytest.raises(LegacyXlsxError) as captured:
        read_legacy_usage_rows(workbook, _mapping())
    assert captured.value.code == expected_code


@pytest.mark.parametrize(
    ("option", "expected_code"),
    (
        ({"duplicate_cell": True}, "LEGACY_XLSX_CELL_INVALID"),
        ({"doctype": True}, "LEGACY_XLSX_PACKAGE_INVALID"),
    ),
)
def test_reader_rejects_ambiguous_cells_and_xml_declarations(
    tmp_path: Path, option: dict[str, bool], expected_code: str
) -> None:
    workbook = tmp_path / "ambiguous.xlsx"
    _xlsx(workbook, **option)
    with pytest.raises(LegacyXlsxError) as captured:
        read_legacy_usage_rows(workbook, _mapping())
    assert captured.value.code == expected_code
