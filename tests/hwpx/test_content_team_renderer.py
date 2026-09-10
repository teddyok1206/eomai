from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.content_team_renderer import (
    _project_general_stem_for_handoff,
    render_content_team_workspace,
)
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    ContentTeamItemSource,
    ContentTeamItemSourceV2,
    ContentTeamRenderRequest,
    ContentTeamRenderRequestV2,
    ContentTeamRenderRequestV3,
    derive_content_team_equation_sources,
    parse_content_team_markdown,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
)

from tests.hwpx.helpers import png_bytes
from tests.hwpx.test_content_team_markdown import GENERAL_ITEM, LABELED_BLOCK_ITEM

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "staging/HwpQuestionEditor_handoff_export.zip"


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def test_general_stem_projection_is_linear_deterministic_and_boundary_local() -> None:
    assert _project_general_stem_for_handoff("single line ") == "single line "
    assert _project_general_stem_for_handoff("first\r\n\r\n second\nthird") == (
        "first second third"
    )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
@pytest.mark.parametrize(
    ("source", "expected_table_count", "expected_visual_count", "expected_labeled_count"),
    [
        pytest.param(GENERAL_ITEM, 1, 2, 0, id="baseline"),
        pytest.param(
            GENERAL_ITEM.replace("$3$", "$y=20+15t-5t^{2}$", 1).replace("$5$", "$v_{y}=-5$", 1),
            1,
            2,
            0,
            id="implicit-decorated-product-and-signed-rhs",
        ),
        pytest.param(
            LABELED_BLOCK_ITEM.replace("대상 X에", "대상 $X^{2+}$에", 1),
            0,
            0,
            2,
            id="mixed-equation-prefix-before-labeled-blocks",
        ),
        pytest.param(
            LABELED_BLOCK_ITEM.replace(
                "ㄱ. 자료에 특성 P가 명시되어 있으므로 옳다.",
                "전체 풀이에서 자료의 판단 근거를 설명하였다.\n\nㄱ. [풀이] 참조",
                1,
            ),
            0,
            0,
            2,
            id="intentional-solution-reference-is-not-template-residue",
        ),
        pytest.param(
            LABELED_BLOCK_ITEM.replace(
                "관측 과정에서 외부 조건은 일정하였다.",
                "관측 과정에서 외부 조건은 일정하였다.\n\n추가 조건도 일정하였다.",
                1,
            ),
            0,
            0,
            2,
            id="labeled-block-blank-paragraph-projection",
        ),
    ],
)
def test_reviewed_handoff_renders_v2_item_with_dynamic_program_layout(
    tmp_path: Path,
    source: str,
    expected_table_count: int,
    expected_visual_count: int,
    expected_labeled_count: int,
) -> None:
    draft = parse_content_team_markdown(source.encode("utf-8"))
    markdown = serialize_content_team_markdown(draft)
    item_value = {
        "schema_version": "2.0",
        **draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"}),
    }
    item_bytes = json.dumps(
        item_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "item-content.json").write_bytes(item_bytes)
    (input_root / "content-team-item.md").write_bytes(markdown)
    (input_root / "handoff.zip").write_bytes(HANDOFF.read_bytes())
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    request = ContentTeamRenderRequest(
        build_id="hwpxbuild_" + "c" * 32,
        item_revision_id="itemrev_" + "d" * 32,
        source=ContentTeamItemSource(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=handoff,
    )
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    result = render_content_team_workspace(request_path, result_path)

    output = tmp_path / "output/content-team-item.hwpx"
    assert result.status == "SUCCEEDED"
    assert result.output_sha256 == _sha256(output.read_bytes())
    assert result.equation_count == len(draft.equation_sources)
    assert result.table_count == expected_table_count
    assert result.visual_count == expected_visual_count
    assert result.labeled_block_count == expected_labeled_count
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o640


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_reviewed_handoff_projects_general_multiline_stem_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = LABELED_BLOCK_ITEM.replace(
        "\n\n<자료>\n대상 X에서 특성 P가 관측되었다.\n\n"
        "[조건]\n관측 과정에서 외부 조건은 일정하였다.",
        "",
        1,
    ).replace(
        "다음은 관측 대상 X에 대한 자료이다.",
        "다음은 관측 대상 X에 대한 자료이다.\n"
        "모든 관측은 같은 기준으로 기록하였다.\n"
        "각 설명을 기준과 비교한다.",
        1,
    )
    draft = parse_content_team_markdown_v2(source.encode("utf-8"))
    assert draft.stem.count("\n") == 2
    assert draft.labeled_blocks == ()
    assert draft.visuals == ()
    markdown = serialize_content_team_markdown(draft)
    item_value = {
        "schema_version": "3.0",
        **draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"}),
    }
    item_bytes = json.dumps(
        item_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "item-content.json").write_bytes(item_bytes)
    (input_root / "content-team-item.md").write_bytes(markdown)
    (input_root / "handoff.zip").write_bytes(HANDOFF.read_bytes())
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    request = ContentTeamRenderRequestV3(
        build_id="hwpxbuild_" + "c" * 32,
        item_revision_id="itemrev_" + "d" * 32,
        source=ContentTeamItemSourceV2(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=handoff,
        images=(),
    )
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    result = render_content_team_workspace(request_path, result_path)

    output = tmp_path / "output/content-team-item.hwpx"
    report = json.loads((tmp_path / "output/content-team-validation.json").read_text())
    assert result.status == "SUCCEEDED"
    assert result.source_json_sha256 == _sha256(item_bytes)
    assert result.source_markdown_sha256 == _sha256(markdown)
    assert result.output_sha256 == _sha256(output.read_bytes())
    assert report["handoff_projection_applied"] is True
    assert report["handoff_projection_sha256"] != _sha256(markdown)
    assert json.loads((input_root / "item-content.json").read_text())["stem"] == draft.stem


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
@pytest.mark.parametrize("image_count", [1, 2])
def test_v2_renderer_replaces_image_slots_with_exact_pinned_pngs(
    tmp_path: Path,
    image_count: int,
) -> None:
    draft = parse_content_team_markdown(GENERAL_ITEM.encode("utf-8"))
    if image_count == 2:
        draft_value = draft.model_dump(mode="json")
        draft_value["visual_layout"] = "IMAGE_IMAGE"
        draft_value["visuals"] = [
            {"kind": "IMAGE", "label": "(가)"},
            {"kind": "IMAGE", "label": "(나)"},
        ]
        draft_value["equation_sources"] = []
        preliminary = type(draft).model_validate(draft_value)
        draft_value["equation_sources"] = list(derive_content_team_equation_sources(preliminary))
        draft = type(draft).model_validate(draft_value)
    markdown = serialize_content_team_markdown(draft)
    item_value = {
        "schema_version": "2.0",
        **draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"}),
    }
    item_bytes = json.dumps(
        item_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    images = tuple(png_bytes(output=ordinal == 0) for ordinal in range(image_count))
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "item-content.json").write_bytes(item_bytes)
    (input_root / "content-team-item.md").write_bytes(markdown)
    (input_root / "handoff.zip").write_bytes(HANDOFF.read_bytes())
    for ordinal, image in enumerate(images):
        (input_root / f"visual-{ordinal}.png").write_bytes(image)
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    request = ContentTeamRenderRequestV2(
        build_id="hwpxbuild_" + "c" * 32,
        item_revision_id="itemrev_" + "d" * 32,
        source=ContentTeamItemSource(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=handoff,
        images=tuple(
            ContentTeamImageSource(
                visual_ordinal=ordinal,
                label=("" if image_count == 1 else ("(가)" if ordinal == 0 else "(나)")),
                artifact_id="artifact_" + str(ordinal + 1) * 32,
                artifact_revision_id="rev_" + str(ordinal + 3) * 32,
                sha256=_sha256(image),
                alt_text=f"검증된 그림 {ordinal + 1}",
                file_name=f"input/visual-{ordinal}.png",
            )
            for ordinal, image in enumerate(images)
        ),
    )
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    result = render_content_team_workspace(request_path, result_path)

    output = tmp_path / "output/content-team-item.hwpx"
    analysis = analyze_package(output)
    assert result.status == "SUCCEEDED"
    assert result.embedded_image_count == image_count
    assert analysis.bindata == tuple(
        f"BinData/content-team-visual-{ordinal}.png" for ordinal in range(image_count)
    )
    with zipfile.ZipFile(output) as archive:
        for ordinal, image in enumerate(images):
            assert archive.read(f"BinData/content-team-visual-{ordinal}.png") == image
        section = archive.read("Contents/section0.xml")
    for ordinal in range(image_count):
        assert f"eomContentTeamVisual{ordinal}".encode() in section
    assert "그림 삽입" not in section.decode("utf-8")
