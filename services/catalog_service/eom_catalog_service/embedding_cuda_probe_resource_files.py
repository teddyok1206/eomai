"""Distinct PATH observations and post-ACK probe R/W access; no installation or model grant."""

from __future__ import annotations

import fcntl
import grp
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from eom_catalog_contracts.embedding_cuda_installation_evidence import (
    CUDA_DEVICE_NODE_SPECS,
    RootLocalCudaDeviceNode,
    RootLocalCudaSharedGpuLease,
    validate_rootlocal_cuda_resource_file_metadata,
)
from eom_catalog_contracts.embedding_installed_runtime_proof import CudaRuntimeDeviceCapture
from eom_catalog_contracts.embedding_native_cuda_probe import NativeCudaProbeResourceDescriptors

from eom_catalog_service.embedding_native_entrypoint import require_native_embedding_identity
from eom_catalog_service.embedding_runtime_files import read_live_runtime_os_file
from eom_catalog_service.embedding_runtime_os_identity import observe_runtime_device
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_exclusive_flock_fdinfo,
)

if TYPE_CHECKING:
    from eom_gpu_lease import SharedGpuLease

_DEVICE_PARENT = Path("/dev")
_LEASE_PARENT = Path("/run/eom-gpu-lease")
_GROUP = "eom-gpu-lease"


class CudaProbeResourceFilesError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool) -> None:
    if not condition:
        raise CudaProbeResourceFilesError("NATIVE_CUDA_RESOURCE_FILES_CHANGED")


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


def _start(pid: int) -> int:
    return native_process_start_ticks(
        read_live_runtime_os_file(
            Path("/proc") / str(pid) / "stat", maximum=65536, owner_uid=os.geteuid()
        ),
        pid,
    )


