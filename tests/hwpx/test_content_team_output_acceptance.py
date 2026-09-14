from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest
from eom_hwpx_builder.content_team_renderer import render_content_team_workspace
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    ContentTeamItemSourceV2,
    ContentTeamOutputAcceptanceV1,
    ContentTeamRenderRequestV3,
    derive_content_team_equation_sources,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
)
from eom_hwpx_contracts.validation import validate_contract as validate_hwpx_contract
from eom_hwpx_manager.content_team_output_acceptance import (
    ContentTeamOutputExpectation,
    verify_content_team_output,
)
from eom_hwpx_manager.errors import HwpxManagerError
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from tests.hwpx.helpers import png_bytes
from tests.hwpx.test_content_team_markdown import GENERAL_ITEM, LABELED_BLOCK_ITEM

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "staging/HwpQuestionEditor_handoff_export.zip"
TABLE_ONLY_ITEM = GENERAL_ITEM.replace("그림과 표는", "표는", 1).replace("\n\n그림\n\n", "\n\n", 1)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _table_only_acceptance_value() -> dict[str, object]:
    table = {
        "visual_ordinal": 0,
        "label": "",
        "column_count": 2,
        "row_count": 2,
        "table_sha256": "sha256:" + "1" * 64,
    }
    item = {
        "position": 1,
        "item_revision_id": "itemrev_" + "2" * 32,
        "visual_layout": "TABLE_ONLY",
        "tables": [table],
        "images": [],
        "equation_count": 0,
        "labeled_block_count": 0,
        "semantic_text_sha256": "sha256:" + "4" * 64,
    }
    item["structure_sha256"] = content_sha256(item)
    receipt = {
        "schema_version": "content-team-output-acceptance/1.0",
        "output_sha256": "sha256:" + "3" * 64,
        "package_entry_count": 7,
        "uncompressed_bytes": 100,
        "section_names": ["Contents/section0.xml"],
        "items": [item],
    }
    receipt["acceptance_sha256"] = content_sha256(receipt)
    return receipt


