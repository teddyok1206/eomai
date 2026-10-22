"""Actual local IO with synthetic ownership, not root, GPU or Job admission."""

import os

import pytest
from eom_catalog_contracts.embedding_benchmark_cuda_ready import (
    BenchmarkCudaReady,
    benchmark_cuda_ready_bytes,
)
from eom_catalog_contracts.embedding_device_benchmark import benchmark_sample_program
from eom_catalog_service import embedding_device_benchmark_files as module
from eom_catalog_service.embedding_device_benchmark_files import BenchmarkFilesError

from tests.unit.embedding_benchmark_cuda_ready_fixtures import benchmark_cuda_ready
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_files import stage_files


def ready_for_process(monkeypatch):
    _, template = benchmark_cuda_ready()
    body = template.model_dump(mode="json", exclude={"ready_sha256"})
    body.update(pid=os.getpid(), worker_uid=os.getuid(), worker_gid=os.getgid())
    body["supplementary_gids"] = [os.getgid() + 1]
    monkeypatch.setattr(module.os, "getgroups", lambda: [os.getgid(), os.getgid() + 1])
    return BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))


def test_ready_is_once_only_separate_from_numerical_members_and_budget(tmp_path, monkeypatch):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    try:
        with files:
            files.write_cuda_ready(ready)
            assert path.read_bytes() == benchmark_cuda_ready_bytes(ready)
            assert len(tuple((execution / "outputs").iterdir())) == 16
            assert files._budget == 0
            with pytest.raises(BenchmarkFilesError):
                files.write_cuda_ready(ready)
            files.assert_current()
            assert files.write_vectors(benchmark_sample_program(2)[0], b"\0" * 24576)
            assert files._budget == 24576
    finally:
        os.close(borrowed)


def test_sealed_cuda_ready_capture_hands_off_once_without_context_reentry(tmp_path, monkeypatch):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    ready_path = execution / "cuda-ready.json"
    ready_path.touch(mode=0o640)
    ready_path.chmod(0o640)
    try:
        with files:
            files.write_cuda_ready(ready_for_process(monkeypatch))
            descriptor = files._input
            assert files.begin_worker_execution() is files
            assert files._input == descriptor and files._budget == 0
            with pytest.raises(BenchmarkFilesError):
                files.begin_worker_execution()
            files.assert_current()
            assert all(path.stat().st_size == 0 for path in (execution / "outputs").iterdir())
        assert os.fstat(borrowed).st_size > 0
    finally:
        files.close()
        os.close(borrowed)


@pytest.mark.parametrize("fault", ("unsealed", "poisoned", "changed_ready", "output_started"))
def test_cuda_capture_handoff_refuses_unsealed_changed_or_already_used_files(
    tmp_path, monkeypatch, fault
):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    ready_path = execution / "cuda-ready.json"
    ready_path.touch(mode=0o640)
    ready_path.chmod(0o640)
    try:
        with files:
            if fault != "unsealed":
                files.write_cuda_ready(ready_for_process(monkeypatch))
            if fault == "poisoned":
                files._ready_state = "POISONED"
            elif fault == "changed_ready":
                ready_path.write_bytes(b"changed")
            elif fault == "output_started":
                files.write_vectors(benchmark_sample_program(2)[0], b"\0" * 24576)
            with pytest.raises(BenchmarkFilesError):
                files.begin_worker_execution()
    finally:
        files.close()
        os.close(borrowed)


def test_cpu_capture_does_not_gain_general_reentrant_context_semantics(tmp_path, monkeypatch):
    files, _, borrowed = stage_files(tmp_path, monkeypatch, 1)
    try:
        with files, pytest.raises(BenchmarkFilesError):
            files.begin_worker_execution()
        with pytest.raises(BenchmarkFilesError):
            files.begin_worker_execution()
    finally:
        files.close()
        os.close(borrowed)


