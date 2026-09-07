from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.content_team_exam_renderer import (
    _merge_item_packages,
    render_content_team_exam_workspace,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamExamAssemblyPointer,
    ContentTeamExamBuildResult,
    ContentTeamExamItemSource,
    ContentTeamExamRenderRequest,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    parse_content_team_markdown,
    serialize_content_team_markdown,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.hwpx.helpers import synthetic_parts, write_hwpx
from tests.hwpx.test_content_team_markdown import LABELED_BLOCK_ITEM

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "staging/HwpQuestionEditor_handoff_export.zip"


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _request(*, positions: tuple[int, ...] = (1, 2)) -> ContentTeamExamRenderRequest:
    handoff = ContentTeamHandoffSnapshot(
        artifact_id="artifact_" + "a" * 32,
        artifact_revision_id="rev_" + "b" * 32,
        members=tuple(
            ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
            for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
        ),
    )
    return ContentTeamExamRenderRequest(
        build_id="hwpxbuild_" + "c" * 32,
        assembly=ContentTeamExamAssemblyPointer(
            assessment_assembly_id="assembly_" + "d" * 32,
            assessment_assembly_revision_id="assemblyrev_" + "e" * 32,
            manifest_sha256="sha256:" + "f" * 64,
            policy_revision_id="assemblypolicyrev_" + "1" * 32,
            policy_sha256="sha256:" + "2" * 64,
            graph_snapshot_revision_id="graphrev_" + "3" * 32,
            graph_snapshot_sha256="sha256:" + "4" * 64,
        ),
        handoff=handoff,
        items=tuple(
            ContentTeamExamItemSource(
                position=position,
                placement_id=f"placement_{index:032x}",
                item_id=f"item_{index:032x}",
                item_revision_id=f"itemrev_{index:032x}",
                item_manifest_sha256="sha256:" + f"{index:064x}",
                source_artifact_id=f"artifact_{index:032x}",
                source_artifact_revision_id=f"rev_{index:032x}",
                source_json_sha256="sha256:" + f"{index + 10:064x}",
                source_markdown_sha256="sha256:" + f"{index + 20:064x}",
                json_file=f"input/items/{position:03d}/item-content.json",
                markdown_file=f"input/items/{position:03d}/content-team-item.md",
                images=(),
            )
            for index, position in enumerate(positions, start=1)
        ),
    )


def test_exam_contract_schemas_match_packaged_copies_and_use_draft_2020_12() -> None:
    for name in (
        "hwpx-content-team-exam-render-request-v1.schema.json",
        "hwpx-content-team-exam-build-result-v1.schema.json",
    ):
        canonical = ROOT / "schemas/hwpx" / name
        packaged = ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
        canonical_value = json.loads(canonical.read_text(encoding="utf-8"))
        packaged_value = json.loads(packaged.read_text(encoding="utf-8"))
        assert canonical_value == packaged_value
        assert canonical_value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(canonical_value)


def test_exam_request_rejects_noncontiguous_positions_and_duplicate_revisions() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        _request(positions=(1, 3))
    value = _request().model_dump(mode="json")
    value["items"][1]["item_revision_id"] = value["items"][0]["item_revision_id"]
    with pytest.raises(ValidationError, match="unique"):
        ContentTeamExamRenderRequest.model_validate(value)


def test_exam_result_requires_one_section_per_item_and_no_fixed_component_counts() -> None:
    base = {
        "build_id": "hwpxbuild_" + "a" * 32,
        "assessment_assembly_revision_id": "assemblyrev_" + "b" * 32,
        "assembly_manifest_sha256": "sha256:" + "c" * 64,
        "item_set_sha256": "sha256:" + "d" * 64,
        "status": "SUCCEEDED",
        "output_file": "output/content-team-exam.hwpx",
        "output_sha256": "sha256:" + "e" * 64,
        "package_manifest_file": "output/package-manifest.json",
        "renderer_report_file": "output/content-team-exam-validation.json",
        "item_count": 2,
        "section_count": 2,
        "equation_count": 0,
        "table_count": 3,
        "visual_count": 1,
        "warnings": [],
        "errors": [],
        "started_at": datetime(2026, 9, 7, tzinfo=UTC),
        "completed_at": datetime(2026, 9, 7, 0, 0, 1, tzinfo=UTC),
    }
    result = ContentTeamExamBuildResult.model_validate(base)
    assert (result.equation_count, result.table_count, result.visual_count) == (0, 3, 1)
    with pytest.raises(ValidationError, match="one section per item"):
        ContentTeamExamBuildResult.model_validate(base | {"section_count": 1})


def test_exam_merger_is_deterministic_and_remaps_each_item_binary_pointer(tmp_path: Path) -> None:
    first = write_hwpx(tmp_path / "first.hwpx", synthetic_parts())
    second = write_hwpx(tmp_path / "second.hwpx", synthetic_parts())
    output_a = tmp_path / "a/output/content-team-exam.hwpx"
    output_b = tmp_path / "b/output/content-team-exam.hwpx"

    report = _merge_item_packages((first, second), output_a)
    _merge_item_packages((first, second), output_b)

    assert output_a.read_bytes() == output_b.read_bytes()
    assert stat.S_IMODE(output_a.stat().st_mode) == 0o600
    assert report["section_count"] == 2
    analysis = analyze_package(output_a)
    assert analysis.sections == ("Contents/section0.xml", "Contents/section1.xml")
    assert analysis.bindata == (
        "BinData/item-001-000.png",
        "BinData/item-002-000.png",
    )
    assert analysis.active_content == ()
    assert analysis.external_links == ()
    with zipfile.ZipFile(output_a) as archive:
        first_section = archive.read("Contents/section0.xml")
        second_section = archive.read("Contents/section1.xml")
    assert b"eomExam001Binary000" in first_section
    assert b"eomExam002Binary000" in second_section


def test_exam_merger_rejects_unpinned_shared_template_drift(tmp_path: Path) -> None:
    first = write_hwpx(tmp_path / "first.hwpx", synthetic_parts())
    changed = [
        (name, b"<settings/>" if name == "settings.xml" else data, compression)
        for name, data, compression in synthetic_parts()
    ]
    second = write_hwpx(tmp_path / "second.hwpx", changed)

    with pytest.raises(HwpxError, match="different reviewed template runtime"):
        _merge_item_packages((first, second), tmp_path / "output/exam.hwpx")


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_reviewed_handoff_builds_two_item_exam_and_applies_assembly_numbering(
    tmp_path: Path,
) -> None:
    raw = _request().model_dump(mode="json")
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "handoff.zip").write_bytes(HANDOFF.read_bytes())
    expected_equations = 0
    for position, item in enumerate(raw["items"], start=1):
        draft = parse_content_team_markdown(LABELED_BLOCK_ITEM.encode("utf-8"))
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
        item_root = input_root / "items" / f"{position:03d}"
        item_root.mkdir(parents=True)
        (item_root / "item-content.json").write_bytes(item_bytes)
        (item_root / "content-team-item.md").write_bytes(markdown)
        item["source_json_sha256"] = _sha256(item_bytes)
        item["source_markdown_sha256"] = _sha256(markdown)
        expected_equations += len(draft.equation_sources)

    request = ContentTeamExamRenderRequest.model_validate(raw)
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")

    result = render_content_team_exam_workspace(request_path, result_path)

    output = tmp_path / "output/content-team-exam.hwpx"
    analysis = analyze_package(output)
    assert result.status == "SUCCEEDED"
    assert result.item_count == result.section_count == 2
    assert result.equation_count == expected_equations
    assert result.table_count == 0
    assert result.visual_count == 0
    assert analysis.sections == ("Contents/section0.xml", "Contents/section1.xml")
    with zipfile.ZipFile(output) as archive:
        first_section = archive.read("Contents/section0.xml").decode("utf-8")
        second_section = archive.read("Contents/section1.xml").decode("utf-8")
    assert ">1. 다음" in first_section
    assert ">2. 다음" in second_section
