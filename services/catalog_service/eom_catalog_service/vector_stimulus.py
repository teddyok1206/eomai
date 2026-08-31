"""Fail-closed SVG validation, deterministic composition, and fixed rasterization."""

from __future__ import annotations

import hashlib
import html
import math
import os
import re
import stat
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from eom_workflow.models import GeneratedLineGraphDrawingV5, GeneratedVectorDrawingV5

SVG_MEMBER: Final = "generated-stimulus.svg"
SVG_MEDIA_TYPE: Final = "image/svg+xml"
SVG_WIDTH: Final = 800
SVG_HEIGHT: Final = 500
SVG_MAX_BYTES: Final = 96 * 1024
SVG_MAX_ELEMENTS: Final = 256
SVG_MAX_DEPTH: Final = 8
SVG_NAMESPACE: Final = "http://www.w3.org/2000/svg"
SVG_RASTERIZER: Final = Path("/usr/bin/rsvg-convert")
SVG_FONT: Final = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
SVG_FONT_FAMILY: Final = "Droid Sans Fallback"
SVG_RENDERER_CONTRACT: Final = "eom-safe-svg-compositor/1.0"

_FORBIDDEN_MARKERS = (
    "<!doctype",
    "<!entity",
    "<script",
    "<style",
    "foreignobject",
    "javascript:",
    "data:",
    "url(",
)
_ALLOWED_TAGS = frozenset(
    {"g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path", "text"}
)
_COMMON_ATTRIBUTES = frozenset(
    {
        "fill",
        "stroke",
        "stroke-width",
        "opacity",
        "stroke-linecap",
        "stroke-linejoin",
        "transform",
    }
)
_TAG_ATTRIBUTES = {
    "g": frozenset({"font-family", "font-size"}),
    "rect": frozenset({"x", "y", "width", "height", "rx", "ry"}),
    "circle": frozenset({"cx", "cy", "r"}),
    "ellipse": frozenset({"cx", "cy", "rx", "ry"}),
    "line": frozenset({"x1", "y1", "x2", "y2"}),
    "polyline": frozenset({"points"}),
    "polygon": frozenset({"points"}),
    "path": frozenset({"d"}),
    "text": frozenset(
        {"x", "y", "font-size", "font-family", "font-weight", "text-anchor", "dominant-baseline"}
    ),
}
_COLOR_NAMES = frozenset(
    {
        "none",
        "black",
        "white",
        "gray",
        "red",
        "green",
        "blue",
        "orange",
        "yellow",
        "brown",
        "purple",
    }
)
_NUMBER_TOKEN = r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
_NUMBER = re.compile(rf"^{_NUMBER_TOKEN}$")
_NUMBER_LIST = re.compile(rf"^{_NUMBER_TOKEN}(?:(?:[ \t]*,[ \t]*|[ \t]+){_NUMBER_TOKEN})*$")
_POINTS = re.compile(r"^[+\-0-9., \t]+$")
_PATH = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9+., eE\-]+$")
_TRANSFORM_ITEM = re.compile(r"(translate|scale|rotate)\(([^()]*)\)")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True)
class RenderedVectorStimulus:
    svg_path: Path
    png_path: Path
    renderer_contract: str
    renderer_version: str
    renderer_sha256: str
    font_sha256: str


@dataclass(frozen=True)
class SvgRendererProvenance:
    renderer_version: str
    renderer_sha256: str
    font_sha256: str


def compose_vector_svg(
    drawing: GeneratedLineGraphDrawingV5 | GeneratedVectorDrawingV5,
) -> bytes:
    """Return canonical, background-composed SVG bytes from one validated V5 drawing."""

    if drawing.production_route != "DETERMINISTIC_SVG":
        raise ValueError("generated background provider is not deployed")
    if isinstance(drawing, GeneratedLineGraphDrawingV5):
        overlay = _line_graph_overlay(drawing)
    else:
        overlay = sanitize_svg_overlay(drawing.svg_overlay, drawing.required_labels)
    background = _background_elements(drawing.background_style)
    body = "".join((*background, overlay))
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        f'viewBox="0 0 800 500">{body}</svg>\n'
    ).encode()
    if len(payload) > SVG_MAX_BYTES:
        raise ValueError("composed SVG exceeds the bounded size")
    return payload


