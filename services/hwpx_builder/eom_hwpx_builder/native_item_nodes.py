"""Native paragraph, table, equation and picture XML for variable canonical Items."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from eom_hwpx_contracts.native_item_format import native_item_spans
from lxml import etree  # type: ignore[import-untyped]

from eom_hwpx_builder.content_team_images import native_picture_element
from eom_hwpx_builder.curated_resources import fail

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
WIDTH = 28541


@dataclass(frozen=True)
class NativeItemTextStyle:
    paragraph: str
    style: str
    character: str


class NativeItemNodes:
    """A per-document ID allocator and native element factory, not a workflow owner."""

    def __init__(self, template_section: etree._Element, header: etree._Element) -> None:
        self._next = 2000000000
        markers = {}
        for text in template_section.iter(HP + "t"):
            for marker in ("[[Q_STEM]]", "[[Q_BOTTOM]]", "[[CHOICE_1]]", "[[SOLUTION]]"):
                if marker in (text.text or ""):
                    if marker in markers:
                        fail("native publication template marker is repeated")
                    run = text.getparent()
                    paragraph = run.getparent()
                    values = (
                        paragraph.get("paraPrIDRef"),
                        paragraph.get("styleIDRef"),
                        run.get("charPrIDRef"),
                    )
                    if any(value is None for value in values):
                        fail("native publication template marker style is absent")
                    markers[marker] = NativeItemTextStyle(*(str(value) for value in values))
        if set(markers) != {"[[Q_STEM]]", "[[Q_BOTTOM]]", "[[CHOICE_1]]", "[[SOLUTION]]"}:
            fail("native publication template markers are incomplete")
        self.styles = {
            "stem": markers["[[Q_STEM]]"],
            "body": markers["[[Q_BOTTOM]]"],
            "choice": markers["[[CHOICE_1]]"],
            "solution": markers["[[SOLUTION]]"],
        }
        # Marker paragraphs originally lived inside fixed template cells. Their
        # hanging indents/grid settings are not free-flow paragraph properties.
        # Add local properties instead of modifying the pinned definitions.
        properties = tuple(header.iter(HH + "paraProperties"))
        if len(properties) != 1:
            fail("native publication paragraph property catalog is absent")
        catalog = properties[0]
        by_id = {str(node.get("id")): node for node in catalog}
        next_id = max(int(identifier) for identifier in by_id) + 1
        for role, style in tuple(self.styles.items()):
            original = by_id.get(style.paragraph)
            if original is None:
                fail("native publication paragraph property is absent")
            derived = copy.deepcopy(original)
            derived.set("id", str(next_id))
            derived.set("snapToGrid", "0")
            for align in derived.iter(HH + "align"):
                align.set("horizontal", "LEFT")
                align.set("vertical", "BASELINE")
            for margin in derived.iter(HH + "margin"):
                for value in margin:
                    value.set("value", "0")
            catalog.append(derived)
            self.styles[role] = NativeItemTextStyle(str(next_id), style.style, style.character)
            next_id += 1
        catalog.set("itemCnt", str(len(catalog)))
        characters = {node.get("id"): node for node in header.iter(HH + "charPr")}
        body_character = characters.get(self.styles["body"].character)
        self._line_height = (
            max(2000, math.ceil(int(body_character.get("height", "1150")) * 1.8))
            if body_character is not None
            else 2100
        )
        equation = next(template_section.iter(HP + "equation"), None)
        if equation is None:
            fail("native publication template equation is absent")
        self._equation: etree._Element = equation

    def identity(self, *, span: int = 1) -> int:
        value = self._next
        self._next += span
        return value

    def paragraph(
        self, text: str = "", *, role: str = "body", page_break: bool = False
    ) -> etree._Element:
        style = self.styles[role]
        paragraph = etree.Element(
            HP + "p",
            {
                "id": str(self.identity()),
                "paraPrIDRef": style.paragraph,
                "styleIDRef": style.style,
                "pageBreak": "1" if page_break else "0",
                "columnBreak": "0",
                "merged": "0",
            },
        )
        for span in native_item_spans(text):
            run = etree.SubElement(paragraph, HP + "run", {"charPrIDRef": style.character})
            if span.kind == "equation":
                run.append(self.equation(span.value))
            else:
                text_node = etree.SubElement(run, HP + "t")
                lines = span.value.split("\n")
                text_node.text = lines[0]
                for line in lines[1:]:
                    etree.SubElement(text_node, HP + "lineBreak").tail = line
        if not len(paragraph):
            etree.SubElement(
                etree.SubElement(paragraph, HP + "run", {"charPrIDRef": style.character}), HP + "t"
            )
        return paragraph

    def equation(self, script: str) -> etree._Element:
        node = copy.deepcopy(self._equation)
        node.set("id", str(self.identity()))
        node.set("zOrder", "0")
        source = node.find(HP + "script")
        size = node.find(HP + "sz")
        if source is None or size is None:
            fail("native publication equation prototype is incomplete")
        source.text = script
        # Canonical content has no source geometry. Reserve proportional native
        # space; do not squeeze every expression into the prototype's '(' width.
        fraction = "over" in script
        width = min(WIDTH, max(1000, len(script) * 650))
        height = 4000 if fraction else 2300
        node.set("baseUnit", "1100")
        node.set("baseLine", "60" if fraction else "85")
        size.set("width", str(width))
        size.set("height", str(height))
        return node

    def object_paragraph(self, node: etree._Element) -> etree._Element:
        paragraph = self.paragraph()
        run = paragraph[0]
        for child in tuple(run):
            run.remove(child)
        run.append(node)
        return paragraph

    def picture(self, *, binary_id: str, width_px: int, height_px: int) -> etree._Element:
        original_width, original_height = width_px * 28, height_px * 28
        factor = min(1.0, WIDTH / original_width, 56000 / original_height)
        return native_picture_element(
            binary_id=binary_id,
            object_id=self.identity(span=2),
            original_width=original_width,
            original_height=original_height,
            width=max(1, round(original_width * factor)),
            height=max(1, round(original_height * factor)),
        )

    def table(
        self,
        rows: tuple[tuple[str, ...], ...],
        *,
        header: bool = True,
        box_lines: tuple[str, ...] = (),
    ) -> etree._Element:
        columns = len(rows[0])
        widths = tuple(WIDTH // columns + int(index < WIDTH % columns) for index in range(columns))
        heights = tuple(
            max(
                1700,
                max(
                    (
                        math.ceil(max(1, len(value)) / max(1, (widths[index] - 600) // 1150))
                        * self._line_height
                        + 600
                    )
                    for index, value in enumerate(row)
                ),
            )
            for row in rows
        )
        if box_lines:
            heights = (
                max(
                    1700,
                    sum(max(1, math.ceil(len(line) / 24)) for line in box_lines) * self._line_height
                    + 600,
                ),
            )
        table = etree.Element(
            HP + "tbl",
            {
                "id": str(self.identity()),
                "zOrder": "0",
                "numberingType": "TABLE",
                "textWrap": "TOP_AND_BOTTOM",
                "textFlow": "BOTH_SIDES",
                "lock": "0",
                "dropcapstyle": "None",
                "pageBreak": "CELL",
                "repeatHeader": "1" if header else "0",
                "rowCnt": str(len(rows)),
                "colCnt": str(columns),
                "cellSpacing": "0",
                "borderFillIDRef": "3",
                "noAdjust": "0",
            },
        )
        etree.SubElement(
            table,
            HP + "sz",
            {
                "width": str(WIDTH),
                "height": str(sum(heights)),
                "widthRelTo": "ABSOLUTE",
                "heightRelTo": "ABSOLUTE",
                "protect": "0",
            },
        )
        etree.SubElement(
            table,
            HP + "pos",
            {
                "treatAsChar": "1",
                "affectLSpacing": "1",
                "flowWithText": "1",
                "allowOverlap": "0",
                "holdAnchorAndSO": "0",
                "vertRelTo": "PARA",
                "horzRelTo": "PARA",
                "vertAlign": "TOP",
                "horzAlign": "LEFT",
                "vertOffset": "0",
                "horzOffset": "0",
            },
        )
        etree.SubElement(
            table, HP + "outMargin", {"left": "0", "right": "0", "top": "300", "bottom": "300"}
        )
        etree.SubElement(
            table, HP + "inMargin", {"left": "300", "right": "300", "top": "150", "bottom": "150"}
        )
        for row_index, row in enumerate(rows):
            tr = etree.SubElement(table, HP + "tr")
            for col_index, text in enumerate(row):
                cell = etree.SubElement(
                    tr,
                    HP + "tc",
                    {
                        "name": "",
                        "header": "1" if header and row_index == 0 else "0",
                        "hasMargin": "1",
                        "protect": "0",
                        "editable": "1",
                        "dirty": "0",
                        "borderFillIDRef": "3",
                    },
                )
                body = etree.SubElement(
                    cell,
                    HP + "subList",
                    {
                        "id": "",
                        "textDirection": "HORIZONTAL",
                        "lineWrap": "BREAK",
                        "vertAlign": "CENTER",
                        "linkListIDRef": "0",
                        "linkListNextIDRef": "0",
                        "textWidth": "0",
                        "textHeight": "0",
                        "hasTextRef": "0",
                        "hasNumRef": "0",
                    },
                )
                for line in box_lines or (text,):
                    body.append(self.paragraph(line, role="body"))
                etree.SubElement(
                    cell, HP + "cellAddr", {"colAddr": str(col_index), "rowAddr": str(row_index)}
                )
                etree.SubElement(cell, HP + "cellSpan", {"colSpan": "1", "rowSpan": "1"})
                etree.SubElement(
                    cell,
                    HP + "cellSz",
                    {"width": str(widths[col_index]), "height": str(heights[row_index])},
                )
                etree.SubElement(
                    cell,
                    HP + "cellMargin",
                    {"left": "300", "right": "300", "top": "150", "bottom": "150"},
                )
        return table
