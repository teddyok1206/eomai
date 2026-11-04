"""Real local mixed rendering; no DB, model calls or production Artifact writes."""

from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path
from unittest.mock import Mock

import eom_hwpx_builder.curated_mixed_renderer as mixed
import pytest
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.content_team_handoff import inspect_content_team_handoff
from eom_hwpx_builder.curated_package_merge import OUTPUT_LIMITS, parse_native_document
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_item_renderer import render_native_item_document
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts import (
    CONTENT_TEAM_HANDOFF_MEMBERS,
    ContentTeamHandoffMember,
    ContentTeamHandoffSnapshot,
    ContentTeamImageSource,
    parse_content_team_markdown,
    parse_content_team_markdown_v2,
    serialize_content_team_markdown,
)
from eom_hwpx_contracts.curated_mixed import (
    CuratedCanonicalSegment,
    CuratedEditorialImage,
    CuratedEditorialSegment,
    CuratedMixedRenderRequest,
    CuratedMixedRenderResult,
    CuratedNativeSegment,
)
from eom_hwpx_contracts.native_item import NATIVE_ITEM_TEMPLATE_SHA256
from eom_hwpx_contracts.native_item_semantics import (
    expected_native_item_events,
    native_item_section_events,
)
from eom_hwpx_contracts.validation import validate_contract
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.hwpx.helpers import png_bytes
from tests.hwpx.test_content_team_markdown import GENERAL_ITEM, LABELED_BLOCK_ITEM
from tests.hwpx.test_native_item import content_and_projection

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "staging/HwpQuestionEditor_handoff_export.zip"
BUILD_ID = "hwpxbuild_" + "a" * 32


@pytest.fixture(scope="module")
def handoff_bytes():
    if not HANDOFF.is_file():
        pytest.skip("reviewed content-team handoff is unavailable")
    evidence = inspect_content_team_handoff(HANDOFF)
    template = next(row for row in evidence.members if row.purpose == "automation-template")
    with zipfile.ZipFile(HANDOFF) as archive:
        return HANDOFF.read_bytes(), archive.read(template.archive_member)


def save(root, name, data):
    target = root / name
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def stage_native_item(root, position, *, table_only=False):
    _content, projection, image = content_and_projection(body=(0, 1, 4) if table_only else None)
    plan = projection.document.model_copy(
        update={"item_number": position, "item_revision_id": f"itemrev_{position:032x}"}
    )
    for binding in projection.images:
        save(root, binding.image.local_file, image)
    raw = canonical_json_bytes(plan.model_dump(mode="json"))
    name = f"input/items/{position:03d}/native-item.json"
    save(root, name, raw)
    return plan, CuratedCanonicalSegment(
        position=position,
        item_revision_id=plan.item_revision_id,
        source_sha256=plan.source_sha256,
        effective_content_sha256=plan.effective_content_sha256,
        blueprint_file=name,
        blueprint_sha256=sha256_bytes(raw),
        blueprint_size_bytes=len(raw),
    )


def stage_editorial(root, position, *, version):
    if version == "2.0":
        draft = parse_content_team_markdown(GENERAL_ITEM.encode())
        labels = ("",)
    else:
        draft = parse_content_team_markdown_v2(LABELED_BLOCK_ITEM.encode())
        value = draft.model_dump(mode="json")
        value.update(
            visual_layout="IMAGE_IMAGE",
            visuals=[{"kind": "IMAGE", "label": label} for label in ("(가)", "(나)")],
        )
        draft = type(draft).model_validate(value)
        labels = ("(가)", "(나)")
    raw = canonical_json_bytes(
        {
            "schema_version": version,
            **draft.model_dump(mode="json", exclude={"schema_version", "source_sha256"}),
        }
    )
    markdown = serialize_content_team_markdown(draft)
    prefix = f"input/items/{position:03d}"
    save(root, f"{prefix}/item-content.json", raw)
    save(root, f"{prefix}/content-team-item.md", markdown)
    images = []
    for ordinal, label in enumerate(labels):
        data = png_bytes(output=ordinal == 0)
        sha = sha256_bytes(data)
        local = f"images/{sha[7:]}.png"
        save(root, local, data)
        images.append(
            CuratedEditorialImage(
                binding=ContentTeamImageSource(
                    visual_ordinal=ordinal,
                    label=label,
                    artifact_id=f"artifact_{ordinal + 10:032x}",
                    artifact_revision_id=f"rev_{ordinal + 20:032x}",
                    sha256=sha,
                    alt_text="INTERNAL DESCRIPTION MUST NOT BE PUBLISHED",
                    file_name=f"input/visual-{ordinal}.png",
                ),
                local_file=local,
                size_bytes=len(data),
            )
        )
    return CuratedEditorialSegment(
        position=position,
        item_revision_id=f"itemrev_{position:032x}",
        source_schema_ref=f"eom.assessment.item-content/{version}",
        json_file=f"{prefix}/item-content.json",
        source_sha256=sha256_bytes(raw),
        json_size_bytes=len(raw),
        markdown_file=f"{prefix}/content-team-item.md",
        markdown_sha256=sha256_bytes(markdown),
        markdown_size_bytes=len(markdown),
        images=tuple(images),
    )


