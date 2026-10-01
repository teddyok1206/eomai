"""Deterministic rendered-space validation for labels in safe SVG overlays."""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from collections.abc import Callable
from typing import Annotated, Final, Literal, NamedTuple

from pydantic import Field, model_validator

from eom_image_contracts.models import FrozenModel, content_sha256, text_sha256
from eom_image_contracts.safe_svg import SVG_NAMESPACE, sanitize_svg_overlay

SVG_LABEL_LAYOUT_SCHEMA_VERSION: Final = "svg-label-layout-validation-receipt/1.0"
SVG_LABEL_LAYOUT_POLICY_REVISION: Final = "eom-svg-label-layout/1.0"
SVG_LABEL_LAYOUT_CLEARANCE_PX: Final = 8
SVG_LABEL_LAYOUT_CANVAS_WIDTH: Final = 800
SVG_LABEL_LAYOUT_CANVAS_HEIGHT: Final = 500
SVG_LABEL_LAYOUT_RENDERER_CONTRACT: Final = "eom-safe-svg-compositor/1.1"
SVG_LABEL_LAYOUT_RENDERER_PATH: Final = "/usr/bin/rsvg-convert"
SVG_LABEL_LAYOUT_FONT_PROFILE: Final = "eom-content-team-diagram-fonts/1.0"
SVG_LABEL_LAYOUT_PACK_VERSION: Final = "1.20.14"
SVG_LABEL_LAYOUT_PACK_BUNDLE_SHA256: Final = (
    "sha256:72150b33965cbd70465cd13738df41eef66d9a9ed51d7a16b84897227c53a391"
)


class SvgLabelLayoutFontSpec(NamedTuple):
    role: str
    family: str
    style: str
    path: str
    sha256: str


SVG_LABEL_LAYOUT_FONT_SPECS: Final = (
    SvgLabelLayoutFontSpec(
        "korean_label",
        "SM JGothic Std",
        "regular",
        "/usr/local/share/fonts/eom/SMJGothicStd-Regular.otf",
        "sha256:9200e1e46cca77f0ff9481c5345c3333caf22d50487418df74f830e4221adea1",
    ),
    SvgLabelLayoutFontSpec(
        "korean_fallback",
        "Noto Sans CJK KR",
        "regular",
        "/usr/local/share/fonts/eom/NotoSansCJKkr-Regular.otf",
        "sha256:6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a",
    ),
    SvgLabelLayoutFontSpec(
        "latin_label",
        "Century Old Style",
        "regular",
        "/usr/local/share/fonts/eom/CenturyOldStyle-Regular.otf",
        "sha256:7f9420403e10e7e74f002fbb48e8034d48f64cbdbef556d4f964b266043de338",
    ),
    SvgLabelLayoutFontSpec(
        "latin_label",
        "Century Old Style",
        "italic",
        "/usr/local/share/fonts/eom/CenturyOldStyle-Italic.otf",
        "sha256:44b00cbdab9fdb7b4307db79784c5b90cbc52c5ffb0add32ac8239d73e567809",
    ),
    SvgLabelLayoutFontSpec(
        "math_label",
        "DejaVu Serif",
        "regular",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "sha256:8f2c103bfa3fd5de71f1b92b18f21906b5a26871fb7e19a9a4c9af539c3cc7ab",
    ),
    SvgLabelLayoutFontSpec(
        "legacy_korean_compatibility",
        "Droid Sans Fallback",
        "regular",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "sha256:acb6440a713d880a13a21b468ba7cd43f5a2b2934972e51be791c880730777b8",
    ),
)

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
RenderSvg = Callable[[bytes], bytes]


def svg_label_layout_font_manifest_sha256() -> str:
    """Return the canonical fixed-font environment identity used by both adapters."""

    return content_sha256(
        {
            "schema_version": "1.0",
            "profile": SVG_LABEL_LAYOUT_FONT_PROFILE,
            "fonts": [
                {
                    "role": font.role,
                    "family": font.family,
                    "style": font.style,
                    "sha256": font.sha256,
                }
                for font in SVG_LABEL_LAYOUT_FONT_SPECS
            ],
        }
    )


