"""Root physical-GPU FD readback shared by explicit CUDA probe and image unit owners."""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    CUDA_DEVICE_NODE_SPECS,
    RootLocalCudaDeviceNode,
    RootLocalCudaSharedGpuLease,
    validate_rootlocal_cuda_resource_file_metadata,
)
from eom_catalog_contracts.embedding_native_cuda_probe import (
    NativeCudaProbeLeaseReady,
    NativeCudaProbeResult,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    parse_rootlocal_evidence_document,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_process_identity import require_exclusive_flock_fdinfo

if TYPE_CHECKING:
    from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady

_LOCK = Path("/run/eom-gpu-lease/gpu0.lock")
_PID1_FDS = Path("/proc/1/fd")
_MAX_PID1_FDS = 4096
_MAX_IMAGE_WORKER_FDS = 4096
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8"}
type ProbeReport = NativeCudaProbeLeaseReady | NativeCudaProbeResult


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("NATIVE_CUDA_PROBE_RESOURCE_OBSERVATION_INVALID")


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _fd_flags(raw: bytes) -> int:
    flags = [
        line.split(b":", 1)[1].strip() for line in raw.splitlines() if line.startswith(b"flags:")
    ]
    _require(len(flags) == 1 and re.fullmatch(rb"[0-7]{1,16}", flags[0]) is not None)
    return int(flags[0], 8)


def _read_fdinfo(pid: int, descriptor: int, uid: int) -> bytes:
    return read_live_runtime_os_file(
        Path("/proc") / str(pid) / "fdinfo" / str(descriptor), maximum=16384, owner_uid=uid
    )


def _require_tmpfs_device(device: int) -> None:
    raw = read_live_runtime_os_file(
        Path("/proc") / str(os.getpid()) / "mountinfo", maximum=1024**2, owner_uid=0
    )
    filesystems: set[str] = set()
    target = f"{os.major(device)}:{os.minor(device)}"
    for line in raw.decode("ascii").splitlines():
        left, separator, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        _require(bool(separator) and len(fields) >= 6 and len(tail) >= 3)
        if fields[2] == target:
            filesystems.add(tail[0])
    _require(filesystems == {"tmpfs"})


@dataclass(frozen=True, slots=True)
class CudaProbeResourceObservation:
    device_nodes: tuple[RootLocalCudaDeviceNode, ...]
    shared_gpu_lease: RootLocalCudaSharedGpuLease
    pid1_descriptor: int


@dataclass(frozen=True, slots=True)
class ImageUnitGpuResources:
    """Image-only physical resource readback, not a fabricated native probe report."""

    device_nodes: tuple[RootLocalCudaDeviceNode, ...]
    shared_gpu_lease: RootLocalCudaSharedGpuLease
    pid1_descriptor: int


type _RetainedGpuUnitResources = CudaProbeResourceObservation | ImageUnitGpuResources


def validate_cuda_probe_fdstore(raw: bytes, lease: RootLocalCudaSharedGpuLease) -> None:
    """Validate the fixed systemd255 projection; a display path is never inode identity."""
    _require(type(raw) is bytes and 0 < len(raw) <= 16 * 1024)
    # Reuse the bounded/duplicate/depth/integer-safe codec for an external array.
    rows = parse_rootlocal_evidence_document(b'{"store":' + raw + b"}", 16 * 1024 + 16)["store"]
    _require(type(rows) is list and len(rows) == 1 and type(rows[0]) is dict)
    row = rows[0]
    _require(set(row) == {"fdname", "type", "devno", "inode", "rdevno", "path", "flags"})
    device, inode = lease.lock_epoch[:2]
    _require(
        row["fdname"] == "eom-gpu0-lease"
        and type(row["type"]) is int
        and row["type"] == lease.lock_epoch[4]
        and type(row["inode"]) is int
        and row["inode"] == inode
        and type(row["devno"]) is list
        and len(row["devno"]) == 2
        and all(type(value) is int for value in row["devno"])
        and tuple(row["devno"]) == (os.major(device), os.minor(device))
        and row["rdevno"] is None
        and row["flags"] == "ro"
        and type(row["path"]) is str
        and 0 < len(row["path"]) <= 512
        and row["path"].startswith("/")
        and not any(ord(c) < 32 for c in row["path"])
    )


def _observe_pid1_retained_lock(lease: RootLocalCudaSharedGpuLease) -> int:
    """Read lock records, never open/dereference arbitrary stored file content."""
    matching: list[int] = []
    with os.scandir(_PID1_FDS) as entries:
        for count, entry in enumerate(entries, 1):
            _require(count <= _MAX_PID1_FDS and re.fullmatch(r"[0-9]{1,7}", entry.name) is not None)
            descriptor = int(entry.name)
            try:
                value = os.stat(_PID1_FDS / entry.name)
            except FileNotFoundError:
                continue  # An unrelated manager descriptor closed; no target observation yet.
            if _epoch(value) != lease.lock_epoch:
                continue
            raw = _read_fdinfo(1, descriptor, 0)
            flags = _fd_flags(raw)
            _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
            _require(bool(flags & os.O_CLOEXEC))
            require_exclusive_flock_fdinfo(
                raw,
                pid=lease.holder_pid,
                device=value.st_dev,
                inode=value.st_ino,
                descriptor_flags=flags,
            )
            _require(_epoch(os.stat(_PID1_FDS / entry.name)) == lease.lock_epoch)
            matching.append(descriptor)
    _require(len(matching) == 1)
    return matching[0]


def _observe_retained_store_descriptor(lease: RootLocalCudaSharedGpuLease, unit: str) -> int:
    result = subprocess.run(
        ("/usr/bin/systemd-analyze", "--no-pager", "--json=short", "fdstore", unit),
        capture_output=True,
        check=False,
        timeout=10,
        env=_ENV,
    )
    _require(result.returncode == 0 and len(result.stderr) <= 16384)
    validate_cuda_probe_fdstore(result.stdout, lease)
    return _observe_pid1_retained_lock(lease)


def observe_cuda_probe_retained_resources(
    observed: CudaProbeResourceObservation, *, unit: str
) -> CudaProbeResourceObservation:
    """After worker exit, validate retained physical fencing without reading dead worker FDs."""
    _require(os.getresuid() == (0, 0, 0) and type(observed) is CudaProbeResourceObservation)
    _require(
        re.fullmatch(r"eom-embedding-native-cuda-probe@[0-9a-f]{32}\.service", unit) is not None
    )
    _assert_retained_resources(observed, unit)
    return observed


def observe_benchmark_cuda_retained_resources(
    observed: CudaProbeResourceObservation, *, unit: str
) -> CudaProbeResourceObservation:
    """Benchmark-only retained fence, not installation-probe admission or cleanup authority."""
    try:
        _require(os.getresuid() == (0, 0, 0) and type(observed) is CudaProbeResourceObservation)
        _require(
            type(unit) is str
            and re.fullmatch(r"eom-embedding-benchmark-cuda@[0-9a-f]{32}\.service", unit)
            is not None
        )
        _assert_retained_resources(observed, unit)
        return observed
    except (ValueError, OSError, subprocess.TimeoutExpired, JsonSchemaError):
        raise ValueError("BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID") from None


def _assert_retained_resources(observed: _RetainedGpuUnitResources, unit: str) -> None:
    lease = RootLocalCudaSharedGpuLease.model_validate(observed.shared_gpu_lease)
    validate_rootlocal_cuda_resource_file_metadata(observed.device_nodes, lease)
    _require(_epoch(_LOCK.lstat()) == lease.lock_epoch)
    _require(_epoch(_LOCK.parent.lstat())[:5] == lease.parent_epoch)
    _require_tmpfs_device(lease.lock_epoch[0])
    _require(_observe_retained_store_descriptor(lease, unit) == observed.pid1_descriptor)
    _require(_epoch(_LOCK.lstat()) == lease.lock_epoch)
    _require(_epoch(_LOCK.parent.lstat())[:5] == lease.parent_epoch)
    for node in observed.device_nodes:
        _require(_epoch(Path(node.path).lstat()) == node.epoch)


@contextmanager
def hold_released_cuda_probe_resources(
    observed: CudaProbeResourceObservation,
) -> Iterator[None]:
    """Root cleanup proof only: hold the same now-free inode across post-retirement checks."""
    _require(os.getresuid() == (0, 0, 0) and type(observed) is CudaProbeResourceObservation)
    with _hold_released_resources(observed):
        yield


@contextmanager
def _hold_released_resources(observed: _RetainedGpuUnitResources) -> Iterator[None]:
    lease = RootLocalCudaSharedGpuLease.model_validate(observed.shared_gpu_lease)
    validate_rootlocal_cuda_resource_file_metadata(observed.device_nodes, lease)

    def current() -> None:
        _require(_epoch(_LOCK.lstat()) == lease.lock_epoch)
        _require(_epoch(_LOCK.parent.lstat())[:5] == lease.parent_epoch)
        for node in observed.device_nodes:
            _require(_epoch(Path(node.path).lstat()) == node.epoch)

    current()
    _require_tmpfs_device(lease.lock_epoch[0])
    descriptor = os.open(_LOCK, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        _require(_epoch(os.fstat(descriptor)) == lease.lock_epoch)
        # A separate open description cannot acquire this while PID1 retains the old flock.
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("NATIVE_CUDA_PROBE_RESOURCE_RELEASE_UNCERTAIN") from None
        current()
        try:
            yield
        finally:
            _require(_epoch(os.fstat(descriptor)) == lease.lock_epoch)
            current()
    finally:
        # Close only our new description. Never LOCK_UN on the old retained description.
        os.close(descriptor)


def _current_lease(pid: int, start_ticks: int, lease_gid: int) -> RootLocalCudaSharedGpuLease:
    parent, lock = _LOCK.parent.lstat(), _LOCK.lstat()
    lease = RootLocalCudaSharedGpuLease.model_validate(
        {
            "source": "ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0",
            "resource_id": "GPU0",
            "lock_path": str(_LOCK),
            "filesystem": "tmpfs",
            "lease_gid": lease_gid,
            "parent_epoch": _epoch(parent)[:5],
            "lock_epoch": _epoch(lock),
            "holder_pid": pid,
            "holder_start_time_ticks": start_ticks,
        }
    )
    _require_tmpfs_device(lock.st_dev)
    return lease


def _require_worker_lock(lease: RootLocalCudaSharedGpuLease, descriptor: int, uid: int) -> None:
    held = Path("/proc") / str(lease.holder_pid) / "fd" / str(descriptor)
    _require(_epoch(held.stat()) == lease.lock_epoch)
    raw = _read_fdinfo(lease.holder_pid, descriptor, uid)
    flags = _fd_flags(raw)
    _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
    _require(bool(flags & os.O_CLOEXEC))
    require_exclusive_flock_fdinfo(
        raw,
        pid=lease.holder_pid,
        device=lease.lock_epoch[0],
        inode=lease.lock_epoch[1],
        descriptor_flags=flags,
    )
    _require(_epoch(held.stat()) == lease.lock_epoch)


def _named_device_nodes() -> tuple[RootLocalCudaDeviceNode, ...]:
    nodes = []
    for role, (name, _major, _minor) in CUDA_DEVICE_NODE_SPECS.items():
        named = Path(name).lstat()
        nodes.append(
            RootLocalCudaDeviceNode.model_validate(
                {
                    "role": role,
                    "path": name,
                    "epoch": _epoch(named),
                    "rdev_major": os.major(named.st_rdev),
                    "rdev_minor": os.minor(named.st_rdev),
                }
            )
        )
    return tuple(nodes)


def observe_image_unit_gpu_resources(
    *,
    unit: str,
    pid: int,
    start_time_ticks: int,
    worker_uid: int,
    lease_gid: int,
) -> ImageUnitGpuResources:
    """Read real worker and PID1 locks; caller separately pins unit/process/policy.

    No worker-supplied descriptor/report or arbitrary file bytes are accepted.
    Only a root owner may call this. This function never signals, launches,
    retires or grants runtime/source/model authority.
    """
    from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_template

    _require(os.getresuid() == (0, 0, 0))
    image_gpu_unit_template(unit)
    _require(type(worker_uid) is int and 0 < worker_uid <= 4294967294)
    lease = _current_lease(pid, start_time_ticks, lease_gid)
    matches = []
    with os.scandir(Path("/proc") / str(pid) / "fd") as entries:
        for count, entry in enumerate(entries, 1):
            _require(
                count <= _MAX_IMAGE_WORKER_FDS
                and re.fullmatch(r"[0-9]{1,7}", entry.name) is not None
            )
            descriptor = int(entry.name)
            try:
                value = (Path("/proc") / str(pid) / "fd" / entry.name).stat()
            except FileNotFoundError:
                continue
            if _epoch(value) == lease.lock_epoch:
                _require_worker_lock(lease, descriptor, worker_uid)
                matches.append(descriptor)
    _require(len(matches) == 1)
    nodes = _named_device_nodes()
    validate_rootlocal_cuda_resource_file_metadata(nodes, lease)
    observed = ImageUnitGpuResources(nodes, lease, _observe_retained_store_descriptor(lease, unit))
    _require_worker_lock(lease, matches[0], worker_uid)
    _assert_retained_resources(observed, unit)
    return observed


def observe_image_unit_gpu_retained_resources(
    observed: ImageUnitGpuResources,
    *,
    unit: str,
) -> ImageUnitGpuResources:
    """Recheck image fencing after worker exit without dereferencing dead worker FDs."""
    from eom_catalog_service.image_gpu_unit_identity import image_gpu_unit_template

    _require(os.getresuid() == (0, 0, 0) and type(observed) is ImageUnitGpuResources)
    image_gpu_unit_template(unit)
    _assert_retained_resources(observed, unit)
    return observed


@contextmanager
def hold_released_image_unit_gpu_resources(observed: ImageUnitGpuResources) -> Iterator[None]:
    """Verify same-inode exclusive reacquisition only after the root owner's cleanup."""
    _require(os.getresuid() == (0, 0, 0) and type(observed) is ImageUnitGpuResources)
    with _hold_released_resources(observed):
        yield


def observe_cuda_probe_resources(
    report: ProbeReport, *, unit: str, lease_gid: int
) -> CudaProbeResourceObservation:
    """Both READY and final are independently read; no reported or named inode alone suffices."""
    _require(os.getresuid() == (0, 0, 0))
    _require(
        re.fullmatch(r"eom-embedding-native-cuda-probe@[0-9a-f]{32}\.service", unit) is not None
    )
    if type(report) is NativeCudaProbeLeaseReady:
        report = NativeCudaProbeLeaseReady.model_validate(report)
    elif type(report) is NativeCudaProbeResult:
        report = NativeCudaProbeResult.model_validate(report)
    else:
        raise ValueError("NATIVE_CUDA_PROBE_RESOURCE_OBSERVATION_INVALID")
    return _observe_native_report_resources(report, unit=unit, lease_gid=lease_gid)


def observe_benchmark_cuda_ready_resources(
    report: BenchmarkCudaReady, *, unit: str, lease_gid: int
) -> CudaProbeResourceObservation:
    """Benchmark-only kernel readback, not a fabricated probe or source/compute grant.

    Caller separately pins unit policy, process/cgroup/birth, executable/host and source/Job.
    The returned small physical observation shares the existing value layout, not probe status.
    """
    try:
        _require(os.getresuid() == (0, 0, 0))
        from eom_catalog_contracts.embedding_benchmark_cuda_ready import BenchmarkCudaReady

        _require(type(report) is BenchmarkCudaReady)
        report = BenchmarkCudaReady.model_validate(report)
        _require(unit == f"eom-embedding-benchmark-cuda@{report.execution_id}.service")
        return _observe_native_report_resources(report, unit=unit, lease_gid=lease_gid)
    except (ValueError, OSError, JsonSchemaError):
        raise ValueError("BENCHMARK_CUDA_RESOURCE_OBSERVATION_INVALID") from None


def _observe_native_report_resources(
    report: ProbeReport | BenchmarkCudaReady, *, unit: str, lease_gid: int
) -> CudaProbeResourceObservation:
    """Shared physical FD checks after each public closed-purpose/root identity guard."""
    _require(type(lease_gid) is int and report.supplementary_gids == (lease_gid,))
    lease = _current_lease(report.pid, report.start_time_ticks, lease_gid)
    held_lock = Path("/proc") / str(report.pid) / "fd" / str(report.resource_fds.lease_fd)
    _require_worker_lock(lease, report.resource_fds.lease_fd, report.worker_uid)
    nodes = []
    hints = report.resource_fds.model_dump()
    for (role, (name, _major, _minor)), field in zip(
        CUDA_DEVICE_NODE_SPECS.items(),
        ("nvidia0_fd", "nvidiactl_fd", "nvidia_uvm_fd", "nvidia_uvm_tools_fd"),
        strict=True,
    ):
        named = Path(name).lstat()
        held = Path("/proc") / str(report.pid) / "fd" / str(hints[field])
        _require(_epoch(held.stat()) == _epoch(named))
        flags = _fd_flags(_read_fdinfo(report.pid, hints[field], report.worker_uid))
        _require(bool(flags & os.O_PATH) and bool(flags & os.O_CLOEXEC))
        nodes.append(
            RootLocalCudaDeviceNode.model_validate(
                {
                    "role": role,
                    "path": name,
                    "epoch": _epoch(named),
                    "rdev_major": os.major(named.st_rdev),
                    "rdev_minor": os.minor(named.st_rdev),
                }
            )
        )
    validate_rootlocal_cuda_resource_file_metadata(tuple(nodes), lease)
    pid1_descriptor = _observe_retained_store_descriptor(lease, unit)
    _require(
        _epoch(_LOCK.lstat()) == lease.lock_epoch
        and _epoch(_LOCK.parent.lstat())[:5] == lease.parent_epoch
    )
    _require(_epoch(held_lock.stat()) == lease.lock_epoch)
    for node in nodes:
        _require(_epoch(Path(node.path).lstat()) == node.epoch)
    return CudaProbeResourceObservation(tuple(nodes), lease, pid1_descriptor)
