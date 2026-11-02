"""Closed proc-reader routing; synthetic ports, no GPU, credentials, or PID1 access."""

from pathlib import Path

import pytest
from eom_catalog_service import embedding_cuda_probe_resource_observation as owner


@pytest.mark.parametrize("uid", (1000, 1100))
def test_worker_fdinfo_uses_existing_nondumpable_process_reader(monkeypatch, uid):
    calls = []

    def native(path, *, maximum, owner_uid):
        calls.append((path, maximum, owner_uid))
        return b"validated kernel fd flags"

    def generic(*args, **kwargs):
        pytest.fail("worker proc storage ownership is not the process credential fence")

    monkeypatch.setattr(owner, "read_live_native_process_member", native, raising=False)
    monkeypatch.setattr(owner, "read_live_runtime_os_file", generic)
    assert owner._read_fdinfo(123, 14, uid) == b"validated kernel fd flags"
    assert calls == [(Path("/proc/123/fdinfo/14"), 16384, uid)]


def test_pid1_fdinfo_keeps_existing_root_owned_protection(monkeypatch):
    calls = []

    def generic(path, *, maximum, owner_uid):
        calls.append((path, maximum, owner_uid))
        return b"validated retained descriptor"

    def native(*args, **kwargs):
        pytest.fail("PID1 is not a native unprivileged worker")

    monkeypatch.setattr(owner, "read_live_native_process_member", native, raising=False)
    monkeypatch.setattr(owner, "read_live_runtime_os_file", generic)
    assert owner._read_fdinfo(1, 80, 0) == b"validated retained descriptor"
    assert calls == [(Path("/proc/1/fdinfo/80"), 16384, 0)]
