"""Derive an original child context from already pinned source/device plan values only."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityViewSelectionV2,
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context_request,
)
from eom_identifiers import content_sha256
from eom_workflow.embedding_batch_plan import EmbeddingBatchAllocation, EmbeddingBatchRoute
from eom_workflow.embedding_batch_plan_family import (
    embedding_batch_query_key,
    validate_embedding_batch_plan_controls,
    validate_embedding_batch_route_record,
)
from eom_workflow.embedding_batch_plan_v12 import (
    EmbeddingBatchPlanRequestV12,
    EmbeddingBatchSelectionV12,
)
from eom_workflow.embedding_device_routing import EmbeddingDeviceRoutingPolicy

from eom_workflow_runner.reference_query_prepare_application import reference_query_prepare_identity


def build_routed_reference_query_context(
    *,
    parent: EmbeddingBatchPlanRequestV12,
    selection: EmbeddingBatchSelectionV12,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingBatchAllocation,
    route: EmbeddingBatchRoute,
    ordinal: int,
) -> SupportedSimilarityContextRequest:
    """No latest lookup, permission, allocation, worker or persistence side effect.

    Actual admission must independently resolve the selection, both device
    populations and the original physical route. These small values are not
    authority. The same values always retain the exact same child identity.
    """
    parent = EmbeddingBatchPlanRequestV12.model_validate(parent)
    selection = EmbeddingBatchSelectionV12.model_validate(selection)
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
    body = dict(
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
        topics=list(query.topics),
        unit_ids=list(query.unit_ids),
        views=[row.model_dump(mode="json") for row in rows],
        vector_mode="REQUIRED",
        maximum_sources=query.maximum_sources,
        top_k=query.top_k,
    )
    return parse_supported_similarity_context_request(
        body | {"request_sha256": content_sha256(body)}
    )
