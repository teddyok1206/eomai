"""Capture one PID1 listener; never bind a path, authorize a Job or launch a process."""

from __future__ import annotations

import fcntl
import os
import selectors
import socket
import stat
import time
from collections.abc import Callable
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation

from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkUnixPeer,
    BenchmarkWorkerChannel,
    PeerFence,
)

_HANDOFF_ROOT = Path("/run/eom-incremental-embeddings/benchmark")
_ROOT_UID = 0


def _require(condition: bool) -> None:
    if not condition:
        raise BenchmarkChannelError("BENCHMARK_ACTIVATION_INVALID")


def _socket_epoch(path: Path, peer: BenchmarkUnixPeer) -> tuple[int, ...]:
    for directory in (path.parent, *path.parent.parents):
        value = directory.lstat()
        synthetic_tmp = (
            _ROOT_UID != 0 and directory == Path("/tmp") and bool(value.st_mode & stat.S_ISVTX)
        )
        _require(
            stat.S_ISDIR(value.st_mode)
            and value.st_uid in (0, _ROOT_UID)
            and (not value.st_mode & 0o022 or synthetic_tmp)
        )
    value = path.lstat()
    _require(
        stat.S_ISSOCK(value.st_mode)
        and value.st_uid == peer.uid
        and value.st_gid == peer.gid
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_nlink == 1
    )
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def capture_benchmark_worker_channel(
    invocation: BenchmarkWorkerInvocation,
    *,
    activation_fd: int,
    expected_peer: BenchmarkUnixPeer,
    peer_fence: PeerFence,
    expires_ns: int,
) -> BenchmarkWorkerChannel:
    """Own a duplicated listener and accepted connection, never the borrowed activation FD.

    PID1 must pass a nonblocking AF_UNIX listener. The fixed root/owner own the socket
    pathname; the numerical worker cannot bind, chmod, unlink, reconnect or choose a peer.
    """
    now = time.monotonic_ns()
    _require(
        type(activation_fd) is int
        and activation_fd >= 3
        and type(expected_peer) is BenchmarkUnixPeer
        and callable(peer_fence)
        and type(expires_ns) is int
        and now < expires_ns <= now + 180 * 10**9
    )
    invocation = BenchmarkWorkerInvocation.model_validate(invocation)
    expected_peer.__post_init__()
    path = _HANDOFF_ROOT / invocation.execution_id / "control.sock"
    epoch = _socket_epoch(path, expected_peer)
    listener: socket.socket | None = None
    connection: socket.socket | None = None
    duplicate = -1
    try:
        _require(bool(fcntl.fcntl(activation_fd, fcntl.F_GETFL) & os.O_NONBLOCK))
        duplicate = fcntl.fcntl(activation_fd, fcntl.F_DUPFD_CLOEXEC, 3)
        listener = socket.socket(fileno=duplicate)
        duplicate = -1
        _require(
            listener.family == socket.AF_UNIX
            and listener.type == socket.SOCK_STREAM
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
            and listener.getsockname() == str(path)
            and not listener.get_inheritable()
        )

        def fence(actual: BenchmarkUnixPeer) -> None:
            _require(actual == expected_peer and time.monotonic_ns() < expires_ns)
            _require(_socket_epoch(path, expected_peer) == epoch)
            check_peer: Callable[[BenchmarkUnixPeer], object] = peer_fence
            _require(check_peer(actual) is None)

        with selectors.DefaultSelector() as selector:
            selector.register(listener, selectors.EVENT_READ)
            while connection is None:
                remaining = (expires_ns - time.monotonic_ns()) / 10**9
                _require(remaining > 0 and _socket_epoch(path, expected_peer) == epoch)
                if not selector.select(min(remaining, 0.5)):
                    continue
                try:
                    connection, _ = listener.accept()
                except BlockingIOError:
                    continue
        connection.setblocking(False)
        connection.set_inheritable(False)
        result = BenchmarkWorkerChannel(
            connection,
            invocation,
            expected_peer=expected_peer,
            peer_fence=fence,
            expires_ns=expires_ns,
        )
        connection = None  # The endpoint now owns it, including later failure cleanup.
        return result
    except Exception:
        raise BenchmarkChannelError("BENCHMARK_ACTIVATION_CAPTURE_FAILED") from None
    finally:
        if connection is not None:
            connection.close()
        if listener is not None:
            listener.close()
        if duplicate >= 0:
            os.close(duplicate)
