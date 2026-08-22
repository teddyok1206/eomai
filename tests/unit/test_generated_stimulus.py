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
    validate_generated_png,
)
from eom_catalog_service.settings import CatalogSettings
from eom_workflow.models import GeneratedImageBrief, GeneratedLineGraphDrawing


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
