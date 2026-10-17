"""Bounded Linux process/open-description identity parsing, no process control or authority."""

from __future__ import annotations

import os
import re


def require_native_cuda_process_status(raw: bytes, *, uid: int, gid: int, lease_gid: int) -> None:
    """Same native probe/benchmark credential rule; not unit, signal or GPU authority."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 128 * 1024
        or any(
            type(value) is not int or not 0 < value <= 4294967294 for value in (uid, gid, lease_gid)
        )
        or gid == lease_gid
    ):
        raise ValueError("NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID")
    fields: dict[str, str] = {}
    for line in raw.decode("ascii").splitlines():
        key, separator, value = line.partition(":")
        if not separator or key in fields:
            raise ValueError("NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID")
        fields[key] = value.strip()
    if (
        fields.get("Uid", "").split() != [str(uid)] * 4
        or fields.get("Gid", "").split() != [str(gid)] * 4
        or fields.get("NoNewPrivs") != "1"
        or any(
            fields.get(key) != "0000000000000000"
            for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        )
    ):
        raise ValueError("NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID")
    groups = fields.get("Groups", "").split()
    if not all(re.fullmatch(r"[0-9]{1,10}", value) is not None for value in groups):
        raise ValueError("NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID")
    values = {int(value) for value in groups}
    if len(values) != len(groups) or values - {gid} != {lease_gid}:
        raise ValueError("NATIVE_CUDA_PROBE_PROCESS_IDENTITY_INVALID")


def native_process_start_ticks(raw: bytes, pid: int) -> int:
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 64 * 1024
        or type(pid) is not int
        or not 0 < pid <= 2147483647
    ):
        raise ValueError("NATIVE_PROCESS_STAT_INVALID")
    text = raw.decode("ascii", errors="strict")
    _comm, separator, tail = text.rpartition(") ")
    fields = tail.split()
    if (
        not text.startswith(f"{pid} (")
        or not separator
        or len(fields) < 20
        or fields[0] not in {"R", "S", "D", "I"}
        or re.fullmatch(r"[0-9]{1,20}", fields[19]) is None
        or not 0 < int(fields[19]) <= 2**64 - 1
    ):
        raise ValueError("NATIVE_PROCESS_STAT_INVALID")
    return int(fields[19])


def require_exclusive_flock_fdinfo(
    raw: bytes, *, pid: int, device: int, inode: int, descriptor_flags: int
) -> None:
    """Match this open description, not another lock owned by the same PID/inode."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 16 * 1024
        or any(type(value) is not int for value in (pid, device, inode, descriptor_flags))
        or not 0 < pid <= 2147483647
        or not 0 <= device < 2**64
        or not 0 < inode < 2**64
        or not 0 <= descriptor_flags < 2**32
    ):
        raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
    fields: dict[str, str] = {}
    for line in raw.decode("ascii", errors="strict").splitlines():
        name, separator, value = line.partition(":")
        if not separator or name not in {"pos", "flags", "mnt_id", "ino", "lock"} or name in fields:
            raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
        fields[name] = value.strip()
    if set(fields) != {"pos", "flags", "mnt_id", "ino", "lock"}:
        raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
    if (
        fields["pos"] != "0"
        or re.fullmatch(r"[0-7]{1,16}", fields["flags"]) is None
        or int(fields["flags"], 8) != descriptor_flags
        or re.fullmatch(r"[1-9][0-9]{0,19}", fields["mnt_id"]) is None
        or not 0 < int(fields["mnt_id"]) < 2**64
        or fields["ino"] != str(inode)
    ):
        raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
    lock = fields["lock"].split()
    if (
        len(lock) != 8
        or re.fullmatch(r"[1-9][0-9]{0,19}:", lock[0]) is None
        or lock[1:4] != ["FLOCK", "ADVISORY", "WRITE"]
        or lock[4] != str(pid)
        or lock[6:] != ["0", "EOF"]
    ):
        raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
    parts = lock[5].split(":")
    if (
        len(parts) != 3
        or any(re.fullmatch(r"[0-9a-f]{2,8}", part) is None for part in parts[:2])
        or parts[2] != str(inode)
        or (int(parts[0], 16), int(parts[1], 16)) != (os.major(device), os.minor(device))
    ):
        raise ValueError("NATIVE_FLOCK_FDINFO_INVALID")
