"""Read-only HWPX native picture uses; no Office execution, external XML or page crop."""

from __future__ import annotations

import io
import math
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from eom_image_contracts.models import content_sha256
from eom_image_contracts.office_picture_uses import (
    OfficeNativeObject,
    OfficeNativeObjectKind,
    OfficeObjectLocator,
    OfficePictureGeometry,
    OfficePicturePlacement,
    OfficePictureUse,
    UnresolvedPictureReason,
    office_object_id,
)

from eom_image_provider.office_embedded_images import OfficeEmbeddedImageError
from eom_image_provider.office_picture_records import _rotation_quarter_turn

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
HC = "{http://www.hancom.co.kr/hwpml/2011/core}"
OPF = "{http://www.idpf.org/2007/opf/}"
_MAX_XML = 8 * 1024 * 1024
_NATIVE_TAGS: dict[str, OfficeNativeObjectKind] = {
    HP + "tbl": "TABLE",
    HP + "equation": "EQUATION",
    HP + "container": "GROUP",
    **{HP + name: "DRAWING" for name in ("line", "rect", "ellipse", "arc", "polygon", "curve")},
}


def _xml(raw: bytes) -> ET.Element:
    if not 0 < len(raw) <= _MAX_XML:
        raise OfficeEmbeddedImageError("OFFICE_PICTURE_XML_LIMIT")
    try:
        text = raw.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_XML_UNSAFE")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError) as exc:
        raise OfficeEmbeddedImageError("OFFICE_PICTURE_XML_INVALID") from exc
    count = 0
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 128 or count > 100000 or node.tag == "{http://www.w3.org/2001/XInclude}include":
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_XML_LIMIT")
        stack.extend((child, depth + 1) for child in node)
    return root


def _native_hashes(root: ET.Element) -> dict[ET.Element, str]:
    """Merkle identities avoid serializing nested table/group subtrees repeatedly."""
    hashes: dict[ET.Element, str] = {}
    for node in reversed(tuple(root.iter())):
        hashes[node] = content_sha256(
            {
                "tag": node.tag,
                "attributes": node.attrib,
                "text": node.text,
                "tail": node.tail,
                "children": [hashes[child] for child in node],
            }
        )
    return hashes


def _number(node: ET.Element, name: str) -> int:
    value = node.get(name, "")
    if re.fullmatch(r"-?[0-9]{1,12}", value) is None:
        raise ValueError("invalid source coordinate")
    return int(value)


def _one(node: ET.Element, tag: str) -> ET.Element:
    candidates = node.findall(tag)
    if len(candidates) != 1:
        raise ValueError("ambiguous source child")
    return candidates[0]


def _boolean(node: ET.Element, name: str) -> bool:
    value = node.get(name)
    if value not in {"0", "1", "false", "true"}:
        raise ValueError("invalid source boolean")
    return value in {"1", "true"}


