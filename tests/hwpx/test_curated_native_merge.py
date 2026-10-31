from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.curated_package_merge import merge_native_hwpx
from eom_hwpx_builder.curated_resources import (
    catalog_rows,
    merge_resources,
    relocate_tree,
    verify_resource_relocation,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.xmlsafe import parse_xml
from eom_hwpx_contracts.curated_document import CuratedHwpxRenderRequest
from eom_hwpx_contracts.validation import validate_contract
from pydantic import ValidationError

from tests.hwpx.helpers import png_bytes, synthetic_parts, write_hwpx


def header(font: str = "First", *, style: str = "Style A") -> bytes:
    return f'''<hh:head xmlns:hh="urn:synthetic:header" secCnt="1">
    <hh:beginNum page="1"/>
    <hh:refList><hh:fontfaces itemCnt="1"><hh:fontface lang="HANGUL" fontCnt="1">
      <hh:font id="0" face="{font}"/></hh:fontface></hh:fontfaces>
    <hh:borderFills itemCnt="1"><hh:borderFill id="1"/></hh:borderFills>
    <hh:charProperties itemCnt="2">
      <hh:charPr id="0"><hh:fontRef hangul="0"/><hh:borderFill borderFillIDRef="1"/></hh:charPr>
      <hh:charPr id="1"><hh:fontRef hangul="0"/></hh:charPr>
    </hh:charProperties>
    <hh:paraProperties itemCnt="1"><hh:paraPr id="0"/></hh:paraProperties>
    <hh:styles itemCnt="2">
      <hh:style id="0" name="{style}" charPrIDRef="0" paraPrIDRef="0" nextStyleIDRef="1"/>
      <hh:style id="1" name="Other" charPrIDRef="1" paraPrIDRef="0" nextStyleIDRef="0"/>
    </hh:styles></hh:refList></hh:head>'''.encode()


def source(tmp_path: Path, name: str, *, second: bool = False, changes=None) -> Path:
    parts = synthetic_parts(reference_image=png_bytes(output=second))
    parts = [part for part in parts if part[0] != "Extra/unknown.dat"]
    parts = [
        (
            member,
            header("Second" if second else "First") if member.endswith("header.xml") else data,
            method,
        )
        for member, data, method in parts
    ]
    if changes:
        parts = changes(parts)
    return write_hwpx(tmp_path / name, parts)


def replace(parts, member: str, old: bytes, new: bytes):
    return [
        (name, data.replace(old, new) if name == member else data, method)
        for name, data, method in parts
    ]


def test_native_merge_relocates_conflicting_font_style_and_image_ids(tmp_path: Path) -> None:
    first, second = source(tmp_path, "one.hwpx"), source(tmp_path, "two.hwpx", second=True)
    before = (first.read_bytes(), second.read_bytes())
    output, again = tmp_path / "merged.hwpx", tmp_path / "again.hwpx"
    report = merge_native_hwpx((first, second), output)
    assert report.section_source_positions == (1, 2)
    assert report.binary_count == 2
    assert merge_native_hwpx((first, second), again) == report
    assert again.read_bytes() == output.read_bytes()
    assert before == (first.read_bytes(), second.read_bytes())
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist()[0] == "mimetype"
        definitions = catalog_rows(parse_xml(archive.read("Contents/header.xml"), "header").root)
        assert [row.get("face") for row in definitions["font:HANGUL"].values()] == [
            "First",
            "Second",
        ]
        assert definitions["styles"]["2"].get("nextStyleIDRef") == "3"
        assert definitions["styles"]["3"].get("nextStyleIDRef") == "2"
        first_xml, second_xml = [archive.read(f"Contents/section{n}.xml") for n in (0, 1)]
        assert b'charPrIDRef="0"' in first_xml
        assert b'charPrIDRef="2"' in second_xml
        assert b'binaryItemIDRef="curated002Binary0000"' in second_xml
        assert archive.read("BinData/curated-001-0000.png") == png_bytes()
        assert archive.read("BinData/curated-002-0000.png") == png_bytes(output=True)
        # Source tables and equation scripts remain native XML, not full-page pictures.
        assert b"<hp:tbl" in second_xml and b"<hp:equation" in second_xml


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda parts: replace(
                parts, "Contents/section0.xml", b'charPrIDRef="0"', b'charPrIDRef="777"'
            ),
            "resource reference is missing",
        ),
        (
            lambda parts: replace(
                parts,
                "Contents/section0.xml",
                b'binaryItemIDRef="image1"',
                b'binaryItemIDRef="absent"',
            ),
            "binary reference is missing",
        ),
        (
            lambda parts: replace(
                parts, "Contents/section0.xml", b"<hp:pic ", b'<hp:pic strangeIDRef="7" '
            ),
            "unknown curated reference",
        ),
        (
            lambda parts: replace(
                parts, "Contents/section0.xml", b"<hp:pic ", b'<hp:pic idRef="7" '
            ),
            "unknown curated reference",
        ),
        (
            lambda parts: replace(
                parts, "Contents/section0.xml", b"<hp:pic ", b'<hp:pic linkListNextIDRef="7" '
            ),
            "linked text-frame",
        ),
        (
            lambda parts: replace(
                parts, "Contents/section0.xml", b'<hp:pic id="pic1"', b'<hp:pic id="table1"'
            ),
            "repeats a document object",
        ),
        (
            lambda parts: replace(
                parts, "Contents/header.xml", b'charPrIDRef="0"', b'charPrIDRef="777"'
            ),
            "resource reference is missing",
        ),
        (
            lambda parts: replace(
                parts, "Contents/header.xml", b'face="First"', b'face="First" futureIDRef="9"'
            ),
            "unknown curated reference",
        ),
        (
            lambda parts: replace(
                parts,
                "Contents/header.xml",
                b'<hh:font id="0" face="First"/>',
                b'<hh:font id="0"/><hh:font id="0"/>',
            ),
            "resource ID is missing or repeated",
        ),
        (
            lambda parts: replace(
                parts,
                "Contents/content.hpf",
                b'<opf:itemref idref="section0"/>',
                b'<opf:itemref idref="section0"/><opf:itemref idref="section0"/>',
            ),
            "repeats a section",
        ),
        (
            lambda parts: [*parts, ("Scripts/evil.js", b"bad", zipfile.ZIP_STORED)],
            "unsupported part",
        ),
        (
            lambda parts: [*parts, ("BinData/orphan.png", png_bytes(), zipfile.ZIP_STORED)],
            "unlisted binary",
        ),
        (
            lambda parts: [*parts, ("Contents/section9.xml", b"<section/>", zipfile.ZIP_STORED)],
            "unordered sections",
        ),
    ],
)
def test_native_merge_fails_explicitly_without_partial_output(
    tmp_path: Path, change, message: str
) -> None:
    first = source(tmp_path, "source.hwpx", changes=change)
    with pytest.raises(HwpxError, match=message):
        merge_native_hwpx((first,), tmp_path / "not-published.hwpx")
    assert not (tmp_path / "not-published.hwpx").exists()


