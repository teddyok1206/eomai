"""Resume only Manager-owned local inputs; never replace a dispatched output."""

import os
from unittest.mock import Mock

import pytest
from eom_hwpx_manager.adapter import copy_stable_regular_file
from eom_hwpx_manager.application_adapter import FixedCuratedBuilderAdapter
from eom_hwpx_manager.errors import HwpxManagerError
from eom_hwpx_manager.settings import HwpxSettings
from eom_identifiers import sha256_file


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    root.mkdir()
    value = FixedCuratedBuilderAdapter(HwpxSettings(workspace_root=root))
    # Root installation/group admission has separate privileged checks. These
    # tests use the real FD staging code under this process's own fixture group.
    monkeypatch.setattr(value, "_workspace_group", lambda: os.getgid())
    return value


def test_reopen_and_repeat_staging_keep_identity_and_do_not_copy_again(
    adapter, tmp_path, monkeypatch
):
    original = tmp_path / "original.hwp"
    original.write_bytes(b"immutable source bytes")
    build_id = "hwpxbuild_" + "a" * 32
    workspace = adapter.open_workspace(build_id)
    copy = Mock(wraps=copy_stable_regular_file)
    monkeypatch.setattr("eom_hwpx_manager.application_adapter.copy_stable_regular_file", copy)
    target = adapter.stage_file(
        workspace, "inputs/001.hwp", original, expected_sha256=sha256_file(original)
    )
    before = target.stat()
    assert adapter.open_workspace(build_id) == workspace
    assert (
        adapter.stage_file(
            workspace, "inputs/001.hwp", original, expected_sha256=sha256_file(original)
        )
        == target
    )
    assert copy.call_count == 1 and target.stat().st_ino == before.st_ino
    assert target.read_bytes() == original.read_bytes()
    assert adapter.settings.timeout_seconds == 900
    assert HwpxSettings().timeout_seconds == 180


@pytest.mark.parametrize("partial", [b"", b"interrupted partial copy"])
def test_unfinished_private_input_can_be_repaired_without_changing_source(
    adapter, tmp_path, partial
):
    source = tmp_path / "source.png"
    source.write_bytes(b"actual pinned media bytes")
    workspace = adapter.open_workspace("hwpxbuild_" + "b" * 32)
    target = workspace / "images/fixture.png"
    target.parent.mkdir(mode=0o770)
    target.write_bytes(partial)
    target.chmod(0o600)
    adapter.stage_file(workspace, "images/fixture.png", source, expected_sha256=sha256_file(source))
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o440


def test_finalized_input_and_symlink_are_never_repaired_by_overwriting(adapter, tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"pinned original")
    workspace = adapter.open_workspace("hwpxbuild_" + "c" * 32)
    target = adapter.stage_file(
        workspace, "images/fixture.png", source, expected_sha256=sha256_file(source)
    )
    with pytest.raises(HwpxManagerError, match="differs from its original pin"):
        adapter.stage_file(
            workspace, "images/fixture.png", source, expected_sha256="sha256:" + "0" * 64
        )
    assert target.read_bytes() == source.read_bytes()
    link = workspace / "images/other.png"
    link.symlink_to(source)
    with pytest.raises(HwpxManagerError, match="identity differs"):
        adapter.stage_file(
            workspace, "images/other.png", source, expected_sha256=sha256_file(source)
        )
    assert source.read_bytes() == b"pinned original"


def test_json_replay_is_exact_and_empty_hard_stop_copy_is_recoverable(adapter):
    workspace = adapter.open_workspace("hwpxbuild_" + "d" * 32)
    partial = workspace / "request.json"
    partial.touch(mode=0o600)
    target = adapter.write_json(workspace, "request.json", {"identity": "fixed"})
    before = target.stat().st_ino
    assert (
        adapter.write_json(workspace, "request.json", {"identity": "fixed"}).stat().st_ino == before
    )
    with pytest.raises(HwpxManagerError, match="original pin"):
        adapter.write_json(workspace, "request.json", {"identity": "different"})


def test_copy_bound_is_checked_before_creating_destination(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"oversized")
    with pytest.raises(ValueError, match="copy bound"):
        copy_stable_regular_file(source, target, max_bytes=1)
    assert not target.exists()
