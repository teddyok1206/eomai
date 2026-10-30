"""Close a planned device decision over one staged batch, not an execution grant."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query_v11 import EmbeddingReferenceQueryInputV11
from eom_catalog_contracts.embedding_work_batch import (
    SupportedEmbeddingWorkBatchInput,
)
from eom_catalog_contracts.inference_transfer_experiment import VIEWS, ExperimentView
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_catalog_service.embedding_device_index_pair import (
    EmbeddingDeviceIndexPair,
    EmbeddingDeviceIndexPin,
)
from eom_workflow.embedding_device_routing import (
    EmbeddingDeviceRoutingDecision,
    EmbeddingDeviceRoutingPolicy,
    EmbeddingGpuAllocationObservation,
    validate_embedding_device_batch_profile,
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
    batch: SupportedEmbeddingWorkBatchInput,
    indexes: tuple[EmbeddingDeviceIndexPair, ...] = (),
) -> tuple[tuple[ExperimentView, EmbeddingDeviceIndexPin], ...]:
    """Validate exact selected numerical identity before launch/reservation.

    The root owner must first authenticate allocation evidence and retain the real
    GPU lease; Catalog must independently resolve/authorize paired index pointers.
    This pure closure reads no stores, acquires no resources and commits nothing.
    Its selected index is immutable: no latest or incomplete-device substitution.
    """
    selected = validate_embedding_device_route_replay(policy, allocation, decision).selected
    profile = selected.profile
    if type(indexes) is not tuple:
        raise EmbeddingBatchRouteError()
    try:
        batch = validate_embedding_device_batch_profile(policy, decision, batch)
    except ValueError:
        raise EmbeddingBatchRouteError() from None
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
        if isinstance(child.request, EmbeddingReferenceQueryInputV11 | PublicSolutionQueryInput)
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
