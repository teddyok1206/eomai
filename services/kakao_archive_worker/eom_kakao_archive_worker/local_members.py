"""Descriptor-relative staged input validation; a path is never source identity."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from eom_kakao_archive_contracts import LocalMember, MediaType, sha256


@contextmanager
def directory_descriptor(path: Path) -> Iterator[int]:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("KAKAO_RENDER_WORKSPACE_INVALID")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def read_member(root: Path, member: LocalMember) -> bytes:
    parts = member.relative_path.split("/")
    with directory_descriptor(root.joinpath(*parts[:-1])) as directory:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("KAKAO_RENDER_MEMBER_UNSAFE")
        if before.st_size != member.size_bytes:
            raise ValueError("KAKAO_RENDER_MEMBER_SIZE_MISMATCH")
        raw = stream.read(member.size_bytes + 1)
        after = os.fstat(stream.fileno())
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("KAKAO_RENDER_MEMBER_CHANGED")
    if len(raw) != member.size_bytes or sha256(raw) != member.sha256:
        raise ValueError("KAKAO_RENDER_MEMBER_HASH_MISMATCH")
    return raw


def write_member(root: Path, name: str, raw: bytes, media_type: MediaType) -> LocalMember:
    # Outputs are worker-chosen opaque single-component names, never source filenames.
    member = LocalMember(
        relative_path=name, sha256=sha256(raw), size_bytes=len(raw), media_type=media_type
    )
    if "/" in name:
        raise ValueError("KAKAO_RENDER_OUTPUT_NAME_INVALID")
    with directory_descriptor(root) as directory:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o640,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    return member
