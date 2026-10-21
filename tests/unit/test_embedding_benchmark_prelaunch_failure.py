"""Synthetic inspection/admission and SQLite; neither root proof nor PG concurrency."""

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    PRELAUNCH_FAILURE_CODE,
    PRELAUNCH_FAILURE_EVENT,
    BenchmarkPrelaunchObservation,
    BenchmarkPrelaunchPredecessorReference,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import (
    read_terminal_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import (
    PREDECESSOR_EVENT,
    BenchmarkLaunchJournal,
)
from eom_orchestrator.embedding_benchmark_prelaunch_failure import (
    BenchmarkPrelaunchFailureApplication,
    submit_benchmark_prelaunch_successor_in_session,
)
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission
from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import invocation_for, receipt_for
from tests.unit.test_embedding_benchmark_launch_history import storage as storage
from tests.unit.test_embedding_device_benchmark_owner import SyntheticOwnerAdmission


class SyntheticInspection:
    def __init__(self, seen):
        self.observation = seen
        self.captures = self.checks = 0
        self.fail_check = None
        self.on_capture = None

    def assert_current(self):
        self.checks += 1
        if self.checks == self.fail_check:
            raise ValueError("SYNTHETIC_PROOF_CHANGED")

    @contextmanager
    def capture(self, request, invocation):
        self.captures += 1
        assert request.request_sha256 == self.observation.request_sha256
        if self.on_capture is not None:
            self.on_capture()
        yield self


@pytest.fixture
def closure(storage):
    sessions, source, reader, journal, job_id = storage
    invocation = invocation_for(storage, 1)
    with sessions() as session, session.begin():
        journal.reserve(session, source.request, invocation)
    seen = observation(source.request, invocation).model_dump(mode="json")
    seen["observed_at"] = (
        (datetime.now(UTC) - timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    inspection = SyntheticInspection(
        BenchmarkPrelaunchObservation.model_validate(seal(seen, "observation_sha256"))
    )
    admission = SyntheticOwnerAdmission(source.request, source.inputs, reader)
    application = BenchmarkPrelaunchFailureApplication(
        sessions, admission=admission, inspection=inspection
    )
    return SimpleNamespace(
        sessions=sessions,
        source=source,
        reader=reader,
        journal=journal,
        job_id=job_id,
        invocation=invocation,
        inspection=inspection,
        admission=admission,
        application=application,
        request=source.request,
        inputs=source.inputs,
        storage=storage,
    )


def close(case):
    return case.application.close(case.request, job_id=case.job_id)


def successor(case, **changes):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
    )
    body = case.request.model_dump(mode="json")
    body.update(benchmark_revision_id=revision, **changes)
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    return request, SyntheticBenchmarkAdmission(request, inputs)


def submit(case, request, admission, predecessor):
    with case.sessions() as session, session.begin():
        result, created = submit_benchmark_prelaunch_successor_in_session(
            session, request, predecessor, source_admission=admission
        )
        return result.job_id, created


def test_closure_preserves_reservation_and_returns_exact_stored_replay_without_inspection(closure):
    case = closure
    result = close(case)
    assert result.created and result.event_sequence == 7
    assert result.decision.observation == case.inspection.observation
    assert result.predecessor == BenchmarkPrelaunchPredecessorReference.from_decision(
        result.decision, event_sequence=7
    )
    with case.sessions() as session, session.begin():
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.job_state == "FAILED" and history.launches[0].receipt is None
        assert history.launches[0].invocation == case.invocation
        job = session.get(JobRecord, case.job_id)
        assert job.error_code == PRELAUNCH_FAILURE_CODE and job.completed_at is not None
        rows = tuple(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert len(rows) == 7 and rows[5].event == "BENCHMARK_LAUNCH_RESERVED"
        assert rows[6].event == PRELAUNCH_FAILURE_EVENT
        assert rows[6].data == result.decision.model_dump(mode="json")
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        assert all(token not in json.dumps(rows[6].data) for token in ('"text"', '"vectors"'))
    count = case.inspection.checks
    case.inspection.fail_check = count + 1
    replay = close(case)
    assert not replay.created and replay.decision == result.decision
    assert replay.event_sequence == result.event_sequence
    assert case.inspection.captures == 1 and case.inspection.checks == count


@pytest.mark.parametrize("fail_check", (1, 2, 3, 4))
def test_initial_or_late_inspection_failure_rolls_back_original_terminalization(
    closure, fail_check
):
    case = closure
    case.inspection.fail_check = fail_check
    with pytest.raises(ValueError, match="PROOF_CHANGED"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 6


@pytest.mark.parametrize("replay", (False, True))
def test_current_and_late_actual_admission_still_protect_closure_and_replay(closure, replay):
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


def test_late_authority_after_root_capture_rolls_back(closure):
    case = closure
    case.inspection.on_capture = lambda: setattr(
        case.admission, "late_error", ValueError("SYNTHETIC_REVOKED_AFTER_CAPTURE")
    )
    with pytest.raises(ValueError, match="REVOKED_AFTER_CAPTURE"):
        close(case)
    with case.sessions() as session:
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 6


@pytest.mark.parametrize(
    "field", ("execution_id", "invocation_raw_sha256", "invocation_sha256", "job_id")
)
def test_foreign_rehashed_observation_cannot_close_original(closure, field):
    case = closure
    body = case.inspection.observation.model_dump(mode="json")
    body[field] = {
        "execution_id": "f" * 32,
        "job_id": "job_" + "f" * 32,
        "invocation_raw_sha256": "sha256:" + "f" * 64,
        "invocation_sha256": "sha256:" + "f" * 64,
    }[field]
    case.inspection.observation = BenchmarkPrelaunchObservation.model_validate(
        seal(body, "observation_sha256")
    )
    with pytest.raises(ValueError, match="OBSERVATION_CONFLICT"):
        close(case)


def test_model_copy_bypass_and_direct_parsed_report_are_not_proof_input(closure):
    case = closure
    case.inspection.observation = case.inspection.observation.model_copy(
        update={"output_count": 15}
    )
    with pytest.raises(ValueError):
        close(case)
    with pytest.raises(TypeError):
        case.application.close(case.request, job_id=case.job_id, observation=observation())


def test_malformed_request_and_reference_errors_never_echo_untrusted_private_extras(closure):
    case = closure
    malformed = case.request.model_copy(update={"private_note": "PRIVATE_NOT_FOR_ERRORS"})
    with pytest.raises(ValueError, match="REQUEST_INVALID") as error:
        case.application.close(malformed, job_id=case.job_id)
    assert "PRIVATE_NOT_FOR_ERRORS" not in str(error.value)
    closed = close(case)
    request, admission = successor(case)
    predecessor = closed.predecessor.model_copy(update={"private_note": "PRIVATE_NOT_FOR_ERRORS"})
    with pytest.raises(ValueError, match="SUCCESSOR_INVALID") as error:
        submit(case, request, admission, predecessor)
    assert "PRIVATE_NOT_FOR_ERRORS" not in str(error.value)


@pytest.mark.parametrize("state", (JobState.FAILED, JobState.CANCELLED))
def test_different_terminal_failure_is_not_rewritten(closure, state):
    case = closure
    with case.sessions() as session, session.begin():
        transition_job(session, case.job_id, state, "SYNTHETIC_FOREIGN_FAILURE")
    with pytest.raises(ValueError, match="TERMINAL_OR_FOREIGN"):
        close(case)
    assert case.inspection.captures == 0


def test_any_recorded_native_result_blocks_prelaunch_closure(closure):
    case = closure
    with case.sessions() as session, session.begin():
        case.journal.record(session, case.request, receipt_for(case.storage, case.invocation))
    with pytest.raises(ValueError, match="ORIGINAL_UNRESOLVED_REQUIRED"):
        close(case)


@pytest.mark.parametrize("fault", ("actor", "linkage", "error", "event", "transition"))
def test_tampered_terminal_decision_is_not_laundered_by_generic_history_transition(closure, fault):
    case = closure
    close(case)
    with case.sessions() as session, session.begin():
        row = session.scalar(select(JobEventRecord).where(JobEventRecord.sequence == 7))
        if fault in {"actor", "linkage"}:
            body = dict(row.data)
            if fault == "actor":
                body["actor_id"] = "operator_" + "f" * 32
            else:
                body["observation"] = seal(
                    body["observation"] | {"invocation_raw_sha256": "sha256:" + "f" * 64},
                    "observation_sha256",
                )
            row.data = seal(body, "decision_sha256")
        elif fault == "error":
            session.get(JobRecord, case.job_id).error_code = "FOREIGN"
        elif fault == "event":
            row.event = "SYNTHETIC_FOREIGN_FAILURE"
        else:
            row.from_state = "VALIDATED"
    with pytest.raises(ValueError):
        close(case)


def test_successor_requires_closed_parent_and_records_exact_immutable_reference(closure):
    case = closure
    result = close(case)
    request, admission = successor(case)
    identifier, created = submit(case, request, admission, result.predecessor)
    assert created and submit(case, request, admission, result.predecessor) == (identifier, False)
    with case.sessions() as session, session.begin():
        history = BenchmarkLaunchJournal(admission, case.reader).read(
            session, request, job_id=identifier
        )
        assert history.predecessor == result.predecessor and history.job_state == "VALIDATED"
        rows = tuple(
            session.scalars(select(JobEventRecord).where(JobEventRecord.job_id == identifier))
        )
        assert len(rows) == 3 and rows[-1].event == PREDECESSOR_EVENT
        assert rows[-1].data == result.predecessor.model_dump(mode="json")
        assert session.get(JobRecord, case.job_id).status == "FAILED"
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 2


def test_unresolved_parent_never_allocates_target_or_independent_execution(closure):
    case = closure
    seen = case.inspection.observation
    reference = BenchmarkPrelaunchPredecessorReference(
        schema_version="embedding-benchmark-prelaunch-failure/1.0",
        kind="PREDECESSOR_REFERENCE",
        job_id=case.job_id,
        execution_id=seen.execution_id,
        request_sha256=seen.request_sha256,
        invocation_sha256=seen.invocation_sha256,
        event_sequence=7,
        decision_sha256="sha256:" + "f" * 64,
    )
    request, admission = successor(case)
    with pytest.raises(ValueError, match="NOT_TERMINAL"):
        submit(case, request, admission, reference)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize("field", ("policy_sha256", "operator_audit_id", "input_set_sha256"))
def test_successor_cannot_change_source_actor_or_measurement_identity(closure, field):
    case = closure
    result = close(case)
    changed = "operator_" + "f" * 32 if field == "operator_audit_id" else "sha256:" + "f" * 64
    request, admission = successor(case, **{field: changed})
    with pytest.raises(ValueError, match="SELECTION_CONFLICT"):
        submit(case, request, admission, result.predecessor)


def test_successor_late_revocation_rolls_back_job_and_predecessor_event(closure):
    case = closure
    result = close(case)
    request, admission = successor(case)
    admission.late_error = ValueError("SYNTHETIC_REVOKED")
    with pytest.raises(ValueError, match="REVOKED"):
        submit(case, request, admission, result.predecessor)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 7


@pytest.mark.parametrize("field", ("job_id", "event_sequence", "decision_sha256", "execution_id"))
def test_forged_predecessor_reference_cannot_allocate_successor(closure, field):
    case = closure
    result = close(case)
    request, admission = successor(case)
    body = result.predecessor.model_dump(mode="json")
    body[field] = {
        "job_id": "job_" + "f" * 32,
        "event_sequence": 8,
        "decision_sha256": "sha256:" + "f" * 64,
        "execution_id": "f" * 32,
    }[field]
    reference = BenchmarkPrelaunchPredecessorReference.model_validate(body)
    with pytest.raises(ValueError):
        submit(case, request, admission, reference)
    with case.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1


@pytest.mark.parametrize("fault", ("sequence", "decision", "self", "state", "duplicate"))
def test_target_predecessor_event_is_validated_on_every_history_read(closure, fault):
    case = closure
    result = close(case)
    request, admission = successor(case)
    identifier, _ = submit(case, request, admission, result.predecessor)
    with case.sessions() as session, session.begin():
        row = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == identifier, JobEventRecord.sequence == 3
            )
        )
        if fault == "sequence":
            row.data = row.data | {"event_sequence": 8}
        elif fault == "decision":
            row.data = row.data | {"decision_sha256": "sha256:" + "f" * 64}
        elif fault == "self":
            row.data = row.data | {"job_id": identifier}
        elif fault == "state":
            row.to_state = "RUNNING"
        else:
            session.add(
                JobEventRecord(
                    job_id=identifier,
                    sequence=4,
                    from_state="VALIDATED",
                    to_state="VALIDATED",
                    event=PREDECESSOR_EVENT,
                    data=dict(row.data),
                )
            )
    with pytest.raises(ValueError), case.sessions() as session, session.begin():
        BenchmarkLaunchJournal(admission, case.reader).read(session, request, job_id=identifier)


def test_successor_can_reach_ordinary_first_reservation_without_reusing_original_execution(closure):
    case = closure
    result = close(case)
    request, admission = successor(case)
    identifier, _ = submit(case, request, admission, result.predecessor)
    journal = BenchmarkLaunchJournal(admission, case.reader)
    target_storage = case.sessions, admission, case.reader, journal, identifier
    target_invocation = invocation_for(target_storage, 1)
    body = target_invocation.model_dump(mode="json") | {"execution_id": uuid4().hex}
    from eom_catalog_contracts.embedding_device_benchmark import BenchmarkWorkerInvocation

    target_invocation = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    with case.sessions() as session, session.begin():
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, identifier, state, "SYNTHETIC_" + state)
        history, created = journal.reserve(session, request, target_invocation)
        assert created and history.predecessor == result.predecessor
        assert history.launches[0].invocation.execution_id != case.invocation.execution_id
        assert session.get(JobRecord, case.job_id).status == "FAILED"


def test_nonlocking_terminal_reader_cannot_be_used_for_running_job(closure):
    case = closure
    with (
        pytest.raises(ValueError, match="NOT_TERMINAL"),
        case.sessions() as session,
        session.begin(),
    ):
        read_terminal_benchmark_job_in_session(session, case.request, job_id=case.job_id)
