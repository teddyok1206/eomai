"""Bind immutable PNG inputs into content-team visual slots after editorial rendering."""

from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path

from eom_hwpx_contracts import ContentTeamImageSource
from lxml import etree  # type: ignore[import-untyped]
from PIL import Image

from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP, read_package
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.xmlsafe import local_name, parse_xml, serialize_xml

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HC_NS = "http://www.hancom.co.kr/hwpml/2011/core"
OPF_NS = "http://www.idpf.org/2007/opf/"
HP = f"{{{HP_NS}}}"
HC = f"{{{HC_NS}}}"
OPF = f"{{{OPF_NS}}}"
PLACEHOLDER = "그림 삽입"


def _dimensions(data: bytes) -> tuple[int, int, int, int]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG" or image.mode not in {"RGB", "RGBA"}:
                raise ValueError("unsupported PNG")
            if image.size != (800, 500):
                raise ValueError("unexpected PNG dimensions")
    except Exception as exc:
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "content-team image is not the pinned 800x500 PNG",
        ) from exc
    original_width, original_height = 800 * 28, 500 * 28
    display_width = 12600
    display_height = round(display_width * 500 / 800)
    return original_width, original_height, display_width, display_height


def _picture(*, binary_id: str, object_id: int, image: bytes) -> etree._Element:
    original_width, original_height, width, height = _dimensions(image)
    picture = etree.Element(
        HP + "pic",
        {
            "id": str(object_id),
            "zOrder": "0",
            "numberingType": "PICTURE",
            "textWrap": "TOP_AND_BOTTOM",
            "textFlow": "BOTH_SIDES",
            "lock": "0",
            "dropcapstyle": "None",
            "href": "",
            "groupLevel": "0",
            "instid": str(object_id + 1),
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
            "binaryItemIDRef": binary_id,
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
    return picture


def _next_object_id(section: etree._Element) -> int:
    values = [
        int(value)
        for element in section.iter()
        for key, value in element.attrib.items()
        if local_name(key) in {"id", "instid"} and value.isdecimal()
    ]
    return max(values, default=2_000_000_000) + 1


def inject_content_team_images(
    output: Path,
    images: tuple[tuple[ContentTeamImageSource, bytes], ...],
) -> None:
    """Replace only unique team-renderer placeholders and add pinned BinData members."""

    if not images:
        return
    package = read_package(output)
    by_name = package.by_name()
    section_entry = by_name.get("Contents/section0.xml")
    content_entry = by_name.get("Contents/content.hpf")
    if section_entry is None or content_entry is None:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "HWPX image parts are missing")
    if any(entry.info.filename.casefold().startswith("bindata/") for entry in package.entries):
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "content-team base output unexpectedly contains body image bytes",
        )
    section = parse_xml(section_entry.data, section_entry.info.filename)
    content = parse_xml(content_entry.data, content_entry.info.filename)
    placeholders = [
        element
        for element in section.root.iter()
        if local_name(element.tag) == "t" and (element.text or "").strip().startswith(PLACEHOLDER)
    ]
    if len(placeholders) != len(images):
        raise HwpxError(
            HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
            "content-team image placeholder count differs from pinned images",
        )
    manifests = [
        element for element in content.root.iter() if local_name(element.tag) == "manifest"
    ]
    if len(manifests) != 1:
        raise HwpxError(HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED, "HWPX manifest is ambiguous")
    replacements: dict[str, bytes] = {
        "Contents/section0.xml": b"",
        "Contents/content.hpf": b"",
    }
    added: list[tuple[str, bytes]] = []
    object_id = _next_object_id(section.root)
    for (source, payload), placeholder in zip(images, placeholders, strict=True):
        run = placeholder.getparent()
        if run is None or local_name(run.tag) != "run" or len(run) != 1:
            raise HwpxError(
                HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
                "content-team image placeholder host is not unique",
            )
        binary_id = f"eomContentTeamVisual{source.visual_ordinal}"
        part_name = f"BinData/content-team-visual-{source.visual_ordinal}.png"
        for child in list(run):
            run.remove(child)
        run.append(_picture(binary_id=binary_id, object_id=object_id, image=payload))
        object_id += 2
        etree.SubElement(
            manifests[0],
            OPF + "item",
            {"id": binary_id, "href": f"../{part_name}", "media-type": "image/png"},
        )
        added.append((part_name, payload))
    replacements["Contents/section0.xml"] = serialize_xml(section)
    replacements["Contents/content.hpf"] = serialize_xml(content)

    temporary = output.with_name(".content-team-images.hwpx")
    if temporary.exists() or temporary.is_symlink():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "image output is not fresh")
    try:
        with zipfile.ZipFile(temporary, "x", allowZip64=False) as archive:
            for entry in package.entries:
                info = zipfile.ZipInfo(entry.info.filename, FIXED_ZIP_TIMESTAMP)
                info.compress_type = entry.info.compress_type
                info.comment = entry.info.comment
                info.extra = entry.info.extra
                info.internal_attr = entry.info.internal_attr
                info.external_attr = entry.info.external_attr
                info.create_system = entry.info.create_system
                archive.writestr(info, replacements.get(entry.info.filename, entry.data))
            for name, payload in added:
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, payload)
        os.chmod(temporary, 0o600)
        analysis = analyze_package(temporary)
        expected = tuple(name for name, _payload in added)
        if analysis.active_content or analysis.external_links or analysis.bindata != expected:
            raise HwpxError(
                HwpxErrorCode.HWPX_IMAGE_BINDING_FAILED,
                "content-team image package validation failed",
            )
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
