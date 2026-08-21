from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_hwpx_contracts import KordocSourcePointer
from eom_hwpx_manager.adapter import HwpxBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError
from eom_hwpx_manager.kordoc_service import KordocHwpxService
from eom_hwpx_manager.protocol import hwpx_schema_bundle_hash, kordoc_schema_bundle_hash
from eom_hwpx_manager.settings import HwpxSettings
from eom_hwpx_manager.state_machine import (
    HwpxBuildState,
    InvalidHwpxBuildTransition,
    require_transition,
)
from eom_identifiers import sha256_file
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord


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


def test_kordoc_protocol_does_not_change_template_protocol_identity() -> None:
    assert (
        hwpx_schema_bundle_hash()
        == "sha256:ea5d4d4cf93667e274cedc6594715882ee72539077838e1f0bd6d3ac018bc722"
    )
    assert (
        kordoc_schema_bundle_hash()
        == "sha256:e29e0245d19a246adea75242cfa45b5e1939f10a0b2e24fd2ca370c8694ee8a6"
    )


def test_hwpx_build_state_machine_rejects_invalid_transition() -> None:
    with pytest.raises(InvalidHwpxBuildTransition, match="SUCCEEDED -> RENDERING"):
        require_transition(HwpxBuildState.SUCCEEDED, HwpxBuildState.RENDERING)


def test_adapter_stages_only_regular_workspace_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ownership_requests: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(
        "eom_hwpx_manager.adapter.pwd.getpwnam",
        lambda _: SimpleNamespace(pw_uid=1234, pw_gid=5678),
    )
    monkeypatch.setattr(
        "eom_hwpx_manager.adapter.os.chown",
        lambda path, uid, gid: ownership_requests.append((Path(path), uid, gid)),
    )
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
    assert ownership_requests == [
        (workspace, 1234, 5678),
        (target.parent, 1234, 5678),
        (target, 1234, 5678),
    ]
    with pytest.raises(HwpxManagerError, match="unsafe"):
        adapter.stage_file(workspace, "../escape", source)
    symlink = tmp_path / "input-link.json"
    symlink.symlink_to(source)
    with pytest.raises(HwpxManagerError, match="regular"):
        adapter.stage_file(workspace, "input/link.json", symlink)


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


class _SourceSession:
    def __init__(self, artifact: object, revision: object) -> None:
        self.artifact: Any = artifact
        self.revision: Any = revision

    def __enter__(self) -> _SourceSession:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def get(self, model: type[object], identifier: str) -> Any:
        if model is ArtifactRecord and identifier == self.artifact.logical_artifact_id:
            return self.artifact
        if model is ArtifactRevisionRecord and identifier == self.revision.revision_id:
            return self.revision
        return None


def _source_service(artifact: object, revision: object) -> KordocHwpxService:
    service = object.__new__(KordocHwpxService)
    service.sessions = lambda: _SourceSession(artifact, revision)  # type: ignore[assignment]
    return service


def test_kordoc_source_pointer_resolves_pinned_approved_revision(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    source_path = artifact_root / "document.md"
    source_path.write_text("# 문항\n", encoding="utf-8")
    source_hash = sha256_file(source_path)
    artifact = SimpleNamespace(logical_artifact_id="artifact_" + "a" * 32, approved=True)
    revision = SimpleNamespace(
        revision_id="rev_" + "b" * 32,
        logical_artifact_id=artifact.logical_artifact_id,
        approved=True,
        content_hash=source_hash,
        nas_path=str(artifact_root),
        manifest={"primary_file": "document.md"},
    )
    pointer = KordocSourcePointer(
        artifact_id=artifact.logical_artifact_id,
        artifact_revision_id=revision.revision_id,
        sha256=source_hash,
    )
    _source_service(artifact, revision)._resolve_source(source_path, pointer)


@pytest.mark.parametrize(
    "defect", ["unapproved", "hash", "stale_path", "symlink", "unsafe_primary"]
)
def test_kordoc_source_pointer_rejects_invalid_resolution(tmp_path: Path, defect: str) -> None:
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    source_path = artifact_root / "document.md"
    source_path.write_text("# 문항\n", encoding="utf-8")
    source_hash = sha256_file(source_path)
    artifact = SimpleNamespace(logical_artifact_id="artifact_" + "a" * 32, approved=True)
    revision = SimpleNamespace(
        revision_id="rev_" + "b" * 32,
        logical_artifact_id=artifact.logical_artifact_id,
        approved=defect != "unapproved",
        content_hash=source_hash if defect != "hash" else "sha256:" + "0" * 64,
        nas_path=str(artifact_root),
        manifest={
            "primary_file": "../document.md" if defect == "unsafe_primary" else "document.md"
        },
    )
    pointer = KordocSourcePointer(
        artifact_id=artifact.logical_artifact_id,
        artifact_revision_id=revision.revision_id,
        sha256=source_hash,
    )
    candidate = source_path
    if defect == "stale_path":
        candidate = tmp_path / "other.md"
        candidate.write_text("# 문항\n", encoding="utf-8")
    elif defect == "symlink":
        candidate = tmp_path / "link.md"
        candidate.symlink_to(source_path)
    with pytest.raises(HwpxManagerError, match="Markdown artifact"):
        _source_service(artifact, revision)._resolve_source(candidate, pointer)
