"""Private local materialization only; never resolves or publishes NAS identities."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from eom_kakao_archive_contracts import LocalMember, sha256


class KakaoPdfExecutionError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@contextmanager
def local_directory(path: Path) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise KakaoPdfExecutionError("KAKAO_PDF_PATH_INVALID")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def require_owner_directory(path: Path, uid: int, gid: int) -> None:
    with local_directory(path) as fd:
        info = os.fstat(fd)
        if info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700:
            raise KakaoPdfExecutionError("KAKAO_PDF_WORKSPACE_UNSAFE")


def create_directory(parent: Path, name: str, *, gid: int, mode: int) -> Path:
    if not name or "/" in name or name in {".", ".."}:
        raise KakaoPdfExecutionError("KAKAO_PDF_PATH_INVALID")
    with local_directory(parent) as fd:
        os.mkdir(name, mode=0o700, dir_fd=fd)
        child = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd
        )
        try:
            os.fchown(child, -1, gid)
            os.fchmod(child, mode)
            os.fsync(fd)
        finally:
            os.close(child)
    return parent / name


def read_local(root: Path, name: str, *, limit: int, uid: int, gid: int | None = None) -> bytes:
    # LocalMember validates names for inputs; result.json is an owner-chosen constant.
    parts = name.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise KakaoPdfExecutionError("KAKAO_PDF_PATH_INVALID")
    with local_directory(root.joinpath(*parts[:-1])) as directory:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != uid
            or (gid is not None and before.st_gid != gid)
            or before.st_mode & 0o022
            or not 0 < before.st_size <= limit
        ):
            raise KakaoPdfExecutionError("KAKAO_PDF_MEMBER_UNSAFE")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(raw) != before.st_size:
            raise KakaoPdfExecutionError("KAKAO_PDF_MEMBER_CHANGED")
    return raw


def read_pinned(root: Path, member: LocalMember, *, uid: int, gid: int | None = None) -> bytes:
    raw = read_local(root, member.relative_path, limit=member.size_bytes, uid=uid, gid=gid)
    if len(raw) != member.size_bytes or sha256(raw) != member.sha256:
        raise KakaoPdfExecutionError("KAKAO_PDF_MEMBER_HASH_MISMATCH")
    return raw


def write_local(root: Path, name: str, raw: bytes, *, gid: int) -> None:
    parts = name.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise KakaoPdfExecutionError("KAKAO_PDF_PATH_INVALID")
    parent = root
    for part in parts[:-1]:
        try:
            parent = create_directory(parent, part, gid=gid, mode=0o750)
        except FileExistsError:
            parent /= part
            with local_directory(parent):
                pass
    with local_directory(parent) as directory:
        fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as stream:
            os.fchown(stream.fileno(), -1, gid)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
