from __future__ import annotations

import json
import shutil
import warnings
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.archive import _validate_name, read_package
from eom_hwpx_builder.bindings import BindingKind, compile_bindings
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.models import BindingManifest, PackageLimits
from eom_hwpx_builder.renderer import failed_result, render_workspace
from eom_hwpx_builder.semantic import compare_semantic, extract_semantic
from eom_hwpx_builder.util import sha256_bytes
from eom_hwpx_builder.validation import validate_structure
from eom_hwpx_builder.xmlsafe import parse_xml
from eom_hwpx_contracts import HwpxBuildResult, HwpxItemDocument, validate_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.hwpx.helpers import (
    document,
    png_bytes,
    prepare_workspace,
    synthetic_parts,
    write_hwpx,
)


def _zip(
    path: Path, entries: list[tuple[str, bytes]], compression: int = zipfile.ZIP_STORED
) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "dir\\..\\escape"])
def test_zip_path_traversal_and_unsafe_names(tmp_path: Path, name: str) -> None:
    package = tmp_path / "unsafe.hwpx"
    _zip(package, [(name, b"x")])
    with pytest.raises(HwpxError) as caught:
        read_package(package)
    assert caught.value.code == HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL


def test_zip_nul_name_is_rejected() -> None:
    with pytest.raises(HwpxError) as caught:
        _validate_name("bad\x00name", PackageLimits())
    assert caught.value.code == HwpxErrorCode.HWPX_ZIP_PATH_TRAVERSAL


def test_duplicate_and_case_colliding_entries(tmp_path: Path) -> None:
    package = tmp_path / "duplicate.hwpx"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _zip(package, [("mimetype", b"a"), ("MIMETYPE", b"b")])
    with pytest.raises(HwpxError) as caught:
        read_package(package)
    assert caught.value.code == HwpxErrorCode.HWPX_ZIP_DUPLICATE_ENTRY


def test_entry_count_and_compression_ratio_limits(tmp_path: Path) -> None:
    many = tmp_path / "many.hwpx"
    _zip(many, [(f"part{index}", b"x") for index in range(3)])
    with pytest.raises(HwpxError) as caught:
        read_package(many, PackageLimits(max_entries=2))
    assert caught.value.code == HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED

    compressed = tmp_path / "ratio.hwpx"
    _zip(compressed, [("large.xml", b"A" * 5000)], zipfile.ZIP_DEFLATED)
    with pytest.raises(HwpxError) as caught:
        read_package(compressed, PackageLimits(max_compression_ratio=2))
    assert caught.value.code == HwpxErrorCode.HWPX_ZIP_BOMB_DETECTED


@pytest.mark.parametrize(
    "payload,code",
    [
        (
            b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
            HwpxErrorCode.HWPX_XML_UNSAFE,
        ),
        (
            b'<x xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="file:///etc/passwd"/></x>',
            HwpxErrorCode.HWPX_XML_UNSAFE,
        ),
        (b"<x><broken></x>", HwpxErrorCode.HWPX_XML_INVALID),
    ],
)
def test_secure_xml_rejects_dtd_xinclude_and_malformed(payload: bytes, code: HwpxErrorCode) -> None:
    with pytest.raises(HwpxError) as caught:
        parse_xml(payload, "unsafe.xml")
    assert caught.value.code == code


def test_input_contract_rejects_control_character_unknown_field_and_bad_path() -> None:
    value = document()
    value["item"]["upper_stem"] = "bad\x01text"
    with pytest.raises((ValidationError, JsonSchemaValidationError)):
        HwpxItemDocument.model_validate(value)
    value = document()
    value["unknown"] = True
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("item-document", value)
    value = document()
    value["item"]["image"]["source_path"] = "../output.png"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("item-document", value)


def test_analyzer_reports_package_profile_markers_image_equation_and_unknown(
    tmp_path: Path,
) -> None:
    path = write_hwpx(tmp_path / "synthetic.hwpx")
    analysis = analyze_package(path)
    assert analysis.mimetype == "application/hwp+zip"
    assert analysis.spine == ("section0",)
    assert analysis.sections == ("Contents/section0.xml",)
    assert analysis.bindata == ("BinData/image1.png",)
    assert len(analysis.marker_locations) == 26
    assert analysis.image_candidates[0]["part"] == "BinData/image1.png"
    assert analysis.equation_candidates[0]["object_id"] == "eq1"
    assert analysis.unknown_parts == ("Extra/unknown.dat",)
    assert analysis.active_content == ()