class SvgLabelLayoutValidationError(ValueError):
    """One stable, retryable worker-result validation error."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(detail)


class SvgLabelBounds(FrozenModel):
    text: str = Field(min_length=1, max_length=256)
    occurrence: int = Field(ge=1, le=32)
    left: int = Field(ge=0, le=SVG_LABEL_LAYOUT_CANVAS_WIDTH - 1)
    top: int = Field(ge=0, le=SVG_LABEL_LAYOUT_CANVAS_HEIGHT - 1)
    right: int = Field(ge=0, le=SVG_LABEL_LAYOUT_CANVAS_WIDTH - 1)
    bottom: int = Field(ge=0, le=SVG_LABEL_LAYOUT_CANVAS_HEIGHT - 1)

    @model_validator(mode="after")
    def ordered_bounds(self) -> SvgLabelBounds:
        if self.left > self.right or self.top > self.bottom:
            raise ValueError("label bounds must be ordered")
        return self


class SvgLabelLayoutValidationReceipt(FrozenModel):
    schema_version: Literal["svg-label-layout-validation-receipt/1.0"]
    policy_revision: Literal["eom-svg-label-layout/1.0"]
    overlay_sha256: Sha256
    renderer_contract: Literal["eom-safe-svg-compositor/1.1"]
    renderer_version: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^rsvg-convert version 2\.58\.",
    )
    renderer_sha256: Sha256
    font_manifest_sha256: Sha256
    clearance_px: Literal[8]
    required_labels: tuple[str, ...] = Field(max_length=16)
    labels: tuple[SvgLabelBounds, ...] = Field(max_length=32)
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def exact_canonical_identity(self) -> SvgLabelLayoutValidationReceipt:
        if self.required_labels != tuple(sorted(set(self.required_labels))):
            raise ValueError("required_labels must be sorted and unique")
        label_order = tuple((label.text, label.occurrence) for label in self.labels)
        if label_order != tuple(sorted(label_order)) or len(label_order) != len(set(label_order)):
            raise ValueError("labels must be sorted and unique by text and occurrence")
        expected = content_sha256(self.model_dump(mode="json", exclude={"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("receipt_sha256 does not match canonical receipt content")
        return self


def validate_svg_label_layout(
    *,
    overlay: str,
    required_labels: tuple[str, ...],
    render_svg: RenderSvg,
    renderer_version: str,
    renderer_sha256: str,
    font_manifest_sha256: str,
) -> SvgLabelLayoutValidationReceipt:
    """Validate exact labels against rendered geometry and return a self-hashed receipt.

    The rasterizer is injected so this contract package stays independent of subprocess,
    filesystem, and Catalog/Orchestrator infrastructure.
    """

    try:
        clean = sanitize_svg_overlay(overlay, required_labels)
    except ValueError as exc:
        raise SvgLabelLayoutValidationError("SVG_LABEL_LAYOUT_RENDER_INVALID", str(exc)) from exc
    canonical_required = tuple(sorted(set(required_labels)))
    if len(canonical_required) != len(required_labels):
        raise SvgLabelLayoutValidationError(
            "SVG_REQUIRED_LABEL_CARDINALITY_INVALID",
            "required labels must be unique",
        )
    root = _parse_canonical_overlay(clean)
    text_nodes = tuple(node for node in root.iter() if _local_name(node.tag) == "text")
    counts = Counter((node.text or "").strip() for node in text_nodes)
    if any(counts[label] != 1 for label in canonical_required):
        raise SvgLabelLayoutValidationError(
            "SVG_REQUIRED_LABEL_CARDINALITY_INVALID",
            "every required label must occur exactly once",
        )
    if len(text_nodes) > 32:
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_LAYOUT_RENDER_INVALID", "SVG contains too many text elements"
        )

    geometry = _render_and_decode(render_svg, _serialize_geometry(root))
    edge_mask = _geometry_edge_mask(geometry)
    label_entries: list[tuple[SvgLabelBounds, bytearray]] = []
    occurrence_by_text: Counter[str] = Counter()
    for index, node in enumerate(text_nodes):
        text = (node.text or "").strip()
        occurrence_by_text[text] += 1
        label_raster = _render_and_decode(render_svg, _serialize_one_text(root, index))
        mask = _alpha_mask(label_raster)
        bounds = _mask_bounds(mask)
        if bounds is None:
            raise SvgLabelLayoutValidationError(
                "SVG_LABEL_LAYOUT_RENDER_INVALID", f"label {text!r} did not render"
            )
        label = SvgLabelBounds(
            text=text,
            occurrence=occurrence_by_text[text],
            left=bounds[0],
            top=bounds[1],
            right=bounds[2],
            bottom=bounds[3],
        )
        _validate_canvas_clearance(label)
        _validate_geometry_clearance(label, mask, geometry, edge_mask)
        label_entries.append((label, mask))
    _validate_label_clearance(tuple(entry[0] for entry in label_entries))

    labels = tuple(
        sorted(
            (entry[0] for entry in label_entries),
            key=lambda value: (value.text, value.occurrence),
        )
    )
    body = {
        "schema_version": SVG_LABEL_LAYOUT_SCHEMA_VERSION,
        "policy_revision": SVG_LABEL_LAYOUT_POLICY_REVISION,
        "overlay_sha256": text_sha256(clean),
        "renderer_contract": SVG_LABEL_LAYOUT_RENDERER_CONTRACT,
        "renderer_version": renderer_version,
        "renderer_sha256": renderer_sha256,
        "font_manifest_sha256": font_manifest_sha256,
        "clearance_px": SVG_LABEL_LAYOUT_CLEARANCE_PX,
        "required_labels": canonical_required,
        "labels": tuple(label.model_dump(mode="json") for label in labels),
    }
    return SvgLabelLayoutValidationReceipt.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


class _Raster(FrozenModel):
    width: int
    height: int
    rgba: bytes


def _parse_canonical_overlay(clean: str) -> ET.Element:
    return ET.fromstring(
        f'<svg xmlns="{SVG_NAMESPACE}" width="800" height="500" viewBox="0 0 800 500">{clean}</svg>'
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clone_without_text(node: ET.Element) -> ET.Element | None:
    if _local_name(node.tag) == "text":
        return None
    clone = ET.Element(_local_name(node.tag), node.attrib)
    for child in node:
        cloned = _clone_without_text(child)
        if cloned is not None:
            clone.append(cloned)
    return clone


def _clone_one_text(node: ET.Element, target: int, cursor: list[int]) -> ET.Element | None:
    if _local_name(node.tag) == "text":
        current = cursor[0]
        cursor[0] += 1
        if current != target:
            return None
        clone = ET.Element("text", node.attrib)
        clone.text = node.text
        return clone
    clone = ET.Element(_local_name(node.tag), node.attrib)
    for child in node:
        cloned = _clone_one_text(child, target, cursor)
        if cloned is not None:
            clone.append(cloned)
    if _local_name(node.tag) != "svg" and not tuple(clone):
        return None
    return clone


def _serialize_geometry(root: ET.Element) -> bytes:
    clean = _clone_without_text(root)
    if clean is None:
        raise AssertionError("SVG root cannot be text")
    clean.set("xmlns", SVG_NAMESPACE)
    rendered = ET.tostring(clean, encoding="utf-8", xml_declaration=True)
    if not isinstance(rendered, bytes):
        raise AssertionError("SVG byte serialization failed")
    return rendered


def _serialize_one_text(root: ET.Element, target: int) -> bytes:
    clean = _clone_one_text(root, target, [0])
    if clean is None:
        raise AssertionError("requested SVG text is absent")
    clean.set("xmlns", SVG_NAMESPACE)
    rendered = ET.tostring(clean, encoding="utf-8", xml_declaration=True)
    if not isinstance(rendered, bytes):
        raise AssertionError("SVG byte serialization failed")
    return rendered


def _decode_rendered_png(payload: bytes) -> _Raster:
    try:
        return _decode_png(payload)
    except (ValueError, struct.error, zlib.error) as exc:
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_LAYOUT_RENDER_INVALID", "renderer returned an invalid bounded PNG"
        ) from exc


def _render_and_decode(render_svg: RenderSvg, payload: bytes) -> _Raster:
    try:
        rendered = render_svg(payload)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_LAYOUT_RENDER_INVALID", "fixed SVG label renderer failed"
        ) from exc
    return _decode_rendered_png(rendered)


def _decode_png(payload: bytes) -> _Raster:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n") or len(payload) > 16 * 1024 * 1024:
        raise ValueError("invalid PNG envelope")
    offset = 8
    width = height = bit_depth = color_type = -1
    compressed = bytearray()
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        if length > 16 * 1024 * 1024 or offset + 12 + length > len(payload):
            raise ValueError("invalid PNG chunk")
        name = payload[offset + 4 : offset + 8]
        data = payload[offset + 8 : offset + 8 + length]
        if name == b"IHDR":
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if (compression, filtering, interlace) != (0, 0, 0):
                raise ValueError("unsupported PNG encoding")
        elif name == b"IDAT":
            compressed.extend(data)
        elif name == b"IEND":
            break
        offset += 12 + length
    if (
        width != SVG_LABEL_LAYOUT_CANVAS_WIDTH
        or height != SVG_LABEL_LAYOUT_CANVAS_HEIGHT
        or bit_depth != 8
        or color_type not in {2, 6}
    ):
        raise ValueError("renderer PNG canvas or pixel format is invalid")
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    maximum = (stride + 1) * height
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(bytes(compressed), maximum + 1)
    if len(raw) > maximum or decompressor.unconsumed_tail:
        raise ValueError("renderer PNG decompressed size is excessive")
    raw += decompressor.flush()
    if len(raw) != (stride + 1) * height:
        raise ValueError("renderer PNG decompressed size is invalid")
    rows: list[bytearray] = []
    for y in range(height):
        start = y * (stride + 1)
        filter_type = raw[start]
        source = raw[start + 1 : start + 1 + stride]
        previous = rows[-1] if rows else bytearray(stride)
        row = _unfilter_row(filter_type, source, previous, channels)
        rows.append(row)
    rgba = bytearray(width * height * 4)
    output = 0
    for row in rows:
        for index in range(0, len(row), channels):
            rgba[output : output + 3] = row[index : index + 3]
            rgba[output + 3] = row[index + 3] if channels == 4 else 255
            output += 4
    return _Raster(width=width, height=height, rgba=bytes(rgba))


def _unfilter_row(filter_type: int, source: bytes, previous: bytearray, bpp: int) -> bytearray:
    row = bytearray(len(source))
    for index, value in enumerate(source):
        left = row[index - bpp] if index >= bpp else 0
        above = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        elif filter_type == 4:
            predictor = _paeth(left, above, upper_left)
        else:
            raise ValueError("unsupported PNG filter")
        row[index] = (value + predictor) & 255
    return row


def _paeth(left: int, above: int, upper_left: int) -> int:
    prediction = left + above - upper_left
    distances = (abs(prediction - left), abs(prediction - above), abs(prediction - upper_left))
    return (left, above, upper_left)[distances.index(min(distances))]


def _alpha_mask(raster: _Raster) -> bytearray:
    return bytearray(raster.rgba[index + 3] for index in range(0, len(raster.rgba), 4))


def _mask_bounds(mask: bytearray) -> tuple[int, int, int, int] | None:
    left = SVG_LABEL_LAYOUT_CANVAS_WIDTH
    top = SVG_LABEL_LAYOUT_CANVAS_HEIGHT
    right = -1
    bottom = -1
    for index, alpha in enumerate(mask):
        if alpha < 16:
            continue
        x = index % SVG_LABEL_LAYOUT_CANVAS_WIDTH
        y = index // SVG_LABEL_LAYOUT_CANVAS_WIDTH
        left = min(left, x)
        top = min(top, y)
        right = max(right, x)
        bottom = max(bottom, y)
    if right < 0:
        return None
    return left, top, right, bottom


def _geometry_edge_mask(raster: _Raster) -> bytearray:
    width = raster.width
    height = raster.height
    luminance = bytearray(width * height)
    alpha = bytearray(width * height)
    for pixel in range(width * height):
        offset = pixel * 4
        red, green, blue, opacity = raster.rgba[offset : offset + 4]
        luminance[pixel] = (54 * red + 183 * green + 19 * blue) // 256
        alpha[pixel] = opacity
    edges = bytearray(width * height)
    for y in range(height - 1):
        for x in range(width - 1):
            index = y * width + x
            for neighbor in (index + 1, index + width):
                if (
                    abs(luminance[index] - luminance[neighbor]) >= 24
                    or abs(alpha[index] - alpha[neighbor]) >= 24
                ):
                    edges[index] = 1
                    edges[neighbor] = 1
    return edges


def _validate_canvas_clearance(label: SvgLabelBounds) -> None:
    clearance = SVG_LABEL_LAYOUT_CLEARANCE_PX
    if (
        label.left < clearance
        or label.top < clearance
        or label.right >= SVG_LABEL_LAYOUT_CANVAS_WIDTH - clearance
        or label.bottom >= SVG_LABEL_LAYOUT_CANVAS_HEIGHT - clearance
    ):
        raise SvgLabelLayoutValidationError(
            "SVG_LABEL_OUT_OF_BOUNDS", f"label {label.text!r} lacks canvas clearance"
        )


def _validate_geometry_clearance(
    label: SvgLabelBounds,
    label_mask: bytearray,
    geometry: _Raster,
    edge_mask: bytearray,
) -> None:
    clearance = SVG_LABEL_LAYOUT_CLEARANCE_PX
    left = max(0, label.left - clearance)
    right = min(SVG_LABEL_LAYOUT_CANVAS_WIDTH - 1, label.right + clearance)
    top = max(0, label.top - clearance)
    bottom = min(SVG_LABEL_LAYOUT_CANVAS_HEIGHT - 1, label.bottom + clearance)
    for y in range(top, bottom + 1):
        row = y * SVG_LABEL_LAYOUT_CANVAS_WIDTH
        if any(edge_mask[row + x] for x in range(left, right + 1)):
            raise SvgLabelLayoutValidationError(
                "SVG_LABEL_GEOMETRY_COLLISION",
                f"label {label.text!r} is too close to rendered geometry",
            )
    for index, opacity in enumerate(label_mask):
        if opacity < 16:
            continue
        offset = index * 4
        red, green, blue, geometry_alpha = geometry.rgba[offset : offset + 4]
        luminance = (54 * red + 183 * green + 19 * blue) // 256
        # Uniform light fills are legitimate label backgrounds.  Reject only a dark filled
        # primitive directly beneath glyph pixels; outline/conductor crowding is handled by the
        # edge mask above.
        if geometry_alpha >= 16 and luminance < 128:
            raise SvgLabelLayoutValidationError(
                "SVG_LABEL_GEOMETRY_COLLISION",
                f"label {label.text!r} overlaps rendered geometry",
            )


def _validate_label_clearance(labels: tuple[SvgLabelBounds, ...]) -> None:
    clearance = SVG_LABEL_LAYOUT_CLEARANCE_PX
    for index, left in enumerate(labels):
        for right in labels[index + 1 :]:
            separated = (
                left.right + clearance < right.left
                or right.right + clearance < left.left
                or left.bottom + clearance < right.top
                or right.bottom + clearance < left.top
            )
            if not separated:
                raise SvgLabelLayoutValidationError(
                    "SVG_LABEL_LABEL_COLLISION",
                    f"labels {left.text!r} and {right.text!r} lack clearance",
                )
