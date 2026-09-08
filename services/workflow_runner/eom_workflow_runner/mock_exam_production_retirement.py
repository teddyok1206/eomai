"""Fail-closed retirement of one exact mock-exam production Workflow cohort.

This adapter is intentionally usable while the Workflow runner is held inactive.  It performs no
worker execution and no NAS operation.  One transaction fences every older claimable command,
cancels any platform job that has not crossed the artifact-commit boundary, queues the ordinary
Workflow cancellation command, and appends an audit event for every cohort member.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Never, cast

from eom_api_contracts.mock_exam_execution import MockExamProductionExecutionV1
from eom_api_contracts.mock_exam_retirement import (
    MockExamProductionRetirementBindingV1,
    MockExamProductionRetirementCommandV1,
    MockExamProductionRetirementOutcomeV1,
    MockExamProductionRetirementReceiptV1,
    WorkflowRetirementSourceState,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.workflow_job_retirement import (
    WorkflowJobRetirementBinding,
    fence_workflow_platform_jobs,
    require_no_held_worker_leases,
    require_workflow_platform_jobs_fenced,
)
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    enqueue_command,
    load_persisted_workflow_request,
)
from eom_workflow_runner.retirement_quiescence import (
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256,
    WORKFLOW_RUNNER_FRAGMENT_PATH,
    ExpiredLeaseReconciliationPort,
    WorkflowRunnerQuiescenceEvidence,
    WorkflowRunnerQuiescencePort,
)
from eom_workflow_runner.state_machine import (
    ACTIVE_WORKFLOW_STATES,
    CommandState,
    WorkflowState,
    record_workflow_event,
    transition_command,
)

_RETIREMENT_EVENT = "WORKFLOW_PRODUCTION_RETIREMENT_REQUESTED"
_RETIREMENT_REASON = "SUPERSEDED_BY_CORRECTED_PROTOCOL"
_CANCEL_REASON = "production occurrence superseded by corrected protocol"


class MockExamProductionRetirementError(RuntimeError):
    """Stable operator-safe retirement failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MockExamProductionRetirementService:
    """Prepare a CAS snapshot and atomically fence one exact 25-Workflow occurrence."""

    def __init__(
        self,
        engine: Engine,
        *,
        quiescence: WorkflowRunnerQuiescencePort,
        lease_reconciler: ExpiredLeaseReconciliationPort,
    ) -> None:
        self._sessions = build_session_factory(engine)
        self._quiescence = quiescence
        self._lease_reconciler = lease_reconciler

    def retire(
        self,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionRetirementReceiptV1:
        _require_utc(at)
        self._require_runner_quiescence()
        if actor.actor_id != checkpoint.operator_id:
            _fail(
                "PRODUCTION_RETIREMENT_OPERATOR_MISMATCH",
                "the retirement actor does not own the production execution",
            )
        rows = _checkpoint_workflow_rows(checkpoint)
        workflow_ids = tuple(row.workflow_id for row in rows)
        retirement_id = _retirement_id(checkpoint)
        # Prove the complete owned occurrence before the orchestrator is allowed to reconcile
        # even an expired lease. Preparation and execution deliberately revalidate after this
        # read-only preflight to retain the existing TOCTOU/CAS defenses.
        with self._sessions() as session:
            self._preflight_exact_scope(
                session,
                checkpoint=checkpoint,
                rows=rows,
                retirement_id=retirement_id,
            )
            replay = self._replay_receipt(
                session,
                checkpoint=checkpoint,
                retirement_id=retirement_id,
            )
            if replay is not None:
                return replay
        # The orchestrator owns lease state and exact worker-unit inspection. Reconciliation is
        # cohort-scoped so retirement can never sweep an unrelated expired lease.
        self._lease_reconciler.reconcile_expired_for_workflows(
            workflow_ids,
            observed_at=at,
        )
        with self._sessions() as session:
            replay = self._replay_receipt(
                session,
                checkpoint=checkpoint,
                retirement_id=retirement_id,
            )
            if replay is not None:
                return replay
            command = self._prepare_command(
                session,
                checkpoint=checkpoint,
                retirement_id=retirement_id,
                at=at,
            )
        return self._execute(command, checkpoint=checkpoint)

    def _preflight_exact_scope(
        self,
        session: Session,
        *,
        checkpoint: MockExamProductionExecutionV1,
        rows: tuple[_PinnedWorkflowRow, ...],
        retirement_id: str,
    ) -> None:
        """Validate all persisted ownership pointers without changing durable state."""

        workflow_ids = tuple(row.workflow_id for row in rows)
        workflows = _load_workflows(session, workflow_ids, for_update=False)
        _reject_other_retirement(session, workflow_ids, retirement_id=retirement_id)
        for row in rows:
            _validate_occurrence_member(
                session,
                workflow=workflows[row.workflow_id],
                checkpoint=checkpoint,
                workflow_call_id=row.workflow_call_id,
                start_command_id=row.start_command_id,
            )

    def _prepare_command(
        self,
        session: Session,
        *,
        checkpoint: MockExamProductionExecutionV1,
        retirement_id: str,
        at: datetime,
    ) -> MockExamProductionRetirementCommandV1:
        rows = _checkpoint_workflow_rows(checkpoint)
        workflow_ids = tuple(row.workflow_id for row in rows)
        workflows = _load_workflows(session, workflow_ids, for_update=False)
        _reject_other_retirement(session, workflow_ids, retirement_id=retirement_id)
        require_no_held_worker_leases(session, workflow_ids)
        bindings: list[MockExamProductionRetirementBindingV1] = []
        for row in rows:
            workflow = workflows[row.workflow_id]
            _validate_occurrence_member(
                session,
                workflow=workflow,
                checkpoint=checkpoint,
                workflow_call_id=row.workflow_call_id,
                start_command_id=row.start_command_id,
            )
            state = WorkflowState(workflow.state)
            if state is WorkflowState.COMPLETED:
                _fail(
                    "PRODUCTION_RETIREMENT_COMPLETED_WORKFLOW",
                    "a completed Workflow requires Item lifecycle retirement, not queue fencing",
                )
            bindings.append(
                MockExamProductionRetirementBindingV1(
                    position=row.position,
                    workflow_call_id=row.workflow_call_id,
                    workflow_id=row.workflow_id,
                    start_command_id=row.start_command_id,
                    expected_workflow_resource_version=workflow.lock_version,
                    observed_workflow_state=cast(
                        WorkflowRetirementSourceState,
                        workflow.state,
                    ),
                )
            )
        body = {
            "schema_version": "mock-exam-production-retirement-command/1.0",
            "retirement_id": retirement_id,
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "production_request_id": checkpoint.production_request_id,
            "production_plan_id": checkpoint.production_plan_id,
            "production_plan_sha256": checkpoint.production_plan_sha256,
            "operator_id": checkpoint.operator_id,
            "reason_code": _RETIREMENT_REASON,
            "authorized_at": at.isoformat().replace("+00:00", "Z"),
            "bindings": [binding.model_dump(mode="json") for binding in bindings],
        }
        return MockExamProductionRetirementCommandV1.model_validate(
            {**body, "command_sha256": content_sha256(body)}
        )

    def _execute(
        self,
        command: MockExamProductionRetirementCommandV1,
        *,
        checkpoint: MockExamProductionExecutionV1,
    ) -> MockExamProductionRetirementReceiptV1:
        # Re-observe immediately before entering the write transaction. The persistent systemd
        # drop-in makes this evidence stable until its explicit privileged post-retirement release.
        self._require_runner_quiescence()
        with transaction(self._sessions) as session:
            workflow_ids = tuple(binding.workflow_id for binding in command.bindings)
            workflows = _load_workflows(session, workflow_ids, for_update=True)
            replay = self._replay_receipt(
                session,
                checkpoint=checkpoint,
                retirement_id=command.retirement_id,
            )
            if replay is not None:
                return replay
            _reject_other_retirement(
                session,
                workflow_ids,
                retirement_id=command.retirement_id,
            )
            require_no_held_worker_leases(session, workflow_ids)
            for binding in command.bindings:
                workflow = workflows[binding.workflow_id]
                if workflow.lock_version != binding.expected_workflow_resource_version:
                    _fail(
                        "PRODUCTION_RETIREMENT_WORKFLOW_CAS_MISMATCH",
                        "a Workflow changed after retirement preparation",
                    )
                if workflow.state != binding.observed_workflow_state:
                    _fail(
                        "PRODUCTION_RETIREMENT_WORKFLOW_STATE_MISMATCH",
                        "a Workflow state changed after retirement preparation",
                    )
                _validate_occurrence_member(
                    session,
                    workflow=workflow,
                    checkpoint=checkpoint,
                    workflow_call_id=binding.workflow_call_id,
                    start_command_id=binding.start_command_id,
                )

            _fence_platform_jobs(session, workflow_ids)
            _fence_older_commands(session, workflow_ids, at=command.authorized_at)

            outcomes: list[MockExamProductionRetirementOutcomeV1] = []
            for binding in command.bindings:
                workflow = workflows[binding.workflow_id]
                prior_state = cast(WorkflowRetirementSourceState, workflow.state)
                cancel_command_id: str | None = None
                disposition: Literal["CANCEL_QUEUED", "UNSUCCESSFUL_TERMINAL_PRESERVED"]
                if WorkflowState(workflow.state) in ACTIVE_WORKFLOW_STATES:
                    cancellation, _created = enqueue_command(
                        session,
                        workflow_id=workflow.workflow_id,
                        command_type=CommandType.CANCEL_WORKFLOW,
                        payload=_cancellation_payload(
                            retirement_id=command.retirement_id,
                            retirement_command_sha256=command.command_sha256,
                            production_request_id=command.production_request_id,
                            workflow_call_id=binding.workflow_call_id,
                        ),
                        actor_type="human",
                        actor_id=command.operator_id,
                        source="mock_exam_production",
                        idempotency_key=_cancellation_idempotency_key(
                            command.retirement_id,
                            binding.workflow_call_id,
                        ),
                    )
                    cancel_command_id = cancellation.command_id
                    disposition = "CANCEL_QUEUED"
                elif WorkflowState(workflow.state) in {
                    WorkflowState.FAILED,
                    WorkflowState.CANCELLED,
                }:
                    disposition = "UNSUCCESSFUL_TERMINAL_PRESERVED"
                else:  # COMPLETED is rejected during preparation and rechecked by CAS.
                    _fail(
                        "PRODUCTION_RETIREMENT_WORKFLOW_STATE_INVALID",
                        "the Workflow cannot be retired by command fencing",
                    )
                # Workflow history is append-only. The row is already locked, so the event's
                # resource version is the current version plus the single increment performed by
                # record_workflow_event; persist the complete payload in its initial INSERT.
                retirement_workflow_resource_version = workflow.lock_version + 1
                audited = record_workflow_event(
                    session,
                    workflow.workflow_id,
                    _RETIREMENT_EVENT,
                    actor_type="human",
                    actor_id=command.operator_id,
                    command_id=cancel_command_id,
                    step_key=workflow.current_step_key,
                    payload={
                        "retirement_id": command.retirement_id,
                        "retirement_command_sha256": command.command_sha256,
                        "execution_id": command.execution_id,
                        "execution_revision_id": command.execution_revision_id,
                        "checkpoint_sha256": command.checkpoint_sha256,
                        "production_request_id": command.production_request_id,
                        "production_plan_id": command.production_plan_id,
                        "production_plan_sha256": command.production_plan_sha256,
                        "position": binding.position,
                        "workflow_call_id": binding.workflow_call_id,
                        "start_command_id": binding.start_command_id,
                        "expected_workflow_resource_version": (
                            binding.expected_workflow_resource_version
                        ),
                        "prior_workflow_state": prior_state,
                        "disposition": disposition,
                        "cancel_command_id": cancel_command_id,
                        "retired_at": command.authorized_at.isoformat().replace("+00:00", "Z"),
                        "retirement_workflow_resource_version": (
                            retirement_workflow_resource_version
                        ),
                    },
                )
                if audited.lock_version != retirement_workflow_resource_version:
                    _fail(
                        "PRODUCTION_RETIREMENT_AUDIT_VERSION_INVALID",
                        "retirement audit resource version was not allocated deterministically",
                    )
                session.flush()
                event = session.scalar(
                    select(WorkflowEventRecord)
                    .where(
                        WorkflowEventRecord.workflow_id == workflow.workflow_id,
                        WorkflowEventRecord.event_type == _RETIREMENT_EVENT,
                    )
                    .order_by(WorkflowEventRecord.sequence.desc())
                    .limit(1)
                )
                if event is None:
                    _fail(
                        "PRODUCTION_RETIREMENT_AUDIT_MISSING",
                        "retirement audit event was not persisted",
                    )
                outcomes.append(
                    MockExamProductionRetirementOutcomeV1(
                        position=binding.position,
                        workflow_call_id=binding.workflow_call_id,
                        workflow_id=binding.workflow_id,
                        expected_workflow_resource_version=(
                            binding.expected_workflow_resource_version
                        ),
                        retirement_workflow_resource_version=(retirement_workflow_resource_version),
                        retirement_event_sequence=event.sequence,
                        prior_workflow_state=prior_state,
                        disposition=disposition,
                        cancel_command_id=cancel_command_id,
                    )
                )
            receipt = _build_receipt(command, tuple(outcomes))
            _require_receipt_fence(session, receipt)
            return receipt

    def _require_runner_quiescence(self) -> None:
        evidence = self._quiescence.observe()
        _require_runner_quiescence_evidence(evidence)

    def _replay_receipt(
        self,
        session: Session,
        *,
        checkpoint: MockExamProductionExecutionV1,
        retirement_id: str,
    ) -> MockExamProductionRetirementReceiptV1 | None:
        workflow_ids = tuple(row.workflow_id for row in _checkpoint_workflow_rows(checkpoint))
        events = tuple(
            session.scalars(
                select(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id.in_(workflow_ids),
                    WorkflowEventRecord.event_type == _RETIREMENT_EVENT,
                )
                .order_by(WorkflowEventRecord.workflow_id, WorkflowEventRecord.sequence)
            )
        )
        matching = tuple(
            event for event in events if event.payload.get("retirement_id") == retirement_id
        )
        if not matching:
            return None
        if len(matching) != len(events):
            _fail(
                "PRODUCTION_RETIREMENT_CONFLICT",
                "the production cohort already pins another retirement identity",
            )
        if len(matching) != 25 or {event.workflow_id for event in matching} != set(workflow_ids):
            _fail(
                "PRODUCTION_RETIREMENT_PARTIAL_AUDIT",
                "retirement audit evidence does not cover the exact cohort",
            )
        workflows = _load_workflows(session, workflow_ids, for_update=False)
        by_workflow = {event.workflow_id: event for event in matching}
        first_payload = matching[0].payload
        command_sha256 = first_payload.get("retirement_command_sha256")
        retired_at = first_payload.get("retired_at")
        if not isinstance(command_sha256, str) or not isinstance(retired_at, str):
            _fail(
                "PRODUCTION_RETIREMENT_AUDIT_INVALID",
                "retirement audit evidence is malformed",
            )
        outcomes: list[MockExamProductionRetirementOutcomeV1] = []
        reconstructed_bindings: list[MockExamProductionRetirementBindingV1] = []
        for row in _checkpoint_workflow_rows(checkpoint):
            event = by_workflow[row.workflow_id]
            payload = event.payload
            _validate_occurrence_member(
                session,
                workflow=workflows[row.workflow_id],
                checkpoint=checkpoint,
                workflow_call_id=row.workflow_call_id,
                start_command_id=row.start_command_id,
            )
            if (
                event.actor_type != "human"
                or event.actor_id != checkpoint.operator_id
                or payload.get("retirement_command_sha256") != command_sha256
                or payload.get("execution_id") != checkpoint.execution_id
                or payload.get("execution_revision_id") != checkpoint.execution_revision_id
                or payload.get("checkpoint_sha256") != checkpoint.checkpoint_sha256
                or payload.get("production_request_id") != checkpoint.production_request_id
                or payload.get("production_plan_id") != checkpoint.production_plan_id
                or payload.get("production_plan_sha256") != checkpoint.production_plan_sha256
                or payload.get("position") != row.position
                or payload.get("workflow_call_id") != row.workflow_call_id
                or payload.get("start_command_id") != row.start_command_id
                or payload.get("retired_at") != retired_at
                or event.command_id != payload.get("cancel_command_id")
                or event.prior_state != payload.get("prior_workflow_state")
                or event.new_state != payload.get("prior_workflow_state")
            ):
                _fail(
                    "PRODUCTION_RETIREMENT_AUDIT_MISMATCH",
                    "retirement audit evidence differs from the pinned execution",
                )
            try:
                reconstructed_bindings.append(
                    MockExamProductionRetirementBindingV1(
                        position=row.position,
                        workflow_call_id=row.workflow_call_id,
                        workflow_id=row.workflow_id,
                        start_command_id=row.start_command_id,
                        expected_workflow_resource_version=int(
                            payload["expected_workflow_resource_version"]
                        ),
                        observed_workflow_state=payload["prior_workflow_state"],
                    )
                )
                outcomes.append(
                    MockExamProductionRetirementOutcomeV1(
                        position=row.position,
                        workflow_call_id=row.workflow_call_id,
                        workflow_id=row.workflow_id,
                        expected_workflow_resource_version=int(
                            payload["expected_workflow_resource_version"]
                        ),
                        retirement_workflow_resource_version=_event_resource_version(
                            payload,
                        ),
                        retirement_event_sequence=event.sequence,
                        prior_workflow_state=payload["prior_workflow_state"],
                        disposition=payload["disposition"],
                        cancel_command_id=payload.get("cancel_command_id"),
                    )
                )
                if (
                    workflows[row.workflow_id].lock_version
                    < outcomes[-1].retirement_workflow_resource_version
                ):
                    _fail(
                        "PRODUCTION_RETIREMENT_AUDIT_VERSION_INVALID",
                        "retirement audit resource version exceeds the current Workflow version",
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise MockExamProductionRetirementError(
                    "PRODUCTION_RETIREMENT_AUDIT_INVALID",
                    "retirement audit evidence failed contract validation",
                ) from exc
        command_body = {
            "schema_version": "mock-exam-production-retirement-command/1.0",
            "retirement_id": retirement_id,
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "production_request_id": checkpoint.production_request_id,
            "production_plan_id": checkpoint.production_plan_id,
            "production_plan_sha256": checkpoint.production_plan_sha256,
            "operator_id": checkpoint.operator_id,
            "reason_code": _RETIREMENT_REASON,
            "authorized_at": retired_at,
            "bindings": [binding.model_dump(mode="json") for binding in reconstructed_bindings],
        }
        if content_sha256(command_body) != command_sha256:
            _fail(
                "PRODUCTION_RETIREMENT_COMMAND_HASH_MISMATCH",
                "retirement audit does not reconstruct its exact command hash",
            )
        MockExamProductionRetirementCommandV1.model_validate(
            {**command_body, "command_sha256": command_sha256}
        )
        body = {
            "schema_version": "mock-exam-production-retirement-receipt/1.0",
            "retirement_id": retirement_id,
            "command_sha256": command_sha256,
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "production_request_id": checkpoint.production_request_id,
            "production_plan_id": checkpoint.production_plan_id,
            "production_plan_sha256": checkpoint.production_plan_sha256,
            "operator_id": checkpoint.operator_id,
            "reason_code": _RETIREMENT_REASON,
            "retired_at": retired_at,
            "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
        }
        receipt = MockExamProductionRetirementReceiptV1.model_validate(
            {**body, "receipt_sha256": content_sha256(body)}
        )
        _require_receipt_fence(session, receipt)
        return receipt


def _checkpoint_workflow_rows(
    checkpoint: MockExamProductionExecutionV1,
) -> tuple[_PinnedWorkflowRow, ...]:
    rows = checkpoint.item_runs
    if len(rows) != 25 or any(
        row.workflow_id is None or row.start_command_id is None for row in rows
    ):
        _fail(
            "PRODUCTION_RETIREMENT_COHORT_INCOMPLETE",
            "retirement requires 25 pinned Workflow and start-command identities",
        )
    # The guard above narrows these optional pointers for runtime; retaining the original typed
    # rows avoids copying item or artifact payloads.
    return cast(tuple[_PinnedWorkflowRow, ...], rows)


class _PinnedWorkflowRow:
    """Structural typing aid for pointers narrowed by ``_checkpoint_workflow_rows``."""

    position: int
    workflow_call_id: str
    workflow_id: str
    start_command_id: str


def _load_workflows(
    session: Session,
    workflow_ids: tuple[str, ...],
    *,
    for_update: bool,
) -> dict[str, WorkflowInstanceRecord]:
    query = (
        select(WorkflowInstanceRecord)
        .where(WorkflowInstanceRecord.workflow_id.in_(workflow_ids))
        .order_by(WorkflowInstanceRecord.workflow_id)
    )
    if for_update:
        query = query.with_for_update()
    rows = tuple(session.scalars(query))
    if len(rows) != 25 or {row.workflow_id for row in rows} != set(workflow_ids):
        _fail(
            "PRODUCTION_RETIREMENT_WORKFLOW_MISSING",
            "one or more pinned Workflows do not exist",
        )
    return {row.workflow_id: row for row in rows}


def _validate_occurrence_member(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    checkpoint: MockExamProductionExecutionV1,
    workflow_call_id: str,
    start_command_id: str,
) -> None:
    try:
        request = load_persisted_workflow_request(workflow.initial_request)
    except (TypeError, ValueError) as exc:
        raise MockExamProductionRetirementError(
            "PRODUCTION_RETIREMENT_STORED_REQUEST_INVALID",
            "a pinned Workflow request cannot be validated",
        ) from exc
    occurrence = request.production_occurrence
    if (
        workflow.created_actor_type != "human"
        or workflow.created_actor_id != checkpoint.operator_id
        or occurrence is None
        or occurrence.production_request_id != checkpoint.production_request_id
        or occurrence.workflow_call_id != workflow_call_id
    ):
        _fail(
            "PRODUCTION_RETIREMENT_OCCURRENCE_MISMATCH",
            "a pinned Workflow does not belong to the exact owned production occurrence",
        )
    start = session.get(WorkflowCommandRecord, start_command_id)
    if (
        start is None
        or start.workflow_id != workflow.workflow_id
        or start.command_type != CommandType.START_WORKFLOW.value
    ):
        _fail(
            "PRODUCTION_RETIREMENT_START_POINTER_MISMATCH",
            "a pinned start command does not belong to its Workflow",
        )


def _reject_other_retirement(
    session: Session,
    workflow_ids: tuple[str, ...],
    *,
    retirement_id: str,
) -> None:
    events = tuple(
        session.scalars(
            select(WorkflowEventRecord).where(
                WorkflowEventRecord.workflow_id.in_(workflow_ids),
                WorkflowEventRecord.event_type == _RETIREMENT_EVENT,
            )
        )
    )
    if any(event.payload.get("retirement_id") != retirement_id for event in events):
        _fail(
            "PRODUCTION_RETIREMENT_CONFLICT",
            "the production cohort already pins another retirement identity",
        )


def _fence_older_commands(
    session: Session,
    workflow_ids: tuple[str, ...],
    *,
    at: datetime,
) -> None:
    commands = tuple(
        session.scalars(
            select(WorkflowCommandRecord)
            .where(
                WorkflowCommandRecord.workflow_id.in_(workflow_ids),
                WorkflowCommandRecord.state.in_(
                    (
                        CommandState.PENDING.value,
                        CommandState.LEASED.value,
                        CommandState.PROCESSING.value,
                    )
                ),
            )
            .order_by(WorkflowCommandRecord.workflow_id, WorkflowCommandRecord.command_id)
            .with_for_update()
        )
    )
    for command in commands:
        state = CommandState(command.state)
        if state in {CommandState.LEASED, CommandState.PROCESSING} and (
            command.lease_expires_at is None or command.lease_expires_at >= at
        ):
            _fail(
                "PRODUCTION_RETIREMENT_COMMAND_LEASE_HELD",
                "an unexpired Workflow command lease blocks production retirement",
            )
        if state is CommandState.PROCESSING:
            transition_command(command, CommandState.PENDING)
        transition_command(command, CommandState.CANCELLED)


def _fence_platform_jobs(session: Session, workflow_ids: tuple[str, ...]) -> None:
    fence_workflow_platform_jobs(
        session,
        bindings=_workflow_job_bindings(session, workflow_ids),
        reason_code=_RETIREMENT_REASON,
    )


def _workflow_job_bindings(
    session: Session,
    workflow_ids: tuple[str, ...],
) -> tuple[WorkflowJobRetirementBinding, ...]:
    # The verified systemd hold prevents the only step-run writer from advancing, and retirement
    # separately proves that the cohort has no held worker lease. Lock the owning Workflow rows and
    # the mutable Job rows instead; keeping this edge read-only avoids granting the API role UPDATE
    # over immutable Workflow-step provenance.
    query = (
        select(WorkflowStepRunRecord)
        .where(
            WorkflowStepRunRecord.workflow_id.in_(workflow_ids),
            WorkflowStepRunRecord.platform_job_id.is_not(None),
        )
        .order_by(WorkflowStepRunRecord.workflow_id, WorkflowStepRunRecord.step_run_id)
    )
    rows = tuple(session.scalars(query))
    bindings: list[WorkflowJobRetirementBinding] = []
    for row in rows:
        if row.platform_job_id is None or row.worker_role is None:
            _fail(
                "PRODUCTION_RETIREMENT_STEP_JOB_POINTER_INVALID",
                "a Workflow platform-job step lacks its exact worker identity",
            )
        bindings.append(
            WorkflowJobRetirementBinding(
                job_id=row.platform_job_id,
                workflow_id=row.workflow_id,
                step_run_id=row.step_run_id,
                attempt=row.attempt,
                role=row.worker_role,
            )
        )
    return tuple(bindings)


def _require_receipt_fence(
    session: Session,
    receipt: MockExamProductionRetirementReceiptV1,
) -> None:
    workflow_ids = tuple(outcome.workflow_id for outcome in receipt.outcomes)
    require_no_held_worker_leases(session, workflow_ids)
    require_workflow_platform_jobs_fenced(
        session,
        bindings=_workflow_job_bindings(session, workflow_ids),
    )
    cancel_ids = {
        outcome.cancel_command_id
        for outcome in receipt.outcomes
        if outcome.cancel_command_id is not None
    }
    commands = tuple(
        session.scalars(
            select(WorkflowCommandRecord).where(
                WorkflowCommandRecord.workflow_id.in_(workflow_ids),
                WorkflowCommandRecord.state.in_(
                    (
                        CommandState.PENDING.value,
                        CommandState.LEASED.value,
                        CommandState.PROCESSING.value,
                    )
                ),
            )
        )
    )
    if any(command.command_id not in cancel_ids for command in commands):
        _fail(
            "PRODUCTION_RETIREMENT_OLDER_COMMAND_REMAINED",
            "an older production command remains claimable after retirement",
        )
    by_id = {
        command.command_id: command
        for command in session.scalars(
            select(WorkflowCommandRecord).where(WorkflowCommandRecord.command_id.in_(cancel_ids))
        )
    }
    for outcome in receipt.outcomes:
        if outcome.cancel_command_id is None:
            continue
        command = by_id.get(outcome.cancel_command_id)
        expected_payload = _cancellation_payload(
            retirement_id=receipt.retirement_id,
            retirement_command_sha256=receipt.command_sha256,
            production_request_id=receipt.production_request_id,
            workflow_call_id=outcome.workflow_call_id,
        )
        if (
            command is None
            or command.workflow_id != outcome.workflow_id
            or command.command_type != CommandType.CANCEL_WORKFLOW.value
            or command.actor_type != "human"
            or command.actor_id != receipt.operator_id
            or command.source != "mock_exam_production"
            or command.idempotency_key
            != _cancellation_idempotency_key(
                receipt.retirement_id,
                outcome.workflow_call_id,
            )
            or command.payload != expected_payload
            or command.request_hash
            != content_sha256(
                {
                    "workflow_id": outcome.workflow_id,
                    "command_type": CommandType.CANCEL_WORKFLOW.value,
                    "payload": expected_payload,
                    "actor_type": "human",
                    "actor_id": receipt.operator_id,
                    "source": "mock_exam_production",
                }
            )
            or command.state
            not in {
                CommandState.PENDING.value,
                CommandState.SUCCEEDED.value,
            }
        ):
            _fail(
                "PRODUCTION_RETIREMENT_CANCEL_POINTER_INVALID",
                "a retirement cancellation command is missing, active, or failed",
            )


def _event_resource_version(payload: dict[str, object]) -> int:
    value = payload.get("retirement_workflow_resource_version")
    if not isinstance(value, int):
        _fail(
            "PRODUCTION_RETIREMENT_AUDIT_INVALID",
            "retirement audit lacks its resource-version CAS result",
        )
    return value


def _cancellation_payload(
    *,
    retirement_id: str,
    retirement_command_sha256: str,
    production_request_id: str,
    workflow_call_id: str,
) -> dict[str, str]:
    return {
        "reason": _CANCEL_REASON,
        "retirement_id": retirement_id,
        "retirement_command_sha256": retirement_command_sha256,
        "production_request_id": production_request_id,
        "workflow_call_id": workflow_call_id,
    }


def _cancellation_idempotency_key(retirement_id: str, workflow_call_id: str) -> str:
    return f"mock-exam-retire:{retirement_id}:{workflow_call_id}"


def _retirement_id(checkpoint: MockExamProductionExecutionV1) -> str:
    digest = content_sha256(
        {
            "schema_version": "mock-exam-production-retirement-identity/1.0",
            "execution_id": checkpoint.execution_id,
            "execution_revision_id": checkpoint.execution_revision_id,
            "checkpoint_sha256": checkpoint.checkpoint_sha256,
            "reason_code": _RETIREMENT_REASON,
        }
    )
    return "productionretire_" + digest.removeprefix("sha256:")[:32]


def _build_receipt(
    command: MockExamProductionRetirementCommandV1,
    outcomes: tuple[MockExamProductionRetirementOutcomeV1, ...],
) -> MockExamProductionRetirementReceiptV1:
    body = {
        "schema_version": "mock-exam-production-retirement-receipt/1.0",
        "retirement_id": command.retirement_id,
        "command_sha256": command.command_sha256,
        "execution_id": command.execution_id,
        "execution_revision_id": command.execution_revision_id,
        "checkpoint_sha256": command.checkpoint_sha256,
        "production_request_id": command.production_request_id,
        "production_plan_id": command.production_plan_id,
        "production_plan_sha256": command.production_plan_sha256,
        "operator_id": command.operator_id,
        "reason_code": command.reason_code,
        "retired_at": command.authorized_at.isoformat().replace("+00:00", "Z"),
        "outcomes": [outcome.model_dump(mode="json") for outcome in outcomes],
    }
    return MockExamProductionRetirementReceiptV1.model_validate(
        {**body, "receipt_sha256": content_sha256(body)}
    )


def _require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        _fail(
            "PRODUCTION_RETIREMENT_CLOCK_INVALID",
            "retirement time must use UTC",
        )


def _require_runner_quiescence_evidence(
    evidence: WorkflowRunnerQuiescenceEvidence,
) -> None:
    if (
        evidence.load_state != "loaded"
        or evidence.active_state != "inactive"
        or evidence.sub_state != "dead"
        or evidence.main_pid != 0
        or evidence.unit_file_state != "enabled"
        or evidence.job != ""
        or evidence.fragment_path != WORKFLOW_RUNNER_FRAGMENT_PATH
        or evidence.drop_in_paths != (WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,)
        or evidence.refuse_manual_start is not True
        or evidence.need_daemon_reload is not False
        or evidence.hold_directory_path != WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY
        or evidence.hold_directory_owner_uid != 0
        or evidence.hold_directory_group_gid != 0
        or evidence.hold_directory_mode != 0o755
        or evidence.hold_path != WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH
        or evidence.hold_sha256 != WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256
        or evidence.hold_owner_uid != 0
        or evidence.hold_group_gid != 0
        or evidence.hold_mode != 0o644
    ):
        _fail(
            "PRODUCTION_RETIREMENT_RUNNER_NOT_QUIESCENT",
            "Workflow runner must be inactive under the exact persistent deployment hold",
        )


def _fail(code: str, message: str) -> Never:
    raise MockExamProductionRetirementError(code, message)
