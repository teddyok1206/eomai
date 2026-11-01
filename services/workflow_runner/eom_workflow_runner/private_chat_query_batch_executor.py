"""One original private CUDA QUERY through existing finite execution and native completion."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Lock
from typing import overload

from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_orchestrator.embedding_batch_plan_store import (
    EmbeddingBatchPlanHistory,
    EmbeddingBatchPlanStore,
)
from eom_orchestrator.local_embedding_control_artifacts import (
    LocalEmbeddingControlArtifactPublisher,
)
from eom_orchestrator.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCoordinator,
    NativePrivateChatQueryHistory,
)
from eom_orchestrator.native_query_job_allocation import (
    create_native_query_launch,
    read_native_query_launch,
    require_native_query_root,
)
from eom_workflow.embedding_batch_execution_receipt import PrivateChatBatchExecutionReceipt
from eom_workflow.embedding_batch_plan_v17 import (
    EmbeddingBatchPlanRequestV17,
    validate_private_batch_query_context,
)
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryBatchExecuted,
    NativePrivateQueryCompletedV2,
    native_private_chat_gpu_query_checkpoint,
    native_private_chat_query_continuation_checkpoint,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_execution_v2 import (
    PrivateChatQueryWorkflowRequestV2,
    SupportedPrivateChatQueryWorkflowRequest,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_submission_context import private_chat_query_origin_key
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from eom_workflow.private_chat_query_workflow_v2 import (
    PrivateChatQueryStepOutputV2,
    SupportedPrivateChatQueryStepOutput,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.embedding_batch_execution import (
    ActiveEmbeddingBatchExecution,
    CatalogEmbeddingBatchExecution,
    ExistingEmbeddingBatchExecution,
)
from eom_workflow_runner.embedding_batch_result_read import read_completed_embedding_batch_result
from eom_workflow_runner.embedding_batch_source_authorization import (
    CatalogEmbeddingBatchSourceAuthorization,
    PrivateChatQueryBatchSource,
)
from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.private_chat_batch_plan_admission import (
    CatalogPrivateChatBatchPlanAdmission,
)
from eom_workflow_runner.private_chat_query_batch_material import (
    PreparedBatchPrivateChatQuery,
    require_private_batch_query_publication_layout,
    stage_private_batch_query_publication,
)
from eom_workflow_runner.private_chat_query_completion import NativePrivateChatQueryCompletion
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryStepPending
from eom_workflow_runner.private_chat_query_launch_preparation import (
    prepare_private_chat_query_launch_candidate,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import ResolvedPrivateChatPublicQuerySources
from eom_workflow_runner.query_batch_binding import prepare_private_chat_query_batch_binding
from eom_workflow_runner.query_batch_execution_read import (
    read_query_batch_execution_receipt,
    resolve_private_chat_query_batch_execution,
    validate_query_batch_child_result,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("PRIVATE_CHAT_QUERY_BATCH_EXECUTOR_INVALID")


class CatalogBatchPrivateChatQueryExecutor:
    """A single private child, not a group, new queue or public-owner impersonation.

    The original parent/allocation and private origin key remain authoritative.
    The operation-local lock prevents a second dispatch in this process; existing
    DB claims/unique histories retain cross-process ownership. A canonical receipt
    permits cold read, never a new physical root. No SQL root spans GPU math.
    """

    def __init__(
        self,
        operation: CatalogEmbeddingBatchExecution,
        request: EmbeddingBatchPlanRequestV17,
        original: ActiveEmbeddingBatchExecution | ExistingEmbeddingBatchExecution,
        owner: CatalogPrivateChatQueryOwnerAdmission,
    ) -> None:
        _require(type(operation) is CatalogEmbeddingBatchExecution)
        admission = operation.admission
        _require(type(admission) is CatalogPrivateChatBatchPlanAdmission)
        assert isinstance(admission, CatalogPrivateChatBatchPlanAdmission)
        _require(
            type(owner) is CatalogPrivateChatQueryOwnerAdmission
            and admission.cuda is owner
            and operation.publisher.engine is owner.catalog.engine
            and operation.publisher.settings.nas_artifact_root == owner.settings.nas_artifact_root
            and type(original) in {ActiveEmbeddingBatchExecution, ExistingEmbeddingBatchExecution}
        )
        request = EmbeddingBatchPlanRequestV17.model_validate(request)
        if isinstance(original, ActiveEmbeddingBatchExecution):
            _require(original.operation is operation and original.request == request)
        route = original.history.route
        _require(route is not None and original.history.failure is None)
        assert route is not None
        _require(route.decision.selected.backend.device == "CUDA")
        with (
            operation.publisher.sessions.begin() as session,
            admission.admit(session, request) as sources,
        ):
            selection, policy = sources.selection, sources.policy
            current = EmbeddingBatchPlanStore(request, selection, policy).read(session)
            _require(current == original.history)
        self.operation, self.parent, self.original, self.owner = operation, request, original, owner
        self.selection, self.routing, self.route = selection, policy, route
        self.publisher = operation.publisher
        self.controls = LocalEmbeddingControlArtifactPublisher(
            self.publisher, source_commit=operation.source_commit
        )
        self.completion = NativePrivateChatQueryCompletion(owner)
        self._lock, self._dispatched = Lock(), False

    def _request(
        self, request: SupportedPrivateChatQueryWorkflowRequest
    ) -> PrivateChatQueryWorkflowRequestV2:
        _require(type(request) is PrivateChatQueryWorkflowRequestV2)
        assert isinstance(request, PrivateChatQueryWorkflowRequestV2)
        request = PrivateChatQueryWorkflowRequestV2.model_validate(request)
        validate_private_batch_query_context(
            self.parent, self.selection, self.route.decision, 0, request
        )
        config = self.owner.configuration
        _require(
            request.resource_profile.device == "CUDA"
            and request.native_execution_policy == config.native_execution_policy
            and request.native_execution_policy_sha256 == config.native_execution_policy_sha256
            and request.runtime_bundle == config.runtime_bundle
            and config.registry.space == self.route.decision.selected.profile.space
        )
        return request

    def evaluate(self, request: SupportedPrivateChatQueryWorkflowRequest) -> RuntimeReadinessReport:
        try:
            self._request(request)
            require_private_batch_query_publication_layout()
            if isinstance(self.original, ActiveEmbeddingBatchExecution) and not self._dispatched:
                self.original.channel.require_direct_peer()
            status, code = ReadinessStatus.PASS, "PRIVATE_CHAT_QUERY_BATCH_READY"
        except (ValueError, OSError):
            status, code = ReadinessStatus.FAIL, "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE"
        return RuntimeReadinessReport(
            (
                RuntimeReadinessCheck(
                    "finite_cuda_private_query",
                    status,
                    code,
                    "original private finite QUERY boundary",
                ),
            )
        )

    def _parent_history(self, session: Session) -> EmbeddingBatchPlanHistory:
        admission = self.operation.admission
        assert isinstance(admission, CatalogPrivateChatBatchPlanAdmission)
        with admission.admit(session, self.parent) as sources:
            _require(sources.selection == self.selection and sources.policy == self.routing)
            history = EmbeddingBatchPlanStore(self.parent, sources.selection, sources.policy).read(
                session
            )
        original = self.original.history
        _require(
            history is not None
            and history.failure is None
            and history.state in {"RUNNING", "SUCCEEDED"}
            and history.job_id == original.job_id
            and history.allocation == original.allocation
            and history.route == original.route
        )
        assert history is not None
        return history

    def _prepared(
        self,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequestV2,
        lease: CommandLeaseIdentity,
    ) -> tuple[PreparedBatchPrivateChatQuery, NativePrivateChatQueryHistory]:
        require_native_query_root(session)
        _require(session.get_bind() is self.publisher.engine)
        parent = self._parent_history(session)
        sources = self.owner.resolve_execution_sources(
            session, request, lease, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        _require(type(sources) is ResolvedPrivateChatPublicQuerySources)
        assert isinstance(sources, ResolvedPrivateChatPublicQuerySources)
        current = session.get(WorkflowInstanceRecord, workflow.workflow_id, populate_existing=True)
        _require(
            current is not None
            and current.idempotency_key == private_chat_query_origin_key(self.selection.origin)
        )
        launch = read_native_query_launch(
            session, request=request, workflow_id=workflow.workflow_id, step_run_id=step.step_run_id
        )
        _require(launch is None or type(launch) is PrivateChatQueryLaunchAssociation)
        assert launch is None or isinstance(launch, PrivateChatQueryLaunchAssociation)
        fresh = launch is None
        if fresh:
            _require(
                isinstance(self.original, ActiveEmbeddingBatchExecution)
                and parent.bound is None
                and not self._dispatched
            )
            assert isinstance(self.original, ActiveEmbeddingBatchExecution)
            self.original.channel.require_direct_peer()
            require_private_batch_query_publication_layout()
        candidate = prepare_private_chat_query_launch_candidate(
            sources,
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            command_lease=lease,
            existing=launch,
        )
        _require(type(candidate.request) is PublicSolutionQueryInput)
        assert isinstance(candidate.request, PublicSolutionQueryInput)
        material = PreparedBatchPrivateChatQuery(
            request, sources.policy, sources.bundle, candidate.association, candidate.request
        )
        if fresh:
            adopted = create_native_query_launch(
                session, request=request, launch=candidate.association
            )
            _require(adopted == candidate.association)
        coordinator = NativePrivateChatQueryCoordinator(request, material.association)
        history = coordinator.read(session)
        _require(history.state not in {"FAILED", "CANCELLED"})
        if not history.records:
            _require(fresh)
            history = coordinator.append(
                session,
                native_private_chat_gpu_query_checkpoint(
                    material.association,
                    "ALLOCATION",
                    NativePrivateQueryAllocation(
                        allocation=NativeQueryAllocation(
                            query_producer=new_native_artifact_producer(),
                            receipt_producer=new_native_artifact_producer(),
                            created_at=datetime.now(UTC),
                            source_commit=self.operation.source_commit,
                        ),
                        origin=sources.projection.origin,
                    ),
                ),
            )
        _require(
            1 <= len(history.records) <= 4
            and history.records[0].schema_version == "native-private-chat-query-coordinator/2.1"
        )
        allocation = history.records[0].payload
        _require(
            type(allocation) is NativePrivateQueryAllocation
            and allocation.origin == sources.projection.origin
        )
        return material, history

    def allocate_execution(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedPrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
    ) -> PrivateChatQueryLaunchAssociation:
        prepared, _ = self._prepared(session, workflow, step, self._request(request), command_lease)
        return prepared.association

    @overload
    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutput | PrivateChatQueryStepPending: ...

    @overload
    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequestV2,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutputV2 | PrivateChatQueryStepPending: ...

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedPrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> SupportedPrivateChatQueryStepOutput | PrivateChatQueryStepPending:
        checked = self._request(request)
        _require(
            idempotency_key
            == (
                f"private-chat-query-step:{workflow.workflow_id}:encode_private_chat_query:1:"
                f"{checked.workflow_definition_sha256}"
            )
        )
        # Busy observation never waits holding the caller's SQL/source root.
        if not self._lock.acquire(blocking=False):
            with fenced_transaction() as session:
                self.owner.resolve_execution_sources(
                    session,
                    checked,
                    command_lease,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                )
                launch = read_native_query_launch(
                    session,
                    request=checked,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                )
                _require(type(launch) is PrivateChatQueryLaunchAssociation)
                assert isinstance(launch, PrivateChatQueryLaunchAssociation)
            return PrivateChatQueryStepPending(
                launch.native_launch_job_id,
                launch.association_sha256,
                "BUSY",
            )
        try:
            return self._execute(workflow, step, checked, command_lease, fenced_transaction)
        finally:
            self._lock.release()

    def _execute(
        self,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequestV2,
        lease: CommandLeaseIdentity,
        fenced: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutputV2 | PrivateChatQueryStepPending:
        with fenced() as session:
            prepared, history = self._prepared(session, workflow, step, request, lease)
            if len(history.records) == 4:
                completed = history.records[3].payload
                _require(type(completed) is NativePrivateQueryCompletedV2)
                assert isinstance(completed, NativePrivateQueryCompletedV2)
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=lease,
                    output=completed.output,
                )
        coordinator = NativePrivateChatQueryCoordinator(request, prepared.association)
        allocation = history.records[0].payload
        assert isinstance(allocation, NativePrivateQueryAllocation)
        if len(history.records) < 3:

            @contextmanager
            def source_transaction() -> Iterator[Session]:
                with native_fenced_runner_transaction(
                    self.publisher.sessions,
                    owner=self.owner,
                    workflow_id=workflow.workflow_id,
                    request=request,
                    lease=lease,
                ) as session:
                    yield session

            bound, batch = prepare_private_chat_query_batch_binding(
                self.parent, self.route, prepared
            )
            authorization = CatalogEmbeddingBatchSourceAuthorization(
                batch,
                (
                    PrivateChatQueryBatchSource(
                        self.owner, request, prepared.association, lease, source_transaction
                    ),
                ),
            )
            pointer = self.controls.find_batch_execution_receipt(
                parent_request_sha256=self.parent.request_sha256,
                allocation_record_sha256=self.original.history.allocation.record_sha256,
            )
            if pointer is not None:
                with fenced() as session:
                    sources = self.owner.resolve_execution_sources(
                        session,
                        request,
                        lease,
                        workflow_id=workflow.workflow_id,
                        step_run_id=step.step_run_id,
                    )
                    _require(type(sources) is ResolvedPrivateChatPublicQuerySources)
                    assert isinstance(sources, ResolvedPrivateChatPublicQuerySources)
                    reader = PinnedArtifactReadContext.for_session(session, self.owner.settings)
                    receipt = read_query_batch_execution_receipt(reader, pointer)
                    _require(
                        type(receipt) is PrivateChatBatchExecutionReceipt
                        and receipt.bound.binding == bound
                    )
                    assert isinstance(receipt, PrivateChatBatchExecutionReceipt)
                    observed = NativePrivateQueryBatchExecuted(
                        batch_receipt=pointer,
                        batch_receipt_sha256=receipt.receipt_sha256,
                        child_ordinal=0,
                        result_sha256=receipt.children[0].result_sha256,
                        completed_observed_at=receipt.completed.retired_at,
                    )
                    resolve_private_chat_query_batch_execution(
                        session,
                        reader=reader,
                        sources=sources,
                        launch=prepared.association,
                        native_input=prepared.request,
                        executed=observed,
                    )
                verified = read_completed_embedding_batch_result(
                    receipt, authorization=authorization
                )
            else:
                with fenced() as session:
                    current_parent = self._parent_history(session)
                if (
                    self._dispatched
                    or not isinstance(self.original, ActiveEmbeddingBatchExecution)
                    or current_parent.bound is not None
                    or len(history.records) != 1
                ):
                    return PrivateChatQueryStepPending(
                        prepared.association.native_launch_job_id,
                        prepared.association.association_sha256,
                        "UNCERTAIN",
                    )
                self._dispatched = True
                saved = self.original.run(bound, batch, authorization=authorization)
                verified = saved.verified
                observed = NativePrivateQueryBatchExecuted(
                    batch_receipt=saved.publication.member,
                    batch_receipt_sha256=saved.publication.semantic_sha256,
                    child_ordinal=0,
                    result_sha256=verified.result.children[0].result.result_sha256,
                    completed_observed_at=verified.completed.retired_at,
                )
            result = verified.result.children[0].result
            _require(type(result) is PublicSolutionQueryResult)
            assert isinstance(result, PublicSolutionQueryResult)
            with fenced() as session:
                sources = self.owner.resolve_execution_sources(
                    session,
                    request,
                    lease,
                    workflow_id=workflow.workflow_id,
                    step_run_id=step.step_run_id,
                )
                _require(type(sources) is ResolvedPrivateChatPublicQuerySources)
                assert isinstance(sources, ResolvedPrivateChatPublicQuerySources)
                child = resolve_private_chat_query_batch_execution(
                    session,
                    reader=PinnedArtifactReadContext.for_session(session, self.owner.settings),
                    sources=sources,
                    launch=prepared.association,
                    native_input=prepared.request,
                    executed=observed,
                )
                validate_query_batch_child_result(child, result)
                history = coordinator.read(session)
                _require(
                    history.records[0].payload == allocation
                    and history.state not in {"FAILED", "CANCELLED"}
                )
                if len(history.records) == 1:
                    history = coordinator.append(
                        session,
                        native_private_chat_query_continuation_checkpoint(
                            request,
                            prepared.association,
                            "EXECUTED",
                            observed,
                            previous=history.records,
                        ),
                    )
                else:
                    _require(history.records[1].payload == observed)
            if len(history.records) == 2:
                verified.assert_current()
                stage_private_batch_query_publication(prepared, result, verified.child_vectors[0])
        output = self.completion.publish(
            workflow=workflow,
            step=step,
            request=request,
            command_lease=lease,
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=native_embedding_publications(
                self.publisher, allocation.allocation.source_commit
            ),
            fenced_transaction=fenced,
        )
        _require(type(output) is PrivateChatQueryStepOutputV2)
        assert isinstance(output, PrivateChatQueryStepOutputV2)
        return output

    @overload
    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        output: PrivateChatQueryStepOutput,
    ) -> PrivateChatQueryStepOutput: ...

    @overload
    def validate_completion(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequestV2,
        command_lease: CommandLeaseIdentity,
        output: PrivateChatQueryStepOutputV2,
    ) -> PrivateChatQueryStepOutputV2: ...

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
        checked = self._request(request)
        _require(type(output) is PrivateChatQueryStepOutputV2)
        assert isinstance(output, PrivateChatQueryStepOutputV2)
        return self.completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=checked,
            command_lease=command_lease,
            output=output,
        )
