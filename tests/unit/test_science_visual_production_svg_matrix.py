from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from eom_catalog_service.generated_stimulus import (
    render_generated_vector_stimulus,
    validate_generated_png,
)
from eom_catalog_service.science_visual_subjects import SUBJECT_DEFINITIONS
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.vector_stimulus import SVG_FONT, SVG_RASTERIZER
from eom_workflow.models import GeneratedVectorDrawingV5

PRODUCTION_PRIMITIVES = frozenset(
    {
        "APPARATUS",
        "AXIS_PLOT",
        "CELL_CROSS_SECTION",
        "CIRCUIT",
        "CONTENT_TABLE",
        "FLOW_DIAGRAM",
        "GENERIC_LABELLED_DIAGRAM",
        "GEOLOGIC_SECTION",
        "MAP_BOUNDARY",
        "ORBITAL_SYSTEM",
        "PARTICLE_SYSTEM",
        "RAY_DIAGRAM",
        "TIMELINE",
        "VECTOR_FIELD",
    }
)

_FONT = "Century Old Style"
_KOREAN_FONT = "SM JGothic Std, Noto Sans CJK KR"


def _text(x: int, y: int, value: str, *, korean: bool = False) -> str:
    family = _KOREAN_FONT if korean else _FONT
    return (
        f'<text fill="#000000" font-family="{family}" font-size="20" x="{x}" y="{y}">{value}</text>'
    )


