"""Synthetic encoder/owner/OOM captures over local real FDs; no installed admission or GPU."""

from __future__ import annotations

import os
import resource
import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkCheckpoint,
    BenchmarkResourceEvidence,
    BenchmarkWorkerInvocation,
    benchmark_checkpoint_count,
    benchmark_sample_program,
    parse_embedding_device_benchmark_bytes,
)
from eom_catalog_contracts.inference_transfer_embedding import EmbeddingExecutionRuntime
from eom_catalog_service import embedding_benchmark_entrypoint as native_entry
from eom_catalog_service import embedding_benchmark_host_memory as host_memory
from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkOwnerChannel,
    BenchmarkUnixPeer,
    BenchmarkWorkerChannel,
)
from eom_catalog_service.embedding_device_benchmark_worker import (
    BenchmarkWorkerError,
    run_embedding_device_benchmark,
)
from eom_catalog_service.embedding_execution_ports import (
    BenchmarkHostObservationError,
    BenchmarkNativeEmbeddingBackend,
    NativeAllocatorPeaks,
    NativeObservedEncoding,
    NativeTokenBatchObservation,
    NativeTokenRejection,
    NativeTokenRowObservation,
)
from eom_catalog_service.embedding_native_factory import NativeEmbeddingFactoryError
from eom_catalog_service.embedding_offline_backend import NativeEmbeddingBackendError
from eom_catalog_service.inference_transfer_ports import EmbeddingRankerProvenance
from eom_identifiers import content_sha256

from tests.unit.embedding_device_benchmark_fixtures import staged_inputs, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_device_benchmark_files import stage_files


