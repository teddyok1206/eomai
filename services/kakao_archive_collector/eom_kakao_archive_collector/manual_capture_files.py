"""Write-once protected local capture metadata; no payload interpretation or NAS I/O."""

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .profile import BrowserRuntimeError, protected_directory


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    size_bytes: int
    sha256: str


def reserve_download_payload(incoming: Path, destination: Path) -> None:
    """Durable local fence before a read action whose response might be lost."""
    if (
        incoming == destination.parent
        or re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", destination.name) is None
        or destination.suffix in {".partial", ".started"}
    ):
        raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
    owners = frozenset({0, os.geteuid()})
    with (
        protected_directory(incoming, allowed_uids=owners) as source_dir,
        protected_directory(destination.parent, allowed_uids=owners) as output_dir,
    ):
        source, output = os.fstat(source_dir), os.fstat(output_dir)
        if (
            source.st_uid != os.geteuid()
            or stat.S_IMODE(source.st_mode) != 0o700
            or output.st_uid != os.geteuid()
            or stat.S_IMODE(output.st_mode) != 0o750
        ):
            raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
        for name in (destination.name, destination.with_suffix(".partial").name):
            try:
                os.stat(name, dir_fd=output_dir, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_ALREADY_STARTED")
        try:
            marker = os.open(
                destination.with_suffix(".started").name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=output_dir,
            )
        except FileExistsError:
            raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_ALREADY_STARTED") from None
        with os.fdopen(marker, "wb") as receipt:
            os.fsync(receipt.fileno())
        os.fsync(output_dir)


def commit_download_payload(
    source: Path, *, incoming: Path, destination: Path, limit: int
) -> DownloadedFile:
    """Hash an SDK file into a write-once protected local attempt member."""
    if (
        source.parent != incoming
        or re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", destination.name) is None
        or destination.suffix == ".partial"
        or not 0 < limit <= 32 * 1024 * 1024
        or destination.parent == incoming
    ):
        raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
    owners = frozenset({0, os.geteuid()})
    partial = destination.with_suffix(".partial").name
    with (
        protected_directory(incoming, allowed_uids=owners) as source_dir,
        protected_directory(destination.parent, allowed_uids=owners) as output_dir,
    ):
        output = os.fstat(output_dir)
        if output.st_uid != os.geteuid() or stat.S_IMODE(output.st_mode) not in {0o700, 0o750}:
            raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
        fd = os.open(
            source.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=source_dir,
        )
        with os.fdopen(fd, "rb") as original:
            before = os.fstat(original.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_mode & 0o022
            ):
                raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
            if before.st_size == 0:
                raise BrowserRuntimeError("DOWNLOAD_EMPTY")
            if before.st_size > limit:
                raise BrowserRuntimeError("DOWNLOAD_LIMIT")
            target = os.open(
                partial,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o640,
                dir_fd=output_dir,
            )
            digest, count = hashlib.sha256(), 0
            with os.fdopen(target, "wb") as copied:
                os.fchown(copied.fileno(), -1, output.st_gid)
                os.fchmod(copied.fileno(), 0o640)
                while chunk := original.read(256 * 1024):
                    count += len(chunk)
                    if count > limit or count > before.st_size:
                        raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
                    digest.update(chunk)
                    copied.write(chunk)
                copied.flush()
                os.fsync(copied.fileno())
            after = os.fstat(original.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if count != before.st_size or any(
                getattr(before, field) != getattr(after, field) for field in fields
            ):
                raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
        os.link(
            partial,
            destination.name,
            src_dir_fd=output_dir,
            dst_dir_fd=output_dir,
            follow_symlinks=False,
        )
        os.unlink(partial, dir_fd=output_dir)
        os.fsync(output_dir)
    return DownloadedFile(size_bytes=count, sha256="sha256:" + digest.hexdigest())


def write_capture_receipt(path: Path, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, "wb") as stream:
        os.fchown(stream.fileno(), -1, path.parent.stat().st_gid)
        os.fchmod(stream.fileno(), 0o640)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def create_capture_directory(path: Path, *, private: bool = False) -> None:
    try:
        path.mkdir(mode=0o700 if private else 0o750)
        # RestrictSUIDSGID forbids setgid syscalls. Reuse existing group membership
        # for explicit read-only control access, keeping the systemd sandbox intact.
        with protected_directory(path, allowed_uids=frozenset({0, os.geteuid()})) as fd:
            os.fchown(fd, -1, path.parent.stat().st_gid)
            os.fchmod(fd, 0o700 if private else 0o750)
    except FileExistsError:
        pass
    with protected_directory(path, allowed_uids=frozenset({0, os.geteuid()})) as fd:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != (
            0o700 if private else 0o750
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_STAGING_UNSAFE")
