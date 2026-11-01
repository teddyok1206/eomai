"""Original private completion through existing publishers and canonical readers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from eom_catalog_contracts.embedding_private_chat_query import (
    EmbeddingPrivateChatQueryInput,
    SupportedPrivateNumericalQueryInput,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryInput
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_query_artifact_read import (
    CatalogPrivateChatQueryArtifacts,
    ResolvedPrivateChatPublicQueryArtifacts,
)
from eom_orchestrator.native_private_chat_query_coordinator import NativePrivateChatQueryCoordinator
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryBatchExecuted,
    NativePrivateQueryCompleted,
    NativePrivateQueryCompletedV2,
    NativePrivateQueryExecuted,
    NativePrivateQueryPublished,
    NativePrivateQueryPublishedV2,
    native_private_chat_query_continuation_checkpoint,
    supported_private_chat_query_checkpoint_receipt,
)
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryWorkflowRequestV2,
    SupportedPrivateChatQueryWorkflowRequest,
    parse_supported_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    SupportedPrivateChatQueryStepOutput,
    parse_supported_private_chat_query_step_output,
)
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
    resolve_supported_private_chat_query_publication,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatPublicQuerySources,
    validate_supported_current_private_chat_query_input,
)
from eom_workflow_runner.query_batch_execution_read import (
    resolve_private_chat_query_batch_execution,
    validate_query_batch_child_result,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


class PrivateChatQueryPublicationMaterial(Protocol):
    """Already materialized CPU/GPU child values, never a physical launch capability."""

    @property
    def workflow_request(self) -> SupportedPrivateChatQueryWorkflowRequest: ...
    @property
    def association(self) -> PrivateChatQueryLaunchAssociation: ...
    @property
    def request(self) -> SupportedPrivateNumericalQueryInput: ...
    @property
    def workspace(self) -> Path: ...


class NativePrivateChatQueryCompletion:
    def __init__(self, owner: CatalogPrivateChatQueryOwnerAdmission) -> None:
        self.owner = owner

    def publish(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedPrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        prepared: PrivateChatQueryPublicationMaterial,
        coordinator: NativePrivateChatQueryCoordinator,
        allocation: NativePrivateQueryAllocation,
        publications: NativeEmbeddingPublications,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> SupportedPrivateChatQueryStepOutput:
        request = parse_supported_private_chat_query_workflow_request(request)
        native = prepared.request
        if (
            isinstance(request, PrivateChatQueryWorkflowRequestV2)
            and not isinstance(native, PublicSolutionQueryInput)
        ) or (
            not isinstance(request, PrivateChatQueryWorkflowRequestV2)
            and not isinstance(native, EmbeddingPrivateChatQueryInput)
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_CONTEXT_INVALID")
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
            validate_supported_current_private_chat_query_input(
                sources, prepared.association, native
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
            if not isinstance(
                executed, (NativePrivateQueryExecuted, NativePrivateQueryBatchExecuted)
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTION_NOT_OBSERVED")
            if isinstance(executed, NativePrivateQueryBatchExecuted):
                if not isinstance(sources, ResolvedPrivateChatPublicQuerySources) or not isinstance(
                    native, PublicSolutionQueryInput
                ):
                    raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_CONTEXT_INVALID")
                resolve_private_chat_query_batch_execution(
                    session,
                    reader=PinnedArtifactReadContext.for_session(session, self.owner.settings),
                    sources=sources,
                    launch=prepared.association,
                    native_input=native,
                    executed=executed,
                )
            if len(history.records) == 2:
                published_type = (
                    NativePrivateQueryPublishedV2
                    if isinstance(request, PrivateChatQueryWorkflowRequestV2)
                    else NativePrivateQueryPublished
                )
                saved = publications.artifacts.publish_private_chat_query(
                    workflow_request=request,
                    policy=sources.policy,
                    bundle=sources.bundle,
                    launch=prepared.association,
                    request=native,
                    workspace=prepared.workspace,
                    created_at=executed.completed_observed_at,
                    identity=native_publication_identity(original.query_producer),
                    expected_result_sha256=executed.result_sha256,
                )
                coordinator.append(
                    session,
                    native_private_chat_query_continuation_checkpoint(
                        request,
                        prepared.association,
                        "PUBLISHED",
                        published_type(
                            query_owner_job_id=saved.owner_job_id,
                            execution_record=saved.intent,
                            result=saved.result,
                            shard=saved.shard,
                            binary=saved.binary,
                            manifest_sha256=saved.manifest_sha256,
                            published_observed_at=datetime.now(UTC),
                        ),
                        previous=history.records,
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
            validate_supported_current_private_chat_query_input(
                sources, prepared.association, native
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
                if not isinstance(
                    completed, (NativePrivateQueryCompleted, NativePrivateQueryCompletedV2)
                ):
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
            if not isinstance(
                executed, (NativePrivateQueryExecuted, NativePrivateQueryBatchExecuted)
            ) or not isinstance(
                published, (NativePrivateQueryPublished, NativePrivateQueryPublishedV2)
            ):
                raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_HISTORY_INVALID")
            receipt = supported_private_chat_query_checkpoint_receipt(
                request, prepared.association, allocation, executed, published
            )
            canonical = CatalogPrivateChatQueryArtifacts(
                session, self.owner.settings
            ).resolve_supported_publication(
                workflow_request=request,
                policy=sources.policy,
                bundle=sources.bundle,
                launch=prepared.association,
                native_input=native,
                receipt=receipt,
                origin=allocation.origin,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                receipt_owner_job_id=original.receipt_producer.job_id,
                manifest_sha256=published.manifest_sha256,
            )
            if canonical.result.result_sha256 != executed.result_sha256:
                raise ValueError("PRIVATE_CHAT_QUERY_CANONICAL_RESULT_MISMATCH")
            if isinstance(executed, NativePrivateQueryBatchExecuted):
                if (
                    not isinstance(sources, ResolvedPrivateChatPublicQuerySources)
                    or not isinstance(native, PublicSolutionQueryInput)
                    or not isinstance(canonical, ResolvedPrivateChatPublicQueryArtifacts)
                ):
                    raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_CONTEXT_INVALID")
                child = resolve_private_chat_query_batch_execution(
                    session,
                    reader=PinnedArtifactReadContext.for_session(session, self.owner.settings),
                    sources=sources,
                    launch=prepared.association,
                    native_input=native,
                    executed=executed,
                )
                validate_query_batch_child_result(child, canonical.result)
            output = publications.completions.publish_supported_private_chat_query(
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
            completed_output: NativePrivateQueryCompleted | NativePrivateQueryCompletedV2
            if isinstance(output, PrivateChatQueryStepOutputV2):
                completed_output = NativePrivateQueryCompletedV2(output=output)
            else:
                completed_output = NativePrivateQueryCompleted(output=output)
            coordinator.append(
                session,
                native_private_chat_query_continuation_checkpoint(
                    request,
                    prepared.association,
                    "COMPLETED",
                    completed_output,
                    previous=history.records,
                ),
            )
            return output

    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedPrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: SupportedPrivateChatQueryStepOutput,
    ) -> SupportedPrivateChatQueryStepOutput:
        try:
            output = parse_supported_private_chat_query_step_output(
                raw_similarity_contract_value(output)
            )
            if isinstance(request, PrivateChatQueryWorkflowRequestV2) != isinstance(
                output, PrivateChatQueryStepOutputV2
            ):
                raise ValueError()
        except (ValueError, TypeError, SchemaError):
            raise ValueError("PRIVATE_CHAT_QUERY_COMPLETION_OUTPUT_INVALID") from None
        sources = self.owner.resolve_execution_sources(
            session,
            request,
            command_lease,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
        )
        resolve_supported_private_chat_query_publication(
            self.owner.settings,
            session=session,
            workflow=workflow,
            step=step,
            sources=sources,
            output=output,
        )
        self.owner.fence_mutation(session, request, command_lease)
        return output