def _representative_overlay(primitive: str) -> tuple[str, tuple[str, ...]]:
    shapes: dict[str, tuple[str, tuple[str, ...]]] = {
        "APPARATUS": (
            '<path d="M260 90 L260 340 Q260 410 340 410 L460 410 '
            'Q540 410 540 340 L540 90" fill="none" stroke="#000000" '
            'stroke-width="5"></path>'
            '<line x1="240" y1="90" x2="560" y2="90" stroke="#000000" '
            'stroke-width="5"></line>'
            '<rect x="270" y="275" width="260" height="95" fill="#E5E7EB" '
            'stroke="#000000" stroke-width="3"></rect>' + _text(330, 455, "beaker"),
            ("beaker",),
        ),
        "AXIS_PLOT": (
            '<line x1="120" y1="410" x2="710" y2="410" stroke="#000000" '
            'stroke-width="4"></line>'
            '<line x1="140" y1="440" x2="140" y2="70" stroke="#000000" '
            'stroke-width="4"></line>'
            '<polyline points="140,390 260,340 380,350 520,220 670,120" fill="none" '
            'stroke="#000000" stroke-width="5"></polyline>'
            + _text(680, 450, "x")
            + _text(90, 80, "y"),
            ("x", "y"),
        ),
        "CELL_CROSS_SECTION": (
            '<ellipse cx="400" cy="250" rx="260" ry="175" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="6"></ellipse>'
            '<circle cx="400" cy="250" r="80" fill="#E5E7EB" stroke="#000000" '
            'stroke-width="4"></circle>'
            '<ellipse cx="250" cy="185" rx="50" ry="22" fill="none" '
            'stroke="#000000" stroke-width="3"></ellipse>' + _text(370, 255, "nucleus"),
            ("nucleus",),
        ),
        "CIRCUIT": (
            '<rect x="145" y="105" width="510" height="290" fill="none" '
            'stroke="#000000" stroke-width="5"></rect>'
            '<line x1="245" y1="215" x2="245" y2="285" stroke="#000000" '
            'stroke-width="4"></line>'
            '<line x1="275" y1="230" x2="275" y2="270" stroke="#000000" '
            'stroke-width="9"></line>'
            '<rect x="390" y="210" width="135" height="80" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></rect>' + _text(435, 260, "R"),
            ("R",),
        ),
        "CONTENT_TABLE": (
            '<rect x="120" y="90" width="560" height="320" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></rect>'
            '<line x1="120" y1="170" x2="680" y2="170" stroke="#000000" '
            'stroke-width="3"></line>'
            '<line x1="310" y1="90" x2="310" y2="410" stroke="#000000" '
            'stroke-width="3"></line>' + _text(160, 140, "sample") + _text(390, 140, "value"),
            ("sample", "value"),
        ),
        "FLOW_DIAGRAM": (
            '<rect x="80" y="190" width="170" height="120" rx="18" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></rect>'
            '<rect x="315" y="190" width="170" height="120" rx="18" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></rect>'
            '<rect x="550" y="190" width="170" height="120" rx="18" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></rect>'
            '<line x1="250" y1="250" x2="315" y2="250" stroke="#000000" '
            'stroke-width="4"></line>'
            '<line x1="485" y1="250" x2="550" y2="250" stroke="#000000" '
            'stroke-width="4"></line>'
            + _text(130, 260, "input")
            + _text(350, 260, "process")
            + _text(590, 260, "output"),
            ("input", "process", "output"),
        ),
        "GENERIC_LABELLED_DIAGRAM": (
            '<circle cx="250" cy="160" r="60" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="5"></circle>'
            '<rect x="430" y="245" width="210" height="125" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="5"></rect>'
            '<line x1="305" y1="195" x2="430" y2="270" stroke="#000000" '
            'stroke-width="4"></line>' + _text(215, 165, "A") + _text(520, 315, "B"),
            ("A", "B"),
        ),
        "GEOLOGIC_SECTION": (
            '<polygon points="90,150 710,105 710,410 90,410" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="5"></polygon>'
            '<line x1="90" y1="235" x2="710" y2="205" stroke="#000000" '
            'stroke-width="5"></line>'
            '<line x1="90" y1="325" x2="710" y2="315" stroke="#000000" '
            'stroke-width="5"></line>' + _text(120, 205, "layer 1") + _text(120, 295, "layer 2"),
            ("layer 1", "layer 2"),
        ),
        "MAP_BOUNDARY": (
            '<polygon points="180,115 330,70 440,150 610,125 665,300 520,420 '
            '320,370 150,250" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="5"></polygon>'
            '<line x1="330" y1="70" x2="350" y2="235" stroke="#000000" '
            'stroke-width="4"></line>'
            '<line x1="150" y1="250" x2="665" y2="300" stroke="#000000" '
            'stroke-width="4"></line>' + _text(255, 220, "region A") + _text(475, 315, "region B"),
            ("region A", "region B"),
        ),
        "ORBITAL_SYSTEM": (
            '<circle cx="400" cy="250" r="55" fill="#E5E7EB" stroke="#000000" '
            'stroke-width="4"></circle>'
            '<ellipse cx="400" cy="250" rx="250" ry="170" fill="none" '
            'stroke="#000000" stroke-width="3"></ellipse>'
            '<circle cx="640" cy="220" r="25" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="4"></circle>' + _text(370, 255, "star") + _text(625, 225, "P"),
            ("star", "P"),
        ),
        "PARTICLE_SYSTEM": (
            "".join(
                f'<circle cx="{190 + column * 70}" cy="{150 + row * 90}" r="22" '
                'fill="#FFFFFF" stroke="#000000" stroke-width="3"></circle>'
                for row in range(3)
                for column in range(7)
            )
            + _text(350, 455, "particles"),
            ("particles",),
        ),
        "RAY_DIAGRAM": (
            '<polygon points="390,90 505,390 275,390" fill="#FFFFFF" '
            'stroke="#000000" stroke-width="4"></polygon>'
            '<line x1="80" y1="160" x2="390" y2="230" stroke="#000000" '
            'stroke-width="4"></line>'
            '<line x1="390" y1="230" x2="700" y2="150" stroke="#000000" '
            'stroke-width="4"></line>' + _text(365, 430, "prism"),
            ("prism",),
        ),
        "TIMELINE": (
            '<line x1="100" y1="250" x2="700" y2="250" stroke="#000000" '
            'stroke-width="5"></line>'
            '<circle cx="200" cy="250" r="18" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="4"></circle>'
            '<circle cx="400" cy="250" r="18" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="4"></circle>'
            '<circle cx="600" cy="250" r="18" fill="#FFFFFF" stroke="#000000" '
            'stroke-width="4"></circle>'
            + _text(175, 210, "t1")
            + _text(375, 210, "t2")
            + _text(575, 210, "t3"),
            ("t1", "t2", "t3"),
        ),
        "VECTOR_FIELD": (
            "".join(
                f'<line x1="{x}" y1="{y}" x2="{x + 70}" y2="{y - 35}" '
                'stroke="#000000" stroke-width="4"></line>'
                f'<polygon points="{x + 70},{y - 35} {x + 48},{y - 35} '
                f'{x + 60},{y - 17}" fill="#000000"></polygon>'
                for y in (150, 260, 370)
                for x in (130, 310, 490)
            )
            + _text(350, 455, "field"),
            ("field",),
        ),
    }
    return shapes[primitive]


