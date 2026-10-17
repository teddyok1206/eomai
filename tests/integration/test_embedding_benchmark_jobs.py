"""Marker-guarded PostgreSQL Job concurrency; synthetic source admission, no live model."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_orchestrator.embedding_benchmark_jobs import (
    BenchmarkJobAdmissionError,
    benchmark_job_key,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.embedding_benchmark_launch_history import BenchmarkLaunchJournal
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_benchmark_launch_history import (
    SyntheticResultReader,
    invocation_for,
    receipt_for,
)


def _launch_storage(engine):
    request, inputs = benchmark_case()
    admission, reader = SyntheticBenchmarkAdmission(request, inputs), SyntheticResultReader()
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    return sessions, admission, reader, BenchmarkLaunchJournal(admission, reader), job_id


pytestmark = pytest.mark.integration


def test_postgres_same_identity_replay_has_one_original_job_and_two_events(guarded_engine: Engine):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    identities = []
    for created in (True, False):
        with Session(guarded_engine) as session, session.begin():
            job, observed = submit_benchmark_job_in_session(
                session, request, source_admission=admission
            )
            assert observed is created and job.status == "VALIDATED"
            identities.append((job.job_id, job.logical_artifact_id, job.revision_id))
    assert identities[0] == identities[1] and admission.entered == admission.exited == 2
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identities[0][0])
            )
            == 2
        )
        assert session.get(ArtifactRecord, identities[0][1]) is None


def test_postgres_parallel_submission_is_busy_until_original_commit_then_replays(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    ready, finish = Event(), Event()

    def first():
        admission = SyntheticBenchmarkAdmission(request, inputs)
        with Session(guarded_engine) as session, session.begin():
            job, created = submit_benchmark_job_in_session(
                session, request, source_admission=admission
            )
            assert created
            identifier = job.job_id
            ready.set()
            assert finish.wait(10)
        return identifier

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(first)
        try:
            assert ready.wait(10)
            with (
                pytest.raises(BenchmarkJobAdmissionError, match="SUBMISSION_BUSY"),
                Session(guarded_engine) as session,
                session.begin(),
            ):
                submit_benchmark_job_in_session(
                    session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
                )
        finally:
            finish.set()
        identifier = future.result(timeout=15)
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
        )
        assert not created and job.job_id == identifier
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identifier)
            )
            == 2
        )


def test_postgres_late_authority_failure_rolls_back_job_and_releases_submission_lock(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    admission.late_error = ValueError("SYNTHETIC_EXPIRED")
    with (
        pytest.raises(ValueError, match="EXPIRED"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(session, request, source_admission=admission)
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(JobRecord).where(JobRecord.idempotency_key == benchmark_job_key(request))
            )
            is None
        )
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(
            session, request, source_admission=SyntheticBenchmarkAdmission(request, inputs)
        )
        assert created and job.status == "VALIDATED"


def test_postgres_failed_original_remains_failed_and_changed_identity_payload_conflicts(
    guarded_engine: Engine,
):
    request, inputs = benchmark_case()
    admission = SyntheticBenchmarkAdmission(request, inputs)
    with Session(guarded_engine) as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        identifier = job.job_id
        transition_job(session, identifier, JobState.FAILED, "SYNTHETIC_BENCHMARK_FAILURE")
    body = request.model_dump(mode="json")
    body["policy_sha256"] = "sha256:" + "0" * 64
    other = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    with (
        pytest.raises(BenchmarkJobAdmissionError, match="HISTORY_CONFLICT"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(
            session, other, source_admission=SyntheticBenchmarkAdmission(other, inputs)
        )
    with Session(guarded_engine) as session, session.begin():
        job, created = submit_benchmark_job_in_session(session, request, source_admission=admission)
        assert not created and job.job_id == identifier and job.status == "FAILED"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == identifier)
            )
            == 3
        )


def test_postgres_concurrent_launch_reservation_and_receipt_are_exact_replays(
    guarded_engine: Engine,
):
    sessions, admission, reader, journal, job_id = storage = _launch_storage(guarded_engine)
    invocation = invocation_for(storage, 1)
    receipt = receipt_for(storage, invocation)

    def submit(value, operation):
        with sessions() as session, session.begin():
            return getattr(journal, operation)(session, admission.request, value)[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        for value, operation in ((invocation, "reserve"), (receipt, "record")):
            futures = [executor.submit(submit, value, operation) for _ in range(2)]
            assert sorted(future.result(timeout=15) for future in futures) == [False, True]
    with sessions() as session, session.begin():
        history = journal.read(session, admission.request, job_id=job_id)
        assert len(history.launches) == 1 and history.launches[0].receipt == receipt
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
            )
            == 7
        )
    assert len(reader.reads) == 1


def test_postgres_six_launches_remain_one_job_and_late_failure_rolls_back(guarded_engine: Engine):
    sessions, admission, _, journal, job_id = storage = _launch_storage(guarded_engine)
    for ordinal in range(1, 7):
        invocation = invocation_for(storage, ordinal)
        with sessions() as session, session.begin():
            _, created = journal.reserve(session, admission.request, invocation)
            assert created
        receipt = receipt_for(storage, invocation)
        admission.late_error = ValueError("SYNTHETIC_LATE_REVOKED")
        with (
            pytest.raises(ValueError, match="LATE_REVOKED"),
            sessions() as session,
            session.begin(),
        ):
            journal.record(session, admission.request, receipt)
        admission.late_error = None
        with sessions() as session, session.begin():
            history = journal.read(session, admission.request, job_id=job_id)
            assert history.launches[-1].receipt is None
            _, created = journal.record(session, admission.request, receipt)
            assert created
    with sessions() as session, session.begin():
        history = journal.read(session, admission.request, job_id=job_id)
        assert len(history.launches) == 6 and history.job_state == "RUNNING"
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == job_id)
            )
            == 17
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.job_id == job_id)
            )
            == 0
        )
