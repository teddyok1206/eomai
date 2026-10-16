"""Independent root readback of fixed CUDA probe FDs and PID1 retention; no release or launch."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

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

from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_process_identity import require_exclusive_flock_fdinfo

_LOCK = Path("/run/eom-gpu-lease/gpu0.lock")
_PID1_FDS = Path("/proc/1/fd")
_MAX_PID1_FDS = 4096
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
    return observed


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
    _require(type(lease_gid) is int and report.supplementary_gids == (lease_gid,))
    parent = _LOCK.parent.lstat()
    lock = _LOCK.lstat()
    lease = RootLocalCudaSharedGpuLease.model_validate(
        {
            "source": "ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0",
            "resource_id": "GPU0",
            "lock_path": str(_LOCK),
            "filesystem": "tmpfs",
            "lease_gid": lease_gid,
            "parent_epoch": _epoch(parent)[:5],
            "lock_epoch": _epoch(lock),
            "holder_pid": report.pid,
            "holder_start_time_ticks": report.start_time_ticks,
        }
    )
    _require_tmpfs_device(lock.st_dev)
    held_lock = Path("/proc") / str(report.pid) / "fd" / str(report.resource_fds.lease_fd)
    _require(_epoch(held_lock.stat()) == lease.lock_epoch)
    raw = _read_fdinfo(report.pid, report.resource_fds.lease_fd, report.worker_uid)
    flags = _fd_flags(raw)
    _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
    _require(bool(flags & os.O_CLOEXEC))
    require_exclusive_flock_fdinfo(
        raw, pid=report.pid, device=lock.st_dev, inode=lock.st_ino, descriptor_flags=flags
    )
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
