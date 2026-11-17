"""Candidate continuation through real owners in disposable PG, not live Kakao."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_source import KakaoSourceAdmission
from eom_catalog_service.kakao_archive_authorization import (
    KakaoArchiveError,
    authorize_kakao_current_operator,
    read_owned_kakao_room_scope,
)
from eom_catalog_service.kakao_question_models import (
    KakaoQuestionCommandRecord,
    KakaoQuestionRecord,
    KakaoQuestionRevisionRecord,
)
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_catalog_service.kakao_source_access import KakaoSourcePrincipal
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_operator_identity import PermissionKey
from eom_orchestrator.models import ArtifactRevisionRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_kakao_question_composition_storage import setup_case
from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_room_storage import student_and_map
from tests.integration.test_kakao_source_storage import source_store as source_store

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def save(store, *, principal: KakaoSourcePrincipal | None = None, **kwargs):
    _, actor, questions, command, *_ = store
    return questions.create_source_candidates(
        principal or actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
        **kwargs,
    )


def counts(engine, room_id):
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model).where(model.room_id == room_id))
            for model in (
                KakaoQuestionRecord,
                KakaoQuestionRevisionRecord,
                KakaoQuestionCommandRecord,
            )
        ), session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))


def test_autosave_uses_existing_question_owner_and_retains_completed_output(question_store):
    engine, actor, questions, command, *_ = question_store
    first = save(question_store)
    assert len(first.saved) == 1 and not first.saved[0].replayed
    assert first.next_candidate_ordinal is None and first.retained_question_ids == ()
    stored = first.saved[0].question
    assert stored.review_state == "UNREVIEWED"
    assert first.unresolved_rows == ()
    original = questions.get_question(
        actor,
        command.source_binding_id,
        command.room_id,
        stored.question_id,
        revision_id=stored.question_revision_id,
    )
    assert original.published.question.created_by == actor.operator_id
    before = counts(engine, command.room_id)
    again = save(question_store)
    assert not again.saved and again.retained_question_ids == (stored.question_id,)
    assert counts(engine, command.room_id) == before


@pytest.mark.parametrize("confirm", [True, False])
def test_manual_review_or_exclusion_is_not_overwritten(question_store, confirm):
    engine, actor, questions, command, *_ = question_store
    first, _ = create_question(question_store)
    changed = questions.change_question(
        actor,
        change_command(first.question, confirm=confirm),
        idempotency_key="manual-review-" + uuid4().hex,
    ).question
    before = counts(engine, command.room_id)
    result = save(question_store)
    assert result.saved == () and result.retained_question_ids == (changed.question_id,)
    assert questions.list_questions(actor, command.source_binding_id).items == (changed,)
    assert counts(engine, command.room_id) == before


def test_split_does_not_resurrect_original_candidate(question_store):
    engine, actor, questions, command, *_ = question_store
    composer, split, original = setup_case(question_store)
    parts = composer.compose_questions(actor, split, idempotency_key="manual-split-" + uuid4().hex)
    before = counts(engine, command.room_id)
    again = save(question_store)
    assert again.retained_question_ids == (original.question_id,) and not again.saved
    assert set(
        q.question_id for q in questions.list_questions(actor, command.source_binding_id).items
    ) == {q.question_id for q in parts.outputs}
    assert counts(engine, command.room_id) == before


def test_interruption_after_publication_recovers_same_question_and_artifact(
    question_store, monkeypatch
):
    engine, actor, questions, command, sources, artifacts, *_ = question_store
    published = []

    def stop(*args, **kwargs):
        published.append(args[3].published.pointer)
        raise RuntimeError("synthetic stop after question publication")

    monkeypatch.setattr(questions, "_adopt", stop)
    with pytest.raises(RuntimeError, match="stop after"):
        save(question_store)
    assert len(published) == 1
    before = counts(engine, command.room_id)
    restarted = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    result = restarted.create_source_candidates(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    )
    assert len(result.saved) == 1 and result.saved[0].question.manifest == published[0]
    assert counts(engine, command.room_id)[1] == before[1]
    assert counts(engine, command.room_id)[0] == (1, 1, 1)


@pytest.mark.parametrize("background", [False, True])
def test_two_controllers_do_not_duplicate_same_candidate(question_store, background):
    engine, _, _, command, *_ = question_store
    barrier = Barrier(2)
    access = synthetic_access(question_store) if background else None

    def run(_):
        barrier.wait(timeout=20)
        return save(question_store, principal=access)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, range(2)))
    ids = {q.question.question_id for page in results for q in page.saved} | {
        q for page in results for q in page.retained_question_ids
    }
    assert len(ids) == 1 and counts(engine, command.room_id)[0] == (1, 1, 1)


def test_manual_creation_wins_during_autosave_without_losing_review(question_store, monkeypatch):
    engine, actor, questions, command, *_ = question_store
    original = questions._create_question
    reviewed = []

    def interleave(*args, **kwargs):
        manual = original(actor, command, "manual-race-" + uuid4().hex)
        reviewed.append(
            questions.change_question(
                actor,
                change_command(manual.question, confirm=False),
                idempotency_key="exclude-race-" + uuid4().hex,
            ).question
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(questions, "_create_question", interleave)
    result = save(question_store)
    assert not result.saved and result.retained_question_ids == (reviewed[0].question_id,)
    assert questions.list_questions(actor, command.source_binding_id).items == (reviewed[0],)
    assert counts(engine, command.room_id)[0][:2] == (1, 2)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"after_candidate_ordinal": -1},
        {"after_candidate_ordinal": True},
    ],
)
def test_invalid_page_rejected_before_source_io(question_store, monkeypatch, kwargs):
    sources = question_store[4]
    monkeypatch.setattr(
        sources, "resolve_question_source_context", lambda *a, **k: pytest.fail("source I/O")
    )
    with pytest.raises(KakaoArchiveError, match="REQUEST_INVALID"):
        save(question_store, **kwargs)


def test_multiple_candidates_page_recollection_and_reconstruction(source_store, monkeypatch):
    engine, actor, binding, sources, artifacts, _, _, prepare = source_store
    texts = (
        "question one",
        "reply one",
        "question two",
        "reply two",
        "question three",
        "reply three",
    )
    roles = ("student", "staff") * 3
    admission, _ = prepare(texts=texts, roles=roles)
    accepted = sources.admit_source(
        actor, admission, idempotency_key="candidate-input-" + uuid4().hex
    )
    rooms = KakaoRoomService(engine)
    room = rooms.get_room(actor, binding.source_binding_id, admission.room_id)
    _, mapping = student_and_map(engine, actor, room)
    rooms.command_room(
        actor,
        binding.source_binding_id,
        room.room_id,
        mapping,
        idempotency_key="map-" + uuid4().hex,
    )
    questions = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    reads = []
    resolve = sources.resolve_question_source_context

    def observed(*args, **kwargs):
        reads.append(kwargs["source_revision_id"])
        return resolve(*args, **kwargs)

    monkeypatch.setattr(sources, "resolve_question_source_context", observed)

    def run(service, source_id, after=0):
        before = len(reads)
        page = service.create_source_candidates(
            actor,
            binding.source_binding_id,
            room.room_id,
            source_revision_id=source_id,
            after_candidate_ordinal=after,
            limit=2,
        )
        assert len(reads) == before + 1
        return page

    first = run(questions, accepted.resolution.source_revision_id)
    assert len(first.saved) == 2 and first.next_candidate_ordinal == 2
    restarted = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    last = run(restarted, accepted.resolution.source_revision_id, after=2)
    assert len(last.saved) == 1 and last.next_candidate_ordinal is None
    before = counts(engine, room.room_id)
    replay = run(restarted, accepted.resolution.source_revision_id)
    assert not replay.saved and len(replay.retained_question_ids) == 2
    assert counts(engine, room.room_id) == before
    successor, _ = prepare(
        previous=accepted.resolution, texts=(*texts, "question four"), roles=(*roles, "student")
    )
    new_source = sources.admit_source(
        actor, successor, idempotency_key="recollection-" + uuid4().hex
    )
    page = run(restarted, new_source.resolution.source_revision_id)
    assert not page.saved and len(page.retained_question_ids) == 2
    page = run(restarted, new_source.resolution.source_revision_id, after=2)
    assert len(page.saved) == 1 and len(page.retained_question_ids) == 1
    assert counts(engine, room.room_id)[0][:2] == (4, 4)


def test_unknown_senders_are_reported_not_silently_treated_as_complete(source_store):
    engine, actor, binding, sources, artifacts, _, _, prepare = source_store
    admission, _ = prepare(roles=("unknown", "unknown"))
    source = sources.admit_source(actor, admission, idempotency_key="unknown-" + uuid4().hex)
    questions = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    result = questions.create_source_candidates(
        actor,
        binding.source_binding_id,
        admission.room_id,
        source_revision_id=source.resolution.source_revision_id,
    )
    assert result.saved == () and result.retained_question_ids == ()
    assert result.unresolved_rows == (1, 2)
    assert result.next_candidate_ordinal is None
    assert counts(engine, admission.room_id)[0] == (0, 0, 0)


@dataclass(frozen=True)
class SyntheticAcceptedAccess:
    """Known-source fixture authority; not a real collection acceptance claim."""

    owner: str
    admission: KakaoSourceAdmission

    def authorize_operator(self, session, permission):
        return authorize_kakao_current_operator(
            session,
            operator_id=self.owner,
            permission=permission,
            admin_only=True,
        )

    def authorize_room(self, session, binding, room, permission, *, lock):
        if (binding, room) != (self.admission.source_binding_id, self.admission.room_id):
            raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
        owner = self.authorize_operator(session, permission)
        return owner, read_owned_kakao_room_scope(session, owner, binding, room, lock=lock)

    def authorize_capture(self, session, admission):
        self.authorize_operator(session, PermissionKey.KAKAO_ARCHIVE_READ)
        if admission != self.admission:
            raise KakaoArchiveError("KAKAO_ARCHIVE_ADMISSION_AUTHORITY_REQUIRED")


def synthetic_access(store):
    _engine, actor, _, command, sources, *_ = store
    accepted = sources.get_source(
        actor,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    )
    return SyntheticAcceptedAccess(actor.operator_id, accepted.resolution.admission)


def test_scoped_background_saves_after_logout_without_new_api_session(question_store):
    engine, actor, questions, command, *_ = question_store
    access = synthetic_access(question_store)
    with Session(engine) as session, session.begin():
        session.get(ApiSessionRecord, actor.session_id).revoked_at = datetime.now(UTC)
        sessions_before = session.scalar(select(func.count()).select_from(ApiSessionRecord))
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        save(question_store)
    result = save(question_store, principal=access)
    assert len(result.saved) == 1
    assert save(question_store, principal=access).retained_question_ids == (
        result.saved[0].question.question_id,
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ApiSessionRecord)) == sessions_before
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        questions.change_question(
            access,
            change_command(result.saved[0].question),
            idempotency_key="not-delegated-" + uuid4().hex,
        )
    with pytest.raises(KakaoArchiveError):
        questions.list_questions(actor, command.source_binding_id)


def test_background_question_adoption_recovers_after_logout(question_store, monkeypatch):
    engine, actor, questions, command, sources, artifacts, *_ = question_store
    access = synthetic_access(question_store)
    published = []

    def stop(*args, **kwargs):
        published.append(args[3].published.pointer)
        raise RuntimeError("synthetic stop")

    monkeypatch.setattr(questions, "_adopt", stop)
    with pytest.raises(RuntimeError, match="synthetic stop"):
        save(question_store, principal=access)
    with Session(engine) as session, session.begin():
        session.get(ApiSessionRecord, actor.session_id).revoked_at = datetime.now(UTC)
    before = counts(engine, command.room_id)
    restarted = KakaoQuestionService(engine, artifacts=artifacts, sources=sources)
    recovered = restarted.create_source_candidates(
        access,
        command.source_binding_id,
        command.room_id,
        source_revision_id=command.source_revision_id,
    )
    assert recovered.saved[0].question.manifest == published[0]
    assert counts(engine, command.room_id)[1] == before[1]


def test_background_revocation_during_publication_prevents_adoption(question_store, monkeypatch):
    engine, actor, _questions, command, _sources, artifacts, *_ = question_store
    access = synthetic_access(question_store)
    commit = artifacts.commit_file_set

    def revoked(*args, **kwargs):
        result = commit(*args, **kwargs)
        with Session(engine) as session, session.begin():
            session.get(OperatorRecord, actor.operator_id).status = "DISABLED"
        return result

    monkeypatch.setattr(artifacts, "commit_file_set", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        save(question_store, principal=access)
    assert counts(engine, command.room_id)[0][:2] == (0, 0)
