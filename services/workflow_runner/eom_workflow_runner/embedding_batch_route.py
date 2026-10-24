"""Close a planned device decision over one staged batch, not an execution grant."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_contracts.embedding_work_batch import (
    EmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.inference_transfer_experiment import VIEWS, ExperimentView
from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPair,
    EmbeddingDeviceIndexPin,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    validate_embedding_device_route_replay,
)


class EmbeddingBatchRouteError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_BATCH_ROUTE_MISMATCH")


def validate_embedding_batch_route(
    *,
    policy: EmbeddingDeviceRoutingPolicy,
    allocation: EmbeddingGpuAllocationObservation,
    decision: EmbeddingDeviceRoutingDecision,
    batch: EmbeddingWorkBatchInput,
    indexes: tuple[EmbeddingDeviceIndexPair, ...] = (),
) -> tuple[tuple[ExperimentView, EmbeddingDeviceIndexPin], ...]:
    """Validate exact selected numerical identity before launch/reservation.

    The root owner must first authenticate allocation evidence and retain the real
    GPU lease; Catalog must independently resolve/authorize paired index pointers.
    This pure closure reads no stores, acquires no resources and commits nothing.
    Its selected index is immutable: no latest or incomplete-device substitution.
    """
    selected = validate_embedding_device_route_replay(policy, allocation, decision).selected
    batch = parse_embedding_work_batch_input(batch)
    profile, resources = selected.profile, selected.profile.resource_profile
    expected_purpose = {"INDEX": "DOCUMENT", "REFERENCE_QUERY": "REFERENCE_QUERY"}.get(
        policy.purpose
    )
    if (
        type(indexes) is not tuple
        or batch.purpose != expected_purpose
        or batch.routing_decision_sha256 != decision.decision_sha256
        or batch.resource_profile_sha256 != resources.resource_profile_sha256
        or batch.timeout_seconds > resources.timeout_seconds
        or batch.expected_vector_bytes >= resources.output_max_bytes
    ):
        raise EmbeddingBatchRouteError()
    for child in batch.children:
        request = child.request
        if (
            child.space.model_spec != profile.space.model_spec
            or child.space.runtime != profile.space.runtime
            or request.batch_size != resources.batch_size
            or request.threads != resources.threads
        ):
            raise EmbeddingBatchRouteError()
        if isinstance(request, EmbeddingReferenceQueryInputV11):
            if (
                request.spaces.document != profile.space
                or request.recipe.recipe_sha256 != policy.view_recipe_sha256
            ):
                raise EmbeddingBatchRouteError()
        elif request.space != profile.space:
            raise EmbeddingBatchRouteError()
    if batch.purpose == "DOCUMENT":
        if indexes:
            raise EmbeddingBatchRouteError()
        return ()
    if not 1 <= len(indexes) <= len(VIEWS) or any(
        type(pair) is not EmbeddingDeviceIndexPair for pair in indexes
    ):
        raise EmbeddingBatchRouteError()
    by_view = {pair.view: pair for pair in indexes}
    requested_views = {
        row.view
        for child in batch.children
        if isinstance(child.request, EmbeddingReferenceQueryInputV11)
        for row in child.request.rows
    }
    if len(by_view) != len(indexes) or set(by_view) != requested_views:
        raise EmbeddingBatchRouteError()
    result: list[tuple[ExperimentView, EmbeddingDeviceIndexPin]] = []
    for view in VIEWS:
        if view not in requested_views:
            continue
        pair = by_view[view]
        index = pair.select(selected.backend.device)
        if (
            index.space != profile.space
            or pair.storage_partition != batch.scope.storage_partition
            or pair.recipe_sha256 != policy.view_recipe_sha256
        ):
            raise EmbeddingBatchRouteError()
        result.append((view, index))
    return tuple(result)
