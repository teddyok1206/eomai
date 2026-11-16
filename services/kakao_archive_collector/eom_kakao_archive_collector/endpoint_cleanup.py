"""Fixed browser-unit stop hook. Remove only a dead, owned VNC Unix socket."""

from __future__ import annotations

import grp
import os
import pwd
import socket
import stat
import sys
from pathlib import Path

from . import driver_setup as setup
from .profile import BrowserRuntimeError, profile_lock, protected_directory
from .supervisor import LOCK


def cleanup_stopped_endpoint() -> None:
    browser = pwd.getpwnam("eom-kakao")
    if (
        os.geteuid() != browser.pw_uid
        or browser.pw_uid == 0
        or setup._kernel_read(Path("/proc/self/cgroup")).decode().strip()
        not in {setup.CGROUP, setup.CGROUP + "/.control"}
    ):
        raise BrowserRuntimeError("KAKAO_BROWSER_CLEANUP_SCOPE_INVALID")
    with (
        profile_lock(
            LOCK,
            uid=browser.pw_uid,
            parent_uids=frozenset({0}),
            gid=grp.getgrnam("eom-kakao-control").gr_gid,
        ),
        protected_directory(
            setup.VNC_SOCKET.parent, allowed_uids=frozenset({0, browser.pw_uid})
        ) as directory,
    ):
        try:
            before = os.stat(setup.VNC_SOCKET.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        if (
            not stat.S_ISSOCK(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != browser.pw_uid
            or before.st_gid != grp.getgrnam("eom-kakao-vnc").gr_gid
            or stat.S_IMODE(before.st_mode) != 0o660
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_CLEANUP_ENDPOINT_UNSAFE")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.25)
            try:
                probe.connect(str(setup.VNC_SOCKET))
            except FileNotFoundError:
                return
            except ConnectionRefusedError:
                pass
            else:
                raise BrowserRuntimeError("KAKAO_BROWSER_CLEANUP_ENDPOINT_LIVE")
        after = os.stat(setup.VNC_SOCKET.name, dir_fd=directory, follow_symlinks=False)
        if (
            before.st_dev,
            before.st_ino,
            before.st_uid,
            before.st_gid,
            before.st_nlink,
            before.st_mode,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            after.st_nlink,
            after.st_mode,
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_CLEANUP_ENDPOINT_CHANGED")
        os.unlink(setup.VNC_SOCKET.name, dir_fd=directory)
        os.fsync(directory)


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise BrowserRuntimeError("KAKAO_BROWSER_CLEANUP_ARGUMENTS_FORBIDDEN")
        cleanup_stopped_endpoint()
    except BrowserRuntimeError as error:
        print(error.code, file=sys.stderr)
        return 75
    except Exception:
        print("KAKAO_BROWSER_CLEANUP_UNCONFIRMED", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
