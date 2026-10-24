"""Additive retry-controller evidence only; synthetic values grant no recovery authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.embedding_benchmark_budget1200_failure import (
    BenchmarkBudget1200PoststartObservation,
    parse_benchmark_budget1200_failure,
)
from eom_catalog_contracts.embedding_benchmark_budget1200_retry_failure import (
    BUDGET1200_RETRY_POSTSTART_SCHEMA,
    BenchmarkBudget1200RetryControllerPin,
    BenchmarkBudget1200RetryFailureDecision,
    BenchmarkBudget1200RetryPoststartObservation,
    BenchmarkBudget1200RetryPredecessorReference,
    benchmark_budget1200_retry_failure_bytes,
    parse_benchmark_budget1200_retry_failure,
)
from eom_catalog_contracts.embedding_benchmark_poststart_failure import MAX_POSTSTART_FAILURE_BYTES
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import BenchmarkFailedControllerPin
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal

INVALID = (ValueError, TypeError, SchemaError)
SOURCE = "3625ffd979788111d64c2fc06b708247f786b950"


def retry_observation_body() -> dict[str, Any]:
    body = observation().model_dump(mode="json")
    body["schema_version"] = "embedding-benchmark-poststart-failure/1.3"
    body["controller"]["source_commit"] = SOURCE
    body["controller"]["unit"] = "eom-embedding-benchmark-retry-3625ffd9.service"
    prefix = "eom-embedding-benchmark-cpu-budget1200@" + body["execution_id"]
    body["terminal"]["native_service"] = prefix + ".service"
    body["terminal"]["native_socket"] = prefix + ".socket"
    return seal(body, "observation_sha256")


def retry_observation() -> BenchmarkBudget1200RetryPoststartObservation:
    return BenchmarkBudget1200RetryPoststartObservation.model_validate(retry_observation_body())


def retry_decision() -> BenchmarkBudget1200RetryFailureDecision:
    seen = retry_observation()
    body = {
        "schema_version": "embedding-benchmark-poststart-failure/1.3",
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
    return BenchmarkBudget1200RetryFailureDecision.model_validate(seal(body, "decision_sha256"))


def test_additive_schema_mirror_pin_and_canonical_three_kind_roundtrips() -> None:
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES[BUDGET1200_RETRY_POSTSTART_SCHEMA]
    canonical = (root / resource.canonical_path).read_bytes()
    packaged = (
        root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    ).read_bytes()
    assert canonical == packaged and sha256_bytes(canonical) == resource.sha256
    Draft202012Validator.check_schema(load_schema(BUDGET1200_RETRY_POSTSTART_SCHEMA))
    decision = retry_decision()
    for value in (
        retry_observation(),
        decision,
        BenchmarkBudget1200RetryPredecessorReference.from_decision(decision, event_sequence=8),
    ):
        raw = benchmark_budget1200_retry_failure_bytes(value)
        assert len(raw) < MAX_POSTSTART_FAILURE_BYTES
        assert parse_benchmark_budget1200_retry_failure(raw) == value
        assert not hasattr(value, "assert_current") and not hasattr(value, "capture")
        with pytest.raises(INVALID):
            parse_benchmark_budget1200_failure(raw)


def test_released_predecessor_schema_bytes_and_controller_meaning_are_unchanged() -> None:
    root = Path(__file__).resolve().parents[2]
    pins = (
        (
            "embedding-benchmark-poststart-failure",
            "sha256:e8ac0a6b5d06f1376f871ad6c42966f9ae5ffc3ae97381e213a9a1bf950950e0",
        ),
        (
            "embedding-benchmark-poststart-failure-v1.1",
            "sha256:da020334f6a7ad88ea3f12308f0f357e821bb2a04ab6e8ef4f9d55180aedc52a",
        ),
        (
            "embedding-benchmark-poststart-failure-v1.2",
            "sha256:33547b07d145e231cf9acc7ec9eff1ed940069e880dd09ef1b60d5e76eba39c3",
        ),
    )
    for name, expected in pins:
        resource = CATALOG_SCHEMA_RESOURCES[name]
        assert resource.sha256 == expected
        assert sha256_bytes((root / resource.canonical_path).read_bytes()) == expected
    pin = retry_observation().controller
    assert type(pin) is BenchmarkBudget1200RetryControllerPin
    assert BenchmarkBudget1200RetryControllerPin.model_validate(pin) == pin
    with pytest.raises(INVALID):
        BenchmarkFailedControllerPin.model_validate(pin.model_dump(mode="json"))
    body = retry_observation_body()
    body["schema_version"] = "embedding-benchmark-poststart-failure/1.2"
    with pytest.raises(INVALID):
        BenchmarkBudget1200PoststartObservation.model_validate(seal(body, "observation_sha256"))


@pytest.mark.parametrize(
    "unit",
    (
        "eom-gpu-benchmark-synthetic.service",
        "eom-embedding-benchmark-verified-3625ffd9.service",
        "eom-embedding-benchmark-retry-3625ffd.service",
        "eom-embedding-benchmark-retry-3625ffd90.service",
        "eom-embedding-benchmark-retry-3625FFD9.service",
        "eom-embedding-benchmark-retry-ffffffff.service",
        "eom-embedding-benchmark-retry-3625ffd9.socket",
        "../eom-embedding-benchmark-retry-3625ffd9.service",
        "eom-embedding-benchmark-retry-3625ffd9.service\n",
    ),
)
def test_controller_unit_family_and_exact_source_pair_are_closed(unit: str) -> None:
    body = retry_observation_body()
    body["controller"]["unit"] = unit
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_commit", "a" * 40),
        ("source_commit", "not-a-source"),
        ("invocation_id", "A" * 32),
        ("supervisor_raw_sha256", "not-a-hash"),
        ("permission", "ADMIN"),
    ),
)
def test_controller_forged_or_additional_fields_are_not_coerced(field: str, value: Any) -> None:
    body = retry_observation_body()
    body["controller"][field] = value
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("main_pid", 1),
        ("main_pid", False),
        ("control_pid", 1),
        ("descriptor_store_count", 1),
        ("cgroup_empty", False),
        ("socket_inactive", False),
        ("retirement", "UNCERTAIN"),
        ("native_service", "eom-embedding-benchmark-cpu-budget600@" + "a" * 32 + ".service"),
        ("native_socket", "eom-embedding-benchmark-cpu-budget1200@" + "b" * 32 + ".socket"),
    ),
)
def test_live_or_wrong_native_terminal_facts_are_rejected(field: str, value: Any) -> None:
    body = retry_observation_body()
    body["terminal"][field] = value
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )


@pytest.mark.parametrize("field", ("launch_ordinal", "started_ns", "completed_ns"))
@pytest.mark.parametrize("value", (True, 1.0, "1", None))
def test_raw_counts_are_strict_before_typed_model_coercion(field: str, value: Any) -> None:
    body = retry_observation_body()
    body[field] = value
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )


def test_hash_linkage_and_noncanonical_bytes_fail_explicitly() -> None:
    body = retry_observation_body()
    body["observation_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(body)
    decision = retry_decision().model_dump(mode="json")
    decision["job_id"] = "job_" + "f" * 32
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryFailureDecision.model_validate(seal(decision, "decision_sha256"))
    raw = benchmark_budget1200_retry_failure_bytes(retry_observation())
    with pytest.raises(INVALID):
        parse_benchmark_budget1200_retry_failure(raw + b"\n")
    with pytest.raises(INVALID):
        parse_benchmark_budget1200_retry_failure(canonical_json_bytes({"unexpected": True}))


def test_tick_integer_upper_bound_matches_schema_and_typed_model_exactly() -> None:
    body = retry_observation_body()
    body["started_ns"], body["completed_ns"] = 2**63 - 2, 2**63 - 1
    value = BenchmarkBudget1200RetryPoststartObservation.model_validate(
        seal(body, "observation_sha256")
    )
    assert value.completed_ns == 2**63 - 1
    body["completed_ns"] = 2**63
    with pytest.raises(INVALID):
        BenchmarkBudget1200RetryPoststartObservation.model_validate(
            seal(body, "observation_sha256")
        )