def _drawing(primitive: str) -> GeneratedVectorDrawingV5:
    overlay, labels = _representative_overlay(primitive)
    return GeneratedVectorDrawingV5.model_validate(
        {
            "kind": "diagram",
            "production_route": "DETERMINISTIC_SVG",
            "background_style": "WHITE",
            "block_id": "block_image",
            "alt_text": f"Representative production {primitive} diagram",
            "scene_description": f"A bounded representative {primitive} science diagram.",
            "scientific_constraints": [
                "All authoritative geometry is encoded in the SVG overlay.",
                "Labels remain separate vector text.",
            ],
            "required_labels": labels,
            "generation_prompt": "Render a monochrome Korean science assessment diagram.",
            "negative_prompt": "photo, decorative background, watermark, pseudo-text",
            "width_px": 800,
            "height_px": 500,
            "svg_overlay": overlay,
        }
    )


def _settings(tmp_path: Path) -> CatalogSettings:
    staging = tmp_path / "catalog"
    registry = staging / "registry"
    staging.mkdir(mode=0o750)
    registry.mkdir(mode=0o750)
    return CatalogSettings(staging_root=staging, nas_artifact_root=tmp_path / "nas")


def test_every_production_subject_uses_a_supported_svg_primitive() -> None:
    subjects = tuple(
        definition
        for definition in SUBJECT_DEFINITIONS
        if definition.route in {"HYBRID", "PYTHON_SVG"}
    )
    used = {definition.primitive for definition in subjects}

    assert len(subjects) == 73
    assert None not in used
    assert used == PRODUCTION_PRIMITIVES - {"TIMELINE"}
    assert all(definition.primitive in PRODUCTION_PRIMITIVES for definition in subjects)


@pytest.mark.skipif(
    not SVG_RASTERIZER.exists() or not SVG_FONT.exists(),
    reason="reviewed SVG runtime is not installed",
)
def test_all_svg_primitives_cross_the_real_production_compositor(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    png_hashes: dict[str, str] = {}

    for index, primitive in enumerate(sorted(PRODUCTION_PRIMITIVES), start=1):
        rendered = render_generated_vector_stimulus(
            settings,
            workflow_id="workflow_" + f"{index:032x}",
            result_revision_id="rev_" + f"{index + 100:032x}",
            drawing=_drawing(primitive),
        )
        validate_generated_png(rendered.png_path)
        png_hashes[primitive] = hashlib.sha256(rendered.png_path.read_bytes()).hexdigest()
        assert rendered.renderer_contract == "eom-safe-svg-compositor/1.1"
        assert rendered.renderer_version == "rsvg-convert version 2.58.0"
        assert b"href=" not in rendered.svg_path.read_bytes().lower()

    assert set(png_hashes) == PRODUCTION_PRIMITIVES
    assert len(set(png_hashes.values())) == len(PRODUCTION_PRIMITIVES)
