"""Disposable PostgreSQL retry graph, not actual root/IAM/numeric or maintenance proof."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationError,
)
from eom_orchestrator.embedding_encoding_reservation_storage import (
    EmbeddingEncodingReservationStorage as Storage,
)
from eom_orchestrator.embedding_encoding_reservations import EmbeddingEncodingReservations
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.embedding_encoding_recovery import ENCODING_RETRY_SUCCESSOR_EVENT
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tests.integration.test_embedding_encoding_reservations import (
    SyntheticCommittedMetadataAdmission,
    _commit_metadata,
    _fixture,
    _owned_fixture,
    _seed_launch,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_encoding_recovery_fixtures import known_failure, unpublished_failure
from tests.unit.embedding_encoding_reservation_fixtures import references, requests
from tests.unit.test_embedding_encoding_reservations import SyntheticAdmission

pytestmark = pytest.mark.integration


def new_owner(engine, partition, seeds=("a", "b")):
    fixture = _fixture(*seeds, partition=partition)
    _seed_launch(engine, fixture)
    admission = SyntheticAdmission(fixture)
    api = EmbeddingEncodingReservations(build_session_factory(engine), admission)
    return fixture, admission, api


def fail_owned(engine, fixture, admission, api, rows, *, failure_factory=known_failure):
    fixture = _owned_fixture(fixture, rows)
    admission.fixture = fixture
    api.bind_launch(fixture.association)
    values = tuple(
        sorted(
            (
                failure_factory(j, fixture.association.intent.native_launch_job_id)
                for j in fixture.association.owned_jobs
            ),
            key=lambda v: v.owned_job.job_reference.job_id,
        )
    )
    with Session(engine) as session, session.begin():
        Storage.prepare_recovery_protocol(session)
        Storage.record_known_failures(session, values)
    return fixture, values


@pytest.mark.parametrize("failure_factory", [known_failure, unpublished_failure])
def test_actual_retry_replay_borrow_completion_and_old_failed_reference_are_separate(
    guarded_engine,
    failure_factory,
):
    partition = "test-" + uuid4().hex
    old, old_gate, old_api = new_owner(guarded_engine, partition)
    reserved = old_api.reserve_and_attach(requests(old), old.association.intent)
    old, failures = fail_owned(
        guarded_engine, old, old_gate, old_api, reserved, failure_factory=failure_factory
    )
    new, _gate, api = new_owner(guarded_engine, partition)
    assert {r.status for r in api.reserve_and_attach(requests(new), new.association.intent)} == {
        "FAILED"
    }
    retried = api.retry_known_failed(requests(new), new.association.intent)
    assert {r.status for r in retried} == {"OWNED"}
    assert {r.owned_job.request for r in retried} == {r.owned_job.request for r in reserved}
    assert {r.owned_job.job_reference for r in retried}.isdisjoint(
        {r.owned_job.job_reference for r in reserved}
    )
    assert api.retry_known_failed(requests(new), new.association.intent) == retried
    completed = _owned_fixture(new, retried)
    proof_gate = SyntheticCommittedMetadataAdmission(completed)
    complete_api = EmbeddingEncodingReservations(build_session_factory(guarded_engine), proof_gate)
    complete_api.bind_launch(completed.association)
    _commit_metadata(guarded_engine, completed)
    assert {r.status for r in complete_api.complete(completed.completions)} == {"COMPLETED"}
    assert {
        r.status for r in old_api.read(tuple(sorted(references(old), key=lambda r: r.job_id)))
    } == {"FAILED"}
    later, _, later_api = new_owner(guarded_engine, partition)
    assert {
        r.status for r in later_api.reserve_and_attach(requests(later), later.association.intent)
    } == {"COMPLETED"}
    with Session(guarded_engine) as session, session.begin():
        assert {f.owned_job.job_reference.job_id for f in failures} == {
            r.owned_job.job_reference.job_id for r in reserved
        }
        for failure in failures:
            job = session.get(JobRecord, failure.owned_job.job_reference.job_id)
            assert job.status == "FAILED" and job.completed_at is not None
            assert Storage.known_failures(session, (job,))[job.job_id] == failure


@pytest.mark.parametrize("failure_factory", [known_failure, unpublished_failure])
def test_concurrent_new_owners_create_only_one_successor_per_failed_encoding(
    guarded_engine, failure_factory
):
    partition = "test-" + uuid4().hex
    old, gate, api = new_owner(guarded_engine, partition)
    rows = api.reserve_and_attach(requests(old), old.association.intent)
    old, _ = fail_owned(guarded_engine, old, gate, api, rows, failure_factory=failure_factory)
    candidates = [new_owner(guarded_engine, partition) for _ in range(2)]
    barrier = Barrier(2)

    def run(candidate):
        fixture, _, owner = candidate
        barrier.wait(timeout=10)
        return owner.retry_known_failed(requests(fixture), fixture.association.intent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, candidates))
    assert {r.owned_job.job_reference for r in results[0]} == {
        r.owned_job.job_reference for r in results[1]
    }
    assert sorted({r.status for r in result}.pop() for result in results) == ["BORROWED", "OWNED"]
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id.in_(r.owned_job.job_reference.job_id for r in rows),
                    JobEventRecord.event == ENCODING_RETRY_SUCCESSOR_EVENT,
                )
            )
            == 2
        )


def test_three_failures_allow_three_successors_without_resetting_any_old_job(guarded_engine):
    partition = "test-" + uuid4().hex
    fixture, gate, api = new_owner(guarded_engine, partition)
    rows = api.reserve_and_attach(requests(fixture), fixture.association.intent)
    histories = []
    for attempt in range(4):
        fixture, _ = fail_owned(guarded_engine, fixture, gate, api, rows)
        histories.extend(r.owned_job.job_reference.job_id for r in rows)
        fixture, gate, api = new_owner(guarded_engine, partition)
        if attempt == 3:
            with pytest.raises(EmbeddingEncodingReservationError, match="RETRY_LIMIT_EXCEEDED"):
                api.retry_known_failed(requests(fixture), fixture.association.intent)
        else:
            rows = api.retry_known_failed(requests(fixture), fixture.association.intent)
    with Session(guarded_engine) as session:
        assert len(histories) == len(set(histories)) == 8
        assert set(
            session.scalars(select(JobRecord.status).where(JobRecord.job_id.in_(histories)))
        ) == {"FAILED"}


def test_late_current_source_denial_rolls_back_successor_declarations_and_jobs(guarded_engine):
    partition = "test-" + uuid4().hex
    old, gate, api = new_owner(guarded_engine, partition)
    rows = api.reserve_and_attach(requests(old), old.association.intent)
    old, _ = fail_owned(guarded_engine, old, gate, api, rows)
    fixture, gate, api = new_owner(guarded_engine, partition)
    gate.denied = "mutation_current"
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        api.retry_known_failed(requests(fixture), fixture.association.intent)
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(
                    JobEventRecord.job_id.in_(r.owned_job.job_reference.job_id for r in rows),
                    JobEventRecord.event == ENCODING_RETRY_SUCCESSOR_EVENT,
                )
            )
            == 0
        )
    gate.denied = None
    assert {
        r.status for r in api.retry_known_failed(requests(fixture), fixture.association.intent)
    } == {"OWNED"}


@pytest.mark.parametrize("terminal", ("FAILED", "CANCELLED"))
def test_unproven_failure_or_cancellation_does_not_create_retry(guarded_engine, terminal):
    partition = "test-" + uuid4().hex
    old, gate, api = new_owner(guarded_engine, partition)
    rows = api.reserve_and_attach(requests(old), old.association.intent)
    old = _owned_fixture(old, rows)
    gate.fixture = old
    api.bind_launch(old.association)
    from eom_orchestrator.state_machine import JobState

    with Session(guarded_engine) as session, session.begin():
        jobs = Storage.lock_references(
            session, tuple(sorted(references(old), key=lambda r: r.job_id)), lock=True
        )
        sequences = Storage.sequences(session, jobs)
        for job in jobs:
            Storage.append(
                session,
                job,
                sequences,
                "SYNTHETIC_UNPROVEN_TERMINAL",
                {},
                target=JobState(terminal),
            )
    fixture, _, api = new_owner(guarded_engine, partition)
    assert {
        r.status for r in api.retry_known_failed(requests(fixture), fixture.association.intent)
    } == {terminal}


def test_corrupt_failure_reference_is_not_a_retry_or_cpu_fallback(guarded_engine):
    from eom_workflow.embedding_encoding_recovery import KNOWN_ENCODING_FAILURE_EVENT

    from tests.unit.inference_transfer_embedding_fixtures import seal

    partition = "test-" + uuid4().hex
    old, gate, api = new_owner(guarded_engine, partition)
    rows = api.reserve_and_attach(requests(old), old.association.intent)
    old, _ = fail_owned(guarded_engine, old, gate, api, rows)
    # Fault injection in the marker-guarded disposable DB only.
    with Session(guarded_engine) as session, session.begin():
        record = session.scalar(
            select(JobEventRecord).where(
                JobEventRecord.job_id == rows[0].owned_job.job_reference.job_id,
                JobEventRecord.event == KNOWN_ENCODING_FAILURE_EVENT,
            )
        )
        record.data = seal(
            record.data | {"native_launch_job_id": "job_" + "0" * 32}, "event_sha256"
        )
    fixture, _, api = new_owner(guarded_engine, partition)
    with pytest.raises(EmbeddingEncodingReservationError, match="FAILURE_HISTORY_INVALID"):
        api.retry_known_failed(requests(fixture), fixture.association.intent)


def test_retry_statement_count_uses_bulk_reads_and_inserts_not_per_target_queries(guarded_engine):
    counts = []
    for seeds in (("a", "b"), tuple("abcdef")):
        partition = "test-" + uuid4().hex
        old, gate, api = new_owner(guarded_engine, partition, seeds)
        rows = api.reserve_and_attach(requests(old), old.association.intent)
        fail_owned(guarded_engine, old, gate, api, rows)
        fixture, _, api = new_owner(guarded_engine, partition, seeds)
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _many, observed=statements):
            observed.append(statement)

        event.listen(guarded_engine, "before_cursor_execute", observe)
        try:
            result = api.retry_known_failed(requests(fixture), fixture.association.intent)
            assert len(result) == len(seeds) and {r.status for r in result} == {"OWNED"}
        finally:
            event.remove(guarded_engine, "before_cursor_execute", observe)
        counts.append(len(statements))
    assert counts[1] <= counts[0] + 2, counts