def _render_table_only(
    tmp_path: Path,
    source: str = TABLE_ONLY_ITEM,
) -> tuple[Path, str, ContentTeamOutputExpectation]:
    draft = parse_content_team_markdown_v2(source.encode("utf-8"))
    assert draft.visual_layout == "TABLE_ONLY"
    assert tuple(visual.kind for visual in draft.visuals) == ("TABLE",)
    assert draft.visuals[0].label == ""
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
    request = ContentTeamRenderRequestV3(
        build_id="hwpxbuild_" + "c" * 32,
        item_revision_id="itemrev_" + "d" * 32,
        source=ContentTeamItemSourceV2(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
            members=tuple(
                ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
                for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        images=(),
    )
    request_path = tmp_path / "request.json"
    result_path = tmp_path / "result.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    result = render_content_team_workspace(request_path, result_path)
    assert result.status == "SUCCEEDED"
    assert result.output_sha256 is not None
    with zipfile.ZipFile(tmp_path / "output/content-team-item.hwpx") as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
    for marker in ("①", "②", "③", "④", "⑤"):
        assert section.count(marker) >= 1
    return (
        tmp_path / "output/content-team-item.hwpx",
        result.output_sha256,
        ContentTeamOutputExpectation(
            position=1,
            item_revision_id=request.item_revision_id,
            draft=draft,
            images=(),
        ),
    )


def _render_paired_images(tmp_path: Path) -> tuple[Path, str, ContentTeamOutputExpectation]:
    base = parse_content_team_markdown_v2(LABELED_BLOCK_ITEM.encode("utf-8"))
    draft_value = base.model_dump(mode="json")
    draft_value["visual_layout"] = "IMAGE_IMAGE"
    draft_value["visuals"] = [
        {"kind": "IMAGE", "label": "(가)"},
        {"kind": "IMAGE", "label": "(나)"},
    ]
    draft = type(base).model_validate(draft_value)
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
    image_bytes = (png_bytes(output=True), png_bytes(output=False))
    for ordinal, payload in enumerate(image_bytes):
        (input_root / f"visual-{ordinal}.png").write_bytes(payload)
    images = tuple(
        ContentTeamImageSource(
            visual_ordinal=ordinal,
            label="(가)" if ordinal == 0 else "(나)",
            artifact_id="artifact_" + str(ordinal + 1) * 32,
            artifact_revision_id="rev_" + str(ordinal + 3) * 32,
            sha256=_sha256(payload),
            alt_text=f"검증 그림 {ordinal + 1}",
            file_name=f"input/visual-{ordinal}.png",
        )
        for ordinal, payload in enumerate(image_bytes)
    )
    request = ContentTeamRenderRequestV3(
        build_id="hwpxbuild_" + "4" * 32,
        item_revision_id="itemrev_" + "5" * 32,
        source=ContentTeamItemSourceV2(
            artifact_id="artifact_" + "6" * 32,
            artifact_revision_id="rev_" + "7" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "8" * 32,
            artifact_revision_id="rev_" + "9" * 32,
            members=tuple(
                ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
                for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        images=images,
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    result = render_content_team_workspace(request_path, tmp_path / "result.json")
    assert result.status == "SUCCEEDED"
    assert result.output_sha256 is not None
    return (
        tmp_path / "output/content-team-item.hwpx",
        result.output_sha256,
        ContentTeamOutputExpectation(
            position=1,
            item_revision_id=request.item_revision_id,
            draft=draft,
            images=images,
        ),
    )


def _render_paired_tables(tmp_path: Path) -> tuple[Path, str, ContentTeamOutputExpectation]:
    base = parse_content_team_markdown_v2(TABLE_ONLY_ITEM.encode("utf-8"))
    first = base.visuals[0].model_dump(mode="json")
    second = deepcopy(first)
    first["label"] = "(가)"
    second["label"] = "(나)"
    second["rows"][0][0] = "C"
    draft_value = base.model_dump(mode="json")
    draft_value["visual_layout"] = "TABLE_TABLE"
    draft_value["visuals"] = [first, second]
    draft = type(base).model_validate(draft_value)
    draft_value["equation_sources"] = derive_content_team_equation_sources(draft)
    draft = type(base).model_validate(draft_value)
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
    request = ContentTeamRenderRequestV3(
        build_id="hwpxbuild_" + "a" * 32,
        item_revision_id="itemrev_" + "b" * 32,
        source=ContentTeamItemSourceV2(
            artifact_id="artifact_" + "c" * 32,
            artifact_revision_id="rev_" + "d" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            members=tuple(
                ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
                for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        images=(),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    result = render_content_team_workspace(request_path, tmp_path / "result.json")
    assert result.status == "SUCCEEDED"
    assert result.output_sha256 is not None
    return (
        tmp_path / "output/content-team-item.hwpx",
        result.output_sha256,
        ContentTeamOutputExpectation(
            position=1,
            item_revision_id=request.item_revision_id,
            draft=draft,
            images=(),
        ),
    )


def _render_table_image(tmp_path: Path) -> tuple[Path, str, ContentTeamOutputExpectation]:
    base = parse_content_team_markdown_v2(TABLE_ONLY_ITEM.encode("utf-8"))
    draft_value = base.model_dump(mode="json")
    draft_value["visual_layout"] = "TABLE_IMAGE"
    draft_value["visuals"] = [
        base.visuals[0].model_dump(mode="json"),
        {"kind": "IMAGE", "label": ""},
    ]
    draft = type(base).model_validate(draft_value)
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
    image_bytes = png_bytes(output=True)
    (input_root / "visual-1.png").write_bytes(image_bytes)
    image = ContentTeamImageSource(
        visual_ordinal=1,
        label="",
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        sha256=_sha256(image_bytes),
        alt_text="표 오른쪽의 검증 그림",
        file_name="input/visual-1.png",
    )
    request = ContentTeamRenderRequestV3(
        build_id="hwpxbuild_" + "3" * 32,
        item_revision_id="itemrev_" + "4" * 32,
        source=ContentTeamItemSourceV2(
            artifact_id="artifact_" + "5" * 32,
            artifact_revision_id="rev_" + "6" * 32,
            json_sha256=_sha256(item_bytes),
            markdown_sha256=_sha256(markdown),
        ),
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "7" * 32,
            artifact_revision_id="rev_" + "8" * 32,
            members=tuple(
                ContentTeamHandoffMember(purpose=purpose, sha256=sha256, size=size)
                for purpose, sha256, size in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        images=(image,),
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    result = render_content_team_workspace(request_path, tmp_path / "result.json")
    assert result.status == "SUCCEEDED"
    assert result.output_sha256 is not None
    return (
        tmp_path / "output/content-team-item.hwpx",
        result.output_sha256,
        ContentTeamOutputExpectation(
            position=1,
            item_revision_id=request.item_revision_id,
            draft=draft,
            images=(image,),
        ),
    )


def _rewrite_member(
    source: Path,
    target: Path,
    member_name: str,
    transform: Callable[[bytes], bytes],
) -> None:
    with (
        zipfile.ZipFile(source) as input_archive,
        zipfile.ZipFile(target, "x", allowZip64=False) as output_archive,
    ):
        for info in input_archive.infolist():
            payload = input_archive.read(info)
            if info.filename == member_name:
                payload = transform(payload)
            replacement = zipfile.ZipInfo(info.filename, info.date_time)
            replacement.compress_type = info.compress_type
            replacement.external_attr = info.external_attr
            replacement.create_system = info.create_system
            output_archive.writestr(replacement, payload)


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_independently_accepts_a_native_table_only_item(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_table_only(tmp_path)

    receipt = verify_content_team_output(
        output,
        expected_sha256=output_sha256,
        expectations=(expectation,),
    )

    validate_hwpx_contract(
        "content-team-output-acceptance-v1",
        receipt.model_dump(mode="json"),
    )
    assert receipt.output_sha256 == output_sha256
    assert len(receipt.items) == 1
    assert receipt.items[0].visual_layout == "TABLE_ONLY"
    assert len(receipt.items[0].tables) == 1
    assert receipt.items[0].tables[0].label == ""
    assert receipt.items[0].images == ()
    with zipfile.ZipFile(output) as archive:
        section = archive.read("Contents/section0.xml")
    assert b"content-team-visual" not in section
    assert "그림 삽입" not in section.decode("utf-8")


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_rejects_a_changed_native_table_cell(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_table_only(tmp_path)
    changed = tmp_path / "changed-cell.hwpx"
    expected_cell = "구간".encode()

    def replace_cell(payload: bytes) -> bytes:
        assert payload.count(expected_cell) == 1
        return payload.replace(expected_cell, "변조".encode(), 1)

    _rewrite_member(output, changed, "Contents/section0.xml", replace_cell)

    with pytest.raises(HwpxManagerError, match="native table differs"):
        verify_content_team_output(
            changed,
            expected_sha256=_sha256(changed.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_accepts_a_table_text_split_across_formatting_runs(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_table_only(
        tmp_path,
        TABLE_ONLY_ITEM.replace("| 구간 |", "| 운동 구간 |", 1),
    )
    changed = tmp_path / "split-cell-run.hwpx"

    def split_text_run(payload: bytes) -> bytes:
        marker = "운동 구간".encode()
        replacement = "운동</hp:t><hp:t>구간".encode()
        assert payload.count(marker) == 1
        return payload.replace(marker, replacement, 1)

    _rewrite_member(output, changed, "Contents/section0.xml", split_text_run)

    receipt = verify_content_team_output(
        changed,
        expected_sha256=_sha256(changed.read_bytes()),
        expectations=(expectation,),
    )

    assert receipt.items[0].tables[0].column_count == 3


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_accepts_contract_projected_hancom_equation_scripts(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_table_only(
        tmp_path,
        TABLE_ONLY_ITEM.replace("$3$", "$x^{2}$"),
    )

    receipt = verify_content_team_output(
        output,
        expected_sha256=output_sha256,
        expectations=(expectation,),
    )

    assert receipt.items[0].equation_count == len(expectation.draft.equation_sources)
    with zipfile.ZipFile(output) as archive:
        assert b"x ^{2}" in archive.read("Contents/section0.xml")


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_rejects_a_changed_projected_equation_script(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_table_only(
        tmp_path,
        TABLE_ONLY_ITEM.replace("$5>3$", "$x^{2}$", 1),
    )
    changed = tmp_path / "changed-equation.hwpx"

    def change_equation(payload: bytes) -> bytes:
        marker = b"x ^{2}"
        assert payload.count(marker) == 1
        return payload.replace(marker, b"x ^{3}", 1)

    _rewrite_member(output, changed, "Contents/section0.xml", change_equation)

    with pytest.raises(HwpxManagerError, match="equations differ"):
        verify_content_team_output(
            changed,
            expected_sha256=_sha256(changed.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_rejects_an_external_reference_before_acceptance(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_table_only(tmp_path)
    changed = tmp_path / "external-reference.hwpx"

    def add_external_reference(payload: bytes) -> bytes:
        marker = b"<hs:sec "
        assert payload.count(marker) == 1
        return payload.replace(
            marker,
            b'<hs:sec href="https://example.invalid/payload" ',
            1,
        )

    _rewrite_member(output, changed, "Contents/section0.xml", add_external_reference)

    with pytest.raises(HwpxManagerError, match="external reference"):
        verify_content_team_output(
            changed,
            expected_sha256=_sha256(changed.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_accepts_two_exact_images_with_editable_panel_labels(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_paired_images(tmp_path)

    receipt = verify_content_team_output(
        output,
        expected_sha256=output_sha256,
        expectations=(expectation,),
    )

    assert receipt.items[0].visual_layout == "IMAGE_IMAGE"
    assert tuple(image.label for image in receipt.items[0].images) == ("(가)", "(나)")
    assert tuple(image.sha256 for image in receipt.items[0].images) == tuple(
        image.sha256 for image in expectation.images
    )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_accepts_an_image_in_its_authored_column_after_a_table(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_table_image(tmp_path)

    receipt = verify_content_team_output(
        output,
        expected_sha256=output_sha256,
        expectations=(expectation,),
    )

    accepted = receipt.items[0]
    assert accepted.visual_layout == "TABLE_IMAGE"
    assert tuple(table.visual_ordinal for table in accepted.tables) == (0,)
    assert tuple(image.visual_ordinal for image in accepted.images) == (1,)


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_rejects_changed_generated_image_bytes(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_paired_images(tmp_path)
    changed = tmp_path / "changed-image.hwpx"
    _rewrite_member(
        output,
        changed,
        "BinData/content-team-visual-0.png",
        lambda _payload: png_bytes(output=False),
    )

    with pytest.raises(HwpxManagerError, match="image bytes differ"):
        verify_content_team_output(
            changed,
            expected_sha256=_sha256(changed.read_bytes()),
            expectations=(expectation,),
        )


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_accepts_two_native_tables_with_editable_panel_labels(tmp_path: Path) -> None:
    output, output_sha256, expectation = _render_paired_tables(tmp_path)

    receipt = verify_content_team_output(
        output,
        expected_sha256=output_sha256,
        expectations=(expectation,),
    )

    assert receipt.items[0].visual_layout == "TABLE_TABLE"
    assert tuple(table.label for table in receipt.items[0].tables) == ("(가)", "(나)")
    with zipfile.ZipFile(output) as archive:
        section = archive.read("Contents/section0.xml").decode("utf-8")
    assert section.count(">(가)<") == 1
    assert section.count(">(나)<") == 1


@pytest.mark.skipif(not HANDOFF.is_file(), reason="content-team handoff ZIP is unavailable")
def test_manager_rejects_a_changed_native_table_panel_label(tmp_path: Path) -> None:
    output, _output_sha256, expectation = _render_paired_tables(tmp_path)
    changed = tmp_path / "changed-table-label.hwpx"

    def replace_label(payload: bytes) -> bytes:
        marker = ">(가)<".encode()
        assert payload.count(marker) == 1
        return payload.replace(marker, ">(다)<".encode(), 1)

    _rewrite_member(output, changed, "Contents/section0.xml", replace_label)

    with pytest.raises(HwpxManagerError, match="labels are not editable text"):
        verify_content_team_output(
            changed,
            expected_sha256=_sha256(changed.read_bytes()),
            expectations=(expectation,),
        )


def test_manager_rejects_arbitrary_builder_bytes(tmp_path: Path) -> None:
    output = tmp_path / "not-a-package.hwpx"
    output.write_bytes(b"SYNTHETIC_CONTENT_TEAM_HWPX")
    draft = parse_content_team_markdown_v2(TABLE_ONLY_ITEM.encode("utf-8"))

    with pytest.raises(HwpxManagerError, match="valid ZIP"):
        verify_content_team_output(
            output,
            expected_sha256=_sha256(output.read_bytes()),
            expectations=(
                ContentTeamOutputExpectation(
                    position=1,
                    item_revision_id="itemrev_" + "d" * 32,
                    draft=draft,
                    images=(),
                ),
            ),
        )


def test_output_acceptance_schema_and_model_agree_on_table_only() -> None:
    value = _table_only_acceptance_value()

    validate_hwpx_contract("content-team-output-acceptance-v1", value)
    parsed = ContentTeamOutputAcceptanceV1.model_validate(value)

    assert parsed.items[0].visual_layout == "TABLE_ONLY"
    assert len(parsed.items[0].tables) == 1
    assert parsed.items[0].images == ()


def test_output_acceptance_schema_and_model_reject_a_labeled_single_table() -> None:
    value = _table_only_acceptance_value()
    items = value["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    tables = item["tables"]
    assert isinstance(tables, list)
    table = tables[0]
    assert isinstance(table, dict)
    table["label"] = "(가)"
    item["structure_sha256"] = content_sha256(
        {key: member for key, member in item.items() if key != "structure_sha256"}
    )
    value["acceptance_sha256"] = content_sha256(
        {key: member for key, member in value.items() if key != "acceptance_sha256"}
    )

    with pytest.raises(JsonSchemaValidationError):
        validate_hwpx_contract("content-team-output-acceptance-v1", value)
    with pytest.raises(PydanticValidationError):
        ContentTeamOutputAcceptanceV1.model_validate(value)


def test_output_acceptance_model_rejects_a_forged_self_hash() -> None:
    value = _table_only_acceptance_value()
    value["acceptance_sha256"] = "sha256:" + "f" * 64

    validate_hwpx_contract("content-team-output-acceptance-v1", value)
    with pytest.raises(PydanticValidationError, match="acceptance hash differs"):
        ContentTeamOutputAcceptanceV1.model_validate(value)
