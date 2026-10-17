"""Fixed existing-only Linux tmpfs mutex, not a GPU cleanup or permission proof."""

from __future__ import annotations

import array
import fcntl
import grp
import os
import select
import signal
import socket
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

SHARED_GPU_LOCK_PATH: Final = Path("/run/eom-gpu-lease/gpu0.lock")
_GROUP_NAME: Final = "eom-gpu-lease"
_MAX_MOUNTINFO_BYTES: Final = 1024 * 1024
_NOTIFY_PATH: Final = Path("/run/systemd/notify")
_STORE_MESSAGE: Final = b"FDSTORE=1\nFDNAME=eom-gpu0-lease\nFDPOLL=0"
_BARRIER_MESSAGE: Final = b"BARRIER=1"


class SharedGpuLeaseError(RuntimeError):
    """Only fixed labels cross a caller boundary; never raw filesystem diagnostics."""

    def __init__(self, code: Literal["INVALID", "BUSY"]) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _LeasePolicy:
    path: Path
    anchor: Path
    owner_uid: int
    group_gid: int


@dataclass(frozen=True, slots=True)
class _DirectoryEpoch:
    descriptor: int
    parent_descriptor: int | None
    name: str
    identity: tuple[int, int, int, int, int]


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    # Unrelated writes in /run must not invalidate a protected ancestor's identity.
    return value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
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


def _production_policy() -> _LeasePolicy:
    try:
        group = grp.getgrnam(_GROUP_NAME)
    except (KeyError, OSError) as exc:
        raise SharedGpuLeaseError("INVALID") from exc
    if sys.platform != "linux" or group.gr_gid <= 0:
        raise SharedGpuLeaseError("INVALID")
    return _LeasePolicy(SHARED_GPU_LOCK_PATH, Path("/"), 0, group.gr_gid)


def _read_mountinfo() -> str:
    descriptor = os.open(
        "/proc/self/mountinfo", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    )
    try:
        parts: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(65536, _MAX_MOUNTINFO_BYTES + 1 - total)):
            total += len(chunk)
            if total > _MAX_MOUNTINFO_BYTES:
                raise SharedGpuLeaseError("INVALID")
            parts.append(chunk)
        return b"".join(parts).decode("utf-8")
    finally:
        os.close(descriptor)


def _require_tmpfs(descriptor: int) -> None:
    device = os.fstat(descriptor).st_dev
    expected = (os.major(device), os.minor(device))
    observed: set[str] = set()
    for line in _read_mountinfo().splitlines():
        left, separator, right = line.partition(" - ")
        fields, filesystem = left.split(), right.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            raise SharedGpuLeaseError("INVALID")
        major, colon, minor = fields[2].partition(":")
        if not colon:
            raise SharedGpuLeaseError("INVALID")
        if (int(major), int(minor)) == expected:
            observed.add(filesystem[0])
    if observed != {"tmpfs"}:
        raise SharedGpuLeaseError("INVALID")


def _verify_directories(epochs: tuple[_DirectoryEpoch, ...]) -> None:
    for epoch in epochs:
        named = os.stat(epoch.name, dir_fd=epoch.parent_descriptor, follow_symlinks=False)
        if epoch.identity != _directory_identity(os.fstat(epoch.descriptor)) or (
            epoch.identity != _directory_identity(named)
        ):
            raise SharedGpuLeaseError("INVALID")


def _verify_file(
    descriptor: int, parent_descriptor: int, policy: _LeasePolicy, identity: tuple[int, ...]
) -> None:
    value = os.fstat(descriptor)
    named = os.stat(policy.path.name, dir_fd=parent_descriptor, follow_symlinks=False)
    if identity != _file_identity(value) or identity != _file_identity(named):
        raise SharedGpuLeaseError("INVALID")
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != policy.owner_uid
        or value.st_gid != policy.group_gid
        or stat.S_IMODE(value.st_mode) != 0o640
        or value.st_nlink != 1
        or value.st_size != 0
        or value.st_dev != os.fstat(parent_descriptor).st_dev
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
        or not fcntl.fcntl(descriptor, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    ):
        raise SharedGpuLeaseError("INVALID")


def _close_descriptors(descriptors: tuple[int, ...]) -> bool:
    succeeded = True
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            succeeded = False
    return succeeded