class FakeBackend:
    def __init__(self, invocation: BenchmarkWorkerInvocation, events: list[str]) -> None:
        self.invocation, self.events = invocation, events
        self.dimension, self.batch_size, self.threads = 1024, 4, 4
        self.provenance = EmbeddingRankerProvenance(
            "PINNED_MODEL", invocation.runtime.spaces.document.model_spec
        )
        self.execution_runtime = EmbeddingExecutionRuntime(
            device=invocation.device,
            execution_runtime_sha256=invocation.runtime.numerical_runtime.runtime_sha256,
        )
        self.calls: list[tuple[tuple[str, ...], str]] = []
        self.closed = False
        self.bad_token = False
        self.left_padding = False
        self.forward_failure_at = 0
        self.ooms: Any = 0
        self.on_encode: Callable[[], None] = lambda: None
        self.ids = (
            {
                row.text: row.token_count
                for row in (*staged_inputs().documents, *staged_inputs().queries)
            }
            | {case.text: case.token_count for case in staged_inputs().synthetic_cases}
            | {staged_inputs().capacity.text: 2048}
        )

    def encode(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> tuple[tuple[float, ...], ...]:
        return self.encode_observed(texts, purpose=purpose).vectors

    def encode_observed(
        self, texts: tuple[str, ...], *, purpose: Literal["QUERY", "DOCUMENT"]
    ) -> NativeObservedEncoding:
        assert not self.closed
        self.events.append("encode-" + purpose)
        self.calls.append((texts, purpose))
        self.on_encode()
        if self.forward_failure_at == len(self.calls):
            raise NativeEmbeddingBackendError("NATIVE_EMBEDDING_INFERENCE_FAILED")
        counts = tuple(self.ids[text] for text in texts)
        text_hashes = tuple(content_sha256(text) for text in texts)
        if not any(texts):
            raise NativeEmbeddingBackendError(
                "NATIVE_EMBEDDING_INPUT_INVALID",
                token_rejection=NativeTokenRejection("EMPTY", text_hashes, None, None),
            )
        if max(counts) > 2048:
            hashes = tuple(
                content_sha256(
                    {"input_ids": [101] + [42] * (count - 2) + [102], "token_type_ids": None}
                )
                for count in counts
            )
            raise NativeEmbeddingBackendError(
                "NATIVE_EMBEDDING_INPUT_TOO_LONG",
                token_rejection=NativeTokenRejection("OVERFLOW", text_hashes, counts, hashes),
            )
        batches = []
        for offset in range(0, len(texts), 4):
            selected = counts[offset : offset + 4]
            maximum = max(selected)
            rows = []
            for index, count in enumerate(selected, offset):
                ids = (101,) + (42,) * (count - 2) + (102,)
                pad = (0,) * (maximum - count)
                mask = (1,) * count
                rows.append(
                    NativeTokenRowObservation(
                        text_hashes[index],
                        pad + ids if self.left_padding else ids + pad,
                        (0,) * len(pad) + mask if self.left_padding else mask + (0,) * len(pad),
                        None,
                        count,
                        "sha256:" + "f" * 64
                        if self.bad_token
                        else content_sha256({"input_ids": ids, "token_type_ids": None}),
                    )
                )
            batches.append(
                NativeTokenBatchObservation(
                    purpose, 0, "left" if self.left_padding else "right", tuple(rows)
                )
            )
        return NativeObservedEncoding(((1.0,) + (0.0,) * 1023,) * len(texts), tuple(batches))

    def synchronize(self) -> None:
        assert not self.closed
        self.events.append("sync")

    def allocator_peaks(self) -> NativeAllocatorPeaks:
        assert not self.closed
        self.events.append("allocator")
        return (
            NativeAllocatorPeaks(1024, 2048)
            if self.invocation.device == "CUDA"
            else NativeAllocatorPeaks(None, None)
        )

    def cuda_oom_count(self) -> int | None:
        assert not self.closed
        self.events.append("cuda-oom")
        value: int = self.ooms
        return value if self.invocation.device == "CUDA" else None


class HostObserver:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.count: Any = 0

    def observe_delta(self) -> int:
        self.events.append("host-oom")
        value: int = self.count
        return value


def peer() -> BenchmarkUnixPeer:
    return BenchmarkUnixPeer(os.getpid(), os.getuid(), os.getgid())


def finalized(local: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
    body = local.model_dump(mode="json")
    if local.device == "CUDA":
        body.update(
            peak_whole_process_gpu_bytes=4096,
            peak_whole_device_gpu_bytes=8192,
            owner_observation_count=2,
        )
        for capacity in body["capacity_samples"]:
            capacity["peak_whole_process_gpu_bytes"] = 4096
    return BenchmarkResourceEvidence.model_validate(seal(body, "resource_sha256"))


def run_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ordinal: int = 1,
    *,
    fault: str = "",
    deadline_seconds: int = 30,
) -> tuple[Any, FakeBackend, list[str], Path, list[BenchmarkCheckpoint]]:
    files, root, borrowed = stage_files(tmp_path, monkeypatch, ordinal)
    events: list[str] = []
    backend = FakeBackend(worker_invocation(ordinal), events)
    host = HostObserver(events)
    if fault == "native_entry":

        @contextmanager
        def quiet() -> Iterator[None]:
            yield

        monkeypatch.setattr(native_entry, "discard_native_embedding_diagnostics", quiet)
        monkeypatch.setattr(native_entry, "require_native_embedding_identity", lambda _: None)
        monkeypatch.setattr(host_memory, "OwnBenchmarkHostOomObserver", lambda **_: host)
    synthetic_clock = [time.perf_counter_ns()]
    if fault == "clock":

        def perf_counter() -> int:
            synthetic_clock[0] += 1000
            return synthetic_clock[0]

        monkeypatch.setattr(time, "perf_counter_ns", perf_counter)
    if fault == "token":
        backend.bad_token = True
    elif fault == "padding":
        backend.left_padding = True
    elif fault == "runtime":
        backend.threads = 3
    elif fault == "encode":
        backend.forward_failure_at = 2
    elif fault == "host_bool":
        host.count = True
    elif fault == "cuda_bool":
        backend.ooms = True
    elif fault == "oom_counts":
        host.count, backend.ooms = 1, 2
    elif fault == "rss":
        monkeypatch.setattr(
            resource, "getrusage", lambda _who: type("Usage", (), {"ru_maxrss": True})()
        )
    elif fault == "capture":
        files._raw_pin = "sha256:" + "f" * 64
    elif fault == "cuda_preentered":
        from tests.unit.test_embedding_benchmark_cuda_files import ready_for_process

        ready_path = root / "cuda-ready.json"
        ready_path.touch(mode=0o640)
        ready_path.chmod(0o640)
        files.__enter__()
        files.write_cuda_ready(ready_for_process(monkeypatch))

    @contextmanager
    def scope() -> Iterator[BenchmarkNativeEmbeddingBackend]:
        events.append("constructor")
        if fault == "clock":
            synthetic_clock[0] += 7_000_000
        try:
            if fault == "constructor":
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_FACTORY_RUNTIME_MISMATCH")
            yield backend
        finally:
            events.append("close")
            backend.closed = True
            if fault == "close":
                raise NativeEmbeddingFactoryError("NATIVE_EMBEDDING_FACTORY_TEARDOWN_UNCERTAIN")

    left, right = socket.socketpair()
    deadline = time.monotonic_ns() + deadline_seconds * 10**9
    invocation = worker_invocation(ordinal)
    checkpoints: list[BenchmarkCheckpoint] = []
    owner_errors: list[str] = []

    def fence(value: BenchmarkUnixPeer) -> None:
        assert value == peer()

    def continuation(value: BenchmarkCheckpoint) -> None:
        events.append("ack-" + value.phase)
        if fault == "clock":
            synthetic_clock[0] += 50_000_000
        assert (
            (root / "outputs" / value.vector.member_name).stat().st_size == value.vector.byte_count
            if value.vector is not None
            else True
        )
        if fault == "revoked" and value.phase == "QUERY_PREPARED":
            raise ValueError("synthetic revoked current authorization")

    worker = BenchmarkWorkerChannel(
        left,
        worker_invocation(4) if fault == "channel_capture" else invocation,
        expected_peer=peer(),
        peer_fence=fence,
        expires_ns=deadline,
    )
    owner = BenchmarkOwnerChannel(
        right,
        invocation,
        expected_peer=peer(),
        peer_fence=fence,
        continuation_fence=continuation,
        expires_ns=deadline,
    )

    def owner_run() -> None:
        try:
            for _ in range(benchmark_checkpoint_count(invocation)):
                checkpoint = owner.receive_checkpoint()
                checkpoints.append(checkpoint)
                owner.acknowledge()

            def finalizer(value: BenchmarkResourceEvidence) -> BenchmarkResourceEvidence:
                assert backend.closed and events.index("close") < len(events)
                events.append("resource-finalizer")
                if fault == "resource":
                    raise ValueError("synthetic unavailable independent monitor")
                return finalized(value)

            owner.finalize_resources(finalizer=finalizer)
        except ValueError:
            owner_errors.append("stopped")
        finally:
            owner.close()

    thread = threading.Thread(target=owner_run)
    thread.start()
    result: Any
    try:
        try:
            if fault == "native_entry":
                result = native_entry.run_native_embedding_benchmark(
                    files,
                    scope,
                    worker,
                    profile=files.profile,
                    entry_started_ns=time.perf_counter_ns() - 1_000_000,
                    expires_ns=deadline,
                )
            else:
                result = run_embedding_device_benchmark(
                    files,
                    scope,
                    worker,
                    entry_started_ns=time.perf_counter_ns() - 1_000_000,
                    expires_ns=deadline,
                    host_oom_observer=host,
                )
        except BenchmarkWorkerError as error:
            if fault != "capture":
                raise
            result = error
    finally:
        worker.close()
        thread.join(timeout=3)
        owner.close()
        os.close(borrowed)
    assert not thread.is_alive()
    return result, backend, events, root, checkpoints


def test_constructor_and_encode_clock_spans_exclude_owner_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _, _, _, _ = run_scenario(tmp_path, monkeypatch, 1, fault="clock")
    assert result.timings.load_hash_ns == 7_001_000
    assert result.timings.cold_encode_ns == 1000
    assert result.timings.warm_encode_ns == (1000,) * 5
    assert tuple(value.encode_ns for value in result.timings.query_encode_ns) == (1000,) * 10
    # Fifty-ms synthetic waits never become worker encode ns or substitute owner E2E spans.


def test_untrusted_raw_capture_never_enters_factory_or_emits_a_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    error, backend, events, root, checkpoints = run_scenario(
        tmp_path, monkeypatch, 4, fault="capture"
    )
    assert isinstance(error, BenchmarkWorkerError) and not backend.closed
    assert "constructor" not in events and not checkpoints
    assert (root / "outputs/worker-result.json").stat().st_size == 0


def test_direct_linux_rss_requires_exact_observation_not_bool_estimate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, backend, events, _, _ = run_scenario(tmp_path, monkeypatch, 4, fault="rss")
    assert result.status == "FAILED" and result.reason_codes == ("BENCHMARK_WORKER_RSS_INVALID",)
    assert backend.closed and "resource-finalizer" not in events


@pytest.mark.parametrize("ordinal", range(1, 7))
def test_fixed_six_source_programs_have_exact_evidence_and_genuine_query_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ordinal: int
) -> None:
    result, backend, events, root, checkpoints = run_scenario(tmp_path, monkeypatch, ordinal)
    assert result.status == "COMPLETED" and backend.closed
    assert tuple(sample.key for sample in result.vectors) == benchmark_sample_program(ordinal)
    assert len(checkpoints) == (21 if ordinal in (1, 2) else 1)
    assert (
        events.index("ack-COLD_READY") < events.index("close") < events.index("resource-finalizer")
    )
    assert len(backend.calls) == (35 if ordinal in (1, 2) else 1)
    assert sum(purpose == "QUERY" for _, purpose in backend.calls) == (
        10 if ordinal in (1, 2) else 0
    )
    if ordinal in (1, 2):
        assert len(result.synthetic_rejections) == 4 and result.timings.warmup_count == 1
        assert all(
            sample.peak_whole_process_gpu_bytes == (4096 if result.device == "CUDA" else None)
            for sample in result.resources.capacity_samples
        )
        prepared = [index for index, value in enumerate(events) if value == "ack-QUERY_PREPARED"]
        encoded = [index for index, value in enumerate(events) if value == "encode-QUERY"]
        ready = [index for index, value in enumerate(events) if value == "ack-QUERY_READY"]
        assert len(prepared) == 10 and all(
            a < b < c for a, b, c in zip(prepared, encoded, ready, strict=True)
        )
    raw = (root / "outputs/worker-result.json").read_bytes()
    assert parse_embedding_device_benchmark_bytes(raw) == result
    assert len(list((root / "outputs").iterdir())) == (16 if ordinal in (1, 2) else 4)


