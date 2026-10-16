"""Fake kernel readonly installation captures, never a held physical lease or GPU grant."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    RootLocalCudaDeviceNode,
    RootLocalCudaSharedGpuLease,
)
from eom_catalog_service import embedding_cuda_probe_resource_files as resources

from tests.unit.test_embedding_cuda_probe_resource_files import fixture


def prepared(monkeypatch):
    kernel, _unused_borrowed_guard, _device = fixture(monkeypatch)
    resources.os.O_NONBLOCK = os.O_NONBLOCK
    nodes = tuple(
        RootLocalCudaDeviceNode.model_validate(
            {
                "role": role,
                "path": name,
                "epoch": resources._epoch(kernel.values[20 + index]),
                "rdev_major": os.major(kernel.values[20 + index].st_rdev),
                "rdev_minor": os.minor(kernel.values[20 + index].st_rdev),
            }
        )
        for index, (role, (name, _major, _minor)) in enumerate(
            resources.CUDA_DEVICE_NODE_SPECS.items()
        )
    )
    lease = RootLocalCudaSharedGpuLease.model_validate(
        {
            "source": "ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0",
            "resource_id": "GPU0",
            "lock_path": "/run/eom-gpu-lease/gpu0.lock",
            "filesystem": "tmpfs",
            "lease_gid": 2468,
            "parent_epoch": resources._epoch(kernel.values[11])[:5],
            "lock_epoch": resources._epoch(kernel.values[99]),
            "holder_pid": 123,
            "holder_start_time_ticks": 987,
        }
    )
    monkeypatch.setattr(
        resources.fcntl,
        "flock",
        lambda *_: pytest.fail("installation identity must not acquire/release physical locks"),
        raising=False,
    )
    return kernel, nodes, lease


def test_installation_owns_only_new_readonly_fds_and_has_no_ownership_interface(monkeypatch):
    kernel, nodes, lease = prepared(monkeypatch)
    captured = resources.capture_cuda_installation_resource_files(nodes, lease)
    assert not hasattr(captured, "assert_owned")
    kernel.pid += 1  # Historical probe PID is not a claim that the current caller owns its lock.
    captured.assert_current()
    captured.close()
    assert set(kernel.closed) == {10, 11, 20, 21, 22, 23, 99}
    assert kernel.flags[99] & os.O_ACCMODE == os.O_RDONLY
    assert all(kernel.flags[fd] & os.O_PATH for fd in range(20, 24))
    captured.close()
    assert len(kernel.closed) == 7


@pytest.mark.parametrize("name", ("nvidiactl", "gpu0.lock"))
def test_partial_capture_closes_every_owned_fd_without_flocking(monkeypatch, name):
    kernel, nodes, lease = prepared(monkeypatch)
    kernel.open_failure = name
    with pytest.raises(resources.CudaProbeResourceFilesError, match="CAPTURE_INVALID"):
        resources.capture_cuda_installation_resource_files(nodes, lease)
    assert set(kernel.closed) == set(kernel.opened)


@pytest.mark.parametrize("fault", ("node", "lease", "parent", "rw", "close_failure"))
def test_drift_or_close_failure_does_not_leave_owned_fds_open(monkeypatch, fault):
    kernel, nodes, lease = prepared(monkeypatch)
    captured = resources.capture_cuda_installation_resource_files(nodes, lease)
    if fault in {"node", "lease", "parent"}:
        key = {"node": 20, "lease": 99, "parent": 11}[fault]
        kernel.named[key].st_ino += 1
    elif fault == "rw":
        kernel.flags[99] |= os.O_RDWR
    else:
        kernel.close_failure = 20
    with pytest.raises(resources.CudaProbeResourceFilesError):
        captured.close()
    assert set(kernel.closed) == {10, 11, 20, 21, 22, 23, 99}


def test_external_node_paths_never_become_open_targets(monkeypatch):
    kernel, nodes, lease = prepared(monkeypatch)
    invalid = nodes[0].model_copy(update={"path": str(Path("/tmp/untrusted"))})
    with pytest.raises(resources.CudaProbeResourceFilesError, match="CAPTURE_INVALID"):
        resources.capture_cuda_installation_resource_files((invalid, *nodes[1:]), lease)
    assert kernel.opened == []
