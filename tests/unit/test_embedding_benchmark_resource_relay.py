"""Real Unix framing/peer waits; root/GPU/Identity positive fixtures are explicitly synthetic."""

import os
import socket
import struct
import threading
import time
from itertools import pairwise
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkResourceEvidence,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service import embedding_benchmark_resource_relay as root_module
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)
from eom_catalog_service.embedding_benchmark_handoff import PreparedBenchmarkEnvironment
from eom_catalog_service.embedding_benchmark_resource_relay import RootBenchmarkGpuResourceRelay
from eom_orchestrator import embedding_benchmark_gpu_resource_client as owner_module
from eom_orchestrator.embedding_benchmark_gpu_resource_client import OwnerBenchmarkGpuResourceClient
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization

from tests.unit.embedding_device_benchmark_fixtures import resources, session, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_channel import local_resources


def actual_peer():
    return BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())


def endpoint(connection, *, tick=None, expires=None):
    return BenchmarkResourceChannel(
        connection,
        worker_invocation(2),
        expected_peer=actual_peer(),
        peer_fence=lambda value: None if value == actual_peer() else pytest.fail("wrong peer"),
        expires_ns=expires or time.monotonic_ns() + 3 * 10**9,
        wait_observer=tick,
    )


def test_real_unix_resource_roundtrip_samples_on_waiting_control_thread():
    left, right = socket.socketpair()
    ticks, errors = [], []
    owner = endpoint(left)
    root = endpoint(right, tick=lambda: ticks.append((threading.get_ident(), time.monotonic())))
    observed = []

    def serve():
        try:
            observed.append(root.receive_resources())
            root.send_resources(resources(2))
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            root.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        time.sleep(0.65)  # Model-free idle socket proves the actual blocking-wait seam.
        owner.send_resources(local_resources(2))
        assert owner.receive_resources() == resources(2)
    finally:
        owner.close()
        thread.join(timeout=4)
    assert not thread.is_alive() and not errors and observed == [local_resources(2)]
    assert len(ticks) >= 2 and {value[0] for value in ticks} == {thread.ident}
    assert all(b[1] - a[1] < 1 for a, b in pairwise(ticks))


@pytest.mark.parametrize("side", ("send", "receive"))
def test_duplicate_resource_exchange_poison_closes_original_descriptor(side):
    left, right = socket.socketpair()
    sender, receiver = endpoint(left), endpoint(right)
    try:
        sender.send_resources(local_resources(2))
        receiver.receive_resources()
        with pytest.raises(ValueError):
            if side == "send":
                sender.send_resources(local_resources(2))
            else:
                receiver.receive_resources()
        assert (left if side == "send" else right).fileno() == -1
    finally:
        sender.close()
        receiver.close()


@pytest.mark.parametrize("fault", ("foreign", "checkpoint", "oversize", "empty", "eof"))
def test_invalid_resource_frames_never_become_a_successful_root_exchange(fault):
    left, right = socket.socketpair()
    receiver = endpoint(right)
    try:
        if fault == "eof":
            left.close()
        elif fault in {"oversize", "empty"}:
            left.sendall(struct.pack("!I", 65537 if fault == "oversize" else 0))
        else:
            value = resources(3) if fault == "foreign" else session(2).checkpoints[0]
            raw = embedding_device_benchmark_bytes(value)
            left.sendall(struct.pack("!I", len(raw)) + raw)
        with pytest.raises(BenchmarkChannelError, match="RESOURCE_RECEIVE_FAILED"):
            receiver.receive_resources()
        assert right.fileno() == -1
    finally:
        left.close()
        receiver.close()


def test_sampling_failure_poison_closes_without_retry():
    left, right = socket.socketpair()
    calls = []

    def denied():
        calls.append(1)
        raise ValueError("synthetic root observation unavailable")

    receiver = endpoint(right, tick=denied)
    try:
        with pytest.raises(ValueError, match="RESOURCE_RECEIVE_FAILED"):
            receiver.receive_resources()
        with pytest.raises(ValueError):
            receiver.receive_resources()
        assert calls == [1] and right.fileno() == -1
    finally:
        left.close()
        receiver.close()


def test_observation_ticks_do_not_renew_absolute_deadline():
    left, right = socket.socketpair()
    ticks = []
    receiver = endpoint(
        right, tick=lambda: ticks.append(1), expires=time.monotonic_ns() + 100_000_000
    )
    started = time.monotonic()
    try:
        with pytest.raises(ValueError):
            receiver.receive_resources()
        assert time.monotonic() - started < 0.6 and ticks and right.fileno() == -1
    finally:
        left.close()
        receiver.close()


def test_actual_wrong_peer_is_rejected_by_kernel_credentials_and_socket_is_owned():
    left, right = socket.socketpair()
    peer = actual_peer()
    try:
        with pytest.raises(ValueError):
            BenchmarkResourceChannel(
                right,
                worker_invocation(2),
                expected_peer=BenchmarkUnixPeer(peer.pid + 1, peer.uid, peer.gid),
                peer_fence=lambda _: None,
                expires_ns=time.monotonic_ns() + 10**9,
            )
        assert right.fileno() == -1
    finally:
        left.close()
        right.close()


