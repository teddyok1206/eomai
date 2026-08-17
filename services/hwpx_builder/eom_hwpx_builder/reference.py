"""Prepare the fixed content-team HWPX profile as an EOM marker reference."""

from __future__ import annotations

import io
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-untyped]
from PIL import Image

from eom_hwpx_builder.archive import SafePackage, read_package
from eom_hwpx_builder.bindings import TEXT_MARKERS
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.util import sha256_bytes
from eom_hwpx_builder.xmlsafe import ParsedXml, local_name, parse_xml, serialize_xml

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"
OPF_NS = "http://www.idpf.org/2007/opf/"
HP = f"{{{HP_NS}}}"
HC = f"{{{HC_NS}}}"
OPF = f"{{{OPF_NS}}}"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
REFERENCE_IMAGE_PART = "BinData/eom-placeholder-image-reference.png"
REFERENCE_IMAGE_ID = "eomReferenceImage"


def _shape(table: etree._Element) -> tuple[int, int]:
    try:
        rows = int(table.attrib.get("rowCnt", table.attrib.get("rows", "")))
        columns = int(table.attrib.get("colCnt", table.attrib.get("cols", "")))
    except ValueError as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "template table shape is invalid"
        ) from exc
    return rows, columns


def _tables(root: etree._Element, shape: tuple[int, int]) -> list[etree._Element]:
    return [
        element
        for element in root.iter()
        if local_name(element.tag) == "tbl" and _shape(element) == shape
    ]


def _unique_table(root: etree._Element, shape: tuple[int, int]) -> etree._Element:
    matches = _tables(root, shape)
    if len(matches) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED,
            f"content-team template requires one {shape[0]}x{shape[1]} table",
        )
    return matches[0]


def _direct_cells(table: etree._Element) -> list[etree._Element]:
    cells: list[etree._Element] = []
    for element in table.iter():
        if local_name(element.tag) not in {"tc", "cell"}:
            continue
        nearest_table = next(
            (ancestor for ancestor in element.iterancestors() if local_name(ancestor.tag) == "tbl"),
            None,
        )
        if nearest_table is table:
            cells.append(element)
    return cells


def _child(element: etree._Element, child_name: str) -> etree._Element | None:
    return next(
        (child for child in element if local_name(child.tag) == child_name),
        None,
    )


def _cell_address(cell: etree._Element) -> tuple[int, int]:
    address = _child(cell, "cellAddr")
    if address is None:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "table cell address missing")
    try:
        return int(address.attrib["rowAddr"]), int(address.attrib["colAddr"])
    except (KeyError, ValueError) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "table cell address invalid"
        ) from exc


def _cell_map(table: etree._Element) -> dict[tuple[int, int], etree._Element]:
    return {_cell_address(cell): cell for cell in _direct_cells(table)}


def _clone_text_paragraph(template: etree._Element, text: str) -> etree._Element:
    paragraph = deepcopy(template)
    paragraph.attrib.update({"pageBreak": "0", "columnBreak": "0", "merged": "0"})
    run_template = next(
        (element for element in template.iter() if local_name(element.tag) == "run"),
        None,
    )
    run_attributes = dict(run_template.attrib) if run_template is not None else {"charPrIDRef": "2"}
    for child in list(paragraph):
        paragraph.remove(child)
    run = etree.SubElement(paragraph, HP + "run", run_attributes)
    text_node = etree.SubElement(run, HP + "t")
    text_node.text = text
    return paragraph


def _sub_list(cell: etree._Element) -> etree._Element:
    sub_list = _child(cell, "subList")
    if sub_list is None:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "table cell text list missing")
    return sub_list


def _set_cell_lines(cell: etree._Element, lines: list[str]) -> None:
    sub_list = _sub_list(cell)
    templates = [child for child in sub_list if local_name(child.tag) == "p"]
    if not templates:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "table cell paragraph missing")
    for paragraph in templates:
        sub_list.remove(paragraph)
    for line in lines:
        sub_list.append(_clone_text_paragraph(templates[0], line))


