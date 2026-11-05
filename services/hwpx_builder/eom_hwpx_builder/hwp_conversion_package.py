"""Package normalization for the pinned optional hwp2hwpx converter.

The pinned writer omits empty style names, uses streaming ZIP descriptors and
writes zero current dimensions when the source current size equals its original
size. Expand those representations without guessing new geometry or content.
Invalidate only the known grouped intent body's HWP-derived line-layout cache;
Hancom must calculate text lines against the converted shape coordinates.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import write_native_package
from eom_hwpx_builder.curated_resources import tree_value
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.util import sha256_file
from eom_hwpx_builder.xmlsafe import parse_xml, serialize_xml

HEADER = "Contents/header.xml"
PREVIEW = "Preview/PrvText.txt"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


@dataclass(frozen=True)
class HwpConversionPackageReceipt:
    candidate_sha256: str
    output_sha256: str
    empty_style_attribute_count: int
    expanded_size_attribute_count: int
    invalidated_intent_line_cache_count: int = 0


def _invalidate_intent_line_caches(
    root: etree._Element,
) -> list[tuple[int, int, etree._Element]]:
    """Recognize the title/body intent group, not other tables/text boxes.

    The source's cached HWP lines can be wider than the converted shape's text
    area. They are derived layout, not text or geometry. Keep the title cache
    and every other paragraph intact; retain exact removals for inverse proof.
    """
    paragraph_ordinals = {node: index for index, node in enumerate(root.iter(HP + "p"))}
    removed = []
    for group in root.iter(HP + "container"):
        bodies = [
            body
            for rectangle in group.findall(HP + "rect")
            if (body := rectangle.find(f"{HP}drawText/{HP}subList")) is not None
            and any("".join(node.itertext()).strip() for node in body.iter(HP + "t"))
        ]
        if len(bodies) != 2:
            continue
        labels = [
            "".join(
                char
                for text in body.iter(HP + "t")
                for char in "".join(text.itertext())
                if not char.isspace()
            )
            for body in bodies
        ]
        if labels.count("출제의도") != 1:
            continue
        body = bodies[1 - labels.index("출제의도")]
        for paragraph in body.findall(HP + "p"):
            for index, child in enumerate(tuple(paragraph)):
                if child.tag == HP + "linesegarray":
                    removed.append((paragraph_ordinals[paragraph], index, child))
                    paragraph.remove(child)
    return removed


def normalize_hwp_conversion_package(candidate: Path, output: Path) -> HwpConversionPackageReceipt:
    """Normalize one local candidate into a fresh package; never overwrite a source."""
    if candidate.is_symlink() or output.exists() or output.is_symlink():
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "conversion package boundary is invalid"
        )
    package = read_package(candidate)
    entries = package.by_name()
    if (
        HEADER not in entries
        or entries.get("mimetype") is None
        or (entries["mimetype"].data != b"application/hwp+zip")
    ):
        raise HwpxError(HwpxErrorCode.HWPX_ZIP_INVALID, "conversion header/mimetype is missing")
    header = parse_xml(entries[HEADER].data, HEADER)
    original = copy.deepcopy(header.root)
    restored: list[tuple[str, str]] = []
    styles = tuple(header.root.iter(HH + "style"))
    by_id = {row.get("id"): row for row in styles}
    if None in by_id or len(by_id) != len(styles) or not styles:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "conversion style IDs are invalid"
        )
    for style in styles:
        for name in ("name", "engName"):
            if name not in style.attrib:
                # The pinned upstream ForStyles copies both source strings.
                # Its writer suppresses only null/empty attributes. This is an
                # empty source value, never a guessed translated style name.
                style.set(name, "")
                restored.append((style.get("id"), name))
    payloads = {name: entry.data for name, entry in entries.items()}
    payloads[HEADER] = serialize_xml(header)
    expanded = 0
    invalidated = 0
    preview: list[str] = []
    for member, entry in entries.items():
        if not (member.startswith("Contents/section") and member.endswith(".xml")):
            continue
        section = parse_xml(entry.data, member)
        original_section = copy.deepcopy(section.root)
        restored_sizes = []
        # ForShapeComponent.curSz emits zero iff current == original on that
        # axis. Some importers treat it literally and collapse grouped text.
        # The source-proven original dimension is the exact equivalent value.
        for ordinal, size in enumerate(section.root.iter(HP + "curSz")):
            parent = size.getparent()
            original_size = None if parent is None else parent.find(HP + "orgSz")
            if original_size is None:
                continue
            for axis in ("width", "height"):
                if size.get(axis) == "0":
                    value = original_size.get(axis, "")
                    if value.isascii() and value.isdecimal() and 0 < int(value) <= 0xFFFFFFFF:
                        size.set(axis, value)
                        restored_sizes.append((ordinal, axis))
        removed_caches = _invalidate_intent_line_caches(section.root)
        inverse = copy.deepcopy(section.root)
        inverse_sizes = tuple(inverse.iter(HP + "curSz"))
        for ordinal, axis in restored_sizes:
            inverse_sizes[ordinal].set(axis, "0")
        inverse_paragraphs = tuple(inverse.iter(HP + "p"))
        for ordinal, index, cache in removed_caches:
            inverse_paragraphs[ordinal].insert(index, copy.deepcopy(cache))
        if tree_value(inverse) != tree_value(original_section):
            raise HwpxError(
                HwpxErrorCode.HWPX_SEMANTIC_MISMATCH,
                "conversion changed unrelated document content",
            )
        if restored_sizes or removed_caches:
            payloads[member] = serialize_xml(section)
        expanded += len(restored_sizes)
        invalidated += len(removed_caches)
        preview.extend("".join(node.itertext()) for node in section.root.iter(HP + "t"))
    if PREVIEW not in payloads:
        # A generated package preview, not another canonical Item/solution.
        # The converter's container declares this member even when it omits it.
        payloads[PREVIEW] = "\r\n".join(preview).encode("utf-8")
    # Invert the representation-only changes before publication.
    restored_root = copy.deepcopy(header.root)
    restored_styles = {node.get("id"): node for node in restored_root.iter(HH + "style")}
    for identifier, name in restored:
        del restored_styles[identifier].attrib[name]
    if tree_value(restored_root) != tree_value(original):
        raise HwpxError(HwpxErrorCode.HWPX_SEMANTIC_MISMATCH, "conversion changed header resources")
    write_native_package(payloads, output)
    try:
        observed = read_package(output).by_name()
        if set(observed) != set(payloads) or any(
            observed[name].data != data for name, data in payloads.items()
        ):
            raise HwpxError(
                HwpxErrorCode.HWPX_SEMANTIC_MISMATCH, "conversion normalization changed members"
            )
    except Exception:
        output.unlink()
        raise
    return HwpConversionPackageReceipt(
        package.package_sha256, sha256_file(output), len(restored), expanded, invalidated
    )
