"""Canonical numbering and optional statements share one publication projection."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.content_team_layout import (
    HP,
    QUESTION_TABLE_ID,
    STATEMENT_TABLE_ID,
    assert_content_team_numbering,
    project_content_team_template_layout,
)
from eom_hwpx_builder.curated_editorial_layout import reflow_curated_editorial_document
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_contracts import parse_content_team_markdown
from lxml import etree

from tests.hwpx.test_content_team_markdown import DIRECT_CHOICE_ITEM, INQUIRY_ITEM
from tests.hwpx.test_content_team_renderer import (
    HANDOFF,
)
from tests.hwpx.test_content_team_renderer import (
    test_reviewed_handoff_renders_v2_item_with_dynamic_program_layout as _render_fixture,
)


def _layout(number: int = 8) -> tuple[etree._Element, etree._Element, etree._Element]:
    root = etree.Element(HP + "sec")
    table = etree.SubElement(root, HP + "tbl", id=QUESTION_TABLE_ID)
    row = etree.SubElement(table, HP + "tr")
    cell = etree.SubElement(row, HP + "tc")
    body = etree.SubElement(cell, HP + "subList")
    stem = etree.SubElement(body, HP + "p", paraPrIDRef="47", styleIDRef="25")
    prefix = etree.SubElement(stem, HP + "run", charPrIDRef="30")
    etree.SubElement(prefix, HP + "t").text = "1. "
    content = etree.SubElement(stem, HP + "run", charPrIDRef="43")
    etree.SubElement(content, HP + "t").text = f"{number}. 질문 본문을 그대로 보존한다."
    etree.SubElement(stem, HP + "linesegarray")
    host = etree.SubElement(body, HP + "p")
    run = etree.SubElement(host, HP + "run")
    view = etree.SubElement(run, HP + "tbl", id=STATEMENT_TABLE_ID, rowCnt="3", colCnt="3")
    label = etree.SubElement(view, HP + "t")
    label.text = "<보 기>ㄱ. ㄴ. ㄷ. "
    etree.SubElement(run, HP + "t")
    etree.SubElement(host, HP + "linesegarray")
    return root, stem, view


def test_direct_choice_removes_only_template_number_and_empty_statement_host() -> None:
    root, stem, view = _layout()
    content = etree.tostring(stem.findall(HP + "run")[1])
    host = view.getparent().getparent()
    project_content_team_template_layout(root, item_number=8, has_statements=False)
    assert etree.tostring(stem.findall(HP + "run")[0]) == content
    assert host.getparent() is None
    assert stem.findall(HP + "linesegarray") == []
    assert_content_team_numbering(root, item_number=8)


def test_statement_combination_preserves_authored_statement_layout() -> None:
    root, _stem, view = _layout(27)
    view.find(HP + "t").text = "<보 기>ㄱ. 저항이 증가한다. ㄴ. 전류가 감소한다. ㄷ. 조건은 같다."
    before = etree.tostring(view)
    project_content_team_template_layout(root, item_number=27, has_statements=True)
    assert etree.tostring(view) == before
    assert_content_team_numbering(root, item_number=27)


def test_later_native_table_host_with_the_same_style_is_not_a_second_stem() -> None:
    root, stem, _view = _layout()
    later = copy.deepcopy(stem)
    later.findall(HP + "run")[0].find(HP + "t").text = "본문 표"
    stem.addnext(later)
    before = etree.tostring(later)
    project_content_team_template_layout(root, item_number=8, has_statements=False)
    assert etree.tostring(later) == before


@pytest.mark.parametrize("unsafe", ["text", "picture", "sibling", "duplicate", "wrong-number"])
def test_unsafe_layout_fails_before_any_mutation(unsafe: str) -> None:
    root, stem, view = _layout()
    if unsafe == "text":
        view.find(HP + "t").text += "실제 작성된 내용"
    elif unsafe == "picture":
        etree.SubElement(view, HP + "pic")
    elif unsafe == "sibling":
        etree.SubElement(view.getparent(), HP + "equation")
    elif unsafe == "duplicate":
        root.append(copy.deepcopy(view))
    else:
        stem.findall(HP + "run")[1].find(HP + "t").text = "9. 다른 문항"
    before = etree.tostring(root)
    with pytest.raises(HwpxError):
        project_content_team_template_layout(root, item_number=8, has_statements=False)
    assert etree.tostring(root) == before


INQUIRY_DIRECT_CHOICE = (
    INQUIRY_ITEM.split("이에 대한 설명으로", 1)[0]
    + DIRECT_CHOICE_ITEM.split("자료에 대한 설명으로", 1)[1]
    .replace(" 알맞은 것은?", "위 탐구 결과에 맞는 것은?", 1)
    .lstrip()
)


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
@pytest.mark.parametrize("source", [DIRECT_CHOICE_ITEM, INQUIRY_ITEM, INQUIRY_DIRECT_CHOICE])
def test_real_single_and_curated_keep_exact_number_and_optional_statements(
    tmp_path: Path, source: str
) -> None:
    draft = parse_content_team_markdown(source.encode())
    _render_fixture(tmp_path, source, 0, 0, 0)
    output = tmp_path / "output/content-team-item.hwpx"
    with zipfile.ZipFile(output) as archive:
        root = etree.fromstring(archive.read("Contents/section0.xml"))
    assert_content_team_numbering(root, item_number=draft.item_number)
    view = [node for node in root.iter(HP + "tbl") if node.get("id") == STATEMENT_TABLE_ID]
    assert len(view) == bool(draft.statements)
    assert root.xpath("count(.//hp:t[contains(text(), '1. 1.')])", namespaces={"hp": HP[1:-1]}) == 0
    visible = "".join("".join(node.itertext()) for node in root.iter(HP + "t"))
    assert visible.count(draft.bottom_stem) == 1
    # Curated geometry adapts the same normalized document; it no longer expects
    # or removes an extra number that single-item/exam paths would retain.
    reflow_curated_editorial_document(output, item_number=draft.item_number)
    with zipfile.ZipFile(output) as archive:
        reflowed = etree.fromstring(archive.read("Contents/section0.xml"))
    assert_content_team_numbering(reflowed, item_number=draft.item_number)
    assert "".join("".join(node.itertext()) for node in reflowed.iter(HP + "t")) == visible
