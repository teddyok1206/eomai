"""Synthetic and unprivileged tmpfs/proc checks, not GPU or native admission."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from eom_catalog_service.embedding_runtime_process_identity import (
    native_process_start_ticks,
    require_exclusive_flock_fdinfo,
    require_native_cuda_process_status,
)


def process_stat(pid=123, ticks=987):
    return f"{pid} (native (probe) worker) S {'0 ' * 18}{ticks} 0\n".encode()


def fdinfo(pid=123, device=None, inode=3001, flags=os.O_RDONLY | os.O_CLOEXEC):
    device = os.makedev(0, 17) if device is None else device
    return (
        f"pos:\t0\nflags:\t{flags:08o}\nmnt_id:\t21\nino:\t{inode}\n"
        f"lock:\t1: FLOCK  ADVISORY  WRITE {pid} "
        f"{os.major(device):02x}:{os.minor(device):02x}:{inode} 0 EOF\n"
    ).encode()


def cuda_status():
    return (
        b"Uid:\t1234 1234 1234 1234\nGid:\t1234 1234 1234 1234\n"
        b"Groups:\t1234 2468\nNoNewPrivs:\t1\n"
        + b"\n".join(
            name + b":\t0000000000000000"
            for name in (b"CapInh", b"CapPrm", b"CapEff", b"CapBnd", b"CapAmb")
        )
        + b"\n"
    )


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "empty",
        "oversize",
        "duplicate",
        "uid",
        "gid",
        "groups",
        "duplicate_group",
        "privilege",
        "capability",
        "bad_group",
    ),
)
def test_same_cuda_credential_rule_is_closed_and_bounded(fault):
    raw = cuda_status()
    changes = {
        "uid": (b"Uid:\t1234", b"Uid:\t1235"),
        "gid": (b"Gid:\t1234", b"Gid:\t1235"),
        "groups": (b"Groups:\t1234 2468", b"Groups:\t1234 2468 9999"),
        "duplicate_group": (b"Groups:\t1234 2468", b"Groups:\t2468 2468"),
        "bad_group": (b"Groups:\t1234 2468", b"Groups:\t1234 invalid"),
        "privilege": (b"NoNewPrivs:\t1", b"NoNewPrivs:\t0"),
        "capability": (b"CapAmb:\t0000000000000000", b"CapAmb:\t0000000000000001"),
    }
    if fault in changes:
        raw = raw.replace(*changes[fault])
    elif fault == "empty":
        raw = b""
    elif fault == "oversize":
        raw = b"x" * (128 * 1024 + 1)
    elif fault == "duplicate":
        raw += b"NoNewPrivs:\t1\n"
    if fault is None:
        require_native_cuda_process_status(raw, uid=1234, gid=1234, lease_gid=2468)
    else:
        with pytest.raises(ValueError, match="NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID"):
            require_native_cuda_process_status(raw, uid=1234, gid=1234, lease_gid=2468)


@pytest.mark.parametrize("field", ("uid", "gid", "lease_gid"))
@pytest.mark.parametrize("value", (True, 0, -1, 4294967295, "1234"))
def test_cuda_expected_ids_are_not_coerced(field, value):
    ids = dict(uid=1234, gid=1234, lease_gid=2468)
    ids[field] = value
    with pytest.raises(ValueError):
        require_native_cuda_process_status(cuda_status(), **ids)


def test_live_own_process_start_and_exact_bounded_flock_parser():
    assert native_process_start_ticks(process_stat(), 123) == 987
    pid = os.getpid()
    assert native_process_start_ticks(Path(f"/proc/{pid}/stat").read_bytes(), pid) > 0
    require_exclusive_flock_fdinfo(
        fdinfo(), pid=123, device=os.makedev(0, 17), inode=3001, descriptor_flags=os.O_CLOEXEC
    )


@pytest.mark.parametrize(
    "raw,pid",
    [
        (b"", 123),
        (b"a" * 65537, 123),
        (process_stat(), True),
        (process_stat(), 0),
        (process_stat(), 124),
        (process_stat(ticks=0), 123),
        (process_stat(ticks=2**64), 123),
        (process_stat().replace(b") S ", b") Z "), 123),
        (b"\xff", 123),
    ],
)
def test_process_parser_rejects_dead_or_wrong_identity(raw, pid):
    with pytest.raises(ValueError):
        native_process_start_ticks(raw, pid)


@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "oversize",
        "encoding",
        "no_lock",
        "duplicate",
        "shared",
        "posix",
        "ofd",
        "wrong_pid",
        "wrong_device",
        "wrong_inode",
        "wrong_flags",
        "wrong_pos",
        "bad_mount",
        "range",
        "blocked",
        "unknown_field",
    ],
)
def test_fdinfo_does_not_confuse_another_lock_or_noncanonical_frame(fault):
    raw = fdinfo()
    if fault == "empty":
        raw = b""
    elif fault == "oversize":
        raw = b" " * 16385
    elif fault == "encoding":
        raw = b"\xff"
    elif fault == "no_lock":
        raw = raw.split(b"lock:")[0]
    elif fault == "duplicate":
        raw += raw.split(b"ino:")[1].split(b"\n", 1)[1]
    elif fault == "shared":
        raw = raw.replace(b"WRITE", b"READ")
    elif fault == "posix":
        raw = raw.replace(b"FLOCK", b"POSIX")
    elif fault == "ofd":
        raw = raw.replace(b"FLOCK", b"OFDLCK")
    elif fault == "wrong_pid":
        raw = raw.replace(b"WRITE 123 ", b"WRITE 124 ")
    elif fault == "wrong_device":
        raw = raw.replace(b"00:11:", b"00:12:")
    elif fault == "wrong_inode":
        raw = raw.replace(b"3001", b"3002")
    elif fault == "wrong_flags":
        raw = fdinfo(flags=os.O_CLOEXEC | os.O_RDWR)
    elif fault == "wrong_pos":
        raw = raw.replace(b"pos:\t0", b"pos:\t1")
    elif fault == "bad_mount":
        raw = raw.replace(b"mnt_id:\t21", b"mnt_id:\t0")
    elif fault == "range":
        raw = raw.replace(b"0 EOF", b"1 EOF")
    elif fault == "blocked":
        raw = raw.replace(b"1: FLOCK", b"1: -> FLOCK")
    elif fault == "unknown_field":
        raw += b"unknown: 1\n"
    with pytest.raises(ValueError):
        require_exclusive_flock_fdinfo(
            raw, pid=123, device=os.makedev(0, 17), inode=3001, descriptor_flags=os.O_CLOEXEC
        )


def test_actual_open_description_lock_is_not_another_open_of_the_same_inode():
    if not Path("/dev/shm").is_dir():
        pytest.skip("Linux tmpfs fixture required")
    with tempfile.TemporaryDirectory(prefix="eom-fdinfo-test-", dir="/dev/shm") as folder:
        path = Path(folder) / "empty-lock"
        held = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        other = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        duplicate = -1
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            duplicate = fcntl.fcntl(held, fcntl.F_DUPFD_CLOEXEC, 3)

            def check(fd):
                value = os.fstat(fd)
                require_exclusive_flock_fdinfo(
                    Path(f"/proc/self/fdinfo/{fd}").read_bytes(),
                    pid=os.getpid(),
                    device=value.st_dev,
                    inode=value.st_ino,
                    descriptor_flags=fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_CLOEXEC,
                )

            check(held)
            check(duplicate)
            with pytest.raises(ValueError):
                check(other)
            fcntl.flock(held, fcntl.LOCK_UN)
            for fd in (held, duplicate):
                with pytest.raises(ValueError):
                    check(fd)
        finally:
            for fd in (duplicate, other, held):
                if fd >= 0:
                    os.close(fd)


def test_actual_other_process_retained_description_reports_original_flock_holder():
    """The PID1 readback relies on cross-process OFD visibility, not just same-process dup."""
    if not Path("/dev/shm").is_dir():
        pytest.skip("Linux tmpfs fixture required")
    with tempfile.TemporaryDirectory(prefix="eom-fdinfo-cross-process-", dir="/dev/shm") as folder:
        path = Path(folder) / "empty-lock"
        held = os.open(path, os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code = """
