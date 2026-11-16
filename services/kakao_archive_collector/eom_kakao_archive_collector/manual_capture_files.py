"""Write-once protected local capture metadata; no payload interpretation or NAS I/O."""

import os
import stat
from pathlib import Path

from .profile import BrowserRuntimeError, protected_directory


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