def stage_mixed(root, handoff):
    root.mkdir(mode=0o700)
    archive_bytes, template_bytes = handoff
    save(root, "input/handoff.zip", archive_bytes)
    template = save(root, "template.hwpx", template_bytes)
    assert sha256_file(template) == NATIVE_ITEM_TEMPLATE_SHA256
    first, _segment = stage_native_item(root, 1)
    native = root / "inputs/001.hwpx"
    native.parent.mkdir(mode=0o700)
    render_native_item_document(root, first, native)
    plans = {}
    segments = [
        CuratedNativeSegment(
            position=1,
            local_file="inputs/001.hwpx",
            source_format="HWPX",
            sha256=sha256_file(native),
            size_bytes=native.stat().st_size,
        )
    ]
    for position in (2, 3):
        plans[position], segment = stage_native_item(root, position, table_only=position == 3)
        segments.append(segment)
    segments.extend(
        (stage_editorial(root, 4, version="2.0"), stage_editorial(root, 5, version="3.0"))
    )
    request = CuratedMixedRenderRequest(
        build_id=BUILD_ID,
        assembly_revision_id="assemblyrev_" + "b" * 32,
        assembly_manifest_sha256="sha256:" + "c" * 64,
        input_plan_sha256="sha256:" + "d" * 64,
        segments=tuple(segments),
        handoff=ContentTeamHandoffSnapshot(
            artifact_id="artifact_" + "e" * 32,
            artifact_revision_id="rev_" + "f" * 32,
            members=tuple(
                ContentTeamHandoffMember(purpose=purpose, sha256=sha, size=size)
                for purpose, sha, size in CONTENT_TEAM_HANDOFF_MEMBERS
            ),
        ),
        converter=None,
    )
    save(root, "request.json", canonical_json_bytes(request.model_dump(mode="json")))
    return request, plans


def test_mixed_native_canonical_editorial_output_is_ordered_editable_and_deterministic(
    tmp_path,
    handoff_bytes,
    monkeypatch,
):
    root = tmp_path / "first"
    request, plans = stage_mixed(root, handoff_bytes)
    validate_contract("curated-render-request-v3", request.model_dump(mode="json"))
    native_before = (root / "inputs/001.hwpx").read_bytes()
    template_before = (root / "template.hwpx").read_bytes()
    runtime = Mock(wraps=mixed.prepare_content_team_runtime)
    template = Mock(wraps=mixed.prepare_native_item_template)
    monkeypatch.setattr(mixed, "prepare_content_team_runtime", runtime)
    monkeypatch.setattr(mixed, "prepare_native_item_template", template)

    result = render_curated_workspace(root / "request.json", root / "result.json")

    assert isinstance(result, CuratedMixedRenderResult) and result.status == "SUCCEEDED"
    assert runtime.call_count == template.call_count == 1
    assert result.failure_position is None
    assert result.source_sha256 == tuple(
        segment.sha256 if isinstance(segment, CuratedNativeSegment) else segment.source_sha256
        for segment in request.segments
    )
    assert result.section_source_positions == (1, 2, 3, 4, 5)
    assert result.native_equation_count > 0 and result.native_table_count > 0
    assert (root / "inputs/001.hwpx").read_bytes() == native_before
    assert (root / "template.hwpx").read_bytes() == template_before
    validate_contract("curated-render-result-v3", result.model_dump(mode="json"))
    document = parse_native_document(read_package(root / "output/assembled.hwpx", OUTPUT_LIMITS))
    entries = document.package.by_name()
    hashes = {
        key: sha256_bytes(entries[member].data)
        for key, (member, _media) in document.binaries.items()
    }
    for position, plan in plans.items():
        member, _section = document.sections[position - 1]
        assert native_item_section_events(
            entries[member].data, hashes
        ) == expected_native_item_events(plan)
    for member, _section in document.sections:
        assert b"INTERNAL DESCRIPTION" not in entries[member].data
        assert b"INTERNAL IMAGE DESCRIPTION" not in entries[member].data
        assert b"[[" not in entries[member].data
    hp = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
    for position in (4, 5):
        section = document.sections[position - 1][1]
        texts = ["".join(p.itertext()) for p in section.iter(hp + "p")]
        assert not any(f"1. {position}. " in text for text in texts)
        assert any(text.startswith(f"{position}. ") for text in texts)
    table = next(
        table
        for table in document.sections[3][1].iter(hp + "tbl")
        if table.get("colCnt") == "3"
        and tuple("".join(cell.itertext()) for cell in table.find(hp + "tr").findall(hp + "tc"))
        == ("구간", "속력", "방향")
    )
    parent = next(table.iterancestors(hp + "tc"))
    width = int(parent.find(hp + "cellSz").get("width"))
    margins = parent.find(hp + "cellMargin")
    assert int(table.find(hp + "sz").get("width")) <= width - int(margins.get("left")) - int(
        margins.get("right")
    )
    assert all(
        int(cell.find(hp + "cellSz").get("height")) >= 1800
        for row in table.findall(hp + "tr")
        for cell in row.findall(hp + "tc")
    )
    labels = [
        cell
        for cell in document.sections[4][1].iter(hp + "tc")
        if "".join(cell.itertext()) in {"(가)", "(나)"}
    ]
    assert len(labels) == 2
    assert all(int(cell.find(hp + "cellSz").get("height")) >= 1800 for cell in labels)
    assert b"(\xea\xb0\x80)" in entries[document.sections[4][0]].data
    assert stat.S_IMODE((root / "output/assembled.hwpx").stat().st_mode) == 0o640
    assert stat.S_IMODE((root / "output/segment-002.hwpx").stat().st_mode) == 0o640
    assert json.loads((root / "output/preservation.json").read_bytes()) == result.model_dump(
        mode="json"
    )
    with pytest.raises(HwpxError, match="fixed workspace"):
        render_curated_workspace(root / "request.json", root / "result.json")
    assert runtime.call_count == 1

    second = tmp_path / "second"
    stage_mixed(second, handoff_bytes)
    repeated = render_curated_workspace(second / "request.json", second / "result.json")
    assert repeated == result
    assert (second / "output/assembled.hwpx").read_bytes() == (
        root / "output/assembled.hwpx"
    ).read_bytes()


