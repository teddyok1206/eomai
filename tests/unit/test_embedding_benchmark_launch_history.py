"""Synthetic admission/Artifact reader and disposable SQLite, NOT live compute or PG locking."""

import json
from uuid import uuid4

import pytest
from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkLaunchReceipt,
    BenchmarkWorkerInvocation,
    BenchmarkWorkerResult,
    embedding_device_benchmark_bytes,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_benchmark_jobs import submit_benchmark_job_in_session
from eom_orchestrator.embedding_benchmark_launch_history import (
    RECORDED_EVENT,
    RESERVED_EVENT,
    BenchmarkLaunchJournal,
)
from eom_orchestrator.models import ArtifactRecord, JobEventRecord, JobRecord
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import event, func, select

from tests.unit.embedding_benchmark_job_fixtures import SyntheticBenchmarkAdmission, benchmark_case
from tests.unit.embedding_device_benchmark_fixtures import (
    launch_receipt,
    worker_invocation,
    worker_result,
)
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_control_file_set_publication import _publisher


class SyntheticResultReader:
    def __init__(self):
        self.members = {}
        self.reads = []

    def read_in_session(self, session, request, pointer):
        assert session.get_transaction() is not None and not session.in_nested_transaction()
        self.reads.append(pointer)
        return self.members[pointer.sha256]


@pytest.fixture
def storage(tmp_path):
    publisher, engine = _publisher(tmp_path)
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function(
            "pg_try_advisory_xact_lock", 1, lambda _: True
        ),
    )
    engine.dispose()
    request, inputs = benchmark_case()
    admission, reader = SyntheticBenchmarkAdmission(request, inputs), SyntheticResultReader()
    sessions = publisher.sessions
    with sessions() as session, session.begin():
        job, _ = submit_benchmark_job_in_session(session, request, source_admission=admission)
        job_id = job.job_id
        for state in (JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job_id, state, "SYNTHETIC_" + state)
    yield sessions, admission, reader, BenchmarkLaunchJournal(admission, reader), job_id
    engine.dispose()


def invocation_for(storage, ordinal):
    _, admission, _, _, job_id = storage
    body = worker_invocation(ordinal).model_dump(mode="json")
    body.update(
        job_id=job_id,
        benchmark_id=admission.request.benchmark_id,
        benchmark_revision_id=admission.request.benchmark_revision_id,
        owner_request_sha256=admission.request.request_sha256,
        local_input={
            "member_name": "benchmark-inputs.json",
            "sha256": sha256_bytes(embedding_device_benchmark_bytes(admission.inputs)),
            "byte_count": len(embedding_device_benchmark_bytes(admission.inputs)),
        },
    )
    return BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))


def receipt_for(storage, invocation, *, cleanup="CONFIRMED", failed=False):
    reader = storage[2]
    body = worker_result(invocation.launch_ordinal).model_dump(mode="json")
    body.update(
        execution_id=invocation.execution_id, invocation_sha256=invocation.invocation_sha256
    )
    for field, digest in (("resources", "resource_sha256"), ("timings", "timing_sha256")):
        body[field]["invocation_sha256"] = invocation.invocation_sha256
        body[field] = seal(body[field], digest)
    if failed:
        body.update(status="FAILED", reason_codes=["SOURCE_ONLY_NOT_ACTIVATED"])
    result = BenchmarkWorkerResult.model_validate(seal(body, "result_sha256"))
    raw = embedding_device_benchmark_bytes(result)
    reader.members[sha256_bytes(raw)] = raw
    body = launch_receipt(invocation.launch_ordinal).model_dump(mode="json")
    body.update(
        job_id=invocation.job_id,
        execution_id=invocation.execution_id,
        invocation_sha256=invocation.invocation_sha256,
        cleanup=cleanup,
    )
    body["worker_result"]["sha256"] = sha256_bytes(raw)
    return BenchmarkLaunchReceipt.model_validate(seal(body, "receipt_sha256"))


def reserve(storage, invocation):
    sessions, admission, _, journal, _ = storage
    with sessions() as session, session.begin():
        return journal.reserve(session, admission.request, invocation)


def record(storage, receipt):
    sessions, admission, _, journal, _ = storage
    with sessions() as session, session.begin():
        return journal.record(session, admission.request, receipt)


def test_six_exact_ordered_original_job_records_and_replay(storage):
    sessions, admission, reader, journal, job_id = storage
    for ordinal in range(1, 7):
        invocation = invocation_for(storage, ordinal)
        history, created = reserve(storage, invocation)
        assert created and len(history.launches) == ordinal
        assert history.launches[-1].receipt is None
        assert reserve(storage, invocation) == (history, False)
        receipt = receipt_for(storage, invocation)
        history, created = record(storage, receipt)
        assert created and history.launches[-1].receipt == receipt
        assert record(storage, receipt) == (history, False)
    with sessions() as session, session.begin():
        assert journal.read(session, admission.request, job_id=job_id) == history
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactRecord)) == 0
        rows = list(session.scalars(select(JobEventRecord).order_by(JobEventRecord.sequence)))
        assert [row.event for row in rows[5:]] == [RESERVED_EVENT, RECORDED_EVENT] * 6
        assert [row.sequence for row in rows] == list(range(1, 18))
        assert all(
            key not in json.dumps([row.data for row in rows])
            for key in ('"text"', '"vectors"', '"token_ids"')
        )
    assert len(reader.reads) == 11


