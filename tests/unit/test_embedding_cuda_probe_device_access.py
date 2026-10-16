"""Fake device open/readback ports only; no real GPU device or initialization."""

from __future__ import annotations

import os

import pytest
from eom_catalog_service import embedding_cuda_probe_resource_files as capture

from tests.unit.test_embedding_cuda_probe_resource_files import fixture


def prepared(monkeypatch):
    kernel, lease, expected = fixture(monkeypatch)
    capture.os.O_RDWR, capture.os.O_NONBLOCK = os.O_RDWR, os.O_NONBLOCK
    before = kernel.open

    def opened(path, flags, *, dir_fd=None):
        if flags & os.O_ACCMODE == os.O_RDWR and not flags & os.O_PATH:
            if kernel.open_failure == str(path):
                raise OSError("synthetic device R/W denial")
            original = kernel.names[str(path)]
            descriptor = original + 40
            kernel.values[descriptor] = kernel.values[original]
            kernel.flags[descriptor] = flags
            kernel.opened.append(descriptor)
            return descriptor
        return before(path, flags, dir_fd=dir_fd)

    capture.os.open = opened
    return kernel, lease, expected


def test_read_write_access_is_separate_from_path_capture_and_borrows_lifetime(monkeypatch):
    kernel, lease, expected = prepared(monkeypatch)
    with capture.capture_cuda_probe_resource_files(expected, lease) as files:
        assert not hasattr(files, "assert_owned")
        hints = files.resource_descriptors
        assert hints.lease_fd == 99 and hints.nvidia0_fd == 20
        with capture.open_cuda_probe_device_access(files) as access:
            access.assert_owned()
            assert all(kernel.flags[fd] & os.O_ACCMODE == os.O_RDWR for fd in range(60, 64))
            assert not kernel.closed
        assert set(kernel.closed) == set(range(60, 64))
        files.assert_current()
    assert 99 not in kernel.closed


def test_partial_rw_open_denial_closes_only_owned_rw_and_retains_path_scope(monkeypatch):
    kernel, lease, expected = prepared(monkeypatch)
    with capture.capture_cuda_probe_resource_files(expected, lease) as files:
        kernel.open_failure = "nvidiactl"
        with pytest.raises(capture.CudaProbeResourceFilesError, match="DEVICE_ACCESS_INVALID"):
            capture.open_cuda_probe_device_access(files)
        assert kernel.closed == [60]
        files.assert_current()


@pytest.mark.parametrize("fault", ("flags", "pid", "lease", "closed_paths"))
def test_active_guard_rechecks_device_process_and_borrowed_lock(monkeypatch, fault):
    kernel, lease, expected = prepared(monkeypatch)
    with capture.capture_cuda_probe_resource_files(expected, lease) as files:
        access = capture.open_cuda_probe_device_access(files)
        if fault == "flags":
            kernel.flags[60] = os.O_RDONLY | os.O_CLOEXEC
        elif fault == "pid":
            kernel.pid += 1
        elif fault == "lease":
            kernel.no_lock = True
        else:
            files.close()
        with pytest.raises((capture.CudaProbeResourceFilesError, ValueError)):
            access.assert_owned()
        with pytest.raises((capture.CudaProbeResourceFilesError, ValueError)):
            access.close()
        assert set(range(60, 64)) <= set(kernel.closed) and 99 not in kernel.closed
        # Restore only fake liveness so the owning fixture can close its PATH handles.
        kernel.pid = 123
        kernel.no_lock = False
