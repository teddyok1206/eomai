"""Excel successor: repeated targets, >200 positions, and old-contract isolation."""

import json
import shutil
from time import monotonic

import pytest
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import OCCURRENCE_OUTPUT_LIMITS, parse_native_document
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes
from eom_hwpx_contracts import parse_content_team_markdown
from eom_hwpx_contracts.curated_mixed import CuratedMixedRenderRequest
from eom_hwpx_contracts.curated_occurrences import (
    CuratedHwpxBuildInputV2,
    CuratedOccurrenceRenderRequest,
    NativeItemRenderRequestV2,
    parse_mixed_render_request,
    parse_mixed_render_result,
)
from eom_hwpx_contracts.validation import validate_contract
from eom_hwpx_manager.content_team_output_acceptance import ContentTeamOutputExpectation
from eom_hwpx_manager.curated_materialization import CuratedMaterialization
from eom_hwpx_manager.curated_output_acceptance import verify_curated_output
from eom_hwpx_manager.errors import HwpxManagerError
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.hwpx.test_curated_mixed_renderer import (
    handoff_bytes as handoff_bytes,
)
from tests.hwpx.test_curated_mixed_renderer import (
    save,
    stage_mixed,
)


def test_occurrence_build_does_not_reinterpret_historical_input():
    pointer = dict(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "1" * 32,
        member_path="source.hwpx",
        schema_ref="eom://schemas/content-intake/source-file/1.0",
        media_type="application/vnd.hancom.hwpx",
        sha256="sha256:" + "1" * 64,
    )
    value = CuratedHwpxBuildInputV2(
        assembly_id="assembly_" + "1" * 32,
        assembly_revision_id="assemblyrev_" + "1" * 32,
        assembly_manifest_sha256="sha256:" + "1" * 64,
        handoff=None,
        converter=None,
        placements=tuple(
            dict(
                kind="NATIVE_DOCUMENT",
                position=i,
                placement_id=f"placement_{i:032x}",
                document=pointer,
                source_format="HWPX",
                size_bytes=100,
            )
            for i in range(1, 1201)
        ),
    ).model_dump(mode="json")
    validate_contract("curated-build-input-v2", value)
    with pytest.raises(SchemaError):
        validate_contract("curated-build-input", value)
    value["placements"][1]["placement_id"] = value["placements"][0]["placement_id"]
    with pytest.raises(ValidationError, match="unique"):
        CuratedHwpxBuildInputV2.model_validate(value)


def test_real_303_occurrence_merge_keeps_native_images_tables_equations_and_repeats(
    tmp_path,
    handoff_bytes,
    record_property,
    monkeypatch,
):
    import eom_hwpx_builder.curated_mixed_renderer as renderer

    errors = []
    merger = renderer.merge_native_hwpx

    def traced_merge(*args, **kwargs):
        try:
            return merger(*args, **kwargs)
        except Exception as exc:
            errors.append(str(exc))
            raise

    monkeypatch.setattr(renderer, "merge_native_hwpx", traced_merge)
    root = tmp_path / "occurrences"
    historical, _ = stage_mixed(root, handoff_bytes)
    native = historical.segments[0].model_dump(mode="json")
    segments = []
    for position in range(1, 301):
        name = f"inputs/{position:03d}.hwpx"
        if position != 1:
            shutil.copyfile(root / "inputs/001.hwpx", root / name)
        segments.append({**native, "position": position, "local_file": name})
    canonical = historical.segments[1].model_dump(mode="json")
    original = json.loads((root / canonical["blueprint_file"]).read_bytes())
    blueprints = []
    for position in (301, 302):
        blueprint = NativeItemRenderRequestV2.model_validate(
            {
                **original,
                "schema_version": "native-item-render-request/2.0",
                "profile": "CANONICAL_ITEM_NATIVE_V2",
                "item_number": position,
            }
        )
        raw = canonical_json_bytes(blueprint.model_dump(mode="json"))
        blueprints.append(blueprint)
        name = f"input/items/{position:03d}/native-item.json"
        save(root, name, raw)
        segments.append(
            {
                **canonical,
                "position": position,
                "blueprint_file": name,
                "blueprint_sha256": sha256_bytes(raw),
                "blueprint_size_bytes": len(raw),
            }
        )
    editorial = historical.segments[3].model_dump(mode="json")
    for field in ("json_file", "markdown_file"):
        name = editorial[field].replace("/004/", "/303/")
        save(root, name, (root / editorial[field]).read_bytes())
        editorial[field] = name
    segments.append({**editorial, "position": 303})
    value = {
        **historical.model_dump(mode="json"),
        "schema_version": "curated-hwpx-render-request/4.0",
        "profile": "CURATED_EDITABLE_OCCURRENCES_V2",
        "segments": segments,
    }
    request = parse_mixed_render_request(value)
    assert isinstance(request, CuratedOccurrenceRenderRequest)
    with pytest.raises(ValidationError):
        CuratedMixedRenderRequest.model_validate(value)
    save(root, "request.json", canonical_json_bytes(value))
    started = monotonic()
    result = render_curated_workspace(root / "request.json", root / "result.json")
    record_property("render_seconds", monotonic() - started)
    assert result.status == "SUCCEEDED", (result, errors)
    assert result.schema_version == "curated-hwpx-render-result/4.0"
    assert parse_mixed_render_result(result.model_dump(mode="json")) == result
    assert result.section_source_positions == tuple(range(1, 304))
    assert result.source_sha256[:300] == (native["sha256"],) * 300
    assert result.source_sha256[300] == result.source_sha256[301]
    assert result.native_table_count >= 300 and result.native_equation_count >= 300
    document = parse_native_document(
        read_package(root / "output/assembled.hwpx", OCCURRENCE_OUTPUT_LIMITS),
        OCCURRENCE_OUTPUT_LIMITS,
    )
    assert len(document.sections) == 303 and len(document.binaries) >= 300
    texts = ["".join(section.itertext()) for _, section in document.sections]
    assert "301." in texts[300] and "302." in texts[301] and "303." in texts[302]
    assert "INTERNAL DESCRIPTION" not in texts[302]
    materialized = CuratedMaterialization(
        request,
        tuple(blueprints),
        (
            ContentTeamOutputExpectation(
                position=303,
                item_revision_id=editorial["item_revision_id"],
                draft=parse_content_team_markdown((root / editorial["markdown_file"]).read_bytes()),
                images=tuple(
                    request.segments[-1].images[i].binding
                    for i in range(len(request.segments[-1].images))
                ),
            ),
        ),
    )
    from unittest.mock import Mock

    import eom_hwpx_manager.curated_output_acceptance as acceptance

    options = Mock(wraps=acceptance._header_options)
    monkeypatch.setattr(acceptance, "_header_options", options)
    started = monotonic()
    accepted = verify_curated_output(root, materialized, result)
    record_property("acceptance_seconds", monotonic() - started)
    assert options.call_count == 304
    assert accepted.sha256 == result.output_sha256 and accepted.section_count == 303
    with pytest.raises(HwpxManagerError):
        verify_curated_output(
            root, materialized, result.model_copy(update={"profile": "CURATED_EDITABLE_V1"})
        )
