"""Protected no-replay phase/file IO shared by concrete root unit owners, not authority."""

from __future__ import annotations

import os
import re
import stat
from contextlib import suppress
from pathlib import Path
from typing import Literal


class UnitEffectRecordError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise UnitEffectRecordError(code)


def _require_record_identity(
    root: Path, unit: str, invocation: str, phase: Literal["ack", "retirement"]
) -> None:
    _require(os.getresuid() == (0, 0, 0), "OWNER_REQUIRED")
    _require(
        isinstance(root, Path)
        and root.is_absolute()
        and ".." not in root.parts
        and type(unit) is str
        and len(unit.encode()) <= 255
        and re.fullmatch(r"eom-[A-Za-z0-9_.@\\-]+\.service", unit, re.ASCII) is not None
        and type(invocation) is str
        and re.fullmatch(r"[0-9a-f]{32}", invocation, re.ASCII) is not None
        and type(phase) is str
        and phase in {"ack", "retirement"},
        "IDENTITY_INVALID",
    )


def require_unit_effect_phase_absent(
    root: Path, unit: str, invocation: str, phase: Literal["ack", "retirement"]
) -> None:
    """Read-only absence; even an incomplete existing intent prohibits this path."""
    _require_record_identity(root, unit, invocation, phase)
    for path in (*reversed(root.parents), root, root / unit, root / unit / invocation):
        try:
            value = path.lstat()
        except FileNotFoundError:
            return  # Its first missing ancestor was protected; never follow a dangling symlink.
        _require(
            stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022,
            "RECORD_DIRECTORY_INVALID",
        )
    try:
        (root / unit / invocation / phase).lstat()
    except FileNotFoundError:
        return
    raise UnitEffectRecordError("RECORD_PHASE_PRESENT")


def reserve_unit_effect_phase(
    root: Path, unit: str, invocation: str, phase: Literal["ack", "retirement"]
) -> int:
    """Own the returned directory FD; caller validates the specific unit/phase authority."""
    _require_record_identity(root, unit, invocation, phase)
    for ancestor in (*reversed(root.parents), root):
        if ancestor == root:
            with suppress(FileExistsError):
                ancestor.mkdir(mode=0o700)
        value = ancestor.lstat()
        _require(
            stat.S_ISDIR(value.st_mode) and value.st_uid == 0 and not value.st_mode & 0o022,
            "RECORD_DIRECTORY_INVALID",
        )
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for name in (unit, invocation, phase):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                if name == phase:
                    raise
            child = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent
            )
            try:
                value = os.fstat(child)
                _require(
                    stat.S_ISDIR(value.st_mode)
                    and value.st_uid == 0
                    and stat.S_IMODE(value.st_mode) == 0o700
                    and value == os.stat(name, dir_fd=parent, follow_symlinks=False),
                    "RECORD_DIRECTORY_INVALID",
                )
            except BaseException:
                os.close(child)
                raise
            os.close(parent)
            parent = child
        descriptor, parent = parent, -1
        return descriptor
    finally:
        if parent >= 0:
            os.close(parent)


def write_unit_effect_record(
    directory: int, name: Literal["intent.json", "result.json"], raw: bytes
) -> None:
    """Exclusive bounded bytes only; caller owns typed canonical record semantics."""
    _require(type(name) is str and name in {"intent.json", "result.json"}, "IDENTITY_INVALID")
    _require(type(raw) is bytes and 0 < len(raw) <= 256 * 1024, "RECORD_TOO_LARGE")
    descriptor = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o400,
        dir_fd=directory,
    )
    try:
        remaining = memoryview(raw)
        while remaining:
            count = os.write(descriptor, remaining)
            _require(type(count) is int and 0 < count <= len(remaining), "RECORD_WRITE_FAILED")
            remaining = remaining[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)
