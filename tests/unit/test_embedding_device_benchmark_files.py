"""Unprivileged synthetic file ownership/ACL surrogates, not root or installed admission."""

from __future__ import annotations

import os
import pwd
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    benchmark_local_output_members,
    benchmark_sample_program,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_device_benchmark_files as module
from eom_catalog_service.embedding_device_benchmark_files import (
    BenchmarkFilesError,
    BenchmarkWorkerLocalFiles,
)
from eom_identifiers import sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import staged_inputs, worker_invocation


def set_acl(path: Path, *, directory: bool) -> None:
    permission = 5 if directory else 4
    raw = struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, bits, identity)
        for tag, bits, identity in (
            (1, 7 if directory else 6, 2**32 - 1),
            (2, permission, os.getuid()),
            (4, permission, 2**32 - 1),
            (16, permission, 2**32 - 1),
            (32, 0, 2**32 - 1),
        )
    )
    os.setxattr(path, "system.posix_acl_access", raw)


def stage_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ordinal: int = 1
) -> tuple[BenchmarkWorkerLocalFiles, Path, int]:
    """Current UID substitutes all physical file owners only in this source fixture."""
    root = tmp_path / "synthetic-benchmark"
    root.mkdir(mode=0o700)
    invocation = worker_invocation(ordinal)
    execution = root / invocation.execution_id
    execution.mkdir(mode=0o750)
    set_acl(execution, directory=True)
    for name in ("inputs", "outputs"):
        directory = execution / name
        directory.mkdir(mode=0o750)
        set_acl(directory, directory=True)
    invocation_path = execution / "invocation.json"
    raw = embedding_device_benchmark_bytes(invocation)
    invocation_path.write_bytes(raw)
    invocation_path.chmod(0o600)
    input_path = execution / "inputs/benchmark-inputs.json"
    input_path.write_bytes(embedding_device_benchmark_bytes(staged_inputs()))
    input_path.chmod(0o640)
    set_acl(input_path, directory=False)
    for name in benchmark_local_output_members(ordinal):
        path = execution / "outputs" / name
        path.touch(mode=0o640)
        path.chmod(0o640)
    monkeypatch.setattr(module, "_HANDOFF_ROOT", root)
    monkeypatch.setattr(module, "_ROOT_UID", os.getuid())
    monkeypatch.setattr(module, "_ROOT_GID", os.getgid())

    def synthetic_account(name: str) -> Any:
        return SimpleNamespace(
            pw_uid=os.getuid() + (1 if name == "eom-workflow-runner" else 0), pw_gid=os.getgid()
        )

    monkeypatch.setattr(pwd, "getpwnam", synthetic_account)
    descriptor = os.open(invocation_path, os.O_RDONLY | os.O_CLOEXEC)
    files = BenchmarkWorkerLocalFiles(
        descriptor,
        profile=invocation.runtime.profile,
        execution_id=invocation.execution_id,
        invocation_raw_sha256=sha256_bytes(raw),
    )
    return files, execution, descriptor


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_fixed_file_capture_read_once_seal_no_clobber_and_borrowed_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ordinal: int
) -> None:
    files, root, borrowed = stage_files(tmp_path, monkeypatch, ordinal)
    try:
        with files:
            invocation = files.read_invocation()
            assert files.read_invocation() is invocation
            assert files.read_inputs(invocation) == staged_inputs()
            assert len(list((root / "outputs").iterdir())) == (16 if ordinal in (1, 2) else 4)
            assert files.native_uid == os.getuid() and files.owner_gid == os.getgid()
            payload = b"\x00" * (6 * 4096)
            binary = files.write_vectors(benchmark_sample_program(ordinal)[0], payload)
            assert binary is not None and binary.sha256 == sha256_bytes(payload)
            assert (root / "outputs/cold-documents.f32").read_bytes() == payload
            with pytest.raises(BenchmarkFilesError):
                files.write_vectors(benchmark_sample_program(ordinal)[0], payload)
            files.assert_current()
        assert os.fstat(borrowed).st_size > 0 and os.lseek(borrowed, 0, os.SEEK_CUR) == 0
        files.close()
    finally:
        os.close(borrowed)


def test_traversal_does_not_require_listing_global_execution_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files, execution, borrowed = stage_files(tmp_path, monkeypatch)
    parent = execution.parent
    parent.chmod(0o111)
    try:
        with pytest.raises(PermissionError):
            os.listdir(parent)
        with files:
            invocation = files.read_invocation()
            assert files.read_inputs(invocation) == staged_inputs()
            files.assert_current()
    finally:
        parent.chmod(0o700)
        os.close(borrowed)


