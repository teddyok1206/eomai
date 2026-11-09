"""Opt-in read-only checks against the user's workbook; never an import operation.

Only structural counts and synthetic pinned targets enter the new contracts.
The workbook, names, cell content and generated artifacts never enter Git.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from eom_catalog_contracts.curated_document_slots import CuratedDocumentAssemblyDraftV3
from eom_catalog_contracts.validation import validate_contract

from tests.unit.content_planning_fixtures import draft, item_target, slot

WORKBOOK_SHA256 = "88ae6c7564294ca518c59c3c6d0f9bbd73703b122d54f169adc46c1d6d7d2e50"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _xml(archive: ZipFile, member: str) -> ElementTree.Element:
    info = archive.getinfo(member)
    assert info.file_size <= 8_000_000
    raw = archive.read(info)
    assert b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper()
    return ElementTree.fromstring(raw)


@pytest.fixture(scope="module")
def workbook():
    configured = os.environ.get("EOM_CONTENT_PLANNING_WORKBOOK")
    if not configured:
        pytest.skip("set EOM_CONTENT_PLANNING_WORKBOOK for the read-only private workbook checks")
    path = Path(configured)
    assert path.is_file() and path.stat().st_size == 757715
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == WORKBOOK_SHA256
    result = {}
    with ZipFile(path) as archive:
        assert len(archive.infolist()) <= 1000
        assert sum(row.file_size for row in archive.infolist()) <= 50_000_000
        shared = ["".join(value.itertext()) for value in _xml(archive, "xl/sharedStrings.xml")]
        relationships = {}
        for value in _xml(archive, "xl/_rels/workbook.xml.rels"):
            if value.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join("xl", value.attrib["Target"]))
            assert target.startswith("xl/") and "\\" not in target
            relationships[value.attrib["Id"]] = target
        for sheet in _xml(archive, "xl/workbook.xml").findall("s:sheets/s:sheet", NS):
            root = _xml(archive, relationships[sheet.attrib[RID]])
            cells = {}
            for cell in root.findall("s:sheetData/s:row/s:c", NS):
                value = cell.find("s:v", NS)
                text = "" if value is None else value.text or ""
                if cell.get("t") == "s":
                    text = shared[int(text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(node.text or "" for node in cell.findall("s:is//s:t", NS))
                cells[cell.attrib["r"]] = text
            result[sheet.attrib["name"]] = cells
    return result


def _indices(cells, columns, *, start=1, end=10000):
    result = []
    for reference, value in cells.items():
        matched = re.fullmatch(r"([A-Z]+)([0-9]+)", reference)
        assert matched is not None
        if (
            matched[1] in columns
            and start <= int(matched[2]) <= end
            and re.fullmatch(r"[0-9]{5}", value)
        ):
            result.append(value)
    return result


@pytest.mark.parametrize(
    "sheet,columns,start,end,total,unique",
    [
        ("27_모의 배치", ("H",), 1, 2000, 1120, 1112),
        ("27_엄메", ("H",), 2, 301, 300, 300),
        ("27_E기적", ("F", "L", "R", "X", "AD", "AJ"), 1, 10000, 1200, 1195),
        ("27_단원별", ("H",), 1, 10000, 235, 235),
    ],
)
def test_real_placement_counts_repeats_and_large_shapes(
    workbook,
    sheet,
    columns,
    start,
    end,
    total,
    unique,
) -> None:
    indices = _indices(workbook[sheet], columns, start=start, end=end)
    assert len(indices) == total
    assert len(set(indices)) == unique
    synthetic = {value: position for position, value in enumerate(sorted(set(indices)), 1)}
    body = draft(0)
    body["placements"] = [
        slot(position, target=item_target(synthetic[value]))
        for position, value in enumerate(indices, 1)
    ]
    validate_contract("curated-document-assembly-draft-v3", body)
    parsed = CuratedDocumentAssemblyDraftV3.model_validate(body)
    assert len(parsed.placements) == total
    assert len({value.target.item_id for value in parsed.placements}) == unique


def test_page_based_unresolved_rows_remain_explicit_empty_not_invented_ids(workbook) -> None:
    cells = workbook["27_단원별"]
    unresolved = [
        reference
        for reference, value in cells.items()
        if reference.startswith("H") and value == "-"
    ]
    assert set(unresolved) == {"H17", "H217", "H232", "H241", "H263"}
    body = draft(0)
    body["placements"] = [slot(i, target={"placement_kind": "EMPTY"}) for i in range(1, 6)]
    value = CuratedDocumentAssemblyDraftV3.model_validate(body)
    assert all(row.target.placement_kind == "EMPTY" for row in value.placements)


def test_weekly_side_tests_and_unrecorded_weeks_are_not_false_completed_placements(
    workbook,
) -> None:
    side = _indices(
        workbook["27_E기적"], ("AO", "AP", "AQ", "AR", "AS", "AT", "AU", "AV", "AW", "AX")
    )
    assert len(side) == 80
    tests = _indices(workbook["27_테스트"], tuple("CDEFGHIJKLMN"))
    assert len(tests) == 100  # 12 designed weeks, only 10 have recorded targets.
    assert not _indices(workbook["27_테스트"], ("K", "L"))


def test_old_unused_catalog_is_not_a_permanent_item_type(workbook) -> None:
    old = workbook["26_미사용"]
    new = workbook["27_모의 배치"]
    assert old["G786"] == new["H2"] == "71707"
    assert "71707" in _indices(new, ("H",))


def test_vlookup_first_hit_must_not_replace_all_usage_locations(workbook) -> None:
    values = _indices(workbook["27_모의 배치"], ("H",), end=2000)
    counts = Counter(values)
    assert counts["71795"] == 2
    assert sum(count - 1 for count in counts.values()) == 8


def test_no_print_evidence_is_invented_from_workbook_review_status(workbook) -> None:
    # The existing green/review-complete cells are not user-recorded print facts.
    assert any("조교최종" in value for value in workbook["27_테스트"].values())
    assert not any(
        re.search(r"인쇄|출판|발행|납품", value)
        for cells in workbook.values()
        for value in cells.values()
    )
