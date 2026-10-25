"""Current original CPU-fallback read shared by document and reference-query applications."""

from __future__ import annotations

from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_workflow.embedding_batch_owner_control import validate_embedding_batch_owner_context
from eom_workflow.embedding_batch_plan_family import SupportedEmbeddingBatchRequest

from eom_workflow_runner.embedding_batch_execution import (
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
    UnavailableEmbeddingBatchExecution,
)


class EmbeddingBatchCpuRouteError(ValueError):
    def __init__(self) -> None:
        super().__init__("EMBEDDING_BATCH_CPU_ROUTE_INVALID")


def require_original_cpu_batch_route(
    operation: CatalogEmbeddingBatchExecution,
    parent: SupportedEmbeddingBatchRequest,
    original: ExistingEmbeddingBatchExecution | UnavailableEmbeddingBatchExecution,
) -> EmbeddingBatchPlanHistory:
    """Existing canonical PRE_EXECUTION BUSY, not an exception or a fresh device choice.

    No child transaction may be held by the caller. This function closes its
    short parent/source read before returning; it is not a cached permission.
    """
    if type(operation) is not CatalogEmbeddingBatchExecution or type(original) not in {
        ExistingEmbeddingBatchExecution,
        UnavailableEmbeddingBatchExecution,
    }:
        raise EmbeddingBatchCpuRouteError()
    with (
        operation.publisher.sessions.begin() as session,
        operation.admission.admit(session, parent) as sources,
    ):
        current = EmbeddingBatchPlanStore(parent, sources.selection, sources.policy).read(session)
        if (
            current is None
            or current.failure is not None
            or current.state not in {"RUNNING", "SUCCEEDED"}
            or current.allocation != original.history.allocation
            or current.route != original.history.route
            or current.route is None
        ):
            raise EmbeddingBatchCpuRouteError()
        observation = current.route.observation
        if (
            current.route.decision.selected.backend.device != "CPU"
            or current.route.decision.reason != "GPU_BUSY_CPU_FALLBACK"
            or observation.status != "BUSY"
            or observation.phase != "PRE_EXECUTION"
            or observation.cuda_launch_state != "NOT_STARTED"
        ):
            raise EmbeddingBatchCpuRouteError()
        if isinstance(original, UnavailableEmbeddingBatchExecution):
            if observation.allocation_reference_sha256 != original.root_observation.message_sha256:
                raise EmbeddingBatchCpuRouteError()
            validate_embedding_batch_owner_context(
                current.allocation.control_request,
                operation.controller_release,
                original.root_observation,
            )
        return current
