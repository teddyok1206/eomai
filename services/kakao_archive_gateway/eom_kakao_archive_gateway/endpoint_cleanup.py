"""Fixed gateway-unit stop hook. No grant, profile, source or credential access."""

from __future__ import annotations

import grp
import os
import pwd
import socket
import stat
import sys
from pathlib import Path

from .grant_file import GatewayRuntimeError, protected_directory
from .supervisor import LISTENER

CGROUP = "0::/system.slice/eom-kakao-remote.service"


def _cgroup() -> str:
    with Path("/proc/self/cgroup").open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_SCOPE_INVALID")
    return raw.decode().strip()


def cleanup_stopped_endpoint() -> None:
    remote = pwd.getpwnam("eom-kakao-remote")
    proxy_gid = grp.getgrnam("eom-kakao-proxy").gr_gid
    if (
        os.geteuid() != remote.pw_uid
        or remote.pw_uid == 0
        or os.getegid() != proxy_gid
        or _cgroup() not in {CGROUP, CGROUP + "/.control"}
    ):
        raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_SCOPE_INVALID")
    with protected_directory(
        LISTENER.parent, allowed_uids=frozenset({0, remote.pw_uid})
    ) as directory:
        try:
            before = os.stat(LISTENER.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        if (
            not stat.S_ISSOCK(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != remote.pw_uid
            or before.st_gid != proxy_gid
            or stat.S_IMODE(before.st_mode) != 0o660
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_ENDPOINT_UNSAFE")
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(0.25)
            try:
                probe.connect(str(LISTENER))
            except FileNotFoundError:
                return
            except ConnectionRefusedError:
                pass
            else:
                raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_ENDPOINT_LIVE")
        after = os.stat(LISTENER.name, dir_fd=directory, follow_symlinks=False)
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
            raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_ENDPOINT_CHANGED")
        os.unlink(LISTENER.name, dir_fd=directory)
        os.fsync(directory)


def main() -> int:
    try:
        if len(sys.argv) != 1:
            raise GatewayRuntimeError("KAKAO_GATEWAY_CLEANUP_ARGUMENTS_FORBIDDEN")
        cleanup_stopped_endpoint()
    except GatewayRuntimeError as error:
        print(error.code, file=sys.stderr)
        return 75
    except Exception:
        print("KAKAO_GATEWAY_CLEANUP_UNCONFIRMED", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
