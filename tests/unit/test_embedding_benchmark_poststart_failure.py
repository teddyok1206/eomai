"""Synthetic inspection and disposable SQLite, not real root proof or PG locking."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    POSTSTART_FAILURE_CODE,
    POSTSTART_FAILURE_EVENT,
    BenchmarkPoststartObservation,
    BenchmarkPoststartPredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_benchmark_poststart_failure import (
    BenchmarkPoststartFailureApplication,
    submit_benchmark_poststart_successor_in_session,
)
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission
from tests.unit.embedding_benchmark_poststart_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for, receipt_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_benchmark_prelaunch_failure import SyntheticInspection
from tests.unit.test_embedding_device_benchmark_owner import SyntheticOwnerAdmission


@pytest.fixture
def closure(storage):
    sessions, source, reader, journal, job_id = storage
    invocation = invocation_for(storage, 1)
    with sessions() as session, session.begin():
        journal.reserve(session, source.request, invocation)
    inspection = SyntheticInspection(observation(source.request, invocation))
    admission = SyntheticOwnerAdmission(source.request, source.inputs, reader)
    application = BenchmarkPoststartFailureApplication(
        sessions, admission=admission, inspection=inspection
    )
    return SimpleNamespace(
        sessions=sessions,
        journal=journal,
        job_id=job_id,
        invocation=invocation,
        inspection=inspection,
        admission=admission,
        application=application,
        request=source.request,
        storage=storage,
    )


def close(case):
    return case.application.close(case.request, job_id=case.job_id)


def test_failure_closure_preserves_partial_reservation_and_stored_replay(closure):
    case = closure
    result = close(case)
    assert result.created and result.event_sequence == 7
    assert result.predecessor == BenchmarkPoststartPredecessorReference.from_decision(
        result.decision, event_sequence=7
    )
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.job_state == "FAILED" and history.launches[0].receipt is None
        assert history.launches[0].invocation == case.invocation
        assert history.prelaunch_failure is None
        assert history.poststart_failure.decision == result.decision
        job = session.get(JobRecord, case.job_id)
        assert job.error_code == POSTSTART_FAILURE_CODE and job.completed_at is not None
        rows = tuple(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert len(rows) == 7 and rows[5].event == "BENCHMARK_LAUNCH_RESERVED"
        assert rows[6].event == POSTSTART_FAILURE_EVENT
        assert rows[6].data == result.decision.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert all(
            token not in json.dumps(rows[6].data)
            for token in ('"text"', '"vectors"', '"input_ids"')
        )
    checks = case.inspection.checks
    case.inspection.fail_check = checks + 1
    replay = close(case)
    assert not replay.created and replay.decision == result.decision
    assert replay.event_sequence == result.event_sequence
    assert case.inspection.captures == 1 and case.inspection.checks == checks


@pytest.mark.parametrize("fail_check", (1, 2, 3, 4))
def test_initial_and_late_proof_changes_roll_back_state_and_event(closure, fail_check):
    case = closure
    case.inspection.fail_check = fail_check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 6


@pytest.mark.parametrize("replay", (False, True))
def test_current_and_late_source_or_identity_authority_protects_closure(closure, replay):
    case = closure
    if replay:
        close(case)
    case.admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == ("FAILED" if replay else "RUNNING")
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == (
            7 if replay else 6
        )


@pytest.mark.parametrize(
    "field", ("execution_id", "invocation_raw_sha256", "invocation_sha256", "job_id")
)
def test_foreign_rehashed_observation_is_not_original_failure_proof(closure, field):
    case = closure
    body = case.inspection.observation.model_dump(mode="json")
    body[field] = {
        "execution_id": "f" * 32,
        "job_id": "job_" + "f" * 32,
        "invocation_raw_sha256": "sha256:" + "f" * 64,
        "invocation_sha256": "sha256:" + "f" * 64,
    }[field]
    if field == "execution_id":
        prefix = "eom-embedding-benchmark-cpu@" + body[field]
        body["terminal"].update(
            native_service=prefix + ".service", native_socket=prefix + ".socket"
        )
    case.inspection.observation = BenchmarkPoststartObservation.model_validate(
        seal(body, "observation_sha256")
    )
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        close(case)


@pytest.mark.parametrize("state", (JobState.FAILED, JobState.CANCELLED))
def test_different_terminal_history_is_never_reinterpreted(closure, state):
    case = closure
    with case.sessions() as session, session.begin():
        transition_job(session, case.job_id, state, "SYNTHETIC_FOREIGN_FAILURE")
    with pytest.raises(ValueError, match="TERMINAL_OR_FOREIGN"):
        close(case)
    assert case.inspection.captures == 0


def test_any_native_receipt_blocks_partial_failure_closure(closure):
    case = closure
    with case.sessions() as session, session.begin():
        case.journal.record(session, case.request, receipt_for(case.storage, case.invocation))
    with pytest.raises(ValueError, match="ORIGINAL_UNRESOLVED_REQUIRED"):
        close(case)


@pytest.mark.parametrize("fault", ("actor", "linkage", "error", "transition", "date"))
def test_tampered_terminal_decision_is_not_laundered_by_history(closure, fault):
    case = closure
    close(case)
    with case.sessions() as session, session.begin():
        row = session.scalar(select(JobEventRecord).where(JobEventRecord.sequence == 7))
        if fault in {"actor", "linkage", "date"}:
            body = dict(row.data)
            if fault == "actor":
                body["actor_id"] = "operator_" + "f" * 32
            elif fault == "linkage":
                body["invocation_sha256"] = "sha256:" + "f" * 64
            else:
                body["decided_at"] = "2026-10-21T00:00:00Z"
            row.data = seal(body, "decision_sha256")
        elif fault == "error":
            session.get(JobRecord, case.job_id).error_code = "FOREIGN_FAILURE"
        else:
            row.from_state = "QUEUED"
    with pytest.raises(ValueError, match="POSTSTART_HISTORY_INVALID"):
        close(case)


def test_untrusted_extras_and_direct_observation_are_not_authority(closure):
    case = closure
    malformed = case.request.model_copy(update={"private_note": "PRIVATE_NOT_FOR_ERRORS"})
    with pytest.raises(ValueError, match="REQUEST_INVALID") as error:
        case.application.close(malformed, job_id=case.job_id)
    assert "PRIVATE_NOT_FOR_ERRORS" not in str(error.value)
    with pytest.raises(TypeError):
        case.application.close(case.request, job_id=case.job_id, observation=observation())


def successor(case, **changes):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.storage[1].inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
    )
    policy = case.request.execution_policy.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-policy/1.1",
        "policy_revision_id": "embeddingbenchmarkpolicyrev_" + uuid4().hex,
        "timeout_seconds": 600,
    }
    body = case.request.model_dump(mode="json") | {
        "schema_version": "embedding-device-benchmark-request/1.1",
        "benchmark_revision_id": revision,
        "execution_policy": seal(policy, "policy_sha256"),
    }
    body.update(changes)
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    return request, SyntheticBenchmarkAdmission(request, inputs)


def submit(case, request, admission, reference):
    with case.sessions() as session, session.begin():
        job, created = submit_benchmark_poststart_successor_in_session(
            session, request, reference, source_admission=admission
        )
        return job.job_id, created


def test_only_explicit_budget_successor_is_registered_once_with_failed_parent_preserved(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case)
    job_id, created = submit(case, request, admission, closed.predecessor)
    assert created and job_id != case.job_id
    assert submit(case, request, admission, closed.predecessor) == (job_id, False)
    with case.sessions() as session:
        parent = session.get(JobRecord, case.job_id)
        child = session.get(JobRecord, job_id)
        assert parent.status == "FAILED" and child.status == "VALIDATED"
        assert parent.request == case.request.model_dump(mode="json")
        assert child.request == request.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        child_events = tuple(
            session.scalars(
                select(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
                .order_by(JobEventRecord.sequence)
            )
        )
        assert child_events[2].event == "BENCHMARK_POSTSTART_SUCCESSOR_REGISTERED"
        assert child_events[2].data == closed.predecessor.model_dump(mode="json")


def test_changed_actor_cannot_be_laundered_as_budget_only_successor(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case, operator_audit_id="operator_" + "f" * 32)
    with pytest.raises(ValueError, match="SUCCESSOR_SELECTION_CONFLICT"):
        submit(case, request, admission, closed.predecessor)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


def test_late_successor_source_revocation_rolls_back_new_identity_and_event(closure):
    case = closure
    closed = close(case)
    request, admission = successor(case)
    admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        submit(case, request, admission, closed.predecessor)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
