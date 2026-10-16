"""Synthetic protected namespaces only; no root, CUDA, model or installed unit."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from eom_catalog_service import embedding_runtime_files as runtime_files
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
    capture_cuda_loader_directory,
    require_cuda_loader_working_directory,
)


def _directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    parent = tmp_path / "protected"
    parent.mkdir(mode=0o700)
    directory = parent / "empty"
    directory.mkdir(mode=0o555)
    directory.chmod(0o555)
    monkeypatch.setattr(runtime_files, "CUDA_LOADER_EMPTY_DIRECTORY", directory)
    return directory


def test_empty_directory_is_captured_once_and_actual_cwd_is_independently_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _directory(tmp_path, monkeypatch)
    snapshots = NumericalRuntimeFileSnapshots(os.geteuid())
    original = capture_cuda_loader_directory(snapshots)
    assert original.path == directory and original.sha256 == ""
    assert stat.S_ISDIR(original.identity[4])
    with pytest.raises(InstalledRuntimeProofError, match="CUDA_WORKING_DIRECTORY_INVALID"):
        require_cuda_loader_working_directory(snapshots)
    monkeypatch.chdir(directory)
    require_cuda_loader_working_directory(snapshots)
    monkeypatch.setattr(os, "scandir", lambda *_: pytest.fail("no repeated directory scan"))
    assert capture_cuda_loader_directory(snapshots) is original
    require_cuda_loader_working_directory(snapshots)
    snapshots.assert_unchanged()
    with pytest.raises(InstalledRuntimeProofError, match="FILE_UNPROTECTED"):
        snapshots.observe_protected_member_identity(directory)


@pytest.mark.parametrize("mode", [0o755, 0o500, 0o777, 0o1555, 0o4555, 0o5555])
def test_exact_read_only_directory_mode_is_mandatory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: int
) -> None:
    directory = _directory(tmp_path, monkeypatch)
    directory.chmod(mode)
    with pytest.raises(InstalledRuntimeProofError, match="EMPTY_DIRECTORY_UNPROTECTED"):
        capture_cuda_loader_directory(NumericalRuntimeFileSnapshots(os.geteuid()))


@pytest.mark.parametrize("fault", ["missing", "file", "link", "nonempty", "ancestor_write"])
def test_missing_linked_or_nonempty_namespace_never_becomes_an_empty_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    directory = _directory(tmp_path, monkeypatch)
    if fault in {"missing", "file", "link"}:
        directory.rmdir()
        if fault == "file":
            directory.write_bytes(b"")
            directory.chmod(0o555)
        elif fault == "link":
            directory.symlink_to(directory.parent, target_is_directory=True)
    elif fault == "nonempty":
        directory.chmod(0o755)
        (directory / "libexample.so").write_bytes(b"not an empty directory")
        directory.chmod(0o555)
    else:
        directory.parent.chmod(0o777)
    with pytest.raises(InstalledRuntimeProofError):
        capture_cuda_loader_directory(NumericalRuntimeFileSnapshots(os.geteuid()))


@pytest.mark.parametrize("acl", ["system.posix_acl_access", "system.posix_acl_default"])
def test_extended_or_default_acl_is_not_silently_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acl: str
) -> None:
    _directory(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "listxattr", lambda _: [acl])
    with pytest.raises(InstalledRuntimeProofError, match="EMPTY_DIRECTORY_UNPROTECTED"):
        capture_cuda_loader_directory(NumericalRuntimeFileSnapshots(os.geteuid()))


@pytest.mark.parametrize("fault", ["chmod", "replace", "ancestor", "insert_then_remove"])
def test_captured_directory_and_ancestor_epochs_cannot_be_replaced_or_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    directory = _directory(tmp_path, monkeypatch)
    snapshots = NumericalRuntimeFileSnapshots(os.geteuid())
    capture_cuda_loader_directory(snapshots)
    if fault == "chmod":
        directory.chmod(0o755)
    elif fault == "replace":
        directory.rename(directory.with_name("retained-old"))
        directory.mkdir(mode=0o555)
    elif fault == "ancestor":
        directory.parent.chmod(0o777)
    else:
        initial = directory.stat()
        directory.chmod(0o755)
        member = directory / "temporary.so"
        member.write_bytes(b"temporary")
        member.unlink()
        directory.chmod(0o555)
        # Filesystem timestamps may share a clock tick; make this fixture's
        # visible epoch change deterministic, rather than depending on timing.
        os.utime(directory, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1))
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        capture_cuda_loader_directory(snapshots)
    with pytest.raises(InstalledRuntimeProofError, match="CHANGED"):
        snapshots.assert_unchanged()


def test_mutation_during_capture_fails_even_if_the_final_named_fd_still_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _directory(tmp_path, monkeypatch)
    actual = os.fstat
    changed = False
    leaf_observations = 0
    initial = directory.stat()

    def observe(descriptor: int) -> os.stat_result:
        nonlocal changed, leaf_observations
        value = actual(descriptor)
        if (value.st_dev, value.st_ino) == (initial.st_dev, initial.st_ino):
            leaf_observations += 1
            if not changed and leaf_observations == 3:
                changed = True
                directory.chmod(0o755)
                (directory / "late.so").write_bytes(b"late")
                directory.chmod(0o555)
                os.utime(directory, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1))
        return value

    monkeypatch.setattr(os, "fstat", observe)
    with pytest.raises(InstalledRuntimeProofError):
        capture_cuda_loader_directory(NumericalRuntimeFileSnapshots(os.geteuid()))
    assert changed


def test_regular_file_snapshot_cannot_be_reused_as_a_directory_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    member = tmp_path / "member"
    member.write_bytes(b"")
    member.chmod(0o600)
    snapshots = NumericalRuntimeFileSnapshots(os.geteuid())
    snapshots.observe_protected_member_identity(member)
    monkeypatch.setattr(runtime_files, "CUDA_LOADER_EMPTY_DIRECTORY", member)
    with pytest.raises(InstalledRuntimeProofError, match="EMPTY_DIRECTORY_REFERENCE_INVALID"):
        capture_cuda_loader_directory(snapshots)
