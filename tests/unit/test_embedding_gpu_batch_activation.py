"""Real Unix listener with explicit synthetic root identities; no actual PID1/root grant."""

from __future__ import annotations

import os
import socket
import tempfile
import time
from pathlib import Path

import pytest
from eom_catalog_service import embedding_gpu_batch_activation as activation
from eom_catalog_service.embedding_benchmark_channel import BenchmarkUnixPeer
from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel

from tests.unit.test_embedding_gpu_control import control_case


@pytest.fixture
def listener(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="eom-gb-") as folder:
        root = Path(folder)
        case = control_case(expires_ns=time.monotonic_ns() + 5 * 10**9)
        path = root / ("a" * 32) / "control.sock"
        path.parent.mkdir()
        peer = BenchmarkUnixPeer(os.getpid(), os.geteuid(), os.getegid())
        monkeypatch.setattr(activation, "GPU_BATCH_RUNTIME_ROOT", root)
        monkeypatch.setattr(activation, "_ROOT_IDENTITY", (peer.uid, peer.gid))
        monkeypatch.setattr(activation, "_LISTENER_CREATOR", peer)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            server.bind(str(path))
            server.listen(1)
            server.setblocking(False)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                client.connect(str(path))
                yield server, client, peer, case


def capture(listener):
    server, _, peer, case = listener
    return activation.capture_embedding_gpu_batch_worker_channel(
        case[0],
        activation_fd=server.fileno(),
        expected_root_pid=peer.pid,
    )


def test_original_root_request_and_busy_cross_real_accepted_socket_without_owning_listener(
    listener,
):
    server, client, peer, case = listener
    descriptor = server.fileno()
    observed = os.fstat(descriptor)
    native = capture(listener)
    root = EmbeddingGpuControlChannel(
        client,
        case[0],
        side="ROOT",
        expected_peer=peer,
        expected_sender=peer,
        peer_fence=lambda actual: None if actual == peer else pytest.fail("peer changed"),
    )
    try:
        root.send_request()
        native.receive_request()
        native.send_allocation(case[2])
        assert root.receive_allocation() == case[2]
    finally:
        root.close()
        native.close()
    assert server.fileno() == descriptor and not server.getblocking()
    assert os.fstat(descriptor).st_ino == observed.st_ino
    assert not server.get_inheritable()


@pytest.mark.parametrize("seconds", (180, 420))
def test_legacy_and_separate_control_allowance_cross_same_original_activation_fd(listener, seconds):
    server, client, peer, _case = listener
    case = control_case(expires_ns=time.monotonic_ns() + seconds * 10**9)
    native = capture((server, client, peer, case))
    root = EmbeddingGpuControlChannel(
        client,
        case[0],
        side="ROOT",
        expected_peer=peer,
        expected_sender=peer,
        peer_fence=lambda actual: None if actual == peer else pytest.fail("peer changed"),
    )
    try:
        root.send_request()
        native.receive_request()
    finally:
        root.close()
        native.close()


def test_activation_rejects_overlong_window_before_accepting_socket(listener):
    server, _client, peer, _case = listener
    case = control_case(expires_ns=time.monotonic_ns() + 421 * 10**9)
    with pytest.raises(ValueError):
        activation.capture_embedding_gpu_batch_worker_channel(
            case[0],
            activation_fd=server.fileno(),
            expected_root_pid=peer.pid,
        )


@pytest.mark.parametrize(
    "fault",
    ["blocking", "passcred", "inheritable", "creator", "path", "root_peer", "not_listening"],
)
def test_activation_refuses_changed_descriptor_or_foreign_root_before_any_work(
    listener, monkeypatch, fault
):
    server, client, peer, case = listener
    descriptor = server.fileno()
    root_pid = peer.pid
    if fault == "blocking":
        server.setblocking(True)
    elif fault == "passcred":
        server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 0)
    elif fault == "inheritable":
        server.set_inheritable(True)
    elif fault == "creator":
        monkeypatch.setattr(
            activation, "_LISTENER_CREATOR", BenchmarkUnixPeer(peer.pid + 1, peer.uid, peer.gid)
        )
    elif fault == "path":
        monkeypatch.setattr(
            activation, "GPU_BATCH_RUNTIME_ROOT", Path("/tmp/not-the-original-unit")
        )
    elif fault == "root_peer":
        root_pid += 1
    else:
        descriptor = client.fileno()
        client.setblocking(False)
    with pytest.raises(ValueError, match="ACTIVATION_INVALID"):
        activation.capture_embedding_gpu_batch_worker_channel(
            case[0], activation_fd=descriptor, expected_root_pid=root_pid
        )
    assert server.fileno() >= 0 and client.fileno() >= 0


def test_accept_timeout_does_not_reset_budget_or_close_borrowed_listener(listener, monkeypatch):
    server, client, _peer, case = listener
    # Drain the one queued connection. The same inherited listener then has none.
    accepted, _ = server.accept()
    accepted.close()
    monkeypatch.setattr(time, "monotonic_ns", lambda: case[0].expires_monotonic_ns)
    with pytest.raises(ValueError, match="ACTIVATION_INVALID"):
        capture(listener)
    assert server.fileno() >= 0 and client.fileno() >= 0