class SharedGpuLease:
    """Own one open-file description and ancestor FDs; no cgroup/driver lifecycle claim."""

    def __init__(
        self,
        descriptor: int,
        directories: tuple[_DirectoryEpoch, ...],
        policy: _LeasePolicy,
        identity: tuple[int, ...],
    ) -> None:
        self._descriptor = descriptor
        self._directories = directories
        self._policy = policy
        self._identity = identity
        self._closed = False

    def fileno(self) -> int:
        if self._closed:
            raise SharedGpuLeaseError("INVALID")
        return self._descriptor

    def assert_valid(self) -> None:
        """Revalidate the held handle without release; no cgroup/driver ownership proof."""
        if self._closed:
            raise SharedGpuLeaseError("INVALID")
        try:
            _verify_directories(self._directories)
            _verify_file(
                self._descriptor, self._directories[-1].descriptor, self._policy, self._identity
            )
            _require_tmpfs(self._descriptor)
        except (SharedGpuLeaseError, OSError, ValueError, UnicodeError) as exc:
            raise SharedGpuLeaseError("INVALID") from exc

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.assert_valid()
        finally:
            self._closed = True
            # Do not LOCK_UN a shared fork/dup description prematurely. Last-close releases it.
            descriptors = (
                self._descriptor,
                *(item.descriptor for item in reversed(self._directories)),
            )
            if not _close_descriptors(descriptors):
                raise SharedGpuLeaseError("INVALID")


def _claim(policy: _LeasePolicy) -> SharedGpuLease:
    """Private synthetic-policy seam; production callers cannot supply identity/path authority."""
    directories: list[_DirectoryEpoch] = []
    directory_descriptors: list[int] = []
    descriptor: int | None = None
    try:
        if (
            not policy.path.is_absolute()
            or not policy.anchor.is_absolute()
            or ".." in policy.path.parts
            or ".." in policy.anchor.parts
            or not policy.path.parent.is_relative_to(policy.anchor)
        ):
            raise SharedGpuLeaseError("INVALID")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent: int | None = None
        for name in (str(policy.anchor), *policy.path.parent.relative_to(policy.anchor).parts):
            current = os.open(name, flags, dir_fd=parent)
            directory_descriptors.append(current)
            value = os.fstat(current)
            directories.append(_DirectoryEpoch(current, parent, name, _directory_identity(value)))
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != policy.owner_uid
                or stat.S_IMODE(value.st_mode) & 0o022
            ):
                raise SharedGpuLeaseError("INVALID")
            parent = current
        parent_descriptor = directories[-1].descriptor
        parent_value = os.fstat(parent_descriptor)
        if stat.S_IMODE(parent_value.st_mode) != 0o750 or parent_value.st_gid != policy.group_gid:
            raise SharedGpuLeaseError("INVALID")
        descriptor = os.open(
            policy.path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent_descriptor,
        )
        identity = _file_identity(os.fstat(descriptor))
        epochs = tuple(directories)
        _verify_directories(epochs)
        _verify_file(descriptor, parent_descriptor, policy, identity)
        _require_tmpfs(descriptor)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            # Contention is BUSY only while the same validated inode still owns the name.
            _verify_directories(epochs)
            _verify_file(descriptor, parent_descriptor, policy, identity)
            _require_tmpfs(descriptor)
            raise SharedGpuLeaseError("BUSY") from exc
        _verify_directories(epochs)
        _verify_file(descriptor, parent_descriptor, policy, identity)
        _require_tmpfs(descriptor)
        return SharedGpuLease(descriptor, epochs, policy, identity)
    except BaseException as exc:
        descriptors = (() if descriptor is None else (descriptor,)) + tuple(
            reversed(directory_descriptors)
        )
        if not _close_descriptors(descriptors):
            raise SharedGpuLeaseError("INVALID") from exc
        if isinstance(exc, SharedGpuLeaseError):
            raise
        if isinstance(exc, (OSError, ValueError, UnicodeError)):
            raise SharedGpuLeaseError("INVALID") from exc
        raise


def acquire_shared_gpu_lease() -> SharedGpuLease:
    """Claim only the fixed root-provisioned lock, with no caller-supplied policy."""
    return _claim(_production_policy())


def _notification_epochs() -> tuple[tuple[int, ...], ...]:
    epochs: list[tuple[int, ...]] = []
    for path in (Path("/"), Path("/run"), _NOTIFY_PATH.parent):
        value = path.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise SharedGpuLeaseError("INVALID")
        epochs.append(_directory_identity(value))
    value = _NOTIFY_PATH.lstat()
    if not stat.S_ISSOCK(value.st_mode) or value.st_uid != 0 or value.st_nlink != 1:
        raise SharedGpuLeaseError("INVALID")
    epochs.append(_file_identity(value))
    return tuple(epochs)


