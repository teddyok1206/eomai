"""Login assignment is durable while unverified model dispatch remains denied."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_orchestrator import auth_enrollment_processor as processor_module
from eom_orchestrator.auth_enrollment_processor import (
    MODEL_VERIFICATION_REASON,
    CodexAuthEnrollmentProcessor,
)
from eom_orchestrator.capability_observer import UnverifiedCapabilityAssignment
from eom_orchestrator.control_models import CodexAuthBindingRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_auth import WorkerAuthObservation
from eom_orchestrator.worker_registry import WorkerSlot

NOW = datetime(2026, 10, 24, tzinfo=UTC)
BINDING = "authbinding_" + "1" * 32
OLD_ASSIGNMENT = "authassignrev_" + "2" * 32
NEW_ASSIGNMENT = "authassignrev_" + "3" * 32


def assignment_case(monkeypatch: pytest.MonkeyPatch):
    binding = SimpleNamespace(
        binding_id=BINDING,
        state="DRAINING",
        reason_code=MODEL_VERIFICATION_REASON,
        current_assignment_revision_id=OLD_ASSIGNMENT,
        account_label="old-account",
    )
    enrollment = SimpleNamespace(enrollment_id="authflow_" + "4" * 32)
    session = Mock()
    session.scalar.return_value = None
    session.no_autoflush = nullcontext()
    session.get.side_effect = lambda model, *_args, **_kwargs: (
        binding if model is CodexAuthBindingRecord else None
    )
    roots = []

    @contextmanager
    def transaction(_sessions):
        previous = vars(binding).copy()
        try:
            yield session
        except Exception:
            vars(binding).clear()
            vars(binding).update(previous)
            roots.append("ROLLBACK")
            raise
        else:
            roots.append("COMMIT")

    monkeypatch.setattr(processor_module, "transaction", transaction)
    observation = WorkerAuthObservation(
        binding_id=BINDING,
        slot_key="slot01",
        account_label="new-account",
        state="READY",
        reason_code=None,
        codex_cli_version="0.162.1",
        observed_at=NOW,
        valid_until=NOW + timedelta(hours=1),
        probe_unit_name="eom-worker-auth-probe@01.service",
    )
    monkeypatch.setattr(processor_module, "observe_worker_auth", lambda **_: observation)
    monkeypatch.setattr(
        processor_module,
        "load_reviewed_capability_policy",
        lambda _: SimpleNamespace(expected_codex_cli_version="0.162.1"),
    )
    monkeypatch.setattr(processor_module, "observe_codex_cli_surface", lambda: ("0.162.1", ()))
    monkeypatch.setattr(
        processor_module,
        "create_auth_assignment_revision",
        lambda *_args, **_kwargs: SimpleNamespace(assignment_revision_id=NEW_ASSIGNMENT),
    )
    monkeypatch.setattr(
        processor_module,
        "persist_worker_auth_observation",
        lambda *_args: setattr(binding, "account_label", observation.account_label),
    )
    snapshot = Mock()
    operational = Mock()
    transition = Mock()
    monkeypatch.setattr(processor_module, "record_reviewed_capability_snapshot", snapshot)
    monkeypatch.setattr(processor_module, "set_auth_binding_operational_state", operational)
    monkeypatch.setattr(processor_module, "transition_codex_auth_enrollment", transition)
    processor = object.__new__(CodexAuthEnrollmentProcessor)
    processor.sessions = Mock(return_value=MagicMock(__enter__=Mock(return_value=session)))
    processor.runner_id = "TEST_ONLY runner"
    processor.capability_policy_path = Path("/TEST_ONLY/policy.yaml")
    processor._locked_claim = lambda *_args: enrollment
    deferred = Mock()
    monkeypatch.setattr(processor_module, "defer_codex_auth_enrollment", deferred)
    target = processor_module._EnrollmentTarget(
        enrollment_id=enrollment.enrollment_id,
        state="VERIFYING",
        binding_id=BINDING,
        slot=WorkerSlot(
            slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True, gpu=False
        ),
        slot_key="slot01",
        account_label="new-account",
        expires_at=NOW + timedelta(minutes=10),
        login_unit_started_at=NOW - timedelta(seconds=10),
    )
    return SimpleNamespace(
        processor=processor,
        target=target,
        binding=binding,
        snapshot=snapshot,
        operational=operational,
        transition=transition,
        roots=roots,
        deferred=deferred,
        session=session,
    )


def test_verified_login_commits_new_assignment_without_copying_old_model_admission(monkeypatch):
    case = assignment_case(monkeypatch)
    case.snapshot.side_effect = UnverifiedCapabilityAssignment(
        binding_id=BINDING, assignment_revision_id=NEW_ASSIGNMENT
    )
    case.processor._verify_and_assign(case.target, NOW)
    assert case.roots == ["COMMIT"]
    assert case.binding.current_assignment_revision_id == NEW_ASSIGNMENT
    assert case.binding.account_label == "new-account"
    assert case.operational.call_args.kwargs["state"] == "DRAINING"
    assert case.operational.call_args.kwargs["reason_code"] == MODEL_VERIFICATION_REASON
    case.transition.assert_not_called()
    case.deferred.assert_called_once()


def test_admitted_assignment_finishes_without_requiring_manual_enable(monkeypatch):
    case = assignment_case(monkeypatch)
    case.processor._verify_and_assign(case.target, NOW)
    assert case.roots == ["COMMIT"]
    case.operational.assert_not_called()
    assert case.transition.call_args.kwargs["target_state"] == "SUCCEEDED"


def test_resuming_assignment_verifies_models_without_repeating_device_login(monkeypatch):
    case = assignment_case(monkeypatch)
    case.session.scalar.return_value = SimpleNamespace(assignment_revision_id=NEW_ASSIGNMENT)
    verification = Mock()
    case.processor._verify_assigned_models = verification
    case.processor._verify_and_assign(case.target, NOW)
    verification.assert_called_once_with(case.target, NEW_ASSIGNMENT, NOW)
    case.snapshot.assert_not_called()
    case.transition.assert_not_called()


def test_automatic_probe_precedes_snapshot_and_success(monkeypatch):
    from eom_orchestrator import auth_enrollment_capabilities as capabilities

    case = assignment_case(monkeypatch)
    case.binding.current_assignment_revision_id = NEW_ASSIGNMENT
    case.processor.settings = SimpleNamespace()
    case.processor.now = lambda: NOW
    ordered = []
    monkeypatch.setattr(
        capabilities, "run_enrollment_model_verification", lambda *_a, **_k: ordered.append("PROBE")
    )
    case.snapshot.side_effect = lambda *_a, **_k: ordered.append("SNAPSHOT")
    case.transition.side_effect = lambda *_a, **_k: ordered.append("SUCCESS")
    case.processor._verify_assigned_models(case.target, NEW_ASSIGNMENT, NOW)
    assert ordered == ["PROBE", "SNAPSHOT", "SUCCESS"]
    assert case.transition.call_args.kwargs["assignment_revision_id"] == NEW_ASSIGNMENT
    case.operational.assert_not_called()


def test_busy_capacity_defers_without_terminalizing_or_repeating_login(monkeypatch):
    from eom_orchestrator import auth_enrollment_capabilities as capabilities

    case = assignment_case(monkeypatch)
    case.processor.settings = SimpleNamespace()
    case.processor.now = lambda: NOW
    monkeypatch.setattr(
        capabilities,
        "run_enrollment_model_verification",
        Mock(side_effect=ControlPlaneError("CODEX_AUTH_VERIFICATION_BUSY", "busy")),
    )
    case.processor._verify_assigned_models(case.target, NEW_ASSIGNMENT, NOW)
    case.deferred.assert_called_once()
    case.snapshot.assert_not_called()
    case.transition.assert_not_called()


def test_probe_failure_keeps_the_verified_assignment_and_never_enables_models(monkeypatch):
    from eom_orchestrator import auth_enrollment_capabilities as capabilities

    case = assignment_case(monkeypatch)
    case.binding.current_assignment_revision_id = NEW_ASSIGNMENT
    case.processor.settings = SimpleNamespace()
    monkeypatch.setattr(
        capabilities,
        "run_enrollment_model_verification",
        Mock(
            side_effect=ControlPlaneError("CONTROL_COMPATIBILITY_EXECUTION_UNCERTAIN", "uncertain")
        ),
    )
    with pytest.raises(ControlPlaneError):
        case.processor._verify_assigned_models(case.target, NEW_ASSIGNMENT, NOW)
    assert case.binding.current_assignment_revision_id == NEW_ASSIGNMENT
    case.transition.assert_not_called()
    case.snapshot.assert_not_called()


def test_manual_drain_during_the_last_probe_is_never_overwritten_by_auto_enable(monkeypatch):
    from eom_orchestrator import auth_enrollment_capabilities as capabilities

    case = assignment_case(monkeypatch)
    case.binding.current_assignment_revision_id = NEW_ASSIGNMENT
    case.processor.settings = SimpleNamespace()
    case.processor.now = lambda: NOW
    monkeypatch.setattr(
        capabilities,
        "run_enrollment_model_verification",
        lambda *_a, **_k: setattr(case.binding, "reason_code", "OPERATOR_REQUESTED_DRAIN"),
    )
    with pytest.raises(ControlPlaneError) as error:
        case.processor._verify_assigned_models(case.target, NEW_ASSIGNMENT, NOW)
    assert error.value.code == "CODEX_AUTH_DRAIN_STATE_CHANGED"
    assert case.binding.reason_code == "OPERATOR_REQUESTED_DRAIN"
    case.snapshot.assert_not_called()
    case.transition.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ControlPlaneError("CONTROL_CAPABILITY_BINDING_UNVERIFIED", "slot role differs"),
        ControlPlaneError("CONTROL_CAPABILITY_POLICY_MISMATCH", "runtime changed"),
        ControlPlaneError("CONTROL_CAPABILITY_CONFLICT", "snapshot conflict"),
        UnverifiedCapabilityAssignment(
            binding_id="authbinding_" + "9" * 32, assignment_revision_id=NEW_ASSIGNMENT
        ),
        UnverifiedCapabilityAssignment(binding_id=BINDING, assignment_revision_id=OLD_ASSIGNMENT),
    ],
)
def test_only_the_exact_new_assignment_missing_admission_is_nonfatal(monkeypatch, error):
    case = assignment_case(monkeypatch)
    case.snapshot.side_effect = error
    with pytest.raises(ControlPlaneError):
        case.processor._verify_and_assign(case.target, NOW)
    assert case.roots == ["ROLLBACK"]
    assert case.binding.current_assignment_revision_id == OLD_ASSIGNMENT
    case.operational.assert_not_called()
    case.transition.assert_not_called()