def _geometry(node: ET.Element) -> OfficePictureGeometry | None:
    try:
        rectangle = _one(node, HP + "imgRect")
        points = tuple(
            (
                _number(_one(rectangle, HC + f"pt{i}"), "x"),
                _number(_one(rectangle, HC + f"pt{i}"), "y"),
            )
            for i in range(4)
        )
        rectangle_width, rectangle_height = points[2]
        if points != (
            (0, 0),
            (rectangle_width, 0),
            (rectangle_width, rectangle_height),
            (0, rectangle_height),
        ):
            return None
        # imgClip is expressed in imgDim's original-image coordinates. Hancom
        # can retain a different imgRect/orgSz after replacing/resizing a bitmap.
        dimensions = _one(node, HP + "imgDim")
        width, height = _number(dimensions, "dimwidth"), _number(dimensions, "dimheight")
        clip = _one(node, HP + "imgClip")
        viewport = (
            _number(clip, "left"),
            _number(clip, "top"),
            _number(clip, "right"),
            _number(clip, "bottom"),
        )
        rotation = _one(node, HP + "rotationInfo")
        angle = _number(rotation, "angle")
        if angle % 90:
            return None
        flips = _one(node, HP + "flip")
        rendering = _one(node, HP + "renderingInfo")
        # Multiple transform pairs indicate inherited/group geometry. They are
        # not flattened by guessing a rotation or a PDF rectangle.
        scaling = _one(rendering, HC + "scaMatrix")
        rotating = _one(rendering, HC + "rotMatrix")
        translation = _one(rendering, HC + "transMatrix")
        scale = tuple(float(scaling.attrib[f"e{i}"]) for i in range(1, 7))
        rotate = tuple(float(rotating.attrib[f"e{i}"]) for i in range(1, 7))
        translate = tuple(float(translation.attrib[f"e{i}"]) for i in range(1, 7))
        if (
            not all(
                math.isfinite(value) and abs(value) <= 1_000_000_000
                for value in (*scale, *rotate, *translate)
            )
            or abs(scale[1]) > 1e-7
            or abs(scale[3]) > 1e-7
            or scale[0] <= 0
            or scale[4] <= 0
            or _rotation_quarter_turn(rotate) != (angle // 90) % 4
            or any(
                abs(translate[index] - value) > 1e-7
                for index, value in ((0, 1), (1, 0), (3, 0), (4, 1))
            )
        ):
            return None
        return OfficePictureGeometry(
            original_extent=(width, height),
            viewport=viewport,
            clockwise_quarter_turns=(angle // 90) % 4,
            flip_horizontal=_boolean(flips, "horizontal"),
            flip_vertical=_boolean(flips, "vertical"),
        )
    except (ValueError, KeyError, OverflowError):
        return None


def _member(href: str) -> str | None:
    if (
        not href
        or "\\" in href
        or ":" in href
        or "#" in href
        or "?" in href
        or href.startswith("/")
    ):
        return None
    # Hancom uses both package-root-qualified and OPF-relative references.
    parts: list[str] = [] if href.startswith("BinData/") else ["Contents"]
    for part in href.split("/"):
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part in {"", "."}:
            return None
        else:
            parts.append(part)
    candidate = str(PurePosixPath(*parts))
    return candidate if re.fullmatch(r"BinData/[^/\\]+", candidate) else None


def _placement(node: ET.Element, anchor: int | None) -> OfficePicturePlacement | None:
    try:
        position, size = _one(node, HP + "pos"), _one(node, HP + "sz")
        x, y = _number(position, "horzOffset"), _number(position, "vertOffset")
        if x >= 2**31:
            x -= 2**32
        if y >= 2**31:
            y -= 2**32
        return OfficePicturePlacement.model_validate(
            {
                "horizontal_offset": x,
                "vertical_offset": y,
                "horizontal_relative": position.get("horzRelTo"),
                "vertical_relative": position.get("vertRelTo"),
                "width": _number(size, "width"),
                "height": _number(size, "height"),
                "z_order": _number(node, "zOrder"),
                "anchor_ordinal": anchor,
            }
        )
    except ValueError:
        return None


def read_hwpx_picture_uses(
    payload: bytes, *, source_sha256: str, grayscale_uses: set[str] | None = None
) -> tuple[list[OfficePictureUse], list[OfficeNativeObject]]:
    # Full ZIP path/expansion validation is performed by the shared whole-image
    # extractor before this read; no paths are extracted to the filesystem.
    with zipfile.ZipFile(io.BytesIO(payload)) as package:
        names = set(package.namelist())
        if "Contents/content.hpf" not in names:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_PACKAGE_MANIFEST_MISSING")
        manifest = _xml(package.read("Contents/content.hpf"))
        media: dict[str, str | None] = {}
        for node in manifest.iter(OPF + "item"):
            identifier = node.get("id", "")
            if not identifier or len(identifier) > 256 or identifier in media:
                raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
            media[identifier] = _member(node.get("href", ""))
        sections = sorted(
            name for name in names if re.fullmatch(r"Contents/section[0-9]+\.xml", name)
        )
        if not 1 <= len(sections) <= 64:
            raise OfficeEmbeddedImageError("OFFICE_PICTURE_SECTION_LIMIT")
        uses: list[OfficePictureUse] = []
        objects: list[OfficeNativeObject] = []
        for member in sections:
            root = _xml(package.read(member))
            native_hashes = _native_hashes(root)
            # Preorder and a carried parent-group ID give O(nodes) traversal.
            stack: list[tuple[ET.Element, str | None, int | None]] = [(root, None, None)]
            ordinal = 0
            while stack:
                node, group_id, anchor = stack.pop()
                locator = OfficeObjectLocator(member_path=member, ordinal=ordinal)
                ordinal += 1
                identifier = office_object_id(source_sha256, locator)
                if node.tag == HP + "pic":
                    images = node.findall(HC + "img")
                    if len(images) != 1:
                        raise OfficeEmbeddedImageError("OFFICE_PICTURE_BINDING_INVALID")
                    reference = images[0].get("binaryItemIDRef", "")
                    source_member = media.get(reference)
                    geometry = _geometry(node)
                    reasons: list[UnresolvedPictureReason] = []
                    if source_member is None:
                        reasons.append("EXTERNAL_IMAGE" if reference in media else "MISSING_IMAGE")
                    if geometry is None:
                        reasons.append("GEOMETRY_UNRESOLVED")
                    if group_id is not None:
                        reasons.append("GROUP_COMPOSITION_REQUIRED")
                    gray = images[0].get("effect") == "GRAY_SCALE" and grayscale_uses is not None
                    if (
                        images[0].get("bright", "0") != "0"
                        or images[0].get("contrast", "0") != "0"
                        or (images[0].get("effect", "REAL_PIC") != "REAL_PIC" and not gray)
                        or images[0].get("alpha", "0") != "0"
                        or any(len(effect) for effect in node.findall(HP + "effects"))
                    ):
                        reasons.append("IMAGE_EFFECT_UNSUPPORTED")
                    if gray:
                        assert grayscale_uses is not None
                        grayscale_uses.add(identifier)
                    uses.append(
                        OfficePictureUse(
                            use_id=identifier,
                            locator=locator,
                            source_member=source_member,
                            native_sha256=native_hashes[node],
                            group_id=group_id,
                            geometry=geometry,
                            placement=_placement(node, anchor),
                            unresolved_reasons=tuple(sorted(reasons)),
                        )
                    )
                kind = _NATIVE_TAGS.get(node.tag)
                if kind is not None:
                    objects.append(
                        OfficeNativeObject(
                            object_id=identifier,
                            locator=locator,
                            kind=kind,
                            group_id=group_id,
                            native_sha256=native_hashes[node],
                        )
                    )
                child_group = identifier if kind == "GROUP" else group_id
                child_anchor = locator.ordinal if node.tag == HP + "p" else anchor
                stack.extend((child, child_group, child_anchor) for child in reversed(node))
                if len(uses) > 2048 or len(objects) > 4096:
                    raise OfficeEmbeddedImageError("OFFICE_PICTURE_OBJECT_LIMIT")
        return uses, objects
