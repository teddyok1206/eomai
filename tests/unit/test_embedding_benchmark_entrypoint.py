"""Synthetic library-composition ordering; not installed admission or a model/device run."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkExecutionPolicy,
    BenchmarkWorkerInvocation,
)
from eom_catalog_service import embedding_benchmark_channel as channels
from eom_catalog_service import embedding_benchmark_entrypoint as entry
from eom_catalog_service import embedding_benchmark_host_memory as host_memory
from eom_catalog_service import embedding_device_benchmark_files as local_files
from eom_catalog_service import embedding_device_benchmark_worker as worker

from tests.unit.embedding_device_benchmark_fixtures import benchmark_policy, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_host_memory import kernel as kernel
from tests.unit.test_embedding_device_benchmark_budget import successor_invocation, successor_policy


@pytest.mark.parametrize("profile", ("CPU_INDEX_FP32", "CUDA_INDEX_FP32"))
@pytest.mark.parametrize("policy", (benchmark_policy(), successor_policy()))
@pytest.mark.parametrize(
    "failure",
    (None, "identity", "profile", "channel", "host", "worker", "files_close", "channel_close"),
)
def test_identity_host_capture_backend_order_and_cleanup_of_both_resources(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    policy: BenchmarkExecutionPolicy,
    failure: str | None,
) -> None:
    events: list[str] = []

    class Files:
        execution_id = "a" * 32

        def __init__(self) -> None:
            self.profile = "WRONG" if failure == "profile" else profile

        def close(self) -> None:
            events.append("files-close")
            if failure == "files_close":
                raise ValueError("synthetic local cleanup failure")

    class Channel:
        execution_policy = policy

        def close(self) -> None:
            events.append("channel-close")
            if failure == "channel_close":
                raise ValueError("synthetic channel cleanup failure")

    class ForeignChannel(Channel):
        pass

    files = Files()
    channel = ForeignChannel() if failure == "channel" else Channel()
    result = SimpleNamespace(status="COMPLETED")
    captured_host = object()

    @contextmanager
    def quiet() -> Iterator[None]:
        events.append("quiet")
        yield

    def identity(value: str) -> None:
        assert value == profile
        events.append("identity")
        if failure == "identity":
            raise ValueError("synthetic identity denial")

    def capture(*, device: str, execution_id: str, policy: BenchmarkExecutionPolicy) -> object:
        events.append("host-capture")
        assert device == ("CPU" if profile == "CPU_INDEX_FP32" else "CUDA")
        assert execution_id == files.execution_id
        assert policy is channel.execution_policy
        if failure == "host":
            raise ValueError("synthetic membership denial")
        return captured_host

    def scope() -> Any:
        pytest.fail("only the existing worker may enter the captured backend scope")

    def run(actual_files: Any, actual_scope: Any, actual_channel: Any, **kwargs: Any) -> Any:
        events.append("worker")
        assert actual_files is files and actual_scope is scope and actual_channel is channel
        assert kwargs == {
            "entry_started_ns": 123,
            "expires_ns": 456,
            "host_oom_observer": captured_host,
        }
        if failure == "worker":
            raise ValueError("synthetic worker failure")
        return result

    monkeypatch.setattr(entry, "discard_native_embedding_diagnostics", quiet)
    monkeypatch.setattr(entry, "require_native_embedding_identity", identity)
    monkeypatch.setattr(local_files, "BenchmarkWorkerLocalFiles", Files)
    monkeypatch.setattr(channels, "BenchmarkWorkerChannel", Channel)
    monkeypatch.setattr(host_memory, "OwnBenchmarkHostOomObserver", capture)
    monkeypatch.setattr(worker, "run_embedding_device_benchmark", run)
    if failure is None:
        assert (
            entry.run_native_embedding_benchmark(
                files, scope, channel, profile=profile, entry_started_ns=123, expires_ns=456
            )
            is result
        )
    else:
        with pytest.raises(entry.NativeEmbeddingEntrypointError):
            entry.run_native_embedding_benchmark(
                files, scope, channel, profile=profile, entry_started_ns=123, expires_ns=456
            )
    prefix = ["quiet", "identity", "host-capture", "worker"]
    count = {"identity": 2, "profile": 2, "channel": 2, "host": 3}.get(failure or "", 4)
    assert events == [*prefix[:count], "files-close", "channel-close"]


@pytest.mark.parametrize("invocation", (worker_invocation(), successor_invocation()))
def test_worker_channel_exposes_only_its_validated_read_only_policy(invocation: Any) -> None:
    connection, owner = socket.socketpair()
    with connection, owner:
        channel = channels.BenchmarkWorkerChannel(
            connection,
            invocation,
            expected_peer=channels.BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid()),
            peer_fence=lambda _: None,
            expires_ns=time.monotonic_ns() + 30 * 10**9,
        )
        try:
            assert channel.execution_policy == invocation.execution_policy
            with pytest.raises(AttributeError):
                channel.execution_policy = benchmark_policy()
            assert channel.execution_policy == invocation.execution_policy
        finally:
            channel.close()


@pytest.mark.parametrize("kernel", (("CPU", 600), ("CUDA", 600)), indirect=True)
@pytest.mark.parametrize("fault", (None, "legacy-policy", "unknown-family"))
def test_entrypoint_binds_real_host_observer_to_actual_channel_policy_before_worker(
    kernel: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    ordinal = 1 if kernel["device"] == "CPU" else 2
    original = (
        worker_invocation(ordinal) if fault == "legacy-policy" else successor_invocation(ordinal)
    )
    body = original.model_dump(mode="json") | {"execution_id": "a" * 32}
    invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    profile = invocation.runtime.profile
    events: list[str] = []

    class Files:
        execution_id = invocation.execution_id

        def __init__(self) -> None:
            self.profile = profile

        def close(self) -> None:
            events.append("files-close")

    @contextmanager
    def quiet() -> Iterator[None]:
        yield

    def run(*_args: Any, **kwargs: Any) -> Any:
        events.append("worker")
        assert kwargs["host_oom_observer"].observe_delta() == 0
        return result

    def scope() -> Any:
        pytest.fail("synthetic composition test must not enter a backend")

    if fault == "unknown-family":
        kernel["cgroup"] = kernel["cgroup"].replace(b"-budget600@", b"-budget900@")
    monkeypatch.setattr(entry, "discard_native_embedding_diagnostics", quiet)
    monkeypatch.setattr(entry, "require_native_embedding_identity", lambda _: None)
    monkeypatch.setattr(local_files, "BenchmarkWorkerLocalFiles", Files)
    monkeypatch.setattr(worker, "run_embedding_device_benchmark", run)
    result = object()
    connection, owner = socket.socketpair()
    with connection, owner:
        channel = channels.BenchmarkWorkerChannel(
            connection,
            invocation,
            expected_peer=channels.BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid()),
            peer_fence=lambda _: None,
            expires_ns=time.monotonic_ns() + 30 * 10**9,
        )
        if fault is None:
            assert (
                entry.run_native_embedding_benchmark(
                    Files(), scope, channel, profile=profile, entry_started_ns=123, expires_ns=456
                )
                is result
            )
            assert events == ["worker", "files-close"]
        else:
            with pytest.raises(entry.NativeEmbeddingEntrypointError):
                entry.run_native_embedding_benchmark(
                    Files(), scope, channel, profile=profile, entry_started_ns=123, expires_ns=456
                )
            assert events == ["files-close"] and kernel["read_count"] == 0
        assert connection.fileno() == -1


def test_fresh_library_import_is_stdlib_only_and_grants_no_production_main() -> None:
    code = (
        "import sys; import eom_catalog_service.embedding_benchmark_entrypoint as entry; "
        "assert not hasattr(entry,'main'); "
        "assert not any(n in sys.modules for n in "
        "('pydantic','torch','transformers','eom_gpu_lease','sqlalchemy','eom_orchestrator'))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, check=False, timeout=30
    )
    assert completed.returncode == 0 and not completed.stdout and not completed.stderr
