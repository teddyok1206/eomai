"""Original private CPU QUERY and four-phase continuation; no global activation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from eom_identifiers import content_sha256, new_job_id, new_revision_id
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.native_embedding_cpu_execution import validate_fixed_native_cpu_resources
from eom_orchestrator.native_private_chat_query_coordinator import (
    NativePrivateChatQueryCoordinator,
    NativePrivateChatQueryHistory,
)
from eom_orchestrator.native_private_chat_query_handoff import (
    NativePrivateQueryHandoffError,
    PreparedNativePrivateChatQuery,
    mark_native_private_query_launch_started,
    stage_native_private_chat_query,
)
from eom_orchestrator.native_private_chat_query_systemd import (
    FixedNativePrivateQueryLauncher,
    NativePrivateQueryLaunchError,
)
from eom_orchestrator.native_query_job_allocation import (
    create_native_query_launch,
    read_native_query_launch,
    require_native_query_root,
)
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryAllocation,
    NativePrivateQueryCompleted,
    native_private_chat_query_checkpoint,
)
from eom_workflow.native_reference_query_coordinator import NativeQueryAllocation
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_publication import PrivateChatQueryLaunchAssociation
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_completion import NativePrivateChatQueryCompletion
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryStepPending
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_source_read import (
    ResolvedPrivateChatQuerySources,
    build_private_chat_query_native_input,
    validate_current_private_chat_query_input,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


class CatalogNativePrivateChatQueryExecutor:
    def __init__(
        self,
        *,
        owner: CatalogPrivateChatQueryOwnerAdmission,
        publisher: ControlFileSetPublisher,
        launcher: FixedNativePrivateQueryLauncher,
        source_commit: str,
    ) -> None:
        owner.configuration.__post_init__()
        if (
            owner.catalog.engine is not publisher.engine
            or owner.settings.nas_artifact_root != publisher.settings.nas_artifact_root
            or not isinstance(launcher, FixedNativePrivateQueryLauncher)
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_OWNER_MISMATCH")
        EmbeddingArtifactStore(publisher, source_commit=source_commit)
        self.owner, self.publisher, self.launcher, self.source_commit = (
            owner,
            publisher,
            launcher,
            source_commit,
        )
        self.completion = NativePrivateChatQueryCompletion(owner)

    def evaluate(self, request: PrivateChatQueryWorkflowRequest) -> RuntimeReadinessReport:
        try:
            request = parse_private_chat_query_workflow_request(request)
            config = self.owner.configuration
            index = request.context_request.views[0].index
            if (
                request.native_execution_policy != config.native_execution_policy
                or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
                or request.runtime_bundle != config.runtime_bundle
                or index is None
                or index.spaces.document != config.registry.space
            ):
                raise ValueError()
            validate_fixed_native_cpu_resources(request.resource_profile)
            self.launcher.assert_current_runtime()
            check = RuntimeReadinessCheck(
                "native_cpu_private_query",
                ReadinessStatus.PASS,
                "PRIVATE_CHAT_QUERY_READY",
                "exact installed private CPU QUERY controls are available",
            )
        except (ValueError, OSError):
            check = RuntimeReadinessCheck(
                "native_cpu_private_query",
                ReadinessStatus.FAIL,
                "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE",
                "configured private CPU QUERY boundary is unavailable",
            )
        return RuntimeReadinessReport((check,))

    def _current(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        workflow_id: str,
        step_run_id: str,
    ) -> ResolvedPrivateChatQuerySources:
        return self.owner.resolve_execution_sources(
            session, request, lease, workflow_id=workflow_id, step_run_id=step_run_id
        )

    @staticmethod
    def _history(
        coordinator: NativePrivateChatQueryCoordinator, session: Session
    ) -> NativePrivateChatQueryHistory:
        history = coordinator.read(session)
        if history.state in {"FAILED", "CANCELLED"}:
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_TERMINAL_HISTORY")
        return history

    def _prepared(
        self,
        session: Session,
        sources: ResolvedPrivateChatQuerySources,
        workflow_id: str,
        step_run_id: str,
        lease: CommandLeaseIdentity,
    ) -> PreparedNativePrivateChatQuery:
        request = sources.request
        launch = read_native_query_launch(
            session, request=request, workflow_id=workflow_id, step_run_id=step_run_id
        )
        if launch is not None and not isinstance(launch, PrivateChatQueryLaunchAssociation):
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_PURPOSE_INVALID")
        job_id = new_job_id() if launch is None else launch.native_launch_job_id
        query_id = (
            "embeddingquery_" + new_revision_id().removeprefix("rev_")
            if launch is None
            else launch.query_request_id
        )
        native = build_private_chat_query_native_input(
            sources, job_id=job_id, query_request_id=query_id
        )
        if launch is None:
            if not self.evaluate(request).ready:
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_CONTEXT_INVALID")
            body = dict(
                schema_version="private-chat-query-launch-association/1.0",
                purpose="PRIVATE_CHAT_QUERY",
                workflow_id=workflow_id,
                step_run_id=step_run_id,
                step_key="encode_private_chat_query",
                attempt=1,
                workflow_request_sha256=request.request_sha256,
                context_request_sha256=request.context_request.request_sha256,
                basis_sha256=native.basis.basis_sha256,
                native_launch_job_id=job_id,
                query_request_id=query_id,
                query_request_sha256=native.request_sha256,
                query_input_set_sha256=native.input_set_sha256,
                recipe_sha256=native.document_recipe.recipe_sha256,
                runtime_bundle=request.runtime_bundle.model_dump(mode="json"),
                resource_profile_sha256=request.resource_profile.resource_profile_sha256,
                original_command_id=lease.command_id,
                original_command_generation=lease.lease_generation,
                launched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            candidate = PrivateChatQueryLaunchAssociation.model_validate(
                body | {"association_sha256": content_sha256(body)}
            )
            PreparedNativePrivateChatQuery(
                job_id.removeprefix("job_"),
                request,
                sources.policy,
                sources.bundle,
                candidate,
                native,
            )
            adopted = create_native_query_launch(session, request=request, launch=candidate)
            if not isinstance(adopted, PrivateChatQueryLaunchAssociation):
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_PURPOSE_INVALID")
            launch = adopted
            if launch != candidate:
                native = build_private_chat_query_native_input(
                    sources,
                    job_id=launch.native_launch_job_id,
                    query_request_id=launch.query_request_id,
                )
        return PreparedNativePrivateChatQuery(
            launch.native_launch_job_id.removeprefix("job_"),
            request,
            sources.policy,
            sources.bundle,
            launch,
            native,
        )

    def _allocate(
        self,
        session: Session,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        workflow_id: str,
        step_run_id: str,
    ) -> tuple[PreparedNativePrivateChatQuery, NativePrivateChatQueryHistory]:
        require_native_query_root(session)
        if session.get_bind() is not self.publisher.engine:
            raise ValueError("PRIVATE_CHAT_QUERY_ALLOCATION_OWNER_MISMATCH")
        sources = self._current(session, request, lease, workflow_id, step_run_id)
        prepared = self._prepared(session, sources, workflow_id, step_run_id, lease)
        coordinator = NativePrivateChatQueryCoordinator(request, prepared.association)
        history = self._history(coordinator, session)
        if not history.records:
            history = coordinator.append(
                session,
                native_private_chat_query_checkpoint(
                    prepared.association,
                    "ALLOCATION",
                    NativePrivateQueryAllocation(
                        allocation=NativeQueryAllocation(
                            query_producer=new_native_artifact_producer(),
                            receipt_producer=new_native_artifact_producer(),
                            created_at=datetime.now(UTC),
                            source_commit=self.source_commit,
                        ),
                        origin=sources.projection.origin,
                    ),
                ),
            )
        allocation = history.records[0].payload
        if (
            not isinstance(allocation, NativePrivateQueryAllocation)
            or allocation.origin != sources.projection.origin
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_ORIGIN_MISMATCH")
        return prepared, history

    def allocate_execution(
        self,
        *,
        session: Session,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
    ) -> PrivateChatQueryLaunchAssociation:
        request = parse_private_chat_query_workflow_request(request)
        prepared, _history = self._allocate(
            session, request, command_lease, workflow.workflow_id, step.step_run_id
        )
        return prepared.association

    def _pending(
        self,
        *,
        prepared: PreparedNativePrivateChatQuery,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        fenced: NativeFencedRunnerTransaction,
        reason: Literal["BUSY", "UNCERTAIN"],
    ) -> PrivateChatQueryStepOutput | PrivateChatQueryStepPending:
        with fenced() as session:
            self._current(session, request, lease, workflow.workflow_id, step.step_run_id)
            history = self._history(
                NativePrivateChatQueryCoordinator(request, prepared.association), session
            )
            if len(history.records) == 4:
                completed = history.records[3].payload
                if not isinstance(completed, NativePrivateQueryCompleted):
                    raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_HISTORY_INVALID")
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=lease,
                    output=completed.output,
                )
        return PrivateChatQueryStepPending(
            prepared.association.native_launch_job_id,
            prepared.association.association_sha256,
            reason,
        )

    def execute(
        self,
        *,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: PrivateChatQueryWorkflowRequest,
        command_lease: CommandLeaseIdentity,
        idempotency_key: str,
        fenced_transaction: NativeFencedRunnerTransaction,
    ) -> PrivateChatQueryStepOutput | PrivateChatQueryStepPending:
        request = parse_private_chat_query_workflow_request(request)
        expected = (
            f"private-chat-query-step:{workflow.workflow_id}:encode_private_chat_query:1:"
            f"{request.workflow_definition_sha256}"
        )
        if idempotency_key != expected:
            raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_CONTEXT_INVALID")
        with fenced_transaction() as session:
            prepared, history = self._allocate(
                session, request, command_lease, workflow.workflow_id, step.step_run_id
            )
            coordinator = NativePrivateChatQueryCoordinator(request, prepared.association)
            allocation = history.records[0].payload
            if not isinstance(allocation, NativePrivateQueryAllocation):
                raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_HISTORY_INVALID")
            if len(history.records) == 4:
                completed = history.records[3].payload
                if not isinstance(completed, NativePrivateQueryCompleted):
                    raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_HISTORY_INVALID")
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=command_lease,
                    output=completed.output,
                )
            if len(history.records) == 1:
                if not self.evaluate(request).ready:
                    return PrivateChatQueryStepPending(
                        prepared.association.native_launch_job_id,
                        prepared.association.association_sha256,
                        "UNCERTAIN",
                    )
                stage_native_private_chat_query(prepared)
                mark_native_private_query_launch_started(prepared)
        if len(history.records) == 1:
            try:
                result = self.launcher.run(prepared)
                observed = self.launcher.completion_observation(prepared, result)
            except NativePrivateQueryLaunchError as error:
                if error.code == "NATIVE_PRIVATE_QUERY_KNOWN_FAILED":
                    with fenced_transaction() as session:
                        self._current(
                            session, request, command_lease, workflow.workflow_id, step.step_run_id
                        )
                        coordinator.record_known_failure(session)
                    raise
                if error.code not in {
                    "NATIVE_PRIVATE_QUERY_BUSY",
                    "NATIVE_PRIVATE_QUERY_UNCERTAIN",
                    "NATIVE_PRIVATE_QUERY_COMPLETION_UNCERTAIN",
                    "NATIVE_PRIVATE_QUERY_CAPACITY_UNAVAILABLE",
                }:
                    raise
                return self._pending(
                    prepared=prepared,
                    workflow=workflow,
                    step=step,
                    request=request,
                    lease=command_lease,
                    fenced=fenced_transaction,
                    reason="BUSY" if error.code == "NATIVE_PRIVATE_QUERY_BUSY" else "UNCERTAIN",
                )
            except NativePrivateQueryHandoffError as error:
                if error.code == "NATIVE_PRIVATE_QUERY_OUTPUT_INVALID":
                    with fenced_transaction() as session:
                        self._current(
                            session, request, command_lease, workflow.workflow_id, step.step_run_id
                        )
                        coordinator.record_known_failure(session)
                    raise
                return self._pending(
                    prepared=prepared,
                    workflow=workflow,
                    step=step,
                    request=request,
                    lease=command_lease,
                    fenced=fenced_transaction,
                    reason="UNCERTAIN",
                )
            except (ValueError, OSError):
                return self._pending(
                    prepared=prepared,
                    workflow=workflow,
                    step=step,
                    request=request,
                    lease=command_lease,
                    fenced=fenced_transaction,
                    reason="UNCERTAIN",
                )
            with fenced_transaction() as session:
                current = self._current(
                    session, request, command_lease, workflow.workflow_id, step.step_run_id
                )
                validate_current_private_chat_query_input(
                    current, prepared.association, prepared.request
                )
                history = self._history(coordinator, session)
                if len(history.records) == 1:
                    coordinator.append(
                        session,
                        native_private_chat_query_checkpoint(
                            prepared.association, "EXECUTED", observed
                        ),
                    )
                elif history.records[1].payload.model_dump(
                    exclude={"completed_observed_at"}
                ) != observed.model_dump(exclude={"completed_observed_at"}):
                    raise ValueError("PRIVATE_CHAT_QUERY_EXECUTOR_OBSERVATION_CONFLICT")
        return self.completion.publish(
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=native_embedding_publications(
                self.publisher, allocation.allocation.source_commit
            ),
            fenced_transaction=fenced_transaction,
        )

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
        return self.completion.validate_completion(
            session=session,
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            output=output,
        )
