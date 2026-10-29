"""Candidate metadata only; no process, lease, policy activation or GPU grant."""

import pytest
from eom_catalog_contracts.embedding_gpu_control import embedding_gpu_allocation_window_seconds
from eom_catalog_contracts.embedding_work_batch import MAX_EMBEDDING_WORK_BATCH_SECONDS
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow_runner.embedding_batch_allocation_candidate import (
    new_embedding_batch_allocation_candidate,
)

from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_batch_plan import planning_case


def finite_case(purpose="REFERENCE_QUERY", *, timeout_seconds=180):
    value = planning_case(purpose=purpose) if purpose == "INDEX" else paired_query_case()
    body = value.policy.model_dump(mode="json")
    for device in ("cpu", "cuda"):
        body[device]["profile"]["resource_profile"] = seal(
            body[device]["profile"]["resource_profile"] | {"timeout_seconds": timeout_seconds},
            "resource_profile_sha256",
        )
    value.policy = EmbeddingDeviceRoutingPolicy.model_validate(seal(body, "policy_sha256"))
    request = value.request.model_dump(mode="json")
    request["routing_policy_sha256"] = value.policy.policy_sha256
    request["routing_policy"]["sha256"] = sha256_bytes(canonical_json_bytes(value.policy))
    value.request = type(value.request).model_validate(seal(request, "request_sha256"))
    return value


@pytest.mark.parametrize("purpose", ("INDEX", "REFERENCE_QUERY"))
@pytest.mark.parametrize("timeout_seconds", (180, 300))
def test_shared_constructor_preserves_original_pins_and_numeric_limits(purpose, timeout_seconds):
    value = finite_case(purpose, timeout_seconds=timeout_seconds)
    before = value.policy.model_dump(mode="json")
    created = new_embedding_batch_allocation_candidate(
        value.request, value.policy, now_monotonic_ns=10**12
    )
    replay_candidate = new_embedding_batch_allocation_candidate(
        value.request, value.policy, now_monotonic_ns=10**12
    )
    assert created != replay_candidate
    assert created.control_request.parent_request_sha256 == value.request.request_sha256
    assert created.control_request.purpose == purpose
    assert (
        created.control_request.expires_monotonic_ns
        == 10**12
        + embedding_gpu_allocation_window_seconds(
            min(timeout_seconds, MAX_EMBEDDING_WORK_BATCH_SECONDS)
        )
        * 10**9
    )
    assert value.policy.model_dump(mode="json") == before


@pytest.mark.parametrize("now", (True, -1, 1.2, "12"))
def test_clock_value_cannot_be_coerced_into_a_candidate(now):
    value = finite_case()
    with pytest.raises(ValueError):
        new_embedding_batch_allocation_candidate(value.request, value.policy, now_monotonic_ns=now)


def test_foreign_routing_policy_is_not_a_fallback_or_allocation_grant():
    value = finite_case()
    policy = EmbeddingDeviceRoutingPolicy.model_validate(
        seal(
            value.policy.model_dump(mode="json")
            | {"policy_revision_id": "embeddingroutingpolicyrev_" + "f" * 32},
            "policy_sha256",
        )
    )
    with pytest.raises(ValueError):
        new_embedding_batch_allocation_candidate(value.request, policy)
