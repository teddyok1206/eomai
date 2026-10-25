"""Pure original source/device closure; no live route, actor, DB, model or dispatch."""

import pytest
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation, EmbeddingBatchRoute
from eom_workflow.embedding_batch_plan_v12 import (
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingGpuAllocationObservation,
    plan_embedding_device_route,
)
from eom_workflow_runner.reference_query_batch_driver import prepare_batch_reference_query_context
from eom_workflow_runner.reference_query_routed_context import build_routed_reference_query_context

from tests.unit.embedding_query_pair_fixtures import paired_query_case
from tests.unit.inference_transfer_embedding_fixtures import seal


def context(value, ordinal=0):
    return build_routed_reference_query_context(
        parent=value.request,
        selection=value.selection,
        policy=value.policy,
        allocation=value.allocation,
        route=value.route,
        ordinal=ordinal,
    )


@pytest.mark.parametrize("mixed", (False, True))
@pytest.mark.parametrize("status", ("ACQUIRED", "BUSY", "CAPACITY_UNAVAILABLE"))
def test_context_is_exact_original_device_pin_and_same_child_identity(mixed, status):
    value = paired_query_case(mixed=mixed, status=status)
    first = context(value)
    assert first == context(value)
    assert first == prepare_batch_reference_query_context(value.request, 0, first)
    assert first.request_id != context(value, 1).request_id
    assert first.anchor == value.selection.anchors[0]
    assert first.graph_snapshot == value.selection.graph_snapshot
    assert first.policy_revision_id == value.selection.access_policy_revision_id
    assert first.policy_sha256 == value.selection.scope.access_policy_sha256
    assert first.source_classes == value.selection.source_classes
    assert first.vector_mode == "REQUIRED"
    assert first.views == value.selection.selected_views("CUDA" if status == "ACQUIRED" else "CPU")
    assert first.schema_version == f"system-rag-similarity-request/{'2.0' if mixed else '1.0'}"


@pytest.mark.parametrize("ordinal", (True, -1, 2, None, "0"))
def test_ordinal_is_not_coerced_or_used_as_negative_index(ordinal):
    with pytest.raises(ValueError):
        context(paired_query_case(), ordinal)


@pytest.mark.parametrize(
    "fault", ("selection", "parent", "allocation", "route", "switched_device", "constructed")
)
def test_other_or_modified_immutable_plan_is_not_a_new_route_grant(fault):
    value = paired_query_case()
    if fault == "selection":
        body = value.selection.model_dump(mode="json")
        body["query"]["top_k"] += 1
        value.selection = EmbeddingBatchSelectionV12.model_validate(seal(body, "selection_sha256"))
    elif fault == "parent":
        value.request = EmbeddingBatchPlanRequestV12.model_validate(
            seal(
                value.request.model_dump(mode="json") | {"batch_id": "embeddingbatch_" + "f" * 32},
                "request_sha256",
            )
        )
    elif fault == "allocation":
        value.allocation = EmbeddingBatchAllocation.model_validate(
            seal(
                value.allocation.model_dump(mode="json") | {"request_sha256": "sha256:" + "f" * 64},
                "record_sha256",
            )
        )
    elif fault == "route":
        value.route = EmbeddingBatchRoute.model_validate(
            seal(
                value.route.model_dump(mode="json")
                | {"allocation_record_sha256": "sha256:" + "f" * 64},
                "record_sha256",
            )
        )
    elif fault == "switched_device":
        # This is a valid other decision but not the original route observation.
        observed = EmbeddingGpuAllocationObservation.model_validate(
            seal(
                value.route.observation.model_dump(mode="json") | {"status": "BUSY"},
                "observation_sha256",
            )
        )
        value.route = EmbeddingBatchRoute.model_validate(
            seal(
                value.route.model_dump(mode="json")
                | {
                    "decision": plan_embedding_device_route(value.policy, observed).model_dump(
                        mode="json"
                    )
                },
                "record_sha256",
            )
        )
    else:
        value.selection = value.selection.model_copy(update={"roles": ["ADMIN"]})
    with pytest.raises(ValueError):
        context(value)