def test_reservation_is_unresolved_not_permission_to_restart(storage):
    invocation = invocation_for(storage, 1)
    reserve(storage, invocation)
    with pytest.raises(ValueError, match="PREVIOUS_UNRESOLVED"):
        reserve(storage, invocation_for(storage, 2))
    body = invocation.model_dump(mode="json")
    body["execution_id"] = uuid4().hex
    changed = BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256"))
    with pytest.raises(ValueError, match="RESERVATION_CONFLICT"):
        reserve(storage, changed)
    assert not storage[2].reads


@pytest.mark.parametrize("fault", ("uncertain", "failed", "missing", "hash", "foreign"))
def test_no_next_launch_from_unconfirmed_unresolved_or_failed_evidence(storage, fault):
    invocation = invocation_for(storage, 1)
    reserve(storage, invocation)
    receipt = receipt_for(
        storage,
        invocation,
        cleanup="UNCERTAIN" if fault == "uncertain" else "CONFIRMED",
        failed=fault == "failed",
    )
    record(storage, receipt)
    if fault == "missing":
        storage[2].members.clear()
    elif fault == "hash":
        storage[2].members[receipt.worker_result.sha256] += b" "
    elif fault == "foreign":
        storage[2].members[receipt.worker_result.sha256] = embedding_device_benchmark_bytes(
            worker_result(2)
        )
    with pytest.raises((ValueError, KeyError)):
        reserve(storage, invocation_for(storage, 2))
    assert len(reserve(storage, invocation)[0].launches) == 1


def test_skip_reuse_and_receipt_before_reservation_are_rejected(storage):
    with pytest.raises(ValueError, match="NOT_RUNNABLE"):
        reserve(storage, invocation_for(storage, 2))
    with pytest.raises(ValueError, match="NOT_RESERVED"):
        record(storage, receipt_for(storage, invocation_for(storage, 1)))
    first = invocation_for(storage, 1)
    reserve(storage, first)
    record(storage, receipt_for(storage, first))
    body = invocation_for(storage, 2).model_dump(mode="json")
    body["execution_id"] = first.execution_id
    with pytest.raises(ValueError, match="EXECUTION_REUSED"):
        reserve(storage, BenchmarkWorkerInvocation.model_validate(seal(body, "invocation_sha256")))


def test_terminal_history_replay_does_not_reopen_or_append(storage):
    sessions, admission, _, journal, job_id = storage
    invocation = invocation_for(storage, 1)
    reserve(storage, invocation)
    with sessions() as session, session.begin():
        transition_job(session, job_id, JobState.FAILED, "SYNTHETIC_UNCERTAIN_EXECUTION")
    history, created = reserve(storage, invocation)
    assert not created and history.job_state == "FAILED"
    with pytest.raises(ValueError, match="NOT_RUNNABLE"):
        record(storage, receipt_for(storage, invocation))
    with sessions() as session, session.begin():
        assert journal.read(session, admission.request, job_id=job_id).job_state == "FAILED"


@pytest.mark.parametrize("action", ("read", "reserve", "record"))
def test_current_source_and_late_session_fence_protect_every_operation(storage, action):
    sessions, admission, _, journal, job_id = storage
    invocation = invocation_for(storage, 1)
    reserve(storage, invocation)
    receipt = receipt_for(storage, invocation)
    admission.late_error = ValueError("SYNTHETIC_SESSION_REVOKED")
    with pytest.raises(ValueError, match="SESSION_REVOKED"), sessions() as session, session.begin():
        if action == "read":
            journal.read(session, admission.request, job_id=job_id)
        elif action == "reserve":
            journal.reserve(session, admission.request, invocation)
        else:
            journal.record(session, admission.request, receipt)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobEventRecord)) == 6


@pytest.mark.parametrize("fault", ("initial", "request", "event", "payload", "transition"))
def test_invalid_original_or_launch_history_is_explicit(storage, fault):
    sessions, admission, _, journal, job_id = storage
    reserve(storage, invocation_for(storage, 1))
    with sessions() as session, session.begin():
        if fault == "request":
            session.get(JobRecord, job_id).request_hash = "sha256:" + "0" * 64
        else:
            row = session.scalar(
                select(JobEventRecord).where(
                    JobEventRecord.job_id == job_id,
                    JobEventRecord.sequence == (2 if fault == "initial" else 6),
                )
            )
            if fault in {"initial", "event"}:
                row.event = "WRONG"
            elif fault == "payload":
                row.data = {**row.data, "invocation_sha256": "sha256:" + "0" * 64}
            else:
                row.to_state = "SUCCEEDED"
    with pytest.raises(ValueError), sessions() as session, session.begin():
        journal.read(session, admission.request, job_id=job_id)
