"""Bounded protected system.slice cgroup reads; no process control or workload grant."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Literal

_ROOT = Path("/sys/fs/cgroup/system.slice")


class UnitProcessObservationError(ValueError):
    def __init__(self, code: Literal["INVALID", "NESTED_CGROUP"]) -> None:
        self.code = code
        super().__init__("UNIT_PROCESS_OBSERVATION_" + code)


def root_owned_unit_processes(unit: str) -> tuple[int, ...]:
    """Read one caller-validated unit, never an arbitrary cgroup/path or nested tree."""
    if (
        type(unit) is not str
        or not 9 <= len(unit) <= 255
        or re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", unit, re.ASCII) is None
    ):
        raise UnitProcessObservationError("INVALID")
    path = _ROOT / unit
    for directory in (path, *path.parents):
        value = directory.lstat()
        if not stat.S_ISDIR(value.st_mode) or value.st_uid != 0 or value.st_mode & 0o022:
            raise UnitProcessObservationError("INVALID")
    if any(child.is_dir() for child in path.iterdir()):
        raise UnitProcessObservationError("NESTED_CGROUP")
    descriptor = os.open(path / "cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        raw = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(raw) > 4096 or any(
        re.fullmatch(rb"[1-9][0-9]{0,9}", line) is None for line in raw.splitlines()
    ):
        raise UnitProcessObservationError("INVALID")
    pids = tuple(int(line) for line in raw.splitlines())
    if len(set(pids)) != len(pids) or len(pids) > 64 or any(pid > 2147483647 for pid in pids):
        raise UnitProcessObservationError("INVALID")
    return pids
