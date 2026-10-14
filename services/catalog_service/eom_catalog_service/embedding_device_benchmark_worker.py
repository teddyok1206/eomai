"""Fixed benchmark leaf; local evidence only, no launch, source grant or performance verdict."""

from __future__ import annotations

import resource
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkCapacitySample,
    BenchmarkCheckpoint,
    BenchmarkInvocationTimings,
    BenchmarkLocalBinary,
    BenchmarkLocalJson,
    BenchmarkLocalVector,
    BenchmarkQueryEncodeTiming,
    BenchmarkResourceEvidence,
    BenchmarkSampleKey,
    BenchmarkStagedInputs,
    BenchmarkSyntheticRejection,
    BenchmarkTokenBatch,
    BenchmarkTokenRow,
    BenchmarkTokenSample,
    BenchmarkTokenWitness,
    BenchmarkVectorSample,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    benchmark_sample_program,
)
from eom_catalog_contracts.embedding_vector_binary import pack_unit_vectors, read_unit_vectors
from eom_identifiers import content_sha256, sha256_bytes

from eom_catalog_service.embedding_benchmark_channel import (
    BenchmarkChannelError,
    BenchmarkWorkerChannel,
)
from eom_catalog_service.embedding_device_benchmark_files import (
    BenchmarkFilesError,
    BenchmarkWorkerLocalFiles,
)
from eom_catalog_service.embedding_execution_ports import (
    BenchmarkHostObservationError,
    BenchmarkHostOomObserver,
    BenchmarkNativeEmbeddingBackend,
    NativeObservedEncoding,
)
from eom_catalog_service.embedding_native_factory import NativeEmbeddingFactoryError
from eom_catalog_service.embedding_offline_backend import NativeEmbeddingBackendError


