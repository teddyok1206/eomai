"""Explicit late-reply revisions through existing owners, only disposable PG."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_packet_store import KakaoPacketCreate
from eom_catalog_contracts.kakao_question import KakaoQuestionProvenance
from eom_catalog_contracts.kakao_question_refresh import KakaoQuestionSourceRefresh
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_packet_service import KakaoPacketService
from eom_catalog_service.kakao_question_editing import resolve_question_text
from eom_catalog_service.kakao_question_models import KakaoQuestionRecord
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from sqlalchemy.orm import Session

from tests.integration.test_kakao_candidate_autosave import counts, synthetic_access
from tests.integration.test_kakao_question_composition_storage import setup_case
from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_room_storage import student_and_map
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def late_source(store, source_store, *, extra_question=False):
    _engine, actor, _questions, creation, sources, *_ = store
    previous = sources.get_source(
        actor,
        creation.source_binding_id,
        creation.room_id,
        source_revision_id=creation.source_revision_id,
    ).resolution
    texts = ("first unique question", "unique continuation", "later staff reply")
    roles = ("student", "student", "staff")
    if extra_question:
        texts += ("separate question",)
        roles += ("student",)
    admission, _ = source_store[-1](previous=previous, texts=texts, roles=roles)
    return sources.admit_source(actor, admission, idempotency_key="late-source-" + uuid4().hex)


def refresh_command(stored, source_id, mapping_id):
    return KakaoQuestionSourceRefresh(
        source_binding_id=stored.source_binding_id,
        room_id=stored.room_id,
        question_id=stored.question_id,
        parent_revision_id=stored.question_revision_id,
        expected_resource_version=stored.resource_version,
        expected_mapping_revision_id=mapping_id,
        source_revision_id=source_id,
        candidate_ordinal=1,
        replace_display_edits=True,
    )


@pytest.fixture
def refresh_case(question_store, source_store):
    engine, actor, questions, creation, sources, artifacts, binding = question_store
    previous = sources.get_source(
        actor,
        creation.source_binding_id,
        creation.room_id,
        source_revision_id=creation.source_revision_id,
    ).resolution
    admission, _ = source_store[-1](
        previous=previous,
        texts=("first unique question", "unique continuation"),
    )
    initial = sources.admit_source(
        actor, admission, idempotency_key="anchored-source-" + uuid4().hex
    )
    creation = creation.model_copy(
        update={"source_revision_id": initial.resolution.source_revision_id}
    )
    store = engine, actor, questions, creation, sources, artifacts, binding
    first, _ = create_question(store)
    old = questions.change_question(
        actor,
        change_command(first.question),
        idempotency_key="old-review-" + uuid4().hex,
    ).question
    source = late_source(store, source_store, extra_question=True)
    command = refresh_command(
        old, source.resolution.source_revision_id, creation.expected_mapping_revision_id
    )
    return store, old, source, command


def test_late_reply_revision_preserves_previous_question_and_packet(refresh_case):
    store, old, _source, command = refresh_case
    engine, actor, questions, _creation, sources, artifacts, *_ = store
    packets = KakaoPacketService(engine, artifacts=artifacts, questions=questions, sources=sources)
    request = KakaoPacketCreate(
        source_binding_id=command.source_binding_id,
        title="before late reply",
        questions=(
            KakaoQuestionProvenance(
                question_id=old.question_id, question_revision_id=old.question_revision_id
            ),
        ),
        display_start_date=date(2026, 1, 1),
        display_end_date_inclusive=date(2026, 12, 31),
        mode="FINAL",
        include_replies=True,
    )
    packet = packets.save_packet(actor, request, idempotency_key="before-refresh-" + uuid4().hex)
    key = "refresh-" + uuid4().hex
    refreshed = questions.refresh_question_source(actor, command, idempotency_key=key)
    saved = refreshed.question
    assert (
        saved.question_id == old.question_id
        and saved.previous_revision_id == old.question_revision_id
    )
    assert saved.resource_version == old.resource_version + 1 and saved.review_state == "UNREVIEWED"
    assert questions.refresh_question_source(actor, command, idempotency_key=key).question == saved
    read = questions.get_question(
        actor,
        command.source_binding_id,
        command.room_id,
        saved.question_id,
        revision_id=saved.question_revision_id,
    )
    resolved = sources.resolve_question_source_context(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    ).resolved
    texts = tuple(
        resolve_question_text(block, resolved) for block in read.published.question.ordered_blocks
    )
    assert texts == ("first unique question", "unique continuation", "later staff reply")
    assert read.published.question.provenance == request.questions
    assert (
        questions.get_question(
            actor,
            old.source_binding_id,
            old.room_id,
            old.question_id,
            revision_id=old.question_revision_id,
        ).stored
        == old
    )
    reopened, selected = packets.resolve_student(
        actor,
        old.source_binding_id,
        packet.packet.packet_id,
        revision_id=packet.packet.packet_revision_id,
        student_id=old.student.student_id,
    )
    assert reopened.stored == packet.packet and selected.questions[0].stored == old
    # Recollection still retains the manual new head; it never creates the old origin again.
    auto = questions.create_source_candidates(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    )
    assert old.question_id in auto.retained_question_ids
    assert all(item.question.question_id != old.question_id for item in auto.saved)


@pytest.mark.parametrize("same_key", [True, False])
def test_refresh_concurrency_and_cas(refresh_case, same_key):
    store, old, _source, command = refresh_case
    engine, actor, questions, *_ = store
    barrier, key = Barrier(2), "race-refresh-" + uuid4().hex

    def run(index):
        barrier.wait(timeout=20)
        try:
            return questions.refresh_question_source(
                actor,
                command,
                idempotency_key=key if same_key else key + str(index),
            )
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, range(2)))
    if same_key:
        assert results[0].question == results[1].question
        assert sum(value.replayed for value in results) == 1
    else:
        assert sum(value == "KAKAO_ARCHIVE_PRECONDITION_FAILED" for value in results) == 1
    assert counts(engine, old.room_id)[0][:2] == (1, old.resource_version + 1)


def test_refresh_interruption_recovers_same_publication(refresh_case, monkeypatch):
    store, old, _source, command = refresh_case
    engine, actor, questions, _creation, sources, artifacts, *_ = store
    published = []

    def stop(*args, **kwargs):
        published.append(args[3].published.pointer)
        raise RuntimeError("synthetic stop after publication")

    monkeypatch.setattr(questions, "_adopt", stop)
    key = "refresh-recover-" + uuid4().hex
    with pytest.raises(RuntimeError, match="stop after"):
        questions.refresh_question_source(actor, command, idempotency_key=key)
    before = counts(engine, old.room_id)
    restarted = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    result = restarted.refresh_question_source(actor, command, idempotency_key=key)
    assert result.question.manifest == published[0]
    assert counts(engine, old.room_id)[1] == before[1]


def test_refresh_other_origin_rejected(refresh_case):
    store, old, _source, command = refresh_case
    engine, actor, questions, *_ = store
    before = counts(engine, old.room_id)
    with pytest.raises(KakaoArchiveError, match="SELECTION_INVALID"):
        questions.refresh_question_source(
            actor,
            command.model_copy(update={"candidate_ordinal": 2}),
            idempotency_key="wrong-origin-" + uuid4().hex,
        )
    assert counts(engine, old.room_id)[0][:2] == before[0][:2]


@pytest.mark.parametrize("cause", ["logout", "disable", "mapping"])
def test_refresh_current_permission_and_mapping_cannot_be_bypassed(refresh_case, cause):
    store, old, _source, command = refresh_case
    engine, actor, questions, *_ = store
    if cause == "mapping":
        rooms = KakaoRoomService(engine)
        room = rooms.get_room(actor, command.source_binding_id, command.room_id)
        _, mapping = student_and_map(engine, actor, room)
        rooms.command_room(
            actor,
            command.source_binding_id,
            command.room_id,
            mapping,
            idempotency_key="move-room-" + uuid4().hex,
        )
    else:
        with Session(engine) as session, session.begin():
            if cause == "logout":
                session.get(ApiSessionRecord, actor.session_id).revoked_at = datetime.now(UTC)
            else:
                session.get(OperatorRecord, actor.operator_id).status = "DISABLED"
    before = counts(engine, old.room_id)
    with pytest.raises(KakaoArchiveError):
        questions.refresh_question_source(actor, command, idempotency_key="denied-" + uuid4().hex)
    assert counts(engine, old.room_id) == before


def test_background_collection_cannot_refresh_manual_revision(question_store, source_store):
    store = question_store
    engine, _actor, questions, creation, *_ = store
    access = synthetic_access(store)
    first, _ = create_question(store)
    source = late_source(store, source_store)
    command = refresh_command(
        first.question, source.resolution.source_revision_id, creation.expected_mapping_revision_id
    )
    before = counts(engine, command.room_id)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        questions.refresh_question_source(
            access, command, idempotency_key="not-delegated-" + uuid4().hex
        )
    assert counts(engine, command.room_id) == before


def test_recomposed_question_cannot_be_refreshed_or_resurrected(question_store):
    engine, actor, questions, creation, *_ = question_store
    composer, split, old = setup_case(question_store)
    composer.compose_questions(actor, split, idempotency_key="split-before-refresh-" + uuid4().hex)
    command = refresh_command(
        old, creation.source_revision_id, creation.expected_mapping_revision_id
    )
    before = counts(engine, old.room_id)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        questions.refresh_question_source(
            actor, command, idempotency_key="superseded-" + uuid4().hex
        )
    assert counts(engine, old.room_id) == before


def test_manual_edit_during_refresh_publication_wins(refresh_case, monkeypatch):
    store, old, _source, command = refresh_case
    engine, actor, questions, *_ = store
    adopt, manual = questions._adopt, []

    def interleave(*args, **kwargs):
        if isinstance(args[1], KakaoQuestionSourceRefresh) and not manual:
            manual.append(
                questions.change_question(
                    actor,
                    change_command(old, confirm=False),
                    idempotency_key="manual-wins-" + uuid4().hex,
                ).question
            )
        return adopt(*args, **kwargs)

    monkeypatch.setattr(questions, "_adopt", interleave)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        questions.refresh_question_source(actor, command, idempotency_key="late-cas-" + uuid4().hex)
    assert questions.list_questions(actor, old.source_binding_id).items == (manual[0],)
    assert manual[0].review_state == "EXCLUDED"
    assert counts(engine, old.room_id)[0][:2] == (1, old.resource_version + 1)


def test_parent_manifest_unavailability_at_adoption_is_not_ignored(refresh_case, monkeypatch):
    import eom_catalog_service.kakao_question_service as owner_module

    store, old, _source, command = refresh_case
    engine, actor, questions, *_ = store
    adopt, validate = questions._adopt, owner_module.validate_source_pointer_metadata_batch
    adopting = False

    def unavailable(session, pointers):
        if adopting and old.manifest in pointers:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID")
        return validate(session, pointers)

    def withdrawn(*args, **kwargs):
        nonlocal adopting
        adopting = True
        return adopt(*args, **kwargs)

    # Inject an unavailable metadata read, never mutate an approved immutable row
    # or disable its database protection to manufacture a late negative case.
    monkeypatch.setattr(owner_module, "validate_source_pointer_metadata_batch", unavailable)
    monkeypatch.setattr(questions, "_adopt", withdrawn)
    with pytest.raises(KakaoArchiveError, match="ADMISSION_EVIDENCE_INVALID"):
        questions.refresh_question_source(
            actor, command, idempotency_key="parent-withdrawn-" + uuid4().hex
        )
    with Session(engine) as session:
        assert (
            session.get(KakaoQuestionRecord, old.question_id).current_revision_id
            == old.question_revision_id
        )
    assert counts(engine, old.room_id)[0][:2] == (1, old.resource_version)