def _set_child_attributes(
    parent: etree._Element, child_name: str, attributes: dict[str, str]
) -> None:
    child = _child(parent, child_name)
    if child is None:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED,
            f"template element missing: {child_name}",
        )
    child.attrib.update(attributes)


def _reshape_data_table(table: etree._Element) -> etree._Element:
    """Turn the template's 2x2 picture grid into an unmerged 2x3 data table."""

    result = deepcopy(table)
    rows = [child for child in result if local_name(child.tag) == "tr"]
    if len(rows) != 2:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "picture grid does not have two rows"
        )
    table_size = _child(result, "sz")
    if table_size is None:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "picture grid size missing")
    width = int(table_size.attrib["width"])
    column_widths = [width // 3, width // 3, width - (width // 3) * 2]
    markers = [
        TEXT_MARKERS[f"item.table.rows.{row}.{column}"] for row in range(2) for column in range(3)
    ]
    result.attrib.update({"rowCnt": "2", "colCnt": "3"})
    marker_index = 0
    for row_index, row in enumerate(rows):
        templates = [child for child in row if local_name(child.tag) in {"tc", "cell"}]
        if len(templates) != 2:
            raise HwpxError(
                HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED,
                "picture grid row does not have two source cells",
            )
        for child in templates:
            row.remove(child)
        for column_index in range(3):
            cell = deepcopy(templates[min(column_index, 1)])
            _set_child_attributes(
                cell,
                "cellAddr",
                {"rowAddr": str(row_index), "colAddr": str(column_index)},
            )
            _set_child_attributes(cell, "cellSpan", {"rowSpan": "1", "colSpan": "1"})
            cell_size = _child(cell, "cellSz")
            height = cell_size.attrib.get("height", "1") if cell_size is not None else "1"
            _set_child_attributes(
                cell,
                "cellSz",
                {"width": str(column_widths[column_index]), "height": height},
            )
            _set_cell_lines(cell, [markers[marker_index]])
            marker_index += 1
            row.append(cell)
    return result


def _prepare_gnd_table(table: etree._Element) -> etree._Element:
    result = deepcopy(table)
    cells = _cell_map(result)
    body = cells.get((2, 0))
    if body is None or len(cells) != 6:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "3x3 GND table profile changed")
    _set_cell_lines(
        body,
        [
            f"ㄱ. {TEXT_MARKERS['item.statements.giyeok']}",
            f"ㄴ. {TEXT_MARKERS['item.statements.nieun']}",
            f"ㄷ. {TEXT_MARKERS['item.statements.digeut']}",
        ],
    )
    return result


def _wrap_table(paragraph_template: etree._Element, table: etree._Element) -> etree._Element:
    paragraph = _clone_text_paragraph(paragraph_template, "")
    run = next(element for element in paragraph if local_name(element.tag) == "run")
    for child in list(run):
        run.remove(child)
    run.append(table)
    return paragraph


def _equation_paragraph(
    paragraph_template: etree._Element, equation_template: etree._Element
) -> etree._Element:
    paragraph = _clone_text_paragraph(paragraph_template, "")
    run = next(element for element in paragraph if local_name(element.tag) == "run")
    for child in list(run):
        run.remove(child)
    equation = deepcopy(equation_template)
    scripts = [element for element in equation.iter() if local_name(element.tag) == "script"]
    if len(scripts) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_EQUATION_BINDING_FAILED,
            "source equation does not have one script element",
        )
    scripts[0].text = "EOM_EQ_PLACEHOLDER"
    run.append(equation)
    return paragraph


def _image_dimensions(data: bytes) -> tuple[int, int, int, int]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode not in {"RGB", "RGBA"}:
                raise ValueError("not an RGB/RGBA PNG")
            pixel_width, pixel_height = image.size
    except Exception as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "reference image is not a valid PNG"
        ) from exc
    display_width = 25985
    display_height = max(1, round(display_width * pixel_height / pixel_width))
    return pixel_width * 28, pixel_height * 28, display_width, display_height


