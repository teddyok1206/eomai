"""Fixed UDS gateway watchdog. No API, browser selectors, login or profile access."""

from __future__ import annotations

import grp
import importlib.metadata
import os
import pwd
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from eom_kakao_archive_contracts.kakao_remote import (
    GatewayLeaseGrant,
    GatewayRevocation,
    gateway_execution_digest,
)

from .grant_file import GatewayRuntimeError, protected_directory, read_owner_grant, read_protected
from .lifetime import GatewayLifetimeState, RemoteGatewayLifetime
from .process import GatewayChild

GRANT = Path("/var/lib/eom-kakao-runtime/remote/grant.json")
PYTHON = Path("/opt/eom/conda/envs/eom-kakao-remote/bin/python")
ASSETS = Path("/opt/eom/kakao-remote/releases/novnc-1.6.0/noVNC")
LISTENER = Path("/run/eom-kakao-remote/gateway.sock")
TARGET = Path("/run/eom-kakao-vnc/vnc.sock")
POLL_SECONDS = 0.1
STARTUP_SECONDS = 10.0
VNC_CGROUP = Path("/sys/fs/cgroup/system.slice/eom-kakao-browser.service")


def _target_ready() -> bool:
    """The permitted gateway UID checks VNC; Catalog must not join the VNC group."""
    browser_uid = pwd.getpwnam("eom-kakao").pw_uid
    vnc_gid = grp.getgrnam("eom-kakao-vnc").gr_gid
    with protected_directory(TARGET.parent, allowed_uids=frozenset({0, browser_uid})) as directory:
        try:
            info = os.stat(TARGET.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != browser_uid
            or info.st_gid != vnc_gid
            or stat.S_IMODE(info.st_mode) != 0o660
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_UNSAFE")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.1)
            try:
                connection.connect(str(TARGET))
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
                return False
            pid, peer_uid, _ = struct.unpack(
                "3i",
                connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")),
            )
            if peer_uid != browser_uid or pid <= 0:
                raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_PEER_INVALID")
            # ProtectProc=invisible prevents inspecting a foreign UID through /proc.
            # The fixed, read-only kernel cgroup membership is the authority instead.
            with protected_directory(VNC_CGROUP, allowed_uids=frozenset({0})) as group:
                fd = os.open(
                    "cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=group
                )
                with os.fdopen(fd, "rb") as stream:
                    raw = stream.read(4097)
            if len(raw) > 4096:
                raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_PEER_INVALID")
            try:
                lines = raw.decode("ascii").splitlines()
                if not lines or any(
                    not value.isascii() or not value.isdecimal() for value in lines
                ):
                    raise ValueError
                members = {int(value) for value in lines}
            except (ValueError, UnicodeError):
                raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_PEER_INVALID") from None
            if pid not in members:
                raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_PEER_INVALID")
        after = os.stat(TARGET.name, dir_fd=directory, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            raise GatewayRuntimeError("KAKAO_GATEWAY_TARGET_CHANGED")
    return True


def _notify_ready(grant: GatewayLeaseGrant) -> None:
    if os.environ.get("NOTIFY_SOCKET") != "/run/systemd/notify":
        raise GatewayRuntimeError("KAKAO_GATEWAY_NOTIFY_INVALID")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
        connection.connect("/run/systemd/notify")
        connection.sendall(
            ("READY=1\nSTATUS=KAKAO_GATEWAY_STARTED:" + gateway_execution_digest(grant)).encode()
        )


def _listener_ready() -> bool:
    remote = pwd.getpwnam("eom-kakao-remote")
    proxy = grp.getgrnam("eom-kakao-proxy")
    with protected_directory(
        LISTENER.parent, allowed_uids=frozenset({0, remote.pw_uid})
    ) as directory:
        try:
            info = os.stat(LISTENER.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if (
            not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != remote.pw_uid
            or info.st_gid != proxy.gr_gid
            or stat.S_IMODE(info.st_mode) != 0o660
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_SOCKET_UNSAFE")
    # A socket inode alone can be stale. No HTTP/WebSocket bytes or authorization are sent.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.1)
        try:
            connection.connect(str(LISTENER))
        except (FileNotFoundError, ConnectionRefusedError, TimeoutError):
            return False
    return True


def gateway_argv() -> tuple[str, ...]:
    return (
        str(PYTHON),
        "-I",
        "-B",
        "-m",
        "websockify",
        "--unix-listen",
        str(LISTENER),
        "--unix-listen-mode",
        "0660",
        "--unix-target",
        str(TARGET),
        "--web",
        str(ASSETS),
        "--file-only",
    )


def supervise(
    read_grant: Callable[[], GatewayLeaseGrant | GatewayRevocation],
    launch: Callable[[], subprocess.Popen[bytes]],
    *,
    stopping: threading.Event,
    listener_ready: Callable[[], bool],
    notify_ready: Callable[[GatewayLeaseGrant], None],
    utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
    monotonic_now: Callable[[], float] = time.monotonic,
) -> None:
    """Local adapter seams for tests; CLI exposes no paths, argv or caller-supplied grants."""
    if stopping.is_set():
        raise GatewayRuntimeError("KAKAO_GATEWAY_START_CANCELLED")
    initial = read_grant()
    if not isinstance(initial, GatewayLeaseGrant):
        raise GatewayRuntimeError("KAKAO_GATEWAY_GRANT_REVOKED")
    child: GatewayChild | None = None

    def close(_: GatewayLeaseGrant) -> bool:
        if child is not None:
            child.close()
        # The owner, not this child adapter, must confirm the whole cgroup is empty.
        return False

    lifetime = RemoteGatewayLifetime(
        initial, now=utc_now(), monotonic_now=monotonic_now(), stop_gateway=close
    )
    try:
        if stopping.is_set():
            raise GatewayRuntimeError("KAKAO_GATEWAY_START_CANCELLED")
        child = GatewayChild(launch())
        ready = False
        startup_deadline = monotonic_now() + STARTUP_SECONDS
        while True:
            if stopping.is_set():
                return
            if child.exited():
                raise GatewayRuntimeError("KAKAO_GATEWAY_CHILD_EXITED")
            if (
                lifetime.poll(now=utc_now(), monotonic_now=monotonic_now())
                != GatewayLifetimeState.ACTIVE
            ):
                return
            observed = read_grant()
            if isinstance(observed, GatewayRevocation):
                lifetime.revoke(observed)
                return
            lifetime.accept_renewal(observed, now=utc_now(), monotonic_now=monotonic_now())
            if not ready:
                if monotonic_now() >= startup_deadline:
                    raise GatewayRuntimeError("KAKAO_GATEWAY_START_TIMEOUT")
                if listener_ready():
                    if (
                        lifetime.poll(now=utc_now(), monotonic_now=monotonic_now())
                        != GatewayLifetimeState.ACTIVE
                    ):
                        return
                    notify_ready(initial)
                    ready = True
            stopping.wait(POLL_SECONDS)
    finally:
        if child is not None:
            child.close()


def _prepare() -> int:
    remote = pwd.getpwnam("eom-kakao-remote")
    owner = pwd.getpwnam("eom-catalog-manager")
    browser = pwd.getpwnam("eom-kakao")
    caddy = pwd.getpwnam("caddy")
    proxy_gid = grp.getgrnam("eom-kakao-proxy").gr_gid
    vnc_gid = grp.getgrnam("eom-kakao-vnc").gr_gid
    grant_gid = grp.getgrnam("eom-kakao-grant").gr_gid
    allowed_groups = {remote.pw_gid, proxy_gid, vnc_gid, grant_gid}
    if (
        os.geteuid() != remote.pw_uid
        or os.getegid() != proxy_gid
        or remote.pw_uid in {0, owner.pw_uid, browser.pw_uid, caddy.pw_uid}
        or not set(os.getgroups()).issubset(allowed_groups)
        or not {vnc_gid, grant_gid}.issubset(os.getgroups())
    ):
        raise GatewayRuntimeError("KAKAO_GATEWAY_IDENTITY_INVALID")
    if importlib.metadata.version("websockify") != "0.13.0":
        raise GatewayRuntimeError("KAKAO_GATEWAY_DEPENDENCY_INVALID")
    if Path(sys.executable) != PYTHON:
        raise GatewayRuntimeError("KAKAO_GATEWAY_INTERPRETER_INVALID")
    with protected_directory(PYTHON.parent, allowed_uids=frozenset({0})):
        pass
    resolved_python = PYTHON.resolve(strict=True)
    if not resolved_python.is_relative_to(PYTHON.parent):
        raise GatewayRuntimeError("KAKAO_GATEWAY_INTERPRETER_INVALID")
    read_protected(resolved_python, uid=0, limit=64 * 1024 * 1024, allowed_uids=frozenset({0}))
    # Installation separately verifies the entire pinned inventory and licenses. Runtime
    # also rejects writable/symlink assets and unexpected huge trees before it reads a grant.
    with protected_directory(ASSETS, allowed_uids=frozenset({0})):
        pass
    count = 0
    total = 0

    def reject_walk_error(_: OSError) -> None:
        raise GatewayRuntimeError("KAKAO_GATEWAY_ASSETS_INVALID")

    for directory, subdirs, files in os.walk(ASSETS, followlinks=False, onerror=reject_walk_error):
        for name in subdirs:
            count += 1
            if count > 4096:
                raise GatewayRuntimeError("KAKAO_GATEWAY_ASSETS_INVALID")
            with protected_directory(Path(directory) / name, allowed_uids=frozenset({0})):
                pass
        for name in files:
            count += 1
            if count > 4096:
                raise GatewayRuntimeError("KAKAO_GATEWAY_ASSETS_INVALID")
            raw = read_protected(
                Path(directory) / name, uid=0, limit=8 * 1024 * 1024, allowed_uids=frozenset({0})
            )
            total += len(raw)
            if total > 64 * 1024 * 1024:
                raise GatewayRuntimeError("KAKAO_GATEWAY_ASSETS_INVALID")
    for member in ("vnc.html", "app/ui.js", "core/rfb.js", "LICENSE.txt"):
        read_protected(ASSETS / member, uid=0, limit=8 * 1024 * 1024, allowed_uids=frozenset({0}))
    with protected_directory(LISTENER.parent, allowed_uids=frozenset({0, remote.pw_uid})) as fd:
        info = os.fstat(fd)
        if (
            info.st_uid != remote.pw_uid
            or info.st_gid != proxy_gid
            or stat.S_IMODE(info.st_mode) != 0o2750
        ):
            raise GatewayRuntimeError("KAKAO_GATEWAY_SOCKET_DIRECTORY_UNSAFE")
        try:
            os.stat(LISTENER.name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise GatewayRuntimeError("KAKAO_GATEWAY_SOCKET_EXISTS")
    with protected_directory(TARGET.parent, allowed_uids=frozenset({0, browser.pw_uid})):
        pass
    return owner.pw_uid


def main() -> int:
    if len(sys.argv) != 1:
        print("KAKAO_GATEWAY_ARGUMENTS_FORBIDDEN", file=sys.stderr)
        return 2
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    try:
        owner_uid = _prepare()
        supervise(
            lambda: read_owner_grant(GRANT, owner_uid=owner_uid),
            lambda: subprocess.Popen(
                gateway_argv(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
                cwd=LISTENER.parent,
                start_new_session=True,
                close_fds=True,
            ),
            stopping=stopping,
            listener_ready=lambda: _target_ready() and _listener_ready(),
            notify_ready=_notify_ready,
        )
    except GatewayRuntimeError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    except Exception:
        # Stable redaction: do not log file bytes, routes, headers or dependency output.
        print("KAKAO_GATEWAY_STOPPED_OR_UNAVAILABLE", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
