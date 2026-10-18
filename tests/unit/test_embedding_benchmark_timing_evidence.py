"""Synthetic original clock closure; no measured device performance or model run."""

from dataclasses import FrozenInstanceError, replace

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkColdTiming,
    BenchmarkInvocationTimings,
    BenchmarkQueryTiming,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_catalog_service.embedding_benchmark_timing_evidence import (
    BenchmarkLaunchTimings,
    assess_benchmark_series_timings,
)

from tests.unit.embedding_device_benchmark_fixtures import (
    invocation_timings,
    owner_request,
    staged_inputs,
    worker_invocation,
)
from tests.unit.inference_transfer_embedding_fixtures import seal


def timing_runs(*, cuda_scale=1):
    runs = []
    for ordinal in range(1, 7):
        invocation, native = worker_invocation(ordinal), invocation_timings(ordinal)
        invocation = BenchmarkWorkerInvocation.model_validate(
            seal(
                invocation.model_dump(mode="json") | {"job_id": "job_" + "a" * 32},
                "invocation_sha256",
            )
        )
        native = BenchmarkInvocationTimings.model_validate(
            seal(
                native.model_dump(mode="json")
                | {"invocation_sha256": invocation.invocation_sha256},
                "timing_sha256",
            )
        )
        if invocation.device == "CUDA" and cuda_scale != 1:
            body = native.model_dump(mode="json")
            for field in ("startup_ns", "load_hash_ns", "cold_encode_ns"):
                body[field] //= cuda_scale
            body["warm_encode_ns"] = [ns // cuda_scale for ns in body["warm_encode_ns"]]
            for query in body["query_encode_ns"]:
                query["encode_ns"] //= cuda_scale
            native = BenchmarkInvocationTimings.model_validate(seal(body, "timing_sha256"))
        runs.append(
            BenchmarkLaunchTimings(
                invocation,
                native,
                BenchmarkColdTiming(
                    launch_ordinal=ordinal,
                    end_to_end_ns=native.startup_ns
                    + native.load_hash_ns
                    + native.cold_encode_ns
                    + 1001,
                    startup_ns=native.startup_ns,
                    load_hash_ns=native.load_hash_ns,
                    encode_ns=native.cold_encode_ns,
                ),
                tuple(
                    BenchmarkQueryTiming(
                        **query.model_dump(mode="json"),
                        authorization_ns=1000,
                        end_to_end_ns=query.encode_ns + 1001,
                    )
                    for query in native.query_encode_ns
                ),
            )
        )
    return tuple(runs)


def assess(runs=None):
    return assess_benchmark_series_timings(
        owner_request(), staged_inputs(), timing_runs() if runs is None else runs
    )


def test_all_original_cold_spans_first_launch_warm_queries_and_conservative_rounding():
    result = assess()
    assert tuple(c.launch_ordinal for c in result.cpu.cold) == (1, 4, 5)
    assert tuple(c.launch_ordinal for c in result.cuda.cold) == (2, 3, 6)
    assert result.cpu.gate_timings.cold_end_to_end_us == (3001,) * 3
    assert result.cuda.gate_timings.cold_end_to_end_us == (3002,) * 3
    assert result.cpu.gate_timings.query_end_to_end_us == ((1001,) * 5,) * 2
    assert result.cuda.gate_timings.query_end_to_end_us == ((1002,) * 5,) * 2
    assert result.performance.verdict == "KEEP_CPU"
    assert result.performance.reasons == ("WARM_MEDIAN_NOT_SUPERIOR", "COLD_MEDIAN_NOT_SUPERIOR")
    assert embedding_device_benchmark_bytes(result.cpu) == embedding_device_benchmark_bytes(
        assess().cpu
    )
    with pytest.raises(FrozenInstanceError):
        result.cpu = result.cuda


def test_fixed_comparator_can_report_synthetic_superiority_without_default_or_numerical_approval():
    result = assess(timing_runs(cuda_scale=2))
    assert result.performance.verdict == "CUDA_PERFORMANCE_SUPERIOR"
    assert result.performance.reasons == ()
    assert not hasattr(result, "default_device") and not hasattr(result, "numerical_pass")


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "reorder",
        "list",
        "foreign_job",
        "reused_execution",
        "native_hash",
        "cold_clock",
        "query_clock",
        "query_order",
        "query_extra",
        "cold_extra",
        "private_extra",
    ],
)
def test_incomplete_foreign_or_cherry_picked_clock_inputs_are_denied_without_content(fault):
    runs = list(timing_runs())
    if fault == "missing":
        runs.pop()
    elif fault == "reorder":
        runs[2], runs[5] = runs[5], runs[2]
    elif fault in {"foreign_job", "reused_execution"}:
        body = runs[2].invocation.model_dump(mode="json")
        body["job_id" if fault == "foreign_job" else "execution_id"] = (
            "job_" + "f" * 32 if fault == "foreign_job" else runs[0].invocation.execution_id
        )
        invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
        native = BenchmarkInvocationTimings.model_validate(
            seal(
                runs[2].native.model_dump(mode="json")
                | {"invocation_sha256": invocation.invocation_sha256},
                "timing_sha256",
            )
        )
        runs[2] = replace(runs[2], invocation=invocation, native=native)
    elif fault == "native_hash":
        runs[2] = replace(runs[2], native=invocation_timings(6))
    elif fault == "cold_clock":
        runs[2] = replace(runs[2], cold=runs[2].cold.model_copy(update={"encode_ns": 999_999}))
    elif fault == "query_clock":
        queries = runs[0].queries
        runs[0] = replace(
            runs[0], queries=(queries[0].model_copy(update={"encode_ns": 999_999}), *queries[1:])
        )
    elif fault == "query_order":
        runs[0] = replace(runs[0], queries=tuple(reversed(runs[0].queries)))
    elif fault == "query_extra":
        queries = runs[0].queries
        runs[0] = replace(
            runs[0],
            queries=(
                queries[0].model_copy(update={"private_note": "PRIVATE_SENTINEL"}),
                *queries[1:],
            ),
        )
    elif fault == "cold_extra":
        runs[2] = replace(
            runs[2], cold=runs[2].cold.model_copy(update={"private_note": "PRIVATE_SENTINEL"})
        )
    elif fault == "private_extra":
        runs[2] = replace(
            runs[2], native=runs[2].native.model_copy(update={"private_note": "PRIVATE_SENTINEL"})
        )
    with pytest.raises(ValueError, match="BENCHMARK_TIMING_SERIES_INVALID") as error:
        assess(runs if fault == "list" else tuple(runs))
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_one_bad_final_cold_sample_cannot_be_discarded_to_make_cuda_superior():
    runs = list(timing_runs(cuda_scale=2))
    runs[5] = replace(runs[5], cold=runs[5].cold.model_copy(update={"end_to_end_ns": 10_000_000}))
    result = assess(tuple(runs))
    assert result.performance.verdict == "KEEP_CPU"
    assert result.performance.reasons == ("COLD_MAX_REGRESSION",)