def test_active_content_and_external_links_are_reported(tmp_path: Path) -> None:
    parts = synthetic_parts()
    parts.append(("Scripts/sourceScripts.xml", b"<script/>", zipfile.ZIP_DEFLATED))
    path = write_hwpx(tmp_path / "active.hwpx", parts)
    analysis = analyze_package(path)
    assert analysis.active_content
    assert validate_structure(path).status == "FAIL"


def test_binding_compiler_handles_split_marker_and_anchor_fallback(tmp_path: Path) -> None:
    reference = png_bytes()
    path = write_hwpx(
        tmp_path / "anchor.hwpx",
        synthetic_parts(split_marker=True, equation_anchor=True, reference_image=reference),
    )
    bindings = compile_bindings(
        path,
        template_id="hwpxtpl_" + "a" * 32,
        template_revision_id="hwpxrev_" + "b" * 32,
        reference_image_sha256=sha256_bytes(reference),
    )
    upper = next(
        binding for binding in bindings.bindings if binding.field_name == "item.upper_stem"
    )
    equation = next(
        binding for binding in bindings.bindings if binding.field_name == "item.equation.source"
    )
    assert upper.constraints["split_across_text_nodes"] is True
    assert equation.binding_kind == BindingKind.EQUATION_ANCHOR
    assert "anchor_text_locator" in equation.constraints
    image = next(
        binding for binding in bindings.bindings if binding.binding_kind == BindingKind.IMAGE_BINARY
    )
    assert image.object_id == "pic1"
    assert image.reference_ids == ("image1",)
    table = next(
        binding for binding in bindings.bindings if binding.field_name == "item.table.rows.1.2"
    )
    assert table.locator["cell_index"] == 5


def test_binding_compiler_rejects_missing_duplicate_marker_and_image_hash(tmp_path: Path) -> None:
    reference = png_bytes()
    parts = synthetic_parts(reference_image=reference)
    section_index = next(
        index for index, part in enumerate(parts) if part[0].endswith("section0.xml")
    )
    name, data, compression = parts[section_index]
    parts[section_index] = (name, data.replace(b"{{EOM_POINTS}}", b"MISSING"), compression)
    missing = write_hwpx(tmp_path / "missing.hwpx", parts)
    with pytest.raises(HwpxError) as caught:
        compile_bindings(
            missing,
            template_id="hwpxtpl_" + "a" * 32,
            template_revision_id="hwpxrev_" + "b" * 32,
            reference_image_sha256=sha256_bytes(reference),
        )
    assert caught.value.code == HwpxErrorCode.HWPX_TEMPLATE_MARKER_MISSING

    parts = synthetic_parts(reference_image=reference)
    index = next(index for index, part in enumerate(parts) if part[0].endswith("section0.xml"))
    name, data, compression = parts[index]
    parts[index] = (
        name,
        data.replace(
            b"</hp:section>",
            b"<hp:p><hp:run><hp:t>{{EOM_POINTS}}</hp:t></hp:run></hp:p></hp:section>",
        ),
        compression,
    )
    duplicate = write_hwpx(tmp_path / "duplicate-marker.hwpx", parts)
    with pytest.raises(HwpxError) as caught:
        compile_bindings(
            duplicate,
            template_id="hwpxtpl_" + "a" * 32,
            template_revision_id="hwpxrev_" + "b" * 32,
            reference_image_sha256=sha256_bytes(reference),
        )
    assert caught.value.code == HwpxErrorCode.HWPX_TEMPLATE_MARKER_DUPLICATE

    valid = write_hwpx(tmp_path / "image.hwpx", synthetic_parts(reference_image=reference))
    with pytest.raises(HwpxError) as caught:
        compile_bindings(
            valid,
            template_id="hwpxtpl_" + "a" * 32,
            template_revision_id="hwpxrev_" + "b" * 32,
            reference_image_sha256="sha256:" + "0" * 64,
        )
    assert caught.value.code == HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED


def test_structural_validator_catches_mimetype_manifest_spine_and_duplicate_id(
    tmp_path: Path,
) -> None:
    cases: list[tuple[str, bytes, bytes]] = [
        ("mimetype", b"application/hwp+zip", b"wrong/type"),
        ("Contents/content.hpf", b"../BinData/image1.png", b"../BinData/missing.png"),
        ("Contents/content.hpf", b'idref="section0"', b'idref="missing"'),
        ("Contents/section0.xml", b'id="p1"', b'id="p0"'),
    ]
    for case_index, (part_name, old, new) in enumerate(cases):
        parts = synthetic_parts()
        index = next(index for index, part in enumerate(parts) if part[0] == part_name)
        name, data, compression = parts[index]
        parts[index] = (name, data.replace(old, new, 1), compression)
        path = write_hwpx(tmp_path / f"invalid-{case_index}.hwpx", parts)
        assert validate_structure(path).status == "FAIL"


