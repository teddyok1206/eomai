"""Current-owner QUERY completion: exact Job history plus canonical Artifact closure."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_service.reference_query_artifact_read import (
    CatalogReferenceQueryArtifacts,
    ResolvedReferenceQueryArtifacts,
)
from eom_orchestrator.native_embedding_query_handoff import PreparedNativeQuery
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    NativeReferenceQueryHistory,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryCompleted,
    NativeQueryExecuted,
    NativeQueryExecutedV11,
    NativeQueryPublished,
    native_reference_query_continuation_checkpoint,
    reference_query_checkpoint_receipt,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_step_output,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    NativeEmbeddingPublications,
    native_publication_identity,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    ResolvedReferenceQuerySources,
    validate_current_reference_query_input,
)
from eom_workflow_runner.reference_query_publication_read import resolve_reference_query_publication
from eom_workflow_runner.repository import CommandLeaseIdentity


class NativeReferenceQueryCompletion:
    """No numerical launch, current-authority cache or storage-only verified read.

    Execution callers hold an actual current command root; completed readers hold
    freshly resolved current read authority and terminal Workflow closure instead.
    Completed unit observations are immutable provenance: reading a committed
    result must not rerun the model or require a historical unit to survive forever.
    """

    def __init__(self, owner: CatalogReferenceQueryOwnerAdmission) -> None:
        self.owner = owner

    def publish(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        prepared: PreparedNativeQuery,
        coordinator: NativeReferenceQueryCoordinator,
        allocation: NativeQueryAllocation,
        publications: NativeEmbeddingPublications,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> ReferenceQueryStepOutput:
        if (
            prepared.workflow_request != request
            or coordinator.request != request
            or coordinator.launch != prepared.association
            or publications.artifacts.source_commit != allocation.source_commit
            or publications.completions.source_commit != allocation.source_commit
        ):
            raise ValueError("REFERENCE_QUERY_COMPLETION_PUBLICATION_CONTEXT_INVALID")
        with fenced_transaction() as session:
            sources = self.owner.resolve_execution_sources(
                session,
                request,
                command_lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            validate_current_reference_query_input(sources, prepared.association, prepared.request)
            history = coordinator.read(session)
            if (
                len(history.records) < 2
                or history.state in {"FAILED", "CANCELLED"}
                or history.records[0].payload != allocation
            ):
                raise ValueError("REFERENCE_QUERY_COMPLETION_EXECUTION_NOT_OBSERVED")
            executed = history.records[1].payload
            assert isinstance(executed, (NativeQueryExecuted, NativeQueryExecutedV11))
            if len(history.records) == 2:
                saved = publications.artifacts.publish_reference_query(
                    workflow_request=request,
                    policy=sources.policy,
                    bundle=sources.bundle,
                    launch=prepared.association,
                    request=prepared.request,
                    workspace=prepared.workspace,
                    created_at=executed.completed_observed_at,
                    identity=native_publication_identity(allocation.query_producer),
                    expected_result_sha256=executed.result_sha256,
                )
                coordinator.append(
                    session,
                    native_reference_query_continuation_checkpoint(
                        prepared.association,
                        "PUBLISHED",
                        NativeQueryPublished(
                            query_owner_job_id=saved.owner_job_id,
                            input=saved.input,
                            result=saved.result,
                            shard=saved.shard,
                            binary=saved.binary,
                            manifest_sha256=saved.manifest_sha256,
                            published_observed_at=datetime.now(UTC),
                        ),
                        previous=history.records,
                        initial_version=history.records[0].schema_version,
                    ),
                )
        # Commit PUBLISHED before the receipt owner's independent publication root.
        # Never hold an uncommitted checkpoint write across a second owner commit.
        with fenced_transaction() as session:
            sources = self.owner.resolve_execution_sources(
                session,
                request,
                command_lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            validate_current_reference_query_input(sources, prepared.association, prepared.request)
            history = coordinator.read(session)
            if (
                len(history.records) < 3
                or history.state in {"FAILED", "CANCELLED"}
                or history.records[0].payload != allocation
            ):
                raise ValueError("REFERENCE_QUERY_COMPLETION_NOT_PUBLISHED")
            if len(history.records) == 4:
                completed = history.records[3].payload
                assert isinstance(completed, NativeQueryCompleted)
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
            executed, published = (row.payload for row in history.records[1:3])
            assert isinstance(executed, (NativeQueryExecuted, NativeQueryExecutedV11))
            assert isinstance(published, NativeQueryPublished)
            receipt = reference_query_checkpoint_receipt(
                request, prepared.association, allocation, executed, published
            )
            canonical = CatalogReferenceQueryArtifacts(
                session, self.owner.settings
            ).resolve_publication(
                workflow_request=request,
                policy=sources.policy,
                bundle=sources.bundle,
                launch=prepared.association,
                receipt=receipt,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                receipt_owner_job_id=allocation.receipt_producer.job_id,
                manifest_sha256=published.manifest_sha256,
            )
            if (
                canonical.request != prepared.request
                or canonical.result.result_sha256 != executed.result_sha256
            ):
                raise ValueError("REFERENCE_QUERY_COMPLETION_CANONICAL_RESULT_MISMATCH")
            output = publications.completions.publish_reference_query(
                receipt, identity=native_publication_identity(allocation.receipt_producer)
            )
            self.validate_completion(
                session=session,
                workflow=workflow,
                step=step,
                request=request,
                command_lease=command_lease,
                output=output,
            )
            coordinator.append(
                session,
                native_reference_query_continuation_checkpoint(
                    prepared.association,
                    "COMPLETED",
                    NativeQueryCompleted(output=output),
                    previous=history.records,
                    initial_version=history.records[0].schema_version,
                ),
            )
            return output

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
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
        self.resolve_publication(
            session=session, workflow=workflow, step=step, sources=sources, output=output
        )
        self.owner.fence_mutation(session, request, command_lease)
        return output

    def resolve_publication(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        sources: ResolvedReferenceQuerySources,
        output: ReferenceQueryStepOutput,
    ) -> tuple[ResolvedReferenceQueryArtifacts, NativeReferenceQueryHistory]:
        return resolve_reference_query_publication(
            self.owner.settings,
            session=session,
            workflow=workflow,
            step=step,
            sources=sources,
            output=output,
        )
