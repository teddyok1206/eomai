"""Protected child publication materialization, never a CPU handoff or numerical launch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.embedding_runtime_bundle import (
    EmbeddingRuntimeBundle,
    parse_embedding_runtime_bundle,
)
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_orchestrator.native_embedding_query_handoff import OWNER_ROOT
from eom_workflow.reference_query_execution import (
    ReferenceQueryExecutionPolicy,
    ReferenceQueryLaunchAssociation,
    SupportedReferenceQueryNativeInput,
    SupportedReferenceQueryNativeResult,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_execution_policy,
    parse_reference_query_launch_association,
    parse_reference_query_native_input,
    parse_supported_reference_query_workflow_request,
    validate_reference_query_launch_association,
    validate_reference_query_native_result,
)

from eom_workflow_runner.query_batch_publication_files import (
    QueryBatchPublicationFilesError,
    require_query_batch_publication_layout,
    stage_query_batch_publication_files,
)

QUERY_PUBLICATION_ROOT = OWNER_ROOT


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID")


def require_batch_query_publication_layout() -> None:
    try:
        require_query_batch_publication_layout(QUERY_PUBLICATION_ROOT, fixed_owner_identity())
    except QueryBatchPublicationFilesError:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID") from None


@dataclass(frozen=True, slots=True)
class PreparedBatchReferenceQuery:
    """Exact original values for the existing publisher; not a compute capability.

    Reuse the existing protected query publication root, not PreparedNativeQuery:
    its exact CPU guard remains unchanged and cannot launch these CUDA inputs.
    """

    workflow_request: SupportedReferenceQueryWorkflowRequest
    policy: ReferenceQueryExecutionPolicy
    bundle: EmbeddingRuntimeBundle
    association: ReferenceQueryLaunchAssociation
    request: SupportedReferenceQueryNativeInput

    def __post_init__(self) -> None:
        workflow = parse_supported_reference_query_workflow_request(self.workflow_request)
        policy = parse_reference_query_execution_policy(self.policy)
        bundle = parse_embedding_runtime_bundle(raw_similarity_contract_value(self.bundle))
        association = parse_reference_query_launch_association(self.association)
        request = parse_reference_query_native_input(workflow, self.request)
        validate_reference_query_launch_association(association, workflow, policy, bundle, request)
        _require(workflow.resource_profile.device == request.spaces.query.runtime.device == "CUDA")
        for name, value in (
            ("workflow_request", workflow),
            ("policy", policy),
            ("bundle", bundle),
            ("association", association),
            ("request", request),
        ):
            object.__setattr__(self, name, value)

    @property
    def workspace(self) -> Path:
        return QUERY_PUBLICATION_ROOT / self.association.native_launch_job_id.removeprefix("job_")


def stage_batch_query_publication(
    prepared: PreparedBatchReferenceQuery,
    result: SupportedReferenceQueryNativeResult,
    vectors: memoryview,
) -> None:
    """Caller retains current canonical receipt/source fences; no NAS or DB writes.

    The only binary copy is this explicit aggregate→child commit boundary. Exact
    replay never truncates an existing or partially written publication member.
    """
    _require(type(prepared) is PreparedBatchReferenceQuery)
    result = validate_reference_query_native_result(prepared.request, result)
    try:
        stage_query_batch_publication_files(
            QUERY_PUBLICATION_ROOT, fixed_owner_identity(), prepared.request, result, vectors
        )
    except QueryBatchPublicationFilesError:
        raise ValueError("REFERENCE_QUERY_BATCH_MATERIAL_INVALID") from None
