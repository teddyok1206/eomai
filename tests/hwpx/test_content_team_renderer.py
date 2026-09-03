from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from eom_hwpx_builder.content_team_renderer import render_content_team_workspace
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    ContentTeamItemSource,
    ContentTeamRenderRequest,
    parse_content_team_markdown,
    serialize_content_team_markdown,
)

from tests.hwpx.test_content_team_markdown import GENERAL_ITEM

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "staging/HwpQuestionEditor_handoff_export.zip"


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_reviewed_handoff_renders_v2_item_with_dynamic_program_layout(tmp_path: Path) -> None:
    draft = parse_content_team_markdown(GENERAL_ITEM.encode("utf-8"))
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
    assert result.table_count == 1
    assert result.visual_count == 2
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o640
