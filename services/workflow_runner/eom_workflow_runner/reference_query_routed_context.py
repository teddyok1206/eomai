"""Derive an original child context from already pinned source/device plan values only."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityViewSelectionV2,
)
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation, EmbeddingBatchRoute
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_query_key,
    parse_embedding_batch_plan_request,
    parse_embedding_batch_selection,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_route_record,
)
from eom_workflow.embedding_batch_plan_v12 import (
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_batch_plan_v14 import (
    EmbeddingBatchPlanRequestV14,
    EmbeddingBatchSelectionV14,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryContext,
    parse_supported_reference_query_context,
)

from eom_workflow_runner.reference_query_prepare_application import reference_query_prepare_identity


def build_routed_reference_query_context(
    *,
    parent: EmbeddingBatchPlanRequestV12 | EmbeddingBatchPlanRequestV14,
    selection: EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
    route: EmbeddingBatchRoute,
    ordinal: int,
) -> SupportedReferenceQueryContext:
    """No latest lookup, permission, allocation, worker or persistence side effect.

    Actual admission must independently resolve the selection, both device
    populations and the original physical route. These small values are not
    authority. The same values always retain the exact same child identity.
    """
    checked_parent = parse_embedding_batch_plan_request(parent)
    checked_selection = parse_embedding_batch_selection(selection)
    if not isinstance(
        checked_parent, EmbeddingBatchPlanRequestV12 | EmbeddingBatchPlanRequestV14
    ) or not isinstance(checked_selection, EmbeddingBatchSelectionV12 | EmbeddingBatchSelectionV14):
        raise ValueError("REFERENCE_QUERY_ROUTED_CONTEXT_FAMILY_INVALID")
    parent, selection = checked_parent, checked_selection
    policy = EmbeddingDeviceRoutingPolicy.model_validate(policy)
    allocation = EmbeddingBatchAllocation.model_validate(allocation)
    route = EmbeddingBatchRoute.model_validate(route)
    validate_embedding_batch_plan_controls(parent, selection, policy)
    validate_embedding_batch_route_record(parent, policy, allocation, route)
    if type(ordinal) is not int or not 0 <= ordinal < len(selection.anchors):
        raise ValueError("REFERENCE_QUERY_BATCH_ORDINAL_INVALID")
    query = selection.query
    assert query is not None
    rows = selection.selected_views(route.decision.selected.backend.device)
    _key, request_id = reference_query_prepare_identity(
        parent.scope.actor_id, embedding_batch_query_key(parent, ordinal)
    )
    body: dict[str, object] = dict(
        schema_version="system-rag-similarity-request/2.0"
        if isinstance(rows[0], SimilarityViewSelectionV2)
        else "system-rag-similarity-request/1.0",
        request_id=request_id,
        consumer_purpose=query.consumer_purpose,
        anchor=selection.anchors[ordinal].model_dump(mode="json"),
        graph_snapshot=selection.graph_snapshot.model_dump(mode="json"),
        policy_revision_id=selection.access_policy_revision_id,
        policy_sha256=selection.scope.access_policy_sha256,
        source_classes=list(selection.source_classes),
        views=[row.model_dump(mode="json") for row in rows],
        maximum_sources=query.maximum_sources,
        top_k=query.top_k,
    )
    if isinstance(selection, EmbeddingBatchSelectionV14):
        body["schema_version"] = "system-rag-similarity-request/3.0"
    else:
        assert selection.query is not None
        body.update(
            topics=list(selection.query.topics),
            unit_ids=list(selection.query.unit_ids),
            vector_mode="REQUIRED",
        )
    return parse_supported_reference_query_context(body | {"request_sha256": content_sha256(body)})
