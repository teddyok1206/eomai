"""Synthetic restricted-root access; real mixed-UID kernel acceptance is opt-in."""

from __future__ import annotations

import errno
import os
import pwd
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_device_benchmark_files as capture
from eom_catalog_service.embedding_benchmark_layout import benchmark_read_acl
from eom_identifiers import sha256_bytes

from tests.unit import test_embedding_benchmark_environment as environment
from tests.unit.embedding_device_benchmark_fixtures import worker_invocation
from tests.unit.test_embedding_device_benchmark_files import set_acl, stage_files

staged = environment.staged


def restricted_root_outputs(monkeypatch, execution: Path) -> tuple[int, list[int]]:
    """Model root/native UID separation and missing DAC write bypass, without chown/root."""
    native_uid = os.getuid() + 200
    outputs = execution / "outputs"
    identities = {(path.stat().st_dev, path.stat().st_ino) for path in outputs.iterdir()}
    for path in (execution, execution / "inputs", outputs):
        os.setxattr(path, "system.posix_acl_access", benchmark_read_acl(native_uid, "DIRECTORY"))
    original_stat, original_fstat, original_open = os.stat, os.fstat, os.open
    opened: list[int] = []

    def metadata(value):
        if (value.st_dev, value.st_ino) not in identities:
            return value
        assert stat.S_IMODE(value.st_mode) == 0o640
        fields = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
        return SimpleNamespace(**(fields | {"st_uid": native_uid}))

    def open_member(path, flags, *args, **kwargs):
        try:
            value = original_stat(path, dir_fd=kwargs.get("dir_fd"), follow_symlinks=False)
        except FileNotFoundError:
            value = None
        if value is not None and (value.st_dev, value.st_ino) in identities:
            access = flags & os.O_ACCMODE
            opened.append(access)
            if access != os.O_RDONLY:
                raise PermissionError(errno.EACCES, "synthetic restricted-root native output")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(
        os, "stat", lambda *args, **kwargs: metadata(original_stat(*args, **kwargs))
    )
    monkeypatch.setattr(os, "fstat", lambda descriptor: metadata(original_fstat(descriptor)))
    monkeypatch.setattr(os, "open", open_member)
    monkeypatch.setattr(
        pwd,
        "getpwnam",
        lambda name: SimpleNamespace(
            pw_uid=os.getuid() + 1 if name == "eom-workflow-runner" else native_uid,
            pw_gid=os.getgid(),
        ),
    )
    return native_uid, opened


def test_environment_preparation_does_not_need_write_access_to_native_owned_outputs(
    staged, monkeypatch
):
    root, metadata = staged
    execution = root / metadata.invocation.execution_id
    native_uid, opened = restricted_root_outputs(monkeypatch, execution)
    assert native_uid != capture._ROOT_UID
    result = environment.prepare(metadata)
    assert result.state == "STAGED_NOT_LAUNCHED"
    assert opened == [os.O_RDONLY] * 16
    assert (execution / "launch.env").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_root_read_view_retains_native_uid_mode_and_exposes_no_writer(
    tmp_path, monkeypatch, ordinal
):
    unused, execution, borrowed = stage_files(tmp_path, monkeypatch, ordinal)
    unused.close()
    invocation = worker_invocation(ordinal)
    native_uid, opened = restricted_root_outputs(monkeypatch, execution)
    arguments = dict(
        profile=invocation.runtime.profile,
        execution_id=invocation.execution_id,
        invocation_raw_sha256=sha256_bytes(capture.embedding_device_benchmark_bytes(invocation)),
    )
    try:
        with capture.BenchmarkRootStagedFiles(borrowed, **arguments) as files:
            assert files.read_invocation() == invocation
            assert files.native_uid == native_uid != capture._ROOT_UID
            assert not isinstance(files, capture.BenchmarkWorkerLocalFiles)
            for name in (
                "write_vectors",
                "write_evidence",
                "write_cuda_ready",
                "seal_supplementary",
            ):
                assert not hasattr(files, name)
            for member in files._members.values():
                assert os.fstat(member.descriptor).st_uid == native_uid
                assert stat.S_IMODE(os.fstat(member.descriptor).st_mode) == 0o640
                with pytest.raises(OSError) as error:
                    os.write(member.descriptor, b"forbidden")
                assert error.value.errno == errno.EBADF
            files.assert_current()
        # The actual writer still requests write-only FDs and receives the simulated DAC denial.
        with (
            capture.BenchmarkWorkerLocalFiles(borrowed, **arguments) as writer,
            pytest.raises(PermissionError, match="restricted-root"),
        ):
            writer.read_invocation()
        assert opened == [os.O_RDONLY] * len(files._members) + [os.O_WRONLY]
        assert all(path.stat().st_size == 0 for path in (execution / "outputs").iterdir())
        assert os.lseek(borrowed, 0, os.SEEK_CUR) == 0
    finally:
        os.close(borrowed)