@pytest.mark.parametrize(
    "fault",
    (
        "token",
        "padding",
        "runtime",
        "encode",
        "constructor",
        "close",
        "revoked",
        "resource",
        "host_bool",
        "cuda_bool",
    ),
)
def test_failed_source_program_preserves_only_real_sealed_prefix_without_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    result, backend, events, root, checkpoints = run_scenario(tmp_path, monkeypatch, 2, fault=fault)
    assert result.status == "FAILED" and result.reason_codes
    assert backend.closed == (fault != "host_bool")
    if fault in ("token", "padding", "runtime", "constructor", "host_bool", "cuda_bool"):
        assert result.vectors == () and checkpoints == []
    if fault in (
        "token",
        "padding",
        "runtime",
        "encode",
        "constructor",
        "close",
        "revoked",
        "host_bool",
        "cuda_bool",
    ):
        assert "resource-finalizer" not in events
    if fault == "host_bool":
        assert "constructor" not in events
    assert (root / "outputs/worker-result.json").stat().st_size > 0


def test_resource_oom_counts_are_actual_distinct_host_plus_allocator_not_gate_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _, _, _, _ = run_scenario(tmp_path, monkeypatch, 3, fault="oom_counts")
    assert result.status == "COMPLETED" and result.resources.oom_count == 3
    # Leaf completion preserves failing observations; owner decides OOM=0 gate separately.


