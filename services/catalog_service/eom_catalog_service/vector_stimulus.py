"""Fail-closed SVG validation, deterministic composition, and fixed rasterization."""

from __future__ import annotations

import hashlib
import html
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, NamedTuple

from eom_image_contracts import sanitize_svg_overlay
from eom_workflow.models import (
    GeneratedLineGraphDrawingV5,
    GeneratedLineGraphDrawingV6,
    GeneratedVectorDrawingV5,
    GeneratedVectorDrawingV6,
)

SVG_MEMBER: Final = "generated-stimulus.svg"
SVG_MEDIA_TYPE: Final = "image/svg+xml"
SVG_WIDTH: Final = 800
SVG_HEIGHT: Final = 500
SVG_MAX_BYTES: Final = 96 * 1024
SVG_RASTERIZER: Final = Path("/usr/bin/rsvg-convert")
SVG_FONT_PROFILE: Final = "eom-content-team-diagram-fonts/1.0"
SVG_FONT_ROOT: Final = Path("/usr/local/share/fonts/eom")
SVG_FONT: Final = SVG_FONT_ROOT / "SMJGothicStd-Regular.otf"
SVG_KOREAN_FALLBACK_FONT: Final = SVG_FONT_ROOT / "NotoSansCJKkr-Regular.otf"
SVG_FONT_FAMILY: Final = "SM JGothic Std, Noto Sans CJK KR"
SVG_LATIN_FONT: Final = SVG_FONT_ROOT / "CenturyOldStyle-Regular.otf"
SVG_LATIN_ITALIC_FONT: Final = SVG_FONT_ROOT / "CenturyOldStyle-Italic.otf"
SVG_LATIN_FONT_FAMILY: Final = "Century Old Style"
SVG_MATH_FONT: Final = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
SVG_MATH_FONT_FAMILY: Final = "DejaVu Serif"
SVG_LEGACY_FONT: Final = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
SVG_LEGACY_FONT_FAMILY: Final = "Droid Sans Fallback"
SVG_RENDERER_CONTRACT: Final = "eom-safe-svg-compositor/1.1"


class _FixedSvgFont(NamedTuple):
    role: str
    family: str
    style: str
    path: Path
    expected_sha256: str


_FIXED_SVG_FONTS: Final = (
    _FixedSvgFont(
        "korean_label",
        "SM JGothic Std",
        "regular",
        SVG_FONT,
        "sha256:9200e1e46cca77f0ff9481c5345c3333caf22d50487418df74f830e4221adea1",
    ),
    _FixedSvgFont(
        "korean_fallback",
        "Noto Sans CJK KR",
        "regular",
        SVG_KOREAN_FALLBACK_FONT,
        "sha256:6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a",
    ),
    _FixedSvgFont(
        "latin_label",
        SVG_LATIN_FONT_FAMILY,
        "regular",
        SVG_LATIN_FONT,
        "sha256:7f9420403e10e7e74f002fbb48e8034d48f64cbdbef556d4f964b266043de338",
    ),
    _FixedSvgFont(
        "latin_label",
        SVG_LATIN_FONT_FAMILY,
        "italic",
        SVG_LATIN_ITALIC_FONT,
        "sha256:44b00cbdab9fdb7b4307db79784c5b90cbc52c5ffb0add32ac8239d73e567809",
    ),
    _FixedSvgFont(
        "math_label",
        SVG_MATH_FONT_FAMILY,
        "regular",
        SVG_MATH_FONT,
        "sha256:8f2c103bfa3fd5de71f1b92b18f21906b5a26871fb7e19a9a4c9af539c3cc7ab",
    ),
    _FixedSvgFont(
        "legacy_korean_compatibility",
        SVG_LEGACY_FONT_FAMILY,
        "regular",
        SVG_LEGACY_FONT,
        "sha256:acb6440a713d880a13a21b468ba7cd43f5a2b2934972e51be791c880730777b8",
    ),
)


@dataclass(frozen=True)
class RenderedVectorStimulus:
    svg_path: Path
    png_path: Path
    renderer_contract: str
    renderer_version: str
    renderer_sha256: str
    font_sha256: str
    font_manifest_sha256: str


@dataclass(frozen=True)
class SvgRendererProvenance:
    renderer_version: str
    renderer_sha256: str
    font_sha256: str
    font_manifest_sha256: str


