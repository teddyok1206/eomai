"""Fixed installed driver only. No browser selectors, login secrets or scheduling here."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import signal
import socket
import stat
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from eom_kakao_archive_contracts.kakao_remote import ProfileFence, validate_remote_contract

from .profile import BrowserRuntimeError, profile_lock, protected_directory, read_protected

REQUEST = Path("/var/lib/eom-kakao-runtime/browser/request.json")
PROFILE = Path("/var/lib/eom-kakao/profile")
LOCK = PROFILE.parent / "profile.lock"
PRIVATE = Path("/run/eom-kakao-private")
DRIVER = Path("/srv/eom/conda/envs/eom-kakao-browser/bin/eom-kakao-browser-driver")
DRIVER_ENV = Path("/etc/eom/kakao-browser.env")
GRACE_SECONDS = 20.0
FORCE_SECONDS = 2.0


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _notify(command_digest: str) -> None:
    target = os.environ.get("NOTIFY_SOCKET")
    if target != "/run/systemd/notify":
        raise BrowserRuntimeError("KAKAO_BROWSER_NOTIFY_INVALID")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
        connection.connect(target)
        connection.sendall(f"READY=1\nSTATUS=KAKAO_BROWSER_STARTED:{command_digest}".encode())


def _terminate(child: subprocess.Popen[bytes], *, grace_seconds: float) -> None:
    # First let the driver close its browser context/flush. Systemd additionally kills
    # the complete cgroup, including descendants outside this process group. Do not
    # kill a possibly recycled group ID after reaping its original main process.
    forced = False
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            forced = True
            child.kill()
    try:
        child.wait(timeout=FORCE_SECONDS)
    except subprocess.TimeoutExpired:
        raise BrowserRuntimeError("KAKAO_BROWSER_CHILD_STOP_UNKNOWN") from None
    if forced:
        raise BrowserRuntimeError("KAKAO_BROWSER_CHILD_STOP_FORCED")


def supervise(
    launch: Callable[[], subprocess.Popen[bytes]],
    *,
    lock_path: Path,
    uid: int,
    parent_uids: frozenset[int],
    stopping: threading.Event,
    notify_ready: Callable[[], None],
    grace_seconds: float = GRACE_SECONDS,
) -> int:
    """Internal OS adapter seam for subprocess tests, not a public command/argv API."""
    if not 0 <= grace_seconds <= GRACE_SECONDS:
        raise BrowserRuntimeError("KAKAO_BROWSER_GRACE_INVALID")
    with profile_lock(lock_path, uid=uid, parent_uids=parent_uids):
        if stopping.is_set():
            raise BrowserRuntimeError("KAKAO_BROWSER_START_CANCELLED")
        child = launch()
        try:
            if child.poll() is not None or os.getpgid(child.pid) != child.pid:
                raise BrowserRuntimeError("KAKAO_BROWSER_DRIVER_START_FAILED")
            notify_ready()
            while child.poll() is None and not stopping.wait(0.1):
                pass
        finally:
            _terminate(child, grace_seconds=grace_seconds)
        # Read after the close/flush handler has actually finished. A requested stop
        # is not success when the handler fails, or default SIGTERM kills the driver.
        if child.returncode is None:
            raise BrowserRuntimeError("KAKAO_BROWSER_CHILD_STOP_UNKNOWN")
        if child.returncode < 0:
            raise BrowserRuntimeError("KAKAO_BROWSER_CHILD_STOP_UNCLEAN")
        return child.returncode


def _prepare() -> tuple[Path, str]:
    browser = pwd.getpwnam("eom-kakao")
    owner = pwd.getpwnam("eom-catalog-manager")
    if (os.geteuid(), os.getegid()) != (browser.pw_uid, browser.pw_gid) or browser.pw_uid == 0:
        raise BrowserRuntimeError("KAKAO_BROWSER_IDENTITY_INVALID")
    raw = read_protected(
        REQUEST, uid=owner.pw_uid, limit=4096, allowed_uids=frozenset({0, owner.pw_uid})
    )
    value = json.loads(raw)
    validate_remote_contract("profile", value)
    fence = ProfileFence.model_validate(value)
    if fence.mode not in {"AUTO", "MANUAL"}:
        raise BrowserRuntimeError("KAKAO_BROWSER_MODE_NOT_STARTABLE")
    command_digest = _digest(raw)
    for directory_path in (PROFILE, PRIVATE):
        with protected_directory(directory_path, allowed_uids=frozenset({0, browser.pw_uid})) as fd:
            info = os.fstat(fd)
            if info.st_uid != browser.pw_uid or stat.S_IMODE(info.st_mode) != 0o700:
                raise BrowserRuntimeError("KAKAO_BROWSER_DIRECTORY_UNSAFE")
    binary = read_protected(DRIVER, uid=0, limit=1024 * 1024, allowed_uids=frozenset({0}))
    if not os.access(DRIVER, os.X_OK):
        raise BrowserRuntimeError("KAKAO_BROWSER_DRIVER_UNAVAILABLE")
    env = read_protected(DRIVER_ENV, uid=0, limit=256, allowed_uids=frozenset({0}))
    if env != f"EOM_KAKAO_BROWSER_DRIVER_SHA256={_digest(binary)}\n".encode():
        raise BrowserRuntimeError("KAKAO_BROWSER_DRIVER_RELEASE_MISMATCH")
    # Never overwrite an earlier attempt, even if the process is now absent.
    snapshot = PRIVATE / f"{fence.browser_run_id}.json"
    with protected_directory(PRIVATE, allowed_uids=frozenset({0, browser.pw_uid})) as directory:
        fd = os.open(
            snapshot.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
    return snapshot, command_digest


def main() -> int:
    if len(sys.argv) != 1:
        print("KAKAO_BROWSER_FIXED_INPUT_REQUIRED", file=sys.stderr)
        return 78
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    try:
        snapshot, digest = _prepare()
        environment = {
            "HOME": str(PROFILE.parent),
            "LANG": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "TMPDIR": "/tmp",
        }
        return supervise(
            lambda: subprocess.Popen(
                [str(DRIVER), "--request", str(snapshot), "--profile", str(PROFILE)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                cwd=PRIVATE,
                start_new_session=True,
                close_fds=True,
            ),
            lock_path=LOCK,
            uid=os.geteuid(),
            parent_uids=frozenset({0}),
            stopping=stopping,
            notify_ready=lambda: _notify(digest),
        )
    except BrowserRuntimeError as error:
        print(error.code, file=sys.stderr)
        return 75 if error.code == "KAKAO_BROWSER_PROFILE_BUSY" else 78
    except Exception:
        # Never include paths, JSON validation detail, browser stdout or credentials.
        print("KAKAO_BROWSER_RUNTIME_UNAVAILABLE", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