@dataclass(frozen=True, slots=True)
class _Directory:
    path: Path
    descriptor: int
    identity: tuple[int, ...]

    def assert_current(self) -> None:
        value = os.fstat(self.descriptor)
        _require(
            _epoch(value)[:5]
            == self.identity
            == _epoch(os.stat(self.path, follow_symlinks=False))[:5]
        )
        _require(stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022)
        flags = fcntl.fcntl(self.descriptor, fcntl.F_GETFL)
        _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
        _require(bool(fcntl.fcntl(self.descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC))


@dataclass(frozen=True, slots=True)
class _Device:
    metadata: RootLocalCudaDeviceNode
    descriptor: int

    def assert_current(self, parent: _Directory) -> None:
        value = os.fstat(self.descriptor)
        named = os.stat(
            Path(self.metadata.path).name, dir_fd=parent.descriptor, follow_symlinks=False
        )
        _require(_epoch(value) == self.metadata.epoch == _epoch(named))
        _require(
            (os.major(value.st_rdev), os.minor(value.st_rdev))
            == (self.metadata.rdev_major, self.metadata.rdev_minor)
        )
        _require(fcntl.fcntl(self.descriptor, fcntl.F_GETFL) & os.O_PATH == os.O_PATH)
        _require(bool(fcntl.fcntl(self.descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC))


def _lease_metadata(
    lease: SharedGpuLease, parent: _Directory, pid: int, ticks: int
) -> RootLocalCudaSharedGpuLease:
    lease.assert_valid()
    parent.assert_current()
    descriptor = lease.fileno()
    value = os.fstat(descriptor)
    named = os.stat("gpu0.lock", dir_fd=parent.descriptor, follow_symlinks=False)
    _require(_epoch(value) == _epoch(named))
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
    _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
    _require(bool(fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC))
    raw = read_live_runtime_os_file(
        Path("/proc") / str(pid) / "fdinfo" / str(descriptor), maximum=16384, owner_uid=os.geteuid()
    )
    require_exclusive_flock_fdinfo(
        raw, pid=pid, device=value.st_dev, inode=value.st_ino, descriptor_flags=flags | os.O_CLOEXEC
    )
    group = grp.getgrnam(_GROUP).gr_gid
    result = RootLocalCudaSharedGpuLease.model_validate(
        {
            "source": "ROOT_PROVISIONED_TMPFS_READONLY_EXCLUSIVE_FLOCK/1.0",
            "resource_id": "GPU0",
            "lock_path": str(_LEASE_PARENT / "gpu0.lock"),
            "filesystem": "tmpfs",
            "lease_gid": group,
            "parent_epoch": parent.identity,
            "lock_epoch": _epoch(value),
            "holder_pid": pid,
            "holder_start_time_ticks": ticks,
        }
    )
    # The borrowed package independently verifies the real protected tmpfs/root policy.
    lease.assert_valid()
    return result


class CapturedCudaProbeResourceFiles:
    """Held PATH-only files plus a borrowed guarded FD; deliberately no assert_owned method."""

    def __init__(
        self,
        *,
        expected_device: CudaRuntimeDeviceCapture,
        lease: SharedGpuLease,
        directories: tuple[_Directory, _Directory],
        devices: tuple[_Device, ...],
        lease_metadata: RootLocalCudaSharedGpuLease,
        lease_fd: int,
        pid: int,
        ticks: int,
    ) -> None:
        self._expected, self._lease = expected_device, lease
        self._directories, self._devices = directories, devices
        self._lease_metadata, self._lease_fd = lease_metadata, lease_fd
        self._lease_flags = (
            fcntl.fcntl(lease_fd, fcntl.F_GETFL),
            fcntl.fcntl(lease_fd, fcntl.F_GETFD),
        )
        self._pid, self._ticks, self._closed = pid, ticks, False

    def assert_current(self) -> None:
        try:
            _require(not self._closed)
            require_native_embedding_identity("CUDA_INDEX_FP32")
            _require(os.getpid() == self._pid and _start(self._pid) == self._ticks)
            observe_runtime_device(self._expected)
            for parent in self._directories:
                parent.assert_current()
            for device in self._devices:
                device.assert_current(self._directories[0])
            _require(self._lease.fileno() == self._lease_fd)
            _require(
                self._lease_flags
                == (
                    fcntl.fcntl(self._lease_fd, fcntl.F_GETFL),
                    fcntl.fcntl(self._lease_fd, fcntl.F_GETFD),
                )
            )
            _require(
                _lease_metadata(self._lease, self._directories[1], self._pid, self._ticks)
                == self._lease_metadata
            )
            _require(_start(self._pid) == self._ticks)
        except Exception:
            raise CudaProbeResourceFilesError("NATIVE_CUDA_RESOURCE_FILES_CHANGED") from None

    @property
    def device_nodes(self) -> tuple[RootLocalCudaDeviceNode, ...]:
        self.assert_current()
        return tuple(device.metadata for device in self._devices)

    @property
    def shared_gpu_lease(self) -> RootLocalCudaSharedGpuLease:
        self.assert_current()
        return self._lease_metadata

    @property
    def resource_descriptors(self) -> NativeCudaProbeResourceDescriptors:
        """Typed hints only; the root observer must inspect these actual open descriptions."""
        self.assert_current()
        return NativeCudaProbeResourceDescriptors(
            nvidia0_fd=self._devices[0].descriptor,
            nvidiactl_fd=self._devices[1].descriptor,
            nvidia_uvm_fd=self._devices[2].descriptor,
            nvidia_uvm_tools_fd=self._devices[3].descriptor,
            lease_fd=self._lease_fd,
        )

    def __enter__(self) -> CapturedCudaProbeResourceFiles:
        try:
            self.assert_current()
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.assert_current()
        finally:
            self._closed = True
            _close(
                tuple(d.descriptor for d in self._directories)
                + tuple(d.descriptor for d in self._devices)
            )


def _close(descriptors: tuple[int, ...]) -> None:
    failed = False
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        raise CudaProbeResourceFilesError("NATIVE_CUDA_RESOURCE_FILES_CLEANUP_UNCERTAIN")


class CapturedCudaInstallationResourceFiles:
    """Readonly installation identity only; no physical flock or numerical ownership interface."""

    def __init__(
        self,
        directories: tuple[_Directory, _Directory],
        devices: tuple[_Device, ...],
        lease: RootLocalCudaSharedGpuLease,
        lease_descriptor: int,
    ) -> None:
        self._directories, self._devices = directories, devices
        self._lease, self._lease_descriptor, self._closed = lease, lease_descriptor, False

    def assert_current(self) -> None:
        _require(not self._closed)
        for parent in self._directories:
            parent.assert_current()
        _require(self._directories[1].identity == self._lease.parent_epoch)
        for device in self._devices:
            device.assert_current(self._directories[0])
        value = os.fstat(self._lease_descriptor)
        named = os.stat("gpu0.lock", dir_fd=self._directories[1].descriptor, follow_symlinks=False)
        _require(_epoch(value) == self._lease.lock_epoch == _epoch(named))
        flags = fcntl.fcntl(self._lease_descriptor, fcntl.F_GETFL)
        _require(flags & os.O_ACCMODE == os.O_RDONLY and not flags & os.O_PATH)
        _require(bool(fcntl.fcntl(self._lease_descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC))

    def close(self) -> None:
        if not self._closed:
            try:
                self.assert_current()
            finally:
                self._closed = True
                _close(
                    tuple(d.descriptor for d in self._directories)
                    + tuple(d.descriptor for d in self._devices)
                    + (self._lease_descriptor,)
                )


def capture_cuda_installation_resource_files(
    nodes: tuple[RootLocalCudaDeviceNode, ...],
    lease: RootLocalCudaSharedGpuLease,
) -> CapturedCudaInstallationResourceFiles:
    """Hold the accepted installation's exact nodes/inode without acquiring any GPU lock."""
    opened: list[int] = []
    try:
        nodes = tuple(RootLocalCudaDeviceNode.model_validate(node) for node in nodes)
        lease = RootLocalCudaSharedGpuLease.model_validate(lease)
        validate_rootlocal_cuda_resource_file_metadata(nodes, lease)
        directories = []
        for path in (_DEVICE_PARENT, _LEASE_PARENT):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            opened.append(descriptor)
            parent = _Directory(path, descriptor, _epoch(os.fstat(descriptor))[:5])
            parent.assert_current()
            directories.append(parent)
        devices = []
        for metadata in nodes:
            descriptor = os.open(
                Path(metadata.path).name,
                os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directories[0].descriptor,
            )
            opened.append(descriptor)
            device = _Device(metadata, descriptor)
            device.assert_current(directories[0])
            devices.append(device)
        descriptor = os.open(
            "gpu0.lock",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=directories[1].descriptor,
        )
        opened.append(descriptor)
        captured = CapturedCudaInstallationResourceFiles(
            (directories[0], directories[1]), tuple(devices), lease, descriptor
        )
        captured.assert_current()
        return captured
    except BaseException as error:
        _close(tuple(opened))
        if isinstance(error, Exception):
            raise CudaProbeResourceFilesError(
                "NATIVE_CUDA_INSTALLATION_RESOURCE_CAPTURE_INVALID"
            ) from None
        raise


class OpenedCudaProbeDeviceAccess:
    """Probe-only R/W descriptor and physical lease checks; never installation admission.

    Unlike PATH-only capture this actually opens the four permitted devices R/W.
    The caller must already have received root's independent pre-init ACK; this
    object does not issue that ACK, release the store or authorize model use.
    """

    def __init__(self, files: CapturedCudaProbeResourceFiles, descriptors: tuple[int, ...]) -> None:
        self._files, self._descriptors, self._closed = files, descriptors, False

    def assert_owned(self) -> None:
        _require(not self._closed)
        _require(type(self._files) is CapturedCudaProbeResourceFiles)
        _require(type(self._descriptors) is tuple and len(self._descriptors) == 4)
        _require(all(type(fd) is int and fd >= 3 for fd in self._descriptors))
        _require(len(set(self._descriptors)) == 4)
        self._files.assert_current()
        for device, descriptor in zip(self._files._devices, self._descriptors, strict=True):
            value = os.fstat(descriptor)
            named = os.stat(
                Path(device.metadata.path).name,
                dir_fd=self._files._directories[0].descriptor,
                follow_symlinks=False,
            )
            _require(_epoch(value) == device.metadata.epoch == _epoch(named))
            _require(
                (os.major(value.st_rdev), os.minor(value.st_rdev))
                == (device.metadata.rdev_major, device.metadata.rdev_minor)
            )
            flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
            _require(flags & os.O_ACCMODE == os.O_RDWR and not flags & os.O_PATH)
            _require(bool(fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC))
        self._files.assert_current()

    def close(self) -> None:
        if not self._closed:
            try:
                self.assert_owned()
            finally:
                self._closed = True
                _close(self._descriptors)

    def __enter__(self) -> OpenedCudaProbeDeviceAccess:
        try:
            self.assert_owned()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_args: object) -> None:
        self.close()


def open_cuda_probe_device_access(
    files: CapturedCudaProbeResourceFiles,
) -> OpenedCudaProbeDeviceAccess:
    """After root ACK only: prove actual device DAC/cgroup R/W access, with no CUDA import."""
    descriptors: list[int] = []
    try:
        _require(type(files) is CapturedCudaProbeResourceFiles)
        files.assert_current()
        for device in files._devices:
            descriptor = os.open(
                Path(device.metadata.path).name,
                os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=files._directories[0].descriptor,
            )
            descriptors.append(descriptor)
        value = OpenedCudaProbeDeviceAccess(files, tuple(descriptors))
        value.assert_owned()
        return value
    except BaseException as error:
        _close(tuple(descriptors))
        if isinstance(error, Exception):
            raise CudaProbeResourceFilesError("NATIVE_CUDA_PROBE_DEVICE_ACCESS_INVALID") from None
        raise


def capture_cuda_probe_resource_files(
    expected_device: CudaRuntimeDeviceCapture, lease: SharedGpuLease
) -> CapturedCudaProbeResourceFiles:
    """Observe fixed files only. Caller retains/acquires/releases its actual lease separately."""
    opened: list[int] = []
    try:
        require_native_embedding_identity("CUDA_INDEX_FP32")
        # Optional adapter is imported only inside the CUDA-specific, identity-checked path.
        from eom_gpu_lease import SharedGpuLease

        _require(type(lease) is SharedGpuLease)
        expected = CudaRuntimeDeviceCapture.model_validate(expected_device)
        observe_runtime_device(expected)
        pid = os.getpid()
        ticks = _start(pid)
        directories = []
        for path in (_DEVICE_PARENT, _LEASE_PARENT):
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            opened.append(descriptor)
            parent = _Directory(path, descriptor, _epoch(os.fstat(descriptor))[:5])
            parent.assert_current()
            directories.append(parent)
        selected_lease = _lease_metadata(lease, directories[1], pid, ticks)
        devices = []
        for role, (name, _major, _minor) in CUDA_DEVICE_NODE_SPECS.items():
            descriptor = os.open(
                Path(name).name,
                os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directories[0].descriptor,
            )
            opened.append(descriptor)
            value = os.fstat(descriptor)
            metadata = RootLocalCudaDeviceNode.model_validate(
                {
                    "role": role,
                    "path": name,
                    "epoch": _epoch(value),
                    "rdev_major": os.major(value.st_rdev),
                    "rdev_minor": os.minor(value.st_rdev),
                }
            )
            device = _Device(metadata, descriptor)
            device.assert_current(directories[0])
            devices.append(device)
        validate_rootlocal_cuda_resource_file_metadata(
            tuple(d.metadata for d in devices), selected_lease
        )
        result = CapturedCudaProbeResourceFiles(
            expected_device=expected,
            lease=lease,
            directories=(directories[0], directories[1]),
            devices=tuple(devices),
            lease_metadata=selected_lease,
            lease_fd=lease.fileno(),
            pid=pid,
            ticks=ticks,
        )
        result.assert_current()
        return result
    except BaseException as error:
        _close(tuple(opened))
        if isinstance(error, Exception):
            raise CudaProbeResourceFilesError(
                "NATIVE_CUDA_RESOURCE_FILES_CAPTURE_INVALID"
            ) from None
        raise
