"""Original six-launch clock closure; pure values, never execution or activation."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.embedding_device_benchmark import (
    BENCHMARK_DEVICE_SEQUENCE,
    BenchmarkColdTiming,
    BenchmarkDevice,
    BenchmarkInvocationTimings,
    BenchmarkOwnerRequest,
    BenchmarkQueryTiming,
    BenchmarkStagedInputs,
    BenchmarkTimingEvidence,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_device_comparison import (
    EmbeddingDeviceTimings,
    EmbeddingPerformanceDecision,
    compare_embedding_device_performance,
)


@dataclass(frozen=True, slots=True)
class BenchmarkLaunchTimings:
    """One validated read materialization, not a provenance or authorization grant."""

    invocation: BenchmarkWorkerInvocation
    native: BenchmarkInvocationTimings
    cold: BenchmarkColdTiming
    queries: tuple[BenchmarkQueryTiming, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkSeriesTimingAssessment:
    cpu: BenchmarkTimingEvidence
    cuda: BenchmarkTimingEvidence
    performance: EmbeddingPerformanceDecision


def _device_evidence(
    device: BenchmarkDevice, runs: tuple[BenchmarkLaunchTimings, ...]
) -> BenchmarkTimingEvidence:
    selected = tuple(run for run in runs if run.invocation.device == device)
    first = selected[0]

    def microseconds(ns: int) -> int:
        return ns // 1000 if device == "CPU" else (ns + 999) // 1000

    body = dict(
        schema_version="embedding-device-benchmark-timing-evidence/1.0",
        device=device,
        cold=tuple(run.cold for run in selected),
        warm_encode_ns=first.native.warm_encode_ns,
        queries=first.queries,
        gate_timings=dict(
            device=device,
            cold_end_to_end_us=tuple(microseconds(run.cold.end_to_end_ns) for run in selected),
            warm_batch_encode_us=tuple(microseconds(ns) for ns in first.native.warm_encode_ns),
            query_encode_us=tuple(
                tuple(
                    microseconds(q.encode_ns) for q in first.queries if q.query_ordinal == ordinal
                )
                for ordinal in (1, 2)
            ),
            query_end_to_end_us=tuple(
                tuple(
                    microseconds(q.end_to_end_ns)
                    for q in first.queries
                    if q.query_ordinal == ordinal
                )
                for ordinal in (1, 2)
            ),
        ),
    )
    evidence = BenchmarkTimingEvidence.model_validate(
        body | {"timing_sha256": content_sha256(body)}
    )
    # The public codec checks raw nested values/extras before schema serialization.
    # It also preserves the released conservative conversion, not a new policy.
    embedding_device_benchmark_bytes(evidence)
    return evidence


def _performance_timings(value: BenchmarkTimingEvidence) -> EmbeddingDeviceTimings:
    timing = value.gate_timings
    return EmbeddingDeviceTimings(
        device=value.device,
        cold_end_to_end_us=timing.cold_end_to_end_us,
        warm_batch_encode_us=timing.warm_batch_encode_us,
        query_encode_us=(timing.query_encode_us[0], timing.query_encode_us[1]),
        query_end_to_end_us=(timing.query_end_to_end_us[0], timing.query_end_to_end_us[1]),
    )


def assess_benchmark_series_timings(
    request: BenchmarkOwnerRequest,
    inputs: BenchmarkStagedInputs,
    runs: tuple[BenchmarkLaunchTimings, ...],
) -> BenchmarkSeriesTimingAssessment:
    """Close original clocks and reuse frozen thresholds; never select fastest runs.

    The caller must obtain these values through actual current source/Artifact
    resolution. This pure assessment neither attests those reads nor replaces
    numerical/resource/cleanup/regression gates or authorizes a device switch.
    """
    try:
        embedding_device_benchmark_bytes(request)
        if type(runs) is not tuple or len(runs) != 6:
            raise ValueError()
        executions: set[str] = set()
        job_id: str | None = None
        for ordinal, (device, run) in enumerate(
            zip(BENCHMARK_DEVICE_SEQUENCE, runs, strict=True), 1
        ):
            if type(run) is not BenchmarkLaunchTimings:
                raise ValueError()
            invocation, native, cold = run.invocation, run.native, run.cold
            validate_benchmark_invocation(request, invocation, inputs)
            embedding_device_benchmark_bytes(native)
            if job_id is None:
                job_id = invocation.job_id
            if (
                invocation.launch_ordinal != ordinal
                or invocation.device != device
                or invocation.job_id != job_id
                or invocation.execution_id in executions
                or native.invocation_sha256 != invocation.invocation_sha256
                or native.launch_ordinal != ordinal
                or native.device != device
                or cold.launch_ordinal != ordinal
                or (cold.startup_ns, cold.load_hash_ns, cold.encode_ns)
                != (native.startup_ns, native.load_hash_ns, native.cold_encode_ns)
                or type(run.queries) is not tuple
                or tuple((q.query_ordinal, q.repetition, q.encode_ns) for q in run.queries)
                != tuple(
                    (q.query_ordinal, q.repetition, q.encode_ns) for q in native.query_encode_ns
                )
            ):
                raise ValueError()
            executions.add(invocation.execution_id)
        cpu, cuda = _device_evidence("CPU", runs), _device_evidence("CUDA", runs)
        return BenchmarkSeriesTimingAssessment(
            cpu,
            cuda,
            compare_embedding_device_performance(
                _performance_timings(cpu), _performance_timings(cuda)
            ),
        )
    except (ValueError, TypeError, AttributeError, KeyError, SchemaError):
        # Native/owner inputs can contain private extras; never echo them.
        raise ValueError("BENCHMARK_TIMING_SERIES_INVALID") from None
