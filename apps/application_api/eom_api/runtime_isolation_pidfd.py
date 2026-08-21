"""Race-resistant pidfd acquisition for the runtime-isolation verifier."""

from __future__ import annotations

import ctypes
import errno
import os
import select
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, cast

_LIBC_PIDFD_SYMBOL: Final = "pidfd_open"
_PIDFD_FLAGS: Final = 0


class PidfdBackend(StrEnum):
    PYTHON_OS_PIDFD = "PYTHON_OS_PIDFD"
    LIBC_PIDFD = "LIBC_PIDFD"
    NONE = "NONE"


class PidfdFailure(StrEnum):
    BACKEND_UNAVAILABLE = "PIDFD_BACKEND_UNAVAILABLE"
    PROCESS_EXITED = "PIDFD_PROCESS_EXITED"
    PERMISSION_DENIED = "PIDFD_PERMISSION_DENIED"
    KERNEL_UNSUPPORTED = "PIDFD_KERNEL_UNSUPPORTED"
    INVALID_DESCRIPTOR = "PIDFD_INVALID_DESCRIPTOR"
    OPEN_FAILED = "PIDFD_OPEN_FAILED"


class PidfdAcquisitionError(RuntimeError):
    """Sanitized acquisition failure; errno is retained for tests and diagnosis only."""

    def __init__(self, failure: PidfdFailure, error_number: int | None = None) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.error_number = error_number


class _LibcPidfdFunction(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, pid: int, flags: int) -> int: ...


class LibcPidfdOpen:
    """Narrow wrapper around the one fixed libc symbol and flags value."""

    def __init__(self, library: object | None = None) -> None:
        libc = library if library is not None else ctypes.CDLL(None, use_errno=True)
        function = cast(_LibcPidfdFunction, getattr(libc, _LIBC_PIDFD_SYMBOL))
        function.argtypes = [ctypes.c_int, ctypes.c_uint]
        function.restype = ctypes.c_int
        self._function = function

    @classmethod
    def detect(cls) -> LibcPidfdOpen | None:
        try:
            return cls()
        except (AttributeError, OSError):
            return None

    def __call__(self, pid: int, flags: int) -> int:
        if flags != _PIDFD_FLAGS:
            raise ValueError("pidfd flags must use the fixed safe value")
        ctypes.set_errno(0)
        descriptor = self._function(pid, _PIDFD_FLAGS)
        if descriptor < 0:
            error_number = ctypes.get_errno() or errno.EIO
            raise OSError(error_number, os.strerror(error_number))
        return descriptor


@dataclass(frozen=True)
class AcquiredPidfd:
    descriptor: int
    backend: PidfdBackend


@dataclass(frozen=True)
class PidfdCapabilityReport:
    ready: bool
    selected_backend: PidfdBackend
    python_binding_available: bool
    libc_backend_available: bool
    fail_closed: bool
    detail_code: str


class PidfdProvider:
    """Select one safe pidfd backend and never degrade to an ordinary PID."""

    def __init__(
        self,
        python_opener: Callable[[int, int], int] | None,
        libc_opener: Callable[[int, int], int] | None,
    ) -> None:
        self._python_opener = python_opener
        self._libc_opener = libc_opener

    @classmethod
    def from_system(cls) -> PidfdProvider:
        candidate = getattr(os, "pidfd_open", None)
        python_opener = cast(Callable[[int, int], int], candidate) if callable(candidate) else None
        return cls(python_opener, LibcPidfdOpen.detect())

    @property
    def python_binding_available(self) -> bool:
        return self._python_opener is not None

    @property
    def libc_backend_available(self) -> bool:
        return self._libc_opener is not None

    @property
    def selected_backend(self) -> PidfdBackend:
        if self._python_opener is not None:
            return PidfdBackend.PYTHON_OS_PIDFD
        if self._libc_opener is not None:
            return PidfdBackend.LIBC_PIDFD
        return PidfdBackend.NONE

    def open(self, pid: int) -> AcquiredPidfd:
        if pid <= 1:
            raise PidfdAcquisitionError(PidfdFailure.PROCESS_EXITED, errno.ESRCH)
        backend = self.selected_backend
        if backend is PidfdBackend.PYTHON_OS_PIDFD:
            opener = self._python_opener
        elif backend is PidfdBackend.LIBC_PIDFD:
            opener = self._libc_opener
        else:
            raise PidfdAcquisitionError(PidfdFailure.BACKEND_UNAVAILABLE)
        assert opener is not None
        try:
            descriptor = opener(pid, _PIDFD_FLAGS)
        except OSError as error:
            raise PidfdAcquisitionError(_classify_errno(error.errno), error.errno) from None
        if type(descriptor) is not int or descriptor < 0:
            raise PidfdAcquisitionError(PidfdFailure.INVALID_DESCRIPTOR)
        try:
            os.set_inheritable(descriptor, False)
        except OSError as error:
            os.close(descriptor)
            raise PidfdAcquisitionError(PidfdFailure.OPEN_FAILED, error.errno) from None
        return AcquiredPidfd(descriptor, backend)


def inspect_pidfd_capability(provider: PidfdProvider | None = None) -> PidfdCapabilityReport:
    """Prove that the selected backend can safely reference this process without service access."""

    selected = provider or PidfdProvider.from_system()
    backend = selected.selected_backend
    try:
        acquired = selected.open(os.getpid())
    except PidfdAcquisitionError as error:
        return PidfdCapabilityReport(
            ready=False,
            selected_backend=backend,
            python_binding_available=selected.python_binding_available,
            libc_backend_available=selected.libc_backend_available,
            fail_closed=True,
            detail_code=error.failure.value,
        )
    try:
        alive = pidfd_is_alive(acquired.descriptor)
    finally:
        os.close(acquired.descriptor)
    return PidfdCapabilityReport(
        ready=alive,
        selected_backend=acquired.backend,
        python_binding_available=selected.python_binding_available,
        libc_backend_available=selected.libc_backend_available,
        fail_closed=True,
        detail_code="PIDFD_READY" if alive else PidfdFailure.PROCESS_EXITED.value,
    )


def pidfd_is_alive(descriptor: int) -> bool:
    poller = select.poll()
    poller.register(descriptor, select.POLLIN)
    return not poller.poll(0)


def pidfd_referenced_pid(descriptor: int) -> int:
    """Read the kernel-owned pidfd identity; -1 means the referenced process exited."""

    fdinfo = os.open(f"/proc/self/fdinfo/{descriptor}", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        content = os.read(fdinfo, 4097)
    finally:
        os.close(fdinfo)
    if len(content) > 4096:
        raise OSError(errno.EFBIG, "pidfd metadata exceeds fixed limit")
    for line in content.decode("ascii", "strict").splitlines():
        key, separator, value = line.partition(":")
        if separator and key == "Pid":
            return int(value.strip())
    raise OSError(errno.EINVAL, "pidfd identity is unavailable")


def _classify_errno(error_number: int | None) -> PidfdFailure:
    if error_number == errno.ESRCH:
        return PidfdFailure.PROCESS_EXITED
    if error_number in {errno.EPERM, errno.EACCES}:
        return PidfdFailure.PERMISSION_DENIED
    if error_number in {errno.ENOSYS, errno.EINVAL}:
        return PidfdFailure.KERNEL_UNSUPPORTED
    return PidfdFailure.OPEN_FAILED
