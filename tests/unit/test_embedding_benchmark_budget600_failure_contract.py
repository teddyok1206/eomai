"""The budget600 failure wire is additive and grants no implicit retry."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.embedding_benchmark_budget600_failure import (
    BenchmarkBudget600FailureDecision,
    BenchmarkBudget600PoststartObservation,
    BenchmarkBudget600PredecessorReference,
    benchmark_budget600_failure_bytes,
    parse_benchmark_budget600_failure,
)
from eom_catalog_contracts.embedding_device_benchmark import benchmark_local_output_members
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

_SHA = "sha256:" + "1" * 64
_EXECUTION = "a" * 32
_VERSION = "embedding-benchmark-poststart-failure/1.1"


def _observation() -> dict[str, object]:
    outputs = [
        {
            "member_name": name,
            "byte_count": 73728 if name == "cold-documents.f32" else 0,
            "raw_sha256": _SHA if name == "cold-documents.f32" else sha256_bytes(b""),
        }
        for name in benchmark_local_output_members(1)
    ]
    body: dict[str, object] = {
        "schema_version": _VERSION,
        "kind": "ROOT_OBSERVATION",
        "job_id": "job_" + "a" * 32,
        "execution_id": _EXECUTION,
        "request_sha256": _SHA,
        "invocation_sha256": _SHA,
        "device": "CPU",
        "launch_ordinal": 1,
        "failure_kind": "BUDGET600_TIMEOUT",
        "association_sha256": _SHA,
        "prepared_sha256": _SHA,
        "completion_sha256": _SHA,
        "invocation_raw_sha256": _SHA,
        "completion_raw_sha256": _SHA,
        "uncertain_raw_sha256": _SHA,
        "original_outcome": "FAILED",
        "cleanup": "CONFIRMED",
        "started_ns": 1,
        "completed_ns": 2,
        "controller": {
            "unit": "eom-gpu-benchmark-budget600-a7a80a1c-v4.service",
            "invocation_id": "b" * 32,
            "source_commit": "c" * 40,
            "supervisor_raw_sha256": _SHA,
        },
        "terminal": {
            "native_service": "eom-embedding-benchmark-cpu-budget600@" + _EXECUTION + ".service",
            "native_socket": "eom-embedding-benchmark-cpu-budget600@" + _EXECUTION + ".socket",
            "native_invocation_id": "d" * 32,
            "retirement_raw_sha256": _SHA,
            "main_pid": 0,
            "control_pid": 0,
            "descriptor_store_count": 0,
            "cgroup_empty": True,
            "socket_inactive": True,
            "retirement": "CONFIRMED",
            "retired_service_template_sha256": _SHA,
            "retired_socket_template_sha256": _SHA,
            "window_before_raw_sha256": _SHA,
            "window_stopped_raw_sha256": _SHA,
            "window_restored_raw_sha256": _SHA,
        },
        "outputs": outputs,
        "boot_id": "12345678-1234-1234-1234-123456789abc",
        "snapshot_sha256": _SHA,
        "observed_at": "2026-10-23T06:17:00Z",
    }
    body["observation_sha256"] = content_sha256(body)
    return body


def _decision() -> dict[str, object]:
    observation = _observation()
    body: dict[str, object] = {
        "schema_version": _VERSION,
        "kind": "FAILURE_DECISION",
        "job_id": observation["job_id"],
        "execution_id": observation["execution_id"],
        "request_sha256": observation["request_sha256"],
        "invocation_sha256": observation["invocation_sha256"],
        "from_state": "RUNNING",
        "to_state": "FAILED",
        "error_code": "BENCHMARK_POSTSTART_EXECUTION_FAILED",
        "observation": observation,
        "actor_id": "guiadmin",
        "decided_at": "2026-10-23T06:18:00Z",
    }
    body["decision_sha256"] = content_sha256(body)
    return body


def test_budget600_observation_decision_reference_roundtrip() -> None:
    observation = BenchmarkBudget600PoststartObservation.model_validate(_observation())
    decision = BenchmarkBudget600FailureDecision.model_validate(_decision())
    predecessor = BenchmarkBudget600PredecessorReference.from_decision(decision, event_sequence=8)
    for value in (observation, decision, predecessor):
        validate_contract(
            "embedding-benchmark-poststart-failure-v1.1", value.model_dump(mode="json")
        )
        assert parse_benchmark_budget600_failure(benchmark_budget600_failure_bytes(value)) == value


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), "embedding-benchmark-poststart-failure/1.0"),
        (("failure_kind",), "NATIVE_SUCCESS"),
        (("terminal", "native_service"), "eom-embedding-benchmark-cpu@" + _EXECUTION + ".service"),
        (("terminal", "window_restored_raw_sha256"), "broken"),
        (("outputs", 0, "member_name"), "worker-result.json"),
        (("completed_ns",), 1),
    ],
)
def test_budget600_invalid_or_legacy_proof_is_rejected(
    path: tuple[str | int, ...], replacement: object
) -> None:
    document = deepcopy(_observation())
    target: object = document
    for component in path[:-1]:
        target = target[component]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]
    document["observation_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "observation_sha256"}
    )
    with pytest.raises((ValueError, ValidationError, SchemaValidationError)):
        BenchmarkBudget600PoststartObservation.model_validate(document)


def test_budget600_missing_uncertainty_is_not_reinterpreted_as_success() -> None:
    document = _observation()
    document.pop("uncertain_raw_sha256")
    with pytest.raises((ValueError, ValidationError, SchemaValidationError)):
        BenchmarkBudget600PoststartObservation.model_validate(document)


def test_budget600_decision_must_pin_same_job() -> None:
    decision = _decision()
    decision["job_id"] = "job_" + "f" * 32
    decision["decision_sha256"] = content_sha256(
        {key: value for key, value in decision.items() if key != "decision_sha256"}
    )
    with pytest.raises((ValueError, ValidationError, SchemaValidationError)):
        BenchmarkBudget600FailureDecision.model_validate(decision)
