"""Descriptor-relative bounded I/O for isolated model and probe materializations."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath

from eom_image_provider.provider import ProviderError


@contextmanager
def open_verified_directory(path: Path, *, expected_owner_uid: int) -> Iterator[int]:
    """Own directory admission/cleanup, not errors from a numerical consumer inside the scope."""
    if not path.is_absolute():
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    with ExitStack() as handles:
        try:
            # Protected ancestors may grant traversal without listing. O_PATH keeps this
            # descriptor-relative no-link walk without broadening their permissions.
            current = os.open(path.root, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
            handles.callback(os.close, current)
            for part in path.parts[1:]:
                if part in {"", ".", ".."}:
                    raise ProviderError("SDXL_PROBE_INPUT_INVALID")
                current = os.open(
                    part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current
                )
                handles.callback(os.close, current)
            current = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=current)
            handles.callback(os.close, current)
            metadata = os.fstat(current)
            if metadata.st_uid != expected_owner_uid or stat.S_IMODE(metadata.st_mode) & 0o022:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        except OSError as exc:
            raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc
        yield current


@contextmanager
def verified_directory(path: Path, *, expected_owner_uid: int) -> Iterator[int]:
    """Retain the established staged-I/O scope error policy for existing callers."""
    try:
        with open_verified_directory(path, expected_owner_uid=expected_owner_uid) as descriptor:
            yield descriptor
    except OSError as exc:
        raise ProviderError("SDXL_PROBE_INPUT_INVALID") from exc


@contextmanager
def _member(root: int, relative: str, *, write: bool = False) -> Iterator[int]:
    parts = relative.split("/")
    if (
        PurePosixPath(relative).is_absolute()
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ProviderError("SDXL_PROBE_INPUT_INVALID")
    directories = []
    descriptor = None
    current = root
    try:
        for part in parts[:-1]:
            current = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current
            )
            directories.append(current)
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL) if write else os.O_RDONLY
        descriptor = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=current)
        yield descriptor
    except OSError as exc:
        raise ProviderError(
            "SDXL_PROBE_OUTPUT_INVALID" if write else "SDXL_PROBE_INPUT_INVALID"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for directory in reversed(directories):
            os.close(directory)


def read_staged_member(
    root: int,
    relative: str,
    *,
    maximum_bytes: int,
    expected_sha256: str | None = None,
    expected_owner_uid: int | None = None,
) -> bytes:
    return _inspect(
        root,
        relative,
        maximum_bytes=maximum_bytes,
        expected_sha256=expected_sha256,
        expected_owner_uid=expected_owner_uid,
        materialize=True,
    )[1]


def verify_staged_member(
    root: int,
    relative: str,
    *,
    size_bytes: int,
    sha256: str,
    expected_owner_uid: int,
) -> None:
    actual_size, _ = _inspect(
        root,
        relative,
        maximum_bytes=size_bytes,
        expected_sha256=sha256,
        expected_owner_uid=expected_owner_uid,
        materialize=False,
    )
    if actual_size != size_bytes:
        raise ProviderError("SDXL_PROBE_HASH_MISMATCH")


def _inspect(
    root: int,
    relative: str,
    *,
    maximum_bytes: int,
    expected_sha256: str | None,
    expected_owner_uid: int | None,
    materialize: bool,
) -> tuple[int, bytes]:
    with _member(root, relative) as descriptor:
        before = os.fstat(descriptor)
        if (
            maximum_bytes <= 0
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= maximum_bytes
            or stat.S_IMODE(before.st_mode) & 0o022
            or (expected_owner_uid is not None and before.st_uid != expected_owner_uid)
        ):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        digest = hashlib.sha256()
        payload = bytearray()
        count = 0
        while count < before.st_size:
            chunk = os.read(descriptor, min(4 * 1024**2, before.st_size - count))
            if not chunk:
                raise ProviderError("SDXL_PROBE_INPUT_INVALID")
            digest.update(chunk)
            count += len(chunk)
            if materialize:
                payload.extend(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ProviderError("SDXL_PROBE_INPUT_INVALID")
        if expected_sha256 is not None and "sha256:" + digest.hexdigest() != expected_sha256:
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        return count, bytes(payload)


def write_staged_member(root: int, relative: str, payload: bytes) -> None:
    with (
        _member(root, relative, write=True) as descriptor,
        os.fdopen(descriptor, "wb", closefd=False) as output,
    ):
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def create_staged_directory(root: int, name: str) -> None:
    if "/" in name or name in {"", ".", ".."}:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID")
    try:
        os.mkdir(name, 0o700, dir_fd=root)
    except OSError as exc:
        raise ProviderError("SDXL_PROBE_OUTPUT_INVALID") from exc


def copy_verified_member(
    source_root: int,
    destination_root: int,
    relative: str,
    *,
    size_bytes: int,
    sha256: str,
    source_owner_uid: int,
    destination_group_gid: int,
) -> None:
    """Stream a pinned weight at the operator install boundary, never through an in-memory blob."""
    with (
        _member(source_root, relative) as source,
        _member(destination_root, relative, write=True) as destination,
    ):
        before = os.fstat(source)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != source_owner_uid
            or stat.S_IMODE(before.st_mode) & 0o022
            or before.st_size != size_bytes
            or not 0 < size_bytes <= 8 * 1024**3
        ):
            raise ProviderError("SDXL_PROBE_MODEL_INVALID")
        digest = hashlib.sha256()
        count = 0
        with os.fdopen(destination, "wb", closefd=False) as output:
            while count < size_bytes:
                chunk = os.read(source, min(4 * 1024**2, size_bytes - count))
                if not chunk:
                    raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
                output.write(chunk)
                digest.update(chunk)
                count += len(chunk)
            output.flush()
            os.fsync(destination)
        after = os.fstat(source)
        if "sha256:" + digest.hexdigest() != sha256 or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ProviderError("SDXL_PROBE_HASH_MISMATCH")
        os.fchown(destination, os.geteuid(), destination_group_gid)
        os.fchmod(destination, 0o640)