def sanitize_svg_overlay(source: str, required_labels: tuple[str, ...]) -> str:
    """Reconstruct the reviewed SVG subset and return canonical overlay elements only."""

    encoded = source.encode("utf-8")
    if not encoded or len(encoded) > 65_536:
        raise ValueError("SVG overlay size is invalid")
    lowered = source.casefold()
    if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
        raise ValueError("SVG overlay contains forbidden active or external content")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        root = _parse_svg_fragment(source, exc)
    counter = [0]
    labels: set[str] = set()
    if root.tag == f"{{{SVG_NAMESPACE}}}svg":
        if root.attrib != {"width": "800", "height": "500", "viewBox": "0 0 800 500"}:
            raise ValueError("SVG overlay canvas contract is invalid")
        clean = "".join(
            _sanitize_element(child, depth=1, counter=counter, labels=labels) for child in root
        )
        if root.text is not None and root.text.strip():
            raise ValueError("SVG overlay root text is invalid")
        if root.tail is not None and root.tail.strip():
            raise ValueError("SVG overlay root tail text is invalid")
    elif _svg_tag_name(root) in _ALLOWED_TAGS:
        clean = _sanitize_element(root, depth=1, counter=counter, labels=labels)
    else:
        raise ValueError("SVG overlay root namespace is invalid")
    if not set(required_labels).issubset(labels):
        raise ValueError("SVG overlay is missing a required label")
    return clean


def write_vector_svg(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        validate_vector_svg_file(path, payload)
        return
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o640
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
    validate_vector_svg_file(path, payload)


def validate_vector_svg_file(path: Path, expected: bytes | None = None) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > SVG_MAX_BYTES
        or stat.S_IMODE(metadata.st_mode) != 0o640
    ):
        raise ValueError("generated stimulus SVG metadata is invalid")
    payload = path.read_bytes()
    if expected is not None and payload != expected:
        raise ValueError("generated stimulus SVG bytes changed")
    if not payload.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"') or not payload.endswith(
        b"</svg>\n"
    ):
        raise ValueError("generated stimulus SVG structure is invalid")


