"""Real local Unix transport; synthetic filesystem ownership, not installed admission."""

from __future__ import annotations

import fcntl
import os
import socket
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from eom_catalog_service import embedding_benchmark_activation as activation
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkUnixPeer,
)

from tests.unit.embedding_device_benchmark_fixtures import worker_invocation


@pytest.fixture(name="tmp_path")
def short_unix_socket_root() -> Iterator[Path]:
    # pytest's descriptive default path can exceed Linux sockaddr_un's byte bound.
    with tempfile.TemporaryDirectory(prefix="eom-bs-") as directory:
        yield Path(directory)


def listener_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[socket.socket, Path]:
    # Linux sockaddr_un is bounded; keep the real fixture pathname short.
    root = tmp_path / "b"
    root.mkdir(mode=0o700)
    execution = root / worker_invocation().execution_id
    execution.mkdir(mode=0o700)
    path = execution / "control.sock"
    monkeypatch.setattr(activation, "_HANDOFF_ROOT", root)
    monkeypatch.setattr(activation, "_ROOT_UID", os.getuid())
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    path.chmod(0o600)
    listener.listen(1)
    listener.setblocking(False)
    return listener, path


def peer() -> BenchmarkUnixPeer:
    return BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())


def test_capture_actual_peer_borrowed_listener_flags_and_endpoint_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener, path = listener_fixture(tmp_path, monkeypatch)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    observed = []
    original_flags = fcntl.fcntl(listener.fileno(), fcntl.F_GETFL)
    try:
        client.connect(str(path))
        channel = activation.capture_benchmark_worker_channel(
            worker_invocation(),
            activation_fd=listener.fileno(),
            expected_peer=peer(),
            peer_fence=lambda actual: observed.append(actual),
            expires_ns=time.monotonic_ns() + 10**9,
        )
        channel.assert_initial_invocation(worker_invocation())
        assert observed and all(value == peer() for value in observed)
        assert fcntl.fcntl(listener.fileno(), fcntl.F_GETFL) == original_flags
        assert path.is_socket()
        channel.close()
        channel.close()
        assert client.recv(1) == b""
        assert listener.fileno() >= 0
    finally:
        client.close()
        listener.close()


@pytest.mark.parametrize("fault", ("peer", "mode", "blocking", "deadline", "fence"))
def test_wrong_peer_namespace_mode_deadline_or_fence_never_returns_channel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    listener, path = listener_fixture(tmp_path, monkeypatch)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    expected = peer()
    deadline = time.monotonic_ns() + 10**9
    try:
        client.connect(str(path))
        if fault == "peer":
            expected = BenchmarkUnixPeer(expected.pid + 1, expected.uid, expected.gid)
        elif fault == "mode":
            path.chmod(0o666)
        elif fault == "blocking":
            listener.setblocking(True)
        elif fault == "deadline":
            deadline = time.monotonic_ns() - 1

        def fence(actual: BenchmarkUnixPeer) -> None:
            if fault == "fence":
                raise ValueError("synthetic owner fence failure")

        with pytest.raises(BenchmarkChannelError):
            activation.capture_benchmark_worker_channel(
                worker_invocation(),
                activation_fd=listener.fileno(),
                expected_peer=expected,
                peer_fence=fence,
                expires_ns=deadline,
            )
        assert listener.fileno() >= 0 and path.is_socket()
    finally:
        client.close()
        listener.close()


def test_changed_socket_after_accept_invalidates_endpoint_without_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener, path = listener_fixture(tmp_path, monkeypatch)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    channel = None
    try:
        client.connect(str(path))
        channel = activation.capture_benchmark_worker_channel(
            worker_invocation(),
            activation_fd=listener.fileno(),
            expected_peer=peer(),
            peer_fence=lambda actual: None,
            expires_ns=time.monotonic_ns() + 10**9,
        )
        path.chmod(0o400)
        with pytest.raises(BenchmarkChannelError):
            channel.assert_initial_invocation(worker_invocation())
        assert client.recv(1) == b""
    finally:
        if channel is not None:
            channel.close()
        client.close()
        listener.close()


def test_unconnected_listener_wait_is_bounded_and_does_not_mutate_borrowed_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener, _ = listener_fixture(tmp_path, monkeypatch)
    try:
        started = time.monotonic_ns()
        with pytest.raises(BenchmarkChannelError):
            activation.capture_benchmark_worker_channel(
                worker_invocation(),
                activation_fd=listener.fileno(),
                expected_peer=peer(),
                peer_fence=lambda actual: None,
                expires_ns=started + 50_000_000,
            )
        assert time.monotonic_ns() - started < 2 * 10**9
        assert listener.fileno() >= 0
    finally:
        listener.close()
