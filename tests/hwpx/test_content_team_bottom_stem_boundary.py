"""Canonical question boundaries must not depend on the handoff's phrase vocabulary."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from eom_hwpx_builder.content_team_question_projection import project_content_team_question
from eom_hwpx_builder.content_team_renderer import (
    ContentTeamRenderRuntime,
    prepare_content_team_runtime,
    render_content_team_document,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.xmlsafe import parse_xml
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    ContentTeamMarkdownError,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
)

from tests.hwpx.test_content_team_markdown import (
    DIRECT_CHOICE_ITEM,
    INQUIRY_ITEM,
    LABELED_BLOCK_ITEM,
)

HANDOFF = Path(__file__).resolve().parents[2] / "staging/HwpQuestionEditor_handoff_export.zip"
RECOGNIZED_BOTTOM = "이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?"


@pytest.fixture(scope="module")
def reviewed_runtime(tmp_path_factory: pytest.TempPathFactory) -> ContentTeamRenderRuntime:
    if not HANDOFF.is_file():
        pytest.skip("content-team handoff ZIP is unavailable")
    workspace = tmp_path_factory.mktemp("bottom-stem-handoff")
    (workspace / "input").mkdir()
    shutil.copyfile(HANDOFF, workspace / "input/handoff.zip")
    snapshot = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        members=tuple(
            ContentTeamHandoffMember.model_validate(
                {"purpose": purpose, "sha256": digest, "size": size}
            )
            for purpose, digest, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    return prepare_content_team_runtime(workspace, snapshot)


@pytest.mark.parametrize("source", [LABELED_BLOCK_ITEM, INQUIRY_ITEM], ids=["general", "inquiry"])
@pytest.mark.parametrize(
    "bottom",
    [
        RECOGNIZED_BOTTOM,
        "관측 결과와 일치하는 설명을 모두 고르면?",
        "위 결과를 바탕으로 " + RECOGNIZED_BOTTOM,
        "위 결과를 바탕으로 판단하시오.\n" + RECOGNIZED_BOTTOM,
    ],
    ids=["full-split", "no-split", "partial-line", "partial-multiline"],
)
@pytest.mark.parametrize("presentation", [None, (12, "1.5")], ids=["single", "assembly"])
def test_canonical_bottom_stem_survives_shared_renderer_without_text_rewrite(
    tmp_path: Path,
    reviewed_runtime: ContentTeamRenderRuntime,
    source: str,
    bottom: str,
    presentation: tuple[int, str] | None,
) -> None:
    assert source.count(RECOGNIZED_BOTTOM) == 1
    source = source.replace(". ", ". 표지 ①과 ②를 관측하였다. ", 1)
    draft = parse_content_team_markdown_v2(source.replace(RECOGNIZED_BOTTOM, bottom).encode())
    before = draft.model_dump(mode="json")
    output = tmp_path / "item.hwpx"
    report = render_content_team_document(
        reviewed_runtime.runtime,
        reviewed_runtime.template,
        serialize_content_team_markdown(draft),
        output,
        draft,
        item_number_override=None if presentation is None else presentation[0],
        score_display_override=None if presentation is None else presentation[1],
    )
    assert report["status"] == "PASS"
    assert draft.model_dump(mode="json") == before
    with ZipFile(output) as archive:
        section = parse_xml(archive.read("Contents/section0.xml"), "Contents/section0.xml").root
        text = "".join(section.xpath('//*[local-name()="t"]/text()'))
    assert text.count(bottom.replace("\n", " ")) == 1
    assert text.count("표지 ①과 ②를 관측하였다.") == 1


@pytest.mark.parametrize("source", [LABELED_BLOCK_ITEM, INQUIRY_ITEM], ids=["general", "inquiry"])
def test_typed_projection_preserves_fields_and_does_not_interpret_inline_circled_markers(
    source: str,
) -> None:
    source = source.replace(". ", ". 표지 ①과 ②를 관측하였다. ", 1)
    draft = parse_content_team_markdown_v2(source.encode())
    before = draft.model_dump(mode="json")
    question, markdown = project_content_team_question(
        draft, question_type=SimpleNamespace, item_number=12, score_display="1.5"
    )
    assert "표지 ①과 ②" in question.stem
    assert question.stem.startswith("12. ")
    assert question.bottom_stem == f"{draft.bottom_stem} [1.5점]"
    assert tuple(getattr(question, f"choice{n}") for n in range(1, 6)) == tuple(
        value.text for value in draft.choices
    )
    assert question.answer == draft.answer.number
    assert question.solution == draft.explanations.correct_answer
    assert question.wrong_answer == draft.explanations.wrong_answer
    if draft.inquiry is not None:
        assert question.inquiry_result == draft.inquiry.result
        assert question.inquiry_procedure == draft.inquiry.procedure
    assert markdown.startswith(b"12. ")
    assert draft.model_dump(mode="json") == before


@pytest.mark.parametrize("invalid", ["choices", "duplicate-score", "equation-index"])
def test_typed_projection_requires_canonical_round_trip_before_constructing_handoff(
    invalid: str,
) -> None:
    draft = parse_content_team_markdown_v2(LABELED_BLOCK_ITEM.encode())
    updates_by_kind: dict[str, dict[str, object]] = {
        "choices": {"choices": draft.choices[:-1]},
        "duplicate-score": {"stem": draft.stem + "\n\n" + draft.bottom_stem + " [3점]"},
        "equation-index": {"equation_sources": ("1",)},
    }
    inconsistent = draft.model_copy(update=updates_by_kind[invalid])
    with pytest.raises(HwpxError if invalid == "duplicate-score" else ContentTeamMarkdownError):
        project_content_team_question(
            inconsistent, question_type=SimpleNamespace, item_number=12, score_display="1.5"
        )


def test_direct_choice_internal_markers_and_soft_line_breaks_survive_real_handoff(
    tmp_path: Path, reviewed_runtime: ContentTeamRenderRuntime
) -> None:
    source = DIRECT_CHOICE_ITEM.replace(
        "② 두 번째 설명", "② 두 번째 설명\n내부 표지 ①을 확인한다."
    ).replace(
        "자료에 대한 설명으로 알맞은 것은?",
        "자료를 확인하시오.\n설명 중 알맞은 것은?",
    )
    draft = parse_content_team_markdown_v2(source.encode())
    before = draft.model_dump(mode="json")
    output = tmp_path / "direct.hwpx"
    render_content_team_document(
        reviewed_runtime.runtime,
        reviewed_runtime.template,
        serialize_content_team_markdown(draft),
        output,
        draft,
    )
    with ZipFile(output) as archive:
        root = parse_xml(archive.read("Contents/section0.xml"), "Contents/section0.xml").root
        text = "".join(root.xpath('//*[local-name()="t"]/text()'))
    assert "두 번째 설명 내부 표지 ①을 확인한다." in text
    assert text.count("자료를 확인하시오. 설명 중 알맞은 것은?") == 1
    assert draft.model_dump(mode="json") == before