@pytest.mark.parametrize(
    "fault",
    (
        "extra",
        "missing",
        "nonempty",
        "symlink",
        "hardlink",
        "mode",
        "acl",
        "directory_acl",
        "input_hash",
        "input_link",
        "invocation_hash",
        "invocation_alias",
    ),
)
def test_untrusted_member_namespace_and_identity_deny_before_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    files, root, borrowed = stage_files(tmp_path, monkeypatch)
    target = root / "outputs/cold-documents.f32"
    if fault == "extra":
        (root / "outputs/extra").touch()
    elif fault == "missing":
        target.unlink()
    elif fault == "nonempty":
        target.write_bytes(b"bad")
    elif fault == "symlink":
        target.unlink()
        target.symlink_to(root / "invocation.json")
    elif fault == "hardlink":
        target.unlink()
        os.link(root / "outputs/resources.json", target)
    elif fault == "mode":
        target.chmod(0o660)
    elif fault == "acl":
        set_acl(target, directory=False)
    elif fault == "directory_acl":
        os.removexattr(root / "outputs", "system.posix_acl_access")
    elif fault == "input_hash":
        (root / "inputs/benchmark-inputs.json").write_bytes(b"bad")
    elif fault == "input_link":
        os.link(root / "inputs/benchmark-inputs.json", root / "inputs/second.json")
    elif fault == "invocation_hash":
        files._raw_pin = "sha256:" + "f" * 64  # Deliberate synthetic capture corruption.
    else:
        old = root / "invocation.json"
        old.rename(root / "old.json")
        old.write_bytes((root / "old.json").read_bytes())
        old.chmod(0o600)
    try:
        with pytest.raises((BenchmarkFilesError, OSError)), files:
            invocation = files.read_invocation()
            files.read_inputs(invocation)
    finally:
        files.close()
        os.close(borrowed)


@pytest.mark.parametrize(
    "fault", ("input", "invocation", "ancestor", "sealed", "offset", "append", "fd", "inheritable")
)
def test_retained_named_fd_epochs_reject_late_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    files, root, borrowed = stage_files(tmp_path, monkeypatch)
    try:
        with files:
            invocation = files.read_invocation()
            files.read_inputs(invocation)
            if fault in ("input", "invocation"):
                (
                    root
                    / ("inputs/benchmark-inputs.json" if fault == "input" else "invocation.json")
                ).write_bytes(b"changed")
            elif fault == "ancestor":
                (root / "outputs").rename(root / "old-outputs")
                (root / "outputs").mkdir(mode=0o750)
            elif fault == "sealed":
                files.write_vectors(benchmark_sample_program(1)[0], b"\x00" * 4096)
                (root / "outputs/cold-documents.f32").write_bytes(b"\x01" * 4096)
            else:
                descriptor = files._members["cold-documents.f32"].descriptor
                if fault == "offset":
                    os.lseek(descriptor, 1, os.SEEK_SET)
                elif fault == "append":
                    import fcntl

                    fcntl.fcntl(descriptor, fcntl.F_SETFL, os.O_APPEND)
                elif fault == "inheritable":
                    os.set_inheritable(descriptor, True)
                else:
                    os.dup2(borrowed, descriptor)
            with pytest.raises(BenchmarkFilesError):
                files.assert_current()
    finally:
        files.close()
        os.close(borrowed)


@pytest.mark.parametrize("fault", ("budget", "short_write", "write", "fsync", "close"))
def test_write_bounds_partial_failure_and_no_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    files, root, borrowed = stage_files(tmp_path, monkeypatch)
    try:
        with files:
            files.read_inputs(files.read_invocation())
            actual_write, actual_close = os.write, os.close
            if fault == "budget":
                files._budget = 16 * 1024**2
                monkeypatch.setattr(os, "write", lambda *_args: pytest.fail("no oversized write"))
            elif fault == "short_write":
                monkeypatch.setattr(os, "write", lambda fd, raw: actual_write(fd, raw[:17]))
            elif fault == "write":
                calls = [0]

                def partial(fd: int, raw: memoryview) -> int:
                    calls[0] += 1
                    if calls[0] == 1:
                        return actual_write(fd, raw[:17])
                    raise OSError("synthetic write failure")

                monkeypatch.setattr(os, "write", partial)
            elif fault == "fsync":
                monkeypatch.setattr(
                    os,
                    "fsync",
                    lambda _fd: (_ for _ in ()).throw(OSError("synthetic fsync")),
                )
            else:
                failed_fd = files._members["cold-documents.f32"].descriptor

                def close_once(fd: int) -> None:
                    actual_close(fd)
                    if fd == failed_fd:
                        raise OSError("synthetic close uncertainty")

                monkeypatch.setattr(os, "close", close_once)
            key = benchmark_sample_program(1)[0]
            if fault == "short_write":
                assert files.write_vectors(key, b"\x00" * 4096) is not None
            else:
                with pytest.raises(BenchmarkFilesError):
                    files.write_vectors(key, b"\x00" * 4096)
                if fault == "write":
                    assert (root / "outputs/cold-documents.f32").stat().st_size == 17
            assert (root / "outputs/cold-documents.f32").exists()
    finally:
        files.close()
        os.close(borrowed)
