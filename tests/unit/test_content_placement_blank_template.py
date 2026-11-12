"""The distributable template contains formatting, never example user data."""

from collections.abc import Callable
from pathlib import Path
from runpy import run_path
from typing import cast
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/content_planning/build_import_template.py"


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    build = cast(Callable[[Path], None], run_path(str(SCRIPT))["build_template"])
    output = tmp_path / "template.xlsx"
    build(output)
    return output


def test_inputs_are_blank(workbook: Path) -> None:
    with ZipFile(workbook) as archive:
        info = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        for index in range(2, 8):
            cell = info.find(f".//x:c[@r='B{index}']", NS)
            assert cell is not None and len(cell) == 0
        placements = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        rows = placements.findall("x:sheetData/x:row", NS)
        assert len(rows) == 201
        assert all(len(cell) == 0 for row in rows[1:] for cell in row)
        assert [el.text for el in rows[0].findall(".//x:t", NS)] == [
            "묶음",
            "회차·단원",
            "문항 번호",
            "고유번호 *",
            "배점",
            "메모",
        ]


def test_leading_zero_format_and_validation(workbook: Path) -> None:
    with ZipFile(workbook) as archive:
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        formats = styles.findall("x:cellXfs/x:xf", NS)
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        for cell in sheet.findall(".//x:c", NS):
            if cell.get("r", "").startswith("D") and cell.get("r") != "D1":
                assert formats[int(cell.attrib["s"])].get("numFmtId") == "49"
        column = sheet.find("x:cols/x:col[@min='4']", NS)
        assert column is not None and formats[int(column.attrib["style"])].get("numFmtId") == "49"
        validation = sheet.find("x:dataValidations/x:dataValidation[@sqref='D2:D1048576']", NS)
        assert validation is not None and validation.get("errorStyle") == "stop"
        formula = validation.findtext("x:formula1", namespaces=NS)
        assert formula is not None and "ISTEXT(D2)" in formula and "VALUE(D2)>=0" in formula


def test_only_safe_local_package_members(workbook: Path) -> None:
    with ZipFile(workbook) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            assert "vba" not in name.lower() and "external" not in name.lower()
            root = ET.fromstring(archive.read(name))
            assert root.findall(".//x:f", NS) == []
            assert all(node.get("TargetMode") != "External" for node in root.iter())
        root = ET.fromstring(archive.read("xl/workbook.xml"))
        assert [sheet.get("name") for sheet in root.findall("x:sheets/x:sheet", NS)] == [
            "교재 정보",
            "문항 배치",
            "작성 안내",
        ]


def test_points_stay_numeric_beyond_preformatted_rows(workbook: Path) -> None:
    with ZipFile(workbook) as archive:
        styles = ET.fromstring(archive.read("xl/styles.xml"))
        formats = styles.findall("x:cellXfs/x:xf", NS)
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        column = sheet.find("x:cols/x:col[@min='5']", NS)
        assert column is not None and formats[int(column.attrib["style"])].get("numFmtId") == "0"
        for cell in sheet.findall(".//x:c", NS):
            if cell.get("r", "").startswith("E") and cell.get("r") != "E1":
                assert formats[int(cell.attrib["s"])].get("numFmtId") == "0"
        validation = sheet.find("x:dataValidations/x:dataValidation[@sqref='E2:E1048576']", NS)
        assert validation is not None
        assert validation.findtext("x:formula1", namespaces=NS) == (
            "AND(ISNUMBER(E2),E2>=0,E2<=1000,ROUND(E2,3)=E2)"
        )


def test_deterministic_and_no_overwrite(workbook: Path, tmp_path: Path) -> None:
    build = cast(Callable[[Path], None], run_path(str(SCRIPT))["build_template"])
    second = tmp_path / "second.xlsx"
    build(second)
    assert workbook.read_bytes() == second.read_bytes()
    with pytest.raises(FileExistsError):
        build(workbook)


def test_metadata_dropdowns_are_blank_and_visible(workbook: Path) -> None:
    with ZipFile(workbook) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        lists = root.findall("x:dataValidations/x:dataValidation[@type='list']", NS)
        assert {entry.attrib["sqref"] for entry in lists} == {"B3", "B6"}
        assert all(entry.get("showDropDown") == "0" for entry in lists)
        guide = ET.fromstring(archive.read("xl/worksheets/sheet3.xml"))
        assert "별도 구현 단계" in " ".join(guide.itertext())
