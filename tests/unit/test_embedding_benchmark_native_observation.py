"""Full real Unix credential framing and synthetic encoder; no installed/PID1/GPU claim."""

import os
import socket
import threading
import time
from contextlib import contextmanager

import pytest
from eom_catalog_contracts.embedding_vector_binary import read_unit_vectors
from eom_catalog_service import embedding_benchmark_native_observation as owner
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkUnixPeer,
    BenchmarkWorkerChannel,
)
from eom_catalog_service.embedding_benchmark_native_connection import (
    CapturedBenchmarkNativeConnection,
)
from eom_catalog_service.embedding_device_benchmark_worker import run_embedding_device_benchmark
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import CpuHandoffIdentity

from tests.unit.embedding_device_benchmark_fixtures import staged_inputs, worker_invocation
from tests.unit.test_embedding_device_benchmark_files import stage_files
from tests.unit.test_embedding_device_benchmark_worker import FakeBackend, HostObserver


@pytest.mark.parametrize("ordinal", (1, 4))
@pytest.mark.parametrize("late_ack_delay", (False, True))
def test_actual_owner_clocks_include_each_fresh_authorization_and_ranking(
    tmp_path, monkeypatch, ordinal, late_ack_delay
):
    files, root, borrowed = stage_files(tmp_path, monkeypatch, ordinal)
    invocation = worker_invocation(ordinal)
    identity = CpuHandoffIdentity(os.getuid(), os.getgid())
    monkeypatch.setattr(owner, "fixed_owner_identity", lambda: identity)
    peer = BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())
    calls = []
    authorization = object.__new__(BenchmarkLaunchAuthorization)
    authorization._invocation = invocation
    monkeypatch.setattr(
        BenchmarkLaunchAuthorization, "assert_current", lambda self: calls.append("authorize")
    )
    authorization_spans = []
    if late_ack_delay:
        real_monotonic = time.monotonic_ns
        offset = [0]
        monkeypatch.setattr(time, "monotonic_ns", lambda: real_monotonic() + offset[0])
        original_authorize = BenchmarkLaunchAuthorization.authorize_checkpoint

        def delayed_authorize(self, checkpoint):
            before = time.monotonic_ns()
            original_authorize(self, checkpoint)
            # Synthetic clock movement, not a wait or actual performance evidence.
            offset[0] += 7_000_000 if checkpoint.phase == "QUERY_PREPARED" else 1_000_000_000
            authorization_spans.append((checkpoint.phase, before, time.monotonic_ns()))

        monkeypatch.setattr(BenchmarkLaunchAuthorization, "authorize_checkpoint", delayed_authorize)

    def read_vectors(_invocation, vector):
        assert _invocation == invocation
        calls.append("read-" + vector.purpose)
        return read_unit_vectors(
            (root / "outputs" / vector.member_name).read_bytes(),
            dimension=1024,
            row_count=vector.row_count,
            expected_sha256=vector.sha256,
        )

    monkeypatch.setattr(owner, "read_benchmark_ready_vectors", read_vectors)
    left, right = socket.socketpair()
    right.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    transport = object.__new__(CapturedBenchmarkNativeConnection)
    transport.connection, transport.listener, transport.sender = right, peer, peer
    transport._writer_may_exit = False
    transport.peer_fence = lambda actual: (
        calls.append("peer") if actual == peer else pytest.fail("peer changed")
    )
    expires = time.monotonic_ns() + 30 * 10**9
    worker = BenchmarkWorkerChannel(
        left, invocation, expected_peer=peer, peer_fence=lambda _: None, expires_ns=expires
    )
    observed, errors = [], []

    def observe():
        try:
            observed.append(
                owner.observe_benchmark_native_session(
                    transport,
                    invocation,
                    staged_inputs(),
                    authorization=authorization,
                    expires_ns=expires,
                    owner_started_ns=time.monotonic_ns() - 1_000_000,
                )
            )
        except BaseException as error:
            errors.append(error)

    events = []
    backend = FakeBackend(invocation, events)

    @contextmanager
    def scope():
        try:
            yield backend
        finally:
            backend.closed = True

    thread = threading.Thread(target=observe)
    thread.start()
    try:
        result = run_embedding_device_benchmark(
            files,
            scope,
            worker,
            entry_started_ns=time.perf_counter_ns() - 1_000_000,
            expires_ns=expires,
            host_oom_observer=HostObserver(events),
        )
    finally:
        worker.close()
        thread.join(timeout=5)
        transport.close()
        os.close(borrowed)
    assert not thread.is_alive() and not errors
    assert result.status == "COMPLETED" and observed[0].resources == result.resources
    assert transport._writer_may_exit and right.fileno() == -1
    assert calls.count("read-DOCUMENT") == 1
    assert calls.count("read-QUERY") == (10 if ordinal == 1 else 0)
    assert len(observed[0].queries) == (10 if ordinal == 1 else 0)
    assert all(t.end_to_end_ns >= t.authorization_ns + t.encode_ns for t in observed[0].queries)
    if late_ack_delay:
        cold_authorization = next(span for span in authorization_spans if span[0] == "COLD_READY")
        assert observed[0].cold_completed_ns <= cold_authorization[1]
        assert all(t.authorization_ns < 1_000_000_000 for t in observed[0].queries)
        prepared = [span for span in authorization_spans if span[0] == "QUERY_PREPARED"]
        ready = [span for span in authorization_spans if span[0] == "QUERY_READY"]
        assert all(
            t.end_to_end_ns < after[2] - before[1]
            for t, before, after in zip(observed[0].queries, prepared, ready, strict=True)
        )


def test_terminal_send_does_not_race_root_unlink_or_imply_cleanup(tmp_path):
    value = object.__new__(CapturedBenchmarkNativeConnection)
    value.listener = BenchmarkUnixPeer(1, 0, 0)
    value._writer_may_exit = True
    value._path = tmp_path / "already-unlinked"
    value.peer_fence(value.listener)
    with pytest.raises(ValueError, match="LISTENER_CHANGED"):
        value.peer_fence(BenchmarkUnixPeer(2, 0, 0))
