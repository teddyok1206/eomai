from __future__ import annotations

import hashlib
import stat
import struct
from pathlib import Path

import pytest
from eom_catalog_service.generated_stimulus import (
    PNG_HEIGHT,
    PNG_WIDTH,
    render_generated_stimulus,
    render_generated_vector_stimulus,
    validate_generated_png,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.vector_stimulus import (
    SVG_FONT,
    SVG_FONT_PROFILE,
    SVG_LATIN_FONT_FAMILY,
    SVG_MATH_FONT_FAMILY,
    SVG_RASTERIZER,
    compose_vector_overlay_svg,
    compose_vector_svg,
    sanitize_svg_overlay,
)
from eom_workflow.models import (
    GeneratedImageBrief,
    GeneratedLineGraphDrawing,
    GeneratedLineGraphDrawingV5,
    GeneratedVectorDrawingV5,
)


def _settings(tmp_path: Path) -> CatalogSettings:
    staging = tmp_path / "catalog"
    registry = staging / "registry"
    staging.mkdir(mode=0o750)
    registry.mkdir(mode=0o750)
    staging.chmod(0o750)
    registry.chmod(0o750)
    return CatalogSettings(staging_root=staging, nas_artifact_root=tmp_path / "nas")


def _drawing() -> GeneratedLineGraphDrawing:
    return GeneratedLineGraphDrawing(
        alt_text="시간이 늘수록 이동 거리가 일정하게 증가하는 선그래프",
        x_axis_label="time(s)",
        y_axis_label="distance(m)",
        series_label="object-A",
        x_values=(1, 2, 3),
        y_values=(5, 10, 15),
        stroke_color="blue",
        point_style="circle",
    )


def test_generated_stimulus_is_a_deterministic_bounded_png(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = render_generated_stimulus(
        settings,
        workflow_id="workflow_" + "1" * 32,
        result_revision_id="rev_" + "2" * 32,
        drawing=_drawing(),
    )
    first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
    second = render_generated_stimulus(
        settings,
        workflow_id="workflow_" + "1" * 32,
        result_revision_id="rev_" + "2" * 32,
        drawing=_drawing(),
    )
    assert first == second
    assert hashlib.sha256(second.read_bytes()).hexdigest() == first_hash
    validate_generated_png(first)
    assert stat.S_IMODE(first.stat().st_mode) == 0o640
    assert struct.unpack(">II", first.read_bytes()[16:24]) == (PNG_WIDTH, PNG_HEIGHT)


def test_generated_image_contract_rejects_inconsistent_or_unordered_points() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        GeneratedImageBrief(
            alt_text="자료를 나타낸 그래프",
            x_axis_label="x",
            y_axis_label="y",
            series_label="A",
            x_values=(1, 2, 3),
            y_values=(1, 2),
        )
    with pytest.raises(ValueError, match="strictly increasing"):
        GeneratedImageBrief(
            alt_text="자료를 나타낸 그래프",
            x_axis_label="x",
            y_axis_label="y",
            series_label="A",
            x_values=(2, 1),
            y_values=(1, 2),
        )


def test_generated_png_validation_rejects_symlink(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    target = render_generated_stimulus(
        settings,
        workflow_id="workflow_" + "3" * 32,
        result_revision_id="rev_" + "4" * 32,
        drawing=_drawing(),
    )
    link = tmp_path / "escaped.png"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="metadata"):
        validate_generated_png(link)


def _vector_drawing(*, route: str = "DETERMINISTIC_SVG") -> GeneratedVectorDrawingV5:
    return GeneratedVectorDrawingV5.model_validate(
        {
            "kind": "natural_scene",
            "production_route": route,
            "background_style": "PAPER",
            "block_id": "block_image",
            "alt_text": "두 사람이 생태 조사 방형구를 살펴보는 모식도",
            "scene_description": "두 조사자가 방형구 옆에서 식물 분포를 관찰한다.",
            "scientific_constraints": ["방형구는 정사각형이다.", "식물 개체는 방형구 안에 있다."],
            "required_labels": ["조사자", "방형구"],
            "generation_prompt": "교과서형 선화로 생태 조사 장면을 그린다.",
            "negative_prompt": "사진풍, 장식적 배경",
            "width_px": 800,
            "height_px": 500,
            "svg_overlay": (
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
                'viewBox="0 0 800 500">'
                '<circle cx="180" cy="130" fill="#ffffff" r="35" stroke="#000000" '
                'stroke-width="3"></circle>'
                '<rect fill="none" height="180" stroke="#000000" stroke-width="4" '
                'width="260" x="360" y="230"></rect>'
                '<text fill="#000000" font-family="'
                'SM JGothic Std, Noto Sans CJK KR" font-size="20" '
                'x="130" y="200">조사자</text>'
                '<text fill="#000000" font-family="'
                'SM JGothic Std, Noto Sans CJK KR" font-size="20" '
                'x="440" y="450">방형구</text>'
                "</svg>"
            ),
        }
    )


def test_vector_overlay_is_sanitized_and_receives_a_deterministic_background() -> None:
    drawing = _vector_drawing()
    first = compose_vector_svg(drawing)
    second = compose_vector_svg(drawing)

    assert first == second
    assert first.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    assert b"#fffdf5" in first
    assert first.index(b"#fffdf5") < first.index("조사자".encode())
    assert b"<script" not in first.lower()


def test_vector_overlay_accepts_safe_group_fragment() -> None:
    source = (
        '<g fill="none" font-family="SM JGothic Std, Noto Sans CJK KR" '
        'font-size="20" stroke="#000000" '
        'stroke-linecap="round" stroke-width="3">'
        '<circle cx="180" cy="130" fill="#ffffff" r="35"></circle>'
        '<rect height="180" width="260" x="360" y="230"></rect>'
        '<text fill="#000000" x="130" y="200">조사자</text>'
        '<text fill="#000000" x="440" y="450">방형구</text>'
        "</g>"
    )

    clean = sanitize_svg_overlay(source, ("조사자", "방형구"))

    assert clean.startswith(
        '<g fill="none" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20"'
    )
    assert "조사자" in clean
    assert "방형구" in clean


def test_vector_overlay_accepts_safe_inherited_text_alignment_on_group() -> None:
    source = (
        '<g fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" text-anchor="middle">'
        '<text font-size="18" x="120" y="80">운동량</text>'
        '<text font-size="18" x="240" y="80">충격량</text>'
        "</g>"
    )

    clean = sanitize_svg_overlay(source, ("운동량", "충격량"))

    assert clean.startswith('<g fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR"')
    assert 'text-anchor="middle"' in clean


def test_vector_overlay_accepts_safe_multi_element_fragment() -> None:
    source = (
        '<circle cx="180" cy="130" fill="#ffffff" r="35" stroke="#000000" '
        'stroke-width="3"></circle>'
        '<rect fill="none" height="180" stroke="#000000" stroke-width="4" '
        'width="260" x="360" y="230"></rect>'
        '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
        'x="130" y="200">조사자</text>'
        '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
        'x="440" y="450">방형구</text>'
    )

    clean = sanitize_svg_overlay(source, ("조사자", "방형구"))

    assert clean.startswith("<circle")
    assert clean.count("<text") == 2


def test_vector_overlay_rejects_unsafe_group_fragment() -> None:
    source = (
        '<g fill="none"><text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" '
        'font-size="20" x="10" y="20">조사자</text><script>alert(1)</script></g>'
    )
    with pytest.raises(ValueError, match="forbidden"):
        sanitize_svg_overlay(source, ("조사자",))


@pytest.mark.parametrize(
    "unsafe",
    [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500"><script>alert(1)</script></svg>'
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500"><image href="https://example.invalid/a.png"/></svg>'
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500"><rect onclick="alert(1)" x="0" y="0" '
            'width="10" height="10"/></svg>'
        ),
    ],
)
def test_vector_overlay_rejects_active_external_or_event_content(unsafe: str) -> None:
    with pytest.raises(ValueError, match="SVG"):
        sanitize_svg_overlay(unsafe, ())


def test_vector_overlay_requires_every_reviewed_label() -> None:
    source = _vector_drawing().svg_overlay.replace("방형구", "조사지", 1)
    with pytest.raises(ValueError, match="required label"):
        sanitize_svg_overlay(source, ("조사자", "방형구"))


def test_vector_overlay_rejects_unpinned_font_or_malformed_geometry() -> None:
    valid = _vector_drawing().svg_overlay
    with pytest.raises(ValueError, match="font family"):
        sanitize_svg_overlay(valid.replace("SM JGothic Std, Noto Sans CJK KR", "sans-serif"), ())
    with pytest.raises(ValueError, match="numeric list"):
        sanitize_svg_overlay(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" '
            'viewBox="0 0 800 500"><polyline points="1,,2 3,4"></polyline></svg>',
            (),
        )
    with pytest.raises(ValueError, match="transform"):
        sanitize_svg_overlay(
            valid.replace('<circle cx="180"', '<circle transform="scale(1,2,3)" cx="180"'),
            (),
        )


def test_vector_overlay_uses_reviewed_content_team_fonts_by_script() -> None:
    source = (
        '<g fill="#000000">'
        '<text font-family="SM JGothic Std, Noto Sans CJK KR" '
        'font-size="20" x="10" y="20">한글 라벨</text>'
        '<text font-family="Century Old Style" font-size="20" x="10" y="50">axis 12</text>'
        '<text font-family="DejaVu Serif" font-size="20" x="10" y="80">\u03b1 + \u03b2</text>'
        "</g>"
    )

    clean = sanitize_svg_overlay(source, ("한글 라벨", "axis 12", "\u03b1 + \u03b2"))

    assert f'font-family="{SVG_LATIN_FONT_FAMILY}"' in clean
    assert f'font-family="{SVG_MATH_FONT_FAMILY}"' in clean


def test_vector_overlay_rejects_missing_font_and_korean_in_latin_font() -> None:
    with pytest.raises(ValueError, match="explicit fixed font"):
        sanitize_svg_overlay('<text fill="#000000" font-size="20" x="10" y="20">A</text>', ("A",))
    with pytest.raises(ValueError, match="fixed Korean font"):
        sanitize_svg_overlay(
            '<text fill="#000000" font-family="Century Old Style" font-size="20" '
            'x="10" y="20">한글</text>',
            ("한글",),
        )
    with pytest.raises(ValueError, match="italic style"):
        sanitize_svg_overlay(
            '<text fill="#000000" font-family="SM JGothic Std, Noto Sans CJK KR" font-size="20" '
            'font-style="italic" x="10" y="20">한글</text>',
            ("한글",),
        )


def test_unavailable_nondeterministic_provider_never_falls_back_to_svg() -> None:
    drawing = _vector_drawing(route="LOCAL_GENERATIVE_BACKGROUND")
    with pytest.raises(ValueError, match="provider is not deployed"):
        compose_vector_svg(drawing)


def test_local_route_produces_only_a_sanitized_transparent_overlay() -> None:
    drawing = _vector_drawing(route="LOCAL_GENERATIVE_BACKGROUND")

    payload = compose_vector_overlay_svg(drawing)

    assert payload.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
    assert "조사자".encode() in payload
    assert "방형구".encode() in payload
    assert b"#fffdf5" not in payload
    assert b"<image" not in payload.lower()
    assert b"href=" not in payload.lower()


def test_v5_line_graph_is_svg_first_and_preserves_exact_data() -> None:
    drawing = GeneratedLineGraphDrawingV5(
        alt_text="시간이 늘수록 이동 거리가 일정하게 증가하는 선그래프",
        x_axis_label="time(s)",
        y_axis_label="distance(m)",
        series_label="object-A",
        x_values=(1, 2, 3),
        y_values=(5, 10, 15),
        stroke_color="blue",
        point_style="circle",
        background_style="GRID",
    )
    svg = compose_vector_svg(drawing)
    assert b"<polyline" in svg
    assert b"#e5e7eb" in svg
    assert b"time(s)" in svg


@pytest.mark.skipif(
    not SVG_RASTERIZER.exists() or not SVG_FONT.exists(),
    reason="reviewed SVG runtime is not installed",
)
def test_real_fixed_svg_rasterizer_produces_reproducible_svg_and_png(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = render_generated_vector_stimulus(
        settings,
        workflow_id="workflow_" + "8" * 32,
        result_revision_id="rev_" + "9" * 32,
        drawing=_vector_drawing(),
    )
    first_hashes = (
        hashlib.sha256(first.svg_path.read_bytes()).hexdigest(),
        hashlib.sha256(first.png_path.read_bytes()).hexdigest(),
    )
    second = render_generated_vector_stimulus(
        settings,
        workflow_id="workflow_" + "8" * 32,
        result_revision_id="rev_" + "9" * 32,
        drawing=_vector_drawing(),
    )

    assert first == second
    assert first_hashes == (
        hashlib.sha256(second.svg_path.read_bytes()).hexdigest(),
        hashlib.sha256(second.png_path.read_bytes()).hexdigest(),
    )
    assert first.renderer_version == "rsvg-convert version 2.58.0"
    assert (
        first.renderer_sha256 == "sha256:" + hashlib.sha256(SVG_RASTERIZER.read_bytes()).hexdigest()
    )
    assert first.font_sha256 == "sha256:" + hashlib.sha256(SVG_FONT.read_bytes()).hexdigest()
    assert first.font_manifest_sha256.startswith("sha256:")
    assert len(first.font_manifest_sha256) == 71
    assert SVG_FONT_PROFILE == "eom-content-team-diagram-fonts/1.0"
    validate_generated_png(second.png_path)