def _image_paragraph(paragraph_template: etree._Element, image: bytes) -> etree._Element:
    original_width, original_height, width, height = _image_dimensions(image)
    paragraph = _clone_text_paragraph(paragraph_template, "")
    run = next(element for element in paragraph if local_name(element.tag) == "run")
    for child in list(run):
        run.remove(child)
    picture = etree.SubElement(
        run,
        HP + "pic",
        {
            "id": "2200000001",
            "zOrder": "0",
            "numberingType": "PICTURE",
            "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES",
            "lock": "0",
            "dropcapstyle": "None",
            "href": "",
            "groupLevel": "0",
            "instid": "2300000001",
            "reverse": "0",
        },
    )
    etree.SubElement(picture, HP + "offset", {"x": "0", "y": "0"})
    etree.SubElement(
        picture, HP + "orgSz", {"width": str(original_width), "height": str(original_height)}
    )
    etree.SubElement(picture, HP + "curSz", {"width": str(width), "height": str(height)})
    etree.SubElement(picture, HP + "flip", {"horizontal": "0", "vertical": "0"})
    etree.SubElement(
        picture,
        HP + "rotationInfo",
        {
            "angle": "0",
            "centerX": str(width // 2),
            "centerY": str(height // 2),
            "rotateimage": "1",
        },
    )
    rendering = etree.SubElement(picture, HP + "renderingInfo")
    etree.SubElement(
        rendering,
        HC + "transMatrix",
        {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"},
    )
    etree.SubElement(
        rendering,
        HC + "scaMatrix",
        {
            "e1": f"{width / original_width:.6f}",
            "e2": "0",
            "e3": "0",
            "e4": "0",
            "e5": f"{height / original_height:.6f}",
            "e6": "0",
        },
    )
    etree.SubElement(
        rendering,
        HC + "rotMatrix",
        {"e1": "1", "e2": "0", "e3": "0", "e4": "0", "e5": "1", "e6": "0"},
    )
    rectangle = etree.SubElement(picture, HP + "imgRect")
    etree.SubElement(rectangle, HC + "pt0", {"x": "0", "y": "0"})
    etree.SubElement(rectangle, HC + "pt1", {"x": str(original_width), "y": "0"})
    etree.SubElement(rectangle, HC + "pt2", {"x": str(original_width), "y": str(original_height)})
    etree.SubElement(rectangle, HC + "pt3", {"x": "0", "y": str(original_height)})
    etree.SubElement(
        picture, HP + "imgClip", {"left": "0", "top": "0", "right": "0", "bottom": "0"}
    )
    etree.SubElement(
        picture, HP + "inMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"}
    )
    etree.SubElement(
        picture,
        HP + "imgDim",
        {"dimwidth": str(original_width), "dimheight": str(original_height)},
    )
    etree.SubElement(
        picture,
        HC + "img",
        {
            "binaryItemIDRef": REFERENCE_IMAGE_ID,
            "bright": "0",
            "contrast": "0",
            "effect": "REAL_PIC",
            "alpha": "0",
        },
    )
    etree.SubElement(
        picture,
        HP + "sz",
        {
            "width": str(width),
            "height": str(height),
            "widthRelTo": "ABSOLUTE",
            "heightRelTo": "ABSOLUTE",
            "protect": "0",
        },
    )
    etree.SubElement(
        picture,
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
            "horzAlign": "CENTER",
            "vertOffset": "0",
            "horzOffset": "0",
        },
    )
    etree.SubElement(
        picture, HP + "outMargin", {"left": "0", "right": "0", "top": "0", "bottom": "0"}
    )
    return paragraph


def _prepare_problem(root: etree._Element, reference_image: bytes) -> None:
    outer = _unique_table(root, (1, 1))
    equation_candidates = [
        element for element in root.iter() if local_name(element.tag) == "equation"
    ]
    if not equation_candidates:
        raise HwpxError(
            HwpxErrorCode.HWPX_EQUATION_BINDING_FAILED, "source template equation missing"
        )
    outer_cells = _direct_cells(outer)
    if len(outer_cells) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "problem container profile changed"
        )
    sub_list = _sub_list(outer_cells[0])
    paragraphs = [child for child in sub_list if local_name(child.tag) == "p"]
    if len(paragraphs) < 5:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "problem paragraph profile changed"
        )
    picture_grid_matches = [
        table
        for table in paragraphs[1].xpath("./hp:run/hp:tbl", namespaces={"hp": HP_NS})
        if _shape(table) == (2, 2)
    ]
    gnd_matches = [
        table
        for table in paragraphs[3].xpath("./hp:run/hp:tbl", namespaces={"hp": HP_NS})
        if _shape(table) == (3, 3)
    ]
    if len(picture_grid_matches) != 1 or len(gnd_matches) != 1:
        raise HwpxError(
            HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED,
            "problem table paragraph profile changed",
        )
    picture_grid = picture_grid_matches[0]
    gnd = gnd_matches[0]
    text_template = paragraphs[2]
    table_template = paragraphs[1]
    choice_template = paragraphs[4]
    data_table = _reshape_data_table(picture_grid)
    gnd_table = _prepare_gnd_table(gnd)
    for paragraph in paragraphs:
        sub_list.remove(paragraph)
    sub_list.extend(
        [
            _clone_text_paragraph(text_template, TEXT_MARKERS["item.item_number"]),
            _clone_text_paragraph(text_template, TEXT_MARKERS["item.upper_stem"]),
            _wrap_table(table_template, data_table),
            _image_paragraph(text_template, reference_image),
            _equation_paragraph(text_template, equation_candidates[0]),
            _clone_text_paragraph(text_template, TEXT_MARKERS["item.lower_stem"]),
            _wrap_table(paragraphs[3], gnd_table),
            *[
                _clone_text_paragraph(
                    choice_template,
                    f"{label} {TEXT_MARKERS[f'item.choices.{index}']}",
                )
                for index, label in enumerate(("①", "②", "③", "④", "⑤"))
            ],
            _clone_text_paragraph(text_template, TEXT_MARKERS["item.points"]),
        ]
    )


