"""Borrow one PID1 root-only listener; no binding, reconnect, source or compute grant."""

from __future__ import annotations

import fcntl
import os
import selectors
import socket
import stat
import struct
import time

from eom_catalog_contracts.embedding_gpu_control import (
    MAX_EMBEDDING_GPU_ALLOCATION_SECONDS,
    EmbeddingGpuAllocationRequest,
    parse_embedding_gpu_control,
)

from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_gpu_batch_launch import GPU_BATCH_RUNTIME_ROOT
from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel

_ROOT_IDENTITY = (0, 0)
_LISTENER_CREATOR = BenchmarkUnixPeer(1, 0, 0)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_GPU_BATCH_ACTIVATION_INVALID")


def capture_embedding_gpu_batch_worker_channel(
    request: EmbeddingGpuAllocationRequest, *, activation_fd: int, expected_root_pid: int
) -> EmbeddingGpuControlChannel:
    """Consume no path authority: PID1's inherited socket is the fixed capability.

    Worker mount isolation hides the handoff path and root /proc. Kernel peer and
    per-frame sender credentials bind the original root connection; no claimed
    root process-birth observation is invented. Root separately owns unit admission.
    """
    checked = parse_embedding_gpu_control(request)
    _require(type(checked) is EmbeddingGpuAllocationRequest)
    assert isinstance(checked, EmbeddingGpuAllocationRequest)
    _require(type(activation_fd) is int and activation_fd >= 3)
    root = BenchmarkUnixPeer(expected_root_pid, *_ROOT_IDENTITY)
    deadline = checked.expires_monotonic_ns
    now = time.monotonic_ns()
    _require(now < deadline <= now + MAX_EMBEDDING_GPU_ALLOCATION_SECONDS * 10**9)
    listener = connection = None
    duplicate = -1
    original = os.fstat(activation_fd)

    def inherited_current() -> None:
        current = os.fstat(activation_fd)
        _require(
            (current.st_dev, current.st_ino, current.st_mode)
            == (original.st_dev, original.st_ino, original.st_mode)
            and stat.S_ISSOCK(current.st_mode)
            and bool(fcntl.fcntl(activation_fd, fcntl.F_GETFL) & os.O_NONBLOCK)
            and bool(fcntl.fcntl(activation_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
        )

    try:
        inherited_current()
        duplicate = fcntl.fcntl(activation_fd, fcntl.F_DUPFD_CLOEXEC, 3)
        listener = socket.socket(fileno=duplicate)
        duplicate = -1
        path = (
            GPU_BATCH_RUNTIME_ROOT
            / checked.allocation_attempt_id.removeprefix("embeddingallocation_")
            / "control.sock"
        )
        _require(
            listener.family == socket.AF_UNIX
            and listener.type == socket.SOCK_STREAM
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) == 1
            and listener.getsockname() == str(path)
            and BenchmarkUnixPeer(
                *struct.unpack(
                    "=iII", listener.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                )
            )
            == _LISTENER_CREATOR
        )
        with selectors.DefaultSelector() as selector:
            selector.register(listener, selectors.EVENT_READ)
            while connection is None:
                inherited_current()
                remaining = (deadline - time.monotonic_ns()) / 10**9
                _require(remaining > 0)
                if not selector.select(min(remaining, 0.5)):
                    continue
                try:
                    connection, _ = listener.accept()
                except BlockingIOError:
                    continue
        connection.setblocking(False)
        connection.set_inheritable(False)
        _require(connection.getsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED) == 1)

        def root_fence(actual: BenchmarkUnixPeer) -> None:
            _require(actual == root and time.monotonic_ns() < deadline)

        result = EmbeddingGpuControlChannel(
            connection,
            checked,
            side="WORKER",
            expected_peer=root,
            expected_sender=root,
            peer_fence=root_fence,
        )
        connection = None
        return result
    except Exception:
        raise ValueError("EMBEDDING_GPU_BATCH_ACTIVATION_INVALID") from None
    finally:
        if connection is not None:
            connection.close()
        if listener is not None:
            listener.close()
        if duplicate >= 0:
            os.close(duplicate)