def test_root_read_view_rejects_nonroot_before_opening_any_files(monkeypatch):
    invocation = worker_invocation()
    monkeypatch.setattr(capture, "_ROOT_UID", os.geteuid() + 1)
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("no nonroot capture"))
    with pytest.raises(capture.BenchmarkFilesError, match="ROOT_REQUIRED"):
        capture.BenchmarkRootStagedFiles(
            0,
            profile=invocation.runtime.profile,
            execution_id=invocation.execution_id,
            invocation_raw_sha256=sha256_bytes(
                capture.embedding_device_benchmark_bytes(invocation)
            ),
        )


def test_root_read_view_rechecks_root_on_context_entry(tmp_path, monkeypatch):
    unused, _execution, borrowed = stage_files(tmp_path, monkeypatch)
    unused.close()
    invocation = worker_invocation()
    files = capture.BenchmarkRootStagedFiles(
        borrowed,
        profile=invocation.runtime.profile,
        execution_id=invocation.execution_id,
        invocation_raw_sha256=sha256_bytes(capture.embedding_device_benchmark_bytes(invocation)),
    )
    monkeypatch.setattr(os, "geteuid", lambda: capture._ROOT_UID + 1)
    monkeypatch.setattr(os, "open", lambda *_a, **_kw: pytest.fail("no nonroot capture"))
    try:
        with pytest.raises(capture.BenchmarkFilesError, match="ROOT_REQUIRED"), files:
            pytest.fail("no nonroot entry")
        assert files._input == -1 and files._directories == []
    finally:
        files.close()
        os.close(borrowed)


@pytest.mark.parametrize("fault", ("extra", "missing", "nonempty", "hardlink", "acl", "directory"))
def test_root_read_view_keeps_closed_member_set_and_identity_checks(tmp_path, monkeypatch, fault):
    unused, execution, borrowed = stage_files(tmp_path, monkeypatch)
    unused.close()
    target = execution / "outputs/cold-documents.f32"
    if fault == "extra":
        (execution / "outputs/extra").touch()
    elif fault == "missing":
        target.unlink()
    elif fault == "nonempty":
        target.write_bytes(b"used")
    elif fault == "hardlink":
        target.unlink()
        os.link(execution / "outputs/resources.json", target)
    elif fault == "acl":
        set_acl(target, directory=False)
    else:
        os.removexattr(execution / "outputs", "system.posix_acl_access")
    invocation = worker_invocation()
    try:
        with (
            capture.BenchmarkRootStagedFiles(
                borrowed,
                profile=invocation.runtime.profile,
                execution_id=invocation.execution_id,
                invocation_raw_sha256=sha256_bytes(
                    capture.embedding_device_benchmark_bytes(invocation)
                ),
            ) as files,
            pytest.raises((capture.BenchmarkFilesError, OSError)),
        ):
            files.read_invocation()
    finally:
        os.close(borrowed)


@pytest.mark.parametrize("fault", ("output", "acl", "directory", "invocation", "offset"))
def test_root_read_view_retains_epochs_for_late_revalidation(tmp_path, monkeypatch, fault):
    unused, execution, borrowed = stage_files(tmp_path, monkeypatch)
    unused.close()
    invocation = worker_invocation()
    try:
        with capture.BenchmarkRootStagedFiles(
            borrowed,
            profile=invocation.runtime.profile,
            execution_id=invocation.execution_id,
            invocation_raw_sha256=sha256_bytes(
                capture.embedding_device_benchmark_bytes(invocation)
            ),
        ) as files:
            files.read_invocation()
            if fault == "output":
                (execution / "outputs/cold-documents.f32").write_bytes(b"used")
            elif fault == "acl":
                set_acl(execution / "outputs/cold-documents.f32", directory=False)
            elif fault == "directory":
                (execution / "outputs").rename(execution / "old-outputs")
                (execution / "outputs").mkdir(mode=0o750)
            elif fault == "invocation":
                (execution / "invocation.json").write_bytes(b"changed")
            else:
                os.lseek(files._members["cold-documents.f32"].descriptor, 1, os.SEEK_SET)
            with pytest.raises(capture.BenchmarkFilesError):
                files.assert_current()
    finally:
        os.close(borrowed)
