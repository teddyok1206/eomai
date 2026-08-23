"""Orchestrator-owned processor for fixed, sanitized Codex account operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from eom_orchestrator.capability_observer import (
    load_reviewed_capability_policy,
    observe_codex_cli_surface,
    record_reviewed_capability_snapshot,
)
from eom_orchestrator.capacity_controller import set_auth_binding_operational_state
from eom_orchestrator.control_commands import (
    claim_next_codex_control_command,
    terminalize_codex_control_command,
)
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import transaction
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.worker_auth import (
    observe_worker_auth,
    persist_worker_auth_observation,
)
from eom_orchestrator.worker_registry import WorkerSlot

AUTH_OBSERVATION_TTL = timedelta(minutes=15)
CAPABILITY_OBSERVATION_TTL = timedelta(minutes=15)
CONTROL_COMMAND_LEASE_TTL = timedelta(minutes=2)


class CodexControlCommandProcessor:
    """Process one command without accepting credentials or arbitrary unit/path input."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        capability_policy_path: Path,
        runner_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.capability_policy_path = capability_policy_path
        self.runner_id = runner_id
        self.now = now

    def process_once(self) -> str | None:
        claimed_at = self.now()
        with transaction(self.sessions) as session:
            record = claim_next_codex_control_command(
                session,
                lease_owner=self.runner_id,
                claimed_at=claimed_at,
                lease_ttl=CONTROL_COMMAND_LEASE_TTL,
            )
            if record is None:
                return None
            command_id = record.command_id
            command_type = record.command_type
            binding_id = record.binding_id
            expected_resource_version = record.expected_resource_version
            reason_code = record.canonical_document.get("reason_code")

        try:
            if command_type in {"DRAIN", "DISABLE"}:
                self._set_operational_state(
                    command_id=command_id,
                    binding_id=binding_id,
                    expected_resource_version=expected_resource_version,
                    state="DRAINING" if command_type == "DRAIN" else "DISABLED",
                    reason_code=str(reason_code),
                )
            else:
                self._observe_or_enable(
                    command_id=command_id,
                    binding_id=binding_id,
                    expected_resource_version=expected_resource_version,
                    require_ready=command_type == "ENABLE",
                )
        except ControlPlaneError as exc:
            with transaction(self.sessions) as session:
                terminalize_codex_control_command(
                    session,
                    command_id=command_id,
                    lease_owner=self.runner_id,
                    outcome="FAILED",
                    result_resource_version=None,
                    binding_state=None,
                    reason_code=exc.code,
                    processed_at=self.now(),
                )
        except Exception:
            with transaction(self.sessions) as session:
                terminalize_codex_control_command(
                    session,
                    command_id=command_id,
                    lease_owner=self.runner_id,
                    outcome="FAILED",
                    result_resource_version=None,
                    binding_state=None,
                    reason_code="CONTROL_COMMAND_INTERNAL_ERROR",
                    processed_at=self.now(),
                )
        return command_id

    def _set_operational_state(
        self,
        *,
        command_id: str,
        binding_id: str,
        expected_resource_version: int,
        state: str,
        reason_code: str,
    ) -> None:
        observed_at = self.now()
        with transaction(self.sessions) as session:
            binding = _locked_binding(
                session,
                binding_id=binding_id,
                expected_resource_version=expected_resource_version,
            )
            updated = set_auth_binding_operational_state(
                session,
                binding_id=binding.binding_id,
                state=state,
                reason_code=reason_code,
                observed_at=observed_at,
                ttl=AUTH_OBSERVATION_TTL,
            )
            terminalize_codex_control_command(
                session,
                command_id=command_id,
                lease_owner=self.runner_id,
                outcome="SUCCEEDED",
                result_resource_version=updated.resource_version,
                binding_state=updated.state,
                reason_code=None,
                processed_at=observed_at,
            )

    def _observe_or_enable(
        self,
        *,
        command_id: str,
        binding_id: str,
        expected_resource_version: int,
        require_ready: bool,
    ) -> None:
        with self.sessions() as session:
            binding = session.get(CodexAuthBindingRecord, binding_id)
            if binding is None or binding.resource_version != expected_resource_version:
                raise ControlPlaneError(
                    "CONTROL_RESOURCE_VERSION_CONFLICT", "auth binding version changed"
                )
            slot_record = session.get(WorkerSlotRecord, binding.worker_slot_id)
            if slot_record is None:
                raise ControlPlaneError("CONTROL_AUTH_SLOT_MISSING", "auth slot is missing")
            slot = _worker_slot(slot_record)
            account_label = binding.account_label

        observed_at = self.now()
        observation = observe_worker_auth(
            slot=slot,
            binding_id=binding_id,
            account_label=account_label,
            observed_at=observed_at,
            ttl=AUTH_OBSERVATION_TTL,
        )
        policy = None
        cli_observation = None
        if observation.state == "READY":
            try:
                policy = load_reviewed_capability_policy(self.capability_policy_path)
                cli_observation = observe_codex_cli_surface()
                if cli_observation[0] != policy.expected_codex_cli_version:
                    raise ControlPlaneError(
                        "CONTROL_CAPABILITY_POLICY_MISMATCH",
                        "reviewed capability policy differs from CLI",
                    )
            except ControlPlaneError:
                observation = replace(
                    observation,
                    state="DEGRADED",
                    reason_code="CAPABILITY_OBSERVATION_FAILED",
                )

        with transaction(self.sessions) as session:
            _locked_binding(
                session,
                binding_id=binding_id,
                expected_resource_version=expected_resource_version,
            )
            updated = persist_worker_auth_observation(session, observation)
            if observation.state == "READY" and policy is not None and cli_observation is not None:
                record_reviewed_capability_snapshot(
                    session,
                    binding_id=binding_id,
                    policy=policy,
                    observed_at=observed_at,
                    ttl=CAPABILITY_OBSERVATION_TTL,
                    cli_observation=cli_observation,
                )
            if require_ready and observation.state != "READY":
                terminalize_codex_control_command(
                    session,
                    command_id=command_id,
                    lease_owner=self.runner_id,
                    outcome="FAILED",
                    result_resource_version=None,
                    binding_state=None,
                    reason_code=observation.reason_code or "CONTROL_AUTH_NOT_READY",
                    processed_at=self.now(),
                )
                return
            terminalize_codex_control_command(
                session,
                command_id=command_id,
                lease_owner=self.runner_id,
                outcome="SUCCEEDED",
                result_resource_version=updated.resource_version,
                binding_state=updated.state,
                reason_code=None,
                processed_at=self.now(),
            )


def _locked_binding(
    session: Session, *, binding_id: str, expected_resource_version: int
) -> CodexAuthBindingRecord:
    binding = session.get(CodexAuthBindingRecord, binding_id, with_for_update=True)
    if binding is None:
        raise ControlPlaneError("CONTROL_AUTH_BINDING_MISSING", "auth binding is missing")
    if binding.resource_version != expected_resource_version:
        raise ControlPlaneError("CONTROL_RESOURCE_VERSION_CONFLICT", "auth binding version changed")
    return binding


def _worker_slot(record: WorkerSlotRecord) -> WorkerSlot:
    return WorkerSlot(
        slot_id=record.slot_id,  # type: ignore[arg-type]
        linux_user=record.linux_user,  # type: ignore[arg-type]
        role=record.role,  # type: ignore[arg-type]
        enabled=record.enabled,
        gpu=record.gpu,
    )