@pytest.mark.parametrize(
    "damage", ["blueprint_identity", "blueprint_hash", "image", "symlink", "markdown"]
)
def test_changed_or_unsafe_segment_is_not_published_and_identifies_its_position(
    tmp_path,
    handoff_bytes,
    damage,
):
    root = tmp_path / "workspace"
    request, _plans = stage_mixed(root, handoff_bytes)
    expected_position = 2
    expected_code = "HWPX_CURATED_INPUT_CHANGED"
    if damage.startswith("blueprint"):
        segment = request.segments[1]
        target = root / segment.blueprint_file
        if damage == "blueprint_hash":
            target.write_bytes(b"not the pinned blueprint")
        else:
            value = json.loads(target.read_bytes())
            value["item_revision_id"] = "itemrev_" + "0" * 32
            raw = canonical_json_bytes(value)
            target.write_bytes(raw)
            updated = segment.model_copy(
                update={"blueprint_sha256": sha256_bytes(raw), "blueprint_size_bytes": len(raw)}
            )
            request = request.model_copy(
                update={"segments": (request.segments[0], updated, *request.segments[2:])}
            )
    elif damage == "image":
        image = _plans[2].body[2]
        (root / image.local_file).write_bytes(b"changed image")
    elif damage == "symlink":
        target = root / request.segments[1].blueprint_file
        moved = root / "otherwise-valid-blueprint.json"
        target.rename(moved)
        target.symlink_to(moved)
        expected_code = "HWPX_CURATED_INPUT_INVALID"
    else:
        expected_position = 4
        (root / request.segments[3].markdown_file).write_bytes(b"changed markdown")
    save(root, "request.json", canonical_json_bytes(request.model_dump(mode="json")))

    result = render_curated_workspace(root / "request.json", root / "result.json")

    assert result.status == "FAILED" and result.failure_code == expected_code
    assert result.failure_position == expected_position
    assert result.source_sha256 == result.segment_sha256 == ()
    assert result.output_sha256 is None and not (root / "output/assembled.hwpx").exists()
    assert result.binary_count == result.native_table_count == result.native_equation_count == 0
    assert stat.S_IMODE((root / "result.json").stat().st_mode) == 0o640
    validate_contract("curated-render-result-v3", result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "name", ["hwpx-curated-render-v3.schema.json", "hwpx-curated-render-result-v3.schema.json"]
)
def test_mixed_schema_is_self_contained_202012_and_mirrored(name):
    raw = (ROOT / "schemas/hwpx" / name).read_bytes()
    assert raw == (ROOT / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name).read_bytes()
    schema = json.loads(raw)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)


def test_mixed_request_rejects_missing_resources_repeated_identity_and_reordered_placements(
    tmp_path,
    handoff_bytes,
):
    request, _plans = stage_mixed(tmp_path / "workspace", handoff_bytes)
    for changes in (
        {"handoff": None},
        {"segments": [request.segments[1].model_dump(), request.segments[0].model_dump()]},
        {
            "segments": [
                request.segments[0].model_dump(),
                request.segments[1].model_dump(),
                request.segments[2]
                .model_copy(update={"item_revision_id": request.segments[1].item_revision_id})
                .model_dump(),
            ]
        },
    ):
        with pytest.raises(ValidationError):
            CuratedMixedRenderRequest.model_validate({**request.model_dump(), **changes})