def _prepare_solution(root: etree._Element) -> None:
    field_table = _unique_table(root, (9, 4))
    cells = _cell_map(field_table)
    required = {(0, 0), (1, 1), (2, 1), (3, 1), (3, 3), (4, 1)}
    if not required.issubset(cells):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSUPPORTED, "9x4 field table profile changed")
    _set_cell_lines(cells[(0, 0)], [TEXT_MARKERS["document_title"]])
    _set_cell_lines(cells[(1, 1)], ["PLACEHOLDER_UNIT"])
    _set_cell_lines(cells[(2, 1)], ["PLACEHOLDER_SUBUNIT"])
    _set_cell_lines(cells[(3, 1)], ["X"])
    _set_cell_lines(cells[(3, 3)], ["X"])
    _set_cell_lines(
        cells[(4, 1)],
        [
            f"답: {TEXT_MARKERS['solution.answer']}",
            "[ 출제 의도 ]",
            TEXT_MARKERS["solution.authoring_intent"],
            "[ 풀이 및 정답 해설 ]",
            TEXT_MARKERS["solution.overview"],
            f"ㄱ. {TEXT_MARKERS['solution.statement_explanations.giyeok']}",
            f"ㄴ. {TEXT_MARKERS['solution.statement_explanations.nieun']}",
            f"ㄷ. {TEXT_MARKERS['solution.statement_explanations.digeut']}",
        ],
    )
    for address, value in {
        (5, 1): "PLACEHOLDER_REFERENCE",
        (6, 1): "PLACEHOLDER_TEAM_INTENT",
        (7, 1): "PLACEHOLDER_SOURCE_ATTACHMENT",
        (8, 1): "PLACEHOLDER_ILLUSTRATION_REQUEST",
    }.items():
        if address in cells:
            _set_cell_lines(cells[address], [value])


