"""Disposable SQLite storage shape only; its SQL lock stub is NOT PostgreSQL concurrency."""

import json

import pytest
from eom_catalog_contracts.embedding_device_benchmark import BenchmarkOwnerRequest
from eom_catalog_contracts.validation import catalog_schema_inventory
from eom_orchestrator.embedding_benchmark_jobs import (
    BENCHMARK_JOB_PROTOCOL,
    BENCHMARK_JOB_TASK,
    benchmark_job_key,
    submit_benchmark_job_in_session,
)
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord, ProtocolVersionRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import event, func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher


@pytest.fixture
def storage(tmp_path):
    publisher, engine = _publisher(tmp_path)
    lock = [True]
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function(
            "pg_try_advisory_xact_lock", 1, lambda _: lock[0]
        ),
    )
    engine.dispose()
    request, inputs = benchmark_case()
    yield publisher.sessions, SyntheticBenchmarkAdmission(request, inputs), lock
    engine.dispose()


def test_protocol_and_idempotency_identity_fit_existing_columns(storage):
    _, admission, _ = storage
    assert len(BENCHMARK_JOB_PROTOCOL) <= ProtocolVersionRecord.__table__.c.version.type.length
    assert (
        len(benchmark_job_key(admission.request))
        <= JobRecord.__table__.c.idempotency_key.type.length
    )


def test_real_job_rows_and_append_only_events_are_small_and_replayable(storage):
    sessions, admission, _ = storage
    identities = []
    for created in (True, False):
        with sessions() as session, session.begin():
            job, observed = submit_benchmark_job_in_session(
                session, admission.request, source_admission=admission
            )
            identities.append((job.job_id, job.logical_artifact_id, job.revision_id))
            assert observed is created and job.status == "VALIDATED" and job.worker_slot_id is None
    assert identities[0] == identities[1] and admission.entered == admission.exited == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        job = session.get(JobRecord, identities[0][0])
        assert job.task_type == BENCHMARK_JOB_TASK and job.request == admission.request.model_dump(
            mode="json"
        )
        assert all(
            token not in json.dumps(job.request) for token in ('"text"', '"vectors"', '"token_ids"')
        )
        rows = list(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert [(row.sequence, row.event, row.to_state) for row in rows] == [
            (1, "JOB_CREATED", "CREATED"),
            (2, "BENCHMARK_REQUEST_VALIDATED", "VALIDATED"),
        ]
        assert (
            session.get(ProtocolVersionRecord, BENCHMARK_JOB_PROTOCOL).schema_sha256
            == dict(catalog_schema_inventory())["embedding-device-benchmark"].sha256
        )


def test_same_identity_different_request_is_not_a_new_attempt(storage):
    sessions, admission, _ = storage
    with sessions() as session, session.begin():
        original, _ = submit_benchmark_job_in_session(
            session, admission.request, source_admission=admission
        )
        original_id = original.job_id
    body = admission.request.model_dump(mode="json")
    body["policy_sha256"] = "sha256:" + "f" * 64
    changed = BenchmarkOwnerRequest.model_validate(seal(body, "request_sha256"))
    other = SyntheticBenchmarkAdmission(changed, admission.inputs)
    with (
        pytest.raises(ValueError, match="HISTORY_CONFLICT"),
        sessions() as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(session, changed, source_admission=other)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.get(JobRecord, original_id).request == admission.request.model_dump(
            mode="json"
        )


def test_historical_failure_is_returned_not_reinterpreted_or_retried(storage):
    sessions, admission, _ = storage
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(
            session, admission.request, source_admission=admission
        )
        identifier = job.job_id
        transition_job(session, identifier, JobState.FAILED, "SYNTHETIC_FAILURE")
    with sessions() as session, session.begin():
        job, created = submit_benchmark_job_in_session(
            session, admission.request, source_admission=admission
        )
        assert not created and job.job_id == identifier and job.status == "FAILED"
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 3


@pytest.mark.parametrize("fault", ("missing", "event", "request_hash", "task"))
def test_original_history_must_be_present_and_match_not_just_the_saved_request(storage, fault):
    sessions, admission, _ = storage
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(
            session, admission.request, source_admission=admission
        )
        identifier = job.job_id
        if fault in {"missing", "event"}:
            record = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.job_id == identifier, JobEventRecord.sequence == 2
                )
            )
            if fault == "missing":
                session.delete(record)
            else:
                record.event = "SYNTHETIC_WRONG_HISTORY"
        elif fault == "request_hash":
            job.request_hash = "sha256:" + "0" * 64
        else:
            job.task_type = "synthetic_wrong_task"
    with (
        pytest.raises(ValueError, match="HISTORY_CONFLICT"),
        sessions() as session,
        session.begin(),
    ):
        submit_benchmark_job_in_session(session, admission.request, source_admission=admission)


@pytest.mark.parametrize("fault", ("late", "busy", "nested", "protocol"))
def test_no_job_side_effect_survives_failed_admission(storage, fault):
    sessions, admission, lock = storage
    if fault == "protocol":
        with sessions() as session, session.begin():
            session.add(
                ProtocolVersionRecord(
                    version=BENCHMARK_JOB_PROTOCOL, schema_sha256="sha256:" + "0" * 64
                )
            )
    if fault == "late":
        admission.late_error = ValueError("EXPIRED")
    elif fault == "busy":
        lock[0] = False
    with pytest.raises(ValueError), sessions() as session, session.begin():
        if fault == "nested":
            with session.begin_nested():
                submit_benchmark_job_in_session(
                    session, admission.request, source_admission=admission
                )
        else:
            submit_benchmark_job_in_session(session, admission.request, source_admission=admission)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 0
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
