"""Explicit fake kernel/lease ports only; no GPU node open, ownership or root acceptance."""

from __future__ import annotations

import fcntl
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from eom_catalog_service import embedding_cuda_probe_resource_files as capture

from tests.unit.embedding_installed_runtime_fixtures import runtime_proof
from tests.unit.test_embedding_runtime_process_identity import fdinfo, process_stat


def metadata(mode, inode, *, device=1, gid=0, rdev=0):
    return SimpleNamespace(
        st_dev=device,
        st_ino=inode,
        st_uid=0,
        st_gid=gid,
        st_mode=mode,
        st_nlink=1,
        st_size=0,
        st_mtime_ns=1000,
        st_ctime_ns=1000,
        st_rdev=rdev,
    )


class FakeKernel:
    def __init__(self):
        self.opened = []
        self.closed = []
        self.flags = {99: os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC}
        self.pid = 123
        self.ticks = 987
        self.no_lock = False
        self.close_failure = None
        self.open_failure = None
        self.identity = True
        self.values = {
            10: metadata(stat.S_IFDIR | 0o755, 10),
            11: metadata(stat.S_IFDIR | 0o750, 11, device=2, gid=2468),
            99: metadata(stat.S_IFREG | 0o640, 99, device=2, gid=2468),
        }
        self.names = {str(Path("/dev")): 10, str(Path("/run/eom-gpu-lease")): 11, "gpu0.lock": 99}
        for index, (_role, (path, major, minor)) in enumerate(
            capture.CUDA_DEVICE_NODE_SPECS.items()
        ):
            number = 20 + index
            self.values[number] = metadata(
                stat.S_IFCHR | 0o666,
                number,
                rdev=os.makedev(511 if major is None else major, minor),
            )
            self.names[Path(path).name] = number
        self.named = dict(self.values)

    def open(self, path, flags, *, dir_fd=None):
        key = str(path)
        if self.open_failure == key:
            raise OSError("synthetic open failure")
        descriptor = self.names[key]
        self.opened.append(descriptor)
        self.flags[descriptor] = flags
        return descriptor

    def fstat(self, fd):
        return self.values[fd]

    def stat(self, path, *, dir_fd=None, follow_symlinks=False):
        return self.named[self.names[str(path)]]

    def close(self, fd):
        self.closed.append(fd)
        if self.close_failure == fd:
            raise OSError("synthetic close failure")

    def control(self, fd, operation):
        if operation == fcntl.F_GETFL:
            return self.flags[fd] & ~os.O_CLOEXEC
        if operation == fcntl.F_GETFD:
            return fcntl.FD_CLOEXEC if self.flags[fd] & os.O_CLOEXEC else 0
        raise AssertionError(operation)

    def read(self, path, *, maximum, owner_uid):
        if path.name == "stat":
            return process_stat(self.pid, self.ticks)
        if path.parent.name == "fdinfo":
            value = self.values[int(path.name)]
            raw = fdinfo(self.pid, value.st_dev, value.st_ino, self.flags[int(path.name)])
            return raw.split(b"lock:")[0] if self.no_lock else raw
        raise AssertionError(path)


class FakeLease:
    def __init__(self):
        self.valid = True
        self.descriptor = 99

    def assert_valid(self):
        if not self.valid:
            raise ValueError("synthetic invalid lease")

    def fileno(self):
        return self.descriptor

    def close(self):
        pytest.fail("capture must never release a borrowed lease")


def fixture(monkeypatch):
    kernel = FakeKernel()
    adapter = SimpleNamespace(
        **{
            name: getattr(os, name)
            for name in (
                "O_RDONLY",
                "O_DIRECTORY",
                "O_NOFOLLOW",
                "O_CLOEXEC",
                "O_PATH",
                "O_ACCMODE",
                "makedev",
                "major",
                "minor",
            )
        }
    )
    adapter.open = kernel.open
    adapter.fstat = kernel.fstat
    adapter.stat = kernel.stat
    adapter.close = kernel.close
    adapter.getpid = lambda: kernel.pid
    adapter.geteuid = lambda: 2014
    monkeypatch.setattr(capture, "os", adapter)
    monkeypatch.setattr(
        capture,
        "fcntl",
        SimpleNamespace(
            F_GETFL=fcntl.F_GETFL,
            F_GETFD=fcntl.F_GETFD,
            FD_CLOEXEC=fcntl.FD_CLOEXEC,
            fcntl=kernel.control,
        ),
    )
    monkeypatch.setattr(
        capture, "grp", SimpleNamespace(getgrnam=lambda _name: SimpleNamespace(gr_gid=2468))
    )

    def identity(_profile):
        if not kernel.identity:
            raise ValueError("synthetic identity denial")

    monkeypatch.setattr(capture, "require_native_embedding_identity", identity)
    monkeypatch.setattr(capture, "observe_runtime_device", lambda value: value.numeric_device)
    monkeypatch.setattr(capture, "read_live_runtime_os_file", kernel.read)
    module = ModuleType("eom_gpu_lease")
    module.SharedGpuLease = FakeLease
    monkeypatch.setitem(sys.modules, "eom_gpu_lease", module)
    return kernel, FakeLease(), runtime_proof("CUDA_INDEX_FP32").device_capture


