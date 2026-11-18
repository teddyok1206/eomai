"""Guarded disposable persistence and local Artifact I/O; no real Kakao account/NAS."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire, KakaoBindingUpdatePolicy
from eom_catalog_contracts.kakao_capability import (
    CSV_POPUP_CAPABILITY_VERIFICATION_REF,
    ConfirmKakaoCapability,
)
from eom_catalog_contracts.kakao_room_intake import CSV_POPUP_ROOM_EVIDENCE_REF
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_capability_models import KakaoCapabilityAcceptanceRecord as Receipt
from eom_catalog_service.kakao_capability_service import KakaoCapabilityService
from eom_catalog_service.kakao_collection_service import KakaoCollectionService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import ApiSessionRecord
from eom_kakao_archive_contracts.capture import CaptureCommand, validate_capture_inputs
from eom_kakao_archive_contracts.execution import WorkerExecution
from eom_kakao_archive_contracts.render import LocalMember
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from sqlalchemy import DateTime, String, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import create, make_actor
from tests.integration.test_kakao_room_intake import h as h
from tests.integration.test_kakao_room_intake import intake as intake
from tests.integration.test_kakao_room_storage import admit
from tests.unit.test_kakao_archive_rules import csv_bytes
from tests.unit.test_kakao_photo_alignment import GROUPS, document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def cap(intake):
    original = intake.prepare()
    room = intake.service.confirm_room(
        intake.actor, original, idempotency_key="source-room-" + uuid4().hex
    ).room
    return SimpleNamespace(
        intake=intake,
        engine=intake.engine,
        actor=intake.actor,
        original=original,
        command=ConfirmKakaoCapability(
            source_binding_id=room.source_binding_id,
            room_id=room.room_id,
            expected_binding_version=1,
        ),
        key="capability-" + uuid4().hex,
        service=KakaoCapabilityService(
            intake.engine, artifacts=intake.artifacts, adapter_release_sha256="sha256:" + "a" * 64
        ),
    )


def confirm(cap, command=None, key=None):
    return cap.service.confirm_capability(
        cap.actor, command or cap.command, idempotency_key=key or cap.key
    )


def test_csv_popup_registration_enters_the_existing_one_room_collection(intake):
    channel, room = "csv-channel", "csv-room"
    groups = [
        (kind, value.replace("/channel1/", f"/{channel}/").replace("/room1/", f"/{room}/"))
        for kind, value in GROUPS
    ]
    popup = document(groups, path=f"/space/workspace/channel/{channel}/chats/{room}")
    with pytest.raises(KakaoArchiveError, match="ROOM_IDENTITY_UNAVAILABLE"):
        intake.service.confirm_room(
            intake.actor,
            intake.prepare(
                channel=channel,
                room=room,
                target={"kind": "BLOB", "path": None},
                document=popup,
                payload=b"wrong bytes",
            ),
            idempotency_key="invalid-csv-room-" + uuid4().hex,
        )
    original = intake.prepare(
        channel=channel,
        room=room,
        target={"kind": "BLOB", "path": None},
        document=popup,
        payload=csv_bytes([["2026-11-18 12:00:00", "synthetic", "사진"]]),
    )
    room_key = "csv-room-" + uuid4().hex
    first = intake.service.confirm_room(intake.actor, original, idempotency_key=room_key)
    proof = intake.service.get_confirmation(
        intake.actor, original.source_binding_id, idempotency_key=room_key
    )
    assert proof.observation.source_evidence.schema_ref == CSV_POPUP_ROOM_EVIDENCE_REF
    assert first.room.mapping.state == "UNMAPPED"
    other = intake.prepare(channel=channel, room="old-photo-format")
    assert (
        intake.service.confirm_room(
            intake.actor, other, idempotency_key="same-channel-photo-" + uuid4().hex
        ).room.room_id
        != first.room.room_id
    )
    capability = KakaoCapabilityService(
        intake.engine, artifacts=intake.artifacts, adapter_release_sha256="sha256:" + "a" * 64
    )
    collection = KakaoCollectionService(intake.engine, capabilities=capability)
    selection = ConfirmKakaoCapability(
        source_binding_id=original.source_binding_id,
        room_id=first.room.room_id,
        expected_binding_version=1,
    )
    policy = (
        KakaoArchiveService(intake.engine)
        .get_binding(intake.actor, original.source_binding_id)
        .policy_revision.policy_revision_id
    )
    request = {"expected_policy_revision_id": policy, "idempotency_key": "csv-auto-" + uuid4().hex}
    status = collection.start_registered_room(intake.actor, selection, **request)
    pinned = collection.read_background_intent(status.run_id)
    assert pinned.capability_manifest.schema_ref == CSV_POPUP_CAPABILITY_VERIFICATION_REF
    parsed = capability.read_pinned_manual_room(
        pinned.capability_manifest,
        binding=original.source_binding_id,
        room=first.room.room_id,
        revision=pinned.accepted.request.capability_revision_id,
    )
    assert (parsed.space_key, parsed.proof.confirmation.expected_room_key) == ("workspace", room)
    assert parsed.capability.direction_evidence == parsed.capability.source_timezone == "unknown"
    assert (
        collection.start_registered_room(intake.actor, selection, **request).run_id == status.run_id
    )


def count_receipts(cap, session):
    return session.scalar(
        select(func.count())
        .select_from(Receipt)
        .where(
            Receipt.owner_operator_id == cap.actor.operator_id,
            Receipt.source_binding_id == cap.command.source_binding_id,
        )
    )


def test_actual_publication_exact_replay_without_temporary_capture_or_activation(cap):
    first = confirm(cap)
    capture = cap.intake.run / cap.original.capture_id
    for path in capture.iterdir():
        path.unlink()
    capture.rmdir()
    replay = confirm(cap)
    read = cap.service.get_capability(
        cap.actor, cap.command.source_binding_id, first.capability.capability_revision_id
    )
    assert replay.replayed and not first.replayed and read.capability == first.capability
    assert first.manifest == replay.manifest == read.manifest
    assert first.accepted_at == replay.accepted_at
    assert first.capability.evidence[0].sha256 == first.verification.manual_proof.sha256
    assert first.capability_pointer.artifact_id == first.manifest.artifact_id
    assert first.capability_pointer.artifact_revision_id == first.manifest.artifact_revision_id
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 1
        revision = session.get(ArtifactRevisionRecord, first.manifest.artifact_revision_id)
        assert {item["file_name"] for item in revision.manifest["files"]} == {
            "capability.json",
            "verification.json",
        }
    binding = KakaoArchiveService(cap.engine).get_binding(cap.actor, cap.command.source_binding_id)
    assert (
        binding.state == "DRAFT"
        and binding.capability_state == "NOT_VERIFIED"
        and not binding.schedule_enabled
    )


def test_existing_worker_input_contract_accepts_exact_capability_and_local_evidence(cap):
    accepted = confirm(cap)
    raw = canonical_json_bytes(accepted.capability.model_dump(mode="json"))
    command = CaptureCommand(
        execution=WorkerExecution(
            command_id="kakaocommand_" + uuid4().hex,
            task_id="kakaotask_" + uuid4().hex,
            attempt_id="kakaoattempt_" + uuid4().hex,
            attempt_number=1,
            fence=1,
        ),
        run_id="kakaorun_" + uuid4().hex,
        source_binding_id=cap.command.source_binding_id,
        profile_id=cap.intake.current.profile_id,
        browser_run_id="kakaobrowserrun_" + uuid4().hex,
        adapter_release_sha256=accepted.capability.adapter_release_sha256,
        capability_revision_id=accepted.capability.capability_revision_id,
        capability=LocalMember(
            relative_path="inputs/capability.json",
            media_type="application/json",
            size_bytes=len(raw),
            sha256=sha256_bytes(raw),
        ),
        issued_at=datetime.now(UTC),
        operation="INVENTORY",
        requested_scope_ids=accepted.capability.visible_scope_ids,
        inventory_revision_id="kakaoinventoryrev_" + uuid4().hex,
        inventory=None,
        room_id=None,
        snapshot_revision_id=None,
        normalization_revision_id=None,
    )
    members = validate_capture_inputs(command, accepted.capability)
    assert {member.relative_path for member in members} == {
        "inputs/capability.json",
        "inputs/manual-room-proof.json",
    }


def test_same_key_concurrent_adoption_is_one_exact_receipt(cap):
    barrier = Barrier(3)

    def call():
        barrier.wait(timeout=10)
        return confirm(cap)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = tuple(pool.map(lambda _: call(), range(3)))
    assert len({result.capability.capability_revision_id for result in results}) == 1
    assert len({result.manifest.artifact_id for result in results}) == 1
    assert sum(not result.replayed for result in results) == 1
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 1


def test_same_key_changed_command_is_conflict(cap):
    confirm(cap)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        confirm(cap, cap.command.model_copy(update={"expected_binding_version": 2}))


def test_same_key_competing_rooms_cannot_adopt_two_capabilities(cap):
    original = cap.intake.prepare(room="another-room")
    room = cap.intake.service.confirm_room(
        cap.actor, original, idempotency_key="another-room-" + uuid4().hex
    ).room
    other = cap.command.model_copy(update={"room_id": room.room_id})
    barrier = Barrier(2)

    def call(command):
        barrier.wait(timeout=10)
        try:
            return confirm(cap, command)
        except KakaoArchiveError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(call, (cap.command, other)))
    assert sum(not isinstance(result, str) for result in results) == 1
    assert "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT" in results
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 1


def test_approved_room_metadata_without_manual_pin_is_not_capability_authority(cap):
    from eom_catalog_service.kakao_room_service import KakaoRoomService

    binding = create(KakaoArchiveService(cap.engine), cap.actor).binding
    result, _ = admit(cap.engine, (cap.actor, binding, KakaoRoomService(cap.engine)))
    command = ConfirmKakaoCapability(
        source_binding_id=binding.source_binding_id,
        room_id=result.room.room_id,
        expected_binding_version=1,
    )
    with pytest.raises(KakaoArchiveError, match="CAPABILITY_UNVERIFIED"):
        confirm(cap, command, key="not-actual-manual-" + uuid4().hex)


def test_missing_pinned_file_is_not_replaced_by_newer_capability(cap, monkeypatch):
    first, second = confirm(cap), confirm(cap, key="newer-capability-" + uuid4().hex)
    original = cap.intake.artifacts.open_verified_member

    def missing(**kwargs):
        if kwargs["artifact_id"] == first.manifest.artifact_id:
            raise OSError("synthetic missing file: private detail must not escape")
        return original(**kwargs)

    monkeypatch.setattr(cap.intake.artifacts, "open_verified_member", missing)
    with pytest.raises(KakaoArchiveError) as error:
        cap.service.get_capability(
            cap.actor, cap.command.source_binding_id, first.capability.capability_revision_id
        )
    assert str(error.value) == "KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID"
    assert (
        cap.service.get_capability(
            cap.actor, cap.command.source_binding_id, second.capability.capability_revision_id
        ).capability
        == second.capability
    )
    monkeypatch.setattr(cap.intake.artifacts, "open_verified_member", original)
    assert (
        cap.service.get_capability(
            cap.actor, cap.command.source_binding_id, first.capability.capability_revision_id
        ).capability
        == first.capability
    )


def test_different_keys_make_distinct_revision_not_hash_identity(cap):
    first, second = confirm(cap), confirm(cap, key="next-capability-" + uuid4().hex)
    assert first.capability.capability_revision_id != second.capability.capability_revision_id
    assert first.manifest.artifact_id != second.manifest.artifact_id
    assert first.capability.observed_at == second.capability.observed_at


def test_other_owner_cannot_confirm_or_read_capability(cap):
    accepted, other = confirm(cap), make_actor(cap.engine)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        cap.service.confirm_capability(other, cap.command, idempotency_key="foreign-" + uuid4().hex)
    with pytest.raises(KakaoArchiveError, match="RESOURCE_NOT_FOUND"):
        cap.service.get_capability(
            other, cap.command.source_binding_id, accepted.capability.capability_revision_id
        )


def test_old_capability_replay_is_not_reinterpreted_under_new_adapter(cap):
    original = confirm(cap)
    newer = KakaoCapabilityService(
        cap.engine, artifacts=cap.intake.artifacts, adapter_release_sha256="sha256:" + "b" * 64
    )
    replay = newer.confirm_capability(cap.actor, cap.command, idempotency_key=cap.key)
    assert replay.replayed and replay.capability == original.capability
    assert replay.capability.adapter_release_sha256 != newer.adapter_sha256


def test_interruption_after_publication_reuses_original_artifact(cap, monkeypatch):
    commit, published = cap.intake.artifacts.commit_file_set, []

    def interrupted(**kwargs):
        result = commit(**kwargs)
        published.append(result.artifact_id)
        raise OSError("synthetic stop after publication")

    monkeypatch.setattr(cap.intake.artifacts, "commit_file_set", interrupted)
    with pytest.raises(OSError, match="synthetic stop"):
        confirm(cap)
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 0
    monkeypatch.setattr(cap.intake.artifacts, "commit_file_set", commit)
    result = confirm(cap)
    assert result.manifest.artifact_id == published[0]


def test_late_identity_revocation_prevents_adoption_after_publication(cap, monkeypatch):
    commit, published = cap.intake.artifacts.commit_file_set, []

    def revoked(**kwargs):
        result = commit(**kwargs)
        published.append(result.artifact_id)
        with Session(cap.engine) as session, session.begin():
            session.execute(
                update(ApiSessionRecord)
                .where(ApiSessionRecord.api_session_id == cap.actor.session_id)
                .values(revoked_at=datetime.now(UTC))
            )
        return result

    monkeypatch.setattr(cap.intake.artifacts, "commit_file_set", revoked)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        confirm(cap)
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 0
        assert len(published) == 1 and session.get(ArtifactRecord, published[0]).approved


def test_policy_change_prevents_first_adoption_but_not_completed_replay(cap, monkeypatch):
    commit, bindings = cap.intake.artifacts.commit_file_set, KakaoArchiveService(cap.engine)

    def changed(**kwargs):
        result = commit(**kwargs)
        old = bindings.get_binding(cap.actor, cap.command.source_binding_id)
        bindings.command_binding(
            cap.actor,
            old.source_binding_id,
            KakaoBindingUpdatePolicy(
                parent_policy_revision_id=old.policy_revision.policy_revision_id,
                expected_resource_version=old.resource_version,
                policy=old.policy_revision.policy.model_copy(update={"interval_minutes": 120}),
            ),
            idempotency_key="changed-policy-" + uuid4().hex,
        )
        return result

    monkeypatch.setattr(cap.intake.artifacts, "commit_file_set", changed)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        confirm(cap)
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 0
    monkeypatch.setattr(cap.intake.artifacts, "commit_file_set", commit)
    with pytest.raises(KakaoArchiveError, match="PRECONDITION_FAILED"):
        confirm(cap)
    command, key = (
        cap.command.model_copy(update={"expected_binding_version": 2}),
        "accepted-version2-" + uuid4().hex,
    )
    result = confirm(cap, command, key)
    current = bindings.get_binding(cap.actor, command.source_binding_id)
    bindings.command_binding(
        cap.actor,
        current.source_binding_id,
        KakaoBindingUpdatePolicy(
            parent_policy_revision_id=current.policy_revision.policy_revision_id,
            expected_resource_version=current.resource_version,
            policy=current.policy_revision.policy.model_copy(update={"interval_minutes": 180}),
        ),
        idempotency_key="changed-again-" + uuid4().hex,
    )
    replay = confirm(cap, command, key)
    assert replay.replayed and replay.capability == result.capability


def test_retired_binding_denies_read_and_replay_without_deleting_receipt(cap):
    result = confirm(cap)
    bindings = KakaoArchiveService(cap.engine)
    current = bindings.get_binding(cap.actor, cap.command.source_binding_id)
    bindings.command_binding(
        cap.actor,
        current.source_binding_id,
        KakaoBindingRetire(
            parent_policy_revision_id=current.policy_revision.policy_revision_id,
            expected_resource_version=current.resource_version,
        ),
        idempotency_key="retire-capability-" + uuid4().hex,
    )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        cap.service.get_capability(
            cap.actor, current.source_binding_id, result.capability.capability_revision_id
        )
    with pytest.raises(KakaoArchiveError, match="BINDING_RETIRED"):
        confirm(cap)
    with Session(cap.engine) as session:
        assert count_receipts(cap, session) == 1


def test_capability_receipt_is_immutable_and_no_binary_db_payload(cap):
    result = confirm(cap)
    for statement in (
        "UPDATE kakao_capability_acceptances SET adapter_release_sha256=adapter_release_sha256 "
        "WHERE capability_revision_id=:id",
        "DELETE FROM kakao_capability_acceptances WHERE capability_revision_id=:id",
    ):
        with pytest.raises(DBAPIError), Session(cap.engine) as session, session.begin():
            session.execute(text(statement), {"id": result.capability.capability_revision_id})
    assert not {"payload", "content", "bytes", "body", "capability"}.intersection(
        Receipt.__table__.columns.keys()
    )
    assert all(isinstance(column.type, (String, DateTime)) for column in Receipt.__table__.columns)
