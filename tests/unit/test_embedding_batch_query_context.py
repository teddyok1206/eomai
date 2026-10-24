"""Pure frozen selection/key checks, not actual source or physical execution evidence."""

from __future__ import annotations

import pytest
from eom_workflow.embedding_batch_plan import (
    EmbeddingBatchPlanRequest,
    embedding_batch_query_key,
    validate_embedding_batch_query_context,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.reference_query_batch_execution_fixtures import two_query_plan_case


def test_exact_ordered_query_selection_and_parent_keys_are_deterministic_and_distinct():
    queries, plan = two_query_plan_case()
    for ordinal, query in enumerate(queries):
        validate_embedding_batch_query_context(
            plan.selection, plan.route.decision, ordinal, query.request
        )
    first = embedding_batch_query_key(plan.request, 0)
    assert first == embedding_batch_query_key(plan.request, 0)
    assert first != embedding_batch_query_key(plan.request, 1)
    changed = EmbeddingBatchPlanRequest.model_validate(
        seal(
            plan.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + "f" * 32},
            "request_sha256",
        )
    )
    assert first != embedding_batch_query_key(changed, 0)


@pytest.mark.parametrize("ordinal", (True, -1, 2, 1.0))
def test_invalid_ordinal_never_names_a_query(ordinal):
    queries, plan = two_query_plan_case()
    with pytest.raises(ValueError):
        embedding_batch_query_key(plan.request, ordinal)
    with pytest.raises(ValueError):
        validate_embedding_batch_query_context(
            plan.selection, plan.route.decision, ordinal, queries[0].request
        )


@pytest.mark.parametrize("fault", ("ordinal", "top_k", "topics", "units", "maximum", "policy"))
def test_valid_but_different_request_scope_is_not_a_batch_member(fault):
    queries, plan = two_query_plan_case()
    query = queries[0]
    with pytest.raises(ValueError):
        body = query.request.model_dump(mode="json")
        context = body["context_request"]
        if fault == "top_k":
            context["top_k"] += 1
        elif fault == "topics":
            context["topics"] = ["다른 개념"]
        elif fault == "units":
            context["unit_ids"] = ["다른 단원"]
        elif fault == "maximum":
            context["maximum_sources"] -= 1
        elif fault == "policy":
            context["policy_sha256"] = "sha256:" + "f" * 64
        body["context_request"] = seal(context, "request_sha256")
        request = parse_supported_reference_query_workflow_request(seal(body, "request_sha256"))
        validate_embedding_batch_query_context(
            plan.selection, plan.route.decision, 1 if fault == "ordinal" else 0, request
        )
