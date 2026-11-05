"""Replace only the known grouped intent decoration with an editable native cell.

Keep the source inline extent/anchor and paragraph styles. Other source objects
are not flattened, resized or rasterized. Exact replacements support inverse
comparison at the existing HWP conversion boundary.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from eom_hwpx_contracts.native_resource_rules import OBJECTS
from lxml import etree  # type: ignore[import-untyped]

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


@dataclass(frozen=True)
class IntentBoxReplacement:
    path: tuple[int, ...]
    original: etree._Element


def _text(root: etree._Element) -> str:
    return "".join(
        character
        for text in root.iter(HP + "t")
        for character in "".join(text.itertext())
        if not character.isspace()
    )


def _native_cell(group: etree._Element) -> etree._Element | None:
    if group.tag != HP + "container" or group.get("groupLevel") != "0":
        return None
    if group.getparent() is None or group.getparent().tag != HP + "run":
        return None
    size, position, margins = (group.find(HP + name) for name in ("sz", "pos", "outMargin"))
    parent_cell = next(group.iterancestors(HP + "tc"), None)
    if (
        size is None
        or position is None
        or margins is None
        or position.get("treatAsChar") != "1"
        or parent_cell is None
        or not parent_cell.get("borderFillIDRef")
        or any(
            not (
                size.get(axis, "").isascii()
                and size.get(axis, "").isdecimal()
                and 0 < int(size.get(axis, "0")) <= 0xFFFFFFFF
            )
            for axis in ("width", "height")
        )
    ):
        return None
    # The supported decoration contains only rectangles/groups and text. Never
    # consume a figure, equation, native table, link or another active control.
    if any(
        (local := etree.QName(node).localname) == "ctrl"
        or (local in OBJECTS and node.tag not in {HP + "rect", HP + "container"})
        for node in group.iter()
    ):
        return None
    bodies = [
        body
        for rectangle in group.iter(HP + "rect")
        if (body := rectangle.find(f"{HP}drawText/{HP}subList")) is not None and _text(body)
    ]
    if len(bodies) != 2:
        return None
    titles = [index for index, body in enumerate(bodies) if _text(body) == "출제의도"]
    if len(titles) != 1:
        return None
    title, body = bodies[titles[0]], bodies[1 - titles[0]]
    frame = body.getparent()
    inner_margins = frame.find(HP + "textMargin")
    if inner_margins is None or any(
        not inner_margins.get(side, "").isdecimal() for side in ("left", "right", "top", "bottom")
    ):
        return None
    border = parent_cell.get("borderFillIDRef", "")
    table = etree.Element(
        HP + "tbl",
        dict(
            id=group.get("id", "0"),
            zOrder=group.get("zOrder", "0"),
            numberingType="TABLE",
            textWrap="TOP_AND_BOTTOM",
            textFlow="BOTH_SIDES",
            lock="0",
            dropcapstyle="None",
            pageBreak="CELL",
            repeatHeader="0",
            rowCnt="1",
            colCnt="1",
            cellSpacing="0",
            borderFillIDRef=border,
            noAdjust="0",
        ),
    )
    table.tail = group.tail
    table.extend(copy.deepcopy(node) for node in (size, position, margins))
    etree.SubElement(table, HP + "inMargin", dict(inner_margins.attrib))
    row = etree.SubElement(table, HP + "tr")
    cell = etree.SubElement(
        row,
        HP + "tc",
        dict(
            name="",
            header="0",
            hasMargin="1",
            protect="0",
            editable="1",
            dirty="0",
            borderFillIDRef=border,
        ),
    )
    content = etree.SubElement(cell, HP + "subList", dict(body.attrib))
    for source in (title, body):
        for paragraph in source.findall(HP + "p"):
            replacement = copy.deepcopy(paragraph)
            for cache in tuple(replacement.iter(HP + "linesegarray")):
                cache.getparent().remove(cache)
            content.append(replacement)
    etree.SubElement(cell, HP + "cellAddr", dict(colAddr="0", rowAddr="0"))
    etree.SubElement(cell, HP + "cellSpan", dict(colSpan="1", rowSpan="1"))
    etree.SubElement(
        cell, HP + "cellSz", {axis: size.get(axis, "") for axis in ("width", "height")}
    )
    etree.SubElement(cell, HP + "cellMargin", dict(inner_margins.attrib))
    return table


def replace_grouped_intent_boxes(root: etree._Element) -> tuple[IntentBoxReplacement, ...]:
    """Bounded DFS; replacing one child preserves paths of all outside siblings."""
    pending: list[tuple[etree._Element, tuple[int, ...]]] = [(root, ())]
    replacements: list[IntentBoxReplacement] = []
    while pending:
        node, path = pending.pop()
        replacement = _native_cell(node)
        if replacement is not None:
            parent = node.getparent()
            assert parent is not None and path
            parent[path[-1]] = replacement
            replacements.append(IntentBoxReplacement(path, node))
            continue
        pending.extend((child, (*path, index)) for index, child in reversed(tuple(enumerate(node))))
    return tuple(replacements)


def restore_grouped_intent_boxes(
    root: etree._Element, replacements: tuple[IntentBoxReplacement, ...]
) -> None:
    """Restore exact old groups in an inverse copy, never the publication tree."""
    for replacement in replacements:
        parent = root
        for index in replacement.path[:-1]:
            parent = parent[index]
        parent[replacement.path[-1]] = copy.deepcopy(replacement.original)
