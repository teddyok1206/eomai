"""Current-owner fixed CPU QUERY execution and original-checkpoint continuation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from eom_identifiers import content_sha256, new_job_id, new_revision_id
from eom_orchestrator.embedding_artifact_store import EmbeddingArtifactStore
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.native_embedding_cpu_execution import validate_fixed_native_cpu_resources
from eom_orchestrator.native_embedding_query_handoff import (
    PreparedNativeQuery,
    mark_native_query_launch_started,
    stage_native_query,
)
from eom_orchestrator.native_embedding_query_systemd import (
    FixedNativeQueryLauncher,
    NativeQueryLaunchError,
)
from eom_orchestrator.native_reference_query_coordinator import (
    NativeReferenceQueryCoordinator,
    NativeReferenceQueryHistory,
    create_native_reference_query_launch,
    read_native_reference_query_launch,
)
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryAllocation,
    NativeQueryCompleted,
    NativeQueryExecuted,
    native_reference_query_checkpoint,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryLaunchAssociation,
    ReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowRequest,
    parse_reference_query_launch_association,
    parse_supported_reference_query_workflow_request,
)
from sqlalchemy.orm import Session

from eom_workflow_runner.local_embedding_execution_port import NativeFencedRunnerTransaction
from eom_workflow_runner.local_embedding_publications import (
    native_embedding_publications,
    new_native_artifact_producer,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
)
from eom_workflow_runner.reference_query_completion import NativeReferenceQueryCompletion
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryStepPending
from eom_workflow_runner.reference_query_owner_admission import (
    CatalogReferenceQueryOwnerAdmission,
    ResolvedReferenceQuerySources,
    build_reference_query_native_input,
    validate_current_reference_query_input,
)
from eom_workflow_runner.repository import CommandLeaseIdentity


def _require_allocation_root(session: Session) -> None:
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise ValueError("REFERENCE_QUERY_ALLOCATION_ROOT_REQUIRED")


class CatalogNativeReferenceQueryExecutor:
    """Explicit composition only; no global admission, fallback or default activation."""

    def __init__(
        self,
        *,
        owner: CatalogReferenceQueryOwnerAdmission,
        publisher: ControlFileSetPublisher,
        launcher: FixedNativeQueryLauncher,
        source_commit: str,
    ) -> None:
        owner.configuration.__post_init__()
        if owner.catalog.engine is not publisher.engine or (
            owner.settings.nas_artifact_root != publisher.settings.nas_artifact_root
        ):
            raise ValueError("REFERENCE_QUERY_EXECUTOR_OWNER_MISMATCH")
        # Validate provenance without touching a model, unit, database or artifact.
        EmbeddingArtifactStore(publisher, source_commit=source_commit)
        self.owner, self.publisher, self.launcher = owner, publisher, launcher
        self.source_commit = source_commit
        self.completion = NativeReferenceQueryCompletion(owner)

    def evaluate(self, request: SupportedReferenceQueryWorkflowRequest) -> RuntimeReadinessReport:
        try:
            request = parse_supported_reference_query_workflow_request(request)
            config = self.owner.configuration
            indexes = tuple(v.index for v in request.context_request.views if v.index is not None)
            if (
                request.native_execution_policy != config.native_execution_policy
                or request.native_execution_policy_sha256 != config.native_execution_policy_sha256
                or request.runtime_bundle != config.runtime_bundle
                or not indexes
                or any(i.spaces.document != config.registry.space for i in indexes)
            ):
                raise ValueError("configured QUERY controls differ")
            validate_fixed_native_cpu_resources(request.resource_profile)
            self.launcher.assert_current_runtime()
            check = RuntimeReadinessCheck(
                "native_cpu_query",
                ReadinessStatus.PASS,
                "REFERENCE_QUERY_READY",
                "exact installed CPU QUERY controls are available",
            )
        except (ValueError, OSError):
            check = RuntimeReadinessCheck(
                "native_cpu_query",
                ReadinessStatus.FAIL,
                "LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE",
                "configured CPU QUERY boundary is unavailable",
            )
        return RuntimeReadinessReport((check,))

    def _current(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        workflow_id: str,
        step_run_id: str,
    ) -> ResolvedReferenceQuerySources:
        return self.owner.resolve_execution_sources(
            session, request, lease, workflow_id=workflow_id, step_run_id=step_run_id
        )

    @staticmethod
    def _history(
        owner: NativeReferenceQueryCoordinator, session: Session
    ) -> NativeReferenceQueryHistory:
        history = owner.read(session)
        if history.state in {"FAILED", "CANCELLED"}:
            raise ValueError("REFERENCE_QUERY_EXECUTOR_TERMINAL_HISTORY")
        return history

    def _prepared(
        self,
        session: Session,
        sources: ResolvedReferenceQuerySources,
        workflow_id: str,
        step_run_id: str,
        lease: CommandLeaseIdentity,
    ) -> PreparedNativeQuery:
        request = sources.request
        launch = read_native_reference_query_launch(
            session, request=request, workflow_id=workflow_id, step_run_id=step_run_id
        )
        job_id = new_job_id() if launch is None else launch.native_launch_job_id
        query_id = (
            "embeddingquery_" + new_revision_id().removeprefix("rev_")
            if launch is None
            else launch.query_request_id
        )
        native_input = build_reference_query_native_input(
            sources, job_id=job_id, query_request_id=query_id
        )
        if launch is None:
            body = {
                "schema_version": "reference-query-launch-association/1.0",
                "purpose": "REFERENCE_QUERY",
                "workflow_id": workflow_id,
                "step_run_id": step_run_id,
                "step_key": "encode_reference_query",
                "attempt": 1,
                "workflow_request_sha256": request.request_sha256,
                "context_request_sha256": request.context_request.request_sha256,
                "native_launch_job_id": job_id,
                "query_request_id": query_id,
                "query_request_sha256": native_input.request_sha256,
                "query_input_set_sha256": native_input.input_set_sha256,
                "recipe_sha256": native_input.recipe.recipe_sha256,
                "runtime_bundle": request.runtime_bundle.model_dump(mode="json"),
                "resource_profile_sha256": request.resource_profile.resource_profile_sha256,
                "original_command_id": lease.command_id,
                "original_command_generation": lease.lease_generation,
                "launched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
            launch = parse_reference_query_launch_association(
                body | {"association_sha256": content_sha256(body)}
            )
            # Check the complete handoff before allocating the durable Job.
            PreparedNativeQuery(
                job_id.removeprefix("job_"),
                request,
                sources.policy,
                sources.bundle,
                launch,
                native_input,
            )
            launch = create_native_reference_query_launch(session, request=request, launch=launch)
        return PreparedNativeQuery(
            launch.native_launch_job_id.removeprefix("job_"),
            request,
            sources.policy,
            sources.bundle,
            launch,
            native_input,
        )

    def _pending(
        self,
        *,
        prepared: PreparedNativeQuery,
        workflow: WorkflowInstanceRecord,
        step: WorkflowStepRunRecord,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        fenced: NativeFencedRunnerTransaction,
        reason: Literal["BUSY", "UNCERTAIN"],
    ) -> ReferenceQueryStepOutput | ReferenceQueryStepPending:
        with fenced() as session:
            self._current(session, request, lease, workflow.workflow_id, step.step_run_id)
            history = self._history(
                NativeReferenceQueryCoordinator(request, prepared.association), session
            )
            if len(history.records) == 4:
                completed = history.records[3].payload
                assert isinstance(completed, NativeQueryCompleted)
                return self.validate_completion(
                    session=session,
                    workflow=workflow,
                    step=step,
                    request=request,
                    command_lease=lease,
                    output=completed.output,
                )
        return ReferenceQueryStepPending(
            prepared.association.native_launch_job_id,
            prepared.association.association_sha256,
            reason,
        )

    def _allocate_in_session(
        self,
        session: Session,
        request: SupportedReferenceQueryWorkflowRequest,
        lease: CommandLeaseIdentity,
        workflow_id: str,
        step_run_id: str,
    ) -> tuple[PreparedNativeQuery, NativeReferenceQueryHistory]:
        """One original allocation path, never staging or physical execution."""
        _require_allocation_root(session)
        if session.get_bind() is not self.publisher.engine:
            raise ValueError("REFERENCE_QUERY_ALLOCATION_OWNER_MISMATCH")
        sources = self._current(session, request, lease, workflow_id, step_run_id)
        prepared = self._prepared(session, sources, workflow_id, step_run_id, lease)
        coordinator = NativeReferenceQueryCoordinator(request, prepared.association)
        history = self._history(coordinator, session)
        if not history.records:
            history = coordinator.append(
                session,
                native_reference_query_checkpoint(
                    prepared.association,
                    "ALLOCATION",
                    NativeQueryAllocation(
                        query_producer=new_native_artifact_producer(),
                        receipt_producer=new_native_artifact_producer(),
                        created_at=datetime.now(UTC),
                        source_commit=self.source_commit,
                    ),
                ),
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
        """Persist allocation in the caller's step-start root, without launch or commit."""
        _require_allocation_root(session)
        request = parse_supported_reference_query_workflow_request(request)
        if not self.evaluate(request).ready:
            raise ValueError("REFERENCE_QUERY_EXECUTOR_CONTEXT_INVALID")
        prepared, _history = self._allocate_in_session(
            session, request, command_lease, workflow.workflow_id, step.step_run_id
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
    ) -> ReferenceQueryStepOutput | ReferenceQueryStepPending:
        request = parse_supported_reference_query_workflow_request(request)
        expected_key = (
            f"reference-query-step:{workflow.workflow_id}:encode_reference_query:1:"
            f"{request.workflow_definition_sha256}"
        )
        if not self.evaluate(request).ready or idempotency_key != expected_key:
            raise ValueError("REFERENCE_QUERY_EXECUTOR_CONTEXT_INVALID")
        with fenced_transaction() as session:
            prepared, history = self._allocate_in_session(
                session, request, command_lease, workflow.workflow_id, step.step_run_id
            )
            coordinator = NativeReferenceQueryCoordinator(request, prepared.association)
            allocation = history.records[0].payload
            assert isinstance(allocation, NativeQueryAllocation)
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
            if len(history.records) == 1:
                stage_native_query(prepared)
                mark_native_query_launch_started(prepared)
        # No Session/root/Workflow lock survives a numerical run or unit observation.
        if len(history.records) == 1:
            try:
                result = self.launcher.run(prepared)
                observed = self.launcher.completion_observation(prepared, result)
            except NativeQueryLaunchError as error:
                if error.code == "NATIVE_QUERY_KNOWN_FAILED":
                    with fenced_transaction() as session:
                        self._current(
                            session, request, command_lease, workflow.workflow_id, step.step_run_id
                        )
                        coordinator.record_known_failure(session)
                    raise
                if error.code not in {
                    "NATIVE_QUERY_BUSY",
                    "NATIVE_QUERY_UNCERTAIN",
                    "NATIVE_QUERY_COMPLETION_UNCERTAIN",
                    "NATIVE_QUERY_CAPACITY_UNAVAILABLE",
                }:
                    raise
                return self._pending(
                    prepared=prepared,
                    workflow=workflow,
                    step=step,
                    request=request,
                    lease=command_lease,
                    fenced=fenced_transaction,
                    reason="BUSY" if error.code == "NATIVE_QUERY_BUSY" else "UNCERTAIN",
                )
            except (ValueError, OSError):
                # A lost observation is not proof of worker failure or permission to retry.
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
                validate_current_reference_query_input(
                    current, prepared.association, prepared.request
                )
                history = self._history(coordinator, session)
                if len(history.records) == 1:
                    history = coordinator.append(
                        session,
                        native_reference_query_checkpoint(
                            prepared.association, "EXECUTED", observed
                        ),
                    )
                else:
                    original = history.records[1].payload
                    assert isinstance(original, NativeQueryExecuted)
                    if original.model_dump(
                        exclude={"completed_observed_at"}
                    ) != observed.model_dump(exclude={"completed_observed_at"}):
                        raise ValueError("REFERENCE_QUERY_EXECUTOR_OBSERVATION_CONFLICT")
        publications = native_embedding_publications(self.publisher, allocation.source_commit)
        return self.completion.publish(
            workflow=workflow,
            step=step,
            request=request,
            command_lease=command_lease,
            prepared=prepared,
            coordinator=coordinator,
            allocation=allocation,
            publications=publications,
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
