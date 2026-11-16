"""Actual atomic split/merge, replay and interruption in the guarded disposable DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_packet_store import KakaoPacketCreate
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_contracts.kakao_question_composition import (
    KakaoCompositionInput,
    KakaoQuestionMerge,
    KakaoQuestionSplit,
    KakaoWholeBlockSelection,
)
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_packet_service import KakaoPacketService
from eom_catalog_service.kakao_question_compose_service import KakaoQuestionComposeService
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionInputRecord as InputRecord,
)
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionOutputRecord as OutputRecord,
)
from eom_catalog_service.kakao_question_composition_models import (
    KakaoQuestionCompositionRecord as CompositionRecord,
)
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_room_storage import student_and_map
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def pin(stored):
    return KakaoCompositionInput(
        question_id=stored.question_id,
        question_revision_id=stored.question_revision_id,
        resource_version=stored.resource_version,
    )


def setup_case(store):
    engine, actor, questions, _creation, sources, artifacts, *_ = store
    initial, _ = create_question(store)
    value = initial.question
    accepted = questions.get_question(
        actor,
        value.source_binding_id,
        value.room_id,
        value.question_id,
        revision_id=value.question_revision_id,
    )
    command = KakaoQuestionSplit(
        source_binding_id=value.source_binding_id,
        room_id=value.room_id,
        input=pin(value),
        partitions=tuple(
            (KakaoWholeBlockSelection(block_id=block.block_id),)
            for block in accepted.published.question.ordered_blocks
        ),
    )
    composer = KakaoQuestionComposeService(
        engine, questions=questions, sources=sources, artifacts=artifacts
    )
    return composer, command, initial.question


def test_split_merge_exact_history_list_replay_and_origin_dedup(question_store):
    engine, actor, questions, creation, *_ = question_store
    composer, command, original = setup_case(question_store)
    key = "compose-" + uuid4().hex
    split = composer.compose_questions(actor, command, idempotency_key=key)
    assert not split.replayed and len(split.outputs) == 2
    page = questions.list_questions(actor, original.source_binding_id)
    assert {q.question_id for q in page.items} == {q.question_id for q in split.outputs}
    assert (
        questions.get_question(
            actor,
            original.source_binding_id,
            original.room_id,
            original.question_id,
            revision_id=original.question_revision_id,
        ).stored
        == original
    )
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        questions.change_question(
            actor, change_command(original), idempotency_key="edit-old-" + uuid4().hex
        )
    with pytest.raises(KakaoArchiveError, match="CANDIDATE_ALREADY_REGISTERED"):
        questions.create_question(actor, creation, idempotency_key="reingest-" + uuid4().hex)
    changed = questions.change_question(
        actor, change_command(split.outputs[0]), idempotency_key="edit-part-" + uuid4().hex
    )
    merge_command = KakaoQuestionMerge(
        source_binding_id=original.source_binding_id,
        room_id=original.room_id,
        inputs=(pin(changed.question), pin(split.outputs[1])),
    )
    merged = composer.compose_questions(
        actor, merge_command, idempotency_key="merge-" + uuid4().hex
    )
    assert len(merged.outputs) == 1
    assert questions.list_questions(actor, original.source_binding_id).items == merged.outputs
    replay = composer.compose_questions(actor, command, idempotency_key=key)
    assert replay.replayed and replay.outputs == split.outputs
    with Session(engine) as session:
        head = session.get(KakaoQuestionRecord, original.question_id)
        assert head.superseded_by_composition_id == split.composition_id
        assert head.current_revision_id == original.question_revision_id
        assert head.resource_version == original.resource_version
        for stored in split.outputs:
            head = session.get(KakaoQuestionRecord, stored.question_id)
            assert head.origin_composition_id == split.composition_id
            assert head.origin_source_revision_id is None and head.origin_occurrence_id is None
            assert head.superseded_by_composition_id == merged.composition_id


def test_same_request_concurrency_adopts_one_result(question_store):
    engine, actor, *_ = question_store
    composer, command, _ = setup_case(question_store)
    key, gate = "same-compose-" + uuid4().hex, Barrier(2)

    def run():
        gate.wait(timeout=20)
        return composer.compose_questions(actor, command, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: run(), range(2)))
    assert one.outputs == two.outputs and one.composition_id == two.composition_id
    assert sum(x.replayed for x in (one, two)) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CompositionRecord)
                .where(CompositionRecord.idempotency_key == key)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.origin_composition_id == one.composition_id)
            )
            == 2
        )


def test_different_request_race_preserves_losing_reservation(question_store):
    engine, actor, *_ = question_store
    composer, command, original = setup_case(question_store)
    gate = Barrier(2)

    def run():
        gate.wait(timeout=20)
        try:
            return composer.compose_questions(
                actor, command, idempotency_key="race-compose-" + uuid4().hex
            )
        except KakaoArchiveError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(not isinstance(x, str) for x in results) == 1
    assert any(isinstance(x, str) and "PRECONDITION_FAILED" in x for x in results)
    with Session(engine) as session:
        heads = tuple(
            session.scalars(
                select(KakaoQuestionRecord).where(KakaoQuestionRecord.room_id == original.room_id)
            )
        )
        assert len(heads) == 3


def test_partial_publication_resumes_same_reserved_outputs(question_store, monkeypatch):
    import eom_catalog_service.kakao_question_compose_service as module

    engine, actor, *_ = question_store
    composer, command, original = setup_case(question_store)
    real_publish, captures = module.publish_kakao_question, []
    key = "interrupt-files-" + uuid4().hex

    def interrupted(*args, **kwargs):
        if captures:
            raise RuntimeError("synthetic interruption before second publication")
        result = real_publish(*args, **kwargs)
        captures.append(result)
        return result

    monkeypatch.setattr(module, "publish_kakao_question", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        composer.compose_questions(actor, command, idempotency_key=key)
    with Session(engine) as session:
        record = session.scalar(
            select(CompositionRecord).where(CompositionRecord.idempotency_key == key)
        )
        cid = record.composition_id
        assert record.state == "RESERVED"
        assert (
            session.get(KakaoQuestionRecord, original.question_id).superseded_by_composition_id
            is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.origin_composition_id == cid)
            )
            == 0
        )
    monkeypatch.setattr(module, "publish_kakao_question", real_publish)
    result = composer.compose_questions(actor, command, idempotency_key=key)
    assert result.composition_id == cid
    assert result.outputs[0].manifest == captures[0].published.pointer
    assert composer.compose_questions(actor, command, idempotency_key=key).replayed


def test_transaction_abort_cannot_leave_some_new_heads(question_store, monkeypatch):
    engine, actor, *_ = question_store
    composer, command, original = setup_case(question_store)
    key, real_insert = "abort-adopt-" + uuid4().hex, composer._insert_output

    def interrupted(*args):
        real_insert(*args)
        raise RuntimeError("synthetic adoption abort")

    monkeypatch.setattr(composer, "_insert_output", interrupted)
    with pytest.raises(RuntimeError, match="synthetic adoption abort"):
        composer.compose_questions(actor, command, idempotency_key=key)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.room_id == original.room_id)
            )
            == 1
        )
        assert (
            session.get(KakaoQuestionRecord, original.question_id).superseded_by_composition_id
            is None
        )
    monkeypatch.setattr(composer, "_insert_output", real_insert)
    assert len(composer.compose_questions(actor, command, idempotency_key=key).outputs) == 2


def test_edit_before_adoption_wins_without_overwriting_it(question_store, monkeypatch):
    engine, actor, questions, *_ = question_store
    composer, command, original = setup_case(question_store)
    real_adopt, changed = composer._adopt, []

    def concurrent_edit(*args):
        changed.append(
            questions.change_question(
                actor, change_command(original), idempotency_key="during-compose-" + uuid4().hex
            )
        )
        return real_adopt(*args)

    monkeypatch.setattr(composer, "_adopt", concurrent_edit)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        composer.compose_questions(actor, command, idempotency_key="compose-stale-" + uuid4().hex)
    assert questions.list_questions(actor, original.source_binding_id).items == (
        changed[0].question,
    )
    with Session(engine) as session:
        assert (
            session.get(KakaoQuestionRecord, original.question_id).superseded_by_composition_id
            is None
        )


def test_changed_body_same_key_is_not_a_new_composition(question_store):
    _, actor, *_ = question_store
    composer, command, _ = setup_case(question_store)
    key = "same-key-" + uuid4().hex
    composer.compose_questions(actor, command, idempotency_key=key)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        composer.compose_questions(
            actor,
            command.model_copy(update={"partitions": tuple(reversed(command.partitions))}),
            idempotency_key=key,
        )


def test_database_prevents_partial_supersession_and_fake_completion(question_store):
    engine, actor, *_ = question_store
    composer, command, original = setup_case(question_store)
    reserved = composer._reserve(actor, command, "reserve-only-" + uuid4().hex)
    for statement in (
        update(KakaoQuestionRecord)
        .where(KakaoQuestionRecord.question_id == original.question_id)
        .values(superseded_by_composition_id=reserved.composition_id),
        update(CompositionRecord)
        .where(CompositionRecord.composition_id == reserved.composition_id)
        .values(state="COMPLETED", completed_at=func.now()),
    ):
        with (
            pytest.raises(DBAPIError, match="ADOPTION_INCOMPLETE"),
            Session(engine) as session,
            session.begin(),
        ):
            session.execute(statement)


def test_completed_receipt_and_input_output_members_are_immutable(question_store):
    engine, actor, *_ = question_store
    composer, command, original = setup_case(question_store)
    result = composer.compose_questions(actor, command, idempotency_key="immutable-" + uuid4().hex)
    statements = (
        update(CompositionRecord)
        .where(CompositionRecord.composition_id == result.composition_id)
        .values(request_sha256="sha256:" + "0" * 64),
        update(InputRecord)
        .where(InputRecord.composition_id == result.composition_id)
        .values(resource_version=2),
        update(OutputRecord)
        .where(OutputRecord.composition_id == result.composition_id)
        .values(ordinal=10),
        update(KakaoQuestionRecord)
        .where(KakaoQuestionRecord.question_id == original.question_id)
        .values(superseded_by_composition_id=None),
        text(
            "INSERT INTO kakao_question_composition_outputs "
            "(composition_id,ordinal,question_id,question_revision_id) VALUES (:c,99,:q,:r)"
        ).bindparams(
            c=result.composition_id,
            q="kakaoquestion_" + uuid4().hex,
            r="kakaoquestionrev_" + uuid4().hex,
        ),
    )
    for statement in statements:
        with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
            session.execute(statement)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRevisionRecord)
                .where(KakaoQuestionRevisionRecord.composition_id == result.composition_id)
            )
            == 2
        )


@pytest.mark.parametrize("withdraw", ["session", "binding"])
@pytest.mark.parametrize("completed", [False, True])
def test_revocation_denies_adoption_and_completed_replay(
    question_store, monkeypatch, withdraw, completed
):
    engine, actor, _, _, _, _, binding = question_store
    composer, command, original = setup_case(question_store)
    key = "revoked-compose-" + uuid4().hex

    def revoke():
        if withdraw == "session":
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC))
                )
        else:
            KakaoArchiveService(engine).command_binding(
                actor,
                binding.source_binding_id,
                KakaoBindingRetire(
                    parent_policy_revision_id=binding.policy_revision.policy_revision_id,
                    expected_resource_version=binding.resource_version,
                ),
                idempotency_key="retire-compose-source-" + uuid4().hex,
            )

    if completed:
        composer.compose_questions(actor, command, idempotency_key=key)
        revoke()
    else:
        real_adopt = composer._adopt

        def revoked_adoption(*args):
            revoke()
            return real_adopt(*args)

        monkeypatch.setattr(composer, "_adopt", revoked_adoption)
    with pytest.raises(KakaoArchiveError, match=r"PERMISSION_DENIED|BINDING_RETIRED"):
        composer.compose_questions(actor, command, idempotency_key=key)
    with Session(engine) as session:
        row = session.get(KakaoQuestionRecord, original.question_id)
        assert (row.superseded_by_composition_id is not None) is completed
        assert row.current_revision_id == original.question_revision_id


def test_student_mapping_change_before_adoption_cannot_move_questions(question_store, monkeypatch):
    engine, actor, questions, *_ = question_store
    composer, command, original = setup_case(question_store)
    real_adopt, rooms = composer._adopt, KakaoRoomService(engine)
    room = rooms.get_room(actor, original.source_binding_id, original.room_id)
    _, mapping = student_and_map(engine, actor, room)

    def mapping_changed(*args):
        rooms.command_room(
            actor,
            original.source_binding_id,
            original.room_id,
            mapping,
            idempotency_key="compose-remap-" + uuid4().hex,
        )
        return real_adopt(*args)

    monkeypatch.setattr(composer, "_adopt", mapping_changed)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        composer.compose_questions(actor, command, idempotency_key="mapping-race-" + uuid4().hex)
    assert questions.list_questions(actor, original.source_binding_id).items == (original,)


def test_existing_packet_keeps_exact_question_after_split_and_restart(question_store):
    engine, actor, questions, _, sources, artifacts, _ = question_store
    composer, command, original = setup_case(question_store)
    packets = KakaoPacketService(engine, questions=questions, sources=sources, artifacts=artifacts)
    packet = packets.save_packet(
        actor,
        KakaoPacketCreate(
            source_binding_id=original.source_binding_id,
            title="분할 이전 불변 질문 묶음",
            questions=(
                KakaoQuestionProvenance(
                    question_id=original.question_id,
                    question_revision_id=original.question_revision_id,
                ),
            ),
            display_start_date=date(2026, 1, 1),
            display_end_date_inclusive=date(2026, 12, 31),
            mode="DRAFT",
            include_replies=False,
        ),
        idempotency_key="before-split-packet-" + uuid4().hex,
    ).packet
    key = "packet-preserving-split-" + uuid4().hex
    split = composer.compose_questions(actor, command, idempotency_key=key)
    restarted = KakaoPacketService(
        engine, questions=questions, sources=sources, artifacts=artifacts
    )
    stored, selected = restarted.resolve_student(
        actor,
        original.source_binding_id,
        packet.packet_id,
        revision_id=packet.packet_revision_id,
        student_id=original.student.student_id,
    )
    assert stored.stored == packet
    assert tuple(q.stored for q in selected.questions) == (original,)
    restarted_composer = KakaoQuestionComposeService(
        engine, questions=questions, sources=sources, artifacts=artifacts
    )
    replay = restarted_composer.compose_questions(actor, command, idempotency_key=key)
    assert replay.replayed and replay.outputs == split.outputs
