"""Real unprivileged file/flock publication, not GPU/root/operator admission."""

import fcntl
import os

import pytest
from eom_catalog_contracts.embedding_benchmark_cuda_ready import benchmark_cuda_ready_bytes
from eom_catalog_service import embedding_benchmark_cuda_observation as reader
from eom_catalog_service import embedding_device_benchmark_files as writer
from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.test_embedding_benchmark_cuda_files import ready_for_process
from tests.unit.test_embedding_device_benchmark_files import stage_files


def test_empty_ready_is_pending_before_any_root_lock_or_byte_read(tmp_path, monkeypatch):
    path = tmp_path / "cuda-ready.json"
    path.touch(mode=0o640)
    monkeypatch.setattr(reader.os, "open", lambda *_a, **_kw: pytest.fail("empty member locked"))
    with pytest.raises(ValueError, match="NOT_READY"):
        reader._read_ready_member(path, NumericalRuntimeFileSnapshots(os.getuid()))


def test_root_reader_cannot_parse_partial_bytes_or_release_native_writer_lock(tmp_path):
    path = tmp_path / "cuda-ready.json"
    path.write_bytes(b'{"partial":')
    path.chmod(0o640)
    held = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="NOT_READY"):
            reader._read_ready_member(path, NumericalRuntimeFileSnapshots(os.getuid()))
        contender = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(contender)
    finally:
        os.close(held)
    _, ready = benchmark_cuda_ready()
    raw = benchmark_cuda_ready_bytes(ready)
    path.write_bytes(raw)
    observed = reader._read_ready_member(path, NumericalRuntimeFileSnapshots(os.getuid()))
    assert observed.raw == raw
    contender = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(contender)


@pytest.mark.parametrize("fault", ("directory", "symlink", "hardlink", "oversize"))
def test_untrusted_ready_shape_is_not_misclassified_as_pending(tmp_path, fault):
    path = tmp_path / "cuda-ready.json"
    other = tmp_path / "target"
    other.write_bytes(b"unchanged")
    if fault == "directory":
        path.mkdir()
    elif fault == "symlink":
        path.symlink_to(other)
    elif fault == "hardlink":
        os.link(other, path)
    else:
        path.write_bytes(b"x" * (reader.MAX_BENCHMARK_CUDA_READY_BYTES + 1))
    with pytest.raises(ValueError, match="READY_INVALID"):
        reader._read_ready_member(path, NumericalRuntimeFileSnapshots(os.getuid()))
    assert other.read_bytes() == b"unchanged"


def test_native_writer_holds_ready_lock_through_every_partial_write(tmp_path, monkeypatch):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    original = os.write
    calls = []

    def checked_write(descriptor, raw):
        contender = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_SH | fcntl.LOCK_NB)
        finally:
            os.close(contender)
        calls.append(True)
        return original(descriptor, raw[:137])

    try:
        with files:
            monkeypatch.setattr(writer.os, "write", checked_write)
            files.write_cuda_ready(ready)
            assert len(calls) > 1
            observed = reader._read_ready_member(path, NumericalRuntimeFileSnapshots(os.getuid()))
            assert observed.raw == benchmark_cuda_ready_bytes(ready)
            files.assert_current()
    finally:
        os.close(borrowed)


def test_unexpected_competing_writer_preserves_empty_member_and_poisoned_scope(
    tmp_path, monkeypatch
):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    held = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with files:
            with pytest.raises(writer.BenchmarkFilesError, match="WRITE_UNCERTAIN"):
                files.write_cuda_ready(ready)
            with pytest.raises(writer.BenchmarkFilesError):
                files.assert_current()
            assert path.stat().st_size == 0
    finally:
        os.close(held)
        os.close(borrowed)
