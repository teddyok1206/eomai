"""Opt-in disposable PG only; root inspection and authority are explicitly synthetic.

No installed unit, controller, model, GPU, NAS or production database is accessed.
The guarded fixture, not an ambient database URL, authorizes test persistence.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_benchmark_prelaunch_failure import (
    MAX_PRELAUNCH_FAILURE_BYTES,
    PRELAUNCH_FAILURE_CODE,
    PRELAUNCH_FAILURE_EVENT,
    BenchmarkPrelaunchObservation,
    BenchmarkPrelaunchPredecessorReference,
    benchmark_prelaunch_failure_bytes,
)
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import content_sha256, new_revision_id, sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    benchmark_job_key,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import (
    PREDECESSOR_EVENT,
    RECORDED_EVENT,
    RESERVED_EVENT,
    BenchmarkLaunchJournal,
)
from eom_orchestrator.embedding_benchmark_prelaunch_failure import (
    BenchmarkPrelaunchFailureApplication,
    submit_benchmark_prelaunch_successor_in_session,
)
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, Text, cast, func, select
from sqlalchemy.orm import sessionmaker

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_benchmark_job_fixtures import benchmark_case
from tests.unit.embedding_benchmark_prelaunch_failure_fixtures import observation
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import SyntheticResultReader, invocation_for

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


class SyntheticRecoveryAdmission:
    """Failure after a staged event exercises rollback, not an early rejected read."""

    def __init__(self, request, inputs):
        self.cases = {request.request_sha256: (request, inputs)}
        self.fail_after_event = None
        self.late_failures = 0

    def register(self, request, inputs):
        self.cases[request.request_sha256] = request, inputs

    @contextmanager
    def admit_in_session(self, session, request):
        expected, inputs = self.cases[request.request_sha256]
        assert request == expected and not session.in_nested_transaction()
        yield inputs
        if self.fail_after_event is not None:
            staged = session.scalar(
                select(JobEventRecord.event_id)
                .join(JobRecord, JobRecord.job_id == JobEventRecord.job_id)
                .where(
                    JobRecord.idempotency_key == benchmark_job_key(request),
                    JobEventRecord.event == self.fail_after_event,
                )
            )
            if staged is not None:
                self.late_failures += 1
                raise ValueError("SYNTHETIC_LATE_AUTHORIZATION_REVOKED")

    def admit_execution_in_session(self, session, request):
        return self.admit_in_session(session, request)

    def read_in_session(self, session, request, pointer):
        pytest.fail("pre-launch closure must not materialize a worker result or NAS Artifact")


@dataclass(frozen=True)
class SyntheticCapturedInspection:
    observation: BenchmarkPrelaunchObservation

    def assert_current(self):
        """Synthetic OS stability only; never installed/root-origin proof."""


class SyntheticInspection:
    def __init__(self, request, invocation):
        self.request, self.invocation = request, invocation
        self.barrier = None
        body = observation(request, invocation).model_dump(mode="json")
        body["observed_at"] = (
            (datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        )
        self.observation = BenchmarkPrelaunchObservation.model_validate(
            seal(body, "observation_sha256")
        )

    @contextmanager
    def capture(self, request, invocation):
        assert request == self.request and invocation == self.invocation
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        yield SyntheticCapturedInspection(self.observation)


def _case(engine):
    request, inputs = benchmark_case()
    admission = SyntheticRecoveryAdmission(request, inputs)
    sessions = sessionmaker(engine, expire_on_commit=False)
    reader = SyntheticResultReader()
    journal = BenchmarkLaunchJournal(admission, reader)
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    storage = sessions, SimpleNamespace(request=request, inputs=inputs), reader, journal, job_id
    invocation = invocation_for(storage, 1)
    with sessions() as session, session.begin():
        journal.reserve(session, request, invocation)
    inspection = SyntheticInspection(request, invocation)
    application = BenchmarkPrelaunchFailureApplication(
        sessions, admission=admission, inspection=inspection
    )
    return SimpleNamespace(
        sessions=sessions,
        request=request,
        inputs=inputs,
        admission=admission,
        journal=journal,
        job_id=job_id,
        invocation=invocation,
        inspection=inspection,
        application=application,
    )


def _successor(case):
    revision = "embeddingbenchmarkrev_" + uuid4().hex
    inputs = BenchmarkStagedInputs.model_validate(
        case.inputs.model_dump(mode="json") | {"benchmark_revision_id": revision}
    )
    body = case.request.model_dump(mode="json")
    body["benchmark_revision_id"] = revision
    body["input_manifest"]["artifact_revision_id"] = new_revision_id()
    body["input_manifest"]["sha256"] = sha256_bytes(embedding_device_benchmark_bytes(inputs))
    request = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    case.admission.register(request, inputs)
    return request


def _events(session, job_id):
    return tuple(
        session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job_id)
            .order_by(JobEventRecord.sequence)
        )
    )


def test_postgres_concurrent_closure_preserves_one_original_decision_and_no_binary_artifacts(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    barrier = Barrier(2)
    case.inspection.barrier = Barrier(2)

    def close():
        barrier.wait(timeout=10)
        return case.application.close(case.request, job_id=case.job_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(close) for _ in range(2)]
        results = tuple(future.result(timeout=20) for future in futures)
    case.inspection.barrier = None
    assert sorted(result.created for result in results) == [False, True]
    original = next(result for result in results if result.created)
    assert all(result.decision == original.decision for result in results)
    assert all(result.event_sequence == original.event_sequence == 7 for result in results)
    replay = case.application.close(case.request, job_id=case.job_id)
    assert not replay.created and replay.decision == original.decision
    assert replay.predecessor == original.predecessor

    with case.sessions() as session, session.begin():
        job = session.get(JobRecord, case.job_id)
        assert job.status == "FAILED" and job.error_code == PRELAUNCH_FAILURE_CODE
        assert job.request == case.request.model_dump(mode="json")
        events = _events(session, case.job_id)
        assert tuple(row.sequence for row in events) == tuple(range(1, 8))
        assert [row.event for row in events].count(PRELAUNCH_FAILURE_EVENT) == 1
        assert [row.event for row in events].count(RESERVED_EVENT) == 1
        assert RECORDED_EVENT not in {row.event for row in events}
        assert events[-1].data == original.decision.model_dump(mode="json")
        assert (
            len(benchmark_prelaunch_failure_bytes(original.decision)) < MAX_PRELAUNCH_FAILURE_BYTES
        )
        assert (
            session.scalar(
                select(func.octet_length(cast(JobEventRecord.data, Text))).where(
                    JobEventRecord.job_id == case.job_id,
                    JobEventRecord.sequence == original.event_sequence,
                )
            )
            < MAX_PRELAUNCH_FAILURE_BYTES
        )
        for model in (ArtifactRecord, ArtifactRevisionRecord):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.job_id == case.job_id)
                )
                == 0
            )
        history = case.journal.read(session, case.request, job_id=case.job_id)
        assert history.launches[0].invocation == case.invocation
        assert history.launches[0].receipt is None


def test_postgres_unresolved_predecessor_denies_successor_without_target_allocation(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    request = _successor(case)
    predecessor = BenchmarkPrelaunchPredecessorReference(
        schema_version="embedding-benchmark-prelaunch-failure/1.0",
        kind="PREDECESSOR_REFERENCE",
        job_id=case.job_id,
        execution_id=case.invocation.execution_id,
        request_sha256=case.request.request_sha256,
        invocation_sha256=case.invocation.invocation_sha256,
        event_sequence=7,
        decision_sha256=content_sha256("synthetic unrecorded closure"),
    )
    with (
        pytest.raises(BenchmarkJobAdmissionError, match="PREDECESSOR_NOT_TERMINAL"),
        case.sessions() as session,
        session.begin(),
    ):
        submit_benchmark_prelaunch_successor_in_session(
            session, request, predecessor, source_admission=case.admission
        )
    with case.sessions() as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
        assert session.get(JobRecord, case.job_id).status == "RUNNING"
        assert len(_events(session, case.job_id)) == 6


def test_postgres_successor_replay_pins_one_predecessor_event_and_late_revocation_rolls_back(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    closure = case.application.close(case.request, job_id=case.job_id)
    request = _successor(case)
    case.admission.fail_after_event = PREDECESSOR_EVENT
    with (
        pytest.raises(ValueError, match="LATE_AUTHORIZATION_REVOKED"),
        case.sessions() as session,
        session.begin(),
    ):
        submit_benchmark_prelaunch_successor_in_session(
            session, request, closure.predecessor, source_admission=case.admission
        )
    assert case.admission.late_failures == 1
    with case.sessions() as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
        assert len(_events(session, case.job_id)) == 7
    case.admission.fail_after_event = None
    identifiers = []
    for expected_created in (True, False):
        with case.sessions() as session, session.begin():
            job, created = submit_benchmark_prelaunch_successor_in_session(
                session, request, closure.predecessor, source_admission=case.admission
            )
            assert created is expected_created and job.status == "VALIDATED"
            identifiers.append(job.job_id)
    assert identifiers[0] == identifiers[1] != case.job_id
    with case.sessions() as session:
        events = _events(session, identifiers[0])
        assert tuple(row.sequence for row in events) == (1, 2, 3)
        assert events[-1].event == PREDECESSOR_EVENT
        assert events[-1].data == closure.predecessor.model_dump(mode="json")
        assert session.get(JobRecord, case.job_id).status == "FAILED"
        assert _events(session, case.job_id)[-1].data == closure.decision.model_dump(mode="json")


def test_postgres_closure_late_authority_failure_rolls_back_then_exact_original_can_close(
    guarded_engine: Engine,
):
    case = _case(guarded_engine)
    case.admission.fail_after_event = PRELAUNCH_FAILURE_EVENT
    with pytest.raises(ValueError, match="LATE_AUTHORIZATION_REVOKED"):
        case.application.close(case.request, job_id=case.job_id)
    assert case.admission.late_failures == 1
    with case.sessions() as session:
        job = session.get(JobRecord, case.job_id)
        assert job.status == "RUNNING" and job.completed_at is None and job.error_code is None
        assert len(_events(session, case.job_id)) == 6
    case.admission.fail_after_event = None
    closed = case.application.close(case.request, job_id=case.job_id)
    assert closed.created and closed.decision.observation == case.inspection.observation
    with case.sessions() as session:
        assert len(_events(session, case.job_id)) == 7
