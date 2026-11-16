"""Only guarded disposable PostgreSQL; no Kakao account, network, NAS or production DB."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from eom_catalog_contracts.kakao_archive_binding import (
    KakaoBindingCreate,
    KakaoBindingRetire,
    KakaoBindingUpdatePolicy,
    KakaoCollectionPolicy,
)
from eom_catalog_contracts.kakao_students import (
    KakaoStudentCreate,
    KakaoStudentRename,
    KakaoStudentRetire,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_models import (
    KakaoBindingCommandRecord,
    KakaoChannelBindingRecord,
    KakaoCollectionPolicyRevisionRecord,
)
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_student_models import (
    KakaoStudentCommandRecord,
    KakaoStudentDisplayRevisionRecord,
    KakaoStudentRecord,
)
from eom_catalog_service.kakao_student_service import KakaoStudentService
from eom_identity_service.models import (
    ApiSessionRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from eom_operator_identity.contracts import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.models import Base
from sqlalchemy import Engine, MetaData, event, func, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def make_actor(engine: Engine, *, role_key: str = "ADMIN") -> ActorContext:
    now = datetime.now(UTC)
    owner = "operator_" + uuid4().hex
    session_id = "apisession_" + uuid4().hex
    with Session(engine) as session, session.begin():
        role_id = session.scalar(select(RoleRecord.role_id).where(RoleRecord.role_key == role_key))
        assert role_id
        session.add(
            OperatorRecord(
                operator_id=owner,
                username=owner,
                normalized_username=owner,
                display_name="Synthetic Kakao owner",
                status="ACTIVE",
                must_change_password=False,
                created_by="disposable-kakao-tests",
            )
        )
        session.flush()
        session.add(
            OperatorRoleAssignmentRecord(
                operator_role_assignment_id="assignment_" + uuid4().hex,
                operator_id=owner,
                role_id=role_id,
                assigned_by="disposable-kakao-tests",
                assigned_at=now,
            )
        )
        session.add(
            ApiSessionRecord(
                api_session_id=session_id,
                operator_id=owner,
                token_family_id="tokenfamily_" + uuid4().hex,
                client_name="disposable-kakao-tests",
                authenticated_at=now,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now + timedelta(hours=1),
                idle_expires_at=now + timedelta(minutes=30),
            )
        )
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=owner,
        session_id=session_id,
        request_id="request-" + uuid4().hex,
        authentication_time=now,
        # Deliberately maximally stale: actual DB roles must decide, not this set.
        permissions=frozenset(PermissionKey),
        source=ActorSource.APPLICATION_API,
    )


@pytest.fixture
def actor(creative_engine: Engine) -> ActorContext:
    return make_actor(creative_engine)


def create(service: KakaoArchiveService, actor: ActorContext, *, key: str | None = None):
    return service.create_binding(
        actor,
        KakaoBindingCreate(display_name="검증 연결", policy=KakaoCollectionPolicy()),
        idempotency_key=key or "kakao-test-" + uuid4().hex,
    )


def test_student_names_can_repeat_and_revision_replay_is_exact(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    command = KakaoStudentCreate(display_name="동명이인")
    key = "student-create-" + uuid4().hex
    first = service.create_student(actor, command, idempotency_key=key).student
    other = service.create_student(actor, command, idempotency_key=key + "other").student
    assert first.student_id != other.student_id
    rename = KakaoStudentRename(
        parent_revision_id=first.display_revision_id,
        expected_resource_version=1,
        display_name="새 표시",
    )
    renamed = service.command_student(
        actor, first.student_id, rename, idempotency_key=key + "rename"
    ).student
    assert (
        renamed.resource_version == 2 and renamed.previous_revision_id == first.display_revision_id
    )
    assert service.create_student(actor, command, idempotency_key=key).student == first
    assert (
        service.get_student(actor, first.student_id, display_revision_id=first.display_revision_id)
        == first
    )
    assert service.get_student(actor, first.student_id) == renamed
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.create_student(
            actor, KakaoStudentCreate(display_name="다른 내용"), idempotency_key=key
        )


def test_student_concurrent_create_is_one_identity(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    command = KakaoStudentCreate(display_name="동시 학생")
    key, barrier = "student-parallel-" + uuid4().hex, Barrier(4)

    def run(_):
        barrier.wait(timeout=20)
        return service.create_student(actor, command, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({r.student.student_id for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoStudentCommandRecord)
                .where(KakaoStudentCommandRecord.idempotency_key == key)
            )
            == 1
        )


def test_student_concurrent_edit_is_one_successor(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    first = service.create_student(
        actor,
        KakaoStudentCreate(display_name="처음"),
        idempotency_key="student-create-" + uuid4().hex,
    ).student
    barrier = Barrier(2)

    def run(index):
        barrier.wait(timeout=20)
        try:
            return service.command_student(
                actor,
                first.student_id,
                KakaoStudentRename(
                    parent_revision_id=first.display_revision_id,
                    expected_resource_version=1,
                    display_name=f"이름 {index}",
                ),
                idempotency_key="student-edit-" + uuid4().hex,
            )
        except KakaoArchiveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert (
        sum(
            isinstance(result, str) and result == "KAKAO_ARCHIVE_PRECONDITION_FAILED"
            for result in results
        )
        == 1
    )
    assert service.get_student(actor, first.student_id).resource_version == 2
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoStudentDisplayRevisionRecord)
                .where(KakaoStudentDisplayRevisionRecord.student_id == first.student_id)
            )
            == 2
        )


def test_student_retirement_preserves_receipt_and_prevents_new_edit(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    first = service.create_student(
        actor,
        KakaoStudentCreate(display_name="보존"),
        idempotency_key="student-create-" + uuid4().hex,
    ).student
    key = "student-retire-" + uuid4().hex
    command = KakaoStudentRetire(
        parent_revision_id=first.display_revision_id, expected_resource_version=1
    )
    retired = service.command_student(actor, first.student_id, command, idempotency_key=key).student
    assert retired.state == "RETIRED"
    assert service.command_student(actor, first.student_id, command, idempotency_key=key).replayed
    assert (
        service.get_student(actor, first.student_id, display_revision_id=first.display_revision_id)
        == first
    )
    with pytest.raises(KakaoArchiveError, match="STUDENT_RETIRED"):
        service.command_student(
            actor,
            first.student_id,
            KakaoStudentRename(
                parent_revision_id=retired.display_revision_id,
                expected_resource_version=2,
                display_name="재활성 불가",
            ),
            idempotency_key=key + "other",
        )


def test_student_other_admin_cannot_read_or_replay(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    first = service.create_student(
        actor,
        KakaoStudentCreate(display_name="비공개"),
        idempotency_key="student-create-" + uuid4().hex,
    ).student
    other = make_actor(creative_engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_student(other, first.student_id)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_student(other, first.student_id, display_revision_id=first.display_revision_id)
    assert service.list_students(other).items == ()
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.command_student(
            other,
            first.student_id,
            KakaoStudentRetire(
                parent_revision_id=first.display_revision_id, expected_resource_version=1
            ),
            idempotency_key="student-retire-" + uuid4().hex,
        )


def test_student_revoked_session_cannot_replay(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    key, command = "student-create-" + uuid4().hex, KakaoStudentCreate(display_name="권한 검증")
    first = service.create_student(actor, command, idempotency_key=key).student
    with Session(creative_engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    for call in (
        lambda: service.create_student(actor, command, idempotency_key=key),
        lambda: service.get_student(actor, first.student_id),
    ):
        with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
            call()


def test_student_display_immutable_and_cross_parent_fk(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    values = [
        service.create_student(
            actor,
            KakaoStudentCreate(display_name="독립 학생"),
            idempotency_key="student-create-" + uuid4().hex,
        ).student
        for _ in range(2)
    ]
    with (
        pytest.raises(ProgrammingError, match="immutable Codex control-plane record"),
        Session(creative_engine) as session,
        session.begin(),
    ):
        session.execute(
            update(KakaoStudentDisplayRevisionRecord)
            .where(
                KakaoStudentDisplayRevisionRecord.display_revision_id
                == values[0].display_revision_id
            )
            .values(display_name="덮어쓰기")
        )
    with pytest.raises(IntegrityError), Session(creative_engine) as session, session.begin():
        session.execute(
            update(KakaoStudentRecord)
            .where(KakaoStudentRecord.student_id == values[0].student_id)
            .values(current_display_revision_id=values[1].display_revision_id)
        )


def test_student_keyset_is_bounded_join_without_n_plus_one(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoStudentService(creative_engine)
    students = [
        service.create_student(
            actor,
            KakaoStudentCreate(display_name="같은 이름"),
            idempotency_key="student-page-" + uuid4().hex,
        ).student
        for _ in range(5)
    ]
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "kakao_students" in statement:
            statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", observe)
    try:
        first = service.list_students(actor, limit=2)
        second = service.list_students(actor, limit=2, cursor=first.next_cursor)
        third = service.list_students(actor, limit=2, cursor=second.next_cursor)
    finally:
        event.remove(creative_engine, "before_cursor_execute", observe)
    assert [item.student_id for page in (first, second, third) for item in page.items] == sorted(
        s.student_id for s in students
    )
    assert third.next_cursor is None
    assert len(statements) == 3
    assert all(
        "JOIN kakao_student_display_revisions" in statement
        and "LIMIT" in statement
        and "OFFSET" not in statement
        for statement in statements
    )


def test_create_read_retire_and_original_replay(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoArchiveService(creative_engine)
    key = "kakao-create-" + uuid4().hex
    first = create(service, actor, key=key)
    assert first.binding.state == "DRAFT" and first.replayed is False
    binding = first.binding
    assert service.get_binding(actor, binding.source_binding_id) == binding
    retirement = KakaoBindingRetire(
        parent_policy_revision_id=binding.policy_revision.policy_revision_id,
        expected_resource_version=binding.resource_version,
    )
    retire_key = "kakao-retire-" + uuid4().hex
    retired = service.command_binding(
        actor, binding.source_binding_id, retirement, idempotency_key=retire_key
    )
    assert retired.binding.state == "RETIRED" and retired.binding.resource_version == 2
    assert service.command_binding(
        actor, binding.source_binding_id, retirement, idempotency_key=retire_key
    ).replayed
    replay = create(service, actor, key=key)
    assert replay.replayed and replay.binding == first.binding
    assert service.get_binding(actor, binding.source_binding_id).state == "RETIRED"
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        service.command_binding(
            actor,
            binding.source_binding_id,
            KakaoBindingRetire(
                parent_policy_revision_id=binding.policy_revision.policy_revision_id,
                expected_resource_version=2,
            ),
            idempotency_key="kakao-repeat-" + uuid4().hex,
        )


def test_policy_successor_and_cas_are_atomic(creative_engine: Engine, actor: ActorContext) -> None:
    service = KakaoArchiveService(creative_engine)
    original = create(service, actor).binding
    command = KakaoBindingUpdatePolicy(
        parent_policy_revision_id=original.policy_revision.policy_revision_id,
        expected_resource_version=1,
        policy=KakaoCollectionPolicy(interval_minutes=120),
    )
    key = "kakao-policy-" + uuid4().hex
    changed = service.command_binding(
        actor, original.source_binding_id, command, idempotency_key=key
    )
    assert (
        changed.binding.policy_revision.previous_revision_id
        == original.policy_revision.policy_revision_id
    )
    assert changed.binding.policy_revision.revision_number == 2
    assert changed.binding.policy_revision.sha256 != original.policy_revision.sha256
    assert changed.binding.schedule_enabled is False
    assert (
        service.command_binding(
            actor, original.source_binding_id, command, idempotency_key=key
        ).binding
        == changed.binding
    )
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        service.command_binding(
            actor, original.source_binding_id, command, idempotency_key=key + "stale"
        )
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.command_binding(
            actor,
            original.source_binding_id,
            command.model_copy(
                update={
                    "policy": KakaoCollectionPolicy(interval_minutes=180),
                }
            ),
            idempotency_key=key,
        )
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoCollectionPolicyRevisionRecord)
                .where(
                    KakaoCollectionPolicyRevisionRecord.source_binding_id
                    == original.source_binding_id
                )
            )
            == 2
        )


def test_failed_receipt_write_rolls_back_successor_and_current(
    creative_engine: Engine, actor: ActorContext, monkeypatch
) -> None:
    service = KakaoArchiveService(creative_engine)
    original = create(service, actor).binding

    def fail_record(*args, **kwargs):
        raise RuntimeError("synthetic interrupted transaction")

    monkeypatch.setattr(service, "_record", fail_record)
    with pytest.raises(RuntimeError, match="synthetic interrupted"):
        service.command_binding(
            actor,
            original.source_binding_id,
            KakaoBindingUpdatePolicy(
                parent_policy_revision_id=original.policy_revision.policy_revision_id,
                expected_resource_version=1,
                policy=KakaoCollectionPolicy(interval_minutes=120),
            ),
            idempotency_key="kakao-rollback-" + uuid4().hex,
        )
    assert service.get_binding(actor, original.source_binding_id) == original
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoCollectionPolicyRevisionRecord)
                .where(
                    KakaoCollectionPolicyRevisionRecord.source_binding_id
                    == original.source_binding_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoBindingCommandRecord)
                .where(
                    KakaoBindingCommandRecord.source_binding_id == original.source_binding_id,
                )
            )
            == 1
        )


def test_concurrent_creation_replays_one_binding(
    creative_engine: Engine, actor: ActorContext
) -> None:
    barrier = Barrier(4)
    service = KakaoArchiveService(creative_engine)
    key = "kakao-concurrent-" + uuid4().hex

    def run(_):
        barrier.wait(timeout=10)
        return create(service, actor, key=key)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({result.binding.source_binding_id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoBindingCommandRecord)
                .where(
                    KakaoBindingCommandRecord.owner_operator_id == actor.operator_id,
                    KakaoBindingCommandRecord.idempotency_key == key,
                )
            )
            == 1
        )


def test_concurrent_distinct_commands_have_one_cas_winner(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoArchiveService(creative_engine)
    binding = create(service, actor).binding
    barrier = Barrier(2)

    def run(minutes):
        barrier.wait(timeout=10)
        try:
            return service.command_binding(
                actor,
                binding.source_binding_id,
                KakaoBindingUpdatePolicy(
                    parent_policy_revision_id=binding.policy_revision.policy_revision_id,
                    expected_resource_version=1,
                    policy=KakaoCollectionPolicy(interval_minutes=minutes),
                ),
                idempotency_key="kakao-cas-" + uuid4().hex,
            ).binding.resource_version
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (120, 180)))
    assert results.count(2) == 1
    assert results.count("KAKAO_ARCHIVE_PRECONDITION_FAILED") == 1


def test_owner_acl_current_role_and_session_are_required(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoArchiveService(creative_engine)
    binding = create(service, actor).binding
    other_admin = make_actor(creative_engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_binding(other_admin, binding.source_binding_id)
    assert not service.list_bindings(other_admin).items
    viewer = make_actor(creative_engine, role_key="VIEWER")
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        create(service, viewer)
    with Session(creative_engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(
                ApiSessionRecord.api_session_id == actor.session_id,
            )
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.get_binding(actor, binding.source_binding_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "DISABLED"),
        ("must_change_password", True),
        ("deleted_at", datetime(2026, 11, 16, tzinfo=UTC)),
    ],
)
def test_current_operator_state_blocks_stale_permission_snapshot(
    creative_engine: Engine, actor: ActorContext, field: str, value: object
) -> None:
    service = KakaoArchiveService(creative_engine)
    created = create(service, actor)
    with Session(creative_engine) as session, session.begin():
        session.execute(
            update(OperatorRecord)
            .where(OperatorRecord.operator_id == actor.operator_id)
            .values({field: value})
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.get_binding(actor, created.binding.source_binding_id)


def test_role_revocation_blocks_replay(creative_engine: Engine, actor: ActorContext) -> None:
    service = KakaoArchiveService(creative_engine)
    key = "kakao-role-" + uuid4().hex
    create(service, actor, key=key)
    with Session(creative_engine) as session, session.begin():
        session.execute(
            update(OperatorRoleAssignmentRecord)
            .where(
                OperatorRoleAssignmentRecord.operator_id == actor.operator_id,
            )
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        create(service, actor, key=key)


def test_list_uses_bounded_owner_keyset_and_one_policy_join(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoArchiveService(creative_engine)
    expected = sorted(create(service, actor).binding.source_binding_id for _ in range(4))
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "kakao_channel_bindings" in statement:
            statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        page1 = service.list_bindings(actor, limit=2)
        page2 = service.list_bindings(actor, limit=2, cursor=page1.next_cursor)
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert [item.source_binding_id for item in (*page1.items, *page2.items)] == expected
    assert page2.next_cursor is None
    assert len(statements) == 2
    assert all(
        "JOIN kakao_collection_policy_revisions" in statement and "LIMIT" in statement
        for statement in statements
    )


def test_policy_and_receipt_are_immutable_and_cross_binding_pointer_fails(
    creative_engine: Engine, actor: ActorContext
) -> None:
    service = KakaoArchiveService(creative_engine)
    first, second = create(service, actor).binding, create(service, actor).binding
    with pytest.raises(IntegrityError), Session(creative_engine) as session, session.begin():
        session.execute(
            update(KakaoChannelBindingRecord)
            .where(
                KakaoChannelBindingRecord.source_binding_id == first.source_binding_id,
            )
            .values(current_policy_revision_id=second.policy_revision.policy_revision_id)
        )
    for statement in (
        update(KakaoCollectionPolicyRevisionRecord)
        .where(
            KakaoCollectionPolicyRevisionRecord.policy_revision_id
            == first.policy_revision.policy_revision_id,
        )
        .values(interval_minutes=120),
        update(KakaoBindingCommandRecord)
        .where(
            KakaoBindingCommandRecord.source_binding_id == first.source_binding_id,
        )
        .values(result_version=10),
    ):
        with (
            pytest.raises(ProgrammingError, match="immutable Codex control-plane record"),
            Session(creative_engine) as session,
            session.begin(),
        ):
            session.execute(statement)
    assert service.get_binding(actor, first.source_binding_id) == first


def test_bootstrap_migration_and_metadata_match(creative_engine: Engine) -> None:
    # Compare this owner and its FK closure, independent of which other
    # application owners happened to be imported by test collection.
    from eom_catalog_service import (
        kakao_capability_models,
        kakao_collection_attempt_models,
        kakao_collection_browser_models,
        kakao_collection_models,
        kakao_manual_models,
        kakao_room_intake_models,
        kakao_room_models,
        kakao_source_models,
    )

    for module in (
        kakao_capability_models,
        kakao_collection_attempt_models,
        kakao_collection_browser_models,
        kakao_collection_models,
        kakao_manual_models,
        kakao_room_intake_models,
        kakao_room_models,
        kakao_source_models,
    ):
        assert module.Base.metadata is Base.metadata
    metadata = MetaData()
    pending = [table for table in Base.metadata.tables.values() if table.name.startswith("kakao_")]
    while pending:
        table = pending.pop()
        if table.key in metadata.tables:
            continue
        table.to_metadata(metadata)
        pending.extend(foreign_key.column.table for foreign_key in table.foreign_keys)

    def include_object(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name.startswith("kakao_")
        return True

    with creative_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include_object})
        assert compare_metadata(context, metadata) == []
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == CURRENT_MIGRATION_REVISION
        )
        rows = connection.execute(
            select(RoleRecord.role_key, PermissionRecord.permission_key)
            .join(
                RolePermissionRecord,
                RolePermissionRecord.role_id == RoleRecord.role_id,
            )
            .join(
                PermissionRecord,
                PermissionRecord.permission_id == RolePermissionRecord.permission_id,
            )
            .where(
                PermissionRecord.permission_key.like("kakao_archive:%"),
            )
        ).all()
        assert len(rows) == 5 and {row[0] for row in rows} == {"ADMIN"}