def _send_descriptor(channel: socket.socket, message: bytes, descriptor: int) -> None:
    rights = array.array("i", [descriptor])
    sent = channel.sendmsg([message], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)])
    if sent != len(message):
        raise SharedGpuLeaseError("INVALID")


def _notification_barrier(channel: socket.socket) -> None:
    reader, writer = os.pipe2(os.O_CLOEXEC)
    try:
        _send_descriptor(channel, _BARRIER_MESSAGE, writer)
        selected, writer = writer, -1
        os.close(selected)
        poller = select.poll()
        poller.register(reader, select.POLLHUP)
        events = poller.poll(10000)
        if events != [(reader, select.POLLHUP)] or os.read(reader, 1) != b"":
            raise SharedGpuLeaseError("INVALID")
    finally:
        owned = (reader,) if writer < 0 else (reader, writer)
        if not _close_descriptors(owned):
            raise SharedGpuLeaseError("INVALID")


def request_unit_gpu_lease_retention(lease: SharedGpuLease) -> None:
    """Request fixed PID1 retention only; processing is NOT store acceptance or CUDA admission.

    The root owner must observe this unit's exact stored descriptor and ACK before
    CUDA initialization. It alone releases the store after unit/GPU cleanup. Even
    on failure this function neither closes/unlocks the borrowed lease nor sends
    FDSTOREREMOVE: a successfully queued store may already be retaining ownership.
    """
    try:
        if (
            type(lease) is not SharedGpuLease
            or os.environ.get("NOTIFY_SOCKET") != str(_NOTIFY_PATH)
            or os.environ.get("FDSTORE") != "1"
        ):
            raise SharedGpuLeaseError("INVALID")
        lease.assert_valid()
        descriptor = lease.fileno()
        before = _notification_epochs()
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as channel:
            channel.settimeout(2.0)
            channel.connect(str(_NOTIFY_PATH))
            if _notification_epochs() != before:
                raise SharedGpuLeaseError("INVALID")
            _send_descriptor(channel, _STORE_MESSAGE, descriptor)
            _notification_barrier(channel)
        lease.assert_valid()
        if lease.fileno() != descriptor or _notification_epochs() != before:
            raise SharedGpuLeaseError("INVALID")
    except (OSError, ValueError, TypeError, OverflowError, SharedGpuLeaseError) as error:
        raise SharedGpuLeaseError("INVALID") from error


def acquire_retained_unit_gpu_lease() -> SharedGpuLease:
    """Wait for real root store observation before the caller may start image work.

    The fixed unit bootstrap reserves SIGUSR1 before importing model-adjacent code;
    this function neither changes handlers/masks nor grants unit/runtime authority.
    Root must validate the actual unit, PID/start ticks, thread frame, retained
    physical inode and policy before sending one ACK. Its separate terminal owner
    retains/cleans the PID1 copy, including when this call times out or is cancelled.
    """
    try:
        if (
            signal.SIGUSR1 not in signal.pthread_sigmask(signal.SIG_BLOCK, set())
            or signal.SIGUSR1 in signal.sigpending()
        ):
            raise SharedGpuLeaseError("INVALID")
    except (OSError, ValueError, TypeError) as error:
        raise SharedGpuLeaseError("INVALID") from error
    lease = acquire_shared_gpu_lease()
    try:
        request_unit_gpu_lease_retention(lease)
        # A blocking rt_sigtimedwait temporarily removes the awaited bit from
        # /proc's effective SigBlk while sleeping. Keep the reservation observable
        # before root ACK: zero-time consumption never enters that kernel wait.
        deadline = time.monotonic() + 30
        received = None
        while time.monotonic() < deadline:
            received = signal.sigtimedwait({signal.SIGUSR1}, 0)
            if received is not None:
                break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if (
            received is None
            or received.si_signo != signal.SIGUSR1
            or received.si_uid != 0
            or received.si_pid <= 0
        ):
            raise SharedGpuLeaseError("INVALID")
        lease.assert_valid()
        return lease
    except BaseException as error:
        # Never LOCK_UN, remove a store, or release PID1's possibly accepted copy.
        lease.close()
        if isinstance(error, (OSError, ValueError, TypeError)):
            raise SharedGpuLeaseError("INVALID") from error
        raise


@contextmanager
def retained_unit_gpu_lease() -> Iterator[SharedGpuLease]:
    """Explicit one-shot unit scope; worker close cannot retire PID1 ownership."""
    lease = acquire_retained_unit_gpu_lease()
    try:
        yield lease
    finally:
        lease.close()


@contextmanager
def shared_gpu_lease() -> Iterator[SharedGpuLease]:
    lease = acquire_shared_gpu_lease()
    try:
        yield lease
    finally:
        lease.close()
