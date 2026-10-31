from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.hwp_picture_placement import (
    decode_hwp_picture_placement,
    restore_hwp_picture_placement,
)
from eom_hwpx_builder.util import sha256_bytes
from lxml import etree

from tests.hwpx.helpers import png_bytes, synthetic_parts, write_hwpx

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def common(*, flags: int = 0x042A2210, vertical: int = -126, horizontal: int = -1146) -> bytes:
    return struct.pack(
        "<Iiiiii4HII", flags, vertical, horizontal, 26982, 29059, 8, 0, 2, 3, 4, 99, 0
    )


def candidate(tmp_path: Path, *, changed: bool = False) -> Path:
    picture = b"""<hp:pic xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"
        id="pic1" zOrder="8" textWrap="IN_FRONT_OF_TEXT" textFlow="BOTH_SIDES">
        <hc:img binaryItemIDRef="image1"/><hp:sz width="26982" height="29059"/>
        <hp:pos treatAsChar="0" flowWithText="0" allowOverlap="1" vertRelTo="PARA"
          horzRelTo="PARA" vertOffset="4294967170" horzOffset="4294966150" holdAnchorAndSO="0"/>
        <hp:outMargin left="0" right="0" top="0" bottom="0"/>
        </hp:pic>"""
    parts = synthetic_parts(reference_image=png_bytes(output=changed))
    parts = [
        (
            name,
            data.replace(b'<hp:pic id="pic1" binaryItemIDRef="image1"/>', picture)
            if name == "Contents/section0.xml"
            else data,
            method,
        )
        for name, data, method in parts
    ]
    return write_hwpx(tmp_path / ("changed.hwpx" if changed else "candidate.hwpx"), parts)


def placement():
    return decode_hwp_picture_placement(common(), image_sha256=sha256_bytes(png_bytes()))


def test_decode_preserves_the_source_reserved_space_and_column_anchor():
    result = placement()
    assert result.text_wrap == "TOP_AND_BOTTOM"
    assert result.text_flow == "BOTH_SIDES"
    assert dict(result.position_attributes) == {
        "treatAsChar": "0",
        "affectLSpacing": "0",
        "flowWithText": "1",
        "allowOverlap": "0",
        "vertRelTo": "PARA",
        "horzRelTo": "COLUMN",
        "vertAlign": "TOP",
        "horzAlign": "LEFT",
        "vertOffset": "4294967170",
        "horzOffset": "4294966150",
    }
    assert result.margins == (("left", "0"), ("right", "2"), ("top", "3"), ("bottom", "4"))


@pytest.mark.parametrize(
    "wrap,expected",
    [(0, "SQUARE"), (1, "TOP_AND_BOTTOM"), (2, "BEHIND_TEXT"), (3, "IN_FRONT_OF_TEXT")],
)
def test_not_a_hardcoded_always_top_and_bottom_layout(wrap: int, expected: str):
    flags = (0x042A2210 & ~(7 << 21)) | wrap << 21
    assert (
        decode_hwp_picture_placement(
            common(flags=flags), image_sha256=sha256_bytes(png_bytes())
        ).text_wrap
        == expected
    )


@pytest.mark.parametrize(
    "field", ["truncated", "unknown_wrap", "unknown_anchor", "unknown_alignment", "bad_hash"]
)
def test_untrusted_source_flags_and_hash_fail_explicitly(field: str):
    raw, sha = common(), sha256_bytes(png_bytes())
    if field == "truncated":
        raw = raw[:39]
    elif field == "unknown_wrap":
        raw = common(flags=0x042A2210 | (7 << 21))
    elif field == "unknown_anchor":
        raw = common(flags=0x042A2210 | (3 << 3))
    elif field == "unknown_alignment":
        raw = common(flags=0x042A2210 | (7 << 5))
    else:
        sha = "sha256:" + "z" * 64
    with pytest.raises(HwpxError):
        decode_hwp_picture_placement(raw, image_sha256=sha)


def test_normalization_changes_only_proven_layout_and_retains_editable_content(tmp_path: Path):
    original = candidate(tmp_path)
    original_bytes = original.read_bytes()
    output = tmp_path / "normalized.hwpx"
    receipt = restore_hwp_picture_placement(original, (placement(),), output)
    assert receipt.picture_count == receipt.changed_picture_count == 1
    assert original.read_bytes() == original_bytes
    with zipfile.ZipFile(output) as normalized, zipfile.ZipFile(original) as source:
        assert normalized.namelist()[0] == "mimetype"
        for name in source.namelist():
            if name != "Contents/section0.xml":
                assert source.read(name) == normalized.read(name)
        root = etree.fromstring(normalized.read("Contents/section0.xml"))
        pic = next(root.iter(HP + "pic"))
        assert pic.get("textWrap") == "TOP_AND_BOTTOM"
        assert pic.find(HP + "pos").get("horzRelTo") == "COLUMN"
        assert pic.find(HP + "pos").get("holdAnchorAndSO") == "0"
        assert pic.find(HP + "pos").get("flowWithText") == "1"
        assert b"hp:tbl" in normalized.read("Contents/section0.xml")
        assert b"hp:equation" in normalized.read("Contents/section0.xml")
    again = tmp_path / "again.hwpx"
    assert restore_hwp_picture_placement(output, (placement(),), again).changed_picture_count == 0
    assert output.read_bytes() == again.read_bytes()


def test_a_different_picture_or_missing_picture_is_not_silently_substituted(tmp_path: Path):
    changed = candidate(tmp_path, changed=True)
    with pytest.raises(HwpxError, match="lineage"):
        restore_hwp_picture_placement(changed, (placement(),), tmp_path / "bad.hwpx")
    assert not (tmp_path / "bad.hwpx").exists()
    with pytest.raises(HwpxError, match="count/order"):
        restore_hwp_picture_placement(changed, (), tmp_path / "bad.hwpx")


def test_existing_output_and_symlinks_are_never_replaced(tmp_path: Path):
    original = candidate(tmp_path)
    before = original.read_bytes()
    with pytest.raises(HwpxError, match="boundary"):
        restore_hwp_picture_placement(original, (placement(),), original)
    linked = tmp_path / "link.hwpx"
    linked.symlink_to(original)
    with pytest.raises(HwpxError, match="boundary"):
        restore_hwp_picture_placement(linked, (placement(),), tmp_path / "unused.hwpx")
    assert original.read_bytes() == before
