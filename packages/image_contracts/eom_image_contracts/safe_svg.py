"""Pure, fail-closed SVG overlay grammar shared by contracts and rasterization."""

from __future__ import annotations

import html
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from typing import Final

SVG_NAMESPACE: Final = "http://www.w3.org/2000/svg"
SVG_MAX_ELEMENTS: Final = 256
SVG_MAX_DEPTH: Final = 8
SVG_LATIN_FONT_FAMILY: Final = "Century Old Style"
SVG_MATH_FONT_FAMILY: Final = "DejaVu Serif"
SVG_KOREAN_FONT_FAMILY: Final = "SM JGothic Std, Noto Sans CJK KR"
SVG_LEGACY_KOREAN_FONT_FAMILY: Final = "Droid Sans Fallback"
SVG_ALLOWED_FONT_FAMILIES: Final = frozenset(
    {
        SVG_KOREAN_FONT_FAMILY,
        SVG_LATIN_FONT_FAMILY,
        SVG_MATH_FONT_FAMILY,
        SVG_LEGACY_KOREAN_FONT_FAMILY,
    }
)

_KOREAN_FONT_FAMILIES = frozenset({SVG_KOREAN_FONT_FAMILY, SVG_LEGACY_KOREAN_FONT_FAMILY})
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
_SAFE_INHERITED_TEXT_ATTRIBUTES = frozenset(
    {
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "text-anchor",
        "dominant-baseline",
    }
)
_TAG_ATTRIBUTES = {
    "g": _SAFE_INHERITED_TEXT_ATTRIBUTES,
    "rect": frozenset({"x", "y", "width", "height", "rx", "ry"}),
    "circle": frozenset({"cx", "cy", "r"}),
    "ellipse": frozenset({"cx", "cy", "rx", "ry"}),
    "line": frozenset({"x1", "y1", "x2", "y2"}),
    "polyline": frozenset({"points"}),
    "polygon": frozenset({"points"}),
    "path": frozenset({"d"}),
    "text": frozenset(
        {
            "x",
            "y",
            "font-size",
            "font-family",
            "font-style",
            "font-weight",
            "text-anchor",
            "dominant-baseline",
        }
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


def sanitize_svg_overlay(source: str, required_labels: tuple[str, ...]) -> str:
    """Reconstruct the one reviewed overlay subset and return canonical elements."""

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
            _sanitize_element(
                child,
                depth=1,
                counter=counter,
                labels=labels,
                inherited_font_family=None,
                inherited_font_style="normal",
            )
            for child in root
        )
        if root.text is not None and root.text.strip():
            raise ValueError("SVG overlay root text is invalid")
        if root.tail is not None and root.tail.strip():
            raise ValueError("SVG overlay root tail text is invalid")
    elif _svg_tag_name(root) in _ALLOWED_TAGS:
        clean = _sanitize_element(
            root,
            depth=1,
            counter=counter,
            labels=labels,
            inherited_font_family=None,
            inherited_font_style="normal",
        )
    else:
        raise ValueError("SVG overlay root namespace is invalid")
    if not set(required_labels).issubset(labels):
        raise ValueError("SVG overlay is missing a required label")
    return clean


def _sanitize_element(
    element: ET.Element,
    *,
    depth: int,
    counter: list[int],
    labels: set[str],
    inherited_font_family: str | None,
    inherited_font_style: str,
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
    effective_font_family = attributes.get("font-family", inherited_font_family)
    effective_font_style = attributes.get("font-style", inherited_font_style)
    if effective_font_style == "italic" and effective_font_family != SVG_LATIN_FONT_FAMILY:
        raise ValueError("SVG italic style requires the fixed Latin font family")
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
        if effective_font_family is None:
            raise ValueError("SVG text requires an explicit fixed font family")
        if _contains_hangul(text) and effective_font_family not in _KOREAN_FONT_FAMILIES:
            raise ValueError("SVG Korean text requires the fixed Korean font family")
        labels.add(text)
    elif element.text is not None and element.text.strip():
        raise ValueError("SVG non-text element contains text")
    if element.tail is not None and element.tail.strip():
        raise ValueError("SVG element tail text is invalid")
    rendered_attributes = "".join(
        f' {name}="{html.escape(value, quote=True)}"' for name, value in sorted(attributes.items())
    )
    children = "".join(
        _sanitize_element(
            child,
            depth=depth + 1,
            counter=counter,
            labels=labels,
            inherited_font_family=effective_font_family,
            inherited_font_style=effective_font_style,
        )
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
    if name == "stroke-linecap":
        if value not in {"butt", "round", "square"}:
            raise ValueError("SVG line cap is invalid")
        return value
    if name == "stroke-linejoin":
        if value not in {"miter", "round", "bevel"}:
            raise ValueError("SVG line join is invalid")
        return value
    if name == "font-family":
        if value not in SVG_ALLOWED_FONT_FAMILIES:
            raise ValueError("SVG font family is invalid")
        return value
    if name == "font-style":
        if value not in {"normal", "italic"}:
            raise ValueError("SVG font style is invalid")
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
    if name in {"width", "height", "r", "rx", "ry", "stroke-width", "font-size"} and (numeric < 0):
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


def _contains_hangul(value: str) -> bool:
    return any(
        "\u1100" <= character <= "\u11ff"
        or "\u3130" <= character <= "\u318f"
        or "\uac00" <= character <= "\ud7a3"
        for character in value
    )
