"""Real guarded disposable DB and local staging/Artifact I/O, never a live account/NAS."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire, KakaoBindingUpdatePolicy
from eom_catalog_contracts.kakao_manual import KakaoManualEnd
from eom_catalog_contracts.kakao_room_intake import ConfirmKakaoManualRoom
from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_manual_models import KakaoManualSessionRecord
from eom_catalog_service.kakao_room_intake import KakaoRoomIntakeService
from eom_catalog_service.kakao_room_intake_models import KakaoManualChannelPinRecord
from eom_catalog_service.kakao_room_models import KakaoRoomRecord
from eom_catalog_service.kakao_room_service import KakaoRoomService
from eom_identifiers import canonical_json_bytes
from eom_identity_service.models import ApiSessionRecord
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadResult, ManualDownloadStart
from eom_kakao_archive_contracts.manual_observation import ManualPageObservation
from eom_kakao_archive_contracts.render import sha256
from eom_orchestrator.kakao_download_inputs import read_received_kakao_download
from eom_orchestrator.models import ArtifactRecord
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_catalog_artifact_created_recovery import _settings
from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_manual_storage import h as h

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def intake(h, tmp_path):
    current = h.ready()
    artifacts = CatalogArtifactService(h.engine, _settings(tmp_path))
    artifacts.settings.staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="kakao-room-intake-", dir=Path.home() / ".cache"
    ) as folder:
        root = Path(folder)
        root.chmod(0o2750)
        fence = ProfileFence(
            schema_version="kakao-profile-fence/1.0",
            profile_id=current.profile_id,
            browser_run_id=current.browser_run_id,
            fence_epoch=current.fence_epoch,
            mode="MANUAL",
        )
        run = root / fence.browser_run_id
        run.mkdir(mode=0o750)
        run.chmod(0o750)
        (run / "run.json").write_bytes(canonical_json_bytes(fence.model_dump(mode="json")))
        (run / "run.json").chmod(0o640)
        calls = []

        def read(expected, capture):
            calls.append(capture)
            return read_received_kakao_download(
                root=root,
                fence=expected,
                capture_id=capture,
                worker_uid=os.getuid(),
                control_gid=os.getgid(),
            )

        rooms = KakaoRoomService(h.engine)
        service = KakaoRoomIntakeService(
            h.engine, artifacts=artifacts, rooms=rooms, read_download=read
        )

        def prepare(channel="channel-one", room="room-one", **changes):
            capture = "kakaodownload_" + uuid4().hex
            directory = run / capture
            directory.mkdir(mode=0o750)
            directory.chmod(0o750)
            started = ManualDownloadStart(
                capture_id=capture,
                profile_id=fence.profile_id,
                browser_run_id=fence.browser_run_id,
                fence_epoch=fence.fence_epoch,
                page_instance_id="kakaopage_" + uuid4().hex,
                started_at=h.now + timedelta(milliseconds=1),
            )
            raw = b"synthetic captured bytes; no image-quality claim"
            result = ManualDownloadResult.model_validate(
                started.model_dump()
                | dict(
                    phase="RECEIVED",
                    completed_at=h.now + timedelta(milliseconds=3),
                    suggested_filename="same-name.bin",
                    member=dict(
                        relative_path="payload.bin", size_bytes=len(raw), sha256=sha256(raw)
                    ),
                    error_code=None,
                )
            )
            doc = dict(
                origin="https://business.kakao.com",
                path=f"/space/workspace/channel/{channel}/chats",
                truncated=False,
                nodes=[],
            )
            observation = ManualPageObservation.model_validate(
                dict(
                    **started.model_dump(exclude={"phase", "schema_version", "started_at"}),
                    observed_at=h.now + timedelta(milliseconds=2),
                    status="OBSERVED",
                    error_code=None,
                    target=dict(
                        kind="SAME_ORIGIN_PATH",
                        path=f"/api/profiles/{channel}/chats/{room}/logs/photo/image",
                    ),
                    document=doc,
                )
            )
            for name, value in {
                "started.json": canonical_json_bytes(started.model_dump(mode="json")),
                "result.json": canonical_json_bytes(result.model_dump(mode="json")),
                "payload.bin": raw,
                "page-observation.json": canonical_json_bytes(
                    observation.model_dump(mode="json", by_alias=True)
                ),
            }.items():
                (directory / name).write_bytes(value)
                (directory / name).chmod(0o640)
            return ConfirmKakaoManualRoom(
                source_binding_id=h.binding,
                manual_lease_id=current.lease_id,
                capture_id=capture,
                expected_channel_key=channel,
                expected_room_key=room,
                display_name="합성 관측 방",
                expected_binding_version=1,
                **changes,
            )

        yield SimpleNamespace(
            h=h,
            engine=h.engine,
            actor=h.actor,
            artifacts=artifacts,
            rooms=rooms,
            service=service,
            root=root,
            run=run,
            calls=calls,
            prepare=prepare,
            current=current,
            reader=read,
        )


def confirm(store, command=None, key=None):
    return store.service.confirm_room(
        store.actor, command or store.prepare(), idempotency_key=key or "manual-room-" + uuid4().hex
    )


def test_real_publication_owned_room_pin_and_exact_replay_without_local_staging(intake):
    command, key = intake.prepare(), "manual-room-" + uuid4().hex
    first = confirm(intake, command, key)
    assert (
        first.room.identity_level == "MANUAL_CONFIRMED" and first.room.mapping.state == "UNMAPPED"
    )
    assert not first.replayed
    calls = len(intake.calls)
    for path in (intake.run / command.capture_id).iterdir():
        path.unlink()
    (intake.run / command.capture_id).rmdir()
    second = confirm(intake, command, key)
    assert second.replayed and second.room == first.room and len(intake.calls) == calls
    with Session(intake.engine) as session:
        pin = session.get(KakaoManualChannelPinRecord, command.source_binding_id)
        assert pin is not None and pin.owner_operator_id == intake.actor.operator_id
        assert len(pin.__table__.columns) == 7


def test_same_named_rooms_are_not_deduplicated_by_name(intake):
    first = confirm(intake, intake.prepare(room="room-one"))
    second = confirm(intake, intake.prepare(room="room-two"))
    assert first.room.display_name == second.room.display_name
    assert first.room.room_id != second.room.room_id


def test_confirmation_provider_keys_must_match_received_download(intake):
    command = intake.prepare().model_copy(update={"expected_room_key": "wrong-room"})
    with pytest.raises(KakaoArchiveError, match="ROOM_IDENTITY_MISMATCH"):
        confirm(intake, command)
    with Session(intake.engine) as session:
        assert session.get(KakaoManualChannelPinRecord, intake.h.binding) is None


def test_one_binding_cannot_mix_provider_channels(intake):
    confirm(intake)
    with pytest.raises(KakaoArchiveError, match="CHANNEL_IDENTITY_MISMATCH"):
        confirm(intake, intake.prepare(channel="another-channel"))
    with Session(intake.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoRoomRecord)
                .where(KakaoRoomRecord.source_binding_id == intake.h.binding)
            )
            == 1
        )


def test_duplicate_request_concurrency_is_one_admission(intake):
    command, key, barrier = intake.prepare(), "manual-room-" + uuid4().hex, Barrier(3)

    def work(_):
        barrier.wait(timeout=10)
        return confirm(intake, command, key)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(work, range(3)))
    assert len({item.room.room_id for item in results}) == 1
    assert sum(not item.replayed for item in results) == 1


def test_same_key_other_body_is_conflict_not_second_room(intake):
    command, key = intake.prepare(), "manual-room-" + uuid4().hex
    first = confirm(intake, command, key)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        confirm(intake, command.model_copy(update={"display_name": "different"}), key)
    assert confirm(intake, command, key).room == first.room


def test_other_owner_denied_before_staging_read(intake):
    other = make_actor(intake.engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        intake.service.confirm_room(
            other, intake.prepare(), idempotency_key="foreign-" + uuid4().hex
        )
    assert not intake.calls


def test_current_identity_rechecked_after_file_read(intake):
    command = intake.prepare()

    def revoked(fence, capture):
        result = intake.reader(fence, capture)
        with Session(intake.engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == intake.actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        return result

    service = KakaoRoomIntakeService(
        intake.engine, artifacts=intake.artifacts, rooms=intake.rooms, read_download=revoked
    )
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        service.confirm_room(intake.actor, command, idempotency_key="revoked-" + uuid4().hex)
    with Session(intake.engine) as session:
        assert session.get(KakaoManualChannelPinRecord, intake.h.binding) is None


def test_channel_pin_is_immutable_and_has_no_large_content(intake):
    confirm(intake)
    for statement in (
        "UPDATE kakao_manual_channel_pins SET channel_key_sha256=channel_key_sha256 "
        "WHERE source_binding_id=:id",
        "DELETE FROM kakao_manual_channel_pins WHERE source_binding_id=:id",
    ):
        with pytest.raises(DBAPIError), Session(intake.engine) as session, session.begin():
            session.execute(text(statement), {"id": intake.h.binding})


def test_completed_replay_survives_later_policy_edit(intake):
    command, key = intake.prepare(), "policy-replay-" + uuid4().hex
    first = confirm(intake, command, key)
    bindings = KakaoArchiveService(intake.engine)
    original = bindings.get_binding(intake.actor, intake.h.binding)
    bindings.command_binding(
        intake.actor,
        intake.h.binding,
        KakaoBindingUpdatePolicy(
            parent_policy_revision_id=original.policy_revision.policy_revision_id,
            expected_resource_version=original.resource_version,
            policy=original.policy_revision.policy.model_copy(update={"interval_minutes": 120}),
        ),
        idempotency_key="policy-update-" + uuid4().hex,
    )
    assert confirm(intake, command, key).room == first.room


def test_first_adoption_rechecks_binding_version_after_read(intake):
    command = intake.prepare()

    def changed(fence, capture):
        result = intake.reader(fence, capture)
        bindings = KakaoArchiveService(intake.engine)
        original = bindings.get_binding(intake.actor, intake.h.binding)
        bindings.command_binding(
            intake.actor,
            intake.h.binding,
            KakaoBindingUpdatePolicy(
                parent_policy_revision_id=original.policy_revision.policy_revision_id,
                expected_resource_version=original.resource_version,
                policy=original.policy_revision.policy.model_copy(update={"interval_minutes": 120}),
            ),
            idempotency_key="policy-changed-" + uuid4().hex,
        )
        return result

    service = KakaoRoomIntakeService(
        intake.engine, artifacts=intake.artifacts, rooms=intake.rooms, read_download=changed
    )
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        service.confirm_room(intake.actor, command, idempotency_key="changed-" + uuid4().hex)


def test_new_authenticated_session_can_confirm_owned_capture_but_not_open_old_remote(intake):
    command, now = intake.prepare(), datetime.now(UTC)
    new_session = "apisession_" + uuid4().hex
    with Session(intake.engine) as session, session.begin():
        session.add(
            ApiSessionRecord(
                api_session_id=new_session,
                operator_id=intake.actor.operator_id,
                token_family_id="tokenfamily_" + uuid4().hex,
                client_name="disposable-intake-reauth",
                authenticated_at=now,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now + timedelta(hours=1),
                idle_expires_at=now + timedelta(minutes=30),
            )
        )
    actor = intake.actor.model_copy(
        update={"session_id": new_session, "request_id": "reauth-" + uuid4().hex}
    )
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        intake.h.service.get_session(actor, intake.current.lease_id)
    result = intake.service.confirm_room(actor, command, idempotency_key="reauth-" + uuid4().hex)
    assert result.room.mapping.state == "UNMAPPED"


def test_ended_manual_history_is_not_reopened_or_changed_by_confirmation(intake):
    command = intake.prepare()
    intake.h.now += timedelta(seconds=1)
    intake.h.service.end_session(
        intake.actor,
        intake.current.lease_id,
        KakaoManualEnd(expected_resource_version=intake.current.resource_version),
        idempotency_key="end-before-intake-" + uuid4().hex,
    )
    intake.h.service.accept_closed(intake.current.lease_id, observe_stopped=intake.h.close)
    result = confirm(intake, command)
    assert result.room.identity_level == "MANUAL_CONFIRMED"
    with Session(intake.engine) as session:
        original = session.get(KakaoManualSessionRecord, intake.current.lease_id)
        assert original.phase == "ENDED" and original.closed_at == intake.h.now


def test_approved_pin_evidence_cannot_be_rewritten(intake):
    confirm(intake)
    with pytest.raises(DBAPIError), Session(intake.engine) as session, session.begin():
        pin = session.get(KakaoManualChannelPinRecord, intake.h.binding)
        session.execute(
            update(ArtifactRecord)
            .where(ArtifactRecord.logical_artifact_id == pin.evidence_artifact_id)
            .values(approved=False)
        )
    assert confirm(intake, intake.prepare(room="another-room")).room.room_id


def test_restart_after_source_publication_reuses_original_artifact(intake, monkeypatch):
    command, key = intake.prepare(), "interrupted-" + uuid4().hex
    original = intake.artifacts.commit_file_set
    published = []

    def interrupted(**kwargs):
        if kwargs["artifact_type"] == "kakao-room-identity":
            raise OSError("synthetic stop before room-identity publication")
        result = original(**kwargs)
        published.append(result.artifact_id)
        return result

    monkeypatch.setattr(intake.artifacts, "commit_file_set", interrupted)
    with pytest.raises(OSError, match="synthetic stop"):
        confirm(intake, command, key)
    assert len(published) == 1

    def resumed(**kwargs):
        result = original(**kwargs)
        if kwargs["artifact_type"] == "kakao-room-intake-evidence":
            published.append(result.artifact_id)
        return result

    monkeypatch.setattr(intake.artifacts, "commit_file_set", resumed)
    service = KakaoRoomIntakeService(
        intake.engine,
        artifacts=intake.artifacts,
        rooms=KakaoRoomService(intake.engine),
        read_download=intake.reader,
    )
    assert (
        service.confirm_room(intake.actor, command, idempotency_key=key).room.mapping.state
        == "UNMAPPED"
    )
    assert published == [published[0], published[0]]


def test_missing_observation_never_falls_back_to_filename_matching(intake):
    command = intake.prepare()
    (intake.run / command.capture_id / "page-observation.json").unlink()
    with pytest.raises(KakaoArchiveError, match="ROOM_IDENTITY_UNAVAILABLE"):
        confirm(intake, command)


def test_retired_binding_does_not_return_existing_private_evidence(intake):
    command, key = intake.prepare(), "retired-replay-" + uuid4().hex
    confirm(intake, command, key)
    bindings = KakaoArchiveService(intake.engine)
    current = bindings.get_binding(intake.actor, intake.h.binding)
    bindings.command_binding(
        intake.actor,
        intake.h.binding,
        KakaoBindingRetire(
            parent_policy_revision_id=current.policy_revision.policy_revision_id,
            expected_resource_version=current.resource_version,
        ),
        idempotency_key="retire-" + uuid4().hex,
    )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        confirm(intake, command, key)
