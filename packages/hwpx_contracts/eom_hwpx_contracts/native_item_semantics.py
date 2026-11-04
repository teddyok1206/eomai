"""Pure native Item content/order checks; accepts bounded XML bytes, never storage paths."""

from __future__ import annotations

from collections.abc import Mapping
from xml.etree import ElementTree as ET

from eom_hwpx_contracts.native_item import (
    NativeItemEquation,
    NativeItemImage,
    NativeItemRenderRequest,
    NativeItemStatements,
    NativeItemTable,
)
from eom_hwpx_contracts.native_item_format import (
    NativeItemText,
    native_item_equation_script,
    native_item_publication_elements,
    native_item_spans,
)

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
type NativeItemEvent = tuple[str, str]


def _paragraph(text: str) -> list[NativeItemEvent]:
    return [("p", ""), *((span.kind, span.value) for span in native_item_spans(text)), ("/p", "")]


def expected_native_item_events(request: NativeItemRenderRequest) -> tuple[NativeItemEvent, ...]:
    result = _paragraph("")
    for element in native_item_publication_elements(request):
        if isinstance(element, NativeItemText):
            result.extend(_paragraph(element.text))
        elif isinstance(element, NativeItemEquation):
            result.extend(
                (("p", ""), ("equation", native_item_equation_script(element)), ("/p", ""))
            )
        elif isinstance(element, NativeItemImage):
            result.extend(
                (
                    ("p", ""),
                    ("image", f"{element.sha256},{element.width_px * 28},{element.height_px * 28}"),
                    ("/p", ""),
                )
            )
        elif isinstance(element, NativeItemTable):
            if element.caption:
                result.extend(_paragraph(element.caption))
            rows = (element.headers, *element.rows)
            result.extend((("p", ""), ("table", f"{len(rows)},{len(element.headers)}")))
            for row_index, row in enumerate(rows):
                for col_index, value in enumerate(row):
                    result.append(("cell", f"{col_index},{row_index},1,1"))
                    result.extend(_paragraph(value))
                    result.append(("/cell", ""))
            result.extend((("/table", ""), ("/p", "")))
        elif isinstance(element, NativeItemStatements):
            result.extend(_paragraph("<보기>"))
            result.extend((("p", ""), ("table", "1,1"), ("cell", "0,0,1,1")))
            for statement in element.statements:
                result.extend(_paragraph(f"{statement.label}. {statement.text}"))
            result.extend((("/cell", ""), ("/table", ""), ("/p", "")))
    return tuple(result)


def native_item_section_events(
    section_xml: bytes, binaries: Mapping[str, str]
) -> tuple[NativeItemEvent, ...]:
    """Read generated native content independently of the lxml element factory."""
    if len(section_xml) > 16 * 1024 * 1024 or any(
        token in section_xml.upper() for token in (b"<!DOCTYPE", b"<!ENTITY")
    ):
        raise ValueError("native Item XML exceeds the safe grammar")
    # Generated sections are UTF-8. Reject UTF-16/NUL spellings before stdlib
    # parsing so they cannot hide a DTD from the byte-level guard above.
    if b"\x00" in section_xml:
        raise ValueError("native Item XML is not UTF-8")
    section_xml.decode("utf-8", errors="strict")
    root = ET.fromstring(section_xml)
    if root.tag != "{http://www.hancom.co.kr/hwpml/2011/section}sec":
        raise ValueError("native Item section root differs")
    result: list[NativeItemEvent] = []

    def paragraph(node: ET.Element, depth: int = 0) -> None:
        if depth > 32 or len(result) > 200000:
            raise ValueError("native Item XML nesting/event limit exceeded")
        result.append(("p", ""))
        for run in node:
            if run.tag != HP + "run":
                raise ValueError("native Item has an unexpected paragraph control")
            for child in run:
                if child.tag == HP + "t":
                    text = child.text or ""
                    for mark in child:
                        if mark.tag != HP + "lineBreak" or len(mark) or mark.text:
                            raise ValueError("native Item has an unexpected text control")
                        text += "\n" + (mark.tail or "")
                    if text:
                        result.append(("text", text))
                elif child.tag == HP + "equation":
                    scripts = child.findall(HP + "script")
                    if len(scripts) != 1 or len(scripts[0]):
                        raise ValueError("native Item equation script is invalid")
                    result.append(("equation", scripts[0].text or ""))
                elif child.tag == HP + "pic":
                    images = tuple(child.iter(HC + "img"))
                    size, clip = child.find(HP + "orgSz"), child.find(HP + "imgClip")
                    flip, rotation = child.find(HP + "flip"), child.find(HP + "rotationInfo")
                    if (
                        len(images) != 1
                        or size is None
                        or clip is None
                        or flip is None
                        or rotation is None
                    ):
                        raise ValueError("native Item picture geometry is incomplete")
                    width, height = int(size.get("width", "0")), int(size.get("height", "0"))
                    if (
                        width <= 0
                        or height <= 0
                        or tuple(int(clip.get(k, "-1")) for k in ("left", "top", "right", "bottom"))
                        != (0, 0, width, height)
                        or flip.get("horizontal") != "0"
                        or flip.get("vertical") != "0"
                        or rotation.get("angle") != "0"
                    ):
                        raise ValueError("native Item picture is cropped or transformed")
                    binary_id = images[0].get("binaryItemIDRef", "")
                    if binary_id not in binaries:
                        raise ValueError("native Item picture member is absent")
                    result.append(("image", f"{binaries[binary_id]},{width},{height}"))
                elif child.tag == HP + "tbl":
                    rows, columns = int(child.get("rowCnt", "0")), int(child.get("colCnt", "0"))
                    tr_rows = child.findall(HP + "tr")
                    if rows <= 0 or columns <= 0 or len(tr_rows) != rows:
                        raise ValueError("native Item table dimensions differ")
                    result.append(("table", f"{rows},{columns}"))
                    for row_index, tr in enumerate(tr_rows):
                        cells = tr.findall(HP + "tc")
                        if len(cells) != columns:
                            raise ValueError("native Item table cells differ")
                        for col_index, cell in enumerate(cells):
                            address, span, body = (
                                cell.find(HP + "cellAddr"),
                                cell.find(HP + "cellSpan"),
                                cell.find(HP + "subList"),
                            )
                            if address is None or span is None or body is None:
                                raise ValueError("native Item cell identity is absent")
                            actual = (
                                address.get("colAddr"),
                                address.get("rowAddr"),
                                span.get("colSpan"),
                                span.get("rowSpan"),
                            )
                            if actual != (str(col_index), str(row_index), "1", "1"):
                                raise ValueError("native Item cell address/span differs")
                            result.append(("cell", ",".join(str(v) for v in actual)))
                            for inner in body:
                                if inner.tag != HP + "p":
                                    raise ValueError("native Item cell contains a non-paragraph")
                                paragraph(inner, depth + 1)
                            result.append(("/cell", ""))
                    result.append(("/table", ""))
                elif child.tag == HP + "secPr":
                    if len(result) != 1:
                        raise ValueError("native Item section properties are misplaced")
                elif child.tag == HP + "ctrl":
                    if len(result) != 1 or len(child) != 1 or child[0].tag != HP + "colPr":
                        raise ValueError("native Item contains an unexpected control")
                else:
                    raise ValueError("native Item contains an unexpected visible object")
        result.append(("/p", ""))

    for child in root:
        if child.tag != HP + "p":
            raise ValueError("native Item section contains a non-paragraph")
        paragraph(child)
    return tuple(result)
