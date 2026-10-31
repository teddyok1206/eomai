"""Preserve HWP picture wrapping instead of imposing a generated-illustration layout.

The fixed converter retains HWP common object bytes in its local IR, but its HWPX
picture writer substitutes SQUARE/IN_FRONT_OF_TEXT and paragraph-relative anchors.
Only the original picture flags may restore those fields; no OCR or pixel rewrite.
This normalization is not acceptance of other converter preservation losses.
"""

from __future__ import annotations

import copy
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_builder.analyzer import analyze_package, resolve_part
from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import write_native_package
from eom_hwpx_builder.curated_resources import attribute, fail, tree_value
from eom_hwpx_builder.models import PackageLimits
from eom_hwpx_builder.util import sha256_bytes, sha256_file
from eom_hwpx_builder.xmlsafe import local_name, parse_xml, serialize_xml

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
WRAPPING = ("SQUARE", "TOP_AND_BOTTOM", "BEHIND_TEXT", "IN_FRONT_OF_TEXT")
TEXT_FLOW = ("BOTH_SIDES", "LEFT_ONLY", "RIGHT_ONLY", "LARGEST_ONLY")
VERTICAL_ANCHOR = ("PAPER", "PAGE", "PARA")
HORIZONTAL_ANCHOR = ("PAPER", "PAGE", "COLUMN", "PARA")
VERTICAL_ALIGN = ("TOP", "CENTER", "BOTTOM", "INSIDE", "OUTSIDE")
HORIZONTAL_ALIGN = ("LEFT", "CENTER", "RIGHT", "INSIDE", "OUTSIDE")


@dataclass(frozen=True)
class HwpPicturePlacement:
    """Small local value, extracted from a hash-pinned HWP by the fixed adapter."""

    image_sha256: str
    width: int
    height: int
    z_order: int
    text_wrap: str
    text_flow: str
    position_attributes: tuple[tuple[str, str], ...]
    margins: tuple[tuple[str, str], ...]


def decode_hwp_picture_placement(common: bytes, *, image_sha256: str) -> HwpPicturePlacement:
    # HWP5 common object properties (Hancom public format, table 70). Do not
    # reconstruct these from the converter's narrowed Picture boolean fields.
    if not 40 <= len(common) <= 65536:
        fail("HWP picture common properties are incomplete")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_sha256) is None:
        fail("HWP picture source hash is invalid")
    flags, vertical, horizontal, width, height, z_order = struct.unpack_from("<Iiiiii", common)
    wrap, vrel, valign = (flags >> 21) & 7, (flags >> 3) & 3, (flags >> 5) & 7
    hrel, halign = (flags >> 8) & 3, (flags >> 10) & 7
    if (
        width <= 0
        or height <= 0
        or z_order < 0
        or wrap >= len(WRAPPING)
        or vrel >= len(VERTICAL_ANCHOR)
        or valign >= len(VERTICAL_ALIGN)
        or halign >= len(HORIZONTAL_ALIGN)
    ):
        fail("HWP picture placement uses unsupported source properties")
    values = (
        ("treatAsChar", str(flags & 1)),
        ("affectLSpacing", str((flags >> 2) & 1)),
        ("flowWithText", str((flags >> 13) & 1)),
        ("allowOverlap", str((flags >> 14) & 1)),
        ("vertRelTo", VERTICAL_ANCHOR[vrel]),
        ("horzRelTo", HORIZONTAL_ANCHOR[hrel]),
        ("vertAlign", VERTICAL_ALIGN[valign]),
        ("horzAlign", HORIZONTAL_ALIGN[halign]),
        # HWPX uses the unsigned decimal representation of signed HWP offsets.
        ("vertOffset", str(vertical & 0xFFFFFFFF)),
        ("horzOffset", str(horizontal & 0xFFFFFFFF)),
    )
    margins = tuple(
        (name, str(value))
        for name, value in zip(
            ("left", "right", "top", "bottom"), struct.unpack_from("<4H", common, 24), strict=True
        )
    )
    return HwpPicturePlacement(
        image_sha256,
        width,
        height,
        z_order,
        WRAPPING[wrap],
        TEXT_FLOW[(flags >> 24) & 3],
        values,
        margins,
    )


@dataclass(frozen=True)
class HwpPicturePlacementReceipt:
    candidate_sha256: str
    output_sha256: str
    picture_count: int
    changed_picture_count: int


