"""Descriptor-checked local profile lock, held for the entire managed process lifetime."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class BrowserRuntimeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@contextmanager
def protected_directory(path: Path, *, allowed_uids: frozenset[int]) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise BrowserRuntimeError("KAKAO_BROWSER_PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
            metadata = os.fstat(fd)
            if metadata.st_uid not in allowed_uids or metadata.st_mode & 0o022:
                raise BrowserRuntimeError("KAKAO_BROWSER_DIRECTORY_UNSAFE")
        yield fd
    finally:
        os.close(fd)


def read_protected(
    path: Path,
    *,
    uid: int,
    limit: int,
    allowed_uids: frozenset[int],
    required_mode: int | None = None,
) -> bytes:
    with protected_directory(path.parent, allowed_uids=allowed_uids) as directory:
        fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != uid
            or before.st_mode & 0o022
            or (required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode)
            or not 0 < before.st_size <= limit
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_MEMBER_UNSAFE")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        # atime can change on a read; compare protected identity/content fields only.
        if (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(raw) != before.st_size:
            raise BrowserRuntimeError("KAKAO_BROWSER_MEMBER_CHANGED")
    return raw


@contextmanager
def profile_lock(
    path: Path, *, uid: int, parent_uids: frozenset[int], gid: int | None = None
) -> Iterator[None]:
    """Never create, replace or unlink the installed lock, including on contention."""
    with protected_directory(path.parent, allowed_uids=parent_uids) as directory:
        fd = os.open(
            path.name,
            os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != uid
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o640
                or (gid is not None and info.st_gid != gid)
                or info.st_size != 0
            ):
                raise BrowserRuntimeError("KAKAO_BROWSER_LOCK_UNSAFE")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BrowserRuntimeError("KAKAO_BROWSER_PROFILE_BUSY") from None
            linked = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != (info.st_dev, info.st_ino):
                raise BrowserRuntimeError("KAKAO_BROWSER_LOCK_CHANGED")
            yield
        finally:
            os.close(fd)
