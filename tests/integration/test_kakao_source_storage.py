"""Guarded disposable PostgreSQL and local Artifact storage, never live source authority."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_source import SOURCE_RESOLUTION_REF
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_question_editing import question_from_candidate
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_catalog_service.kakao_source_models import (
    KakaoSourceCommandRecord,
    KakaoSourceHeadRecord,
    KakaoSourceRevisionRecord,
)
from eom_catalog_service.kakao_source_pointers import validate_source_pointer_metadata_batch
from eom_catalog_service.kakao_source_service import KakaoSourceService, source_admission_pointers
from eom_identifiers import sha256_bytes
from eom_identity_service.models import ApiSessionRecord
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_catalog_artifact_created_recovery import _settings
from tests.integration.test_kakao_archive_storage import create, make_actor
from tests.integration.test_kakao_room_storage import admit
from tests.unit.test_kakao_source_admission import source_case

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def source_store(creative_engine, tmp_path):
    actor = make_actor(creative_engine)
    bindings = KakaoArchiveService(creative_engine)
    binding = create(bindings, actor).binding
    room, _ = admit(creative_engine, (actor, binding, KakaoRoomService(creative_engine)))
    artifacts = CatalogArtifactService(creative_engine, _settings(tmp_path))
    allowed = {}
    calls = []

    def authority(session, proposed_actor, admission):
        assert session.in_transaction()
        calls.append(admission.authority.attempt_id)
        if (
            proposed_actor.operator_id != actor.operator_id
            or allowed.get(admission.authority.attempt_id) != admission
        ):
            raise PermissionError("synthetic owner revoked")

    service = KakaoSourceService(creative_engine, artifacts=artifacts, authorize_capture=authority)

    def prepare(*, previous=None, texts=("private question", "private question"), room_id=None):
        counter = 0

        def publish(name, payload, schema, media):
            nonlocal counter
            counter += 1
            path = tmp_path / (uuid4().hex + "-input")
            path.write_bytes(payload)
            result = artifacts.commit_file_set(
                files={name: path},
                primary_file=name,
                artifact_type="test-kakao-source-input",
                idempotency_key="source-input-" + uuid4().hex,
                request={"fixture": counter},
                result={},
                file_metadata={name: {"schema_ref": schema, "media_type": media}},
                expected_file_sha256={name: sha256_bytes(payload)},
            )
            return ArtifactMemberPointer(
                artifact_id=result.artifact_id,
                artifact_revision_id=result.revision_id,
                member_path=name,
                schema_ref=schema,
                media_type=media,
                sha256=result.content_hash,
            )

        admission, data, _ = source_case(
            binding=binding.source_binding_id,
            room=room_id or room.room.room_id,
            previous=previous,
            texts=texts,
            publish=publish,
        )
        allowed[admission.authority.attempt_id] = admission
        return admission, data

    return creative_engine, actor, binding, service, artifacts, allowed, calls, prepare


def accepted(store, *, key=None, previous=None, texts=("private question", "private question")):
    _, actor, _, service, _, _, _, prepare = store
    value, _ = prepare(previous=previous, texts=texts)
    key = key or "source-admit-" + uuid4().hex
    return service.admit_source(actor, value, idempotency_key=key), value, key


def test_source_admission_exact_replay_read_and_metadata_only(source_store):
    engine, actor, binding, service, _, _, calls, _ = source_store
    first, value, key = accepted(source_store)
    again = service.admit_source(actor, value, idempotency_key=key)
    assert (
        again.replayed and again.resolution == first.resolution and again.manifest == first.manifest
    )
    read = service.get_source(
        actor,
        binding.source_binding_id,
        value.room_id,
        source_revision_id=first.resolution.source_revision_id,
    )
    assert read.resolution == first.resolution
    assert len({row.occurrence_id for row in read.resolution.rows}) == 2
    assert len(calls) >= 4
    with Session(engine) as session:
        row = session.get(KakaoSourceRevisionRecord, first.resolution.source_revision_id)
        command = session.get(KakaoSourceCommandRecord, first.resolution.command_id)
        assert command.state == "COMPLETED"
        assert session.get(KakaoSourceHeadRecord, value.room_id).resource_version == 1
        for record in (row, command):
            stored = {
                column.name: getattr(record, column.name) for column in record.__table__.columns
            }
            assert "private question" not in json.dumps(stored, default=str)
            assert not any(isinstance(item, (bytes, dict, list)) for item in stored.values())
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRecord)
                .where(ArtifactRecord.artifact_type == "kakao-source-resolution")
            )
            >= 1
        )


def test_source_same_key_concurrency_accepts_one_revision_and_publication(source_store):
    engine, actor, _, service, _, _, _, prepare = source_store
    value, _ = prepare()
    key = "source-concurrent-" + uuid4().hex
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=15)
        return service.admit_source(actor, value, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: run(), range(2)))
    assert first.resolution == second.resolution
    assert first.manifest == second.manifest
    assert first.publication_job_id == second.publication_job_id
    assert sum(item.replayed for item in (first, second)) == 1
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoSourceRevisionRecord)
                .where(KakaoSourceRevisionRecord.room_id == value.room_id)
            )
            == 1
        )


def test_interruption_after_artifact_publication_recovers_same_reserved_identity(
    source_store, monkeypatch
):
    engine, actor, _, service, _, _, _, prepare = source_store
    value, _ = prepare()
    key = "source-interrupt-" + uuid4().hex
    adopt = service._adopt

    def stopped(*args, **kwargs):
        raise RuntimeError("synthetic stop after immutable publication")

    monkeypatch.setattr(service, "_adopt", stopped)
    with pytest.raises(RuntimeError, match="synthetic stop"):
        service.admit_source(actor, value, idempotency_key=key)
    with Session(engine) as session:
        reserved = session.scalar(
            select(KakaoSourceCommandRecord).where(KakaoSourceCommandRecord.idempotency_key == key)
        )
        command_id, revision_id = reserved.command_id, reserved.source_revision_id
        assert reserved.state == "RESERVED"
        assert session.get(KakaoSourceHeadRecord, value.room_id).resource_version == 0
        publications = tuple(
            session.scalars(
                select(ArtifactRevisionRecord)
                .join(
                    ArtifactRecord,
                    ArtifactRecord.logical_artifact_id
                    == ArtifactRevisionRecord.logical_artifact_id,
                )
                .where(ArtifactRecord.artifact_type == "kakao-source-resolution")
            )
        )
        existing_ids = {row.revision_id for row in publications}
    monkeypatch.setattr(service, "_adopt", adopt)
    recovered = service.admit_source(actor, value, idempotency_key=key)
    assert recovered.resolution.command_id == command_id
    assert recovered.resolution.source_revision_id == revision_id
    assert recovered.manifest.artifact_revision_id in existing_ids


def test_competing_source_cas_never_overwrites_first_revision(source_store, monkeypatch):
    _, actor, _, service, _, _, _, prepare = source_store
    first, _ = prepare()
    second, _ = prepare(texts=("different observation",))
    barrier = Barrier(2)
    inputs = service._inputs

    def overlap(value):
        result = inputs(value)
        barrier.wait(timeout=30)
        return result

    monkeypatch.setattr(service, "_inputs", overlap)

    def run(value):
        try:
            return service.admit_source(actor, value, idempotency_key="cas-" + uuid4().hex)
        except KakaoArchiveError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (first, second)))
    assert sum(isinstance(item, str) for item in results) == 1
    assert "KAKAO_ARCHIVE_PRECONDITION_FAILED" in results


def test_successor_reuses_occurrences_and_old_revision_read_stays_exact(source_store):
    _, actor, binding, service, _, _, _, _ = source_store
    first, value, _ = accepted(source_store)
    second, _, _ = accepted(source_store, previous=first.resolution)
    assert second.resolution.resource_version == 2
    assert [r.occurrence_id for r in first.resolution.rows] == [
        r.occurrence_id for r in second.resolution.rows
    ]
    assert (
        service.get_source(
            actor,
            binding.source_binding_id,
            value.room_id,
            source_revision_id=first.resolution.source_revision_id,
        ).resolution
        == first.resolution
    )
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        service.get_source(
            actor,
            binding.source_binding_id,
            value.room_id,
            source_revision_id="kakaosourcerev_" + uuid4().hex,
        )


@pytest.mark.parametrize(
    "fault",
    [
        "other_owner",
        "expired",
        "capture_revoked",
        "binding_retired",
        "same_key_changed",
        "different_key_same_attempt",
    ],
)
def test_source_replay_and_read_recheck_current_authority(source_store, fault):
    engine, actor, binding, service, _, allowed, _, prepare = source_store
    first, value, key = accepted(source_store)
    if fault == "other_owner":
        actor = make_actor(engine)
    elif fault == "expired":
        with Session(engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == actor.session_id)
                .values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
    elif fault == "capture_revoked":
        allowed.clear()
    elif fault == "binding_retired":
        KakaoArchiveService(engine).command_binding(
            actor,
            binding.source_binding_id,
            KakaoBindingRetire(
                expected_resource_version=binding.resource_version,
                parent_policy_revision_id=binding.policy_revision.policy_revision_id,
            ),
            idempotency_key="retire-" + uuid4().hex,
        )
    elif fault == "same_key_changed":
        value, _ = prepare(texts=("other body",))
    else:
        key = "new-key-" + uuid4().hex
    with pytest.raises(KakaoArchiveError):
        service.admit_source(actor, value, idempotency_key=key)
    if fault in {"other_owner", "expired", "binding_retired"}:
        with pytest.raises(KakaoArchiveError):
            service.get_source(
                actor,
                binding.source_binding_id,
                value.room_id,
                source_revision_id=first.resolution.source_revision_id,
            )


def test_metadata_validation_batches_pointers_and_fails_dangling(source_store):
    engine, _, _, _, _, _, _, prepare = source_store
    value, _ = prepare()
    statements = []

    def listen(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", listen)
    try:
        with Session(engine) as session, session.begin():
            pointers = source_admission_pointers(value)
            validate_source_pointer_metadata_batch(session, pointers * 5)
        assert len(statements) == 1
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    missing = value.normalization.model_copy(update={"artifact_revision_id": "rev_" + uuid4().hex})
    with Session(engine) as session, session.begin(), pytest.raises(KakaoArchiveError):
        validate_source_pointer_metadata_batch(session, (missing,))


@pytest.mark.parametrize("kind", ["source", "command"])
def test_accepted_source_and_command_are_database_immutable(source_store, kind):
    engine, _, _, _, _, _, _, _ = source_store
    first, _, _ = accepted(source_store)
    table, column, value = (
        ("kakao_source_revisions", "source_revision_id", first.resolution.source_revision_id)
        if kind == "source"
        else ("kakao_source_commands", "command_id", first.resolution.command_id)
    )
    with Session(engine) as session, session.begin(), pytest.raises(DBAPIError):
        session.execute(
            text(f"DELETE FROM {table} WHERE {column} = :identity"), {"identity": value}
        )


def test_no_arbitrary_capture_authority_or_public_latest(source_store):
    engine, _, _, _, artifacts, _, _, _ = source_store
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        KakaoSourceService(engine, artifacts=artifacts, authorize_capture=None)
    assert SOURCE_RESOLUTION_REF.endswith("source-resolution-v1/1.0")


def test_reserved_command_cannot_complete_with_null_timestamp(source_store):
    engine, actor, _, service, _, _, _, prepare = source_store
    admission, _ = prepare()
    reserved = service._reserve(actor, admission, "reserved-null-check-" + uuid4().hex)
    with (
        Session(engine) as session,
        session.begin(),
        pytest.raises(DBAPIError, match="ck_kakao_source_command_state"),
    ):
        session.execute(
            update(KakaoSourceCommandRecord)
            .where(KakaoSourceCommandRecord.command_id == reserved.command_id)
            .values(state="COMPLETED", completed_at=None)
        )


def test_accepted_source_resolves_once_into_existing_question_rules(source_store, monkeypatch):
    _, actor, binding, service, _, _, _, _ = source_store
    first, admission, _ = accepted(source_store)
    read = service._read
    calls = []

    def observed_read(pointer, *, limit):
        calls.append(pointer)
        return read(pointer, limit=limit)

    monkeypatch.setattr(service, "_read", observed_read)
    resolved = service.resolve_question_source(
        actor,
        binding.source_binding_id,
        admission.room_id,
        source_revision_id=first.resolution.source_revision_id,
    )
    assert calls.count(admission.normalization) == 1
    assert resolved.occurrence_ids == {
        row.row_ordinal: row.occurrence_id for row in first.resolution.rows
    }
    candidate = resolved.candidates[1]
    question = question_from_candidate(
        resolved,
        candidate,
        question_id="kakaoquestion_" + uuid4().hex,
        question_revision_id="kakaoquestionrev_" + uuid4().hex,
        student=None,
        actor_id=actor.operator_id,
        created_at=datetime.now(UTC),
    )
    assert question.review_state == "UNREVIEWED" and question.student is None
    assert len(question.ordered_blocks) == 2
    assert question.sources[0].pointer == admission.normalization
    assert (
        question.ordered_blocks[0].source_occurrence_id
        != question.ordered_blocks[1].source_occurrence_id
    )


def test_resolver_current_auth_after_normalization_io(source_store, monkeypatch):
    engine, actor, binding, service, _, _, _, _ = source_store
    first, admission, _ = accepted(source_store)
    read = service._read

    def revoke_after_read(pointer, *, limit):
        raw = read(pointer, limit=limit)
        if pointer == admission.normalization:
            with Session(engine) as session, session.begin():
                session.execute(
                    update(ApiSessionRecord)
                    .where(ApiSessionRecord.api_session_id == actor.session_id)
                    .values(revoked_at=datetime.now(UTC))
                )
        return raw

    monkeypatch.setattr(service, "_read", revoke_after_read)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.resolve_question_source(
            actor,
            binding.source_binding_id,
            admission.room_id,
            source_revision_id=first.resolution.source_revision_id,
        )


def test_resolver_does_not_substitute_latest_or_another_owner(source_store):
    engine, actor, binding, service, _, _, _, _ = source_store
    first, admission, _ = accepted(source_store)
    for acting, revision in (
        (actor, "kakaosourcerev_" + uuid4().hex),
        (make_actor(engine), first.resolution.source_revision_id),
    ):
        with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
            service.resolve_question_source(
                acting, binding.source_binding_id, admission.room_id, source_revision_id=revision
            )


def test_resolver_rejects_corrupt_pinned_normalization_without_exposing_body(
    source_store, monkeypatch
):
    _, actor, binding, service, _, _, _, _ = source_store
    first, admission, _ = accepted(source_store)
    read = service._read

    def wrong_payload(pointer, *, limit):
        raw = read(pointer, limit=limit)
        if pointer == admission.normalization:
            value = json.loads(raw)
            value["room_id"] = "kakaoroom_" + uuid4().hex
            return json.dumps(value).encode()
        return raw

    monkeypatch.setattr(service, "_read", wrong_payload)
    with pytest.raises(KakaoArchiveError, match="STORED_SOURCE_INVALID") as error:
        service.resolve_question_source(
            actor,
            binding.source_binding_id,
            admission.room_id,
            source_revision_id=first.resolution.source_revision_id,
        )
    assert "private question" not in str(error.value)
