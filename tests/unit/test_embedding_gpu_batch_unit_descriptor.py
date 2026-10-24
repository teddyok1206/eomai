"""Exact per-instance unit binding; filesystem effects are local fixtures, never PID1."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service import embedding_gpu_batch_unit_descriptor as descriptor


def test_descriptor_contains_only_the_original_absolute_allocation_path():
    attempt = "a" * 32
    assert descriptor.embedding_gpu_batch_descriptor_path(attempt) == Path(
        "/run/systemd/system/eom-embedding-native-gpu-batch@"
        + attempt
        + ".service.d/10-allocation.conf"
    )
    assert descriptor.embedding_gpu_batch_descriptor_bytes(attempt) == (
        "[Service]\nOpenFile=\nOpenFile=/run/eom-native-embedding-gpu-batch/"
        + attempt
        + "/allocation.json:gpu-batch-allocation:read-only\n"
    ).encode("ascii")


@pytest.mark.parametrize("attempt", ("../other", "A" * 32, "a" * 31, "a" * 32 + "\n"))
def test_no_path_or_property_injection(attempt):
    with pytest.raises(ValueError):
        descriptor.embedding_gpu_batch_descriptor_bytes(attempt)


@pytest.mark.parametrize("fault", ("absent", "other_instance", "extra"))
def test_only_one_exact_original_drop_in_is_accepted(fault):
    attempt = "a" * 32
    correct = str(descriptor.embedding_gpu_batch_descriptor_path(attempt))
    descriptor.require_embedding_gpu_batch_descriptor(attempt, correct)
    value = {
        "absent": "",
        "other_instance": correct.replace(attempt, "b" * 32),
        "extra": correct + " /etc/systemd/system/override.conf",
    }[fault]
    with pytest.raises(ValueError, match="EMBEDDING_GPU_BATCH_UNIT_DESCRIPTOR_INVALID"):
        descriptor.require_embedding_gpu_batch_descriptor(attempt, value)


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(descriptor, "_UNIT_ROOT", tmp_path)
    monkeypatch.setattr(descriptor.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(descriptor.os, "getresgid", lambda: (0, 0, 0))
    monkeypatch.setattr(descriptor, "fixed_owner_identity", lambda: object())
    path = descriptor.embedding_gpu_batch_descriptor_path("a" * 32)
    path.parent.mkdir(mode=0o700)

    @contextmanager
    def directory(value, **kwargs):
        assert value == path.parent and kwargs["uid"] == kwargs["gid"] == 0
        assert kwargs["mode"] == 0o700
        fd = os.open(value, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield fd
        finally:
            os.close(fd)

    def create(fd, name, raw, **kwargs):
        assert name == path.name and kwargs == {"owner_gid": 0, "mode": 0o444}
        out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444, dir_fd=fd)
        try:
            os.write(out, raw)
        finally:
            os.close(out)

    monkeypatch.setattr(descriptor, "protected_cpu_handoff_directory", directory)
    monkeypatch.setattr(descriptor, "create_protected_cpu_handoff_member", create)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""))
    monkeypatch.setattr(descriptor.subprocess, "run", run)
    return path, run


@pytest.mark.parametrize("reload_failure", (False, True))
def test_exclusive_file_and_reload_uncertainty_never_clobber_or_replay(local, reload_failure):
    path, run = local
    if reload_failure:
        run.return_value.returncode = 1
        with pytest.raises(ValueError, match="RELOAD_UNCERTAIN"):
            descriptor.prepare_embedding_gpu_batch_descriptor("a" * 32)
    else:
        descriptor.prepare_embedding_gpu_batch_descriptor("a" * 32)
    original = path.stat()
    assert path.read_bytes() == descriptor.embedding_gpu_batch_descriptor_bytes("a" * 32)
    assert original.st_mode & 0o777 == 0o444
    with pytest.raises(ValueError, match="ALREADY_PRESENT"):
        descriptor.prepare_embedding_gpu_batch_descriptor("a" * 32)
    assert path.stat().st_ino == original.st_ino
    run.assert_called_once_with(
        ("/usr/bin/systemctl", "--no-ask-password", "daemon-reload"),
        capture_output=True,
        check=False,
        timeout=10,
        env=descriptor._ENV,
    )


def test_an_existing_unrelated_drop_in_is_not_replaced(local):
    path, run = local
    unrelated = path.parent / "99-external.conf"
    unrelated.write_bytes(b"not owned by this operation")
    with pytest.raises(ValueError, match="ALREADY_PRESENT"):
        descriptor.prepare_embedding_gpu_batch_descriptor("a" * 32)
    assert unrelated.read_bytes() == b"not owned by this operation"
    assert not path.exists()
    run.assert_not_called()


def test_concurrent_creation_dispatches_only_one_reload_without_overwriting(local):
    path, run = local

    def create():
        try:
            descriptor.prepare_embedding_gpu_batch_descriptor("a" * 32)
        except (ValueError, FileExistsError):
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: create(), range(2))) == 1
    assert path.read_bytes() == descriptor.embedding_gpu_batch_descriptor_bytes("a" * 32)
    run.assert_called_once()
