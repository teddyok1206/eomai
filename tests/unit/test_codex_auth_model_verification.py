"""Automatic verification must never turn another assignment's proof into authority."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_orchestrator import auth_enrollment_capability_admission as module
from eom_orchestrator.capability_observer import ReviewedCapabilityPolicy
from eom_orchestrator.control_models import CodexAuthAssignmentRevisionRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_workflow.codex_compatibility import CodexCompatibilityRuntime
from eom_workflow.control_plane import ModelCapability

BINDING = "authbinding_" + "1" * 32
ASSIGNMENT = "authassignrev_" + "2" * 32
NOW = datetime(2026, 10, 24, tzinfo=UTC)


def policy():
    runtime = CodexCompatibilityRuntime(
        cli_version="0.162.1",
        cli_launcher_sha256="sha256:" + "a" * 64,
        cli_binary_sha256="sha256:" + "b" * 64,
        worker_exec_sha256="sha256:" + "c" * 64,
        contract_sha256="sha256:" + "d" * 64,
    )
    return ReviewedCapabilityPolicy.model_validate(
        {
            "version": 3,
            "expected_codex_cli_version": runtime.cli_version,
            "compatibility_runtime": runtime.model_dump(mode="json"),
            "models": [
                {
                    "model": "gpt-6.1-sol",
                    "reasoning_efforts": ["medium", "high"],
                    "bindings": [
                        {
                            "binding_id": BINDING,
                            "assignment_revision_id": "authassignrev_" + "3" * 32,
                            "slot_id": "03",
                            "role": "image",
                        }
                    ],
                }
            ],
        }
    )


def proof_case(monkeypatch):
    baseline = policy()
    binding = SimpleNamespace(
        binding_id=BINDING,
        current_assignment_revision_id=ASSIGNMENT,
        worker_slot_id="03",
        resource_version=15,
    )
    assignment = SimpleNamespace(
        binding_id=BINDING, assignment_revision_id=ASSIGNMENT, assigned_at=NOW
    )
    revision = SimpleNamespace(
        logical_artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
        content_hash="sha256:" + "6" * 64,
    )
    session = Mock()
    session.get.side_effect = lambda model, *_args: (
        assignment if model is CodexAuthAssignmentRevisionRecord else None
    )
    session.execute.return_value.one_or_none.return_value = (Mock(), revision)
    report = SimpleNamespace(
        runtime=baseline.compatibility_runtime,
        request=SimpleNamespace(
            run_id=module.enrollment_compatibility_run_id(ASSIGNMENT, baseline), created_at=NOW
        ),
        cases=[
            SimpleNamespace(
                binding_id=BINDING,
                slot_id="03",
                assignment_revision_id=ASSIGNMENT,
                expected_resource_version=14,
                model="gpt-6.1-sol",
                reasoning_effort="medium",
                status="PASS",
            ),
            SimpleNamespace(
                binding_id=BINDING,
                slot_id="03",
                assignment_revision_id=ASSIGNMENT,
                expected_resource_version=14,
                model="gpt-6.1-sol",
                reasoning_effort="high",
                status="FAIL",
            ),
        ],
    )
    monkeypatch.setattr(module, "load_committed_compatibility_report", lambda *_args: report)
    return session, binding, baseline, report


def test_new_assignment_and_policy_each_change_the_run_identity():
    baseline = policy()
    first = module.enrollment_compatibility_run_id(ASSIGNMENT, baseline)
    assert first == module.enrollment_compatibility_run_id(ASSIGNMENT, baseline)
    assert first != module.enrollment_compatibility_run_id("authassignrev_" + "f" * 32, baseline)
    changed = baseline.model_copy(
        update={"models": (baseline.models[0].model_copy(update={"model": "gpt-6-sol"}),)}
    )
    assert first != module.enrollment_compatibility_run_id(ASSIGNMENT, changed)


def test_candidate_selection_is_scoped_and_deduplicated():
    baseline = policy()
    assert module.enrollment_candidate_pairs(baseline, binding_id=BINDING, slot_id="03") == (
        ("gpt-6.1-sol", "medium"),
        ("gpt-6.1-sol", "high"),
    )
    assert module.enrollment_candidate_pairs(baseline, binding_id=BINDING, slot_id="04") == ()
    assert (
        module.enrollment_candidate_pairs(
            baseline, binding_id="authbinding_" + "f" * 32, slot_id="03"
        )
        == ()
    )


def test_only_canonical_passed_pairs_are_admitted(monkeypatch):
    session, binding, baseline, _ = proof_case(monkeypatch)
    capabilities = module.enrollment_verified_capabilities(
        session, binding=binding, policy=baseline
    )
    assert [(item.model, item.reasoning_efforts) for item in capabilities] == [
        ("gpt-6.1-sol", ("medium",))
    ]


@pytest.mark.parametrize(
    "mutation",
    ["assignment", "binding", "slot", "runtime", "run", "resource_version", "unreviewed_model"],
)
def test_stale_or_foreign_proofs_are_rejected(monkeypatch, mutation):
    session, binding, baseline, report = proof_case(monkeypatch)
    if mutation == "assignment":
        report.cases[0].assignment_revision_id = "authassignrev_" + "f" * 32
    elif mutation == "binding":
        report.cases[0].binding_id = "authbinding_" + "f" * 32
    elif mutation == "slot":
        report.cases[0].slot_id = "04"
    elif mutation == "runtime":
        report.runtime = None
    elif mutation == "run":
        report.request.run_id = "codexcompat_" + "f" * 32
    elif mutation == "resource_version":
        report.cases[0].expected_resource_version = 100
    else:
        report.cases[0].model = "unreviewed-model"
    with pytest.raises(ControlPlaneError, match="proof differs"):
        module.enrollment_verified_capabilities(session, binding=binding, policy=baseline)


def test_local_or_missing_publication_grants_nothing(monkeypatch):
    session, binding, baseline, _ = proof_case(monkeypatch)
    session.execute.return_value.one_or_none.return_value = None
    assert module.enrollment_verified_capabilities(session, binding=binding, policy=baseline) == ()


@pytest.mark.parametrize("peer_changed", [False, True])
def test_authoring_admits_only_pairs_verified_for_the_current_review_account(
    monkeypatch, peer_changed
):
    peer_binding = "authbinding_" + "8" * 32
    peer_assignment = "authassignrev_" + "9" * 32
    document = policy().model_dump(mode="json")
    document["models"] = [
        {
            "model": "gpt-6.1-sol",
            "reasoning_efforts": ["high"],
            "bindings": [
                {
                    "binding_id": peer_binding,
                    "assignment_revision_id": peer_assignment,
                    "slot_id": "02",
                    "role": "review",
                }
            ],
        }
    ]
    baseline = ReviewedCapabilityPolicy.model_validate(document)
    binding = SimpleNamespace(binding_id=BINDING, worker_slot_id="01")
    peer = SimpleNamespace(
        binding_id=peer_binding,
        worker_slot_id="02",
        current_assignment_revision_id="authassignrev_" + "a" * 32
        if peer_changed
        else peer_assignment,
    )
    session = Mock()
    session.scalar.return_value = peer
    session.get.return_value = SimpleNamespace(enabled=True, role="review")
    own = (
        ModelCapability(
            model="gpt-6.1-sol", reasoning_efforts=("medium", "high"), state="AVAILABLE"
        ),
    )
    monkeypatch.setattr(
        module,
        "_proved_capabilities",
        lambda _session, *, binding, policy: own if binding.worker_slot_id == "01" else (),
    )
    result = module.enrollment_verified_capabilities(session, binding=binding, policy=baseline)
    assert [(cap.model, cap.reasoning_efforts) for cap in result] == (
        [] if peer_changed else [("gpt-6.1-sol", ("high",))]
    )


def test_active_enrollment_rejects_manual_refresh_before_it_can_replace_health():
    from eom_orchestrator.auth_enrollment import require_no_active_auth_enrollment

    session = Mock()
    session.scalar.return_value = "authflow_" + "b" * 32
    with pytest.raises(ControlPlaneError) as error:
        require_no_active_auth_enrollment(session, binding_id=BINDING)
    assert error.value.code == "CODEX_AUTH_ENROLLMENT_ALREADY_ACTIVE"
    statement = str(session.scalar.call_args.args[0])
    assert "binding_id" in statement and "state IN" in statement and "LIMIT" in statement
    session.scalar.return_value = None
    require_no_active_auth_enrollment(session, binding_id=BINDING)


def test_native_catalog_only_narrows_candidates_and_never_grants_other_models():
    from eom_orchestrator.auth_enrollment_capabilities import catalog_visible_candidate_pairs

    catalog = SimpleNamespace(
        state="OBSERVED",
        models=[
            SimpleNamespace(
                id="gpt-6.1-sol",
                model="gpt-6.1-sol",
                hidden=False,
                input_modalities=("text", "image"),
                supported_reasoning_efforts=("medium",),
            ),
            SimpleNamespace(
                id="hidden-model",
                model="hidden-model",
                hidden=True,
                input_modalities=("text", "image"),
                supported_reasoning_efforts=("medium",),
            ),
            SimpleNamespace(
                id="text-only",
                model="text-only",
                hidden=False,
                input_modalities=("text",),
                supported_reasoning_efforts=("medium",),
            ),
            SimpleNamespace(
                id="unreviewed-model",
                model="unreviewed-model",
                hidden=False,
                input_modalities=("text", "image"),
                supported_reasoning_efforts=("medium",),
            ),
        ],
    )
    pairs = (
        ("gpt-6.1-sol", "medium"),
        ("gpt-6.1-sol", "high"),
        ("hidden-model", "medium"),
        ("text-only", "medium"),
    )
    assert catalog_visible_candidate_pairs(pairs, catalog) == (("gpt-6.1-sol", "medium"),)
    catalog.state = "UNAVAILABLE"
    with pytest.raises(ControlPlaneError) as error:
        catalog_visible_candidate_pairs(pairs, catalog)
    assert error.value.code == "CODEX_MODEL_CATALOG_UNAVAILABLE"


def test_committed_report_replay_needs_neither_local_results_nor_new_worker_calls(monkeypatch):
    from contextlib import nullcontext

    from eom_orchestrator import auth_enrollment_capabilities as execution
    from eom_orchestrator.control_models import CodexAuthBindingRecord, CodexAuthEnrollmentRecord
    from eom_orchestrator.settings import Settings

    assignment = SimpleNamespace(enrollment_id="authflow_" + "e" * 32)
    enrollment = SimpleNamespace(binding_id=BINDING)
    binding = SimpleNamespace(binding_id=BINDING)
    session = Mock()
    session.get.side_effect = lambda model, *_args: {
        CodexAuthAssignmentRevisionRecord: assignment,
        CodexAuthEnrollmentRecord: enrollment,
        CodexAuthBindingRecord: binding,
    }[model]
    monkeypatch.setattr(
        execution, "build_session_factory", lambda _engine: lambda: nullcontext(session)
    )
    monkeypatch.setattr(
        execution, "load_checkpointed_codex_compatibility_request", lambda *_a: None
    )
    monkeypatch.setattr(
        execution, "load_enrollment_model_verification_report", lambda *_a, **_k: object()
    )
    catalog = Mock(side_effect=AssertionError("committed replay must not observe another catalog"))
    model = Mock(side_effect=AssertionError("committed replay must not invoke a model"))
    monkeypatch.setattr(execution, "observe_worker_usage", catalog)
    monkeypatch.setattr(execution, "execute_pinned_codex_compatibility", model)
    execution.run_enrollment_model_verification(
        Mock(),
        enrollment_id=assignment.enrollment_id,
        assignment_revision_id=ASSIGNMENT,
        policy=policy(),
        settings=Settings(runtime_source_commit="a" * 40),
    )
    catalog.assert_not_called()
    model.assert_not_called()
