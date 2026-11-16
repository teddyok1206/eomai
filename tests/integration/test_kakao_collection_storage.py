"""Accepted run/task identities and current-owner checks in guarded disposable PG only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingUpdatePolicy
from eom_catalog_contracts.kakao_collection import KakaoRoomCollectionCreate
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_capability_service import KakaoCapabilityService
from eom_catalog_service.kakao_collection_models import KakaoCollectionRunRecord as Run
from eom_catalog_service.kakao_collection_models import KakaoCollectionTaskRecord as Task
from eom_catalog_service.kakao_collection_service import KakaoCollectionService
from eom_identity_service.models import (
    ApiSessionRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_capability_storage import cap as cap
from tests.integration.test_kakao_capability_storage import confirm
from tests.integration.test_kakao_room_intake import h as h
from tests.integration.test_kakao_room_intake import intake as intake

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def collection(cap):
    accepted = confirm(cap)
    binding = KakaoArchiveService(cap.engine).get_binding(cap.actor, cap.command.source_binding_id)
    return SimpleNamespace(
        cap=cap,
        engine=cap.engine,
        actor=cap.actor,
        service=KakaoCollectionService(cap.engine, capabilities=cap.service),
        command=KakaoRoomCollectionCreate(
            source_binding_id=binding.source_binding_id,
            room_id=cap.command.room_id,
            capability_revision_id=accepted.capability.capability_revision_id,
            expected_binding_version=binding.resource_version,
            expected_policy_revision_id=binding.policy_revision.policy_revision_id,
        ),
        key="collection-" + uuid4().hex,
    )


def create(collection, command=None, key=None, actor=None):
    return collection.service.create_room_collection(
        actor or collection.actor,
        command or collection.command,
        idempotency_key=key or collection.key,
    )


def run_count(collection):
    with Session(collection.engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.source_binding_id == collection.command.source_binding_id)
        )


def test_durable_acceptance_replay_without_file_republication_or_activation(
    collection, monkeypatch
):
    result = create(collection)
    command = collection.command
    fresh = KakaoCollectionService(collection.engine, capabilities=collection.cap.service)
    state = fresh.get_status(collection.actor, command.source_binding_id, result.run_id)
    assert state.state == "QUEUED" and state.resource_version == 1
    assert state.created_at == state.updated_at == result.created_at
    monkeypatch.setattr(
        collection.cap.service, "get_capability", lambda *_: pytest.fail("no repeated file I/O")
    )
    replay = fresh.create_room_collection(collection.actor, command, idempotency_key=collection.key)
    assert replay == result.model_copy(update=dict(replayed=True))
    intent = fresh.read_background_intent(result.run_id)
    assert intent.accepted == replay and intent.capability_manifest.sha256
    assert run_count(collection) == 1
    binding = KakaoArchiveService(collection.engine).get_binding(
        collection.actor, command.source_binding_id
    )
    assert binding.state == "DRAFT" and not binding.schedule_enabled
    with Session(collection.engine) as session:
        task = session.get(Task, result.task_id)
        assert (
            task.run_id == result.run_id and task.room_id == command.room_id and task.ordinal == 1
        )
        assert all(
            column.type.__class__.__name__ not in {"JSONB", "LargeBinary"}
            for table in (Run.__table__, Task.__table__)
            for column in table.columns
        )


def test_same_key_concurrent_submission_has_one_run_and_task(collection):
    barrier = Barrier(3)

    def call(_):
        barrier.wait(timeout=15)
        return create(collection)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(call, range(3)))
    assert len({(r.run_id, r.task_id) for r in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    assert run_count(collection) == 1


def test_different_keys_cannot_queue_two_active_runs_for_the_same_binding(collection):
    barrier = Barrier(2)

    def call(key):
        barrier.wait(timeout=15)
        try:
            return create(collection, key=key)
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(call, (collection.key, collection.key + "other")))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert "KAKAO_ARCHIVE_COLLECTION_ALREADY_PENDING" in results
    assert run_count(collection) == 1


def test_same_key_modified_body_is_not_a_new_request(collection):
    create(collection)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        create(collection, collection.command.model_copy(update=dict(expected_binding_version=2)))
    assert run_count(collection) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_binding_version", 2),
        ("expected_policy_revision_id", "kakaopolicyrev_" + "0" * 32),
    ],
)
def test_stale_request_is_not_silently_upgraded(collection, field, value):
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        create(collection, collection.command.model_copy(update={field: value}))
    assert run_count(collection) == 0


def test_other_current_owner_cannot_replay_or_read_the_intent(collection):
    result = create(collection)
    other = make_actor(collection.engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        create(collection, actor=other)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        collection.service.get_status(other, collection.command.source_binding_id, result.run_id)


def test_no_row_remains_after_transaction_interruption(collection, monkeypatch):
    original = collection.service._receipt

    def stop(*_args, **_kwargs):
        raise RuntimeError("synthetic interrupt before commit")

    monkeypatch.setattr(collection.service, "_receipt", stop)
    with pytest.raises(RuntimeError, match="synthetic interrupt"):
        create(collection)
    assert run_count(collection) == 0
    monkeypatch.setattr(collection.service, "_receipt", original)
    assert not create(collection).replayed and run_count(collection) == 1


def test_expired_http_auth_does_not_become_a_fabricated_background_actor(collection):
    result = create(collection)
    with Session(collection.engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == collection.actor.session_id)
            .values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        collection.service.get_status(
            collection.actor, collection.command.source_binding_id, result.run_id
        )
    intent = collection.service.read_background_intent(result.run_id)
    assert intent.accepted.run_id == result.run_id and intent.status.state == "QUEUED"
    assert not hasattr(intent, "actor") and not hasattr(intent, "session_id")


def test_current_owner_revocation_blocks_stored_intent_preparation(collection):
    result = create(collection)
    with Session(collection.engine) as session, session.begin():
        session.execute(
            update(OperatorRecord)
            .where(OperatorRecord.operator_id == collection.actor.operator_id)
            .values(must_change_password=True)
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        collection.service.read_background_intent(result.run_id)


def test_stale_actor_permissions_do_not_override_current_role_revocation(collection):
    result = create(collection)
    with Session(collection.engine) as session, session.begin():
        session.execute(
            update(OperatorRoleAssignmentRecord)
            .where(
                OperatorRoleAssignmentRecord.operator_id == collection.actor.operator_id,
                OperatorRoleAssignmentRecord.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        collection.service.read_background_intent(result.run_id)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        create(collection)


def test_capability_for_one_room_cannot_collect_another_room(collection):
    original = collection.cap.intake.prepare(room="different-room")
    room = collection.cap.intake.service.confirm_room(
        collection.actor, original, idempotency_key="different-room-" + uuid4().hex
    ).room
    with pytest.raises(KakaoArchiveError, match="COLLECTION_CAPABILITY_MISMATCH"):
        create(collection, collection.command.model_copy(update=dict(room_id=room.room_id)))
    assert run_count(collection) == 0


def test_late_identity_change_after_evidence_read_prevents_adoption(collection, monkeypatch):
    original = collection.cap.service.get_capability

    def changed(*args):
        capability = original(*args)
        with Session(collection.engine) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == collection.actor.operator_id)
                .values(must_change_password=True)
            )
        return capability

    monkeypatch.setattr(collection.cap.service, "get_capability", changed)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        create(collection)
    assert run_count(collection) == 0


def test_policy_change_preserves_original_replay_but_blocks_new_preparation(collection):
    result = create(collection)
    service = KakaoArchiveService(collection.engine)
    binding = service.get_binding(collection.actor, collection.command.source_binding_id)
    service.command_binding(
        collection.actor,
        binding.source_binding_id,
        KakaoBindingUpdatePolicy(
            parent_policy_revision_id=binding.policy_revision.policy_revision_id,
            expected_resource_version=binding.resource_version,
            policy=binding.policy_revision.policy.model_copy(update=dict(interval_minutes=120)),
        ),
        idempotency_key="policy-change-" + uuid4().hex,
    )
    assert create(collection) == result.model_copy(update=dict(replayed=True))
    with pytest.raises(KakaoArchiveError, match="COLLECTION_POLICY_CHANGED"):
        collection.service.read_background_intent(result.run_id)


def test_new_installed_adapter_does_not_reinterpret_historical_intent(collection):
    result = create(collection)
    successor = KakaoCollectionService(
        collection.engine,
        capabilities=KakaoCapabilityService(
            collection.engine,
            artifacts=collection.cap.intake.artifacts,
            adapter_release_sha256="sha256:" + "b" * 64,
        ),
    )
    assert (
        successor.create_room_collection(
            collection.actor, collection.command, idempotency_key=collection.key
        ).run_id
        == result.run_id
    )
    with pytest.raises(KakaoArchiveError, match="COLLECTION_ADAPTER_CHANGED"):
        successor.read_background_intent(result.run_id)


@pytest.mark.parametrize(
    "target,values",
    [
        ("run", dict(policy_sha256="sha256:" + "0" * 64, resource_version=2)),
        ("run", dict(state="PAUSING", stop_target=None, resource_version=2)),
        ("task", dict(ordinal=2)),
    ],
)
def test_database_pins_task_order_and_stop_invariants(collection, target, values):
    result = create(collection)
    model, identifier = (Run, result.run_id) if target == "run" else (Task, result.task_id)
    with pytest.raises(DBAPIError), Session(collection.engine) as session, session.begin():
        column = model.run_id if target == "run" else model.task_id
        session.execute(update(model).where(column == identifier).values(**values))
    assert create(collection).run_id == result.run_id


def test_terminal_failed_identity_is_never_changed_by_replay(collection):
    result = create(collection)
    with Session(collection.engine) as session, session.begin():
        session.execute(update(Task).where(Task.task_id == result.task_id).values(state="FAILED"))
        session.execute(
            update(Run)
            .where(Run.run_id == result.run_id)
            .values(state="FAILED", resource_version=2)
        )
    assert create(collection).run_id == result.run_id
    assert (
        collection.service.get_status(
            collection.actor, collection.command.source_binding_id, result.run_id
        ).state
        == "FAILED"
    )
    with pytest.raises(KakaoArchiveError, match="COLLECTION_TERMINAL"):
        collection.service.read_background_intent(result.run_id)
    with pytest.raises(DBAPIError), Session(collection.engine) as session, session.begin():
        session.execute(
            update(Run)
            .where(Run.run_id == result.run_id)
            .values(state="COMPLETED", resource_version=3)
        )
    successor = create(collection, key=collection.key + "successor")
    assert successor.run_id != result.run_id and run_count(collection) == 2


@pytest.mark.parametrize("invalid", ["missing_task", "run_initial_state", "task_initial_state"])
def test_run_cannot_be_committed_without_its_initial_queued_task(collection, invalid):
    result = create(collection)
    with Session(collection.engine) as session, session.begin():
        old = session.get(Run, result.run_id)
        values = {column.name: getattr(old, column.name) for column in Run.__table__.columns}
        session.execute(update(Task).where(Task.task_id == result.task_id).values(state="FAILED"))
        session.execute(
            update(Run)
            .where(Run.run_id == result.run_id)
            .values(state="FAILED", resource_version=2)
        )
    new_id = "kakaorun_" + uuid4().hex
    values.update(
        run_id=new_id,
        idempotency_key="orphan-" + uuid4().hex,
        resource_version=1,
        state="COMPLETED" if invalid == "run_initial_state" else "QUEUED",
    )
    with pytest.raises(DBAPIError), Session(collection.engine) as session, session.begin():
        session.add(Run(**values))
        session.flush()
        if invalid == "task_initial_state":
            session.add(
                Task(
                    task_id="kakaotask_" + uuid4().hex,
                    run_id=new_id,
                    owner_operator_id=collection.actor.operator_id,
                    source_binding_id=collection.command.source_binding_id,
                    room_id=collection.command.room_id,
                    ordinal=1,
                    state="COMPLETED",
                )
            )
    assert run_count(collection) == 1
    assert create(collection).run_id == result.run_id


def test_pending_lookup_has_matching_partial_unique_index(collection):
    create(collection)
    with Session(collection.engine) as session, session.begin():
        session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = session.execute(
            text(
                "EXPLAIN (FORMAT JSON) SELECT run_id FROM kakao_collection_runs "
                "WHERE source_binding_id = :binding "
                "AND state NOT IN ('COMPLETED','PARTIAL','FAILED','CANCELLED')"
            ),
            dict(binding=collection.command.source_binding_id),
        ).scalar_one()
        assert "uq_kakao_collection_active_binding" in str(plan)
