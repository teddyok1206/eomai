"""One pure ordered QUERY binding constructor for finite CUDA and fixed-CPU fallback."""

from __future__ import annotations

from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_SECONDS,
    MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
    SupportedEmbeddingWorkBatchInput,
    parse_supported_embedding_work_batch_input,
)
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_identifiers import content_sha256
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_workflow.embedding_batch_plan import (
    BATCH_PLAN_PROTOCOL,
    EmbeddingBatchBound,
    EmbeddingBatchRoute,
)
from eom_workflow.embedding_batch_plan_family import (
    SupportedEmbeddingBatchRequest,
    validate_embedding_batch_binding,
)
from eom_workflow.embedding_batch_plan_v14 import EmbeddingBatchPlanRequestV14

from eom_workflow_runner.reference_query_batch_material import PreparedBatchReferenceQuery


def prepare_reference_query_batch_binding(
    parent: SupportedEmbeddingBatchRequest,
    route: EmbeddingBatchRoute,
    materials: tuple[PreparedNativeQuery | PreparedBatchReferenceQuery, ...],
) -> tuple[EmbeddingBatchBound, SupportedEmbeddingWorkBatchInput]:
    """Metadata/value construction only; current source, lease and route grants are separate.

    Preserve existing CUDA canonical bytes. A CPU value remains a genuine
    PreparedNativeQuery accepted by the unchanged fixed CPU handoff/launcher.
    """
    if (
        parent.purpose != "REFERENCE_QUERY"
        or type(materials) is not tuple
        or len(materials) != len(parent.child_selection_sha256s)
        or any(
            type(value) not in {PreparedNativeQuery, PreparedBatchReferenceQuery}
            for value in materials
        )
    ):
        raise ValueError("REFERENCE_QUERY_BATCH_BINDING_INVALID")
    public = isinstance(parent, EmbeddingBatchPlanRequestV14)
    if any(isinstance(value.request, PublicSolutionQueryInput) != public for value in materials):
        raise ValueError("REFERENCE_QUERY_BATCH_BINDING_INVALID")
    scope = parent.scope
    resources = route.decision.selected.profile.resource_profile
    body = dict(
        schema_version="embedding-work-batch-input/2.0"
        if public
        else "embedding-work-batch-input/1.0",
        purpose="REFERENCE_QUERY",
        scope=scope.model_dump(mode="json"),
        routing_decision_sha256=route.decision.decision_sha256,
        resource_profile_sha256=resources.resource_profile_sha256,
        timeout_seconds=min(resources.timeout_seconds, MAX_EMBEDDING_WORK_BATCH_SECONDS),
        vector_max_bytes=MAX_EMBEDDING_WORK_BATCH_VECTOR_BYTES,
        children=[
            dict(scope_sha256=scope.scope_sha256, request=value.request.model_dump(mode="json"))
            for value in materials
        ],
    )
    batch = parse_supported_embedding_work_batch_input(
        body | {"request_sha256": content_sha256(body)}
    )
    binding_body = dict(
        schema_version=BATCH_PLAN_PROTOCOL,
        message_type="BOUND",
        request_sha256=parent.request_sha256,
        route_record_sha256=route.record_sha256,
        batch_request_sha256=batch.request_sha256,
        resource_profile_sha256=resources.resource_profile_sha256,
        children=[
            dict(
                selection_sha256=parent.child_selection_sha256s[ordinal],
                workflow_id=value.association.workflow_id,
                step_run_id=value.association.step_run_id,
                native_job_id=value.association.native_launch_job_id,
                workflow_request_sha256=value.workflow_request.request_sha256,
                launch_association_sha256=value.association.association_sha256,
                native_input_sha256=value.request.request_sha256,
            )
            for ordinal, value in enumerate(materials)
        ],
    )
    binding = EmbeddingBatchBound.model_validate(
        binding_body | {"record_sha256": content_sha256(binding_body)}
    )
    validate_embedding_batch_binding(parent, route, binding, batch)
    return binding, batch
