from __future__ import annotations

import copy
from pathlib import Path
from zipfile import ZipFile

import pytest
from eom_hwpx_builder.curated_package_merge import merge_native_hwpx
from eom_hwpx_builder.curated_renderer import render_curated_workspace
from eom_hwpx_builder.curated_resources import (
    NativeMergeProfile,
    ObjectRelocation,
    catalog_rows,
    merge_resources,
    verify_resource_relocation,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.xmlsafe import local_name, parse_xml
from eom_hwpx_contracts.curated_document import (
    CuratedHwpxRenderRequestV2,
    CuratedHwpxRenderResultV2,
)
from eom_hwpx_contracts.validation import validate_contract
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from tests.hwpx.test_curated_native_merge import header, replace, request_value, source
from tests.hwpx.test_curated_renderer import submit, workspace

PROFILE = NativeMergeProfile.EDITABLE_V2
VERSION = b"""<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version"
    tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1"
    os="1" xmlVersion="1.4" application="Example" appVersion="1"/>"""
SETTING = b"""<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app"
    xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">
    <ha:CaretPosition listIDRef="0" paraIDRef="1" pos="2"/>{}</ha:HWPApplicationSetting>"""
PRINT = b"""<config:config-item-set name="PrintInfo"><config:config-item
    name="ZoomX" type="short">100</config:config-item></config:config-item-set>"""


def test_windows_and_mac_producer_metadata_can_share_native_v2_but_not_v1(tmp_path):
    first = office_source(tmp_path, "windows.hwpx")
    second = office_source(tmp_path, "mac.hwpx", version=VERSION.replace(b'os="1"', b'os="10"'))
    before = first.read_bytes(), second.read_bytes()
    report = merge_native_hwpx((first, second), tmp_path / "combined.hwpx", profile=PROFILE)
    assert report.section_source_positions == (1, 2)
    assert (first.read_bytes(), second.read_bytes()) == before
    with pytest.raises(HwpxError, match="global settings differ"):
        merge_native_hwpx((first, second), tmp_path / "v1.hwpx")


def office_source(tmp_path: Path, name: str, *, version=VERSION, settings=b"", changes=None):
    def transform(parts):
        parts = [
            (
                member,
                version
                if member == "version.xml"
                else SETTING.replace(b"{}", settings)
                if member == "settings.xml"
                else data,
                method,
            )
            for member, data, method in parts
        ]
        return changes(parts) if changes else parts

    return source(tmp_path, name, changes=transform)


def test_editable_profile_accepts_declared_version_and_neutral_print_difference(tmp_path):
    first = office_source(tmp_path, "first.hwpx", settings=PRINT)
    second = office_source(
        tmp_path,
        "second.hwpx",
        version=VERSION.replace(b'micro="0"', b'micro="1"').replace(
            b'xmlVersion="1.4"', b'xmlVersion="1.5"'
        ),
    )
    before = first.read_bytes(), second.read_bytes()
    with pytest.raises(HwpxError, match="global settings"):
        merge_native_hwpx((first, second), tmp_path / "v1.hwpx")
    output = tmp_path / "v2.hwpx"
    receipt = merge_native_hwpx((first, second), output, profile=PROFILE)
    assert receipt.warnings == ("FIRST_DOCUMENT_PRINT_SETTINGS", "STYLE_NAMES_RELOCATED")
    with ZipFile(output) as archive:
        assert archive.read("settings.xml") == SETTING.replace(b"{}", PRINT)
        version = parse_xml(archive.read("version.xml"), "version").root
        assert version.get("xmlVersion") == "1.5"
        assert version.get("micro") == "1"
        definitions = catalog_rows(parse_xml(archive.read("Contents/header.xml"), "header").root)
        names = [row.get("name") for row in definitions["styles"].values()]
        assert names[:2] == ["Style A", "Other"]
        assert len(names) == len(set(names)) == 4
    assert before == (first.read_bytes(), second.read_bytes())
    replay = tmp_path / "again.hwpx"
    assert merge_native_hwpx((first, second), replay, profile=PROFILE) == receipt
    assert output.read_bytes() == replay.read_bytes()


@pytest.mark.parametrize(
    "setting",
    [
        PRINT.replace(b">100<", b">50<"),
        PRINT.replace(b"ZoomX", b"UnknownSetting"),
        PRINT.replace(b"</config:config-item-set>", b"<config:future/></config:config-item-set>"),
        PRINT.replace(b"</config:config-item-set>", PRINT + b"</config:config-item-set>"),
    ],
)
def test_editable_profile_does_not_ignore_unknown_or_non_neutral_options(tmp_path, setting):
    first = office_source(tmp_path, "one.hwpx")
    second = office_source(tmp_path, "two.hwpx", settings=setting)
    with pytest.raises(HwpxError, match="global settings"):
        merge_native_hwpx((first, second), tmp_path / "bad.hwpx", profile=PROFILE)
    assert not (tmp_path / "bad.hwpx").exists()


def test_header_union_and_default_tracking_do_not_invent_missing_definitions():
    first = parse_xml(header(), "header").root
    second = parse_xml(header("B"), "header").root
    reference = next(node for node in second if local_name(node.tag) == "refList")
    extra = parse_xml(
        b'<hh:bullets xmlns:hh="urn:synthetic:header" itemCnt="1"><hh:bullet id="1"/></hh:bullets>',
        "extra",
    ).root
    reference.append(extra)
    objects = (ObjectRelocation({}), ObjectRelocation({}))
    merged, plans = merge_resources((first, second), ({}, {}), objects, profile=PROFILE)
    assert len(catalog_rows(merged)["bullets"]) == 1
    verify_resource_relocation((first, second), merged, plans)
    changed = copy.deepcopy(merged)
    catalog_rows(changed)["styles"]["2"].set("name", "changed after merge")
    with pytest.raises(HwpxError, match="style name differs"):
        verify_resource_relocation((first, second), changed, plans)
    with pytest.raises(HwpxError, match="catalog sets differ"):
        merge_resources((first, second), ({}, {}), objects)


def test_anonymous_grouped_shapes_are_distinct_but_ambiguous_nonzero_ids_still_fail(tmp_path):
    def shapes(parts):
        return replace(
            parts,
            "Contents/section0.xml",
            b"</hp:section>",
            b'<hp:container id="0"><hp:rect id="0"/><hp:rect id="0"/></hp:container></hp:section>',
        )

    first = source(tmp_path, "one.hwpx", changes=shapes)
    output = tmp_path / "output.hwpx"
    receipt = merge_native_hwpx((first,), output, profile=PROFILE)
    assert receipt.section_source_positions == (1,)
    with ZipFile(output) as archive:
        root = parse_xml(archive.read("Contents/section0.xml"), "section").root
        identifiers = [
            node.get("id") for node in root.iter() if local_name(node.tag) in {"container", "rect"}
        ]
        assert len(set(identifiers)) == 3 and "0" not in identifiers
    with pytest.raises(HwpxError, match="repeats a document object"):
        merge_native_hwpx((first,), tmp_path / "strict.hwpx")
    duplicate = source(
        tmp_path,
        "duplicate.hwpx",
        changes=lambda parts: replace(
            shapes(parts), "Contents/section0.xml", b'container id="0"', b'container id="pic1"'
        ),
    )
    with pytest.raises(HwpxError, match="repeats a document object"):
        merge_native_hwpx((duplicate,), tmp_path / "bad.hwpx", profile=PROFILE)


def test_converter_pin_and_source_segment_lineage_are_not_interchangeable():
    value = request_value()
    value.update(
        schema_version="curated-hwpx-render-request/2.0", profile=PROFILE.value, converter=None
    )
    validate_contract("curated-render-request-v2", value)
    assert CuratedHwpxRenderRequestV2.model_validate(value).converter is None
    value["segments"][0].update(source_format="HWP", local_file="inputs/001.hwp")
    with pytest.raises(ValidationError, match="converter identity"):
        CuratedHwpxRenderRequestV2.model_validate(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("curated-render-request-v2", value)
    value["converter"] = {
        "profile": "HWP2HWPX_NATIVE_V1",
        "source_commit": "62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
        "bundle_sha256": "sha256:" + "e" * 64,
    }
    validate_contract("curated-render-request-v2", value)
    assert CuratedHwpxRenderRequestV2.model_validate(value).converter is not None
    result = {
        "schema_version": "curated-hwpx-render-result/2.0",
        "profile": PROFILE.value,
        "build_id": value["build_id"],
        "assembly_revision_id": value["assembly_revision_id"],
        "assembly_manifest_sha256": value["assembly_manifest_sha256"],
        "request_sha256": "sha256:" + "a" * 64,
        "status": "SUCCEEDED",
        "source_sha256": ["sha256:" + "b" * 64],
        "segment_sha256": ["sha256:" + "c" * 64],
        "section_source_positions": [1],
        "binary_count": 1,
        "output_sha256": "sha256:" + "d" * 64,
        "output_size_bytes": 10,
        "failure_code": None,
        "warnings": ["HWP_CONVERTED_NATIVE"],
        "converter_bundle_sha256": value["converter"]["bundle_sha256"],
    }
    validate_contract("curated-render-result-v2", result)
    parsed = CuratedHwpxRenderResultV2.model_validate(result)
    assert parsed.segment_sha256 != parsed.source_sha256
    result["segment_sha256"] = []
    with pytest.raises(ValidationError, match="lineage count"):
        CuratedHwpxRenderResultV2.model_validate(result)


@pytest.mark.parametrize(
    "name", ["hwpx-curated-render-v2.schema.json", "hwpx-curated-render-result-v2.schema.json"]
)
def test_successor_schema_mirrors(name):
    root = Path(__file__).resolve().parents[2]
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()


def test_native_v2_renderer_uses_its_own_result_contract(tmp_path):
    root, value = workspace(tmp_path)
    value.update(
        schema_version="curated-hwpx-render-request/2.0", profile=PROFILE.value, converter=None
    )
    result = submit(root, value)
    assert isinstance(result, CuratedHwpxRenderResultV2)
    assert result.status == "SUCCEEDED"
    assert result.source_sha256 == result.segment_sha256
    validate_contract("curated-render-result-v2", result.model_dump(mode="json"))


def test_native_hwp_v2_keeps_original_and_converted_hash_chains_distinct(tmp_path, monkeypatch):
    from eom_hwpx_builder import curated_renderer
    from eom_hwpx_builder.hwp_conversion_package import HwpConversionPackageReceipt
    from eom_hwpx_builder.util import sha256_file

    root, value = workspace(tmp_path)
    native = tmp_path / "editable.hwpx"
    (root / "inputs/001.hwpx").rename(native)
    original = root / "inputs/001.hwp"
    original.write_bytes(b"immutable staged native HWP source")
    value.update(
        schema_version="curated-hwpx-render-request/2.0",
        profile=PROFILE.value,
        converter={
            "profile": "HWP2HWPX_NATIVE_V1",
            "source_commit": "62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
            "bundle_sha256": "sha256:" + "e" * 64,
        },
    )
    value["segments"][0].update(
        source_format="HWP",
        local_file="inputs/001.hwp",
        sha256=sha256_file(original),
        size_bytes=original.stat().st_size,
    )
    calls = []

    class Converter:
        def __init__(self, snapshot):
            assert snapshot.bundle_sha256 == value["converter"]["bundle_sha256"]

        def convert(self, source_path, output, *, source_sha256):
            calls.append((source_path, source_sha256))
            output.write_bytes(native.read_bytes())
            return HwpConversionPackageReceipt("sha256:" + "f" * 64, sha256_file(output), 0, 0)

    monkeypatch.setattr(curated_renderer, "NativeHwpConverter", Converter)
    result = submit(root, value)
    assert result.status == "SUCCEEDED"
    assert result.source_sha256 == (sha256_file(original),)
    assert result.segment_sha256 == (sha256_file(native),)
    assert result.source_sha256 != result.segment_sha256
    assert result.converter_bundle_sha256 == value["converter"]["bundle_sha256"]
    assert result.warnings == ("HWP_CONVERTED_NATIVE",)
    assert calls == [(original, sha256_file(original))]
    assert original.read_bytes() == b"immutable staged native HWP source"
    validate_contract("curated-render-result-v2", result.model_dump(mode="json"))


def test_shape_instances_and_field_ids_do_not_collide_between_documents(tmp_path):
    def instances(parts):
        parts = replace(
            parts, "Contents/section0.xml", b'<hp:pic id="pic1"', b'<hp:pic id="pic1" instid="5000"'
        )
        return replace(
            parts,
            "Contents/section0.xml",
            b"</hp:section>",
            b'<hp:ctrl><hp:fieldBegin id="7" fieldid="7000"/>'
            b'<hp:fieldEnd beginIDRef="7"/></hp:ctrl></hp:section>',
        )

    first = source(tmp_path, "one.hwpx", changes=instances)
    second = source(tmp_path, "two.hwpx", changes=instances)
    output = tmp_path / "merged.hwpx"
    merge_native_hwpx((first, second), output, profile=PROFILE)
    with ZipFile(output) as archive:
        roots = [
            parse_xml(archive.read(f"Contents/section{i}.xml"), "section").root for i in range(2)
        ]
        instance_ids = [n.get("instid") for r in roots for n in r.iter() if n.get("instid")]
        assert len(instance_ids) == len(set(instance_ids)) == 2
        field_ids = [n.get("fieldid") for r in roots for n in r.iter() if n.get("fieldid")]
        assert len(field_ids) == len(set(field_ids)) == 2
        for root in roots:
            begin = next(n for n in root.iter() if local_name(n.tag) == "fieldBegin")
            end = next(n for n in root.iter() if local_name(n.tag) == "fieldEnd")
            assert begin.get("id") == end.get("beginIDRef") == begin.get("fieldid")


@pytest.mark.parametrize("version", ["1.0", "2.0"])
def test_curated_request_does_not_accept_duplicate_schema_or_pointer_keys(tmp_path, version):
    root, _value = workspace(tmp_path)
    payload = (
        '{"schema_version":"curated-hwpx-render-request/' + version + '",'
        '"schema_version":"curated-hwpx-render-request/' + version + '"}'
    ).encode()
    (root / "request.json").write_bytes(payload)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        render_curated_workspace(root / "request.json", root / "result.json")
    assert not (root / "output").exists()
