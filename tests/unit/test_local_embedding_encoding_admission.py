"""Current encoding composition with explicit synthetic owner/OS seams; no live authority."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from eom_orchestrator.embedding_encoding_reservations import EncodingReadTarget
from eom_orchestrator.native_embedding_launch_identity import NativeEmbeddingLaunchObservation
from eom_workflow.local_embedding_request import require_local_embedding_operator_seed
from eom_workflow_runner import local_embedding_encoding_admission as admission
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import ResolvedLocalEmbeddingAdmission
from eom_workflow_runner.local_embedding_owner_admission import ResolvedLocalEmbeddingSources
from eom_workflow_runner.repository import CommandLeaseIdentity
from sqlalchemy.orm import Session

from tests.unit.local_embedding_admission_fixtures import native_fixture


@pytest.fixture
def current(monkeypatch):
    fixture = native_fixture()
    intent = fixture.association.intent
    owner, launcher = Mock(), Mock()
    owner.fence_current_actor.side_effect = lambda session, request: (
        owner.identity.fence_current_operator(
            session, require_local_embedding_operator_seed(request).operator_id
        )
    )
    sources = ResolvedLocalEmbeddingSources(
        ResolvedLocalEmbeddingAdmission(fixture.request, fixture.plan, fixture.policy),
        fixture.entries,
    )
    owner.resolve_sources.return_value = sources
    owner.resolve_mutation_sources.return_value = sources
    execution = admission.CurrentEncodingExecution(
        fixture.request,
        intent,
        CommandLeaseIdentity(
            intent.command_id, intent.runner_id, "wflease_" + "f" * 32, intent.lease_generation
        ),
    )
    port = admission.CatalogEncodingOwnerAdmission(owner, execution, launcher)
    session = MagicMock(spec=Session)
    session.scalar.side_effect = (
        SimpleNamespace(
            workflow_id=intent.workflow_id, state="RUNNING", current_step_key="encode_batch"
        ),
        SimpleNamespace(
            workflow_id=intent.workflow_id,
            step_key="encode_batch",
            attempt=1,
            state="RUNNING",
            step_type="application",
            worker_role=None,
            result_schema="incremental-embedding-result@1.0",
            input_pointer_manifest={
                "source_plan": fixture.request.source_plan.model_dump(mode="json"),
                "source_plan_sha256": fixture.request.source_plan_sha256,
            },
        ),
    )
    launch = Mock(return_value=NativeEmbeddingLaunchObservation("CLAIMED", intent))
    lease = Mock()
    artifacts = Mock()
    artifacts.return_value.resolve_input.return_value = fixture.native_input
    artifacts.return_value.resolve_result.return_value = SimpleNamespace(
        request=fixture.native_input, result=fixture.result
    )
    launcher.observe.return_value = (SimpleNamespace(fresh=True, succeeded=False),) * 2
    monkeypatch.setattr(admission, "require_native_embedding_launch", launch)
    monkeypatch.setattr(admission, "require_command_lease", lease)
    monkeypatch.setattr(admission, "CatalogLocalEmbeddingEncodingArtifacts", artifacts)
    return fixture, port, session, owner, launcher, launch, lease, artifacts


@pytest.mark.parametrize("operation", ("reserve", "launch", "complete", "fence"))
def test_all_mutations_require_current_source_command_step_and_original_job(
    current, operation: str
) -> None:
    fixture, port, session, owner, _launcher, launch, _lease, _artifacts = current
    if operation == "reserve":
        resolved = port.resolve_reservation(
            session,
            tuple(job.request for job in fixture.association.owned_jobs),
            fixture.association.intent,
        )
        assert resolved.workflow_request == fixture.request
    if operation == "launch":
        assert port.resolve_launch(session, fixture.association).owned_input == fixture.native_input
    if operation == "complete":
        assert (
            port.resolve_completion(session, fixture.association, fixture.completions).result
            == fixture.result
        )
    if operation == "fence":
        port.fence_mutation(session, fixture.association.intent)
    owner.resolve_mutation_sources.assert_called_once_with(
        session, fixture.request, port.execution.command_lease
    )
    launch.assert_called_once_with(session, fixture.association.intent, fixture.request)


def test_identity_denial_precedes_workflow_existence_or_artifact_reads(current) -> None:
    fixture, port, session, owner, _launcher, launch, _lease, artifacts = current
    owner.identity.fence_current_operator.side_effect = RuntimeError(
        "SYNTHETIC_CURRENT_IDENTITY_DENIED"
    )
    with pytest.raises(RuntimeError):
        port.resolve_launch(session, fixture.association)
    assert session.scalar.call_count == 0 and launch.call_count == 0 and artifacts.call_count == 0


def test_terminal_native_or_stale_current_step_is_not_mutation_authority(current) -> None:
    fixture, port, session, _owner, _launcher, launch, _lease, artifacts = current
    launch.return_value = NativeEmbeddingLaunchObservation("SUCCEEDED", fixture.association.intent)
    with pytest.raises(RuntimeError, match="TERMINAL_OR_FOREIGN"):
        port.resolve_launch(session, fixture.association)
    assert artifacts.call_count == 0


def test_foreign_encoding_is_rejected_by_explicit_current_plan(current) -> None:
    fixture, port, session, _owner, _launcher, _launch, _lease, _artifacts = current
    other = native_fixture("c")
    with pytest.raises(RuntimeError, match="SCOPE_MISMATCH"):
        port.resolve_reservation(
            session,
            tuple(job.request for job in other.association.owned_jobs),
            fixture.association.intent,
        )


def test_changed_step_input_pointer_is_not_silently_repaired(current) -> None:
    fixture, port, session, _owner, _launcher, launch, _lease, artifacts = current
    intent = fixture.association.intent
    session.scalar.side_effect = (
        SimpleNamespace(
            workflow_id=intent.workflow_id, state="RUNNING", current_step_key="encode_batch"
        ),
        SimpleNamespace(
            workflow_id=intent.workflow_id,
            step_key="encode_batch",
            attempt=1,
            state="RUNNING",
            step_type="application",
            worker_role=None,
            result_schema="incremental-embedding-result@1.0",
            input_pointer_manifest={},
        ),
    )
    with pytest.raises(RuntimeError, match="CURRENT_STEP_INVALID"):
        port.resolve_launch(session, fixture.association)
    assert artifacts.call_count == 0 and launch.call_count == 0


def test_read_scope_denial_precedes_existing_job_lookup(current) -> None:
    _fixture, port, session, owner, _launcher, launch, _lease, artifacts = current
    refs = (native_fixture("c").association.owned_jobs[0].job_reference,)
    with pytest.raises(RuntimeError, match="READ_SCOPE_INVALID"):
        port.fence_read_scope(session, refs)
    owner.resolve_sources.assert_called_once()
    assert session.scalar.call_count == 0 and launch.call_count == 0 and artifacts.call_count == 0


def test_completed_rows_reauthorize_without_historical_lease_or_winner_plan(current) -> None:
    fixture, port, session, owner, launcher, launch, lease, artifacts = current
    lease.side_effect = AssertionError("historical lease must not be used for completed reads")
    targets = tuple(EncodingReadTarget(e.owned_job, e.intent, e) for e in fixture.completions)
    observed = port.reauthorize_read(session, targets)
    assert observed.uncertain_launch_job_ids == frozenset()
    artifacts.return_value.verify_shared_rows.assert_called_once()
    assert launcher.observe.call_count == 0 and launch.call_count == 0 and lease.call_count == 0
    owner.identity.fence_current_operator.assert_called_once()


def test_unexpired_current_lease_and_fresh_units_are_inspected_without_start(current) -> None:
    fixture, port, session, _owner, launcher, _launch, lease, _artifacts = current
    targets = tuple(
        EncodingReadTarget(job, fixture.association.intent, None)
        for job in fixture.association.owned_jobs
    )
    observed = port.reauthorize_read(session, targets)
    assert observed.current_intent == fixture.association.intent
    assert observed.uncertain_launch_job_ids == frozenset()
    lease.assert_called_once()
    launcher.observe.assert_called_once_with(
        fixture.association.intent.native_launch_job_id.removeprefix("job_")
    )
    launcher.run.assert_not_called()


def test_expired_current_command_keeps_pending_ownership_uncertain_and_never_starts(
    current,
) -> None:
    fixture, port, session, _owner, launcher, _launch, lease, _artifacts = current
    lease.side_effect = WorkflowError(
        WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT, "synthetic expiry"
    )
    targets = tuple(
        EncodingReadTarget(job, fixture.association.intent, None)
        for job in fixture.association.owned_jobs
    )
    observed = port.reauthorize_read(session, targets)
    assert observed.uncertain_launch_job_ids == frozenset(
        (fixture.association.intent.native_launch_job_id,)
    )
    assert launcher.observe.call_count == 0 and launcher.run.call_count == 0


def test_late_session_revocation_after_artifact_read_is_not_returned_as_authorized(current) -> None:
    fixture, port, session, owner, _launcher, _launch, _lease, artifacts = current
    owner.identity.fence_current_operator.side_effect = RuntimeError("SYNTHETIC_LATE_REVOCATION")
    targets = tuple(EncodingReadTarget(e.owned_job, e.intent, e) for e in fixture.completions)
    with pytest.raises(RuntimeError):
        port.reauthorize_read(session, targets)
    artifacts.return_value.verify_shared_rows.assert_called_once()