@pytest.mark.parametrize("fault", ("missing", "nonempty", "symlink", "hardlink", "mode", "acl"))
def test_untrusted_ready_member_is_not_created_or_overwritten(tmp_path, monkeypatch, fault):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    other = tmp_path / "untouched"
    other.write_bytes(b"original")
    if fault == "symlink":
        path.symlink_to(other)
    elif fault == "hardlink":
        os.link(other, path)
    elif fault != "missing":
        path.touch(mode=0o640)
        path.chmod(0o640)
        if fault == "nonempty":
            path.write_bytes(b"old")
        elif fault == "mode":
            path.chmod(0o660)
        elif fault == "acl":
            from tests.unit.test_embedding_device_benchmark_files import set_acl

            set_acl(path, directory=False)
    ready = ready_for_process(monkeypatch)
    try:
        with files:
            with pytest.raises(BenchmarkFilesError, match="WRITE_UNCERTAIN"):
                files.write_cuda_ready(ready)
            with pytest.raises(BenchmarkFilesError):
                files.assert_current()
        assert other.read_bytes() == b"original"
        if fault == "missing":
            assert not path.exists()
        if fault == "nonempty":
            assert path.read_bytes() == b"old"
    finally:
        os.close(borrowed)


@pytest.mark.parametrize(
    "fault", ("pid", "job_id", "invocation_raw_sha256", "worker_uid", "groups")
)
def test_readiness_identity_rejected_before_write(tmp_path, monkeypatch, fault):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    body = ready.model_dump(mode="json", exclude={"ready_sha256"})
    if fault == "groups":
        monkeypatch.setattr(module.os, "getgroups", lambda: [])
    else:
        body[fault] = {
            "pid": os.getpid() + 1,
            "job_id": "job_" + "a" * 32,
            "invocation_raw_sha256": "sha256:" + "a" * 64,
            "worker_uid": os.getuid() + 1,
        }[fault]
        ready = BenchmarkCudaReady.model_validate(seal(body, "ready_sha256"))
    try:
        with files, pytest.raises(BenchmarkFilesError):
            files.write_cuda_ready(ready)
        assert path.stat().st_size == 0
    finally:
        os.close(borrowed)


def test_cpu_never_writes_ready_member(tmp_path, monkeypatch):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 1)
    try:
        with files, pytest.raises(BenchmarkFilesError):
            files.write_cuda_ready(ready_for_process(monkeypatch))
        assert not (execution / "cuda-ready.json").exists()
    finally:
        os.close(borrowed)


def test_successful_partial_writes_seal_exact_bytes(tmp_path, monkeypatch):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    original = os.write
    calls = []

    def short_write(descriptor, raw):
        calls.append(True)
        return original(descriptor, raw[:137])

    try:
        with files:
            monkeypatch.setattr(module.os, "write", short_write)
            files.write_cuda_ready(ready)
            files.assert_current()
            assert path.read_bytes() == benchmark_cuda_ready_bytes(ready)
            assert len(calls) > 1 and files._budget == 0
    finally:
        os.close(borrowed)


@pytest.mark.parametrize(
    "fault", ("zero_write", "partial_write", "fsync", "close", "late_mutation")
)
def test_uncertain_write_or_close_and_post_seal_mutation_fail_closed(tmp_path, monkeypatch, fault):
    files, execution, borrowed = stage_files(tmp_path, monkeypatch, 2)
    path = execution / "cuda-ready.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    ready = ready_for_process(monkeypatch)
    original_write, original_close = os.write, os.close
    try:
        with files:
            if fault == "late_mutation":
                files.write_cuda_ready(ready)
                path.write_bytes(b"changed")
                with pytest.raises(BenchmarkFilesError):
                    files.assert_current()
                return
            with monkeypatch.context() as patch:
                if fault == "zero_write":
                    patch.setattr(module.os, "write", lambda *_args: 0)
                elif fault == "partial_write":
                    calls = []

                    def partial(descriptor, raw):
                        calls.append(True)
                        if len(calls) == 1:
                            return original_write(descriptor, raw[:5])
                        raise OSError("synthetic interrupted write")

                    patch.setattr(module.os, "write", partial)
                elif fault == "fsync":
                    patch.setattr(module.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError()))
                else:

                    def uncertain_close(descriptor):
                        original_close(descriptor)
                        raise OSError("synthetic uncertain close")

                    patch.setattr(module.os, "close", uncertain_close)
                with pytest.raises(BenchmarkFilesError, match="UNCERTAIN"):
                    files.write_cuda_ready(ready)
            with pytest.raises(BenchmarkFilesError):
                files.assert_current()
            with pytest.raises(BenchmarkFilesError):
                files.write_cuda_ready(ready)
            if fault == "partial_write":
                assert path.stat().st_size == 5
    finally:
        original_close(borrowed)
