from __future__ import annotations

import copy
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from eom_hwpx_builder.curated_resources import tree_value
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.hwp_conversion_package import normalize_hwp_conversion_package
from eom_hwpx_builder.util import sha256_file
from eom_hwpx_builder.xmlsafe import parse_xml

from tests.hwpx.helpers import synthetic_parts, write_hwpx
from tests.hwpx.test_curated_native_merge import header

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


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


def intent_group(*, label="출제 의도", grouped=True):
    body = f"""<hp:rect id="0" instid="100" groupLevel="2">
      <hp:orgSz width="23550" height="8000"/><hp:curSz width="22743" height="8000"/>
      <hp:drawText lastWidth="29418"><hp:subList>
        <hp:p id="0"><hp:run charPrIDRef="0"><hp:t>보존할 출제 의도 본문입니다.</hp:t></hp:run>
          <hp:linesegarray>
            <hp:lineseg textpos="0" horzpos="500" horzsize="27852"/></hp:linesegarray>
        </hp:p>
        <hp:p id="1"><hp:run charPrIDRef="0"><hp:t>둘째 문단입니다.</hp:t></hp:run>
          <hp:linesegarray>
            <hp:lineseg textpos="0" horzpos="500" horzsize="27852"/></hp:linesegarray>
        </hp:p>
      </hp:subList><hp:textMargin left="283" right="283" top="283" bottom="283"/></hp:drawText>
    </hp:rect>
    <hp:rect id="0" instid="101" groupLevel="2"><hp:drawText><hp:subList>
      <hp:p id="2"><hp:run charPrIDRef="0"><hp:t>{label}</hp:t></hp:run>
        <hp:linesegarray><hp:lineseg textpos="0" horzsize="5924"/></hp:linesegarray>
      </hp:p>
    </hp:subList></hp:drawText></hp:rect>"""
    if not grouped:
        return body.encode()
    group = (
        '<hp:container id="200" groupLevel="0">'
        '<hp:container id="0" groupLevel="1">'
        + body
        + '<hp:rect id="0" instid="102" groupLevel="2">'
        '<hp:orgSz width="891" height="5567"/>'
        '<hp:curSz width="860" height="5567"/></hp:rect></hp:container>'
        '<hp:sz width="30244" height="10603" widthRelTo="ABSOLUTE" '
        'heightRelTo="ABSOLUTE" protect="0"/>'
        '<hp:pos treatAsChar="1" vertRelTo="PAPER" horzRelTo="PAPER" '
        'vertOffset="34467" horzOffset="49425"/>'
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        "</hp:container>"
    ).encode()
    return (
        b'<hp:p><hp:run><hp:tbl id="201" rowCnt="1" colCnt="1">'
        b'<hp:tr><hp:tc borderFillIDRef="1"><hp:subList><hp:p><hp:run>'
        + group
        + b"</hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
    )


def with_intent_group(tmp_path, *, label="출제 의도", grouped=True):
    original = candidate(tmp_path)
    with ZipFile(original) as archive:
        parts = [(row.filename, archive.read(row), row.compress_type) for row in archive.infolist()]
    return write_hwpx(
        tmp_path / "intent-source.hwpx",
        [
            (
                name,
                data.replace(
                    b"</hp:section>",
                    intent_group(label=label, grouped=grouped) + b"</hp:section>",
                )
                if name == "Contents/section0.xml"
                else data,
                method,
            )
            for name, data, method in parts
        ],
    )


def test_only_grouped_intent_decoration_is_replaced_with_an_editable_native_cell(tmp_path):
    source = with_intent_group(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "intent-normalized.hwpx"
    receipt = normalize_hwp_conversion_package(source, output)
    assert receipt.rebuilt_intent_box_count == 1
    with ZipFile(source) as original, ZipFile(output) as normalized:
        source_root = parse_xml(original.read("Contents/section0.xml"), "source").root
        result_root = parse_xml(normalized.read("Contents/section0.xml"), "result").root
        source_group = source_root.find(f".//{HP}container[@id='200']")
        result_table = result_root.find(f".//{HP}tbl[@id='200']")
        assert result_table is not None
        assert not tuple(result_table.iter(HP + "container"))
        assert not tuple(result_table.iter(HP + "drawText"))
        assert not tuple(result_table.iter(HP + "linesegarray"))
        assert result_table.find(f"{HP}tr/{HP}tc").get("editable") == "1"
        for name in ("sz", "pos", "outMargin"):
            assert tree_value(source_group.find(HP + name)) == tree_value(
                result_table.find(HP + name)
            )
        source_body, source_label = source_group.findall(f".//{HP}drawText/{HP}subList")
        actual = result_table.findall(f"{HP}tr/{HP}tc/{HP}subList/{HP}p")
        expected = [*source_label.findall(HP + "p"), *source_body.findall(HP + "p")]
        assert len(actual) == len(expected) == 3
        for left, right in zip(expected, actual, strict=True):
            left = copy.deepcopy(left)
            for cache in tuple(left.iter(HP + "linesegarray")):
                cache.getparent().remove(cache)
            assert tree_value(left) == tree_value(right)
        # Replace only the known decoration back: every outside text,
        # equation, style reference, table, geometry and image is unchanged.
        restored = copy.deepcopy(result_root)
        restored_table = restored.find(f".//{HP}tbl[@id='200']")
        restored_table.getparent().replace(restored_table, copy.deepcopy(source_group))
        assert tree_value(restored) == tree_value(source_root)
        for name in original.namelist():
            if name not in {"Contents/header.xml", "Contents/section0.xml"}:
                assert normalized.read(name) == original.read(name)
    assert source.read_bytes() == before
    again = tmp_path / "intent-again.hwpx"
    assert normalize_hwp_conversion_package(output, again).rebuilt_intent_box_count == 0
    assert again.read_bytes() == output.read_bytes()


@pytest.mark.parametrize(
    "label,grouped", [("팀장 출제 의도", True), ("풀이 및 정답 해설", True), ("출제 의도", False)]
)
def test_other_text_boxes_and_ungrouped_rectangles_are_untouched(tmp_path, label, grouped):
    source = with_intent_group(tmp_path, label=label, grouped=grouped)
    output = tmp_path / "other-normalized.hwpx"
    receipt = normalize_hwp_conversion_package(source, output)
    assert receipt.rebuilt_intent_box_count == 0
    with ZipFile(source) as original, ZipFile(output) as normalized:
        assert normalized.read("Contents/section0.xml") == original.read("Contents/section0.xml")


@pytest.mark.parametrize("other_object", [b"<hp:pic/>", b"<hp:equation/>", b"<hp:ellipse/>"])
def test_intent_decoration_with_nontext_objects_is_not_rebuilt(tmp_path, other_object):
    source = with_intent_group(tmp_path)
    with ZipFile(source) as archive:
        parts = [(row.filename, archive.read(row), row.compress_type) for row in archive.infolist()]
    source = write_hwpx(
        tmp_path / "other-object.hwpx",
        [
            (
                name,
                data.replace(b"</hp:container>", other_object + b"</hp:container>", 1)
                if name == "Contents/section0.xml"
                else data,
                method,
            )
            for name, data, method in parts
        ],
    )
    output = tmp_path / "untouched.hwpx"
    assert normalize_hwp_conversion_package(source, output).rebuilt_intent_box_count == 0
    with ZipFile(source) as old, ZipFile(output) as new:
        assert old.read("Contents/section0.xml") == new.read("Contents/section0.xml")
