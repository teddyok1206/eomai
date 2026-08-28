"""Orchestrator-owned processor for fixed-slot Codex device authentication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.auth_enrollment import (
    POLL_INTERVAL,
    claim_due_codex_auth_enrollment,
    create_auth_assignment_revision,
    defer_codex_auth_enrollment,
    held_lease_exists,
    mark_codex_device_login_started,
    transition_codex_auth_enrollment,
)
from eom_orchestrator.capability_observer import (
    load_reviewed_capability_policy,
    observe_codex_cli_surface,
    record_reviewed_capability_snapshot,
)
from eom_orchestrator.capacity_controller import set_auth_binding_operational_state
from eom_orchestrator.codex_auth_broker_client import (
    CodexAuthBrokerClient,
    CodexAuthBrokerError,
)
from eom_orchestrator.control_models import (
    CodexAuthBindingRecord,
    CodexAuthEnrollmentRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import transaction
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.worker_auth import observe_worker_auth, persist_worker_auth_observation
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_systemd import launch_device_login_unit

AUTH_OBSERVATION_TTL = timedelta(hours=1)
CAPABILITY_OBSERVATION_TTL = timedelta(hours=1)
REAUTH_DRAIN_REASON = "OPERATOR_REAUTHENTICATION_REQUESTED"
REAUTH_COMPLETE_REASON = "OPERATOR_REAUTHENTICATION_COMPLETE"
MINIMUM_DEVICE_LOGIN_WINDOW = timedelta(minutes=10)


@dataclass(frozen=True)
class _EnrollmentTarget:
    enrollment_id: str
    state: str
    binding_id: str
    slot: WorkerSlot
    slot_key: str
    account_label: str
    expires_at: datetime
    login_unit_started_at: datetime | None


class CodexAuthEnrollmentProcessor:
    """Advance one durable enrollment without receiving or persisting credentials."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        capability_policy_path: Path,
        runner_id: str,
        broker: CodexAuthBrokerClient | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.capability_policy_path = capability_policy_path
        self.runner_id = runner_id
        self.broker = broker or CodexAuthBrokerClient()
        self.now = now

    def process_once(self) -> str | None:
        claimed_at = self.now()
        with transaction(self.sessions) as session:
            record = claim_due_codex_auth_enrollment(
                session,
                lease_owner=self.runner_id,
                claimed_at=claimed_at,
            )
            if record is None:
                return None
            try:
                target = self._target(session, record)
            except ControlPlaneError as exc:
                transition_codex_auth_enrollment(
                    session,
                    enrollment_id=record.enrollment_id,
                    lease_owner=self.runner_id,
                    target_state="FAILED",
                    transitioned_at=claimed_at,
                    error_code=exc.code,
                    next_action_at=None,
                )
                return record.enrollment_id
            except Exception:
                transition_codex_auth_enrollment(
                    session,
                    enrollment_id=record.enrollment_id,
                    lease_owner=self.runner_id,
                    target_state="FAILED",
                    transitioned_at=claimed_at,
                    error_code="CODEX_AUTH_ENROLLMENT_INTERNAL_ERROR",
                    next_action_at=None,
                )
                return record.enrollment_id

        try:
            if claimed_at >= target.expires_at:
                self._terminal_failure(
                    target.enrollment_id, "EXPIRED", "CODEX_AUTH_ENROLLMENT_EXPIRED"
                )
            elif target.state == "REQUESTED":
                self._request_drain(target, claimed_at)
            elif target.state == "DRAINING":
                self._wait_for_drain(target, claimed_at)
            elif target.state == "READY_FOR_LOGIN":
                self._start_or_observe_login(target, claimed_at)
            elif target.state == "WAITING_FOR_USER":
                self._observe_login(target, claimed_at)
            elif target.state == "VERIFYING":
                self._verify_and_assign(target, claimed_at)
            else:
                raise ControlPlaneError(
                    "CODEX_AUTH_ENROLLMENT_STATE_INVALID",
                    "auth enrollment state is invalid",
                )
        except ControlPlaneError as exc:
            self._terminal_failure(target.enrollment_id, "FAILED", exc.code)
        except Exception:
            self._terminal_failure(
                target.enrollment_id,
                "FAILED",
                "CODEX_AUTH_ENROLLMENT_INTERNAL_ERROR",
            )
        return target.enrollment_id

    def _target(self, session: Session, record: CodexAuthEnrollmentRecord) -> _EnrollmentTarget:
        binding = session.get(CodexAuthBindingRecord, record.binding_id)
        if binding is None:
            raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
        slot_record = session.get(WorkerSlotRecord, binding.worker_slot_id)
        if slot_record is None:
            raise ControlPlaneError("CONTROL_AUTH_SLOT_MISSING", "auth slot is missing")
        slot = WorkerSlot(
            slot_id=slot_record.slot_id,  # type: ignore[arg-type]
            linux_user=slot_record.linux_user,  # type: ignore[arg-type]
            role=slot_record.role,  # type: ignore[arg-type]
            enabled=slot_record.enabled,
            gpu=slot_record.gpu,
        )
        slot_key = str(record.canonical_document.get("slot_key", ""))
        if slot_key != f"slot{slot.slot_id}":
            raise ControlPlaneError(
                "CODEX_AUTH_ENROLLMENT_IDENTITY_MISMATCH",
                "auth enrollment slot differs",
            )
        return _EnrollmentTarget(
            enrollment_id=record.enrollment_id,
            state=record.state,
            binding_id=record.binding_id,
            slot=slot,
            slot_key=slot_key,
            account_label=record.requested_account_label,
            expires_at=record.expires_at,
            login_unit_started_at=record.login_unit_started_at,
        )

    def _request_drain(self, target: _EnrollmentTarget, observed_at: datetime) -> None:
        with transaction(self.sessions) as session:
            enrollment = self._locked_claim(session, target.enrollment_id, "REQUESTED")
            binding = session.get(
                CodexAuthBindingRecord,
                target.binding_id,
                with_for_update=True,
            )
            if binding is None:
                raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
            if binding.resource_version != enrollment.expected_binding_resource_version:
                raise ControlPlaneError(
                    "CONTROL_RESOURCE_VERSION_CONFLICT",
                    "auth binding version changed",
                )
            set_auth_binding_operational_state(
                session,
                binding_id=binding.binding_id,
                state="DRAINING",
                reason_code=REAUTH_DRAIN_REASON,
                observed_at=observed_at,
                ttl=AUTH_OBSERVATION_TTL,
            )
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                target_state="DRAINING",
                transitioned_at=observed_at,
                next_action_at=observed_at,
            )

    def _wait_for_drain(self, target: _EnrollmentTarget, observed_at: datetime) -> None:
        with transaction(self.sessions) as session:
            enrollment = self._locked_claim(session, target.enrollment_id, "DRAINING")
            binding = session.get(CodexAuthBindingRecord, target.binding_id, with_for_update=True)
            if binding is None or binding.state != "DRAINING":
                raise ControlPlaneError(
                    "CODEX_AUTH_DRAIN_STATE_CHANGED",
                    "auth binding no longer has the required drain state",
                )
            if held_lease_exists(session, binding_id=target.binding_id):
                defer_codex_auth_enrollment(
                    session,
                    enrollment_id=enrollment.enrollment_id,
                    lease_owner=self.runner_id,
                    next_action_at=observed_at + POLL_INTERVAL,
                )
                return
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                target_state="READY_FOR_LOGIN",
                transitioned_at=observed_at,
                next_action_at=observed_at,
            )

    def _start_or_observe_login(self, target: _EnrollmentTarget, observed_at: datetime) -> None:
        if target.expires_at - observed_at < MINIMUM_DEVICE_LOGIN_WINDOW:
            raise ControlPlaneError(
                "CODEX_AUTH_LOGIN_WINDOW_INSUFFICIENT",
                "too little enrollment time remains to start a bounded device login",
            )
        if target.login_unit_started_at is None:
            with transaction(self.sessions) as session:
                should_launch = mark_codex_device_login_started(
                    session,
                    enrollment_id=target.enrollment_id,
                    lease_owner=self.runner_id,
                    started_at=observed_at,
                )
            if should_launch:
                activity = launch_device_login_unit(target.slot, target.enrollment_id)
                if activity.state == "UNAVAILABLE":
                    raise ControlPlaneError(
                        "CODEX_DEVICE_LOGIN_UNIT_UNAVAILABLE",
                        "fixed device-login unit is unavailable",
                    )
        self._observe_login(target, observed_at, expected_state="READY_FOR_LOGIN")

    def _observe_login(
        self,
        target: _EnrollmentTarget,
        observed_at: datetime,
        *,
        expected_state: str = "WAITING_FOR_USER",
    ) -> None:
        try:
            response = self.broker.request(
                action="STATUS",
                enrollment_id=target.enrollment_id,
                slot_key=target.slot_key,
            )
        except CodexAuthBrokerError as exc:
            if exc.code in {
                "CODEX_AUTH_CHALLENGE_NOT_READY",
                "CODEX_AUTH_BROKER_UNAVAILABLE",
            }:
                self._defer(target.enrollment_id, expected_state, observed_at)
                return
            raise ControlPlaneError(exc.code, "Codex device-login status is unavailable") from exc
        status = response.status
        if status is None:
            raise ControlPlaneError(
                "CODEX_AUTH_BROKER_RESPONSE_INVALID",
                "Codex device-login status is absent",
            )
        if status.state in {"STARTING", "WAITING_FOR_USER"}:
            if expected_state == "READY_FOR_LOGIN" and status.state == "WAITING_FOR_USER":
                self._transition(
                    target.enrollment_id,
                    expected_state,
                    "WAITING_FOR_USER",
                    observed_at,
                )
            else:
                self._defer(target.enrollment_id, expected_state, observed_at)
            return
        if status.state == "SUCCEEDED":
            self._transition(
                target.enrollment_id,
                expected_state,
                "VERIFYING",
                observed_at,
            )
            return
        reason = status.reason_code or "CODEX_DEVICE_LOGIN_FAILED"
        target_terminal = "EXPIRED" if status.state == "EXPIRED" else "FAILED"
        self._terminal_failure(target.enrollment_id, target_terminal, reason)

    def _verify_and_assign(self, target: _EnrollmentTarget, observed_at: datetime) -> None:
        observation = observe_worker_auth(
            slot=target.slot,
            binding_id=target.binding_id,
            account_label=target.account_label,
            observed_at=observed_at,
            ttl=AUTH_OBSERVATION_TTL,
        )
        if observation.state != "READY":
            raise ControlPlaneError(
                observation.reason_code or "CONTROL_AUTH_NOT_READY",
                "new worker authentication did not pass the fixed identity probe",
            )
        policy = load_reviewed_capability_policy(self.capability_policy_path)
        cli_observation = observe_codex_cli_surface()
        if cli_observation[0] != policy.expected_codex_cli_version:
            raise ControlPlaneError(
                "CONTROL_CAPABILITY_POLICY_MISMATCH",
                "reviewed capability policy differs from CLI",
            )
        with transaction(self.sessions) as session:
            enrollment = self._locked_claim(session, target.enrollment_id, "VERIFYING")
            binding = session.get(CodexAuthBindingRecord, target.binding_id, with_for_update=True)
            if binding is None or binding.state != "DRAINING":
                raise ControlPlaneError(
                    "CODEX_AUTH_DRAIN_STATE_CHANGED",
                    "auth binding no longer has the required drain state",
                )
            assignment = create_auth_assignment_revision(
                session,
                enrollment=enrollment,
                codex_cli_version=observation.codex_cli_version,
                assigned_at=observed_at,
            )
            binding.current_assignment_revision_id = assignment.assignment_revision_id
            # The binding pointer and its matching account label/resource
            # version form one DB-guarded transition. Prevent an incidental
            # lookup in the health projection from flushing only the pointer.
            with session.no_autoflush:
                persist_worker_auth_observation(session, observation)
            record_reviewed_capability_snapshot(
                session,
                binding_id=binding.binding_id,
                policy=policy,
                observed_at=observed_at,
                ttl=CAPABILITY_OBSERVATION_TTL,
                cli_observation=cli_observation,
                source="LOCAL_OBSERVATION",
            )
            set_auth_binding_operational_state(
                session,
                binding_id=binding.binding_id,
                state="DRAINING",
                reason_code=REAUTH_COMPLETE_REASON,
                observed_at=observed_at + timedelta(microseconds=1),
                ttl=AUTH_OBSERVATION_TTL,
            )
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                target_state="SUCCEEDED",
                transitioned_at=observed_at,
                assignment_revision_id=assignment.assignment_revision_id,
                next_action_at=None,
            )

    def _transition(
        self,
        enrollment_id: str,
        expected_state: str,
        target_state: str,
        observed_at: datetime,
    ) -> None:
        with transaction(self.sessions) as session:
            enrollment = self._locked_claim(session, enrollment_id, expected_state)
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                target_state=target_state,
                transitioned_at=observed_at,
                next_action_at=observed_at,
            )

    def _defer(self, enrollment_id: str, expected_state: str, observed_at: datetime) -> None:
        with transaction(self.sessions) as session:
            enrollment = self._locked_claim(session, enrollment_id, expected_state)
            defer_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                next_action_at=observed_at + POLL_INTERVAL,
            )

    def _terminal_failure(self, enrollment_id: str, state: str, error_code: str) -> None:
        with transaction(self.sessions) as session:
            enrollment = session.get(
                CodexAuthEnrollmentRecord,
                enrollment_id,
                with_for_update=True,
            )
            if enrollment is None or enrollment.state not in {
                "REQUESTED",
                "DRAINING",
                "READY_FOR_LOGIN",
                "WAITING_FOR_USER",
                "VERIFYING",
            }:
                return
            if enrollment.lease_owner != self.runner_id:
                return
            transition_codex_auth_enrollment(
                session,
                enrollment_id=enrollment.enrollment_id,
                lease_owner=self.runner_id,
                target_state=state,
                transitioned_at=self.now(),
                error_code=error_code,
                next_action_at=None,
            )

    def _locked_claim(
        self,
        session: Session,
        enrollment_id: str,
        expected_state: str,
    ) -> CodexAuthEnrollmentRecord:
        enrollment = session.get(
            CodexAuthEnrollmentRecord,
            enrollment_id,
            with_for_update=True,
        )
        if enrollment is None or enrollment.state != expected_state:
            raise ControlPlaneError(
                "CODEX_AUTH_ENROLLMENT_STATE_CHANGED",
                "auth enrollment state changed",
            )
        if enrollment.lease_owner != self.runner_id:
            raise ControlPlaneError(
                "CODEX_AUTH_ENROLLMENT_LEASE_LOST",
                "auth enrollment lease is lost",
            )
        return enrollment