def test_renderer_round_trip_replaces_all_bound_values_and_is_deterministic(tmp_path: Path) -> None:
    first_request, output_image = prepare_workspace(tmp_path / "first")
    first_result = render_workspace(first_request, first_request.parent / "result.json")
    first_output = first_request.parent / str(first_result.output_file)
    assert first_result.status == "PENDING_MANUAL_HANCOM_VALIDATION"
    assert first_result.output_sha256 == sha256_bytes(first_output.read_bytes())
    assert (
        validate_structure(
            first_output,
            bindings=BindingManifest.model_validate_json(
                (first_request.parent / "template-bindings.json").read_text()
            ),
            expected_image_sha256=sha256_bytes(output_image),
            expected_equation_source="x+y=z",
            require_markers_removed=True,
        ).status
        == "PASS"
    )
    section = read_package(first_output).by_name()["Contents/section0.xml"].data.decode("utf-8")
    assert "PLACEHOLDER UPPER STEM 한글 &amp; &lt;XML&gt;" in section

    second_request, _ = prepare_workspace(tmp_path / "second")
    second_result = render_workspace(second_request, second_request.parent / "result.json")
    second_output = second_request.parent / str(second_result.output_file)
    assert second_output.read_bytes() == first_output.read_bytes()
    assert second_result.output_sha256 == first_result.output_sha256


def test_renderer_preserves_unknown_part_entry_order_and_compression(tmp_path: Path) -> None:
    request, _ = prepare_workspace(tmp_path / "workspace")
    template = read_package(request.parent / "template.hwpx")
    result = render_workspace(request, request.parent / "result.json")
    output = read_package(request.parent / str(result.output_file))
    assert [entry.info.filename for entry in output.entries] == [
        entry.info.filename for entry in template.entries
    ]
    assert [entry.info.compress_type for entry in output.entries] == [
        entry.info.compress_type for entry in template.entries
    ]
    assert output.by_name()["Extra/unknown.dat"].data == b"SYNTHETIC UNKNOWN PART"


def test_semantic_exact_match_and_mismatch(tmp_path: Path) -> None:
    request, _ = prepare_workspace(tmp_path / "workspace")
    result = render_workspace(request, request.parent / "result.json")
    output = request.parent / str(result.output_file)
    bindings = BindingManifest.model_validate_json(
        (request.parent / "template-bindings.json").read_text()
    )
    actual = extract_semantic(output, bindings)
    assert actual["item.table.rows.1.2"] == "PLACEHOLDER R2C3"
    expected = document()
    assert compare_semantic(expected, output, bindings).status == "PASS"
    expected["item"]["choices"][0] = "DIFFERENT PLACEHOLDER"
    report = compare_semantic(expected, output, bindings)
    assert report.status == "FAIL"
    assert report.fields["item.choices.0"] == "MISMATCH"


def test_image_dimension_validation_and_result_schema(tmp_path: Path) -> None:
    request, _ = prepare_workspace(tmp_path / "workspace")
    wrong = png_bytes(output=True, dimensions=(400, 250))
    image_path = request.parent / "input/eom-placeholder-image-output.png"
    image_path.write_bytes(wrong)
    value = json.loads((request.parent / "input/document.json").read_text())
    value["item"]["image"]["sha256"] = sha256_bytes(wrong)
    (request.parent / "input/document.json").write_text(json.dumps(value))
    with pytest.raises(HwpxError) as caught:
        render_workspace(request, request.parent / "result.json")
    assert caught.value.code == HwpxErrorCode.HWPX_IMAGE_REPLACEMENT_FAILED
    failed = failed_result(request, request.parent / "result.json", datetime.now(UTC), caught.value)
    assert failed is not None
    validate_contract("build-result", failed.model_dump(mode="json"))
    assert HwpxBuildResult.model_validate_json(
        (request.parent / "result.json").read_text()
    ).errors == ("HWPX_IMAGE_REPLACEMENT_FAILED",)


def test_package_copy_does_not_make_synthetic_fixture_a_compatibility_claim(tmp_path: Path) -> None:
    path = write_hwpx(tmp_path / "synthetic.hwpx")
    copy = tmp_path / "copy.hwpx"
    shutil.copyfile(path, copy)
    assert analyze_package(copy).version_info["owpml"] == "synthetic-poc"