class SyntheticResourceChannel:
    def __init__(
        self, connection, invocation, *, expected_peer, peer_fence, expires_ns, wait_observer=None
    ):
        self.received, self.sent, self.closed = local_resources(2), [], False
        self.tick = wait_observer
        self.peer, self.fence = expected_peer, peer_fence
        self.fence(self.peer)

    def receive_resources(self):
        self.fence(self.peer)
        if self.tick is not None:
            self.tick()
            self.tick()
        return self.received

    def send_resources(self, value):
        self.fence(self.peer)
        if self.tick is not None:
            self.tick()
        self.sent.append(value)

    def close(self):
        self.closed = True


def test_concrete_root_relay_uses_one_observer_and_never_manufactures_counters(monkeypatch):
    invocation = worker_invocation(2)
    environment = PreparedBenchmarkEnvironment(
        invocation.execution_id,
        invocation.job_id,
        "sha256:" + "a" * 64,
        os.getpid(),
        1,
        time.monotonic_ns() + 10**9,
    )
    made = []

    class SyntheticObserver:
        def __init__(self, *args, **kwargs):
            self.samples = 1
            self.state = "OPEN"
            made.append(self)

        def sample(self):
            self.samples += 1

        def finalize(self, local):
            assert local == local_resources(2)
            self.state = "FROZEN"
            return resources(2)

        def observed_peaks(self):
            return SimpleNamespace(state=self.state)

    monkeypatch.setattr(root_module.os, "getresuid", lambda: (0, 0, 0))
    monkeypatch.setattr(
        root_module.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=990, pw_gid=1000)
    )
    monkeypatch.setattr(root_module, "benchmark_owner_start_ticks", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        root_module, "observe_benchmark_cuda_ready", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(root_module, "BenchmarkGpuMemoryObserver", SyntheticObserver)
    monkeypatch.setattr(root_module, "BenchmarkResourceChannel", SyntheticResourceChannel)
    relay = RootBenchmarkGpuResourceRelay(
        None, invocation, environment, backend=None, inventory=None, host=None
    )
    assert relay.serve() == resources(2)
    assert len(made) == 1 and made[0].samples == 3 and relay._channel.closed
    with pytest.raises(ValueError, match="ALREADY_USED"):
        relay.serve()
    assert len(made) == 1


def test_root_relay_denies_actual_nonroot_before_kernel_observation(monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("actual nonroot process required")

    def forbidden(*args, **kwargs):
        pytest.fail("root observer must not run")

    monkeypatch.setattr(root_module, "observe_benchmark_cuda_ready", forbidden)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        RootBenchmarkGpuResourceRelay(
            None, worker_invocation(2), None, backend=None, inventory=None, host=None
        )


def test_resource_client_denies_actual_wrong_os_owner_before_frame_or_auth(monkeypatch):
    from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity

    expected = fixed_owner_identity()
    if os.getresuid() == (expected.owner_uid,) * 3 and os.getresgid() == (expected.owner_gid,) * 3:
        pytest.skip("actual non-owner process required")

    def forbidden(*args, **kwargs):
        pytest.fail("no resource frame may be opened")

    monkeypatch.setattr(owner_module, "BenchmarkResourceChannel", forbidden)
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        OwnerBenchmarkGpuResourceClient(
            None, None, root_peer=None, authorization=None, expires_ns=0
        )


@pytest.mark.parametrize("fault", ("none", "before", "after", "root_result", "alias", "late_alias"))
def test_owner_client_preserves_current_original_invocation_and_root_only_fields(
    monkeypatch, fault
):
    invocation = worker_invocation(2)
    checks = []
    local = local_resources(2)
    original_rss = local.peak_rss_bytes
    monkeypatch.setattr(
        owner_module, "fixed_owner_identity", lambda: SimpleNamespace(owner_uid=990, owner_gid=1000)
    )
    monkeypatch.setattr(owner_module.os, "getresuid", lambda: (990, 990, 990))
    monkeypatch.setattr(owner_module.os, "getresgid", lambda: (1000, 1000, 1000))
    monkeypatch.setattr(owner_module, "BenchmarkResourceChannel", SyntheticResourceChannel)

    def authorize(self, value):
        checks.append(value)
        if fault == "late_alias":
            object.__setattr__(local, "peak_rss_bytes", original_rss + 1)
        if (fault == "before" and len(checks) == 1) or (fault == "after" and len(checks) == 2):
            raise ValueError("synthetic source revoked")

    monkeypatch.setattr(BenchmarkLaunchAuthorization, "assert_invocation", authorize)
    authorizer = object.__new__(BenchmarkLaunchAuthorization)
    client = OwnerBenchmarkGpuResourceClient(
        None,
        invocation,
        root_peer=BenchmarkUnixPeer(1, 0, 0),
        authorization=authorizer,
        expires_ns=time.monotonic_ns() + 10**9,
    )
    client._channel.received = resources(2)
    if fault == "root_result":
        body = resources(2).model_dump(mode="json")
        body["peak_rss_bytes"] += 1
        client._channel.received = BenchmarkResourceEvidence.model_validate(
            seal(body, "resource_sha256")
        )
    elif fault == "alias":
        body = local_resources(2).model_dump(mode="json")
        body.update(
            peak_whole_device_gpu_bytes=1, peak_whole_process_gpu_bytes=1, owner_observation_count=1
        )
        local = BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))
    if fault in {"none", "late_alias"}:
        assert client.finalize(local) == resources(2)
        assert checks == [invocation, invocation]
        assert client._channel.sent[0].peak_rss_bytes == original_rss
    else:
        with pytest.raises(ValueError):
            client.finalize(local if fault == "alias" else local_resources(2))
    assert client._channel.closed
    with pytest.raises(ValueError, match="ALREADY_USED"):
        client.finalize(local_resources(2))
