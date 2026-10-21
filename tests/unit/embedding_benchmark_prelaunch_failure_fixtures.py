"""Synthetic closure metadata only: no current identity, root origin, OS or compute proof."""

from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    BenchmarkPrelaunchFailureDecision,
    BenchmarkPrelaunchObservation,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import owner_request, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal


def observation(
    request: BenchmarkOwnerRequest | None = None,
    invocation: BenchmarkWorkerInvocation | None = None,
) -> BenchmarkPrelaunchObservation:
    request = request or owner_request()
    invocation = invocation or worker_invocation(1)
    body = {
        "schema_version": "embedding-benchmark-prelaunch-failure/1.0",
        "kind": "ROOT_OBSERVATION",
        "job_id": invocation.job_id,
        "execution_id": invocation.execution_id,
        "request_sha256": request.request_sha256,
        "invocation_sha256": invocation.invocation_sha256,
        "device": "CPU",
        "launch_ordinal": 1,
        "association_sha256": content_sha256("synthetic association"),
        "uncertainty_sha256": content_sha256("synthetic uncertainty"),
        "invocation_raw_sha256": sha256_bytes(embedding_device_benchmark_bytes(invocation)),
        "uncertainty_raw_sha256": content_sha256("synthetic uncertainty bytes"),
        "controller": {
            "unit": "eom-gpu-benchmark-synthetic.service",
            "invocation_id": "a" * 32,
            "source_commit": "b" * 40,
            "supervisor_raw_sha256": content_sha256("synthetic supervisor"),
        },
        "boot_id": "00000000-0000-0000-0000-000000000001",
        "snapshot_sha256": content_sha256("synthetic not an OS observation"),
        "output_count": 16,
        "disposition": "PREPARATION_FAILED_BEFORE_NATIVE_START",
        "observed_at": "2026-10-21T12:00:00Z",
    }
    return BenchmarkPrelaunchObservation.model_validate(seal(body, "observation_sha256"))


def decision() -> BenchmarkPrelaunchFailureDecision:
    seen = observation()
    body = {
        "schema_version": "embedding-benchmark-prelaunch-failure/1.0",
        "kind": "FAILURE_DECISION",
        "job_id": seen.job_id,
        "execution_id": seen.execution_id,
        "request_sha256": seen.request_sha256,
        "invocation_sha256": seen.invocation_sha256,
        "from_state": "RUNNING",
        "to_state": "FAILED",
        "error_code": "BENCHMARK_PRELAUNCH_PREPARATION_FAILED",
        "observation": seen.model_dump(mode="json"),
        "actor_id": "operator_" + "1" * 32,
        "decided_at": "2026-10-21T12:00:01Z",
    }
    return BenchmarkPrelaunchFailureDecision.model_validate(seal(body, "decision_sha256"))
