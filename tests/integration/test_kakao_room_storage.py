"""Guarded disposable PostgreSQL only; synthetic authority, no private source/NAS/network."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_rooms import (
    ROOM_OBSERVATION_REF,
    KakaoRoomMap,
    KakaoRoomObservation,
    KakaoRoomUnmap,
)
from eom_catalog_contracts.kakao_students import (
    KakaoStudentCreate,
    KakaoStudentRename,
    KakaoStudentRetire,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_room_models import (
    KakaoRoomAdmissionRecord,
    KakaoRoomMappingRevisionRecord,
    KakaoRoomRecord,
)
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_catalog_service.kakao_student_models import KakaoStudentRecord
from eom_catalog_service.kakao_student_service import KakaoStudentService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import ApiSessionRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import Engine, event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_kakao_archive_storage import create, make_actor

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def store_evidence(engine: Engine, raw: bytes, *, kind: str, member: str, schema: str):
    """Test fixture registered metadata only, never a fake production source authority."""
    artifact, revision, job = "artifact_" + uuid4().hex, "rev_" + uuid4().hex, "job_" + uuid4().hex
    digest = sha256_bytes(raw)
    manifest = dict(
        manifest_version="1.0",
        job_id=job,
        logical_artifact_id=artifact,
        revision_id=revision,
        artifact_type=kind,
        primary_file=member,
        content_hash=digest,
        content_bytes=len(raw),
        files=[
            dict(
                file_name=member,
                sha256=digest,
                bytes=len(raw),
                schema_ref=schema,
                media_type="application/json",
            )
        ],
    )
    with Session(engine) as session, session.begin():
        ensure_protocol_version(session, "kakao-test/1", "sha256:" + "f" * 64)
        session.flush()
        session.add(
            JobRecord(
                job_id=job,
                protocol_version="kakao-test/1",
                idempotency_key="kakao-evidence-" + uuid4().hex,
                request_hash=digest,
                task_type="catalog",
                request={},
                status="SUCCEEDED",
                logical_artifact_id=artifact,
                revision_id=revision,
            )
        )
        session.flush()
        session.add(
            ArtifactRecord(
                logical_artifact_id=artifact, job_id=job, artifact_type=kind, approved=True
            )
        )
        session.flush()
        session.add(
            ArtifactRevisionRecord(
                revision_id=revision,
                logical_artifact_id=artifact,
                job_id=job,
                content_hash=digest,
                content_bytes=len(raw),
                manifest_hash=sha256_bytes(canonical_json_bytes(manifest)),
                manifest=manifest,
                nas_path="/disposable/kakao-fixture/" + artifact,
                result={},
                approved=True,
            )
        )
    return ArtifactMemberPointer(
        artifact_id=artifact,
        artifact_revision_id=revision,
        schema_ref=schema,
        media_type="application/json",
        member_path=member,
        sha256=digest,
    )


def observed(engine: Engine, binding_id: str, **changes):
    source = store_evidence(
        engine,
        b'{"synthetic_source":true}',
        kind="test-kakao-source",
        member="source.json",
        schema="eom://schemas/test-kakao-source/1.0",
    )
    value = dict(
        source_binding_id=binding_id,
        proposed_room_id="kakaoroom_" + uuid4().hex,
        identity_level="MANUAL_CONFIRMED",
        source_identity_sha256=sha256_bytes(uuid4().bytes),
        display_name="동명이인 대화방",
        observed_at=datetime.now(UTC),
        source_evidence=source,
    )
    value.update(changes)
    observation = KakaoRoomObservation.model_validate(value)
    raw = canonical_json_bytes(observation.model_dump(mode="json"))
    evidence = store_evidence(
        engine,
        raw,
        kind="kakao-room-identity",
        member="observation.json",
        schema=ROOM_OBSERVATION_REF,
    )

    def authority(_session, _actor, proposed, pointer):
        # This fake replaces the installed owner adapter, not an untrusted worker callback.
        assert proposed == observation and pointer == evidence
        assert sha256_bytes(raw) == pointer.sha256

    return observation, evidence, authority


@pytest.fixture
def room_context(creative_engine):
    actor = make_actor(creative_engine)
    binding = create(KakaoArchiveService(creative_engine), actor).binding
    service = KakaoRoomService(creative_engine)
    return actor, binding, service


def admit(engine, context, *, key=None, values=None):
    actor, binding, service = context
    observation, evidence, authority = values or observed(engine, binding.source_binding_id)
    result = service.admit_room(
        actor,
        observation,
        evidence=evidence,
        idempotency_key=key or "admit-room-" + uuid4().hex,
        authorize_observation=authority,
    )
    return result, (observation, evidence, authority)


def student_and_map(engine, actor, room):
    student = (
        KakaoStudentService(engine)
        .create_student(
            actor,
            KakaoStudentCreate(display_name="학생 표시"),
            idempotency_key="student-" + uuid4().hex,
        )
        .student
    )
    command = KakaoRoomMap(
        parent_revision_id=room.mapping.mapping_revision_id,
        expected_resource_version=room.resource_version,
        student_id=student.student_id,
        student_display_revision_id=student.display_revision_id,
        reason="원본 대화방과 학생 확인",
    )
    return student, command


def test_room_server_identity_names_are_not_dedup_and_admission_replays_exact(
    creative_engine, room_context
):
    actor, binding, service = room_context
    key = "admit-room-" + uuid4().hex
    first, values = admit(creative_engine, room_context, key=key)
    second, _ = admit(creative_engine, room_context)
    assert first.room.display_name == second.room.display_name
    assert first.room.room_id != second.room.room_id != values[0].proposed_room_id
    assert first.room.room_id != values[0].proposed_room_id
    assert first.room.mapping.state == "UNMAPPED"
    assert admit(creative_engine, room_context, key=key, values=values)[0].replayed
    other_key, _ = admit(creative_engine, room_context, values=values)
    assert other_key.room.room_id == first.room.room_id
    student, command = student_and_map(creative_engine, actor, first.room)
    mapped = service.command_room(
        actor,
        binding.source_binding_id,
        first.room.room_id,
        command,
        idempotency_key="map-room-" + uuid4().hex,
    ).room
    assert mapped.mapping.student_id == student.student_id
    assert admit(creative_engine, room_context, key=key, values=values)[0].room == first.room
    assert service.get_room(actor, binding.source_binding_id, first.room.room_id) == mapped
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        admit(creative_engine, room_context, key=key)


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_admission_one_room_and_one_initial_mapping(
    creative_engine, room_context, same_key
):
    values = observed(creative_engine, room_context[1].source_binding_id)
    barrier, key = Barrier(4), "admit-parallel-" + uuid4().hex

    def run(i):
        barrier.wait(timeout=20)
        return admit(
            creative_engine, room_context, values=values, key=key if same_key else key + str(i)
        )[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    ids = {r.room.room_id for r in results}
    assert len(ids) == 1
    assert sum(not r.replayed for r in results) == (1 if same_key else 4)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoRoomMappingRevisionRecord)
                .where(KakaoRoomMappingRevisionRecord.room_id == next(iter(ids)))
            )
            == 1
        )


def test_map_unmap_keeps_exact_history_after_student_rename(creative_engine, room_context):
    actor, binding, service = room_context
    room = admit(creative_engine, room_context)[0].room
    student, command = student_and_map(creative_engine, actor, room)
    key = "map-replay-" + uuid4().hex
    mapped = service.command_room(
        actor, binding.source_binding_id, room.room_id, command, idempotency_key=key
    ).room
    KakaoStudentService(creative_engine).command_student(
        actor,
        student.student_id,
        KakaoStudentRename(
            parent_revision_id=student.display_revision_id,
            expected_resource_version=1,
            display_name="변경된 표시",
        ),
        idempotency_key="rename-" + uuid4().hex,
    )
    assert service.get_room(actor, binding.source_binding_id, room.room_id) == mapped
    unmap = KakaoRoomUnmap(
        parent_revision_id=mapped.mapping.mapping_revision_id,
        expected_resource_version=2,
        reason="잘못 연결한 학생 해제",
    )
    unmapped = service.command_room(
        actor, binding.source_binding_id, room.room_id, unmap, idempotency_key=key + "unmap"
    ).room
    assert unmapped.resource_version == 3 and unmapped.mapping.student_id is None
    assert (
        service.command_room(
            actor, binding.source_binding_id, room.room_id, command, idempotency_key=key
        ).room
        == mapped
    )
    assert (
        service.get_room(
            actor,
            binding.source_binding_id,
            room.room_id,
            mapping_revision_id=mapped.mapping.mapping_revision_id,
        )
        == mapped
    )
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.command_room(
            actor,
            binding.source_binding_id,
            room.room_id,
            command.model_copy(update={"reason": "다른 의도"}),
            idempotency_key=key,
        )
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        service.command_room(
            actor, binding.source_binding_id, room.room_id, command, idempotency_key=key + "stale"
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_mapping_single_cas_successor(creative_engine, room_context, same_key):
    actor, binding, service = room_context
    room = admit(creative_engine, room_context)[0].room
    _, command = student_and_map(creative_engine, actor, room)
    barrier, key = Barrier(4), "mapping-parallel-" + uuid4().hex

    def run(i):
        barrier.wait(timeout=20)
        try:
            return service.command_room(
                actor,
                binding.source_binding_id,
                room.room_id,
                command,
                idempotency_key=key if same_key else key + str(i),
            )
        except KakaoArchiveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    if same_key:
        assert len({r.room.mapping.mapping_revision_id for r in results}) == 1
        assert sum(not r.replayed for r in results) == 1
    else:
        assert results.count("KAKAO_ARCHIVE_PRECONDITION_FAILED") == 3
    assert service.get_room(actor, binding.source_binding_id, room.room_id).resource_version == 2


@pytest.mark.parametrize("action", ["rename", "retire"])
def test_mapping_rejects_stale_or_retired_student(creative_engine, room_context, action):
    actor, binding, service = room_context
    room = admit(creative_engine, room_context)[0].room
    student, command = student_and_map(creative_engine, actor, room)
    update_student = (
        KakaoStudentRename(
            parent_revision_id=student.display_revision_id,
            expected_resource_version=1,
            display_name="변경",
        )
        if action == "rename"
        else KakaoStudentRetire(
            parent_revision_id=student.display_revision_id, expected_resource_version=1
        )
    )
    KakaoStudentService(creative_engine).command_student(
        actor, student.student_id, update_student, idempotency_key="change-student-" + uuid4().hex
    )
    with pytest.raises(
        KakaoArchiveError, match="STUDENT_STALE" if action == "rename" else "STUDENT_RETIRED"
    ):
        service.command_room(
            actor,
            binding.source_binding_id,
            room.room_id,
            command,
            idempotency_key="mapping-reject-" + uuid4().hex,
        )
    assert service.get_room(actor, binding.source_binding_id, room.room_id).resource_version == 1


def test_student_rename_race_uses_current_display_after_lock(creative_engine, room_context):
    actor, binding, service = room_context
    room = admit(creative_engine, room_context)[0].room
    student, command = student_and_map(creative_engine, actor, room)
    started = Event()

    def mapping():
        started.set()
        return service.command_room(
            actor,
            binding.source_binding_id,
            room.room_id,
            command,
            idempotency_key="mapping-race-" + uuid4().hex,
        )

    # Hold the real student row first; update through the official service on the same connection.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with creative_engine.connect() as connection, connection.begin():
            connection.execute(
                select(KakaoStudentRecord.student_id)
                .where(KakaoStudentRecord.student_id == student.student_id)
                .with_for_update()
            )
            future = pool.submit(mapping)
            assert started.wait(timeout=10)
            rename_service = KakaoStudentService(creative_engine)
            rename_service._sessions = sessionmaker(bind=connection, expire_on_commit=False)
            rename_service.command_student(
                actor,
                student.student_id,
                KakaoStudentRename(
                    parent_revision_id=student.display_revision_id,
                    expected_resource_version=1,
                    display_name="경합 후 표시",
                ),
                idempotency_key="race-rename-" + uuid4().hex,
            )
        with pytest.raises(KakaoArchiveError, match="STUDENT_STALE"):
            future.result(timeout=20)


def test_owner_isolation_binding_and_student_cannot_cross(creative_engine, room_context):
    actor, binding, service = room_context
    room = admit(creative_engine, room_context)[0].room
    other = make_actor(creative_engine)
    _, foreign_command = student_and_map(creative_engine, other, room)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_room(other, binding.source_binding_id, room.room_id)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.command_room(
            actor,
            binding.source_binding_id,
            room.room_id,
            foreign_command,
            idempotency_key="foreign-student-" + uuid4().hex,
        )
    second = create(KakaoArchiveService(creative_engine), actor).binding
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_room(actor, second.source_binding_id, room.room_id)


def test_retired_binding_and_revoked_session_deny_replay(creative_engine, room_context):
    actor, binding, service = room_context
    key = "admission-retire-" + uuid4().hex
    room, values = admit(creative_engine, room_context, key=key)
    _, command = student_and_map(creative_engine, actor, room.room)
    mapkey = key + "map"
    service.command_room(
        actor, binding.source_binding_id, room.room.room_id, command, idempotency_key=mapkey
    )
    KakaoArchiveService(creative_engine).command_binding(
        actor,
        binding.source_binding_id,
        KakaoBindingRetire(
            parent_policy_revision_id=binding.policy_revision.policy_revision_id,
            expected_resource_version=binding.resource_version,
        ),
        idempotency_key=key + "retire",
    )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        admit(creative_engine, room_context, key=key, values=values)
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        service.command_room(
            actor, binding.source_binding_id, room.room.room_id, command, idempotency_key=mapkey
        )
    with Session(creative_engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.get_room(actor, binding.source_binding_id, room.room.room_id)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-source",
        "revoked-source",
        "source-schema",
        "source-member",
        "source-hash",
        "outer-header",
        "outer-manifest",
        "outer-job",
    ],
)
def test_admission_replay_revalidates_both_artifact_pointers(
    creative_engine, room_context, fault, monkeypatch
):
    key = "pointer-replay-" + uuid4().hex
    first, values = admit(creative_engine, room_context, key=key)
    observation, evidence, _authority = values
    original = Session.execute
    target = evidence if fault.startswith("outer") else observation.source_evidence

    def faulted_read(session, statement, *args, **kwargs):
        result = original(session, statement, *args, **kwargs)
        columns = getattr(statement, "column_descriptions", ())
        if len(columns) != 3 or columns[0].get("entity") is not ArtifactRecord:
            return result
        rows = list(result.all())
        position = next(
            (
                index
                for index, row in enumerate(rows)
                if row[1].revision_id == target.artifact_revision_id
            ),
            None,
        )
        if position is None:
            return SimpleNamespace(all=lambda: rows)
        row = rows[position]
        # Inject at the metadata read boundary. Approved Artifact rows stay immutable;
        # this never disables their database protection, even in the disposable fixture.
        logical = SimpleNamespace(
            **{c.name: getattr(row[0], c.name) for c in ArtifactRecord.__table__.columns}
        )
        revision = SimpleNamespace(
            **{
                c.name: deepcopy(getattr(row[1], c.name))
                for c in ArtifactRevisionRecord.__table__.columns
            }
        )
        status = row[2]
        if fault == "missing-source":
            rows.pop(position)
            return SimpleNamespace(all=lambda: rows)
        if fault == "outer-header":
            logical.artifact_type = "wrong-kind"
        elif fault == "outer-job":
            status = "FAILED"
        elif fault == "outer-manifest":
            revision.manifest_hash = "sha256:" + "0" * 64
        elif fault == "revoked-source":
            logical.approved = False
        else:
            entry = revision.manifest["files"][0]
            if fault == "source-schema":
                entry["schema_ref"] = "eom://schemas/wrong/1.0"
            elif fault == "source-member":
                entry["file_name"] = "different.json"
            else:
                entry["sha256"] = "sha256:" + "0" * 64
            revision.manifest_hash = sha256_bytes(canonical_json_bytes(revision.manifest))
        rows[position] = (logical, revision, status)
        return SimpleNamespace(all=lambda: rows)

    with monkeypatch.context() as scoped:
        scoped.setattr(Session, "execute", faulted_read)
        with pytest.raises(KakaoArchiveError, match="ADMISSION_EVIDENCE_INVALID"):
            admit(creative_engine, room_context, key=key, values=values)
    assert admit(creative_engine, room_context, key=key, values=values)[0].replayed
    assert (
        room_context[2].get_room(
            room_context[0], room_context[1].source_binding_id, first.room.room_id
        )
        == first.room
    )


def test_admission_requires_current_authority_even_on_replay_and_rejects_future(
    creative_engine, room_context
):
    actor, binding, service = room_context
    key = "authority-replay-" + uuid4().hex
    _, (observation, evidence, _) = admit(creative_engine, room_context, key=key)

    def denied(*_):
        raise PermissionError("private source not authorized")

    for authority in (None, denied):
        with pytest.raises(KakaoArchiveError, match="ADMISSION_AUTHORITY_REQUIRED"):
            service.admit_room(
                actor,
                observation,
                evidence=evidence,
                idempotency_key=key,
                authorize_observation=authority,
            )
    future = observed(
        creative_engine,
        binding.source_binding_id,
        observed_at=datetime.now(UTC) + timedelta(days=1),
    )
    with pytest.raises(KakaoArchiveError, match="ADMISSION_EVIDENCE_INVALID"):
        admit(creative_engine, room_context, values=future)


def test_read_page_is_index_ordered_bounded_and_constant_queries(creative_engine, room_context):
    actor, binding, service = room_context
    rooms = [admit(creative_engine, room_context)[0].room for _ in range(3)]
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        one = service.list_rooms(actor, binding.source_binding_id, limit=1)
        count = len(statements)
        statements.clear()
        all_rooms = service.list_rooms(actor, binding.source_binding_id, limit=100)
        assert len(statements) == count
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert [r.room_id for r in all_rooms.items] == sorted(r.room_id for r in rooms)
    assert one.next_cursor == one.items[-1].room_id
    assert (
        len(service.list_rooms(actor, binding.source_binding_id, cursor=one.next_cursor).items) == 2
    )


def test_immutable_history_and_composite_current_fk_reject_mutation(creative_engine, room_context):
    room = admit(creative_engine, room_context)[0].room
    other = admit(creative_engine, room_context)[0].room
    with pytest.raises(DBAPIError), Session(creative_engine) as session, session.begin():
        session.execute(
            update(KakaoRoomMappingRevisionRecord)
            .where(
                KakaoRoomMappingRevisionRecord.mapping_revision_id
                == room.mapping.mapping_revision_id
            )
            .values(reason="변조")
        )
    with pytest.raises(DBAPIError), Session(creative_engine) as session, session.begin():
        session.execute(
            update(KakaoRoomAdmissionRecord)
            .where(KakaoRoomAdmissionRecord.room_id == room.room_id)
            .values(evidence_sha256="sha256:" + "0" * 64)
        )
    with pytest.raises(DBAPIError), Session(creative_engine) as session, session.begin():
        session.execute(
            update(KakaoRoomRecord)
            .where(KakaoRoomRecord.room_id == room.room_id)
            .values(current_mapping_revision_id=other.mapping.mapping_revision_id)
        )
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_transaction_interruption_leaves_no_admitted_room(
    creative_engine, room_context, monkeypatch
):
    _actor, binding, service = room_context
    values = observed(creative_engine, binding.source_binding_id)
    original = service._mapped_view

    def interrupt(*args):
        original(*args)
        raise RuntimeError("synthetic interruption before commit")

    monkeypatch.setattr(service, "_mapped_view", interrupt)
    key = "interrupted-admission-" + uuid4().hex
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        admit(creative_engine, room_context, values=values, key=key)
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoRoomRecord)
                .where(KakaoRoomRecord.source_binding_id == binding.source_binding_id)
            )
            == 0
        )
    monkeypatch.setattr(service, "_mapped_view", original)
    assert not admit(creative_engine, room_context, values=values, key=key)[0].replayed