def restore_hwp_picture_placement(
    candidate: Path,
    placements: tuple[HwpPicturePlacement, ...],
    output: Path,
) -> HwpPicturePlacementReceipt:
    """Restore only source-proven picture fields in a new package, never the original."""
    if candidate.is_symlink() or output.exists() or output.is_symlink():
        fail("HWP picture normalization file boundary is invalid")
    limits = PackageLimits()
    package = read_package(candidate, limits)
    entries = package.by_name()
    analysis = analyze_package(candidate, limits)
    if analysis.active_content or analysis.external_links or not analysis.sections:
        fail("HWP picture normalization candidate is unsafe")
    if len(placements) > 1000:
        fail("HWP picture normalization count exceeded")
    manifest = parse_xml(entries["Contents/content.hpf"].data, "Contents/content.hpf").root
    media: dict[str, str] = {}
    for node in manifest.iter():
        if local_name(node.tag) != "item":
            continue
        identifier, href = attribute(node, "id"), attribute(node, "href")
        if not identifier or identifier in media or not href:
            fail("HWP picture normalization manifest identity is invalid")
        member = resolve_part("Contents/content.hpf", href)
        if member not in entries:
            fail("HWP picture normalization member is missing")
        media[identifier] = member
    parsed_sections = [
        (member, parse_xml(entries[member].data, member)) for member in analysis.sections
    ]
    roots = [(member, parsed.root) for member, parsed in parsed_sections]
    nodes = tuple(node for _member, root in roots for node in root.iter(HP + "pic"))
    if len(nodes) != len(placements):
        fail("HWP picture count/order differs from the source")
    changed = 0
    image_hashes: dict[str, str] = {}
    for node, expected in zip(nodes, placements, strict=True):
        images = tuple(node.iter(HC + "img"))
        if len(images) != 1:
            fail("HWP source picture has an ambiguous image reference")
        image_member = media.get(attribute(images[0], "binaryItemIDRef") or "")
        if image_member is None:
            fail("HWP source picture byte lineage differs")
        if image_member not in image_hashes:
            image_hashes[image_member] = sha256_bytes(entries[image_member].data)
        if image_hashes[image_member] != expected.image_sha256:
            fail("HWP source picture byte lineage differs")
        size, pos, margin = node.find(HP + "sz"), node.find(HP + "pos"), node.find(HP + "outMargin")
        if (
            size is None
            or pos is None
            or margin is None
            or (
                attribute(size, "width") != str(expected.width)
                or attribute(size, "height") != str(expected.height)
                or attribute(node, "zOrder") != str(expected.z_order)
            )
        ):
            fail("HWP source picture dimensions/z-order differ")
        before = tree_value(node)
        node.set("textWrap", expected.text_wrap)
        node.set("textFlow", expected.text_flow)
        pos.attrib.update(dict(expected.position_attributes))
        margin.attrib.update(dict(expected.margins))
        changed += int(tree_value(node) != before)
    payloads = {entry.info.filename: entry.data for entry in package.entries}
    # Only the section serialization changes; all other members remain byte-identical.
    payloads.update({member: serialize_xml(parsed) for member, parsed in parsed_sections})
    write_native_package(payloads, output)
    try:
        observed = read_package(output, limits).by_name()
        expected_roots = dict(roots)
        if set(observed) != set(entries):
            fail("HWP normalized package members differ")
        for member, entry in entries.items():
            if member in expected_roots:
                root = parse_xml(observed[member].data, member).root
                if tree_value(root) != tree_value(expected_roots[member]):
                    fail("HWP normalized section changed after serialization")
            elif observed[member].data != entry.data:
                fail("HWP normalization changed a non-section member")
        # No hidden changes outside the explicitly restored picture attributes.
        for member, root in roots:
            original = parse_xml(entries[member].data, member).root
            clone = copy.deepcopy(root)
            for before, after in zip(
                original.iter(HP + "pic"), clone.iter(HP + "pic"), strict=True
            ):
                for name in ("textWrap", "textFlow"):
                    if name in before.attrib:
                        after.attrib[name] = before.attrib[name]
                    else:
                        after.attrib.pop(name, None)
                for name in ("pos", "outMargin"):
                    before_child, after_child = before.find(HP + name), after.find(HP + name)
                    assert before_child is not None and after_child is not None
                    restored_names = (
                        tuple(dict(placements[0].position_attributes))
                        if name == "pos"
                        else ("left", "right", "top", "bottom")
                    )
                    for key in restored_names:
                        if key in before_child.attrib:
                            after_child.attrib[key] = before_child.attrib[key]
                        else:
                            after_child.attrib.pop(key, None)
            if tree_value(clone) != tree_value(original):
                fail("HWP normalization modified non-placement content")
    except Exception:
        output.unlink()
        raise
    return HwpPicturePlacementReceipt(
        package.package_sha256, sha256_file(output), len(nodes), changed
    )
