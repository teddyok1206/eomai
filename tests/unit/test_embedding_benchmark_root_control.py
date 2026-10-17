"""Actual framed sockets; positive root, machine drivers and cleanup are synthetic."""

import os
import socket
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from eom_catalog_service import embedding_benchmark_root_control as root
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkResourceChannel,
    BenchmarkUnixPeer,
)
from eom_catalog_service.embedding_benchmark_control_channel import BenchmarkLaunchControlChannel
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_orchestrator.embedding_benchmark_launch_workspace import StagedOwnerBenchmarkLaunch

from tests.unit.embedding_benchmark_control_fixtures import association, prepared
from tests.unit.embedding_device_benchmark_fixtures import (
    owner_request,
    resources,
    staged_inputs,
    worker_invocation,
)
from tests.unit.test_embedding_benchmark_channel import local_resources


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_one_root_bridge_preserves_control_fd_across_cuda_resource_roundtrip(monkeypatch, ordinal):
    association_value = association(ordinal)
    invocation = worker_invocation(ordinal)
    pins = NativeEmbeddingBackendPins(**prepared(association_value).backend.model_dump(mode="json"))
    peer = BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())
    saved, launches = [], []
    monkeypatch.setattr(root, "require_root_benchmark_control", lambda: None)
    monkeypatch.setattr(
        root.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=peer.uid, pw_gid=peer.gid)
    )
    monkeypatch.setattr(root, "benchmark_owner_start_ticks", lambda *args, **kwargs: 1)
    monkeypatch.setattr(root, "prepare_benchmark_handoff", lambda *args: object())
    monkeypatch.setattr(
        root,
        "prepare_benchmark_environment",
        lambda *args, **kwargs: SimpleNamespace(
            owner_start_ticks=1, environment_raw_sha256="sha256:" + "a" * 64
        ),
    )
    monkeypatch.setattr(
        root, "_persist_root_control", lambda execution, name, raw: saved.append((name, raw))
    )

    class SyntheticDriver:
        def __init__(self, *args, **kwargs):
            self.duplicate = args[0] if invocation.device == "CUDA" else None

        def run(self):
            assert saved[0][0] == "root-prepared.json"
            launches.append(invocation.execution_id)
            if self.duplicate is not None:
                channel = BenchmarkResourceChannel(
                    self.duplicate,
                    invocation,
                    expected_peer=peer,
                    peer_fence=lambda _: None,
                    expires_ns=association_value.expires_ns,
                )
                try:
                    assert channel.receive_resources() == local_resources(ordinal)
                    channel.send_resources(resources(ordinal))
                finally:
                    channel.close()
            return SimpleNamespace(
                execution_id=invocation.execution_id,
                job_id=invocation.job_id,
                invocation_sha256=invocation.invocation_sha256,
                started_ns=100,
                completed_ns=200,
                outcome="SUCCEEDED",
                resources=resources(ordinal),
            )

    monkeypatch.setattr(root, "FixedRootBenchmarkCpuDriver", SyntheticDriver)
    monkeypatch.setattr(root, "FixedRootBenchmarkCudaDriver", SyntheticDriver)
    left, right = socket.socketpair()
    owner = BenchmarkLaunchControlChannel(
        left,
        association_value,
        side="OWNER",
        expected_peer=peer,
        peer_fence=lambda _: None,
        controller_release="a" * 40,
    )
    staged = StagedOwnerBenchmarkLaunch(
        association_value, owner_request(), invocation, staged_inputs()
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            root.serve_root_benchmark_launch,
            right,
            staged,
            selected_request_sha256=staged.request.request_sha256,
            backend=pins,
            controller_release="a" * 40,
            cuda=root.RootBenchmarkCudaRuntime(None, None),
        )
        try:
            owner.send_association()
            owner.receive_prepared()
            if invocation.device == "CUDA":
                with owner.resources() as duplicate:
                    channel = BenchmarkResourceChannel(
                        duplicate,
                        invocation,
                        expected_peer=peer,
                        peer_fence=lambda _: None,
                        expires_ns=association_value.expires_ns,
                    )
                    try:
                        channel.send_resources(local_resources(ordinal))
                        assert channel.receive_resources() == resources(ordinal)
                    finally:
                        channel.close()
            complete = owner.receive_completed()
            owner.close()
            assert complete == future.result(timeout=3)
            assert (
                complete.cleanup == "CONFIRMED"
            )  # Synthetic driver, not actual cleanup acceptance.
            assert [name for name, _ in saved] == ["root-prepared.json", "root-completion.json"]
            assert launches == [invocation.execution_id]
        finally:
            owner.close()


def test_actual_nonroot_is_rejected_before_staging(monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("requires actual nonroot")
    left, right = socket.socketpair()
    try:
        with pytest.raises(ValueError, match="ROOT_REQUIRED"):
            root.serve_root_benchmark_launch(
                right,
                None,
                selected_request_sha256="sha256:" + "a" * 64,
                backend=None,
                controller_release="a" * 40,
            )
        assert right.fileno() == -1
    finally:
        left.close()
        right.close()