@pytest.mark.parametrize(
    "member, old, new",
    [
        ("settings.xml", b"<settings ", b'<settings different="true" '),
        ("version.xml", b'owpml="synthetic-poc"', b'owpml="different"'),
        ("Contents/header.xml", b'page="1"', b'page="9"'),
    ],
)
def test_different_global_settings_are_not_silently_discarded(
    tmp_path: Path, member, old, new
) -> None:
    first = source(tmp_path, "one.hwpx")
    second = source(tmp_path, "two.hwpx", changes=lambda parts: replace(parts, member, old, new))
    with pytest.raises(HwpxError, match="differ"):
        merge_native_hwpx((first, second), tmp_path / "not-published.hwpx")


def test_source_extension_does_not_define_its_content_format(tmp_path: Path) -> None:
    native_zip_with_hwp_name = source(tmp_path, "misnamed.hwp")
    assert merge_native_hwpx(
        (native_zip_with_hwp_name,), tmp_path / "output.hwpx"
    ).section_source_positions == (1,)


def test_output_is_never_overwritten_and_symlink_source_is_not_followed(tmp_path: Path) -> None:
    first = source(tmp_path, "one.hwpx")
    linked = tmp_path / "linked.hwpx"
    linked.symlink_to(first)
    with pytest.raises(HwpxError, match="regular local file"):
        merge_native_hwpx((linked,), tmp_path / "unused.hwpx")
    before = first.read_bytes()
    with pytest.raises(HwpxError, match="invalid"):
        merge_native_hwpx((first,), first)
    assert first.read_bytes() == before


def test_resource_verifier_detects_changed_definitions_and_forward_cycles() -> None:
    originals = tuple(parse_xml(header(font), "header").root for font in ("A", "B"))
    merged, plans = merge_resources(originals, ({}, {}), ({}, {}))
    verify_resource_relocation(originals, merged, plans)
    changed = copy.deepcopy(merged)
    catalog_rows(changed)["font:HANGUL"]["1"].set("face", "Wrong font")
    with pytest.raises(HwpxError, match="resource differs"):
        verify_resource_relocation(originals, changed, plans)
    section = parse_xml(b'<section><shape idRef="9"/></section>', "section").root
    with pytest.raises(HwpxError, match="unknown curated reference"):
        relocate_tree(section, plans[0])


def request_value() -> dict:
    return {
        "schema_version": "curated-hwpx-render-request/1.0",
        "build_id": "hwpxbuild_" + "a" * 32,
        "assembly_revision_id": "assemblyrev_" + "b" * 32,
        "assembly_manifest_sha256": "sha256:" + "c" * 64,
        "profile": "NATIVE_EDITABLE_PRESERVATION_V1",
        "segments": [
            {
                "position": 1,
                "local_file": "inputs/001.hwpx",
                "source_format": "HWPX",
                "sha256": "sha256:" + "d" * 64,
                "size_bytes": 10,
            }
        ],
    }


def test_local_request_schema_and_pydantic_agree() -> None:
    value = request_value()
    validate_contract("curated-render-request", value)
    parsed = CuratedHwpxRenderRequest.model_validate(value)
    assert parsed.model_dump(mode="json") == value


@pytest.mark.parametrize(
    "field, value",
    [
        ("position", 2),
        ("local_file", "inputs/001.hwp"),
        ("local_file", "../source.hwpx"),
        ("size_bytes", True),
    ],
)
def test_local_request_rejects_bad_identity_order_paths_and_types(field, value) -> None:
    request = request_value()
    request["segments"][0][field] = value
    with pytest.raises(ValidationError):
        CuratedHwpxRenderRequest.model_validate(request)


def test_schema_bytes_are_mirrored() -> None:
    root = Path(__file__).resolve().parents[2]
    filename = "hwpx-curated-render-v1.schema.json"
    assert (root / "schemas/hwpx" / filename).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / filename
    ).read_bytes()
