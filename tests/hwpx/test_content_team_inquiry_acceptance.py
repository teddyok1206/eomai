"""A Builder success must also pass independent Manager content acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from eom_hwpx_contracts import (
    ContentTeamTable,
    derive_content_team_equation_sources,
    parse_content_team_markdown_v2,
    parse_content_team_text_blocks,
    serialize_content_team_markdown,
)
from eom_hwpx_manager.content_team_output_acceptance import verify_content_team_output
from eom_hwpx_manager.errors import HwpxManagerError

from tests.hwpx.test_content_team_markdown import INQUIRY_ITEM
from tests.hwpx.test_content_team_output_acceptance import (
    HANDOFF,
    _render_editorial_item,
    _rewrite_member,
    _sha256,
)

TABLE = (
    "| 대상 | 값 A | 값 B | 값 C | 값 D |\n|---|---|---|---|---|\n"
    "| X | 11 | 12 | 13 | 14 |\n| Y | 21 | 22 | 23 | 24 |"
)


def _inquiry_source(*, table_count: int = 1) -> str:
    base = parse_content_team_markdown_v2(INQUIRY_ITEM.encode())
    value = base.model_dump(mode="json")
    value["inquiry"]["result"] = "결과의 각 값은 다음 표와 같다.\n\n" + TABLE
    if table_count == 2:
        value["inquiry"]["result"] += "\n\n두 번째 측정 결과이다.\n\n" + TABLE.replace("11", "31")
    value["inquiry"]["result"] += "\n\n두 대상은 같은 조건에서 측정하였다."
    draft = type(base).model_validate(value)
    value["equation_sources"] = derive_content_team_equation_sources(draft)
    return serialize_content_team_markdown(type(base).model_validate(value)).decode()


def test_inquiry_projection_reuses_bounded_table_grammar_and_preserves_order() -> None:
    blocks = parse_content_team_text_blocks("앞 문단\n\n" + TABLE + "\n\n뒤 문단")
    assert blocks[0] == "앞 문단" and blocks[2] == "뒤 문단"
    assert isinstance(blocks[1], ContentTeamTable)
    assert blocks[1].headers == ("대상", "값 A", "값 B", "값 C", "값 D")
    assert blocks[1].rows[1] == ("Y", "21", "22", "23", "24")


@pytest.mark.parametrize(
    "invalid",
    [
        TABLE.replace("|---|---|---|---|---|", "|---|---|"),
        TABLE.replace("| Y | 21 | 22 | 23 | 24 |", "| Y | 21 |"),
    ],
)
def test_inquiry_projection_rejects_invalid_tables(invalid: str) -> None:
    with pytest.raises(ValueError):
        parse_content_team_text_blocks(invalid)


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
@pytest.mark.parametrize("table_count", [1, 2])
def test_inquiry_native_tables_pass_builder_and_independent_manager(
    tmp_path: Path, table_count: int
) -> None:
    output, sha, expected = _render_editorial_item(
        tmp_path, _inquiry_source(table_count=table_count)
    )
    original = expected.draft.model_dump(mode="json")
    receipt = verify_content_team_output(output, expected_sha256=sha, expectations=(expected,))
    assert receipt.items[0].visual_layout == "INQUIRY_BOX"
    # Inquiry tables are not reassigned general-visual ordinals in historical receipts.
    assert receipt.items[0].tables == ()
    assert expected.draft.model_dump(mode="json") == original
    assert (
        verify_content_team_output(output, expected_sha256=sha, expectations=(expected,)) == receipt
    )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
@pytest.mark.parametrize("separator", ["|---|---|---|---|---|", "|:---|---:|:---:|---|---:|"])
def test_inquiry_table_column_alignment_is_projected_and_independently_verified(
    tmp_path: Path, separator: str
) -> None:
    source = _inquiry_source().replace("|---|---|---|---|---|", separator)
    output, sha, expected = _render_editorial_item(tmp_path, source)
    receipt = verify_content_team_output(output, expected_sha256=sha, expectations=(expected,))
    assert receipt.items[0].tables == ()


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
def test_original_inquiry_fixture_with_equations_and_right_aligned_column_is_accepted(
    tmp_path: Path,
) -> None:
    output, sha, expected = _render_editorial_item(tmp_path, INQUIRY_ITEM)
    receipt = verify_content_team_output(output, expected_sha256=sha, expectations=(expected,))
    assert receipt.items[0].equation_count == len(expected.draft.equation_sources)


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
def test_inquiry_table_alignment_drift_is_rejected(tmp_path: Path) -> None:
    source = _inquiry_source().replace("|---|---|---|---|---|", "|:---|---:|:---:|---|---:|")
    output, _sha, expected = _render_editorial_item(tmp_path, source)

    def mutate(data: bytes) -> bytes:
        root = ElementTree.fromstring(data)
        table = next(t for t in root.iter() if t.tag.endswith("}tbl") and t.get("colCnt") == "5")
        row = next(t for t in table if t.tag.endswith("}tr"))
        cells = [t for t in row if t.tag.endswith("}tc")]
        left = next(p for p in cells[0].iter() if p.tag.endswith("}p"))
        right = next(p for p in cells[1].iter() if p.tag.endswith("}p"))
        right.set("paraPrIDRef", left.attrib["paraPrIDRef"])
        serialized = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
        assert isinstance(serialized, bytes)
        return serialized

    candidate = tmp_path / "changed-alignment.hwpx"
    _rewrite_member(output, candidate, "Contents/section0.xml", mutate)
    with pytest.raises(HwpxManagerError, match="inquiry native table differs"):
        verify_content_team_output(
            candidate, expected_sha256=_sha256(candidate.read_bytes()), expectations=(expected,)
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
@pytest.mark.parametrize(
    "mutation", ["cell", "removed", "duplicate", "reordered", "prose", "prose-order"]
)
def test_inquiry_native_table_acceptance_rejects_content_loss_or_drift(
    tmp_path: Path, mutation: str
) -> None:
    output, _sha, expected = _render_editorial_item(tmp_path, _inquiry_source(table_count=2))

    def mutate(data: bytes) -> bytes:
        root = ElementTree.fromstring(data)
        parents = {child: parent for parent in root.iter() for child in parent}
        tables = [
            element
            for element in root.iter()
            if element.tag.endswith("}tbl") and element.get("colCnt") == "5"
        ]
        assert len(tables) == 2
        if mutation == "cell":
            node = next(t for t in tables[0].iter() if t.tag.endswith("}t") and t.text == "11")
            node.text = "999"
        elif mutation == "removed":
            parents[tables[0]].remove(tables[0])
        elif mutation == "duplicate":
            parents[tables[0]].append(ElementTree.fromstring(ElementTree.tostring(tables[0])))
        elif mutation == "reordered":
            first, second = tables
            p1, p2 = parents[first], parents[second]
            i1, i2 = list(p1).index(first), list(p2).index(second)
            p1.remove(first)
            p2.remove(second)
            p1.insert(i1, second)
            p2.insert(i2, first)
        elif mutation == "prose-order":
            first = next(
                t
                for t in root.iter()
                if t.tag.endswith("}t") and "결과의 각 값은" in (t.text or "")
            )
            last = next(
                t
                for t in root.iter()
                if t.tag.endswith("}t") and "두 대상은 같은 조건" in (t.text or "")
            )
            first.text, last.text = last.text, first.text
        else:
            node = next(
                t
                for t in root.iter()
                if t.tag.endswith("}t") and "두 대상은 같은 조건" in (t.text or "")
            )
            node.text = "삭제된 설명"
        serialized = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
        assert isinstance(serialized, bytes)
        return serialized

    candidate = tmp_path / "changed.hwpx"
    _rewrite_member(output, candidate, "Contents/section0.xml", mutate)
    with pytest.raises(HwpxManagerError):
        verify_content_team_output(
            candidate, expected_sha256=_sha256(candidate.read_bytes()), expectations=(expected,)
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="reviewed local handoff archive is unavailable")
def test_inquiry_and_general_items_share_exam_renderer_and_manager_acceptance(
    tmp_path: Path,
) -> None:
    from eom_hwpx_builder.content_team_exam_renderer import render_content_team_exam_workspace
    from eom_hwpx_contracts import ContentTeamExamRenderRequest, parse_content_team_markdown
    from eom_hwpx_manager.content_team_output_acceptance import ContentTeamOutputExpectation

    from tests.hwpx.test_content_team_exam_renderer import _request
    from tests.hwpx.test_content_team_output_acceptance import TABLE_ONLY_ITEM

    raw = _request().model_dump(mode="json")
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "handoff.zip").write_bytes(HANDOFF.read_bytes())
    expectations = []
    sources = (_inquiry_source(table_count=2), TABLE_ONLY_ITEM)
    for position, (item, source) in enumerate(zip(raw["items"], sources, strict=True), start=1):
        draft = parse_content_team_markdown(source.encode())
        markdown = serialize_content_team_markdown(draft)
        content = json.dumps(
            {
                "schema_version": "2.0",
                **draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"}),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        folder = input_root / "items" / f"{position:03d}"
        folder.mkdir(parents=True)
        (folder / "item-content.json").write_bytes(content)
        (folder / "content-team-item.md").write_bytes(markdown)
        item["source_json_sha256"] = _sha256(content)
        item["source_markdown_sha256"] = _sha256(markdown)
        expectations.append(
            ContentTeamOutputExpectation(
                position=position, item_revision_id=item["item_revision_id"], draft=draft, images=()
            )
        )
    request = ContentTeamExamRenderRequest.model_validate(raw)
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    result = render_content_team_exam_workspace(request_path, tmp_path / "result.json")
    assert result.status == "SUCCEEDED" and result.output_sha256 is not None
    receipt = verify_content_team_output(
        tmp_path / "output/content-team-exam.hwpx",
        expected_sha256=result.output_sha256,
        expectations=tuple(expectations),
    )
    assert len(receipt.items) == 2
    assert receipt.items[0].visual_layout == "INQUIRY_BOX"
    assert receipt.items[1].visual_layout == "TABLE_ONLY"
