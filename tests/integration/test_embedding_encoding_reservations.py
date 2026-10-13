"""Prepared marker-guarded existing-Job tests; executed only by the root disposable driver.

Synthetic owner gates below inspect canonical approved DB member metadata only.
They are NOT real IAM/session/source admission, NAS publication, binary/L2 proof,
native execution or a production port implementation. No worker credentials/users.
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from eom_identifiers import content_sha256, new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.database import build_engine, build_session_factory
from eom_orchestrator.embedding_encoding_reservation_storage import (
    BORROWED_EVENT,
    ENCODING_PROTOCOL_VERSION,
    OWNED_EVENT,
    EmbeddingEncodingReservationError,
)
from eom_orchestrator.embedding_encoding_reservations import (
    EmbeddingEncodingReservations,
    ResolvedEncodingCompletion,
)
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
)
from eom_orchestrator.native_embedding_launch_identity import (
    create_native_embedding_launch,
    require_native_embedding_launch,
)
from eom_orchestrator.repository import ensure_protocol_version
from eom_orchestrator.state_machine import JobState, record_initial_event, transition_job
from eom_workflow.local_embedding_encoding_job import (
    EmbeddingEncodingCompletedEvent,
    EmbeddingEncodingReadResult,
    LocalEmbeddingLaunchAssociation,
    LocalEmbeddingLaunchIntent,
)
from eom_workflow.schemas import LOCAL_EMBEDDING_SCHEMA_RESOURCES
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from scripts.api.testdb_guard import TestDatabaseManifest as DisposableManifest
from scripts.api.testdb_guard import validate_application_schema_metadata, validate_state_directory
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.embedding_encoding_reservation_fixtures import (
    fixture_for_jobs,
    partition_fixture,
    requests,
    reservation_fixture,
)
from tests.unit.local_embedding_admission_fixtures import NativeAdmissionFixture
from tests.unit.test_embedding_encoding_reservations import SyntheticAdmission

pytestmark = pytest.mark.integration


def _fixture(
    *seeds: str, partition: str | None = None, ordinal: int | None = None
) -> NativeAdmissionFixture:
    return partition_fixture(
        reservation_fixture(*seeds, ordinal=uuid4().int if ordinal is None else ordinal),
        partition or "test-" + uuid4().hex,
    )


def test_actual_native_coordinator_keeps_original_job_intent_and_key_within_db_bound(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a", "b")
    arguments = {
        "request": fixture.request,
        "workflow_id": "workflow_" + uuid4().hex,
        "step_run_id": "steprun_" + uuid4().hex,
        "command_id": "wfcmd_" + uuid4().hex,
        "runner_id": "synthetic-coordinator-metadata",
        "lease_generation": 1,
    }
    schema = next(row[3] for row in LOCAL_EMBEDDING_SCHEMA_RESOURCES if row[0] == "encoding-job")
    with Session(guarded_engine) as session, session.begin():
        ensure_protocol_version(session, ENCODING_PROTOCOL_VERSION, schema)
        session.flush()
        first = create_native_embedding_launch(session, **arguments)
        assert first.state == "CLAIMED"
    with Session(guarded_engine) as session, session.begin():
        second = create_native_embedding_launch(
            session,
            **(
                arguments
                | {
                    "command_id": "wfcmd_" + uuid4().hex,
                    "lease_generation": 2,
                }
            ),
        )
        assert second == first
        assert require_native_embedding_launch(session, first.intent, fixture.request) == first
        job = session.get(JobRecord, first.intent.native_launch_job_id)
        assert job is not None and len(job.idempotency_key) <= 128 and job.worker_slot_id is None
        assert "rows" not in job.request and "text" not in job.request
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id == job.job_id)
            )
            == 4
        )


def _seed_launch(engine: Engine, fixture: NativeAdmissionFixture) -> None:
    with Session(engine) as session, session.begin():
        schema = next(
            row[3] for row in LOCAL_EMBEDDING_SCHEMA_RESOURCES if row[0] == "encoding-job"
        )
        ensure_protocol_version(session, ENCODING_PROTOCOL_VERSION, schema)
        # Explicit flush: ProtocolVersion and unrelated Job have no ORM relationship ordering.
        session.flush()
        job = JobRecord(
            job_id=fixture.association.intent.native_launch_job_id,
            protocol_version=ENCODING_PROTOCOL_VERSION,
            idempotency_key="synthetic-launch:" + uuid4().hex,
            request_hash=content_sha256({"synthetic": True}),
            task_type="synthetic_native_launch_metadata",
            request={"synthetic": True},
            status=JobState.CREATED.value,
            logical_artifact_id=new_logical_artifact_id(),
            revision_id=new_revision_id(),
            worker_slot_id=None,
        )
        session.add(job)
        session.flush()
        record_initial_event(session, job)
        for state in (JobState.VALIDATED, JobState.QUEUED, JobState.CLAIMED, JobState.RUNNING):
            transition_job(session, job.job_id, state, "SYNTHETIC_NATIVE_LAUNCH")
            session.flush()


def _owned_fixture(
    fixture: NativeAdmissionFixture, result: tuple[EmbeddingEncodingReadResult, ...]
) -> NativeAdmissionFixture:
    jobs = tuple(row.owned_job for row in result if row.status == "OWNED")
    return fixture_for_jobs(fixture, jobs)


def _event_count(engine: Engine, ids: tuple[str, ...]) -> int:
    with Session(engine) as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id.in_(ids))
            )
            or 0
        )


def test_actual_overlapping_batches_one_shared_owner_original_allocations_and_replay(
    guarded_engine: Engine,
) -> None:
    partition = "test-" + uuid4().hex
    left, right = _fixture("a", "b", partition=partition), _fixture("b", "c", partition=partition)
    _seed_launch(guarded_engine, left)
    _seed_launch(guarded_engine, right)
    left_owner = EmbeddingEncodingReservations(
        build_session_factory(guarded_engine), SyntheticAdmission(left)
    )
    right_owner = EmbeddingEncodingReservations(
        build_session_factory(guarded_engine), SyntheticAdmission(right)
    )
    left_result = left_owner.reserve_and_attach(requests(left), left.association.intent)
    right_result = right_owner.reserve_and_attach(requests(right), right.association.intent)
    shared = {row.encoding.encoding_sha256 for row in requests(left)} & {
        row.encoding.encoding_sha256 for row in requests(right)
    }
    assert len(shared) == 1
    shared_key = next(iter(shared))
    a = next(
        row for row in left_result if row.owned_job.request.encoding.encoding_sha256 == shared_key
    )
    b = next(
        row for row in right_result if row.owned_job.request.encoding.encoding_sha256 == shared_key
    )
    assert a.status == "OWNED" and b.status == "BORROWED" and a.owned_job == b.owned_job
    ids = tuple({row.owned_job.job_reference.job_id for row in (*left_result, *right_result)})
    before = _event_count(guarded_engine, ids)
    assert left_owner.reserve_and_attach(requests(left), left.association.intent) == left_result
    assert right_owner.reserve_and_attach(requests(right), right.association.intent) == right_result
    assert _event_count(guarded_engine, ids) == before
    with Session(guarded_engine) as session:
        rows = tuple(session.scalars(select(JobRecord).where(JobRecord.job_id.in_(ids))))
        assert len(rows) == 3 and all(
            row.status == "CLAIMED" and row.worker_slot_id is None for row in rows
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id.in_(ids), JobEventRecord.event == OWNED_EVENT)
            )
            == 3
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobEventRecord)
                .where(JobEventRecord.job_id.in_(ids), JobEventRecord.event == BORROWED_EVENT)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.job_id.in_(ids))
            )
            == 0
        )
        assert all(
            set(row.request)
            == {"schema_version", "record_type", "purpose", "space", "encoding", "request_sha256"}
            for row in rows
        )


class SyntheticCommittedMetadataAdmission(SyntheticAdmission):
    """DB metadata gate only; finite/L2, actual bytes/IAM/source verification NOT_TESTED."""

    def resolve_completion(
        self,
        session: Session,
        association: LocalEmbeddingLaunchAssociation,
        events: tuple[EmbeddingEncodingCompletedEvent, ...],
    ) -> ResolvedEncodingCompletion:
        self.check("completion_current")
        receipt = events[0].receipt
        pointers = (receipt.result_manifest, receipt.shard_manifest, receipt.binary_member)
        row = session.execute(
            select(ArtifactRecord, ArtifactRevisionRecord, JobRecord)
            .join(
                ArtifactRevisionRecord,
                ArtifactRevisionRecord.logical_artifact_id == ArtifactRecord.logical_artifact_id,
            )
            .join(JobRecord, JobRecord.job_id == ArtifactRevisionRecord.job_id)
            .where(
                ArtifactRecord.logical_artifact_id == pointers[0].artifact_id,
                ArtifactRevisionRecord.revision_id == pointers[0].artifact_revision_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).first()
        if (
            row is None
            or not row[0].approved
            or not row[1].approved
            or row[2].status != "SUCCEEDED"
        ):
            raise EmbeddingEncodingReservationError("SYNTHETIC_COMMITTED_METADATA_REQUIRED")
        members = {member["member_path"]: member for member in row[1].manifest["members"]}
        if set(members) != {"result.json", "shard.json", "vectors.f32"} or any(
            members[p.member_path] != p.model_dump(mode="json") for p in pointers
        ):
            raise EmbeddingEncodingReservationError("SYNTHETIC_COMMITTED_METADATA_REQUIRED")
        return ResolvedEncodingCompletion(self.fixture.native_input, self.fixture.result)


def _commit_metadata(engine: Engine, fixture: NativeAdmissionFixture) -> None:
    receipt = fixture.completions[0].receipt
    pointers = (receipt.result_manifest, receipt.shard_manifest, receipt.binary_member)
    manifest = {
        "manifest_version": "synthetic-pointer-metadata-only/1.0",
        "members": [pointer.model_dump(mode="json") for pointer in pointers],
    }
    with Session(engine) as session, session.begin():
        job = JobRecord(
            job_id=new_job_id(),
            protocol_version=ENCODING_PROTOCOL_VERSION,
            idempotency_key="synthetic-output:" + uuid4().hex,
            request_hash=content_sha256(manifest),
            task_type="synthetic_shared_file_set_metadata",
            request={},
            status="SUCCEEDED",
            logical_artifact_id=pointers[0].artifact_id,
            revision_id=pointers[0].artifact_revision_id,
        )
        session.add(job)
        session.flush()
        session.add(
            ArtifactRecord(
                logical_artifact_id=job.logical_artifact_id,
                job_id=job.job_id,
                artifact_type="control_incremental_embedding",
                approved=True,
            )
        )
        session.flush()
        session.add(
            ArtifactRevisionRecord(
                revision_id=job.revision_id,
                logical_artifact_id=job.logical_artifact_id,
                job_id=job.job_id,
                content_hash=content_sha256(manifest),
                manifest_hash=content_sha256(manifest),
                content_bytes=1,
                nas_path="synthetic://not-a-real-nas-commit",
                manifest=manifest,
                result={"synthetic_metadata_only": True},
                approved=True,
            )
        )


def test_actual_completion_committed_metadata_replay_and_original_allocations(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a", "b")
    _seed_launch(guarded_engine, fixture)
    admission = SyntheticCommittedMetadataAdmission(fixture)
    owner = EmbeddingEncodingReservations(build_session_factory(guarded_engine), admission)
    reserved = owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    owned = _owned_fixture(fixture, reserved)
    partial = fixture_for_jobs(fixture, (owned.association.owned_jobs[0],))
    admission.fixture = partial
    with pytest.raises(EmbeddingEncodingReservationError, match="OWNED_SUBSET_MISMATCH"):
        owner.bind_launch(partial.association)
    admission.fixture = owned
    owner.bind_launch(owned.association)
    ids = tuple(row.owned_job.job_reference.job_id for row in reserved)
    before = _event_count(guarded_engine, ids)
    with pytest.raises(EmbeddingEncodingReservationError, match="COMMITTED_METADATA_REQUIRED"):
        owner.complete(owned.completions)
    assert _event_count(guarded_engine, ids) == before
    _commit_metadata(guarded_engine, owned)
    admission.denied = "late_mutation"
    admission.calls.clear()
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        owner.complete(owned.completions)
    assert _event_count(guarded_engine, ids) == before
    with Session(guarded_engine) as session:
        assert set(session.scalars(select(JobRecord.status).where(JobRecord.job_id.in_(ids)))) == {
            "RUNNING"
        }
    admission.denied = None
    result = owner.complete(owned.completions)
    assert all(row.status == "COMPLETED" for row in result)
    completed = _event_count(guarded_engine, ids)
    assert owner.complete(owned.completions) == result
    owner.bind_launch(owned.association)
    forged = owned.association.model_dump(mode="json")
    forged["owned_jobs"][0]["job_reference"]["allocated_artifact_revision_id"] = new_revision_id()
    forged["association_sha256"] = content_sha256(
        {key: value for key, value in forged.items() if key != "association_sha256"}
    )
    with pytest.raises(EmbeddingEncodingReservationError, match="LAUNCH_CONFLICT"):
        owner.bind_launch(LocalEmbeddingLaunchAssociation.model_validate(forged))
    assert _event_count(guarded_engine, ids) == completed
    with Session(guarded_engine) as session:
        for original in reserved:
            reference = original.owned_job.job_reference
            row = session.get(JobRecord, reference.job_id)
            assert row is not None and (row.logical_artifact_id, row.revision_id) == (
                reference.allocated_artifact_id,
                reference.allocated_artifact_revision_id,
            )
            assert (
                reference.allocated_artifact_id
                != owned.completions[0].receipt.result_manifest.artifact_id
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.job_id.in_(ids))
            )
            == 0
        )


def test_actual_late_command_refusal_rolls_back_all_new_jobs_and_events(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a", "b")
    _seed_launch(guarded_engine, fixture)
    admission = SyntheticAdmission(fixture)
    admission.denied = "mutation_current"
    owner = EmbeddingEncodingReservations(build_session_factory(guarded_engine), admission)
    with pytest.raises(EmbeddingEncodingReservationError, match="CURRENT_OWNER_DENIED"):
        owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    with Session(guarded_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(JobRecord)
                .where(
                    JobRecord.idempotency_key.in_(row.idempotency_key for row in requests(fixture))
                )
            )
            == 0
        )


def test_actual_changed_intent_and_stale_allocated_reference_fail_without_history_rewrite(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a", "b")
    _seed_launch(guarded_engine, fixture)
    owner = EmbeddingEncodingReservations(
        build_session_factory(guarded_engine), SyntheticAdmission(fixture)
    )
    reserved = owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    ids = tuple(row.owned_job.job_reference.job_id for row in reserved)
    count = _event_count(guarded_engine, ids)
    body = fixture.association.intent.model_dump(mode="json") | {"lease_generation": 2}
    changed = LocalEmbeddingLaunchIntent.model_validate(
        body
        | {
            "intent_sha256": content_sha256(
                {key: value for key, value in body.items() if key != "intent_sha256"}
            )
        }
    )
    with pytest.raises(EmbeddingEncodingReservationError, match="INTENT_CONFLICT"):
        owner.reserve_and_attach(requests(fixture), changed)
    reference = reserved[0].owned_job.job_reference.model_copy(
        update={"allocated_artifact_revision_id": new_revision_id()}
    )
    with pytest.raises(EmbeddingEncodingReservationError, match="REFERENCE_MISMATCH"):
        owner.read((reference,))
    assert _event_count(guarded_engine, ids) == count


def test_actual_terminal_reservation_read_and_attachment_never_reset_failure(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a")
    _seed_launch(guarded_engine, fixture)
    owner = EmbeddingEncodingReservations(
        build_session_factory(guarded_engine), SyntheticAdmission(fixture)
    )
    reserved = owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    reference = reserved[0].owned_job.job_reference
    with Session(guarded_engine) as session, session.begin():
        transition_job(session, reference.job_id, JobState.FAILED, "SYNTHETIC_KNOWN_FAILURE")
    assert owner.read((reference,))[0].status == "FAILED"
    assert (
        owner.reserve_and_attach(requests(fixture), fixture.association.intent)[0].status
        == "FAILED"
    )
    owned = _owned_fixture(fixture, reserved)
    with pytest.raises(EmbeddingEncodingReservationError, match="TERMINAL_OR_FOREIGN"):
        owner.bind_launch(owned.association)
    with Session(guarded_engine) as session:
        record = session.get(JobRecord, reference.job_id)
        assert record is not None and record.status == "FAILED"


def test_actual_reservation_sql_statement_count_is_batched_not_per_key(
    guarded_engine: Engine,
) -> None:
    fixture = _fixture("a", "b", "c")
    _seed_launch(guarded_engine, fixture)
    seen: list[str] = []

    def before(
        _connection: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: bool
    ) -> None:
        seen.append(statement.split(None, 1)[0])

    event.listen(guarded_engine, "before_cursor_execute", before)
    try:
        owner = EmbeddingEncodingReservations(
            build_session_factory(guarded_engine), SyntheticAdmission(fixture)
        )
        owner.reserve_and_attach(requests(fixture), fixture.association.intent)
    finally:
        event.remove(guarded_engine, "before_cursor_execute", before)
    assert seen.count("SELECT") <= 8 and seen.count("INSERT") <= 3 and len(seen) <= 16, tuple(seen)


def _guard_child(url: str, state_path: str, expected: DisposableManifest) -> Engine:
    state = validate_state_directory(Path(state_path))
    manifest = DisposableManifest.load(state / "manifest.json")
    parsed = make_url(url)
    assert (
        manifest == expected
        and parsed.database == manifest.database
        and parsed.username == manifest.owner_role
    )
    engine = build_engine(url)
    try:
        with engine.connect() as connection:
            database, actor, owner, marker = connection.execute(
                text(
                    "SELECT pg_catalog.current_database(),CURRENT_USER,owner.rolname,"
                    "pg_catalog.obj_description(namespace.oid,'pg_namespace') "
                    "FROM pg_catalog.pg_namespace namespace JOIN pg_catalog.pg_roles owner "
                    "ON owner.oid=namespace.nspowner WHERE namespace.nspname='app'"
                )
            ).one()
            assert database == manifest.database and actor == manifest.owner_role
            path, usage, create = connection.execute(
                text(
                    "SELECT current_schemas(false),"
                    "has_schema_privilege(current_user,'app','USAGE'),"
                    "has_schema_privilege(current_user,'app','CREATE')"
                )
            ).one()
            validate_application_schema_metadata(
                manifest,
                schema_owner=owner,
                schema_comment=marker,
                effective_search_path=tuple(path),
                has_usage=usage,
                has_create=create,
            )
            assert (
                connection.scalar(text("SELECT version_num FROM app.alembic_version"))
                == CURRENT_MIGRATION_REVISION
            )
        return engine
    except BaseException:
        engine.dispose()
        raise


def _race(
    url: str,
    state_path: str,
    manifest: DisposableManifest,
    seeds: tuple[str, ...],
    partition: str,
    ordinal: int,
    barrier: Any,
    queue: Any,
) -> None:
    engine: Engine | None = None
    try:
        engine = _guard_child(url, state_path, manifest)
        fixture = _fixture(*seeds, partition=partition, ordinal=ordinal)
        barrier.wait(timeout=20)
        owner = EmbeddingEncodingReservations(
            build_session_factory(engine), SyntheticAdmission(fixture)
        )
        rows = owner.reserve_and_attach(requests(fixture), fixture.association.intent)
        queue.put(
            tuple(
                (
                    row.owned_job.request.encoding.encoding_sha256,
                    row.owned_job.job_reference.job_id,
                    row.status,
                )
                for row in rows
            )
        )
    except Exception as error:
        queue.put(("ERROR", type(error).__name__))
    finally:
        if engine is not None:
            engine.dispose()


@pytest.mark.parametrize(
    "batches", [(("b",), ("b",)), (("a", "b"), ("b", "c"))], ids=["same_key", "overlap"]
)
def test_actual_independent_process_overlap_race_one_shared_reservation_owner(
    guarded_engine: Engine,
    batches: tuple[tuple[str, ...], tuple[str, ...]],
) -> None:
    partition = "test-" + uuid4().hex
    ordinals = (uuid4().int, uuid4().int)
    fixtures = (
        _fixture(*batches[0], partition=partition, ordinal=ordinals[0]),
        _fixture(*batches[1], partition=partition, ordinal=ordinals[1]),
    )
    for fixture in fixtures:
        _seed_launch(guarded_engine, fixture)
    context = multiprocessing.get_context("spawn")
    state = validate_state_directory(Path(os.environ["EOM_API_TEST_STATE"]))
    manifest = DisposableManifest.load(state / "manifest.json")
    barrier, queue = context.Barrier(2), context.Queue()
    processes = tuple(
        context.Process(
            target=_race,
            args=(
                guarded_engine.url.render_as_string(hide_password=False),
                str(state),
                manifest,
                seeds,
                partition,
                ordinal,
                barrier,
                queue,
            ),
        )
        for seeds, ordinal in zip(batches, ordinals, strict=True)
    )
    try:
        for process in processes:
            process.start()
        results = (queue.get(timeout=30), queue.get(timeout=30))
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        assert all(result and result[0] != "ERROR" for result in results), "sanitized race failure"
        shared = {row.encoding.encoding_sha256 for row in requests(fixtures[0])} & {
            row.encoding.encoding_sha256 for row in requests(fixtures[1])
        }
        shared_rows = tuple(row for result in results for row in result if row[0] in shared)
        assert len(shared_rows) == 2 and shared_rows[0][1] == shared_rows[1][1]
        assert sorted(row[2] for row in shared_rows) == ["BORROWED", "OWNED"]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        queue.close()
