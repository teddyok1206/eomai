"""Synthetic metadata only; no genuine actor, root provenance, PID1 or cleanup authority."""

from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureDecision,
    BenchmarkPoststartObservation,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkWorkerInvocation,
    benchmark_local_output_members,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, sha256_bytes

from tests.unit.embedding_device_benchmark_fixtures import owner_request, worker_invocation
from tests.unit.inference_transfer_embedding_fixtures import seal


def observation(
    request: BenchmarkOwnerRequest | None = None,
    invocation: BenchmarkWorkerInvocation | None = None,
) -> BenchmarkPoststartObservation:
    request = request or owner_request()
    invocation = invocation or worker_invocation(1)
    prefix = "eom-embedding-benchmark-cpu@" + invocation.execution_id
    body = {
        "schema_version": "embedding-benchmark-poststart-failure/1.0",
        "kind": "ROOT_OBSERVATION",
        "job_id": invocation.job_id,
        "execution_id": invocation.execution_id,
        "request_sha256": request.request_sha256,
        "invocation_sha256": invocation.invocation_sha256,
        "device": "CPU",
        "launch_ordinal": 1,
        "association_sha256": content_sha256("synthetic association"),
        "prepared_sha256": content_sha256("synthetic preparation"),
        "completion_sha256": content_sha256("synthetic completion"),
        "invocation_raw_sha256": sha256_bytes(embedding_device_benchmark_bytes(invocation)),
        "completion_raw_sha256": content_sha256("synthetic completion bytes"),
        "original_outcome": "FAILED",
        "cleanup": "CONFIRMED",
        "started_ns": 100,
        "completed_ns": 200,
        "controller": {
            "unit": "eom-gpu-benchmark-synthetic.service",
            "invocation_id": "a" * 32,
            "source_commit": "b" * 40,
            "supervisor_raw_sha256": content_sha256("synthetic supervisor"),
        },
        "terminal": {
            "native_service": prefix + ".service",
            "native_socket": prefix + ".socket",
            "native_invocation_id": "c" * 32,
            "retirement_raw_sha256": content_sha256("synthetic retirement bytes"),
            "main_pid": 0,
            "control_pid": 0,
            "descriptor_store_count": 0,
            "cgroup_empty": True,
            "socket_inactive": True,
            "retirement": "CONFIRMED",
        },
        "outputs": [
            {
                "member_name": name,
                "byte_count": 73728 if index == 0 else 0,
                "raw_sha256": content_sha256("synthetic partial")
                if index == 0
                else sha256_bytes(b""),
            }
            for index, name in enumerate(benchmark_local_output_members(1))
        ],
        "boot_id": "00000000-0000-0000-0000-000000000001",
        "snapshot_sha256": content_sha256("synthetic not an OS observation"),
        "observed_at": "2026-10-22T12:00:00Z",
    }
    return BenchmarkPoststartObservation.model_validate(seal(body, "observation_sha256"))


def decision() -> BenchmarkPoststartFailureDecision:
    seen = observation()
    body = {
        "schema_version": "embedding-benchmark-poststart-failure/1.0",
        "kind": "FAILURE_DECISION",
        "job_id": seen.job_id,
        "execution_id": seen.execution_id,
        "request_sha256": seen.request_sha256,
        "invocation_sha256": seen.invocation_sha256,
        "from_state": "RUNNING",
        "to_state": "FAILED",
        "error_code": "BENCHMARK_POSTSTART_EXECUTION_FAILED",
        "observation": seen.model_dump(mode="json"),
        "actor_id": "operator_" + "1" * 32,
        "decided_at": "2026-10-22T12:00:01Z",
    }
    return BenchmarkPoststartFailureDecision.model_validate(seal(body, "decision_sha256"))
