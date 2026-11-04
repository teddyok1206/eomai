"""Reflow generated editorial segments in the new curated profile only.

The reviewed legacy renderer and original source documents are unchanged. Its
fixed template's literal number prefix and cached cell geometry are not valid
for a newly numbered mixed assembly. Preserve content and picture geometry;
adjust only generated table/cell dimensions and discard derived line caches.
"""

from __future__ import annotations

import math
import unicodedata
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.curated_package_merge import write_native_package
from eom_hwpx_builder.curated_resources import fail
from eom_hwpx_builder.xmlsafe import parse_xml, serialize_xml

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"


def _required(parent: etree._Element, name: str) -> etree._Element:
    values = parent.findall(HP + name)
    if len(values) != 1:
        fail("curated editorial layout has an ambiguous native child: " + name)
    return values[0]


def _content(root: etree._Element) -> tuple[object, ...]:
    return tuple(
        (
            node.tag,
            tuple(
                sorted(
                    (key, value)
                    for key, value in node.attrib.items()
                    if not (
                        key in {"width", "height"}
                        and (
                            node.tag == HP + "cellSz"
                            or (node.tag == HP + "sz" and node.getparent().tag == HP + "tbl")
                        )
                    )
                )
            ),
            node.text or "",
            node.tail or "",
        )
        for node in root.iter()
    )


def _paragraph_height(paragraph: etree._Element, *, available: int, fonts: dict[str, int]) -> int:
    units = 0.0
    font = 1000
    breaks = 0
    object_height = 0
    for run in paragraph.findall(HP + "run"):
        height = fonts.get(run.get("charPrIDRef", ""), 1000)
        font = max(font, height)
        for child in run:
            if child.tag == HP + "t":
                text = "".join(child.itertext())
                units += sum(
                    height * (1 if unicodedata.east_asian_width(char) in {"W", "F"} else 0.6)
                    for char in text
                )
                breaks += len(child.findall(HP + "lineBreak"))
            elif child.tag in {HP + "tbl", HP + "pic", HP + "equation"}:
                size = _required(child, "sz")
                object_height = max(object_height, int(size.get("height", "0")))
    lines = max(1, math.ceil(units / max(available, 1))) + breaks if units or breaks else 0
    return object_height + math.ceil(font * 1.6) * lines


def reflow_curated_editorial_document(output: Path, *, item_number: int) -> None:
    package = read_package(output)
    entries = package.by_name()
    section = parse_xml(entries["Contents/section0.xml"].data, "Contents/section0.xml")
    header = parse_xml(entries["Contents/header.xml"].data, "Contents/header.xml")
    prefixes = []
    for paragraph in section.root.iter(HP + "p"):
        runs = paragraph.findall(HP + "run")
        if len(runs) < 2:
            continue
        left, right = runs[0].find(HP + "t"), runs[1].find(HP + "t")
        if (
            left is not None
            and right is not None
            and left.text == "1. "
            and (right.text or "").startswith(f"{item_number}. ")
        ):
            prefixes.append((paragraph, runs[0]))
    if len(prefixes) != 1:
        fail("curated editorial stem does not have one reviewed template number prefix")
    prefixes[0][0].remove(prefixes[0][1])
    for cache in tuple(section.root.iter(HP + "linesegarray")):
        cache.getparent().remove(cache)
    before = _content(section.root)
    fonts = {
        str(node.get("id")): int(node.get("height", "1000"))
        for node in header.root.iter(HH + "charPr")
    }
    tables = tuple(section.root.iter(HP + "tbl"))
    # Widths propagate top down so an inner data table fits its actual image/table
    # slot, not the full-width prototype. Do not resize a picture or crop its use.
    for table in tables:
        parent_cell = next(table.iterancestors(HP + "tc"), None)
        if parent_cell is None:
            continue
        parent_size, margin = _required(parent_cell, "cellSz"), _required(parent_cell, "cellMargin")
        available = (
            int(parent_size.get("width", "0"))
            - int(margin.get("left", "0"))
            - int(margin.get("right", "0"))
        )
        size = _required(table, "sz")
        width = int(size.get("width", "0"))
        if available <= 0 or width <= 0:
            fail("curated editorial table has no positive text width")
        if width > available:
            for row in table.findall(HP + "tr"):
                for cell in row.findall(HP + "tc"):
                    cell_size = _required(cell, "cellSz")
                    cell_size.set(
                        "width", str(max(1, int(cell_size.get("width", "0")) * available // width))
                    )
            size.set("width", str(available))
    # Heights propagate bottom up. Row spans are constraints on a shared row grid;
    # counting an entire spanning cell once per row would inflate the whole page.
    for table in reversed(tables):
        rows = table.findall(HP + "tr")
        heights = [0] * len(rows)
        cells = []
        for row in rows:
            for cell in row.findall(HP + "tc"):
                address, span, size = (
                    _required(cell, name) for name in ("cellAddr", "cellSpan", "cellSz")
                )
                margin, body = _required(cell, "cellMargin"), _required(cell, "subList")
                first, count = int(address.get("rowAddr", "-1")), int(span.get("rowSpan", "0"))
                if first < 0 or count < 1 or first + count > len(rows):
                    fail("curated editorial table row span is invalid")
                available = (
                    int(size.get("width", "0"))
                    - int(margin.get("left", "0"))
                    - int(margin.get("right", "0"))
                )
                content_height = sum(
                    _paragraph_height(p, available=available, fonts=fonts)
                    for p in body.findall(HP + "p")
                )
                required = max(
                    int(size.get("height", "0")),
                    content_height + int(margin.get("top", "0")) + int(margin.get("bottom", "0")),
                )
                cells.append((first, count, size, required))
        for first, count, _size, required in sorted(cells, key=lambda cell: cell[1]):
            deficit = required - sum(heights[first : first + count])
            if deficit > 0:
                quotient, remainder = divmod(deficit, count)
                for offset in range(count):
                    heights[first + offset] += quotient + (offset < remainder)
        for first, count, size, _required_height in cells:
            size.set("height", str(sum(heights[first : first + count])))
        _required(table, "sz").set("height", str(sum(heights)))
    if _content(section.root) != before:
        fail("curated editorial reflow changed source content or picture geometry")
    payloads = {name: entry.data for name, entry in entries.items()}
    payloads["Contents/section0.xml"] = serialize_xml(section)
    candidate = output.with_suffix(".layout.hwpx")
    write_native_package(payloads, candidate)
    candidate.replace(output)