def test_host_observation_failure_preserves_specific_code_and_cannot_be_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def killed(_self: HostObserver) -> int:
        raise BenchmarkHostObservationError("BENCHMARK_HOST_OOM_KILL_DETECTED")

    monkeypatch.setattr(HostObserver, "observe_delta", killed)
    result, _, events, root, _ = run_scenario(tmp_path, monkeypatch, 3)
    assert result.status == "FAILED"
    assert result.reason_codes == ("BENCHMARK_HOST_OOM_KILL_DETECTED",)
    assert "constructor" not in events
    assert (root / "outputs/worker-result.json").stat().st_size > 0


def test_native_library_composition_runs_same_full_worker_program_over_real_local_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, backend, _, root, checkpoints = run_scenario(
        tmp_path, monkeypatch, 1, fault="native_entry"
    )
    assert result.status == "COMPLETED" and backend.closed
    assert len(checkpoints) == 21
    assert (root / "outputs/worker-result.json").stat().st_size > 0
    # Identity/host capture and numerical backend are synthetic, not production admission.


def test_cuda_full_program_accepts_leaf_sealed_capture_without_second_context_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, backend, events, root, checkpoints = run_scenario(
        tmp_path, monkeypatch, 2, fault="cuda_preentered"
    )
    assert result.status == "COMPLETED" and backend.closed
    assert len(checkpoints) == benchmark_checkpoint_count(worker_invocation(2))
    assert "constructor" in events and "resource-finalizer" in events
    assert (root / "cuda-ready.json").stat().st_size > 0
    assert (root / "outputs/worker-result.json").stat().st_size > 0
    # Actual file/socket ownership is synthetic; this is no GPU/model/admission claim.


