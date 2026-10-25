"""CUDA QUERY executor over existing Runner allocation, finite group and canonical completion."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    NativeReferenceQueryHistory,
    create_native_reference_query_launch,
    read_native_reference_query_launch,
)
from eom_workflow.embedding_batch_plan_family import embedding_batch_query_key
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryBatchExecuted,
    NativeQueryCompleted,
    native_reference_query_continuation_checkpoint,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_source_authorization import ReferenceQueryBatchSource
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.reference_query_batch_execution_read import (
    resolve_reference_query_batch_execution,
    validate_reference_query_batch_child_result,
)
from eom_workflow_runner.reference_query_batch_group import (
    CatalogReferenceQueryBatchGroup,
    PreparedReferenceQueryBatchChild,
)
from eom_workflow_runner.reference_query_batch_material import (
    PreparedBatchReferenceQuery,
    require_batch_query_publication_layout,
    stage_batch_query_publication,
)
from eom_workflow_runner.reference_query_completion import NativeReferenceQueryCompletion
from eom_workflow_runner.reference_query_launch_preparation import (
    prepare_reference_query_launch_candidate,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("REFERENCE_QUERY_BATCH_EXECUTOR_INVALID")


class CatalogBatchReferenceQueryExecutor:
    """Existing native executor port; no CPU flag, Role worker or standalone launcher."""

    def __init__(self, group: CatalogReferenceQueryBatchGroup) -> None:
        _require(type(group) is CatalogReferenceQueryBatchGroup)
        self.group, self.owner, self.publisher = group, group.owner, group.publisher
        self.completion = NativeReferenceQueryCompletion(self.owner)

    def evaluate(self, request: SupportedReferenceQueryWorkflowRequest) -> RuntimeReadinessReport:
        try:
            request = parse_supported_reference_query_workflow_request(request)
            self.group.ordinal(request)
            self.group.assert_available()
            require_batch_query_publication_layout()
            status, code = ReadinessStatus.PASS, "REFERENCE_QUERY_BATCH_READY"
        except (ValueError, OSError):
            status, code = ReadinessStatus.FAIL, "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE"
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "finite_cuda_query", status, code, "original finite QUERY batch boundary"
                ),
            )
        )

    def _prepared(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
    ) -> tuple[PreparedBatchReferenceQuery, NativeReferenceQueryHistory]:
        root = session.get_transaction()
        _require(root is not None and root.is_active and not session.in_nested_transaction())
        _require(session.get_bind() is self.publisher.engine)
        ordinal = self.group.ordinal(request)
        sources = self.owner.resolve_execution_sources(
            session, request, lease, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        current = session.get(WorkflowInstanceRecord, workflow.workflow_id, populate_existing=True)
        _require(
            current is not None
            and current.idempotency_key
            == embedding_batch_query_key(self.group.active.request, ordinal)
        )
        self.group.assert_available()
        require_batch_query_publication_layout()
        launch = read_native_reference_query_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        fresh = launch is None
        if fresh:
            self.group.assert_gathering()
        candidate = prepare_reference_query_launch_candidate(
            sources,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            command_lease=lease,
            existing=launch,
        )
        prepared = PreparedBatchReferenceQuery(
            request, sources.policy, sources.bundle, candidate.association, candidate.request
        )
        self.group.assert_original_material(prepared)
        if launch is None:
            launch = create_native_reference_query_launch(
                session, request=request, launch=candidate.association
            )
            _require(launch == candidate.association)
        coordinator = NativeReferenceQueryCoordinator(request, launch)
        history = coordinator.read(session)
        _require(history.state not in {"FAILED", "CANCELLED"})
        if not history.records:
            _require(fresh)
            history = coordinator.append(
                session,
                native_reference_query_continuation_checkpoint(
                    launch,
                    "ALLOCATION",
                    NativeQueryAllocation(
                        query_producer=new_native_artifact_producer(),
                        receipt_producer=new_native_artifact_producer(),
                        created_at=datetime.now(UTC),
                        source_commit=self.group.source_commit,
                    ),
                    previous=(),
                    initial_version="native-reference-query-coordinator/1.2",
                ),
            )
        _require(
            1 <= len(history.records) <= 4
            and history.records[0].schema_version == "native-reference-query-coordinator/1.2"
        )
        return prepared, history

    def allocate_execution(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
    ) -> ReferenceQueryLaunchAssociation:
        prepared, _history = self._prepared(
            session,
            workflow,
            step,
            parse_supported_reference_query_workflow_request(request),
            command_lease,
        )
        return prepared.association

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> ReferenceQueryStepOutput:
        request = parse_supported_reference_query_workflow_request(request)
        _require(
            idempotency_key
            == (
                f"reference-query-step:{workflow.workflow_id}:encode_reference_query:1:"
                f"{request.workflow_definition_sha256}"
            )
        )
        with fenced_transaction() as session:
            prepared, history = self._prepared(session, workflow, step, request, command_lease)
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
        coordinator = NativeReferenceQueryCoordinator(request, prepared.association)
        allocation = history.records[0].payload
        assert isinstance(allocation, NativeQueryAllocation)

        @contextmanager
        def source_transaction() -> Iterator[Session]:
            # Leader/root callbacks can run in another Runner thread. Explicit
            # identities preserve this child, never the caller's ContextVar.
            with native_fenced_runner_transaction(
                self.publisher.sessions,
                owner=self.owner,
                workflow_id=workflow.workflow_id,
                request=request,
                lease=command_lease,
            ) as session:
                yield session

        ordinal = self.group.ordinal(request)
        saved = self.group.join(
            PreparedReferenceQueryBatchChild(
                ordinal,
                prepared,
                ReferenceQueryBatchSource(
                    self.owner, request, prepared.association, command_lease, source_transaction
                ),
            )
        )
        verified = saved.verified
        child_result = verified.result.children[ordinal].result
        _require(isinstance(child_result, EmbeddingReferenceQueryResult))
        assert isinstance(child_result, EmbeddingReferenceQueryResult)
        observed = NativeQueryBatchExecuted(
            batch_receipt=saved.publication.member,
            batch_receipt_sha256=saved.publication.semantic_sha256,
            child_ordinal=ordinal,
            result_sha256=child_result.result_sha256,
            completed_observed_at=verified.completed.retired_at,
        )
        with fenced_transaction() as session:
            sources = self.owner.resolve_execution_sources(
                session,
                request,
                command_lease,
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
            )
            child = resolve_reference_query_batch_execution(
                session,
                reader=PinnedArtifactReadContext.for_session(session, self.owner.settings),
                sources=sources,
                launch=prepared.association,
                native_input=prepared.request,
                executed=observed,
            )
            validate_reference_query_batch_child_result(child, child_result)
            history = coordinator.read(session)
            _require(history.records[0].payload == allocation)
            if len(history.records) == 1:
                history = coordinator.append(
                    session,
                    native_reference_query_continuation_checkpoint(
                        prepared.association,
                        "EXECUTED",
                        observed,
                        previous=history.records,
                        initial_version=history.records[0].schema_version,
                    ),
                )
            else:
                _require(history.records[1].payload == observed)
        # Canonical proof/current source was checked above; no SQL root survives
        # the explicit local→child publication materialization boundary.
        if len(history.records) == 2:
            verified.assert_current()
            stage_batch_query_publication(prepared, child_result, verified.child_vectors[ordinal])
        return self.completion.publish(
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=native_embedding_publications(self.publisher, allocation.source_commit),
            fenced_transaction=fenced_transaction,
        )

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
        return self.completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            output=output,
        )
