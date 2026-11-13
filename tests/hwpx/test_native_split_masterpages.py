"""Master-page intake is opt-in and retains only the source-referenced native closure."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import (
    NativeDocumentReadProfile,
    merge_native_hwpx,
    parse_native_document,
)
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_item_split import NativeItemSplitError, split_native_exam

from tests.hwpx.helpers import png_bytes
from tests.hwpx.test_native_item_split import HP, paragraph, plan_for, section, source

type Parts = list[tuple[str, bytes, int]]


def _source(tmp_path: Path, *, change: Callable[[Parts], Parts] | None = None) -> Path:
    def transform(parts: Parts) -> Parts:
        result = []
        for member, data, method in parts:
            if member == "Contents/content.hpf":
                for number in range(2):
                    data = data.replace(
                        b"</opf:manifest>",
                        (
                            f'<opf:item id="masterpage{number}" href="masterpage{number}.xml" '
                            'media-type="application/xml"/></opf:manifest>'
                        ).encode(),
                    )
            result.append((member, data, method))
        result.extend(
            [
                (
                    "Contents/masterpage0.xml",
                    (
                        f'<masterPage xmlns:hp="{HP}" id="masterpage0" type="EVEN">'
                        '<hp:pic id="masterpic"><hp:img binaryItemIDRef="unused"/>'
                        '<hp:imgRect left="10" right="20"/></hp:pic></masterPage>'
                    ).encode(),
                    zipfile.ZIP_DEFLATED,
                ),
                (
                    "Contents/masterpage1.xml",
                    (
                        f'<masterPage xmlns:hp="{HP}" id="masterpage1" type="ODD">'
                        "<hp:p><hp:run><hp:t>Unselected source page decoration</hp:t>"
                        "</hp:run></hp:p>"
                        "</masterPage>"
                    ).encode(),
                    zipfile.ZIP_DEFLATED,
                ),
            ]
        )
        return change(result) if change else result

    geometry = '<hp:secPr masterPageCnt="1"><hp:masterPage idRef="masterpage0"/></hp:secPr>'
    return source(
        tmp_path,
        sections=(
            section(
                paragraph("전체 제목", inner=geometry)
                + paragraph("1. 첫 문항")
                + paragraph("2. 둘째 문항")
            ),
        ),
        transform=transform,
    )


def test_masterpages_are_split_read_only_capability_not_old_merger_permission(
    tmp_path: Path,
) -> None:
    path = _source(tmp_path)
    package = read_package(path)
    with pytest.raises(HwpxError, match="unsupported part"):
        parse_native_document(package)
    doc = parse_native_document(package, profile=NativeDocumentReadProfile.NATIVE_SPLIT_V1)
    assert len(doc.masterpages) == 2
    with pytest.raises(HwpxError, match="unsupported part"):
        merge_native_hwpx((path,), tmp_path / "merged.hwpx")
    assert not (tmp_path / "merged.hwpx").exists()


def test_split_keeps_masterpage_xml_and_binary_without_copying_unselected_page(
    tmp_path: Path,
) -> None:
    path = _source(tmp_path)
    before = path.read_bytes()
    plan = plan_for(path)
    results = split_native_exam(path, tmp_path / "out", plan=plan)
    assert len(results) == 2
    with zipfile.ZipFile(path) as original:
        master_xml = original.read("Contents/masterpage0.xml")
    for number in (1, 2):
        with zipfile.ZipFile(tmp_path / f"out/{number:03d}.hwpx") as z:
            assert z.read("Contents/masterpage0.xml") == master_xml
            assert z.read("BinData/unused.png") == png_bytes(output=True)
            assert "Contents/masterpage1.xml" not in z.namelist()
            assert "BinData/image1.png" not in z.namelist()
            assert not any(n.startswith("Preview/") for n in z.namelist())
            assert b"masterpage0" in z.read("Contents/content.hpf")
            assert b"masterpage1" not in z.read("Contents/content.hpf")
    assert path.read_bytes() == before
    assert split_native_exam(path, tmp_path / "again", plan=plan) == results


@pytest.mark.parametrize(
    "part,old,new,error",
    [
        (
            "Contents/section0.xml",
            b'idRef="masterpage0"',
            b'idRef="absent"',
            "MASTERPAGE_REFERENCE_MISSING",
        ),
        (
            "Contents/masterpage0.xml",
            b'binaryItemIDRef="unused"',
            b'binaryItemIDRef="absent"',
            "BINARY_REFERENCE_MISSING",
        ),
        (
            "Contents/masterpage0.xml",
            b'<hp:pic id="masterpic"',
            b'<hp:pic strangeIDRef="masterpage0" id="masterpic"',
            "REFERENCE_UNSUPPORTED",
        ),
        (
            "Contents/masterpage0.xml",
            b'<hp:pic id="masterpic"',
            b'<hp:pic href="https://example.invalid/x" id="masterpic"',
            "EXTERNAL_REFERENCE",
        ),
    ],
)
def test_bad_masterpage_references_never_become_blank_or_ignored(
    tmp_path: Path, part: str, old: bytes, new: bytes, error: str
) -> None:
    def change(parts: Parts) -> Parts:
        return [(n, b.replace(old, new) if n == part else b, m) for n, b, m in parts]

    path = _source(tmp_path, change=change)
    with pytest.raises(NativeItemSplitError, match=error):
        plan_for(path)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("case", ["rootid", "manifestid", "unlisted", "arbitrarypart"])
def test_only_exact_manifested_native_masterpage_parts_are_allowed(
    tmp_path: Path, case: str
) -> None:
    def change(parts: Parts) -> Parts:
        result = []
        for n, b, m in parts:
            if case == "rootid" and n == "Contents/masterpage0.xml":
                b = b.replace(b'id="masterpage0"', b'id="wrong"')
            if case == "manifestid" and n == "Contents/content.hpf":
                b = b.replace(b'id="masterpage0"', b'id="other"')
            if case == "unlisted" and n == "Contents/content.hpf":
                import re

                b = re.sub(rb'<opf:item id="masterpage0"[^>]*/>', b"", b)
            result.append((n, b, m))
        if case == "arbitrarypart":
            result.append(("Contents/not-masterpage.xml", b"<unknown/>", zipfile.ZIP_DEFLATED))
        return result

    path = _source(tmp_path, change=change)
    with pytest.raises(HwpxError):
        parse_native_document(read_package(path), profile=NativeDocumentReadProfile.NATIVE_SPLIT_V1)
