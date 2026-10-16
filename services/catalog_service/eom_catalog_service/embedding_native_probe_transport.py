"""Fixed root-staged probe files and root-only signal handshakes; no launch or authority."""

from __future__ import annotations

import errno
import fcntl
import os
import signal
import stat
from pathlib import Path
from typing import Literal

type ProbeProfile = Literal["CPU_INDEX_FP32", "CUDA_INDEX_FP32"]
MAX_NATIVE_PROBE_BYTES = 64 * 1024


def _fail(profile: ProbeProfile, suffix: str) -> ValueError:
    if profile not in ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"):
        return ValueError("NATIVE_PROBE_PROFILE_INVALID")
    name = "CPU" if profile == "CPU_INDEX_FP32" else "CUDA"
    return ValueError(f"NATIVE_{name}_PROBE_{suffix}")


def native_probe_file_epoch(value: os.stat_result) -> tuple[int, ...]:
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


def capture_native_probe_descriptors(
    profile: ProbeProfile, input_fd: int, output_fds: tuple[int, ...]
) -> tuple[os.stat_result, tuple[os.stat_result, ...]]:
    if profile not in ("CPU_INDEX_FP32", "CUDA_INDEX_FP32") or not 1 <= len(output_fds) <= 2:
        raise _fail(profile, "DESCRIPTORS_INVALID")
    descriptors = (input_fd, *output_fds)
    if any(type(fd) is not int or fd < 0 for fd in descriptors):
        raise _fail(profile, "DESCRIPTORS_INVALID")
    values = tuple(os.fstat(fd) for fd in descriptors)
    if (
        any(
            not stat.S_ISREG(v.st_mode)
            or v.st_uid != 0
            or v.st_nlink != 1
            or stat.S_IMODE(v.st_mode) != 0o600
            for v in values
        )
        or len({(v.st_dev, v.st_ino) for v in values}) != len(values)
        or not 0 < values[0].st_size <= MAX_NATIVE_PROBE_BYTES
        or any(v.st_size != 0 for v in values[1:])
    ):
        raise _fail(profile, "DESCRIPTORS_INVALID")
    for index, descriptor in enumerate(descriptors):
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        expected = os.O_RDONLY if index == 0 else os.O_WRONLY
        if (
            flags & os.O_ACCMODE != expected
            or flags & (os.O_APPEND | os.O_NONBLOCK)
            or os.lseek(descriptor, 0, os.SEEK_CUR) != 0
        ):
            raise _fail(profile, "DESCRIPTORS_INVALID")
    return values[0], values[1:]


def read_native_probe_input(
    profile: ProbeProfile, descriptor: int, initial: os.stat_result
) -> bytes:
    raw = os.read(descriptor, initial.st_size + 1)
    if len(raw) != initial.st_size or native_probe_file_epoch(
        os.fstat(descriptor)
    ) != native_probe_file_epoch(initial):
        raise _fail(profile, "INPUT_CHANGED")
    return raw


def write_native_probe_report(
    profile: ProbeProfile, descriptor: int, raw: bytes, initial: os.stat_result
) -> None:
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= MAX_NATIVE_PROBE_BYTES
        or native_probe_file_epoch(os.fstat(descriptor)) != native_probe_file_epoch(initial)
    ):
        raise _fail(profile, "OUTPUT_CHANGED")
    remaining = memoryview(raw)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise _fail(profile, "OUTPUT_FAILED")
        remaining = remaining[written:]
    os.fsync(descriptor)
    final = os.fstat(descriptor)
    if (
        native_probe_file_epoch(final)[:6] != native_probe_file_epoch(initial)[:6]
        or final.st_size != len(raw)
        or os.lseek(descriptor, 0, os.SEEK_CUR) != len(raw)
    ):
        raise _fail(profile, "OUTPUT_CHANGED")


def require_native_probe_write_denied(profile: ProbeProfile, path: Path) -> None:
    """Try opening only; never create, truncate or write an unexpectedly writable target."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            return
        raise _fail(profile, "WRITE_CHECK_INVALID") from None
    os.close(descriptor)
    raise _fail(profile, "WRITE_ALLOWED")


def wait_native_probe_owner_ack(profile: ProbeProfile, signal_number: int) -> None:
    if signal_number not in (signal.SIGUSR1, signal.SIGUSR2):
        raise _fail(profile, "OWNER_SIGNAL_INVALID")
    received = signal.sigtimedwait({signal_number}, 30)
    if received is None or received.si_signo != signal_number or received.si_uid != 0:
        raise _fail(profile, "OWNER_OBSERVATION_MISSING")