def test_capture_is_path_only_borrowed_lease_and_never_a_compute_grant(monkeypatch):
    kernel, lease, expected = fixture(monkeypatch)
    with capture.capture_cuda_probe_resource_files(expected, lease) as observed:
        assert len(observed.device_nodes) == 4
        assert observed.shared_gpu_lease.holder_pid == 123
        assert observed.shared_gpu_lease.holder_start_time_ticks == 987
        assert not hasattr(observed, "assert_owned")
        assert all(kernel.flags[fd] & os.O_PATH for fd in (20, 21, 22, 23))
        assert all(
            not kernel.flags[fd] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            for fd in kernel.opened
        )
    assert set(kernel.closed) == set(kernel.opened) and 99 not in kernel.closed
    observed.close()
    assert len(kernel.closed) == 6


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "wrong_lease",
        "unheld",
        "bad_lease",
        "device_type",
        "owner",
        "major",
        "parent_write",
        "lease_rw",
        "lease_inheritable",
        "open",
    ],
)
def test_capture_refuses_before_use_and_closes_every_owned_partial_descriptor(monkeypatch, fault):
    kernel, lease, expected = fixture(monkeypatch)
    if fault == "identity":
        kernel.identity = False
    elif fault == "wrong_lease":
        lease = object()
    elif fault == "unheld":
        kernel.no_lock = True
    elif fault == "bad_lease":
        lease.valid = False
    elif fault == "device_type":
        kernel.values[20].st_mode = stat.S_IFREG | 0o666
    elif fault == "owner":
        kernel.values[20].st_uid = 1000
    elif fault == "major":
        kernel.values[20].st_rdev = os.makedev(999, 0)
    elif fault == "parent_write":
        kernel.values[10].st_mode |= 0o020
    elif fault == "lease_rw":
        kernel.flags[99] |= os.O_RDWR
    elif fault == "lease_inheritable":
        kernel.flags[99] &= ~os.O_CLOEXEC
    elif fault == "open":
        kernel.open_failure = "nvidia-uvm"
    with pytest.raises(capture.CudaProbeResourceFilesError):
        capture.capture_cuda_probe_resource_files(expected, lease)
    assert sorted(kernel.closed) == sorted(kernel.opened) and 99 not in kernel.closed


@pytest.mark.parametrize(
    "fault",
    [
        "pid",
        "start",
        "named_node",
        "rdev",
        "flags",
        "lease_fd",
        "unlock",
        "lease_invalid",
        "parent_changed",
        "parent_flags",
        "lease_status_flag",
    ],
)
def test_live_capture_revalidates_epoch_process_and_exact_held_description(monkeypatch, fault):
    kernel, lease, expected = fixture(monkeypatch)
    observed = capture.capture_cuda_probe_resource_files(expected, lease)
    if fault == "pid":
        kernel.pid += 1
    elif fault == "start":
        kernel.ticks += 1
    elif fault == "named_node":
        kernel.named[20] = metadata(stat.S_IFCHR | 0o666, 100)
    elif fault == "rdev":
        kernel.values[20].st_rdev = os.makedev(195, 1)
    elif fault == "flags":
        kernel.flags[20] &= ~os.O_CLOEXEC
    elif fault == "lease_fd":
        lease.descriptor = 98
    elif fault == "unlock":
        kernel.no_lock = True
    elif fault == "lease_invalid":
        lease.valid = False
    elif fault == "parent_changed":
        kernel.named[10] = metadata(stat.S_IFDIR | 0o755, 100)
    elif fault == "parent_flags":
        kernel.flags[10] &= ~os.O_CLOEXEC
    elif fault == "lease_status_flag":
        kernel.flags[99] ^= os.O_NONBLOCK
    with pytest.raises(capture.CudaProbeResourceFilesError):
        observed.assert_current()
    with pytest.raises(capture.CudaProbeResourceFilesError):
        observed.close()
    assert sorted(kernel.closed) == sorted(kernel.opened) and 99 not in kernel.closed


def test_cleanup_attempts_all_owned_descriptors_after_one_close_failure(monkeypatch):
    kernel, lease, expected = fixture(monkeypatch)
    observed = capture.capture_cuda_probe_resource_files(expected, lease)
    kernel.close_failure = 22
    with pytest.raises(capture.CudaProbeResourceFilesError, match="CLEANUP_UNCERTAIN"):
        observed.close()
    assert sorted(kernel.closed) == sorted(kernel.opened) and 99 not in kernel.closed


def test_optional_resource_adapter_import_has_no_gpu_model_lease_or_orchestrator_side_effect():
    code = (
        "import sys;import eom_catalog_service.embedding_cuda_probe_resource_files;"
        "forbidden={'torch','transformers','eom_gpu_lease','eom_orchestrator','sqlalchemy'};"
        "assert not ({name.split('.',1)[0] for name in sys.modules}&forbidden);"
        "print('RESOURCE_CAPTURE_IMPORT_ONLY=PASS')"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=False, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "RESOURCE_CAPTURE_IMPORT_ONLY=PASS"
