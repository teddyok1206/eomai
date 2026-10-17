"""Original private completion through existing publishers and canonical readers."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_service.private_chat_query_artifact_read import CatalogPrivateChatQueryArtifacts
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_orchestrator.native_private_chat_query_handoff import PreparedNativePrivateChatQuery
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryCompleted,
    NativePrivateQueryExecuted,
    NativePrivateQueryPublished,
    native_private_chat_query_checkpoint,
    private_chat_query_checkpoint_receipt,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    NativeEmbeddingPublications,
    native_publication_identity,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_publication_read import (
    resolve_private_chat_query_publication,
)
from eom_workflow_runner.private_chat_query_source_read import (
    validate_current_private_chat_query_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


class NativePrivateChatQueryCompletion:
    def __init__(self, owner: CatalogPrivateChatQueryOwnerAdmission) -> None:
        self.owner = owner

    def publish(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        prepared: PreparedNativePrivateChatQuery,
        coordinator: NativePrivateChatQueryCoordinator,
        allocation: NativePrivateQueryAllocation,
        publications: NativeEmbeddingPublications,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutput:
        original = allocation.allocation
        if (
            prepared.workflow_request != request
            or coordinator.request != request
            or coordinator.launch != prepared.association
            or publications.artifacts.source_commit != original.source_commit
            or publications.completions.source_commit != original.source_commit
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_CONTEXT_INVALID")
        with fenced_transaction() as session:
            sources = self.owner.resolve_execution_sources(
                session,
                request,
                command_lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            validate_current_private_chat_query_input(
                sources, prepared.association, prepared.request
            )
            history = coordinator.read(session)
            if (
                len(history.records) < 2
                or history.state in {"FAILED", "CANCELLED"}
                or history.records[0].payload != allocation
                or sources.projection.origin != allocation.origin
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_NOT_OBSERVED")
            executed = history.records[1].payload
            if not isinstance(executed, NativePrivateQueryExecuted):
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_NOT_OBSERVED")
            if len(history.records) == 2:
                saved = publications.artifacts.publish_private_chat_query(
                    workflow_request=request,
                    policy=sources.policy,
                    bundle=sources.bundle,
                    launch=prepared.association,
                    request=prepared.request,
                    workspace=prepared.workspace,
                    created_at=executed.completed_observed_at,
                    identity=native_publication_identity(original.query_producer),
                    expected_result_sha256=executed.result_sha256,
                )
                coordinator.append(
                    session,
                    native_private_chat_query_checkpoint(
                        prepared.association,
                        "PUBLISHED",
                        NativePrivateQueryPublished(
                            query_owner_job_id=saved.owner_job_id,
                            execution_record=saved.intent,
                            result=saved.result,
                            shard=saved.shard,
                            binary=saved.binary,
                            manifest_sha256=saved.manifest_sha256,
                            published_observed_at=datetime.now(UTC),
                        ),
                    ),
                )
        # A distinct receipt commit must not wait on an uncommitted PUBLISHED row.
        with fenced_transaction() as session:
            sources = self.owner.resolve_execution_sources(
                session,
                request,
                command_lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            validate_current_private_chat_query_input(
                sources, prepared.association, prepared.request
            )
            history = coordinator.read(session)
            if (
                len(history.records) < 3
                or history.state in {"FAILED", "CANCELLED"}
                or history.records[0].payload != allocation
                or sources.projection.origin != allocation.origin
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_NOT_PUBLISHED")
            if len(history.records) == 4:
                completed = history.records[3].payload
                if not isinstance(completed, NativePrivateQueryCompleted):
                    raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_HISTORY_INVALID")
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
            executed, published = (record.payload for record in history.records[1:3])
            if not isinstance(executed, NativePrivateQueryExecuted) or not isinstance(
                published, NativePrivateQueryPublished
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_HISTORY_INVALID")
            receipt = private_chat_query_checkpoint_receipt(
                request, prepared.association, allocation, executed, published
            )
            canonical = CatalogPrivateChatQueryArtifacts(
                session, self.owner.settings
            ).resolve_publication(
                workflow_request=request,
                policy=sources.policy,
                bundle=sources.bundle,
                launch=prepared.association,
                native_input=prepared.request,
                receipt=receipt,
                origin=allocation.origin,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                receipt_owner_job_id=original.receipt_producer.job_id,
                manifest_sha256=published.manifest_sha256,
            )
            if canonical.result.result_sha256 != executed.result_sha256:
                raise ValueError("PRIVATE_CHAT_QUERY_CANONICAL_RESULT_MISMATCH")
            output = publications.completions.publish_private_chat_query(
                receipt, identity=native_publication_identity(original.receipt_producer)
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
                native_private_chat_query_checkpoint(
                    prepared.association, "COMPLETED", NativePrivateQueryCompleted(output=output)
                ),
            )
            return output

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: PrivateChatQueryStepOutput,
    ) -> PrivateChatQueryStepOutput:
        try:
            output = PrivateChatQueryStepOutput.model_validate(
                raw_similarity_contract_value(output)
            )
        except (ValueError, TypeError, SchemaError):
            raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_OUTPUT_INVALID") from None
        sources = self.owner.resolve_execution_sources(
            session,
            request,
            command_lease,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
        )
        resolve_private_chat_query_publication(
            self.owner.settings,
            session=session,
            workflow=workflow,
            step=step,
            sources=sources,
            output=output,
        )
        self.owner.fence_mutation(session, request, command_lease)
        return output