def _prepare_manifest(parsed: ParsedXml) -> None:
    root = parsed.root
    manifest = next(
        (element for element in root.iter() if local_name(element.tag) == "manifest"),
        None,
    )
    if manifest is None:
        raise HwpxError(HwpxErrorCode.HWPX_MANIFEST_INVALID, "content manifest missing")
    existing_ids = {
        element.attrib.get("id") for element in manifest if local_name(element.tag) == "item"
    }
    if REFERENCE_IMAGE_ID in existing_ids:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "reference image identifier already exists"
        )
    etree.SubElement(
        manifest,
        OPF + "item",
        {
            "id": REFERENCE_IMAGE_ID,
            "href": REFERENCE_IMAGE_PART,
            "media-type": "image/png",
            "isEmbeded": "1",
        },
    )
    for element in root.iter():
        element_name = local_name(element.tag).casefold()
        if element_name == "title":
            element.text = "EOM PLACEHOLDER REFERENCE"
        if element_name != "meta":
            continue
        name = element.attrib.get("name", "").casefold()
        if name in {"creator", "lastsaveby"}:
            element.attrib["content"] = "PLACEHOLDER"
        elif name == "modifieddate":
            element.attrib["content"] = "2026-08-17T00:00:00Z"


def _write_package(source: SafePackage, payloads: dict[str, bytes], output: Path) -> None:
    if output.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "reference output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=False) as archive:
            written: set[str] = set()
            for entry in source.entries:
                info = zipfile.ZipInfo(entry.info.filename, FIXED_ZIP_TIMESTAMP)
                info.compress_type = entry.info.compress_type
                info.comment = entry.info.comment
                info.extra = entry.info.extra
                info.internal_attr = entry.info.internal_attr
                info.external_attr = entry.info.external_attr
                info.create_system = entry.info.create_system
                archive.writestr(info, payloads[entry.info.filename])
                written.add(entry.info.filename)
            for name in sorted(set(payloads) - written):
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100600 << 16
                archive.writestr(info, payloads[name])
        temporary.replace(output)
    except (OSError, zipfile.BadZipFile) as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "reference package write failed"
        ) from exc


def prepare_content_team_reference(
    source: Path, reference_image: Path, output: Path
) -> dict[str, Any]:
    """Create one marker reference from the fixed Hancom content-team template profile."""

    package = read_package(source)
    payloads = {entry.info.filename: entry.data for entry in package.entries}
    if REFERENCE_IMAGE_PART in payloads:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "reference image part already exists"
        )
    section_bytes = payloads.get("Contents/section0.xml")
    content_bytes = payloads.get("Contents/content.hpf")
    if section_bytes is None or content_bytes is None:
        raise HwpxError(HwpxErrorCode.HWPX_MANIFEST_INVALID, "core template parts missing")
    image_bytes = reference_image.read_bytes()
    _image_dimensions(image_bytes)
    section = parse_xml(section_bytes, "Contents/section0.xml")
    content = parse_xml(content_bytes, "Contents/content.hpf")
    _prepare_problem(section.root, image_bytes)
    _prepare_solution(section.root)
    _prepare_manifest(content)
    payloads["Contents/section0.xml"] = serialize_xml(section)
    payloads["Contents/content.hpf"] = serialize_xml(content)
    payloads["Preview/PrvText.txt"] = b"EOM PLACEHOLDER REFERENCE"
    payloads[REFERENCE_IMAGE_PART] = image_bytes
    _write_package(package, payloads, output)
    result = read_package(output)
    return {
        "status": "PASS",
        "source_sha256": package.package_sha256,
        "output_sha256": result.package_sha256,
        "reference_image_sha256": sha256_bytes(image_bytes),
        "output": output.name,
    }