def compose_vector_svg(
    drawing: (
        GeneratedLineGraphDrawingV5
        | GeneratedVectorDrawingV5
        | GeneratedLineGraphDrawingV6
        | GeneratedVectorDrawingV6
    ),
) -> bytes:
    """Return canonical, background-composed SVG bytes from one deterministic drawing."""

    if drawing.production_route != "DETERMINISTIC_SVG":
        raise ValueError("generated background provider is not deployed")
    if isinstance(drawing, GeneratedLineGraphDrawingV5 | GeneratedLineGraphDrawingV6):
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


def compose_vector_overlay_svg(
    drawing: GeneratedVectorDrawingV5 | GeneratedVectorDrawingV6,
) -> bytes:
    """Return the canonical transparent overlay for local raster composition."""

    if drawing.production_route not in {
        "LOCAL_GENERATIVE_BACKGROUND",
        "HYBRID_LOCAL_GENERATIVE",
    }:
        raise ValueError("local image overlay route is invalid")
    overlay = sanitize_svg_overlay(drawing.svg_overlay, drawing.required_labels)
    payload = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
        f'viewBox="0 0 800 500">{overlay}</svg>\n'
    ).encode()
    if len(payload) > SVG_MAX_BYTES:
        raise ValueError("composed SVG exceeds the bounded size")
    return payload


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
    if (
        SVG_RASTERIZER.is_symlink()
        or not stat.S_ISREG(renderer.st_mode)
        or renderer.st_uid != 0
        or stat.S_IMODE(renderer.st_mode) & 0o022
        or not os.access(SVG_RASTERIZER, os.X_OK)
    ):
        raise ValueError("fixed SVG rasterizer metadata is invalid")
    font_identities: list[int] = []
    for fixed in _FIXED_SVG_FONTS:
        font = fixed.path.lstat()
        if (
            fixed.path.is_symlink()
            or not stat.S_ISREG(font.st_mode)
            or font.st_uid != 0
            or stat.S_IMODE(font.st_mode) != 0o644
            or not os.access(fixed.path, os.R_OK)
        ):
            raise ValueError("fixed SVG font metadata is invalid")
        font_identities.extend(
            (font.st_dev, font.st_ino, font.st_size, font.st_mtime_ns, font.st_ctime_ns)
        )
    return _cached_svg_renderer_provenance(
        renderer.st_dev,
        renderer.st_ino,
        renderer.st_size,
        renderer.st_mtime_ns,
        renderer.st_ctime_ns,
        *font_identities,
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
    font_hashes = tuple(_sha256_file(font.path) for font in _FIXED_SVG_FONTS)
    if any(
        actual != font.expected_sha256
        for font, actual in zip(_FIXED_SVG_FONTS, font_hashes, strict=True)
    ):
        raise ValueError("fixed SVG font hash is invalid")
    font_manifest = {
        "schema_version": "1.0",
        "profile": SVG_FONT_PROFILE,
        "fonts": [
            {
                "role": font.role,
                "family": font.family,
                "style": font.style,
                "sha256": font.expected_sha256,
            }
            for font in _FIXED_SVG_FONTS
        ],
    }
    manifest_bytes = json.dumps(
        font_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SvgRendererProvenance(
        renderer_version=version,
        renderer_sha256=_sha256_file(SVG_RASTERIZER),
        font_sha256=font_hashes[0],
        font_manifest_sha256="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


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


def _contains_hangul(value: str) -> bool:
    return any(
        "\u1100" <= character <= "\u11ff"
        or "\u3130" <= character <= "\u318f"
        or "\uac00" <= character <= "\ud7a3"
        for character in value
    )


def _label_font_family(value: str) -> str:
    if _contains_hangul(value):
        return SVG_FONT_FAMILY
    if any("\u0370" <= character <= "\u03ff" for character in value):
        return SVG_MATH_FONT_FAMILY
    return SVG_LATIN_FONT_FAMILY


def _line_graph_overlay(
    drawing: GeneratedLineGraphDrawingV5 | GeneratedLineGraphDrawingV6,
) -> str:
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
        f'<text fill="#1f2937" font-family="{_label_font_family(drawing.x_axis_label)}" '
        f'font-size="18" '
        f'text-anchor="middle" '
        f'x="420" y="475">{html.escape(drawing.x_axis_label)}</text>'
        f'<text fill="#1f2937" font-family="{_label_font_family(drawing.y_axis_label)}" '
        f'font-size="18" x="20" y="35">'
        f"{html.escape(drawing.y_axis_label)}</text>"
    )
    return axes + polyline + markers + labels
