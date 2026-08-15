from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from eom_hwpx_manager.adapter import HwpxBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError
from eom_hwpx_manager.settings import HwpxSettings
from eom_hwpx_manager.state_machine import (
    HwpxBuildState,
    InvalidHwpxBuildTransition,
    require_transition,
)


def test_hwpx_build_state_machine_happy_path() -> None:
    path = (
        HwpxBuildState.CREATED,
        HwpxBuildState.VALIDATING_INPUT,
        HwpxBuildState.STAGING,
        HwpxBuildState.RENDERING,
        HwpxBuildState.PACKAGING,
        HwpxBuildState.VALIDATING_OUTPUT,
        HwpxBuildState.COMMITTING,
        HwpxBuildState.PENDING_MANUAL_VALIDATION,
        HwpxBuildState.SUCCEEDED,
    )
    for current, target in pairwise(path):
        require_transition(current, target)


def test_hwpx_build_state_machine_rejects_invalid_transition() -> None:
    with pytest.raises(InvalidHwpxBuildTransition, match="SUCCEEDED -> RENDERING"):
        require_transition(HwpxBuildState.SUCCEEDED, HwpxBuildState.RENDERING)


def test_adapter_stages_only_regular_workspace_files(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    settings = HwpxSettings(workspace_root=workspace_root, builder_user="eom-hwpx")
    adapter = HwpxBuilderAdapter(settings)
    workspace = adapter.create_workspace("hwpxbuild_" + "a" * 32)
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    target = adapter.stage_file(workspace, "input/document.json", source)
    assert target.is_file()
    assert target.resolve().is_relative_to(workspace.resolve())
    with pytest.raises(HwpxManagerError, match="unsafe"):
        adapter.stage_file(workspace, "../escape", source)


def test_adapter_result_loader_rejects_non_object_and_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    value = workspace / "result.json"
    value.write_text("[]", encoding="utf-8")
    with pytest.raises(HwpxManagerError, match="object"):
        HwpxBuilderAdapter.load_json(value, workspace)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(HwpxManagerError, match="unsafe"):
        HwpxBuilderAdapter.load_json(outside, workspace)
