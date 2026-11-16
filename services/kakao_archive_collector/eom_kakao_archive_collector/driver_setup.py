"""Fixed MANUAL browser inputs and installed executable validation, never credentials output."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import secrets
import socket
import stat
import struct
from dataclasses import dataclass
from pathlib import Path

from eom_kakao_archive_contracts.kakao_remote import ProfileFence, validate_remote_contract

from .profile import BrowserRuntimeError, profile_lock, protected_directory, read_protected
from .supervisor import LOCK
from .supervisor import PRIVATE as PRIVATE
from .supervisor import PROFILE as PROFILE

PLAYWRIGHT_VERSION = "1.65.2"
BROWSER_ROOT = Path("/opt/eom/kakao-browser") / f"playwright-{PLAYWRIGHT_VERSION}"
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-browser/bin/python")
XVNC = Path("/usr/bin/Xtigervnc")
RELEASE = Path("/etc/eom/kakao-browser-driver.env")
XAUTHORITY = PRIVATE / "Xauthority"
PASSWORD = PROFILE.parent / "vnc.passwd"
VNC_SOCKET = Path("/run/eom-kakao-vnc/vnc.sock")
DISPLAY = ":94"
X_SOCKET = Path("/tmp/.X11-unix/X94")
X_LOCK = Path("/tmp/.X94-lock")
CGROUP = "0::/system.slice/eom-kakao-browser.service"


@dataclass(frozen=True, slots=True)
class ManualSetup:
    fence: ProfileFence
    xvnc_sha256: str
    chromium_sha256: str


def _kernel_read(path: Path) -> bytes:
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if not 0 < len(raw) <= 4096:
        raise BrowserRuntimeError("KAKAO_BROWSER_SUPERVISION_UNCONFIRMED")
    return raw


def require_supervisor() -> None:
    parent = os.getppid()
    expected = [
        str(PYTHON).encode(),
        b"-I",
        b"-B",
        b"-m",
        b"eom_kakao_archive_collector.supervisor",
    ]
    if (
        _kernel_read(Path("/proc/self/cgroup")).decode().strip() != CGROUP
        or _kernel_read(Path(f"/proc/{parent}/cgroup")).decode().strip() != CGROUP
        or _kernel_read(Path(f"/proc/{parent}/cmdline")).rstrip(b"\0").split(b"\0") != expected
        or os.getppid() != parent
    ):
        raise BrowserRuntimeError("KAKAO_BROWSER_SUPERVISION_UNCONFIRMED")
    try:
        with profile_lock(
            LOCK,
            uid=os.geteuid(),
            parent_uids=frozenset({0}),
            gid=grp.getgrnam("eom-kakao-control").gr_gid,
        ):
            pass
    except BrowserRuntimeError as error:
        if error.code == "KAKAO_BROWSER_PROFILE_BUSY":
            return
        raise
    raise BrowserRuntimeError("KAKAO_BROWSER_SUPERVISION_UNCONFIRMED")


def hash_executable(path: Path, *, uid: int = 0) -> str:
    """Stream once at the launch boundary, not copy a whole Chromium binary in memory."""
    with protected_directory(path.parent, allowed_uids=frozenset({0, uid})) as directory:
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
            or not before.st_mode & 0o111
            or not 0 < before.st_size <= 1024 * 1024 * 1024
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_EXECUTABLE_UNTRUSTED")
        digest = hashlib.sha256()
        count = 0
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > before.st_size:
                raise BrowserRuntimeError("KAKAO_BROWSER_EXECUTABLE_CHANGED")
            digest.update(chunk)
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
        ) or count != before.st_size:
            raise BrowserRuntimeError("KAKAO_BROWSER_EXECUTABLE_CHANGED")
    return "sha256:" + digest.hexdigest()


def require_chromium(path: Path, expected_sha256: str) -> None:
    if (
        not path.is_relative_to(BROWSER_ROOT)
        or path == BROWSER_ROOT
        or hash_executable(path) != expected_sha256
    ):
        raise BrowserRuntimeError("KAKAO_BROWSER_CHROMIUM_RELEASE_MISMATCH")


def _require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise BrowserRuntimeError("KAKAO_BROWSER_STALE_ENDPOINT_RECONCILE_REQUIRED")


def _authority_state(directory: int, name: str) -> os.stat_result | None:
    try:
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
        or not 0 < info.st_size <= 4096
    ):
        raise BrowserRuntimeError("KAKAO_BROWSER_XAUTHORITY_UNSAFE")
    return info


def prepare_xauthority() -> None:
    """Rotate local display authority only while the real supervisor owns the profile."""
    require_supervisor()
    if XAUTHORITY.parent != PRIVATE or XAUTHORITY.name != "Xauthority":
        raise BrowserRuntimeError("KAKAO_BROWSER_FIXED_INPUT_REQUIRED")
    for endpoint in (VNC_SOCKET, X_SOCKET, X_LOCK):
        _require_absent(endpoint)
    with protected_directory(PRIVATE, allowed_uids=frozenset({0, os.geteuid()})) as directory:
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise BrowserRuntimeError("KAKAO_BROWSER_DIRECTORY_UNSAFE")
        prior = _authority_state(directory, XAUTHORITY.name)
        hostname = socket.gethostname().encode("utf-8")
        if not 0 < len(hostname) <= 255 or re.fullmatch(r":[0-9]{1,3}", DISPLAY) is None:
            raise BrowserRuntimeError("KAKAO_BROWSER_DISPLAY_INVALID")
        # libXau: network-order FamilyLocal, then four length-prefixed byte strings.
        # The cookie is passed only through this protected file, never a process argument.
        fields = (
            hostname,
            DISPLAY[1:].encode("ascii"),
            b"MIT-MAGIC-COOKIE-1",
            secrets.token_bytes(16),
        )
        raw = struct.pack("!H", 256) + b"".join(
            struct.pack("!H", len(value)) + value for value in fields
        )
        temporary = ".Xauthority.next"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
        except OSError:
            raise BrowserRuntimeError("KAKAO_BROWSER_XAUTHORITY_CREATE_FAILED") from None
        created = os.fstat(fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            require_supervisor()
            current = _authority_state(directory, XAUTHORITY.name)
            staged = _authority_state(directory, temporary)
            if (
                current != prior
                or staged is None
                or (staged.st_dev, staged.st_ino)
                != (
                    created.st_dev,
                    created.st_ino,
                )
            ):
                raise BrowserRuntimeError("KAKAO_BROWSER_XAUTHORITY_CHANGED")
            os.replace(temporary, XAUTHORITY.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        except OSError:
            raise BrowserRuntimeError("KAKAO_BROWSER_XAUTHORITY_WRITE_FAILED") from None
        finally:
            # Remove only this call's unfinished inode, never an older or substituted file.
            try:
                pending = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (pending.st_dev, pending.st_ino) == (created.st_dev, created.st_ino):
                    os.unlink(temporary, dir_fd=directory)


def validate_setup(request: Path, profile: Path) -> ManualSetup:
    browser = pwd.getpwnam("eom-kakao")
    uid = browser.pw_uid
    if (
        (os.geteuid(), os.getegid()) != (uid, browser.pw_gid)
        or uid == 0
        or profile != PROFILE
        or request.parent != PRIVATE
        or re.fullmatch(r"kakaobrowserrun_[0-9a-f]{32}\.json", request.name) is None
    ):
        raise BrowserRuntimeError("KAKAO_BROWSER_FIXED_INPUT_REQUIRED")
    raw = read_protected(
        request, uid=uid, limit=4096, allowed_uids=frozenset({0, uid}), required_mode=0o400
    )
    value = json.loads(raw)
    validate_remote_contract("profile", value)
    fence = ProfileFence.model_validate(value)
    if request.name != f"{fence.browser_run_id}.json":
        raise BrowserRuntimeError("KAKAO_BROWSER_FENCE_MISMATCH")
    if fence.mode != "MANUAL":
        raise BrowserRuntimeError("KAKAO_BROWSER_AUTO_UNAVAILABLE")
    require_supervisor()
    for path in (PROFILE, PRIVATE):
        with protected_directory(path, allowed_uids=frozenset({0, uid})) as directory:
            metadata = os.fstat(directory)
            if metadata.st_uid != uid or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise BrowserRuntimeError("KAKAO_BROWSER_DIRECTORY_UNSAFE")
    with protected_directory(VNC_SOCKET.parent, allowed_uids=frozenset({0, uid})) as directory:
        metadata = os.fstat(directory)
        if (
            metadata.st_uid != uid
            or metadata.st_gid != grp.getgrnam("eom-kakao-vnc").gr_gid
            or stat.S_IMODE(metadata.st_mode) != 0o2750
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_VNC_DIRECTORY_UNSAFE")
    raw = read_protected(
        PASSWORD, uid=uid, limit=16, allowed_uids=frozenset({0, uid}), required_mode=0o600
    )
    if len(raw) not in {8, 16}:
        raise BrowserRuntimeError("KAKAO_BROWSER_VNC_PASSWORD_FILE_INVALID")
    for path in (VNC_SOCKET, X_SOCKET, X_LOCK):
        _require_absent(path)
    config = read_protected(RELEASE, uid=0, limit=256, allowed_uids=frozenset({0})).decode("ascii")
    pattern = (
        r"EOM_KAKAO_XVNC_SHA256=(sha256:[0-9a-f]{64})\n"
        r"EOM_KAKAO_CHROMIUM_SHA256=(sha256:[0-9a-f]{64})\n"
    )
    matched = re.fullmatch(pattern, config)
    if matched is None or hash_executable(XVNC) != matched.group(1):
        raise BrowserRuntimeError("KAKAO_BROWSER_DRIVER_RELEASE_MISMATCH")
    return ManualSetup(fence, matched.group(1), matched.group(2))


def child_environment() -> dict[str, str]:
    # Paths are not secret values. Inherit no tokens, debug flags, proxies or caller config.
    return {
        "HOME": str(PROFILE.parent),
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "TMPDIR": "/tmp",
        "DISPLAY": DISPLAY,
        "XAUTHORITY": str(XAUTHORITY),
        "PLAYWRIGHT_BROWSERS_PATH": str(BROWSER_ROOT),
    }


def xvnc_argv() -> tuple[str, ...]:
    return (
        str(XVNC),
        DISPLAY,
        "-geometry",
        "1440x960",
        "-depth",
        "24",
        "-desktop",
        "EOM-Kakao",
        "-auth",
        str(XAUTHORITY),
        "-nolisten",
        "tcp",
        "-rfbport",
        "-1",
        "-rfbunixpath",
        str(VNC_SOCKET),
        "-rfbunixmode",
        "0660",
        "-SecurityTypes",
        "VncAuth",
        "-PasswordFile",
        str(PASSWORD),
    )
