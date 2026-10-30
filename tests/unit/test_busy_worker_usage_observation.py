"""Busy-slot usage is a read receipt, never auth/role/capacity mutation."""

from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator import control_command_processor as processor
from eom_orchestrator import control_commands as commands
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.models import WorkerSlotRecord
from eom_orchestrator.worker_registry import WorkerSlot
from eom_workflow import CodexUsageObservation

from tests.unit.test_execution_control_contracts import _usage_observation


def busy_case(monkeypatch):
    raw = _usage_observation()
    raw["observation_sha256"] = content_sha256(
        {k: v for k, v in raw.items() if k != "observation_sha256"}
    )
    usage = CodexUsageObservation.model_validate(raw)
    binding = NS(
        binding_id=usage.binding_id,
        worker_slot_id="01",
        resource_version=7,
        current_assignment_revision_id="authassignrev_" + "9" * 32,
        account_label="synthetic",
        state="READY",
    )
    slot = NS(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True, gpu=False)
    rows = {CodexAuthBindingRecord: binding, WorkerSlotRecord: slot}
    session = NS(get=lambda kind, _id: rows[kind])

    def sessions():
        return nullcontext(session)

    service = processor.CodexControlCommandProcessor(
        sessions,
        capability_policy_path=Path("/synthetic/policy"),
        runner_id="synthetic",
        now=lambda: datetime(2026, 10, 30, tzinfo=UTC),
    )
    monkeypatch.setattr(processor, "transaction", lambda _: nullcontext(session))
    monkeypatch.setattr(processor, "_binding_has_held_lease", lambda *args, **kw: True)
    guard = Mock()
    monkeypatch.setattr(processor, "require_no_active_auth_enrollment", guard)
    monkeypatch.setattr(processor, "_locked_binding", lambda *args, **kw: binding)
    monkeypatch.setattr(processor, "observe_codex_cli_surface", lambda: ("0.162.1", frozenset()))
    read_usage = Mock(return_value=usage)
    monkeypatch.setattr(processor, "observe_worker_usage", read_usage)
    terminalize = Mock()
    monkeypatch.setattr(processor, "terminalize_codex_control_command", terminalize)
    monkeypatch.setattr(
        service,
        "_collect_observation",
        Mock(side_effect=AssertionError("auth probe during model work")),
    )
    monkeypatch.setattr(
        processor,
        "persist_worker_auth_observation",
        Mock(side_effect=AssertionError("auth mutation")),
    )
    return NS(**locals())


def test_busy_worker_usage_has_no_auth_refresh_state_promotion_or_model_call(monkeypatch):
    case = busy_case(monkeypatch)
    case.service._observe_or_enable(
        command_id=case.usage.command_id,
        binding_id=case.binding.binding_id,
        expected_resource_version=7,
        require_ready=False,
        collect_usage=True,
    )
    case.read_usage.assert_called_once()
    assert case.guard.call_count == 2
    case.terminalize.assert_called_once()
    result = case.terminalize.call_args.kwargs
    assert result["result_resource_version"] == 7 and result["binding_state"] == "READY"
    assert result["usage_observation"] == case.usage and result["outcome"] == "SUCCEEDED"
    assert case.binding.resource_version == 7 and case.binding.state == "READY"


def test_account_assignment_changed_during_usage_is_not_published(monkeypatch):
    case = busy_case(monkeypatch)
    with pytest.raises(processor.ControlPlaneError, match="auth assignment changed"):
        case.service._observe_busy_usage(
            command_id=case.usage.command_id,
            binding_id=case.binding.binding_id,
            expected_resource_version=7,
            assignment_revision_id="authassignrev_" + "8" * 32,
            slot=WorkerSlot(
                slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True, gpu=False
            ),
        )
    case.terminalize.assert_not_called()


def test_maintenance_claim_is_scoped_and_does_not_process_enrollment(monkeypatch):
    case = busy_case(monkeypatch)
    enrollment = Mock()
    case.service.enrollment_processor = enrollment
    claim = Mock(return_value=None)
    monkeypatch.setattr(processor, "claim_next_codex_control_command", claim)
    assert case.service.process_observation_once() is None
    assert claim.call_args.kwargs["command_type"] == "OBSERVE"
    enrollment.process_once.assert_not_called()


def test_read_claim_filters_both_pending_and_expired_attempts():
    session = Mock()
    session.scalars.return_value = ()
    session.scalar.return_value = None
    assert (
        commands.claim_next_codex_control_command(
            session,
            lease_owner="synthetic",
            claimed_at=datetime.now(UTC),
            lease_ttl=processor.CONTROL_COMMAND_LEASE_TTL,
            command_type="OBSERVE",
        )
        is None
    )
    for statement in (session.scalars.call_args.args[0], session.scalar.call_args.args[0]):
        assert "OBSERVE" in statement.compile().params.values()


def test_read_claim_scope_is_closed_before_any_sql():
    session = Mock()
    with pytest.raises(ValueError, match="claim scope"):
        commands.claim_next_codex_control_command(
            session,
            lease_owner="synthetic",
            claimed_at=datetime.now(UTC),
            lease_ttl=processor.CONTROL_COMMAND_LEASE_TTL,
            command_type="ENABLE",
        )
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