import fcntl, os, sys
from pathlib import Path
fd = int(sys.argv[1])
fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
sys.stdout.buffer.write(Path(f'/proc/{os.getpid()}/fdinfo/{fd}').read_bytes())
"""
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-c", code, str(held)],
                pass_fds=(held,),
                capture_output=True,
                check=True,
                timeout=10,
            )
            value = os.fstat(held)
            require_exclusive_flock_fdinfo(
                result.stdout,
                pid=os.getpid(),
                device=value.st_dev,
                inode=value.st_ino,
                descriptor_flags=fcntl.fcntl(held, fcntl.F_GETFL) | os.O_CLOEXEC,
            )
            assert not result.stderr
        finally:
            os.close(held)


def test_actual_retained_lock_still_reports_original_holder_after_that_process_exits():
    """A remaining description must fence cleanup even after the process that flocked exits."""
    if not Path("/dev/shm").is_dir():
        pytest.skip("Linux tmpfs fixture required")
    with tempfile.TemporaryDirectory(prefix="eom-fdinfo-exited-holder-", dir="/dev/shm") as folder:
        held = os.open(
            Path(folder) / "empty-lock", os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
        )
        try:
            code = "import fcntl,sys; fcntl.flock(int(sys.argv[1]),fcntl.LOCK_EX|fcntl.LOCK_NB)"
            child = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", code, str(held)],
                pass_fds=(held,),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0 and not stdout and not stderr
            value = os.fstat(held)
            require_exclusive_flock_fdinfo(
                Path(f"/proc/{os.getpid()}/fdinfo/{held}").read_bytes(),
                pid=child.pid,
                device=value.st_dev,
                inode=value.st_ino,
                descriptor_flags=fcntl.fcntl(held, fcntl.F_GETFL) | os.O_CLOEXEC,
            )
        finally:
            os.close(held)
