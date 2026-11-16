"""Stored private packet and exact student subset; guarded PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_packet_store import KakaoPacketCreate, KakaoPacketRevise
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_contracts.kakao_question_store import KakaoQuestionCreate
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_packet_models import (
    KakaoPacketCommandRecord,
    KakaoPacketRevisionRecord,
)
from eom_catalog_service.kakao_packet_service import KakaoPacketService
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_room_storage import admit, student_and_map
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def packet_store(question_store, source_store):
    engine, actor, questions, _qcommand, sources, artifacts, binding = question_store
    first, _ = create_question(question_store)
    rooms = KakaoRoomService(engine)
    second_room = admit(engine, (actor, binding, rooms))[0].room
    _, mapping = student_and_map(engine, actor, second_room)
    second_room = rooms.command_room(
        actor,
        binding.source_binding_id,
        second_room.room_id,
        mapping,
        idempotency_key="second-map-" + uuid4().hex,
    ).room
    admission, _ = source_store[-1](
        room_id=second_room.room_id, texts=("second student", "second question")
    )
    accepted = sources.admit_source(
        actor, admission, idempotency_key="second-source-" + uuid4().hex
    )
    second = questions.create_question(
        actor,
        KakaoQuestionCreate(
            source_binding_id=binding.source_binding_id,
            room_id=second_room.room_id,
            source_revision_id=accepted.resolution.source_revision_id,
            candidate_ordinal=1,
            expected_mapping_revision_id=second_room.mapping.mapping_revision_id,
        ),
        idempotency_key="second-question-" + uuid4().hex,
    )
    command = KakaoPacketCreate(
        source_binding_id=binding.source_binding_id,
        title="익명 학생 질문 묶음",
        questions=tuple(
            KakaoQuestionProvenance(
                question_id=v.question.question_id,
                question_revision_id=v.question.question_revision_id,
            )
            for v in (first, second)
        ),
        display_start_date=date(2026, 1, 1),
        display_end_date_inclusive=date(2026, 12, 31),
        mode="DRAFT",
        include_replies=False,
    )
    service = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    return (
        engine,
        actor,
        service,
        command,
        (first.question, second.question),
        questions,
        sources,
        artifacts,
    )


def test_durable_packet_selection_and_student_isolation(packet_store):
    engine, actor, service, command, selected, questions, sources, artifacts = packet_store
    result = service.save_packet(actor, command, idempotency_key="packet-" + uuid4().hex)
    restarted = KakaoPacketService(
        engine, artifacts=artifacts, questions=questions, sources=sources
    )
    assert restarted.list_packets(actor, command.source_binding_id).items == (result.packet,)
    for expected in selected:
        stored, resolved = restarted.resolve_student(
            actor,
            command.source_binding_id,
            result.packet.packet_id,
            revision_id=result.packet.packet_revision_id,
            student_id=expected.student.student_id,
        )
        assert stored.stored == result.packet
        assert tuple(q.stored for q in resolved.questions) == (expected,)
        assert {source.resolved.normalization.room_id for source in resolved.sources} == {
            expected.room_id
        }


def test_packet_same_intent_concurrency_and_exact_replay(packet_store):
    _, actor, service, command, *_ = packet_store
    barrier, key = Barrier(2), "packet-race-" + uuid4().hex

    def run():
        barrier.wait(timeout=20)
        return service.save_packet(actor, command, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: run(), range(2)))
    assert one.packet == two.packet and sum(value.replayed for value in (one, two)) == 1
    assert service.save_packet(actor, command, idempotency_key=key).replayed
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.save_packet(
            actor, command.model_copy(update={"include_replies": True}), idempotency_key=key
        )


def test_packet_publication_interruption_keeps_ids_and_artifact(packet_store, monkeypatch):
    engine, actor, service, command, *_ = packet_store
    key, original, observed = "packet-stop-" + uuid4().hex, service._adopt, []

    def stop(*args):
        observed.append(args[4].pointer)
        raise RuntimeError("synthetic interrupted adoption")

    monkeypatch.setattr(service, "_adopt", stop)
    with pytest.raises(RuntimeError, match="synthetic"):
        service.save_packet(actor, command, idempotency_key=key)
    with Session(engine) as session:
        row = session.scalar(
            select(KakaoPacketCommandRecord).where(KakaoPacketCommandRecord.idempotency_key == key)
        )
        assert row.state == "RESERVED"
        identity = row.packet_id, row.packet_revision_id
    monkeypatch.setattr(service, "_adopt", original)
    recovered = service.save_packet(actor, command, idempotency_key=key)
    assert (recovered.packet.packet_id, recovered.packet.packet_revision_id) == identity
    assert recovered.packet.manifest == observed[0]


def test_packet_new_revision_does_not_rewrite_old_packet_or_old_replay(packet_store):
    _, actor, service, command, *_ = packet_store
    key = "original-packet-" + uuid4().hex
    first = service.save_packet(actor, command, idempotency_key=key)
    revise = KakaoPacketRevise.model_validate(
        command.model_dump(mode="json")
        | dict(
            schema_version="kakao-packet-revise/1.0",
            packet_id=first.packet.packet_id,
            parent_revision_id=first.packet.packet_revision_id,
            expected_resource_version=1,
            questions=tuple(reversed(command.questions)),
            title="순서 교정",
        )
    )
    second = service.save_packet(actor, revise, idempotency_key="revised-packet-" + uuid4().hex)
    assert second.packet.resource_version == 2
    old = service.get_packet(
        actor,
        command.source_binding_id,
        first.packet.packet_id,
        revision_id=first.packet.packet_revision_id,
    )
    assert tuple(q.question_id for q in old.packet.questions) == tuple(
        q.question_id for q in command.questions
    )
    assert service.save_packet(actor, command, idempotency_key=key).packet == first.packet
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        service.save_packet(actor, revise, idempotency_key="stale-packet-" + uuid4().hex)


def test_later_question_edits_do_not_reselect_packet_inputs(packet_store):
    _, actor, service, command, selected, questions, *_ = packet_store
    packet = service.save_packet(actor, command, idempotency_key="frozen-packet-" + uuid4().hex)
    questions.change_question(
        actor, change_command(selected[0]), idempotency_key="later-review-" + uuid4().hex
    )
    _, resolved = service.resolve_student(
        actor,
        command.source_binding_id,
        packet.packet.packet_id,
        revision_id=packet.packet.packet_revision_id,
        student_id=selected[0].student.student_id,
    )
    assert resolved.questions[0].stored == selected[0]


def test_final_refuses_unreviewed_questions_and_foreign_owner_cannot_read(packet_store):
    engine, actor, service, command, *_ = packet_store
    with pytest.raises(ValueError, match="FINAL_BLOCKED"):
        service.save_packet(
            actor,
            command.model_copy(update={"mode": "FINAL"}),
            idempotency_key="blocked-final-" + uuid4().hex,
        )
    packet = service.save_packet(actor, command, idempotency_key="private-packet-" + uuid4().hex)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_packet(
            make_actor(engine),
            command.source_binding_id,
            packet.packet.packet_id,
            revision_id=packet.packet.packet_revision_id,
        )


def test_session_revoke_after_publication_stops_adoption(packet_store, monkeypatch):
    engine, actor, service, command, *_ = packet_store
    import eom_catalog_service.kakao_packet_service as module

    publish = module.publish_kakao_packet

    def revoked(*args, **kwargs):
        value = publish(*args, **kwargs)
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        return value

    monkeypatch.setattr(module, "publish_kakao_packet", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.save_packet(actor, command, idempotency_key="revoked-packet-" + uuid4().hex)


def test_packet_revision_is_immutable_and_completed_command_not_rewritten(packet_store):
    engine, actor, service, command, *_ = packet_store
    saved = service.save_packet(actor, command, idempotency_key="immutable-packet-" + uuid4().hex)
    with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
        session.execute(
            update(KakaoPacketRevisionRecord)
            .where(KakaoPacketRevisionRecord.packet_revision_id == saved.packet.packet_revision_id)
            .values(title="changed")
        )
    with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
        session.execute(
            update(KakaoPacketCommandRecord)
            .where(KakaoPacketCommandRecord.packet_revision_id == saved.packet.packet_revision_id)
            .values(completed_at=None)
        )


def test_wrong_student_cannot_resolve_another_students_questions(packet_store):
    _, actor, service, command, *_ = packet_store
    packet = service.save_packet(actor, command, idempotency_key="wrong-student-" + uuid4().hex)
    with pytest.raises(KakaoArchiveError, match="STUDENT_NOT_IN_PACKET"):
        service.resolve_student(
            actor,
            command.source_binding_id,
            packet.packet.packet_id,
            revision_id=packet.packet.packet_revision_id,
            student_id="kakaostudent_" + uuid4().hex,
        )


def test_competing_packet_revisions_have_only_one_cas_winner(packet_store):
    _, actor, service, command, *_ = packet_store
    first = service.save_packet(actor, command, idempotency_key="parent-packet-" + uuid4().hex)
    barrier = Barrier(2)

    def revise(title):
        update_command = KakaoPacketRevise.model_validate(
            command.model_dump(mode="json")
            | dict(
                schema_version="kakao-packet-revise/1.0",
                packet_id=first.packet.packet_id,
                parent_revision_id=first.packet.packet_revision_id,
                expected_resource_version=1,
                title=title,
            )
        )
        barrier.wait(timeout=20)
        try:
            return service.save_packet(
                actor, update_command, idempotency_key="competing-" + uuid4().hex
            )
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(revise, ("편집 A", "편집 B")))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "KAKAO_ARCHIVE_PRECONDITION_FAILED" in results


def test_packet_listing_does_not_materialize_question_or_source_bodies(packet_store, monkeypatch):
    _, actor, service, command, _selected, _questions, _sources, artifacts = packet_store
    first = service.save_packet(actor, command, idempotency_key="listed-packet-" + uuid4().hex)

    def forbidden(*args, **kwargs):
        raise AssertionError("list must not read bodies")

    monkeypatch.setattr(artifacts, "read_member", forbidden)
    assert service.list_packets(actor, command.source_binding_id).items == (first.packet,)