def rasterize_vector_svg(svg_path: Path, png_path: Path) -> SvgRendererProvenance:
    """Rasterize one sanitized SVG through the fixed Ubuntu librsvg command boundary."""

    provenance = svg_renderer_provenance()
    if png_path.exists() or png_path.is_symlink():
        raise ValueError("generated stimulus PNG target already exists")
    completed = subprocess.run(
        [
            str(SVG_RASTERIZER),
            "--format=png",
            "--width=800",
            "--height=500",
            str(svg_path),
        ],
        cwd=svg_path.parent,
        env={"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or not 0 < len(completed.stdout) <= 2 * 1024 * 1024:
        raise ValueError("fixed SVG rasterizer failed")
    descriptor = os.open(
        png_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o640,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(completed.stdout)
            output.flush()
            os.fsync(output.fileno())
        os.fchmod(descriptor, 0o640)
    finally:
        os.close(descriptor)
    return provenance


def svg_renderer_provenance() -> SvgRendererProvenance:
    """Validate fixed renderer/font identities and return their immutable byte provenance."""

    renderer = SVG_RASTERIZER.lstat()
    font = SVG_FONT.lstat()
    if (
        SVG_RASTERIZER.is_symlink()
        or not stat.S_ISREG(renderer.st_mode)
        or renderer.st_uid != 0
        or stat.S_IMODE(renderer.st_mode) & 0o022
        or not os.access(SVG_RASTERIZER, os.X_OK)
    ):
        raise ValueError("fixed SVG rasterizer metadata is invalid")
    if (
        SVG_FONT.is_symlink()
        or not stat.S_ISREG(font.st_mode)
        or font.st_uid != 0
        or stat.S_IMODE(font.st_mode) & 0o022
        or not os.access(SVG_FONT, os.R_OK)
    ):
        raise ValueError("fixed SVG font metadata is invalid")
    return _cached_svg_renderer_provenance(
        renderer.st_dev,
        renderer.st_ino,
        renderer.st_size,
        renderer.st_mtime_ns,
        renderer.st_ctime_ns,
        font.st_dev,
        font.st_ino,
        font.st_size,
        font.st_mtime_ns,
        font.st_ctime_ns,
    )


@lru_cache(maxsize=4)
def _cached_svg_renderer_provenance(*identity: int) -> SvgRendererProvenance:
    del identity
    completed = subprocess.run(
        [str(SVG_RASTERIZER), "--version"],
        cwd="/",
        env={"HOME": "/nonexistent", "LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
    )
    version = completed.stdout.decode("ascii", errors="strict").strip()
    if completed.returncode != 0 or not version.startswith("rsvg-convert version 2.58."):
        raise ValueError("fixed SVG rasterizer version is invalid")
    return SvgRendererProvenance(
        renderer_version=version,
        renderer_sha256=_sha256_file(SVG_RASTERIZER),
        font_sha256=_sha256_file(SVG_FONT),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sanitize_element(
    element: ET.Element,
    *,
    depth: int,
    counter: list[int],
    labels: set[str],
) -> str:
    if depth > SVG_MAX_DEPTH:
        raise ValueError("SVG overlay nesting is too deep")
    counter[0] += 1
    if counter[0] > SVG_MAX_ELEMENTS:
        raise ValueError("SVG overlay has too many elements")
    tag = _svg_tag_name(element)
    if tag not in _ALLOWED_TAGS:
        raise ValueError("SVG overlay element is not allowed")
    allowed = _COMMON_ATTRIBUTES | _TAG_ATTRIBUTES[tag]
    if any(name not in allowed for name in element.attrib):
        raise ValueError("SVG overlay attribute is not allowed")
    attributes = {
        name: _validate_attribute(tag, name, value) for name, value in element.attrib.items()
    }
    text = ""
    if tag == "text":
        if tuple(element):
            raise ValueError("SVG text cannot contain child elements")
        text = (element.text or "").strip()
        if (
            not text
            or len(text) > 256
            or text != unicodedata.normalize("NFC", text)
            or any(unicodedata.category(character).startswith("C") for character in text)
        ):
            raise ValueError("SVG text value is unsafe")
        labels.add(text)
    elif element.text is not None and element.text.strip():
        raise ValueError("SVG non-text element contains text")
    if element.tail is not None and element.tail.strip():
        raise ValueError("SVG element tail text is invalid")
    rendered_attributes = "".join(
        f' {name}="{html.escape(value, quote=True)}"' for name, value in sorted(attributes.items())
    )
    children = "".join(
        _sanitize_element(child, depth=depth + 1, counter=counter, labels=labels)
        for child in element
    )
    return f"<{tag}{rendered_attributes}>{html.escape(text)}{children}</{tag}>"


def _parse_svg_fragment(source: str, original: ET.ParseError) -> ET.Element:
    try:
        return ET.fromstring(
            f'<svg xmlns="{SVG_NAMESPACE}" width="800" height="500" '
            f'viewBox="0 0 800 500">{source}</svg>'
        )
    except ET.ParseError:
        raise ValueError("SVG overlay XML is invalid") from original


def _svg_tag_name(element: ET.Element) -> str:
    if element.tag.startswith(f"{{{SVG_NAMESPACE}}}"):
        return element.tag.removeprefix(f"{{{SVG_NAMESPACE}}}")
    if element.tag.startswith("{"):
        raise ValueError("SVG overlay element namespace is invalid")
    return element.tag


def _validate_attribute(tag: str, name: str, value: str) -> str:
    if not value or value != value.strip() or len(value) > 8192:
        raise ValueError("SVG attribute value is invalid")
    if name in {"fill", "stroke"}:
        if value not in _COLOR_NAMES and _COLOR.fullmatch(value) is None:
            raise ValueError("SVG color is invalid")
        return value.lower()
    if name in {"stroke-linecap"}:
        if value not in {"butt", "round", "square"}:
            raise ValueError("SVG line cap is invalid")
        return value
    if name in {"stroke-linejoin"}:
        if value not in {"miter", "round", "bevel"}:
            raise ValueError("SVG line join is invalid")
        return value
    if name == "font-family":
        if value != SVG_FONT_FAMILY:
            raise ValueError("SVG font family is invalid")
        return value
    if name == "font-weight":
        if value not in {"normal", "bold", "400", "700"}:
            raise ValueError("SVG font weight is invalid")
        return value
    if name == "text-anchor":
        if value not in {"start", "middle", "end"}:
            raise ValueError("SVG text anchor is invalid")
        return value
    if name == "dominant-baseline":
        if value not in {"auto", "middle", "central", "hanging"}:
            raise ValueError("SVG baseline is invalid")
        return value
    if name == "transform":
        return _canonical_transform(value)
    if name == "points":
        if len(value) > 4096 or _POINTS.fullmatch(value) is None:
            raise ValueError("SVG point list is invalid")
        numbers = _parse_number_list(value)
        if (
            len(numbers) < 4
            or len(numbers) % 2
            or any(not _bounded_number(number) for number in numbers)
        ):
            raise ValueError("SVG point list coordinates are invalid")
        return " ".join(
            numbers[index] + "," + numbers[index + 1] for index in range(0, len(numbers), 2)
        )
    if name == "d":
        if len(value) > 8192 or _PATH.fullmatch(value) is None:
            raise ValueError("SVG path data is invalid")
        path_numbers = re.findall(
            r"[+\-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+\-]?[0-9]+)?",
            value,
        )
        if any(not _bounded_number(number) for number in path_numbers):
            raise ValueError("SVG path coordinate is invalid")
        return " ".join(value.split())
    if _NUMBER.fullmatch(value) is None or not _bounded_number(value):
        raise ValueError(f"SVG numeric attribute is invalid: {tag}.{name}")
    numeric = float(value)
    if name in {"width", "height", "r", "rx", "ry", "stroke-width", "font-size"} and numeric < 0:
        raise ValueError("SVG size attribute cannot be negative")
    if name == "opacity" and not 0 <= numeric <= 1:
        raise ValueError("SVG opacity is invalid")
    if name == "stroke-width" and numeric > 40:
        raise ValueError("SVG stroke width is excessive")
    if name == "font-size" and not 8 <= numeric <= 72:
        raise ValueError("SVG font size is invalid")
    return _canonical_number(numeric)


def _parse_number_list(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if not stripped or _NUMBER_LIST.fullmatch(stripped) is None:
        raise ValueError("SVG numeric list is invalid")
    return tuple(re.findall(_NUMBER_TOKEN, stripped))


def _canonical_transform(value: str) -> str:
    if len(value) > 256:
        raise ValueError("SVG transform is invalid")
    rendered: list[str] = []
    position = 0
    for match in _TRANSFORM_ITEM.finditer(value):
        if value[position : match.start()].strip():
            raise ValueError("SVG transform is invalid")
        operation = match.group(1)
        numbers = _parse_number_list(match.group(2))
        expected_counts = {"translate": {1, 2}, "scale": {1, 2}, "rotate": {1, 3}}
        if len(numbers) not in expected_counts[operation] or any(
            not _bounded_number(number) for number in numbers
        ):
            raise ValueError("SVG transform arguments are invalid")
        rendered.append(
            f"{operation}({','.join(_canonical_number(float(number)) for number in numbers)})"
        )
        position = match.end()
    if value[position:].strip() or not rendered or len(rendered) > 4:
        raise ValueError("SVG transform is invalid")
    return " ".join(rendered)


def _bounded_number(value: str) -> bool:
    try:
        number = float(value)
    except ValueError:
        return False
    return math.isfinite(number) and -10_000 <= number <= 10_000


def _canonical_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, ".6f").rstrip("0").rstrip(".")


def _background_elements(style: str) -> tuple[str, ...]:
    base = '<rect fill="#ffffff" height="500" width="800" x="0" y="0"></rect>'
    if style == "WHITE":
        return (base,)
    if style == "PAPER":
        return (
            '<rect fill="#fffdf5" height="500" width="800" x="0" y="0"></rect>',
            '<rect fill="none" height="480" stroke="#d1d5db" stroke-width="2" '
            'width="780" x="10" y="10"></rect>',
        )
    if style == "GRID":
        lines = tuple(
            f'<line opacity="0.5" stroke="#e5e7eb" stroke-width="1" x1="{x}" '
            f'x2="{x}" y1="0" y2="500"></line>'
            for x in range(0, 801, 50)
        ) + tuple(
            f'<line opacity="0.5" stroke="#e5e7eb" stroke-width="1" x1="0" '
            f'x2="800" y1="{y}" y2="{y}"></line>'
            for y in range(0, 501, 50)
        )
        return (base, *lines)
    raise ValueError("SVG background style is invalid")


def _line_graph_overlay(drawing: GeneratedLineGraphDrawingV5) -> str:
    left, top, right, bottom = 90, 55, 750, 420
    minimum_x, maximum_x = min(drawing.x_values), max(drawing.x_values)
    minimum_y, maximum_y = min(drawing.y_values), max(drawing.y_values)
    if minimum_y == maximum_y:
        minimum_y -= 1
        maximum_y += 1
    points = tuple(
        (
            left + (value_x - minimum_x) * (right - left) // (maximum_x - minimum_x),
            bottom - (value_y - minimum_y) * (bottom - top) // (maximum_y - minimum_y),
        )
        for value_x, value_y in zip(drawing.x_values, drawing.y_values, strict=True)
    )
    colors = {"blue": "#2563eb", "green": "#16a34a", "orange": "#ea580c"}
    color = colors[drawing.stroke_color]
    axes = (
        '<line stroke="#1f2937" stroke-width="3" x1="90" x2="750" y1="420" y2="420"></line>'
        '<line stroke="#1f2937" stroke-width="3" x1="90" x2="90" y1="420" y2="55"></line>'
    )
    polyline = (
        f'<polyline fill="none" points="{" ".join(f"{x},{y}" for x, y in points)}" '
        f'stroke="{color}" stroke-linejoin="round" stroke-width="4"></polyline>'
    )
    if drawing.point_style == "circle":
        markers = "".join(
            f'<circle cx="{x}" cy="{y}" fill="{color}" r="7"></circle>' for x, y in points
        )
    else:
        markers = "".join(
            f'<rect fill="{color}" height="12" width="12" x="{x - 6}" y="{y - 6}"></rect>'
            for x, y in points
        )
    labels = (
        f'<text fill="#1f2937" font-family="{SVG_FONT_FAMILY}" font-size="18" '
        f'text-anchor="middle" '
        f'x="420" y="475">{html.escape(drawing.x_axis_label)}</text>'
        f'<text fill="#1f2937" font-family="{SVG_FONT_FAMILY}" font-size="18" x="20" y="35">'
        f"{html.escape(drawing.y_axis_label)}</text>"
    )
    return axes + polyline + markers + labels
