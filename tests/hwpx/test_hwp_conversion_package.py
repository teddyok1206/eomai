from __future__ import annotations

from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.hwp_conversion_package import normalize_hwp_conversion_package
from eom_hwpx_builder.util import sha256_file
from eom_hwpx_builder.xmlsafe import parse_xml

from tests.hwpx.helpers import synthetic_parts, write_hwpx
from tests.hwpx.test_curated_native_merge import header

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def candidate(tmp_path, *, bad_header=None):
    definition = header().replace(
        b"urn:synthetic:header", b"http://www.hancom.co.kr/hwpml/2011/head"
    )
    if bad_header:
        definition = bad_header(definition)
    parts = [
        (
            name,
            definition if name == "Contents/header.xml" else data,
            ZIP_DEFLATED if name == "mimetype" else method,
        )
        for name, data, method in synthetic_parts()
        if name not in {"Preview/PrvText.txt", "Extra/unknown.dat"}
    ]
    return write_hwpx(tmp_path / "candidate.hwpx", parts)


def test_normalization_restores_only_empty_attributes_and_native_container_metadata(tmp_path):
    source = candidate(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "normalized.hwpx"
    receipt = normalize_hwp_conversion_package(source, output)
    assert receipt.candidate_sha256 == sha256_file(source)
    assert receipt.output_sha256 == sha256_file(output)
    assert receipt.empty_style_attribute_count == 2
    with ZipFile(source) as original, ZipFile(output) as normalized:
        assert normalized.infolist()[0].filename == "mimetype"
        assert normalized.infolist()[0].compress_type == ZIP_STORED
        assert "Preview/PrvText.txt" in normalized.namelist()
        assert normalized.read("Preview/PrvText.txt")
        for name in original.namelist():
            if name != "Contents/header.xml":
                assert normalized.read(name) == original.read(name)
        root = parse_xml(normalized.read("Contents/header.xml"), "header").root
        assert [node.get("engName") for node in root.iter(HH + "style")] == ["", ""]
        assert b"<hp:equation" in normalized.read("Contents/section0.xml")
        assert b"<hp:tbl" in normalized.read("Contents/section0.xml")
    assert source.read_bytes() == before
    again = tmp_path / "again.hwpx"
    assert normalize_hwp_conversion_package(output, again).empty_style_attribute_count == 0
    assert again.read_bytes() == output.read_bytes()


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.replace(b'<hh:style id="1"', b'<hh:style id="0"'),
        lambda data: data.replace(b'<hh:style id="0"', b"<hh:style"),
        lambda data: b'<!DOCTYPE head [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + data,
    ],
)
def test_invalid_header_is_not_repaired_into_an_admitted_document(tmp_path, change):
    source = candidate(tmp_path, bad_header=change)
    with pytest.raises(HwpxError):
        normalize_hwp_conversion_package(source, tmp_path / "bad.hwpx")
    assert not (tmp_path / "bad.hwpx").exists()


def test_symlinks_and_preexisting_outputs_remain_unchanged(tmp_path):
    source = candidate(tmp_path)
    link = tmp_path / "link.hwpx"
    link.symlink_to(source)
    with pytest.raises(HwpxError, match="boundary"):
        normalize_hwp_conversion_package(link, tmp_path / "out.hwpx")
    before = source.read_bytes()
    with pytest.raises(HwpxError, match="boundary"):
        normalize_hwp_conversion_package(source, source)
    assert source.read_bytes() == before


def test_zero_current_size_is_expanded_only_from_the_exact_original_axis(tmp_path):
    source = candidate(tmp_path)
    with ZipFile(source) as archive:
        parts = [(row.filename, archive.read(row), row.compress_type) for row in archive.infolist()]
    old = source.read_bytes()
    shapes = b"""<hp:container id="0"><hp:orgSz width="23550" height="8000"/>
      <hp:curSz width="22743" height="0"/><hp:rect id="0">
      <hp:orgSz width="7239" height="2117"/><hp:curSz width="0" height="0"/>
      </hp:rect></hp:container>"""
    changed = write_hwpx(
        tmp_path / "grouped.hwpx",
        [
            (
                name,
                data.replace(b"</hp:section>", shapes + b"</hp:section>")
                if name == "Contents/section0.xml"
                else data,
                method,
            )
            for name, data, method in parts
        ],
    )
    output = tmp_path / "grouped-normalized.hwpx"
    receipt = normalize_hwp_conversion_package(changed, output)
    assert receipt.expanded_size_attribute_count == 3
    with ZipFile(output) as archive:
        root = parse_xml(archive.read("Contents/section0.xml"), "section").root
        sizes = tuple(root.iter("{http://www.hancom.co.kr/hwpml/2011/paragraph}curSz"))
        assert [(row.get("width"), row.get("height")) for row in sizes] == [
            ("22743", "8000"),
            ("7239", "2117"),
        ]
    assert source.read_bytes() == old
    assert (
        normalize_hwp_conversion_package(
            output, tmp_path / "again.hwpx"
        ).expanded_size_attribute_count
        == 0
    )