def test_foreign_channel_invocation_fails_before_backend_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _, events, _, checkpoints = run_scenario(
        tmp_path, monkeypatch, 3, fault="channel_capture"
    )
    assert result.status == "FAILED"
    assert result.reason_codes == ("EMBEDDING_BENCHMARK_INITIAL_INVOCATION_INVALID",)
    assert "constructor" not in events and not checkpoints


@pytest.mark.parametrize("case", ("host", "clock", "deadline"))
def test_missing_host_capture_and_invalid_clocks_cleanup_without_constructor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    files, _, borrowed = stage_files(tmp_path, monkeypatch, 4)
    left, right = socket.socketpair()
    worker = BenchmarkWorkerChannel(
        left,
        worker_invocation(4),
        expected_peer=peer(),
        peer_fence=lambda value: None,
        expires_ns=time.monotonic_ns() + 10**9,
    )

    def forbidden() -> Any:
        pytest.fail("missing capture must not construct")

    try:
        with pytest.raises(BenchmarkWorkerError, match="CAPTURE_INVALID"):
            observer: Any = None if case == "host" else HostObserver([])
            run_embedding_device_benchmark(
                files,
                forbidden,
                worker,
                entry_started_ns=True if case == "clock" else time.perf_counter_ns() - 1_000_000,
                expires_ns=True if case == "deadline" else time.monotonic_ns() + 10**9,
                host_oom_observer=observer,
            )
        assert left.fileno() == -1
        assert os.fstat(borrowed).st_size > 0
    finally:
        files.close()
        worker.close()
        right.close()
        os.close(borrowed)
