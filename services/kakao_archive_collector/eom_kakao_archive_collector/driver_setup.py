"""Fixed MANUAL browser inputs and installed executable validation, never credentials output."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import re
import stat
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
    for path, limit in ((XAUTHORITY, 4096), (PASSWORD, 16)):
        raw = read_protected(
            path, uid=uid, limit=limit, allowed_uids=frozenset({0, uid}), required_mode=0o600
        )
        if path == PASSWORD and len(raw) not in {8, 16}:
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
