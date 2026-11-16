"""Official disposable PostgreSQL and local Artifacts; never production or real chats."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_question import (
    KakaoDisplayOverride,
    KakaoQuestionConfirm,
    KakaoQuestionEdit,
    KakaoQuestionExclude,
    KakaoQuestionProvenance,
)
from eom_catalog_contracts.kakao_question_store import KakaoQuestionChange, KakaoQuestionCreate
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionCommandRecord,
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identity_service.models import ApiSessionRecord
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_room_storage import student_and_map
from tests.integration.test_kakao_source_storage import accepted
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def question_store(source_store):
    engine, actor, binding, sources, artifacts, *_ = source_store
    source, admission, _ = accepted(source_store)
    rooms = KakaoRoomService(engine)
    room = rooms.get_room(actor, binding.source_binding_id, admission.room_id)
    _, mapping = student_and_map(engine, actor, room)
    room = rooms.command_room(
        actor,
        binding.source_binding_id,
        room.room_id,
        mapping,
        idempotency_key="map-" + uuid4().hex,
    ).room
    command = KakaoQuestionCreate(
        source_binding_id=binding.source_binding_id,
        room_id=room.room_id,
        source_revision_id=source.resolution.source_revision_id,
        candidate_ordinal=1,
        expected_mapping_revision_id=room.mapping.mapping_revision_id,
    )
    service = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    return engine, actor, service, command, sources, artifacts, binding


def create_question(store, *, key=None):
    _, actor, service, command, *_ = store
    key = key or "question-create-" + uuid4().hex
    return service.create_question(actor, command, idempotency_key=key), key


def change_command(stored, *, confirm=True):
    edit = (
        KakaoQuestionConfirm(
            parent_revision_id=stored.question_revision_id,
            reason="익명 원문 확인",
            boundary_confirmed=True,
        )
        if confirm
        else KakaoQuestionExclude(
            parent_revision_id=stored.question_revision_id, reason="제외 확인"
        )
    )
    return KakaoQuestionChange(
        source_binding_id=stored.source_binding_id,
        room_id=stored.room_id,
        question_id=stored.question_id,
        expected_resource_version=stored.resource_version,
        edit=edit,
    )


def test_create_exact_read_review_history_and_no_private_db_body(question_store):
    engine, actor, service, command, *_ = question_store
    first, key = create_question(question_store)
    assert first.question.review_state == "UNREVIEWED" and not first.replayed
    again = service.create_question(actor, command, idempotency_key=key)
    assert again.replayed and again.question == first.question
    changed = service.change_question(
        actor, change_command(first.question), idempotency_key="review-" + uuid4().hex
    )
    assert changed.question.resource_version == 2 and changed.question.review_state == "CONFIRMED"
    read = service.get_question(
        actor,
        command.source_binding_id,
        command.room_id,
        first.question.question_id,
        revision_id=first.question.question_revision_id,
    )
    assert read.stored == first.question
    assert (
        len({block.source_occurrence_id for block in read.published.question.ordered_blocks}) == 2
    )
    page = service.list_questions(actor, command.source_binding_id)
    assert page.items == (changed.question,)
    assert (
        service.list_questions(
            actor, command.source_binding_id, cursor=first.question.question_id
        ).items
        == ()
    )
    with Session(engine) as session:
        for cls in (KakaoQuestionRecord, KakaoQuestionCommandRecord, KakaoQuestionRevisionRecord):
            rows = session.scalars(select(cls).where(cls.question_id == first.question.question_id))
            for row in rows:
                values = {
                    column.name: getattr(row, column.name) for column in cls.__table__.columns
                }
                assert "private question" not in json.dumps(values, default=str)
                assert not any(isinstance(value, (bytes, dict, list)) for value in values.values())


@pytest.mark.parametrize("edit", [False, True])
def test_same_intent_concurrency_accepts_exactly_one_revision(question_store, edit):
    engine, actor, service, command, *_ = question_store
    if edit:
        first, _ = create_question(question_store)
        command = change_command(first.question)
    barrier, key = Barrier(2), "concurrent-" + uuid4().hex

    def run():
        barrier.wait(timeout=20)
        call = service.change_question if edit else service.create_question
        return call(actor, command, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = list(pool.map(lambda _: run(), range(2)))
    assert one.question == two.question
    assert sum(result.replayed for result in (one, two)) == 1
    with Session(engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(KakaoQuestionRevisionRecord)
            .where(KakaoQuestionRevisionRecord.question_id == one.question.question_id)
        ) == (2 if edit else 1)


def test_interruption_after_publication_reuses_reserved_identity_and_artifact(
    question_store, monkeypatch
):
    engine, actor, service, command, *_ = question_store
    original, key = service._adopt, "interrupted-" + uuid4().hex
    published = []

    def stop(*args, **kwargs):
        published.append(args[3].published.pointer)
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(service, "_adopt", stop)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        service.create_question(actor, command, idempotency_key=key)
    with Session(engine) as session:
        reserved = session.scalar(
            select(KakaoQuestionCommandRecord).where(
                KakaoQuestionCommandRecord.idempotency_key == key
            )
        )
        identity = reserved.question_id, reserved.question_revision_id
        assert reserved.state == "RESERVED"
        assert session.get(KakaoQuestionRecord, identity[0]) is None
    monkeypatch.setattr(service, "_adopt", original)
    recovered = service.create_question(actor, command, idempotency_key=key)
    assert (recovered.question.question_id, recovered.question.question_revision_id) == identity
    assert recovered.question.manifest == published[0]
    assert service.create_question(actor, command, idempotency_key=key).replayed


def test_origin_duplicate_and_changed_request_do_not_overwrite_current(question_store):
    engine, actor, service, command, *_ = question_store
    first, key = create_question(question_store)
    with pytest.raises(KakaoArchiveError, match="CANDIDATE_ALREADY_REGISTERED"):
        create_question(question_store)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.create_question(
            actor, command.model_copy(update={"candidate_ordinal": 2}), idempotency_key=key
        )
    with Session(engine) as session:
        assert session.get(KakaoQuestionRecord, first.question.question_id).resource_version == 1


def test_display_edit_is_durable_without_rewriting_source_or_old_question(question_store):
    engine, actor, service, command, sources, artifacts, _ = question_store
    first, _ = create_question(question_store)
    original = service.get_question(
        actor,
        command.source_binding_id,
        command.room_id,
        first.question.question_id,
        revision_id=first.question.question_revision_id,
    ).published.question
    blocks = list(original.ordered_blocks)
    blocks[0] = blocks[0].model_copy(
        update={
            "display_override": KakaoDisplayOverride(
                text="표시 문구 교정", reason="오타 표시만 교정"
            )
        }
    )
    edited = service.change_question(
        actor,
        KakaoQuestionChange(
            source_binding_id=command.source_binding_id,
            room_id=command.room_id,
            question_id=original.question_id,
            expected_resource_version=1,
            edit=KakaoQuestionEdit(
                parent_revision_id=original.question_revision_id,
                student=original.student,
                ordered_blocks=tuple(blocks),
                selection_exclusions=(),
            ),
        ),
        idempotency_key="display-edit-" + uuid4().hex,
    )
    restarted = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    current = restarted.get_question(
        actor,
        command.source_binding_id,
        command.room_id,
        original.question_id,
        revision_id=edited.question.question_revision_id,
    )
    assert current.stored.resource_version == 2 and current.stored.review_state == "UNREVIEWED"
    assert current.published.question.ordered_blocks[0].display_override.text == "표시 문구 교정"
    assert (
        restarted.get_question(
            actor,
            command.source_binding_id,
            command.room_id,
            original.question_id,
            revision_id=original.question_revision_id,
        ).published.question
        == original
    )
    source = sources.resolve_question_source(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    )
    assert source.normalization.messages[0].text == "private question"


def test_old_edit_replay_returns_old_revision_not_latest(question_store):
    _, actor, service, _command, *_ = question_store
    first, _ = create_question(question_store)
    change, key = change_command(first.question), "first-change-" + uuid4().hex
    reviewed = service.change_question(actor, change, idempotency_key=key)
    excluded = service.change_question(
        actor,
        change_command(reviewed.question, confirm=False),
        idempotency_key="next-change-" + uuid4().hex,
    )
    assert excluded.question.resource_version == 3
    old = service.change_question(actor, change, idempotency_key=key)
    assert old.replayed and old.question == reviewed.question


def test_competing_edit_cas_has_one_winner(question_store):
    engine, actor, service, *_ = question_store
    first, _ = create_question(question_store)
    barrier = Barrier(2)

    def run(confirm):
        barrier.wait(timeout=20)
        try:
            return service.change_question(
                actor,
                change_command(first.question, confirm=confirm),
                idempotency_key="compete-" + uuid4().hex,
            )
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (True, False)))
    assert sum(not isinstance(value, str) for value in results) == 1
    assert "KAKAO_ARCHIVE_PRECONDITION_FAILED" in results
    with Session(engine) as session:
        assert session.get(KakaoQuestionRecord, first.question.question_id).resource_version == 2


@pytest.mark.parametrize("revoke", ["session", "binding"])
def test_revoke_after_publication_prevents_adoption(question_store, monkeypatch, revoke):
    engine, actor, _service, command, _sources, _artifacts, binding = question_store
    import eom_catalog_service.kakao_question_service as module

    publish = module.publish_kakao_question

    def revoked(*args, **kwargs):
        result = publish(*args, **kwargs)
        if revoke == "session":
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC))
                )
        else:
            # Source withdrawal is a domain lifecycle change, never a rewrite of
            # immutable generic Artifact approval or fake credential mutation.
            KakaoArchiveService(engine).command_binding(
                actor,
                command.source_binding_id,
                KakaoBindingRetire(
                    parent_policy_revision_id=binding.policy_revision.policy_revision_id,
                    expected_resource_version=binding.resource_version,
                ),
                idempotency_key="withdraw-source-" + uuid4().hex,
            )
        return result

    monkeypatch.setattr(module, "publish_kakao_question", revoked)
    with pytest.raises(KakaoArchiveError, match=r"PERMISSION_DENIED|BINDING_RETIRED"):
        create_question(question_store)
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.room_id == command.room_id)
            )
            == 0
        )


def test_owner_and_retired_binding_deny_history_and_replay(question_store):
    engine, actor, service, command, _, _, binding = question_store
    first, key = create_question(question_store)
    other = make_actor(engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_question(
            other,
            command.source_binding_id,
            command.room_id,
            first.question.question_id,
            revision_id=first.question.question_revision_id,
        )
    KakaoArchiveService(engine).command_binding(
        actor,
        binding.source_binding_id,
        KakaoBindingRetire(
            parent_policy_revision_id=binding.policy_revision.policy_revision_id,
            expected_resource_version=binding.resource_version,
        ),
        idempotency_key="retire-" + uuid4().hex,
    )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        service.create_question(actor, command, idempotency_key=key)


@pytest.mark.parametrize("mutation", ["revision", "head", "command"])
def test_sql_immutability_and_current_version_guards(question_store, mutation):
    engine, _, _, *_ = question_store
    first, _ = create_question(question_store)
    with pytest.raises(DBAPIError), Session(engine) as session, session.begin():
        if mutation == "revision":
            session.execute(
                update(KakaoQuestionRevisionRecord)
                .where(
                    KakaoQuestionRevisionRecord.question_revision_id
                    == first.question.question_revision_id
                )
                .values(review_state="EXCLUDED")
            )
        elif mutation == "head":
            session.execute(
                update(KakaoQuestionRecord)
                .where(KakaoQuestionRecord.question_id == first.question.question_id)
                .values(resource_version=2)
            )
        else:
            session.execute(
                update(KakaoQuestionCommandRecord)
                .where(KakaoQuestionCommandRecord.question_id == first.question.question_id)
                .values(state="RESERVED", completed_at=None)
            )


def test_question_pages_are_metadata_only_no_artifact_read(question_store, monkeypatch):
    _, actor, service, command, _, artifacts, _ = question_store
    first, _ = create_question(question_store)

    def blocked(*args, **kwargs):
        raise AssertionError("list must not parse message or question bodies")

    monkeypatch.setattr(artifacts, "read_member", blocked)
    assert service.list_questions(
        actor, command.source_binding_id, room_id=command.room_id
    ).items == (first.question,)


def test_batch_read_preserves_selected_order_and_parses_shared_source_once(
    question_store, monkeypatch
):
    _, actor, service, command, sources, _artifacts, _ = question_store
    first, _ = create_question(question_store)
    next_revision = service.change_question(
        actor, change_command(first.question), idempotency_key="batch-review-" + uuid4().hex
    )
    original = sources.resolve_question_source_context
    calls = []

    def observed(*args, **kwargs):
        calls.append(kwargs["source_revision_id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(sources, "resolve_question_source_context", observed)
    resolved = service.resolve_questions(
        actor,
        command.source_binding_id,
        tuple(
            KakaoQuestionProvenance(
                question_id=value.question_id, question_revision_id=value.question_revision_id
            )
            for value in (next_revision.question, first.question)
        ),
    )
    assert tuple(value.stored for value in resolved.questions) == (
        next_revision.question,
        first.question,
    )
    assert calls == [command.source_revision_id]
    assert len(resolved.sources) == 1


def test_bounded_batch_read_rejects_duplicate_and_missing_exact_revision(question_store):
    _, actor, service, command, *_ = question_store
    first, _ = create_question(question_store)
    pin = KakaoQuestionProvenance(
        question_id=first.question.question_id,
        question_revision_id=first.question.question_revision_id,
    )
    with pytest.raises(KakaoArchiveError, match="QUESTION_SELECTION_INVALID"):
        service.resolve_questions(actor, command.source_binding_id, (pin, pin))
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.resolve_questions(
            actor,
            command.source_binding_id,
            (pin.model_copy(update={"question_revision_id": "kakaoquestionrev_" + uuid4().hex}),),
        )
