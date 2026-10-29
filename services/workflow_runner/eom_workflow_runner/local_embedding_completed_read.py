"""Current-owner read of a completed registered document Workflow, never a historical lease."""

from eom_catalog_service.embedding_registry_application import (
    verify_embedding_index_registration_observation,
)
from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_embedding_completion,
)
from eom_catalog_service.local_embedding_encoding_artifacts import (
    CatalogLocalEmbeddingEncodingArtifacts,
)
from eom_orchestrator.native_embedding_coordinator import NativeEmbeddingCoordinator
from eom_orchestrator.native_embedding_launch_identity import (
    read_native_embedding_launch,
    read_native_embedding_launch_association,
)
from eom_workflow.local_embedding_request_v2 import (
    parse_supported_local_embedding_request,
    supported_local_embedding_request_actor,
)
from eom_workflow.local_embedding_workflow_receipt_v2 import (
    SupportedLocalEmbeddingStepOutput,
    parse_supported_local_embedding_step_output,
    validate_supported_local_embedding_workflow_receipt,
)
from eom_workflow.native_embedding_coordinator import NativeCoordinatorCompleted
from eom_workflow.native_embedding_coordinator_v2 import NativeCoordinatorCompletedV2
from eom_workflow.native_embedding_coordinator_v3 import NativeCoordinatorCompletedV3
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_completion_coverage import resolved_native_index_coverage
from eom_workflow_runner.local_embedding_owner_admission import CatalogLocalEmbeddingOwnerAdmission
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("LOCAL_EMBEDDING_COMPLETED_READ_INVALID")


def read_completed_local_embedding(
    session: Session,
    owner: CatalogLocalEmbeddingOwnerAdmission,
    workflow: WorkflowInstanceRecord,
) -> SupportedLocalEmbeddingStepOutput:
    """No permission reconstructed from stored actor IDs or expired command tokens.

    Trusted composition supplies its actual current owner. Canonical receipt,
    coordinator and registered-index reads remain their existing public owners.
    """
    _require(type(owner) is CatalogLocalEmbeddingOwnerAdmission)
    current = session.get(WorkflowInstanceRecord, workflow.workflow_id, populate_existing=True)
    _require(current is not None)
    assert current is not None
    workflow = current
    request = parse_supported_local_embedding_request(workflow.initial_request)
    sources = owner.resolve_sources(session, request)
    actor_kind, actor_id = supported_local_embedding_request_actor(request)
    _require(
        workflow.state == workflow.stage == "COMPLETED"
        and workflow.definition_hash == request.workflow_definition_sha256
        and workflow.created_actor_type == actor_kind
        and workflow.created_actor_id == actor_id
    )
    step = session.scalar(
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id == workflow.workflow_id,
            WorkflowStepRunRecord.step_key == "encode_batch",
            WorkflowStepRunRecord.attempt == 1,
        )
        .execution_options(populate_existing=True)
    )
    _require(step is not None and step.state == "SUCCEEDED")
    assert step is not None
    output = parse_supported_local_embedding_step_output(step.output_pointer_manifest)
    receipt = resolve_native_embedding_completion(session, owner.settings, output)
    launch = read_native_embedding_launch(
        session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
    )
    _require(launch is not None)
    assert launch is not None
    history = NativeEmbeddingCoordinator(launch.intent, request).read(session)
    _require(history.state == "SUCCEEDED" and len(history.records) == 4)
    completed = history.records[3].payload
    _require(
        isinstance(
            completed,
            (
                NativeCoordinatorCompleted,
                NativeCoordinatorCompletedV2,
                NativeCoordinatorCompletedV3,
            ),
        )
    )
    assert isinstance(
        completed,
        (NativeCoordinatorCompleted, NativeCoordinatorCompletedV2, NativeCoordinatorCompletedV3),
    )
    _require(
        completed.output == output
        and output.workflow_id == workflow.workflow_id
        and output.step_run_id == step.step_run_id
        and output.receipt_owner_job_id == step.platform_job_id
    )
    resolved = verify_embedding_index_registration_observation(
        session,
        owner.registry_caller(request),
        receipt.registration_command,
        receipt.registration_result,
        owner.catalog,
    )
    association = read_native_embedding_launch_association(session, launch.intent, request)
    native_input = (
        None
        if association is None
        else CatalogLocalEmbeddingEncodingArtifacts(session, owner.settings).resolve_input(
            association
        )
    )
    validate_supported_local_embedding_workflow_receipt(
        receipt,
        request,
        sources.admission.plan,
        sources.admission.policy,
        workflow_id=workflow.workflow_id,
        step_run_id=step.step_run_id,
        receipt_owner_job_id=output.receipt_owner_job_id,
        launch_association=association,
        owned_input=native_input,
        index_coverage=resolved_native_index_coverage(resolved),
    )
    # Materialization is not a durable permission decision.
    owner.fence_current_actor(session, request)
    return output
