"""Safe local reads shared by image-training publication adapters."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


class PublicationFileReadError(RuntimeError):
    """A local publication input could not be read without following links."""


def read_regular_file(
    path: Path,
    *,
    maximum_bytes: int,
    expected_sha256: str | None = None,
) -> bytes:
    """Read one stable regular file without traversing a symbolic link."""

    if not path.is_absolute() or maximum_bytes <= 0:
        raise PublicationFileReadError("PUBLICATION_SOURCE_PATH_INVALID")
    current = Path(path.root)
    try:
        for part in path.parts[1:]:
            current /= part
            if stat.S_ISLNK(current.lstat().st_mode):
                raise PublicationFileReadError("PUBLICATION_SOURCE_PATH_INVALID")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise PublicationFileReadError("PUBLICATION_SOURCE_READ_FAILED") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
        ):
            raise PublicationFileReadError("PUBLICATION_SOURCE_FILE_INVALID")
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, before.st_size - len(payload)))
            if not chunk:
                raise PublicationFileReadError("PUBLICATION_SOURCE_FILE_TRUNCATED")
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise PublicationFileReadError("PUBLICATION_SOURCE_FILE_CHANGED")
    finally:
        os.close(descriptor)
    body = bytes(payload)
    actual_sha256 = "sha256:" + hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise PublicationFileReadError("PUBLICATION_SOURCE_HASH_MISMATCH")
    return body
