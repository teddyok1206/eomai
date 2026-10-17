"""Opt-in real-root disposable filesystem tests; production prefixes are never used."""

from __future__ import annotations

import json
import os
import pwd
import stat
from dataclasses import replace

import pytest

from scripts.image_provider import gpu_runtime_permissions as permissions

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or os.environ.get("EOM_GPU_PERMISSION_FS_TEST") != "1",
    reason="requires explicit root-only disposable filesystem test gate",
)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    uid = pwd.getpwnam("eom").pw_uid
    parent = tmp_path / "envs"
    parent.mkdir()
    prefixes = tuple(parent / name for name in ("image", "trainer"))
    originals = permissions._PREFIXES
    assert all(prefix.is_relative_to(tmp_path) and prefix not in originals for prefix in prefixes)
    for prefix in prefixes:
        site = prefix / "lib/python3.11/site-packages"
        info = site / "synthetic-1.dist-info"
        info.mkdir(parents=True)
        (prefix / "bin").mkdir()
        (prefix / "bin/python3.11").write_bytes(b"synthetic interpreter: never executed")
        (info / "METADATA").write_bytes(b"Name: synthetic\nVersion: 1\n")
        (info / "RECORD").write_bytes(b"synthetic,sha256:unchanged,12\n")
    for path in (parent, *parent.rglob("*")):
        os.chown(path, uid, uid)
        path.chmod(0o775 if path.is_dir() or path.name == "python3.11" else 0o664)
    cache = tmp_path / "unrelated-conda-cache-record"
    first = prefixes[0] / "lib/python3.11/site-packages/synthetic-1.dist-info/RECORD"
    cache.hardlink_to(first)
    second = prefixes[1] / "lib/python3.11/site-packages/synthetic-1.dist-info/RECORD"
    second.unlink()
    second.hardlink_to(first)
    audit = tmp_path / "audit"
    audit.mkdir(mode=0o700)
    workspace = audit / ("imageprep_" + "a" * 32)
    workspace.mkdir(mode=0o700)
    monkeypatch.setattr(permissions, "_PARENT", parent)
    monkeypatch.setattr(permissions, "_PREFIXES", prefixes)
    monkeypatch.setattr(permissions, "_WORKSPACE_ROOT", audit)
    return prefixes, cache, workspace, uid


def test_actual_root_preparation_preserves_shared_inode_owner_mode_and_bytes(runtime):
    prefixes, cache, workspace, uid = runtime
    original, raw = cache.stat(), cache.read_bytes()
    plan = permissions.capture_gpu_runtime_permission_plan()
    assert sum(member.privatize for member in plan) == 2
    permissions.prepare_gpu_runtime_permissions(plan, workspace=workspace)
    for member in plan:
        current = member.path.lstat()
        assert current.st_uid == 0 and not current.st_mode & 0o022
    for prefix in prefixes:
        record = prefix / "lib/python3.11/site-packages/synthetic-1.dist-info/RECORD"
        assert record.read_bytes() == raw and record.stat().st_nlink == 1
        assert record.stat().st_ino != original.st_ino
    assert cache.stat().st_uid == uid and stat.S_IMODE(cache.stat().st_mode) == 0o664
    assert cache.stat().st_ino == original.st_ino and cache.read_bytes() == raw
    result = json.loads((workspace / "permissions/result.json").read_bytes())
    assert result["status"] == "PREPARED_NOT_DEPLOYED" and result["privatized"] == 2
    assert len(list((workspace / "permissions").glob("*.original"))) == 2


def test_replay_of_preparation_never_repairs_or_reinterprets_an_old_plan(runtime):
    _, cache, workspace, _ = runtime
    plan = permissions.capture_gpu_runtime_permission_plan()
    permissions.prepare_gpu_runtime_permissions(plan, workspace=workspace)
    original = cache.stat()
    with pytest.raises(ValueError):
        permissions.prepare_gpu_runtime_permissions(plan, workspace=workspace)
    assert cache.stat() == original


def test_drift_is_rejected_before_any_permission_change(runtime):
    prefixes, cache, workspace, uid = runtime
    plan = permissions.capture_gpu_runtime_permission_plan()
    metadata = prefixes[0] / "lib/python3.11/site-packages/synthetic-1.dist-info/METADATA"
    metadata.write_bytes(b"changed after capture")
    with pytest.raises(ValueError):
        permissions.prepare_gpu_runtime_permissions(plan, workspace=workspace)
    assert not (workspace / "permissions").exists() and cache.stat().st_uid == uid


def test_unknown_target_is_rejected_before_reading_or_mutating_it(runtime):
    _, _, workspace, _ = runtime
    plan = permissions.capture_gpu_runtime_permission_plan()
    invalid = (replace(plan[0], path=workspace / "not-an-image-prefix"), *plan[1:])
    with pytest.raises(ValueError):
        permissions.prepare_gpu_runtime_permissions(invalid, workspace=workspace)
    assert not (workspace / "permissions").exists()


def test_shared_interpreter_is_not_implicitly_copied_or_chowned(runtime):
    prefixes, _, workspace, _ = runtime
    binary = prefixes[0] / "bin/python3.11"
    (workspace / "outside-interpreter").hardlink_to(binary)
    with pytest.raises(ValueError):
        permissions.capture_gpu_runtime_permission_plan()
    assert not (workspace / "permissions").exists()


def test_metadata_symlink_is_never_followed(runtime):
    prefixes, cache, workspace, _ = runtime
    metadata = prefixes[0] / "lib/python3.11/site-packages/synthetic-1.dist-info/METADATA"
    metadata.unlink()
    metadata.symlink_to(cache)
    with pytest.raises(ValueError):
        permissions.capture_gpu_runtime_permission_plan()
    assert not (workspace / "permissions").exists()


def test_unknown_owner_is_not_adopted_as_a_runtime_owner(runtime):
    prefixes, _, workspace, _ = runtime
    metadata = prefixes[0] / "lib/python3.11/site-packages/synthetic-1.dist-info/METADATA"
    os.chown(metadata, pwd.getpwnam("eom-image").pw_uid, 0)
    with pytest.raises(ValueError):
        permissions.capture_gpu_runtime_permission_plan()
    assert not (workspace / "permissions").exists()


def test_empty_metadata_is_not_repaired(runtime):
    prefixes, _, workspace, _ = runtime
    metadata = prefixes[0] / "lib/python3.11/site-packages/synthetic-1.dist-info/METADATA"
    metadata.write_bytes(b"")
    with pytest.raises(ValueError):
        permissions.capture_gpu_runtime_permission_plan()
    assert not (workspace / "permissions").exists()
