"""New logical child intents preserve source/index/Graph pins, not runtime authority."""

from __future__ import annotations

import pytest
from eom_workflow.embedding_batch_plan import EmbeddingBatchPlanRequest
from eom_workflow_runner.reference_query_batch_driver import prepare_batch_reference_query_context

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import two_query_plan_case


def test_parent_scoped_child_identity_keeps_all_source_pins_and_original_context():
    queries, plan = two_query_plan_case()
    original = queries[0].request.context_request
    # The generic planning fixture uses an opaque actor label. This helper is
    # specifically an actual-operator request identity, not a permission grant.
    scope = seal(
        plan.request.scope.model_dump(mode="json")
        | {"actor_id": queries[0].request.operator_audit.operator_id},
        "scope_sha256",
    )
    plan.request = EmbeddingBatchPlanRequest.model_validate(
        seal(plan.request.model_dump(mode="json") | {"scope": scope}, "request_sha256")
    )
    before = original.model_dump(mode="json")
    first = prepare_batch_reference_query_context(plan.request, 0, original)
    assert first == prepare_batch_reference_query_context(plan.request, 0, original)
    assert original.model_dump(mode="json") == before
    assert (
        first.request_id != original.request_id and first.request_sha256 != original.request_sha256
    )
    assert first.model_dump(
        mode="json", exclude={"request_id", "request_sha256"}
    ) == original.model_dump(mode="json", exclude={"request_id", "request_sha256"})
    parent = EmbeddingBatchPlanRequest.model_validate(
        seal(
            plan.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + "f" * 32},
            "request_sha256",
        )
    )
    assert prepare_batch_reference_query_context(parent, 0, original).request_id != first.request_id
    assert (
        prepare_batch_reference_query_context(plan.request, 1, original).request_id
        != first.request_id
    )


@pytest.mark.parametrize("ordinal", (True, -1, 2))
def test_invalid_ordinal_is_not_a_new_logical_query(ordinal):
    queries, plan = two_query_plan_case()
    with pytest.raises(ValueError):
        prepare_batch_reference_query_context(
            plan.request, ordinal, queries[0].request.context_request
        )
