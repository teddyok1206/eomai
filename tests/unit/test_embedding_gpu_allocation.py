"""Actual Linux flock/dup tests over synthetic tmpfs metadata; no production GPU work."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys

import pytest
from eom_catalog_service.embedding_gpu_allocation import (
    NativeEmbeddingGpuAllocationError,
    hold_native_embedding_gpu_allocation,
)
from eom_gpu_lease import SharedGpuLeaseError
from eom_gpu_lease import lease as physical


@pytest.fixture
def allocation_policy(tmp_path, monkeypatch):
    directory = tmp_path / "lease"
    directory.mkdir(mode=0o750)
    path = directory / "gpu0.lock"
    path.touch(mode=0o640)
    path.chmod(0o640)
    policy = physical._LeasePolicy(path, tmp_path, os.getuid(), os.getgid())
    device = path.stat().st_dev
    monkeypatch.setattr(physical, "_production_policy", lambda: policy)
    monkeypatch.setattr(
        physical,
        "_read_mountinfo",
        lambda: f"1 0 {os.major(device)}:{os.minor(device)} / /synthetic rw - tmpfs tmpfs rw\n",
    )
    return policy


def test_acquired_scope_keeps_one_original_flock_until_caller_finishes(allocation_policy):
    with hold_native_embedding_gpu_allocation() as first:
        assert first is not None
        descriptor = first.fileno()
        first.assert_valid()
        with hold_native_embedding_gpu_allocation() as second:
            assert second is None
        assert first.fileno() == descriptor
        first.assert_valid()
        with pytest.raises(SharedGpuLeaseError, match="BUSY"):
            physical.acquire_shared_gpu_lease()
    with hold_native_embedding_gpu_allocation() as after:
        assert after is not None


def test_worker_close_does_not_unlock_an_independently_retained_description(allocation_policy):
    with hold_native_embedding_gpu_allocation() as owned:
        assert owned is not None
        retained = fcntl.fcntl(owned.fileno(), fcntl.F_DUPFD_CLOEXEC, 3)
    try:
        with hold_native_embedding_gpu_allocation() as blocked:
            assert blocked is None
    finally:
        os.close(retained)
    with hold_native_embedding_gpu_allocation() as available:
        assert available is not None


def test_invalid_inode_is_not_a_busy_fallback(allocation_policy):
    allocation_policy.path.chmod(0o660)
    with pytest.raises(NativeEmbeddingGpuAllocationError), hold_native_embedding_gpu_allocation():
        pytest.fail("invalid allocation must never enter body")


def test_error_after_acquisition_is_not_converted_into_a_second_busy_result(allocation_policy):
    entered = 0
    with (
        pytest.raises(SharedGpuLeaseError, match="BUSY"),
        hold_native_embedding_gpu_allocation() as owned,
    ):
        assert owned is not None
        entered += 1
        raise SharedGpuLeaseError("BUSY")
    assert entered == 1
    with hold_native_embedding_gpu_allocation() as available:
        assert available is not None


def test_cleanup_failure_does_not_become_success_or_fallback(allocation_policy, monkeypatch):
    close = physical.SharedGpuLease.close

    def failed_close(lease):
        close(lease)
        raise SharedGpuLeaseError("INVALID")

    monkeypatch.setattr(physical.SharedGpuLease, "close", failed_close)
    with (
        pytest.raises(SharedGpuLeaseError, match="INVALID"),
        hold_native_embedding_gpu_allocation() as owned,
    ):
        assert owned is not None


def test_cross_process_dup_does_not_change_original_kernel_lock_holder(allocation_policy):
    # An inherited descriptor has the same open-file description as SCM_RIGHTS.
    # Reapplying flock does not make the independent worker-PID proof true.
    code = """import fcntl,json,os,sys
fd=int(sys.argv[1])
def owner():
    with open('/proc/self/fdinfo/'+str(fd),encoding='ascii') as stream:
        locks=[line.split() for line in stream if line.startswith('lock:')]
    assert len(locks)==1 and locks[0][2:5]==['FLOCK','ADVISORY','WRITE']
    return int(locks[0][5])
before=owner()
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
print(json.dumps({'child_pid':os.getpid(),'before':before,'after':owner()}))
"""
    with hold_native_embedding_gpu_allocation() as owned:
        assert owned is not None
        observed = subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(owned.fileno())],
            pass_fds=(owned.fileno(),),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        result = json.loads(observed.stdout)
        assert result["before"] == result["after"] == os.getpid()
        assert result["child_pid"] != os.getpid()
        owned.assert_valid()
