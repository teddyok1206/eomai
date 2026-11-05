"""Guarded disposable PostgreSQL only; no model, NAS, source rights or live claims.

Synthetic Artifact/actor rows prove pointer relationships and restart fencing,
not publication or document eligibility. History is retained until guarded DB
cleanup; fixture teardown only closes its own non-running synthetic work.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_service.material_learning_models import (
    LearningMaterialRecord,
    LearningMaterialRevisionRecord,
    MaterialLearningEventRecord,
    MaterialLearningRunRecord,
    MaterialLearningTaskRecord,
)
from eom_catalog_service.material_learning_store import (
    MaterialLearningStorageError,
    MaterialSubmissionPins,
    add_material_task,
    claim_next_material_run,
    create_material_learning,
    lock_material_run,
    material_submission_identity,
    next_material_task,
    release_material_claim,
    transition_material_run,
    transition_material_task,
)
from eom_identity_service.models import OperatorRecord
from eom_workflow.material_learning_state import (
    TASK_TRANSITIONS,
    MaterialLearningState,
    MaterialTaskState,
)
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.item_registry.test_registry_persistence import _artifact

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def pins(creative_engine: Engine):
    actor = "operator_" + uuid4().hex
    with Session(creative_engine) as session, session.begin():
        session.add(
            OperatorRecord(
                operator_id=actor,
                username=actor,
                normalized_username=actor,
                display_name="Synthetic material owner",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_by="disposable-material-test",
            )
        )
        artifact = _artifact(session)
        pointer = MaterialArtifactMember(
            artifact_id=artifact.logical_artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="material/intake.json",
            schema_ref="eom://schemas/material-learning/intake/1.0",
            media_type="application/json",
            sha256="sha256:" + "2" * 64,
            bytes=1,
        )
    value = MaterialSubmissionPins(
        actor,
        "material-create-" + uuid4().hex,
        "혼합 자료",
        "WORKBOOK",
        "sha256:" + "3" * 64,
        pointer,
    )
    yield value
    # Close only these synthetic tasks, without deleting or reinterpreting a
    # terminal record. No child Workflow/model was ever submitted by this suite.
    with Session(creative_engine) as session, session.begin():
        for run in session.scalars(
            select(MaterialLearningRunRecord)
            .where(MaterialLearningRunRecord.created_by == actor)
            .with_for_update()
        ):
            for task in session.scalars(
                select(MaterialLearningTaskRecord).where(
                    MaterialLearningTaskRecord.run_id == run.run_id
                )
            ):
                state = MaterialTaskState(task.state)
                if TASK_TRANSITIONS[state]:
                    target = (
                        MaterialTaskState.CANCELLED
                        if MaterialTaskState.CANCELLED in TASK_TRANSITIONS[state]
                        else MaterialTaskState.FAILED
                    )
                    if state == MaterialTaskState.GRAPH_READY:
                        target = MaterialTaskState.COMPLETED
                    transition_material_task(session, run, task, target, now=datetime.now(UTC))
            if run.state not in {"COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "CANCELLED"}:
                transition_material_run(
                    session, run, MaterialLearningState.CANCELLED, now=datetime.now(UTC)
                )


def create(engine, pins):
    with Session(engine) as session, session.begin():
        run, created = create_material_learning(session, pins)
        return run.run_id, created


def ready_task(session, run, key="first"):
    transition_material_run(session, run, MaterialLearningState.PREPARING, now=datetime.now(UTC))
    transition_material_run(session, run, MaterialLearningState.DISCOVERING, now=datetime.now(UTC))
    task, _ = add_material_task(session, run, task_kind="DISCOVER", unit_key=key, ordinal=1)
    assert transition_material_task(
        session, run, task, MaterialTaskState.PREPARING, now=datetime.now(UTC)
    )
    assert transition_material_task(
        session, run, task, MaterialTaskState.READY, now=datetime.now(UTC)
    )
    return task


def test_exact_replay_and_different_payload_same_key_are_distinct(creative_engine, pins):
    first = create(creative_engine, pins)
    assert first[1]
    assert create(creative_engine, pins) == (first[0], False)
    with pytest.raises(MaterialLearningStorageError, match="IDEMPOTENCY_CONFLICT"):
        create(creative_engine, replace(pins, title="다른 자료"))
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(LearningMaterialRevisionRecord)
                .where(LearningMaterialRevisionRecord.created_by == pins.operator_id)
            )
            == 1
        )


def test_concurrent_same_command_creates_one_material_and_first_run(creative_engine, pins):
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        return create(creative_engine, pins)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: submit(), range(2)))
    assert len({value[0] for value in results}) == 1
    assert sum(value[1] for value in results) == 1


def test_interrupted_creation_rolls_back_and_original_key_resumes(creative_engine, pins):
    identity = material_submission_identity(pins.operator_id, pins.idempotency_key)
    with (
        pytest.raises(RuntimeError, match="synthetic interruption"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        create_material_learning(session, pins)
        session.flush()
        raise RuntimeError("synthetic interruption")
    with Session(creative_engine) as session:
        assert session.get(LearningMaterialRecord, identity.material_id) is None
    assert create(creative_engine, pins) == (identity.first_run_id, True)


def test_expired_coordinator_lease_does_not_reopen_model_execution(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        assert transition_material_task(
            session, run, task, MaterialTaskState.RUNNING, now=datetime.now(UTC)
        )
        task_id = task.task_id
    now = datetime.now(UTC)
    with Session(creative_engine) as session, session.begin():
        first = claim_next_material_run(
            session, lease_owner="old-coordinator", now=now, lease_duration=timedelta(seconds=30)
        )
        assert first is not None and first.run_id == run_id
    with Session(creative_engine) as session, session.begin():
        second = claim_next_material_run(
            session,
            lease_owner="new-coordinator",
            now=now + timedelta(seconds=31),
            lease_duration=timedelta(seconds=30),
        )
        assert (
            second is not None
            and second.run_id == run_id
            and second.lease_token != first.lease_token
        )
        with pytest.raises(MaterialLearningStorageError, match="LEASE_STALE"):
            lock_material_run(session, first, now=now + timedelta(seconds=31))
        run = lock_material_run(session, second, now=now + timedelta(seconds=31))
        task = next_material_task(session, run_id)
        assert task.task_id == task_id and task.state == "RUNNING"
        with pytest.raises(ValueError, match="TRANSITION_INVALID"):
            transition_material_task(
                session, run, task, MaterialTaskState.RUNNING, now=now + timedelta(seconds=31)
            )
        release_material_claim(session, second, now=now + timedelta(seconds=31))


def test_one_ai_task_across_two_books_even_for_two_coordinators(creative_engine, pins):
    run_ids = (
        create(creative_engine, pins)[0],
        create(creative_engine, replace(pins, idempotency_key="second-material-" + uuid4().hex))[0],
    )
    tasks = []
    for run_id in run_ids:
        with Session(creative_engine) as session, session.begin():
            run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
            tasks.append(ready_task(session, run).task_id)
    barrier = Barrier(2)

    def start(index):
        barrier.wait(timeout=10)
        with Session(creative_engine) as session, session.begin():
            run = session.get(MaterialLearningRunRecord, run_ids[index], with_for_update=True)
            task = session.get(MaterialLearningTaskRecord, tasks[index])
            return transition_material_task(
                session, run, task, MaterialTaskState.RUNNING, now=datetime.now(UTC)
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(start, range(2)))
    assert sorted(results) == [False, True]
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MaterialLearningTaskRecord)
                .where(MaterialLearningTaskRecord.state.in_({"RUNNING", "ANALYZING"}))
            )
            == 1
        )


def test_parent_locked_events_are_ordered_and_task_replay_adds_nothing(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        expected = run.next_event_sequence
        replayed, created = add_material_task(
            session, run, task_kind="DISCOVER", unit_key="first", ordinal=1
        )
        assert not created and replayed.task_id == task.task_id
        assert run.next_event_sequence == expected
    with Session(creative_engine) as session:
        sequences = tuple(
            session.scalars(
                select(MaterialLearningEventRecord.sequence)
                .where(MaterialLearningEventRecord.run_id == run_id)
                .order_by(MaterialLearningEventRecord.sequence)
            )
        )
        assert sequences == tuple(range(1, expected))


def test_pausing_stops_new_work_but_keeps_running_child_reconcilable(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        transition_material_task(
            session, run, task, MaterialTaskState.RUNNING, now=datetime.now(UTC)
        )
        transition_material_run(session, run, MaterialLearningState.PAUSED, now=datetime.now(UTC))
    with Session(creative_engine) as session, session.begin():
        claim = claim_next_material_run(
            session,
            lease_owner="paused-child-reconcile",
            now=datetime.now(UTC),
            lease_duration=timedelta(seconds=30),
        )
        assert claim is not None and claim.run_id == run_id
        run = lock_material_run(session, claim, now=datetime.now(UTC))
        assert run.state == "PAUSED"
        assert next_material_task(session, run_id).state == "RUNNING"
        release_material_claim(session, claim, now=datetime.now(UTC))


def test_live_child_cannot_be_hidden_by_terminal_parent_state(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        transition_material_task(
            session, run, task, MaterialTaskState.RUNNING, now=datetime.now(UTC)
        )
        with pytest.raises(
            MaterialLearningStorageError, match="ACTIVE_CHILD_REQUIRES_RECONCILIATION"
        ):
            transition_material_run(
                session, run, MaterialLearningState.CANCELLED, now=datetime.now(UTC)
            )
        assert run.state == "DISCOVERING" and task.state == "RUNNING"


def test_revision_and_failed_task_history_are_db_immutable(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        transition_material_task(
            session,
            run,
            task,
            MaterialTaskState.FAILED,
            now=datetime.now(UTC),
            error_code="SYNTHETIC_FAILURE",
        )
        task_id = task.task_id
    with Session(creative_engine) as session, session.begin():
        task = session.get(MaterialLearningTaskRecord, task_id)
        with pytest.raises(IntegrityError, match="TASK_HISTORY_IMMUTABLE"), session.begin_nested():
            task.state = "READY"
            session.flush()
        revision = session.get(
            LearningMaterialRevisionRecord,
            material_submission_identity(
                pins.operator_id, pins.idempotency_key
            ).material_revision_id,
        )
        with pytest.raises(IntegrityError, match="HISTORY_IMMUTABLE"), session.begin_nested():
            revision.title = "overwrite"
            session.flush()


def test_partial_member_pointer_cannot_pass_sql_null_semantics(creative_engine, pins):
    run_id, _ = create(creative_engine, pins)
    with Session(creative_engine) as session, session.begin():
        run = session.get(MaterialLearningRunRecord, run_id, with_for_update=True)
        task = ready_task(session, run)
        with (
            pytest.raises(IntegrityError, match="ck_material_learning_task_input"),
            session.begin_nested(),
        ):
            task.input_artifact_id = pins.manifest.artifact_id
            task.input_artifact_revision_id = pins.manifest.artifact_revision_id
            task.input_sha256 = None
            session.flush()


def test_material_storage_has_no_document_or_worker_binary_payload_columns():
    for model in (
        LearningMaterialRecord,
        LearningMaterialRevisionRecord,
        MaterialLearningRunRecord,
        MaterialLearningTaskRecord,
        MaterialLearningEventRecord,
    ):
        assert not any(
            column.type.__class__.__name__ in {"JSON", "JSONB", "LargeBinary", "BYTEA", "Text"}
            for column in model.__table__.columns
        )
