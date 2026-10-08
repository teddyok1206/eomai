"""Bounded owner preparation secrets; no logging or implicit credential fallback."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4

from eom_orchestrator.general_chat_state import ChatError

ENVIRONMENT_LIMIT = 16384


def read_chat_preparation_file(path: Path, *, uid: int, gid: int, mode: int) -> bytes:
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_uid, before.st_gid, stat.S_IMODE(before.st_mode)) != (uid, gid, mode)
            or not 0 < before.st_size <= ENVIRONMENT_LIMIT
            or before.st_nlink != 1
        ):
            raise ValueError()
        payload = bytearray()
        while len(payload) <= ENVIRONMENT_LIMIT:
            chunk = os.read(descriptor, ENVIRONMENT_LIMIT + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) != before.st_size or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError()
        return bytes(payload)
    except (OSError, ValueError):
        raise ChatError("GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_chat_environment(path: Path, *, uid: int, gid: int, mode: int) -> dict[str, str]:
    try:
        payload = read_chat_preparation_file(path, uid=uid, gid=gid, mode=mode)
        values = {}
        for line in payload.decode("ascii").splitlines():
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            if not key or key in values or any(ord(char) < 32 for char in value):
                raise ValueError()
            values[key] = value
        return values
    except (ValueError, UnicodeError):
        raise ChatError("GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID") from None


def install_chat_environment(path: Path, payload: bytes, *, uid: int, gid: int) -> None:
    """No-replace durable first installation; exact existing bytes are retained."""
    if not 0 < len(payload) <= ENVIRONMENT_LIMIT:
        raise ChatError("GENERAL_CHAT_PROTECTED_ENVIRONMENT_INVALID")
    temporary = path.with_name("." + path.name + "." + uuid4().hex)
    descriptor = -1
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.fchown(descriptor, uid, gid)
        offset = 0
        while offset < len(payload):
            count = os.write(descriptor, payload[offset:])
            if count <= 0:
                raise OSError()
            offset += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except (OSError, ValueError):
        raise ChatError("GENERAL_CHAT_PROTECTED_ENVIRONMENT_INSTALL_FAILED") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
