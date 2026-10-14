"""Current-owner QUERY completion: exact Job history plus canonical Artifact closure."""

from __future__ import annotations

from eom_catalog_service.local_embedding_completion_artifacts import (
    resolve_native_reference_query_completion,
)
from eom_catalog_service.reference_query_artifact_read import CatalogReferenceQueryArtifacts
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    read_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryCompleted,
    NativeQueryExecuted,
    NativeQueryPublished,
    reference_query_checkpoint_receipt,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    ReferenceQueryWorkflowRequest,
    parse_reference_query_step_output,
    validate_reference_query_launch_association,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    build_reference_query_native_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


class NativeReferenceQueryCompletion:
    """No numerical launch, current-authority cache or storage-only verified read.

    The caller holds an actual current command root. Completed unit observations
    are immutable provenance: reading a committed result must not rerun the model
    or require a historical systemd unit to survive forever.
    """

    def __init__(self, owner: CatalogReferenceQueryOwnerAdmission) -> None:
        self.owner = owner

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: ReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: ReferenceQueryStepOutput,
    ) -> ReferenceQueryStepOutput:
        output = parse_reference_query_step_output(output)
        sources = self.owner.resolve_execution_sources(
            session,
            request,
            command_lease,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
        )
        launch = read_native_reference_query_launch(
            session,
            request=request,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
        )
        if launch is None:
            raise ValueError("REFERENCE_QUERY_COMPLETION_COORDINATOR_MISSING")
        history = NativeReferenceQueryCoordinator(request, launch).read(session)
        if len(history.records) < 3 or history.state in {"FAILED", "CANCELLED"}:
            raise ValueError("REFERENCE_QUERY_COMPLETION_NOT_PUBLISHED")
        allocation, executed, published = (r.payload for r in history.records[:3])
        assert isinstance(allocation, NativeQueryAllocation)
        assert isinstance(executed, NativeQueryExecuted)
        assert isinstance(published, NativeQueryPublished)
        # Read the current step row, never trust a detached caller's producer field.
        current_step = session.get(WorkflowStepRunRecord, step.step_run_id, populate_existing=True)
        if (
            current_step is None
            or output.receipt.artifact_id != allocation.receipt_producer.artifact_id
            or output.receipt.artifact_revision_id
            != allocation.receipt_producer.artifact_revision_id
            or (
                current_step.platform_job_id is not None
                and current_step.platform_job_id != allocation.receipt_producer.job_id
            )
            or (
                len(history.records) == 4
                and history.records[3].payload != NativeQueryCompleted(output=output)
            )
        ):
            raise ValueError("REFERENCE_QUERY_COMPLETION_PRODUCER_MISMATCH")
        receipt = resolve_native_reference_query_completion(session, self.owner.settings, output)
        expected = reference_query_checkpoint_receipt(
            request, launch, allocation, executed, published
        )
        if receipt != expected:
            raise ValueError("REFERENCE_QUERY_COMPLETION_HISTORY_MISMATCH")
        resolved = CatalogReferenceQueryArtifacts(session, self.owner.settings).resolve_publication(
            workflow_request=request,
            policy=sources.policy,
            bundle=sources.bundle,
            launch=launch,
            receipt=receipt,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            receipt_owner_job_id=allocation.receipt_producer.job_id,
            manifest_sha256=published.manifest_sha256,
        )
        native_input = build_reference_query_native_input(
            sources, job_id=launch.native_launch_job_id, query_request_id=launch.query_request_id
        )
        validate_reference_query_launch_association(
            launch, request, sources.policy, sources.bundle, native_input
        )
        if (
            native_input != resolved.request
            or executed.result_sha256 != resolved.result.result_sha256
        ):
            raise ValueError("REFERENCE_QUERY_COMPLETION_CURRENT_INPUT_MISMATCH")
        self.owner.fence_mutation(session, request, command_lease)
        return output