class BenchmarkWorkerError(ValueError):
    def __init__(self, code: str, *, cleanup_uncertain: bool = False) -> None:
        self.code, self.cleanup_uncertain = code, cleanup_uncertain
        super().__init__(code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BenchmarkWorkerError(code)


def _sealed(body: dict[str, Any], field: str) -> dict[str, Any]:
    return body | {field: content_sha256(body)}


@dataclass(frozen=True)
class _Input:
    text: str
    text_sha256: str
    row_sha256: str
    count: int
    ids_sha256: str


@dataclass(frozen=True)
class _Range:
    key: BenchmarkSampleKey
    purpose: Literal["DOCUMENT", "QUERY"]
    space_sha256: str
    rows: tuple[str, ...]
    binary: BenchmarkLocalBinary | None
    offset: int
    row_count: int


def _vector_prefix(
    records: list[_Range], supplementary: BenchmarkLocalBinary | None
) -> tuple[BenchmarkVectorSample, ...]:
    result = []
    for record in records:
        binary = record.binary or supplementary
        if binary is None:
            break
        result.append(
            BenchmarkVectorSample.model_validate(
                _sealed(
                    {
                        "key": record.key.model_dump(mode="json"),
                        "purpose": record.purpose,
                        "space_sha256": record.space_sha256,
                        "ordered_rows": record.rows,
                        "binary": binary.model_dump(mode="json"),
                        "byte_offset": record.offset,
                        "byte_count": record.row_count * 4096,
                        "row_count": record.row_count,
                        "dimension": 1024,
                    },
                    "sample_sha256",
                )
            )
        )
    return tuple(result)


def _runtime(
    invocation: BenchmarkWorkerInvocation, backend: BenchmarkNativeEmbeddingBackend
) -> None:
    provenance, runtime = backend.provenance, backend.execution_runtime
    _require(
        provenance.kind == "PINNED_MODEL"
        and provenance.model_spec == invocation.runtime.spaces.document.model_spec
        and type(backend.dimension) is int
        and backend.dimension == 1024
        and type(backend.batch_size) is int
        and backend.batch_size == 4
        and type(backend.threads) is int
        and backend.threads == 4
        and runtime.device == invocation.device
        and runtime.execution_runtime_sha256 == invocation.runtime.numerical_runtime.runtime_sha256,
        "BENCHMARK_WORKER_RUNTIME_INVALID",
    )


def _rss() -> int:
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    _require(type(maximum) is int and 0 < maximum <= 64 * 1024**2, "BENCHMARK_WORKER_RSS_INVALID")
    return maximum * 1024


def _inputs(key: BenchmarkSampleKey, inputs: BenchmarkStagedInputs) -> tuple[_Input, ...]:
    if key.phase in ("COLD_DOCUMENT", "WARM_DOCUMENT", "QUERY"):
        selected = (
            inputs.documents
            if key.phase != "QUERY"
            else (inputs.queries[(key.query_ordinal or 1) - 1],)
        )
        return tuple(
            _Input(
                row.text,
                row.row.input_text_sha256,
                row.row.row_sha256,
                row.token_count,
                row.token_ids_sha256,
            )
            for row in selected
        )
    fixture = (
        inputs.capacity
        if key.phase == "CAPACITY"
        else inputs.synthetic_cases[(key.synthetic_case or 1) - 1]
    )
    assert fixture.token_ids_sha256 is not None
    return (
        _Input(
            fixture.text,
            fixture.input_text_sha256,
            fixture.input_text_sha256,
            fixture.token_count,
            fixture.token_ids_sha256,
        ),
    ) * key.batch_size


def _actual_sample(
    key: BenchmarkSampleKey, expected: tuple[_Input, ...], observed: NativeObservedEncoding
) -> tuple[BenchmarkTokenSample, bytes]:
    _require(type(observed) is NativeObservedEncoding, "BENCHMARK_WORKER_TOKEN_INVALID")
    observed.__post_init__()
    purpose = "QUERY" if key.phase == "QUERY" else "DOCUMENT"
    _require(len(observed.vectors) == len(expected), "BENCHMARK_WORKER_TOKEN_INVALID")
    batches = []
    position = 0
    for batch in observed.batches:
        _require(
            batch.purpose == purpose and batch.padding_side == "right",
            "BENCHMARK_WORKER_TOKEN_INVALID",
        )
        rows = []
        for actual in batch.rows:
            _require(position < len(expected), "BENCHMARK_WORKER_TOKEN_INVALID")
            selected = expected[position]
            _require(
                (actual.input_text_sha256, actual.unpadded_token_count, actual.token_ids_sha256)
                == (selected.text_sha256, selected.count, selected.ids_sha256),
                "BENCHMARK_WORKER_TOKEN_INVALID",
            )
            rows.append(
                BenchmarkTokenRow(
                    row_sha256=selected.row_sha256,
                    input_ids=actual.input_ids,
                    attention_mask=actual.attention_mask,
                    token_type_ids=actual.token_type_ids,
                    token_count=actual.unpadded_token_count,
                    token_ids_sha256=actual.token_ids_sha256,
                )
            )
            position += 1
        batches.append(
            BenchmarkTokenBatch.model_validate(
                _sealed(
                    {
                        "purpose": purpose,
                        "pad_token_id": batch.pad_token_id,
                        "rows": [row.model_dump(mode="json") for row in rows],
                    },
                    "batch_sha256",
                )
            )
        )
    _require(position == len(expected), "BENCHMARK_WORKER_TOKEN_INVALID")
    token = BenchmarkTokenSample.model_validate(
        _sealed(
            {
                "key": key.model_dump(mode="json"),
                "batches": [batch.model_dump(mode="json") for batch in batches],
            },
            "sample_sha256",
        )
    )
    raw = pack_unit_vectors(observed.vectors, dimension=1024)
    read_unit_vectors(
        raw, dimension=1024, row_count=len(expected), expected_sha256=sha256_bytes(raw)
    )
    return token, raw


def _negative(
    backend: BenchmarkNativeEmbeddingBackend, inputs: BenchmarkStagedInputs
) -> tuple[BenchmarkSyntheticRejection, ...]:
    result = []
    for case in inputs.synthetic_cases[6:]:
        for batch in (1, 4):
            try:
                backend.encode_observed((case.text,) * batch, purpose="DOCUMENT")
            except NativeEmbeddingBackendError as error:
                rejected = error.token_rejection
                _require(rejected is not None, "BENCHMARK_WORKER_REJECTION_INVALID")
                assert rejected is not None
                rejected.__post_init__()
                _require(
                    rejected.input_text_sha256 == (case.input_text_sha256,) * batch,
                    "BENCHMARK_WORKER_REJECTION_INVALID",
                )
                if case.case_ordinal == 7:
                    _require(
                        error.code == "NATIVE_EMBEDDING_INPUT_INVALID"
                        and rejected.reason == "EMPTY"
                        and rejected.token_counts is None
                        and rejected.token_ids_sha256 is None,
                        "BENCHMARK_WORKER_REJECTION_INVALID",
                    )
                else:
                    _require(
                        error.code == "NATIVE_EMBEDDING_INPUT_TOO_LONG"
                        and rejected.reason == "OVERFLOW"
                        and rejected.token_counts == (case.token_count,) * batch
                        and rejected.token_ids_sha256 == (case.token_ids_sha256,) * batch,
                        "BENCHMARK_WORKER_REJECTION_INVALID",
                    )
            else:
                raise BenchmarkWorkerError("BENCHMARK_WORKER_REJECTION_INVALID")
            result.append(
                BenchmarkSyntheticRejection.model_validate(
                    {
                        "synthetic_case": case.case_ordinal,
                        "batch_size": batch,
                        "reason": case.expected,
                    }
                )
            )
    return tuple(result)


def run_embedding_device_benchmark(
    files: BenchmarkWorkerLocalFiles,
    backend_scope: Callable[[], AbstractContextManager[BenchmarkNativeEmbeddingBackend]],
    channel: BenchmarkWorkerChannel,
    *,
    entry_started_ns: int,
    expires_ns: int,
    host_oom_observer: BenchmarkHostOomObserver,
) -> BenchmarkWorkerResult:
    """Run once with mandatory captured adapters; never launch, release a lease or publish.

    COMPLETED means this evidence program finished, not resource/performance/authorization/
    cleanup PASS. Real root-installed entry/capture and host observer remain uncomposed.
    """
    invocation: BenchmarkWorkerInvocation | None = None
    records: list[_Range] = []
    tokens: list[BenchmarkTokenSample] = []
    supplementary: BenchmarkLocalBinary | None = None
    witness: BenchmarkLocalJson | None = None
    timings: BenchmarkInvocationTimings | None = None
    resources: BenchmarkResourceEvidence | None = None
    output: BenchmarkWorkerResult | None = None
    negatives: tuple[BenchmarkSyntheticRejection, ...] = ()
    failure: str | None = None
    completed = False
    cleanup_uncertain = False
    entered = False
    last_host, last_cuda = 0, 0

    def check() -> None:
        _require(time.monotonic_ns() < expires_ns, "BENCHMARK_WORKER_DEADLINE")
        files.assert_current()

    def host_count() -> int:
        nonlocal last_host
        count = host_oom_observer.observe_delta()
        _require(
            type(count) is int and last_host <= count <= 64, "BENCHMARK_WORKER_HOST_OOM_INVALID"
        )
        last_host = count
        return count

    def gpu_count(backend: BenchmarkNativeEmbeddingBackend) -> int:
        nonlocal last_cuda
        count = backend.cuda_oom_count()
        if invocation is not None and invocation.device == "CPU":
            _require(count is None, "BENCHMARK_WORKER_CUDA_OOM_INVALID")
            return 0  # Inapplicable CUDA addend; CPU never claims a CUDA observation.
        _require(
            type(count) is int and last_cuda <= count <= 64, "BENCHMARK_WORKER_CUDA_OOM_INVALID"
        )
        assert count is not None
        last_cuda = count
        return count

    def result(status: Literal["COMPLETED", "FAILED"], code: str | None) -> BenchmarkWorkerResult:
        assert invocation is not None
        return BenchmarkWorkerResult.model_validate(
            _sealed(
                {
                    "schema_version": "embedding-device-benchmark-worker-result/1.0",
                    "kind": "WORKER_RESULT",
                    "execution_id": invocation.execution_id,
                    "invocation_sha256": invocation.invocation_sha256,
                    "launch_ordinal": invocation.launch_ordinal,
                    "device": invocation.device,
                    "status": status,
                    "reason_codes": () if code is None else (code,),
                    "vectors": [
                        value.model_dump(mode="json")
                        for value in _vector_prefix(records, supplementary)
                    ],
                    "synthetic_rejections": [value.model_dump(mode="json") for value in negatives],
                    "token_witness": witness.model_dump(mode="json")
                    if witness is not None
                    else None,
                    "timings": timings.model_dump(mode="json") if timings is not None else None,
                    "resources": resources.model_dump(mode="json")
                    if resources is not None
                    else None,
                },
                "result_sha256",
            )
        )

    try:
        now = time.perf_counter_ns()
        _require(
            type(entry_started_ns) is int and 0 < entry_started_ns < now,
            "BENCHMARK_WORKER_CAPTURE_INVALID",
        )
        _require(
            type(expires_ns) is int
            and time.monotonic_ns() < expires_ns <= time.monotonic_ns() + 180 * 10**9,
            "BENCHMARK_WORKER_CAPTURE_INVALID",
        )
        _require(
            callable(backend_scope) and callable(getattr(host_oom_observer, "observe_delta", None)),
            "BENCHMARK_WORKER_CAPTURE_INVALID",
        )
        files.__enter__()
        entered = True
        invocation = files.read_invocation()
        channel.assert_initial_invocation(invocation)
        inputs = files.read_inputs(invocation)
        check()
        host_count()
        program = benchmark_sample_program(invocation.launch_ordinal)
        load_start = time.perf_counter_ns()
        startup = load_start - entry_started_ns
        capacity: list[BenchmarkCapacitySample] = []
        warm: list[int] = []
        queries: list[BenchmarkQueryEncodeTiming] = []
        supplementary_offset = 0
        with backend_scope() as backend:
            load_ns = time.perf_counter_ns() - load_start
            _runtime(invocation, backend)
            gpu_count(backend)
            warmup = False
            sequence = 1
            cold_ns = 0
            for key in program:
                check()
                _runtime(invocation, backend)
                selected = _inputs(key, inputs)
                purpose: Literal["DOCUMENT", "QUERY"] = (
                    "QUERY" if key.phase == "QUERY" else "DOCUMENT"
                )
                if key.phase == "WARM_DOCUMENT" and not warmup:
                    negatives = _negative(backend, inputs)
                    check()
                    _actual_sample(
                        key,
                        selected,
                        backend.encode_observed(
                            tuple(row.text for row in selected), purpose="DOCUMENT"
                        ),
                    )
                    warmup = True
                if key.phase == "QUERY":
                    checkpoint = BenchmarkCheckpoint.model_validate(
                        _sealed(
                            {
                                "schema_version": "embedding-device-benchmark-checkpoint/1.0",
                                "kind": "LOCAL_CHECKPOINT",
                                "execution_id": invocation.execution_id,
                                "invocation_sha256": invocation.invocation_sha256,
                                "sequence": sequence,
                                "phase": "QUERY_PREPARED",
                                "query_ordinal": key.query_ordinal,
                                "query_repetition": key.repetition,
                                "vector": None,
                                "encode_duration_ns": None,
                            },
                            "checkpoint_sha256",
                        )
                    )
                    channel.send_checkpoint(checkpoint)
                    channel.receive_ack()
                    sequence += 1
                    check()
                backend.synchronize()
                started = time.perf_counter_ns()
                token, raw = _actual_sample(
                    key,
                    selected,
                    backend.encode_observed(tuple(row.text for row in selected), purpose=purpose),
                )
                backend.synchronize()
                duration = time.perf_counter_ns() - started
                _require(type(duration) is int and duration > 0, "BENCHMARK_WORKER_CLOCK_INVALID")
                _runtime(invocation, backend)
                check()
                binary = files.write_vectors(key, raw)
                rows = (
                    ()
                    if key.phase in ("SYNTHETIC", "CAPACITY")
                    else tuple(row.row_sha256 for row in selected)
                )
                offset = supplementary_offset if binary is None else 0
                records.append(
                    _Range(
                        key,
                        purpose,
                        invocation.runtime.spaces.query.space_sha256
                        if purpose == "QUERY"
                        else invocation.runtime.spaces.document.space_sha256,
                        rows,
                        binary,
                        offset,
                        len(selected),
                    )
                )
                if binary is None:
                    supplementary_offset += len(raw)
                tokens.append(token)
                if key.phase == "WARM_DOCUMENT":
                    warm.append(duration)
                elif key.phase == "QUERY":
                    assert key.query_ordinal is not None and key.repetition is not None
                    queries.append(
                        BenchmarkQueryEncodeTiming(
                            query_ordinal=key.query_ordinal,
                            repetition=key.repetition,
                            encode_ns=duration,
                        )
                    )
                if key.phase in ("COLD_DOCUMENT", "QUERY"):
                    assert binary is not None
                    local = BenchmarkLocalVector(
                        member_name=binary.member_name,
                        sha256=binary.sha256,
                        byte_count=binary.byte_count,
                        row_count=len(selected),
                        dimension=1024,
                        purpose=purpose,
                        space_sha256=records[-1].space_sha256,
                    )
                    checkpoint = BenchmarkCheckpoint.model_validate(
                        _sealed(
                            {
                                "schema_version": "embedding-device-benchmark-checkpoint/1.0",
                                "kind": "LOCAL_CHECKPOINT",
                                "execution_id": invocation.execution_id,
                                "invocation_sha256": invocation.invocation_sha256,
                                "sequence": sequence,
                                "phase": "COLD_READY"
                                if key.phase == "COLD_DOCUMENT"
                                else "QUERY_READY",
                                "query_ordinal": key.query_ordinal,
                                "query_repetition": key.repetition,
                                "vector": local.model_dump(mode="json"),
                                "encode_duration_ns": duration,
                            },
                            "checkpoint_sha256",
                        )
                    )
                    channel.send_checkpoint(checkpoint)
                    channel.receive_ack()
                    sequence += 1
                    if key.phase == "COLD_DOCUMENT":
                        cold_ns = duration
                if key.phase == "CAPACITY":
                    peaks = backend.allocator_peaks()
                    capacity.append(
                        BenchmarkCapacitySample.model_validate(
                            {
                                "batch_size": key.batch_size,
                                "maximum_tokens": 2048,
                                "input_text_sha256": inputs.capacity.input_text_sha256,
                                "token_ids_sha256": inputs.capacity.token_ids_sha256,
                                "peak_rss_bytes": _rss(),
                                "peak_allocated_gpu_bytes": peaks.allocated_bytes,
                                "peak_reserved_gpu_bytes": peaks.reserved_bytes,
                                "peak_whole_process_gpu_bytes": None,
                            }
                        )
                    )
                check()
                host_count()
                gpu_count(backend)
            channel.transcript()
            if invocation.launch_ordinal in (1, 2):
                supplementary = files.seal_supplementary()
            actual_witness = BenchmarkTokenWitness.model_validate(
                _sealed(
                    {
                        "schema_version": "embedding-device-benchmark-token-witness/1.0",
                        "invocation_sha256": invocation.invocation_sha256,
                        "launch_ordinal": invocation.launch_ordinal,
                        "samples": [sample.model_dump(mode="json") for sample in tokens],
                    },
                    "witness_sha256",
                )
            )
            witness = files.write_evidence(actual_witness)
            timings = BenchmarkInvocationTimings.model_validate(
                _sealed(
                    {
                        "schema_version": "embedding-device-benchmark-invocation-timings/1.0",
                        "invocation_sha256": invocation.invocation_sha256,
                        "launch_ordinal": invocation.launch_ordinal,
                        "device": invocation.device,
                        "startup_ns": startup,
                        "load_hash_ns": load_ns,
                        "cold_encode_ns": cold_ns,
                        "warmup_count": int(warmup),
                        "warm_encode_ns": warm,
                        "query_encode_ns": [query.model_dump(mode="json") for query in queries],
                    },
                    "timing_sha256",
                )
            )
            if invocation.launch_ordinal in (1, 2):
                files.write_evidence(timings)
            peaks = backend.allocator_peaks()
            cuda_ooms = gpu_count(backend)
            _runtime(invocation, backend)
            check()
        # Successful factory exit includes gated close; it never releases the owner's lease.
        check()
        oom_count = host_count() + cuda_ooms
        _require(oom_count <= 64, "BENCHMARK_WORKER_OOM_INVALID")
        local_resources = BenchmarkResourceEvidence.model_validate(
            _sealed(
                {
                    "schema_version": "embedding-device-benchmark-resources/1.0",
                    "invocation_sha256": invocation.invocation_sha256,
                    "launch_ordinal": invocation.launch_ordinal,
                    "device": invocation.device,
                    "peak_rss_bytes": _rss(),
                    "peak_allocated_gpu_bytes": peaks.allocated_bytes,
                    "peak_reserved_gpu_bytes": peaks.reserved_bytes,
                    "peak_whole_process_gpu_bytes": None,
                    "peak_whole_device_gpu_bytes": None,
                    "owner_observation_count": 0,
                    "oom_count": oom_count,
                    "other_consumer_overlap_count": 0,
                    "capacity_samples": [sample.model_dump(mode="json") for sample in capacity],
                },
                "resource_sha256",
            )
        )
        resources = channel.exchange_resources(local_resources)
        check()
        files.write_evidence(resources)
        output = result("COMPLETED", None)
        files.write_evidence(output)
        check()
        completed = True
    except Exception as error:
        failure = (
            error.code
            if isinstance(
                error,
                (
                    BenchmarkWorkerError,
                    BenchmarkHostObservationError,
                    BenchmarkFilesError,
                    BenchmarkChannelError,
                    NativeEmbeddingFactoryError,
                    NativeEmbeddingBackendError,
                ),
            )
            else "BENCHMARK_WORKER_FAILED"
        )
        if invocation is not None and entered:
            try:
                check()
                output = result("FAILED", failure)
                files.write_evidence(output)
            except Exception:
                cleanup_uncertain = True
    finally:
        try:
            files.close()
        except Exception:
            cleanup_uncertain = True
        try:
            channel.close()
        except Exception:
            cleanup_uncertain = True
    if failure is not None and (output is None or cleanup_uncertain):
        raise BenchmarkWorkerError(failure, cleanup_uncertain=cleanup_uncertain) from None
    if cleanup_uncertain or not (completed or failure is not None):
        raise BenchmarkWorkerError("BENCHMARK_WORKER_CLEANUP_UNCERTAIN", cleanup_uncertain=True)
    assert output is not None
    return output
