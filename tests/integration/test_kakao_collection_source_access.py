"""Accepted-run authorization in disposable PG; no login bypass or real Kakao I/O."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_models import KakaoChannelBindingRecord
from eom_catalog_service.kakao_collection_attempt_models import KakaoCollectionAttemptRecord
from eom_catalog_service.kakao_collection_attempt_service import KakaoCollectionAttemptService
from eom_catalog_service.kakao_collection_models import KakaoCollectionRunRecord as Run
from eom_catalog_service.kakao_collection_models import KakaoCollectionTaskRecord as Task
from eom_catalog_service.kakao_room_models import KakaoRoomRecord
from eom_catalog_service.kakao_source_service import KakaoSourceService
from eom_identifiers import sha256_bytes
from eom_identity_service.models import (
    ApiSessionRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_operator_identity import PermissionKey
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tests.integration.test_kakao_collection_attempt_storage import attempt as attempt
from tests.integration.test_kakao_collection_attempt_storage import browser as browser
from tests.integration.test_kakao_collection_attempt_storage import cap as cap
from tests.integration.test_kakao_collection_attempt_storage import collection as collection
from tests.integration.test_kakao_collection_attempt_storage import h as h
from tests.integration.test_kakao_collection_attempt_storage import intake as intake
from tests.integration.test_kakao_collection_attempt_storage import (
    photo,
    result_input,
    source_input,
)
from tests.unit import test_kakao_source_admission as source_fixtures

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def accepted_access(attempt, **kwargs):
    data = result_input(attempt, **kwargs)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    return data, attempt.service.accepted_source_access(data.reserved.attempt_id)


def publish_source(attempt, data, access, *, key, read=None, service=None):
    return (service or attempt.service).publish_and_admit_capture_source(
        access,
        data.reserved.attempt_id,
        read_member=read or (lambda member: data.members[member.relative_path]),
        idempotency_key=key,
        expected_source_revision_id=None,
        expected_resource_version=0,
    )


def expire_session(attempt, reason):
    with Session(attempt.engine) as session, session.begin():
        row = session.get(ApiSessionRecord, attempt.actor.session_id)
        if reason == "logout":
            row.revoked_at = datetime.now(UTC)
            row.revoke_reason = "synthetic normal logout"
        else:
            setattr(row, reason, datetime.now(UTC) - timedelta(seconds=1))


def counts(attempt):
    with Session(attempt.engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (ApiSessionRecord, ArtifactRevisionRecord)
        )


@pytest.mark.parametrize("expiry", ["logout", "idle_expires_at", "absolute_expires_at"])
def test_accepted_work_finishes_without_extending_http_login(attempt, expiry):
    data, access = accepted_access(attempt, images=(photo(), photo()))
    expire_session(attempt, expiry)
    sessions_before, _ = counts(attempt)
    key = "background-source-" + uuid4().hex
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        publish_source(attempt, data, attempt.actor, key=key)
    result = publish_source(attempt, data, access, key=key)
    assert len(result.resolution.rows) == 2
    assert len({row.occurrence_id for row in result.resolution.rows}) == 2
    attached = result.resolution.admission.attachments
    assert len(attached) == 2 and attached[0].attachment_id != attached[1].attachment_id
    assert attached[0].original == attached[1].original
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
    assert counts(attempt)[0] == sessions_before
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        attempt.service._sources.get_source(
            attempt.actor,
            data.reserved.source_binding_id,
            data.reserved.room_id,
            source_revision_id=result.resolution.source_revision_id,
        )
    before_replay = counts(attempt)
    data.members.clear()
    replay = publish_source(
        attempt,
        data,
        access,
        key=key,
        read=lambda _m: pytest.fail("completed replay must not read worker workspace"),
    )
    assert replay.replayed and replay.resolution == result.resolution
    assert counts(attempt) == before_replay


def test_restarted_controller_recovers_committed_source_after_logout(attempt, monkeypatch):
    data, access = accepted_access(attempt)
    key = "background-recovery-" + uuid4().hex
    committed = []

    def stopped(_access, _attempt_id, source_revision_id):
        committed.append(source_revision_id)
        raise RuntimeError("synthetic controller stop after source commit")

    monkeypatch.setattr(attempt.service, "accept_source_revision", stopped)
    with pytest.raises(RuntimeError, match="after source commit"):
        publish_source(attempt, data, access, key=key)
    assert len(committed) == 1
    expire_session(attempt, "logout")
    restarted = KakaoCollectionAttemptService(
        attempt.engine,
        artifacts=attempt.artifacts,
        profile_id=attempt.service.profile_id,
        adapter_release_sha256=attempt.service.adapter_sha256,
    )
    access = restarted.accepted_source_access(data.reserved.attempt_id)
    before = counts(attempt)
    recovered = publish_source(
        attempt,
        data,
        access,
        key=key,
        service=restarted,
        read=lambda _m: pytest.fail("committed source recovery must not read local files"),
    )
    assert recovered.replayed and recovered.resolution.source_revision_id == committed[0]
    assert counts(attempt) == before
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
        assert session.get(KakaoCollectionAttemptRecord, data.reserved.attempt_id).state == (
            "RESULT_ACCEPTED"
        )


@pytest.mark.parametrize("cause", ["disabled", "password_reset", "role_revoked", "room", "binding"])
@pytest.mark.parametrize("published", [False, True])
def test_background_access_does_not_bypass_current_revocation(attempt, cause, published):
    data, access = accepted_access(attempt)
    key = "revoked-background-" + uuid4().hex
    if published:
        publish_source(attempt, data, access, key=key)
    with Session(attempt.engine) as session, session.begin():
        if cause == "disabled":
            session.get(OperatorRecord, access.owner_operator_id).status = "DISABLED"
        elif cause == "password_reset":
            session.get(OperatorRecord, access.owner_operator_id).must_change_password = True
        elif cause == "role_revoked":
            session.execute(
                update(OperatorRoleAssignmentRecord)
                .where(OperatorRoleAssignmentRecord.operator_id == access.owner_operator_id)
                .values(revoked_at=datetime.now(UTC))
            )
        elif cause == "room":
            session.get(KakaoRoomRecord, data.reserved.room_id).state = "RETIRED"
        else:
            session.get(
                KakaoChannelBindingRecord, data.reserved.source_binding_id
            ).state = "RETIRED"
    before = counts(attempt)
    with pytest.raises(KakaoArchiveError):
        publish_source(
            attempt,
            data,
            access,
            key=key,
            read=lambda _m: pytest.fail("revoked owner must fail before local I/O"),
        )
    assert counts(attempt) == before
    with pytest.raises(KakaoArchiveError):
        attempt.service.accepted_source_access(data.reserved.attempt_id)


def test_revocation_during_local_read_blocks_publication(attempt):
    data, access = accepted_access(attempt)
    before = counts(attempt)

    def read(member):
        with Session(attempt.engine) as session, session.begin():
            session.get(OperatorRecord, access.owner_operator_id).status = "DISABLED"
        return data.members[member.relative_path]

    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        publish_source(attempt, data, access, key="revoke-during-read-" + uuid4().hex, read=read)
    assert counts(attempt) == before
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"


@pytest.mark.parametrize("state", ["unaccepted", "FAILED", "PAUSED", "CANCELLED"])
def test_only_successful_accepted_capture_can_obtain_access(attempt, state):
    data = result_input(
        attempt,
        status="PARTIAL" if state == "unaccepted" else state,
        error="UI_CHANGED" if state == "FAILED" else None,
    )
    if state != "unaccepted":
        attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        attempt.service.accepted_source_access(data.reserved.attempt_id)
    with Session(attempt.engine) as session:
        row = session.get(KakaoCollectionAttemptRecord, data.reserved.attempt_id)
        assert row.result_status == (None if state == "unaccepted" else state)


@pytest.mark.parametrize("change", ["owner", "attempt", "fence", "profile"])
def test_background_principal_is_exact_accepted_identity_not_an_authority_claim(attempt, change):
    data, access = accepted_access(attempt)
    if change == "owner":
        access = replace(access, owner_operator_id="operator_" + "f" * 32)
    else:
        field, value = {
            "attempt": ("attempt_id", "kakaoattempt_" + "f" * 32),
            "fence": ("fence", access.attempt.fence + 1),
            "profile": ("profile_id", "kakaoprofile_" + "f" * 32),
        }[change]
        access = replace(access, attempt=access.attempt.model_copy(update={field: value}))
    with pytest.raises(KakaoArchiveError):
        publish_source(
            attempt,
            data,
            access,
            key="false-background-" + uuid4().hex,
            read=lambda _m: pytest.fail("unaccepted scope must not read local files"),
        )


def test_background_scope_cannot_authorize_another_room_permission_or_service(attempt):
    data, access = accepted_access(attempt)
    with Session(attempt.engine) as session:
        with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
            access.authorize_operator(session, PermissionKey.CODEX_ACCOUNT_MANAGE)
        with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
            access.authorize_room(
                session,
                data.reserved.source_binding_id,
                "kakaoroom_" + "f" * 32,
                PermissionKey.KAKAO_ARCHIVE_COLLECT,
                lock=False,
            )
    other = KakaoCollectionAttemptService(
        attempt.engine,
        artifacts=attempt.artifacts,
        profile_id=attempt.service.profile_id,
        adapter_release_sha256=attempt.service.adapter_sha256,
    )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        publish_source(attempt, data, access, service=other, key="other-service-" + uuid4().hex)


def test_background_source_admission_checks_actual_capture_authority(attempt):
    data, access = accepted_access(attempt)
    admission = source_input(attempt, data)
    admission = admission.model_copy(
        update={
            "authority": admission.authority.model_copy(update={"fence": access.attempt.fence + 1})
        }
    )
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        attempt.service.admit_capture_source(
            access, admission, idempotency_key="false-capture-" + uuid4().hex
        )
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"


def test_background_read_cannot_return_another_capture_in_the_same_room(attempt, monkeypatch):
    data, access = accepted_access(attempt)
    first = publish_source(attempt, data, access, key="first-source-" + uuid4().hex)
    # Publish a second anonymous fixture through the normal source store, not raw
    # DB inserts. Its synthetic capture authority is unrelated to the real attempt.
    monkeypatch.setattr(source_fixtures, "NOW", datetime.now(UTC))

    def publish(name, payload, schema, media):
        path = attempt.tmp / (uuid4().hex + "-input")
        path.write_bytes(payload)
        result = attempt.artifacts.commit_file_set(
            files={name: path},
            primary_file=name,
            artifact_type="test-kakao-other-source",
            idempotency_key="other-source-input-" + uuid4().hex,
            request={"synthetic": True},
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

    admission, _, _ = source_fixtures.source_case(
        binding=data.reserved.source_binding_id,
        room=data.reserved.room_id,
        previous=first.resolution,
        publish=publish,
    )
    fixture_store = KakaoSourceService(
        attempt.engine, artifacts=attempt.artifacts, authorize_capture=lambda *_: None
    )
    other = fixture_store.admit_source(
        attempt.actor, admission, idempotency_key="second-source-" + uuid4().hex
    )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        attempt.service._sources.get_source(
            access,
            data.reserved.source_binding_id,
            data.reserved.room_id,
            source_revision_id=other.resolution.source_revision_id,
        )
    # Broad authenticated room read remains distinct from narrow background access.
    assert (
        attempt.service._sources.get_source(
            attempt.actor,
            data.reserved.source_binding_id,
            data.reserved.room_id,
            source_revision_id=other.resolution.source_revision_id,
        ).resolution
        == other.resolution
    )


def test_concurrent_background_calls_adopt_one_source_without_session_creation(attempt):
    data, access = accepted_access(attempt)
    expire_session(attempt, "logout")
    key = "background-concurrent-" + uuid4().hex
    before_sessions, _ = counts(attempt)
    barrier = Barrier(2)

    def call(_):
        barrier.wait(timeout=15)
        return publish_source(attempt, data, access, key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(call, range(2)))
    assert first.resolution == second.resolution and first.manifest == second.manifest
    assert counts(attempt)[0] == before_sessions
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"


@pytest.mark.parametrize("published", [False, True])
def test_terminal_run_allows_exact_completed_replay_not_new_source(attempt, published):
    data, access = accepted_access(attempt)
    key = "terminal-source-" + uuid4().hex
    result = publish_source(attempt, data, access, key=key) if published else None
    # Synthetic terminal observation: only the disposable DB is mutated.
    with Session(attempt.engine) as session, session.begin():
        row = session.get(Run, data.reserved.run_id)
        row.state = "PARTIAL"
        row.resource_version += 1
    access = attempt.service.accepted_source_access(data.reserved.attempt_id)
    before = counts(attempt)
    if published:
        replay = publish_source(
            attempt, data, access, key=key, read=lambda _m: pytest.fail("terminal replay read")
        )
        assert replay.replayed and replay.resolution == result.resolution
    else:
        with pytest.raises(KakaoArchiveError, match="COLLECTION_TERMINAL"):
            publish_source(
                attempt, data, access, key=key, read=lambda _m: pytest.fail("terminal new read")
            )
    assert counts(attempt) == before
