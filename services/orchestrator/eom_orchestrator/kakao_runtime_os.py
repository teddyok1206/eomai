"""Shared OS observations for the two fixed private Kakao units, not a scheduler."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

UNITS = frozenset({"eom-kakao-browser.service", "eom-kakao-remote.service"})


@dataclass(frozen=True, slots=True)
class IdleRuntimeObservation:
    """Read-only fixed-unit snapshot, never execution permission or prior success."""

    unit: str
    boot_id: str
    observed_at: datetime
    cgroup_state: Literal["ABSENT", "EMPTY"]
    never_dispatched: bool


class KakaoRuntimeOsError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@contextmanager
def protected_directory(
    path: Path, *, owners: frozenset[int], protected: bool = True
) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise KakaoRuntimeOsError("PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if protected and (info.st_uid not in owners or info.st_mode & 0o022):
                raise KakaoRuntimeOsError("DIRECTORY_UNTRUSTED")
        yield fd
    finally:
        os.close(fd)


def read_protected(path: Path, *, uid: int, maximum: int, owners: frozenset[int]) -> bytes:
    with protected_directory(path.parent, owners=owners) as directory:
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != uid
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or not 0 < before.st_size <= maximum
        ):
            raise KakaoRuntimeOsError("FILE_UNTRUSTED")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if (
            any(getattr(before, key) != getattr(after, key) for key in fields)
            or len(raw) != before.st_size
        ):
            raise KakaoRuntimeOsError("FILE_CHANGED")
        return raw


def boot_identity(path: Path) -> str:
    with path.open("r", encoding="ascii") as stream:
        value = stream.read(64).strip()
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is None:
        raise KakaoRuntimeOsError("BOOT_UNKNOWN")
    return value


def parse_unit_observation(raw: bytes, properties: tuple[str, ...]) -> dict[str, str]:
    try:
        if len(raw) > 16384:
            raise ValueError
        values: dict[str, str] = {}
        allowed = frozenset(properties)
        for line in raw.decode("utf-8").splitlines():
            key, value = line.split("=", 1)
            if key not in allowed or key in values:
                raise ValueError
            values[key] = value
        if values.keys() != allowed:
            raise ValueError
        for key in (
            "MainPID",
            "ControlPID",
            "ExecMainPID",
            "ExecMainStartTimestampMonotonic",
            "ExecMainCode",
            "ExecMainStatus",
        ):
            if re.fullmatch(r"0|[1-9][0-9]{0,19}", values[key]) is None:
                raise ValueError
        if values["Result"] not in {
            "success",
            "exit-code",
            "signal",
            "core-dump",
            "watchdog",
            "timeout",
            "start-limit-hit",
            "resources",
            "protocol",
            "oom-kill",
        }:
            raise ValueError
        return values
    except (ValueError, UnicodeError, KeyError):
        raise KakaoRuntimeOsError("OBSERVATION_INVALID") from None


def show_unit(unit: str, properties: tuple[str, ...]) -> dict[str, str]:
    if unit not in UNITS:
        raise KakaoRuntimeOsError("UNIT_UNTRUSTED")
    try:
        completed = subprocess.run(
            [
                "/usr/bin/systemctl",
                "show",
                unit,
                "--no-pager",
                "--property=" + ",".join(properties),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if completed.returncode:
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise KakaoRuntimeOsError("OBSERVATION_UNAVAILABLE") from None
    return parse_unit_observation(completed.stdout, properties)


def cgroup_closed(
    root: Path,
    unit: str,
    *,
    open_directory: Callable[[Path], AbstractContextManager[int]],
) -> Literal["ABSENT", "EMPTY"]:
    if unit not in UNITS:
        raise KakaoRuntimeOsError("UNIT_UNTRUSTED")
    path = root / "system.slice" / unit
    try:
        with open_directory(path) as directory:
            fd = os.open(
                "cgroup.events", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
            )
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(1025)
    except FileNotFoundError:
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise KakaoRuntimeOsError("CGROUP_UNKNOWN") from None
        with open_directory(root / "system.slice"):
            pass
        return "ABSENT"
    if len(raw) > 1024:
        raise KakaoRuntimeOsError("CGROUP_UNKNOWN")
    try:
        values: dict[str, str] = {}
        for line in raw.decode("ascii").splitlines():
            key, value = line.split()
            if key in values or key not in {"populated", "frozen"} or value not in {"0", "1"}:
                raise ValueError
            values[key] = value
        if values.get("populated") != "0":
            raise ValueError
    except (ValueError, UnicodeError):
        raise KakaoRuntimeOsError("CGROUP_NOT_CLOSED") from None
    return "EMPTY"
