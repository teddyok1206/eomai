"""Real capture owner/source admission over anonymous artifacts in guarded disposable PG."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from io import BytesIO
from threading import Barrier
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive import (
    KakaoAttachmentObservation,
    KakaoMessageObservation,
)
from eom_catalog_contracts.kakao_snapshot import KakaoRoomSnapshot
from eom_catalog_contracts.kakao_source import CAPTURE_REF, KakaoSourceAdmission
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_intake import publish_kakao_capture
from eom_catalog_service.kakao_collection_attempt_models import (
    KakaoCollectionAttemptRecord as Attempt,
)
from eom_catalog_service.kakao_collection_attempt_service import KakaoCollectionAttemptService
from eom_catalog_service.kakao_collection_models import KakaoCollectionRunRecord as Run
from eom_catalog_service.kakao_collection_models import KakaoCollectionTaskRecord as Task
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_catalog_service.kakao_source_service import KakaoSourceService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service.models import OperatorRecord
from eom_kakao_archive_contracts.capture import (
    CaptureAttachment,
    CaptureCommand,
    CaptureInventory,
    CaptureResult,
    CaptureRoomReport,
    CsvMember,
    InventoryRoom,
    InventoryScope,
)
from eom_kakao_archive_contracts.execution import WorkerExecution
from eom_kakao_archive_contracts.render import LocalMember
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_capability_storage import cap as cap
from tests.integration.test_kakao_collection_browser_storage import browser as browser
from tests.integration.test_kakao_collection_browser_storage import closed, running
from tests.integration.test_kakao_collection_storage import collection as collection
from tests.integration.test_kakao_room_intake import h as h
from tests.integration.test_kakao_room_intake import intake as intake

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def local(path, value, media="application/json"):
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value.model_dump(mode="json"))
    return LocalMember(
        relative_path=path, media_type=media, size_bytes=len(raw), sha256=sha256_bytes(raw)
    )


@pytest.fixture
def attempt(browser, tmp_path):
    active = running(browser)
    # The existing browser harness advances a synthetic clock to close MANUAL.
    # This source/Artifact integration intentionally uses the real UTC clock;
    # synchronize once rather than weakening the production timestamp guard.
    delay = (active.browser_observed_at - datetime.now(UTC)).total_seconds()
    assert delay < 2
    if delay > 0:
        sleep(delay)
    artifacts = browser.collection.cap.intake.artifacts
    service = KakaoCollectionAttemptService(
        browser.h.engine,
        artifacts=artifacts,
        profile_id=browser.h.profile,
        adapter_release_sha256=browser.collection.cap.service.adapter_sha256,
    )
    return SimpleNamespace(
        browser=browser,
        engine=browser.h.engine,
        active=active,
        artifacts=artifacts,
        service=service,
        actor=browser.h.actor,
        tmp=tmp_path,
    )


def reserve(attempt):
    return attempt.service.reserve_attempt(
        attempt.browser.accepted.task_id, browser_run_id=attempt.active.browser_run_id
    )


def publish(attempt, files, primary):
    files = {
        name: value
        if isinstance(value, bytes)
        else canonical_json_bytes(value.model_dump(mode="json"))
        for name, value in files.items()
    }
    paths = {}
    for name, raw in files.items():
        path = attempt.tmp / (uuid4().hex + "-staged")
        path.write_bytes(raw)
        paths[name] = path
    result = attempt.artifacts.commit_file_set(
        files=paths,
        primary_file=primary,
        artifact_type="test-kakao-owned-capture",
        idempotency_key="capture-evidence-" + uuid4().hex,
        request={"synthetic": True},
        result={},
        file_metadata={
            name: {"schema_ref": CAPTURE_REF, "media_type": "application/json"} for name in files
        },
        expected_file_sha256={name: sha256_bytes(raw) for name, raw in files.items()},
    )
    return ArtifactMemberPointer(
        artifact_id=result.artifact_id,
        artifact_revision_id=result.revision_id,
        member_path=primary,
        schema_ref=CAPTURE_REF,
        media_type="application/json",
        sha256=result.content_hash,
    )


def command_input(attempt, reserved=None, **changes):
    reserved = reserved or reserve(attempt)
    accepted = attempt.browser.collection.cap.service.get_capability(
        attempt.actor,
        reserved.source_binding_id,
        attempt.browser.collection.command.capability_revision_id,
    )
    execution = WorkerExecution(
        **{name: getattr(reserved, name) for name in WorkerExecution.model_fields}
    )
    now = datetime.now(UTC)
    proof = accepted.capability.evidence[0].model_copy(
        update=dict(relative_path="outputs/room-proof.json")
    )
    inventory = CaptureInventory(
        execution=execution,
        run_id=reserved.run_id,
        source_binding_id=reserved.source_binding_id,
        inventory_revision_id="kakaoinventoryrev_" + uuid4().hex,
        inventory_started_at=now,
        inventory_finished_at=now,
        reconciliation_pass_at=None,
        scopes=(
            InventoryScope(
                scope_id="MANUAL_SELECTED_ROOM",
                filters_cleared=False,
                end_reached=False,
                pending_loading=False,
                stabilization_completed=False,
                new_rooms_on_stabilization=0,
                evidence=proof,
            ),
        ),
        rooms=(
            InventoryRoom(
                room_id=reserved.room_id,
                scope_ids=("MANUAL_SELECTED_ROOM",),
                identity_level="manual_binding",
                evidence=proof,
            ),
        ),
        unresolved=(),
        inventory_complete=False,
    )
    command = CaptureCommand.model_validate(
        dict(
            execution=execution,
            run_id=reserved.run_id,
            source_binding_id=reserved.source_binding_id,
            profile_id=reserved.profile_id,
            browser_run_id=reserved.browser_run_id,
            adapter_release_sha256=accepted.capability.adapter_release_sha256,
            capability_revision_id=accepted.capability.capability_revision_id,
            capability=local("inputs/capability.json", accepted.capability),
            issued_at=now,
            operation="CAPTURE_ROOM",
            requested_scope_ids=("MANUAL_SELECTED_ROOM",),
            inventory_revision_id=inventory.inventory_revision_id,
            inventory=local("inputs/inventory.json", inventory),
            room_id=reserved.room_id,
            snapshot_revision_id=reserved.snapshot_revision_id,
            normalization_revision_id=reserved.normalization_revision_id,
        )
        | changes
    )
    inventory_pointer = publish(attempt, {"inventory.json": inventory}, "inventory.json")
    pointer = publish(attempt, {"command.json": command}, "command.json")
    return reserved, command, accepted, pointer, inventory_pointer


def result_proposal(attempt, *, status="PARTIAL", error=None, images=()):
    reserved, command, cap, command_pointer, inventory_pointer = command_input(attempt)
    attempt.service.pin_command(
        reserved.attempt_id, command_pointer, inventory_pointer=inventory_pointer
    )
    raw = (
        b"DATE,USER,MESSAGE\r\n"
        b"2026-11-16 12:00:00,anonymous,same question\r\n"
        b"2026-11-16 12:00:00,anonymous,same question\r\n"
    )
    now = datetime.now(UTC)
    attachments, observations, image_members = [], [], {}
    for row, raw_image in enumerate(images, 1):
        from PIL import Image

        with Image.open(BytesIO(raw_image)) as image:
            width, height = image.size
        observation = KakaoAttachmentObservation(
            attachment_id="kakaoattachment_" + uuid4().hex,
            attachment_revision_id="kakaoattachmentrev_" + uuid4().hex,
            album_ordinal=1,
            availability="available",
            association="SNAPSHOT_ONLY",
        )
        member = local(f"outputs/photo-{row}.png", raw_image, "image/png")
        attachments.append(
            CaptureAttachment(
                **observation.model_dump(),
                row_ordinal=row,
                quality_level="unknown",
                member=member,
                width_px=width,
                height_px=height,
                failure_reason=None,
            )
        )
        observations.append(
            KakaoMessageObservation(
                row_ordinal=row,
                kind="attachment",
                attachments=(observation,),
            )
        )
        image_members[member.relative_path] = raw_image
    norm = parse_kakao_csv(
        raw,
        source_binding_id=reserved.source_binding_id,
        room_id=reserved.room_id,
        snapshot_revision_id=reserved.snapshot_revision_id,
        normalization_revision_id=reserved.normalization_revision_id,
        observed_at_utc=now,
        source_timezone="unknown",
        source_order="unknown",
        observations=tuple(observations),
    )
    snapshot = KakaoRoomSnapshot(
        source_binding_id=reserved.source_binding_id,
        room_id=reserved.room_id,
        snapshot_revision_id=reserved.snapshot_revision_id,
        source_sha256=sha256_bytes(raw),
        source_bytes=len(raw),
        observed_at_utc=now,
        csv_scope="unknown",
    )
    report = (
        CaptureRoomReport(
            execution=command.execution,
            run_id=reserved.run_id,
            source_binding_id=reserved.source_binding_id,
            room_id=reserved.room_id,
            inventory_revision_id=command.inventory_revision_id,
            snapshot_revision_id=reserved.snapshot_revision_id,
            normalization_revision_id=reserved.normalization_revision_id,
            observed_start_at=command.issued_at,
            observed_end_at=now,
            raw_csv=CsvMember(
                relative_path="outputs/source.csv", sha256=sha256_bytes(raw), size_bytes=len(raw)
            ),
            normalization=local("outputs/normalization.json", norm),
            csv_scope="unknown",
            source_order="unknown",
            source_timezone="unknown",
            direction_evidence="unknown",
            csv_rows=2,
            unknown_sender_rows=2,
            first_source_at_utc=None,
            last_source_at_utc=None,
            attachment_bubbles_observed=len(attachments),
            attachment_inventory_complete=False,
            unresolved_attachment_bubbles=0,
            attachments=tuple(attachments),
            room_complete=False,
        )
        if status == "PARTIAL"
        else None
    )
    result = CaptureResult(
        execution=command.execution,
        run_id=reserved.run_id,
        source_binding_id=reserved.source_binding_id,
        room_id=reserved.room_id,
        command_sha256=command_pointer.sha256,
        adapter_release_sha256=command.adapter_release_sha256,
        capability_revision_id=command.capability_revision_id,
        status=status,
        report=None if report is None else local("outputs/room-report.json", report),
        error_code=error,
    )
    return SimpleNamespace(
        reserved=reserved,
        command=command,
        cap=cap,
        command_pointer=command_pointer,
        inventory_pointer=inventory_pointer,
        result=result,
        report=report,
        raw=raw,
        normalization=norm,
        snapshot=snapshot,
        members={
            "outputs/source.csv": raw,
            "outputs/normalization.json": canonical_json_bytes(norm.model_dump(mode="json")),
            **image_members,
        },
    )


def result_input(attempt, *, status="PARTIAL", error=None, images=()):
    data = result_proposal(attempt, status=status, error=error, images=images)
    data.pointer = publish(
        attempt,
        {"result.json": data.result, **({"room-report.json": data.report} if data.report else {})},
        "result.json",
    )
    return data


def publish_and_admit(attempt, data, *, key=None, read=None):
    return attempt.service.publish_and_admit_capture_source(
        attempt.actor,
        data.reserved.attempt_id,
        read_member=read or (lambda member: data.members[member.relative_path]),
        idempotency_key=key or "published-capture-" + uuid4().hex,
        expected_source_revision_id=None,
        expected_resource_version=0,
    )


def photo():
    from PIL import Image

    stream = BytesIO()
    Image.new("RGB", (6, 8), "white").save(stream, format="PNG")
    return stream.getvalue()


def test_accepted_output_publishes_source_and_replays_without_local_files(attempt):
    data = result_input(attempt, images=(photo(), photo()))
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-publication-replay-" + uuid4().hex
    reads = []

    def read(member):
        reads.append(member.relative_path)
        return data.members[member.relative_path]

    accepted = publish_and_admit(attempt, data, key=key, read=read)
    assert len(reads) == len(set(reads)) == 4
    assert len(accepted.resolution.rows) == 2
    attached = accepted.resolution.admission.attachments
    assert len(attached) == 2
    assert attached[0].attachment_id != attached[1].attachment_id
    assert attached[0].original == attached[1].original
    assert attached[0].media_receipt == attached[1].media_receipt
    assert all(entry.quality == "UNKNOWN" for entry in attached)
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    data.members.clear()

    def missing(_member):
        pytest.fail("completed replay must not read local inputs")

    replay = publish_and_admit(attempt, data, key=key, read=missing)
    assert replay.replayed and replay.resolution == accepted.resolution
    with Session(attempt.engine) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before


def test_capture_publication_recovers_committed_source_before_task_adoption(attempt, monkeypatch):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-publication-adoption-stop-" + uuid4().hex
    adopt = attempt.service.accept_source_revision

    def stopped(*_args):
        raise RuntimeError("synthetic stop after committed source")

    monkeypatch.setattr(attempt.service, "accept_source_revision", stopped)
    with pytest.raises(RuntimeError, match="committed source"):
        publish_and_admit(attempt, data, key=key)
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    monkeypatch.setattr(attempt.service, "accept_source_revision", adopt)
    replay = publish_and_admit(attempt, data, key=key, read=lambda _m: pytest.fail("local read"))
    assert replay.replayed
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before


def test_capture_publication_recovers_original_publications_without_duplicate_bytes(
    attempt, monkeypatch
):
    from eom_catalog_service import kakao_capture_publication as publication

    data = result_input(attempt, images=(photo(), photo()))
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-original-publication-stop-" + uuid4().hex
    original = publication.publish_kakao_media

    def stopped(*_args, **_kwargs):
        raise RuntimeError("synthetic stop after originals")

    monkeypatch.setattr(publication, "publish_kakao_media", stopped)
    with pytest.raises(RuntimeError, match="after originals"):
        publish_and_admit(attempt, data, key=key)
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    monkeypatch.setattr(publication, "publish_kakao_media", original)
    accepted = publish_and_admit(attempt, data, key=key)
    assert len(accepted.resolution.admission.attachments) == 2
    with Session(attempt.engine) as session:
        # Only one deduplicated photo blob and the new source resolution were added.
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before + 2
        )


def test_capture_publication_rechecks_revocation_after_local_read(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    with Session(attempt.engine) as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))

    def read(member):
        with Session(attempt.engine) as session, session.begin():
            session.get(OperatorRecord, attempt.actor.operator_id).status = "DISABLED"
        return data.members[member.relative_path]

    with pytest.raises(KakaoArchiveError):
        publish_and_admit(attempt, data, read=read)
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before


def test_completed_capture_publication_does_not_bypass_current_permissions(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-completed-current-owner-" + uuid4().hex
    publish_and_admit(attempt, data, key=key)
    with Session(attempt.engine) as session, session.begin():
        session.get(OperatorRecord, attempt.actor.operator_id).status = "DISABLED"
    with pytest.raises(KakaoArchiveError):
        publish_and_admit(attempt, data, key=key, read=lambda _m: pytest.fail("local read"))


@pytest.mark.parametrize("state", ["unaccepted", "failed", "other-owner"])
def test_capture_publication_rejects_before_reading_unowned_or_failed_input(attempt, state):
    data = result_input(
        attempt,
        status="FAILED" if state == "failed" else "PARTIAL",
        error="UI_CHANGED" if state == "failed" else None,
    )
    if state != "unaccepted":
        attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    actor = make_actor(attempt.engine) if state == "other-owner" else attempt.actor
    with pytest.raises(KakaoArchiveError):
        attempt.service.publish_and_admit_capture_source(
            actor,
            data.reserved.attempt_id,
            read_member=lambda _m: pytest.fail("local read"),
            idempotency_key="invalid-publication-" + uuid4().hex,
            expected_source_revision_id=None,
            expected_resource_version=0,
        )


def test_capture_publication_rejects_hash_mismatch_without_source_adoption(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_INVALID"):
        publish_and_admit(attempt, data, read=lambda _m: b"tampered")
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"


def test_capture_publication_competing_calls_share_originals_and_one_source(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-publication-race-" + uuid4().hex
    barrier = Barrier(2)

    def call(_):
        barrier.wait(timeout=15)
        return publish_and_admit(attempt, data, key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = tuple(pool.map(call, range(2)))
    assert accepted[0].resolution == accepted[1].resolution
    assert accepted[0].manifest == accepted[1].manifest
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"


def test_completed_capture_publication_rejects_changed_key_and_precondition(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    key = "capture-publication-pinned-" + uuid4().hex
    accepted = publish_and_admit(attempt, data, key=key)
    for changed in (
        dict(idempotency_key=key + "-other"),
        dict(
            expected_source_revision_id=accepted.resolution.source_revision_id,
            expected_resource_version=1,
        ),
    ):
        arguments = (
            dict(idempotency_key=key, expected_source_revision_id=None, expected_resource_version=0)
            | changed
        )
        with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
            attempt.service.publish_and_admit_capture_source(
                attempt.actor,
                data.reserved.attempt_id,
                read_member=lambda _m: pytest.fail("local read"),
                **arguments,
            )


def test_claim_is_durable_and_replays_same_identity_under_concurrency(attempt):
    barrier = Barrier(3)

    def call(_):
        barrier.wait(timeout=10)
        return reserve(attempt)

    with ThreadPoolExecutor(max_workers=3) as pool:
        values = tuple(pool.map(call, range(3)))
    assert len({v.attempt_id for v in values}) == 1
    assert values[0] == attempt.service.get_attempt(values[0].attempt_id)
    with Session(attempt.engine) as session:
        assert session.scalar(select(func.count()).select_from(Attempt)) == 1
        assert session.get(Task, values[0].task_id).state == "QUEUED"
        assert not any(
            c.type.__class__.__name__ in {"JSONB", "LargeBinary"} for c in Attempt.__table__.columns
        )


def test_command_adoption_replay_and_competing_pointer_rejected(attempt):
    reserved, command, _, pointer, inventory_pointer = command_input(attempt)
    first = attempt.service.pin_command(
        reserved.attempt_id, pointer, inventory_pointer=inventory_pointer
    )
    assert first.state == "COMMAND_READY"
    assert first == attempt.service.pin_command(
        reserved.attempt_id, pointer, inventory_pointer=inventory_pointer
    )
    other = publish(attempt, {"command.json": command}, "command.json")
    with pytest.raises(KakaoArchiveError):
        attempt.service.pin_command(reserved.attempt_id, other, inventory_pointer=inventory_pointer)
    with Session(attempt.engine) as session:
        assert session.get(Task, reserved.task_id).state == "RUNNING"
        assert session.get(Run, reserved.run_id).state == "COLLECTING"
        row = session.get(Attempt, reserved.attempt_id)
        assert row.inventory_artifact_id == inventory_pointer.artifact_id
        revision = session.get(ArtifactRevisionRecord, pointer.artifact_revision_id)
        assert {member["file_name"] for member in revision.manifest["files"]} == {"command.json"}
    assert pointer.artifact_id != inventory_pointer.artifact_id


def test_different_inventory_identity_cannot_replace_pinned_source(attempt):
    reserved, _, _, pointer, inventory_pointer = command_input(attempt)
    attempt.service.pin_command(reserved.attempt_id, pointer, inventory_pointer=inventory_pointer)
    raw = attempt.artifacts.read_member(
        artifact_id=inventory_pointer.artifact_id,
        revision_id=inventory_pointer.artifact_revision_id,
        member_path="inventory.json",
        sha256=inventory_pointer.sha256,
        schema_ref=CAPTURE_REF,
        media_type="application/json",
        max_bytes=4 * 1024 * 1024,
    )
    different = publish(attempt, {"inventory.json": raw}, "inventory.json")
    assert (
        different.sha256 == inventory_pointer.sha256
        and different.artifact_id != inventory_pointer.artifact_id
    )
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        attempt.service.pin_command(reserved.attempt_id, pointer, inventory_pointer=different)


def test_wrong_room_command_cannot_gain_execution_or_source_authority(attempt):
    reserved, _, _, pointer, inventory_pointer = command_input(
        attempt, room_id="kakaoroom_" + "f" * 32
    )
    with pytest.raises(KakaoArchiveError, match="IDENTITY_MISMATCH"):
        attempt.service.pin_command(
            reserved.attempt_id, pointer, inventory_pointer=inventory_pointer
        )
    assert attempt.service.get_attempt(reserved.attempt_id).state == "RESERVED"


def test_result_acceptance_replays_but_does_not_complete_unvalidated_source(attempt):
    data = result_input(attempt)
    result = attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    assert result.state == "RESULT_ACCEPTED"
    assert result == attempt.service.accept_result(result.attempt_id, data.pointer)
    with Session(attempt.engine) as session:
        assert session.get(Task, result.task_id).state == "RUNNING"
        assert session.get(Run, result.run_id).state == "COLLECTING"


def source_input(attempt, data):
    publication = publish_kakao_capture(
        attempt.artifacts,
        snapshot=data.snapshot,
        source=data.raw,
        normalization=data.normalization,
        authorize=lambda: None,
    )
    return KakaoSourceAdmission(
        source_binding_id=data.reserved.source_binding_id,
        room_id=data.reserved.room_id,
        snapshot_revision_id=data.reserved.snapshot_revision_id,
        normalization_revision_id=data.reserved.normalization_revision_id,
        expected_source_revision_id=None,
        expected_resource_version=0,
        source=publication.source,
        snapshot=publication.snapshot,
        normalization=publication.normalization,
        authority=dict(
            run_id=data.reserved.run_id,
            attempt_id=data.reserved.attempt_id,
            fence=data.reserved.fence,
            command_sha256=data.command_pointer.sha256,
            capability_revision_id=data.command.capability_revision_id,
            adapter_release_sha256=data.command.adapter_release_sha256,
            command=data.command_pointer,
            capability=data.cap.capability_pointer,
            capture_result=data.pointer,
            capture_report=data.pointer.model_copy(
                update=dict(member_path="room-report.json", sha256=data.result.report.sha256)
            ),
        ),
        attachments=(),
    )


def test_real_capture_authorizer_admits_source_and_keeps_duplicate_messages(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    admission = source_input(attempt, data)
    source = KakaoSourceService(
        attempt.engine,
        artifacts=attempt.artifacts,
        authorize_capture=attempt.service.authorize_source,
    )
    key = "owned-source-" + uuid4().hex
    result = source.admit_source(attempt.actor, admission, idempotency_key=key)
    assert len(result.resolution.rows) == 2
    assert len({r.occurrence_id for r in result.resolution.rows}) == 2
    attempt.service.accept_source_revision(
        attempt.actor, data.reserved.attempt_id, result.resolution.source_revision_id
    )
    again = source.get_source(
        attempt.actor,
        admission.source_binding_id,
        admission.room_id,
        source_revision_id=result.resolution.source_revision_id,
    )
    assert again.resolution == result.resolution
    replay = source.admit_source(attempt.actor, admission, idempotency_key=key)
    assert replay.replayed and replay.resolution == result.resolution
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
    with (
        Session(attempt.engine) as session,
        session.begin(),
        pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"),
    ):
        attempt.service.authorize_source(
            session,
            attempt.actor,
            admission.model_copy(
                update=dict(authority=admission.authority.model_copy(update=dict(fence=999)))
            ),
        )
    other = make_actor(attempt.engine)
    with (
        Session(attempt.engine) as session,
        session.begin(),
        pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"),
    ):
        attempt.service.authorize_source(session, other, admission)


def test_application_source_admission_replays_after_task_adoption_interruption(
    attempt, monkeypatch
):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    admission = source_input(attempt, data)
    key = "source-adoption-interrupted-" + uuid4().hex
    adopt = attempt.service.accept_source_revision
    observed = []

    def interrupted(actor, attempt_id, source_revision_id):
        observed.append(source_revision_id)
        raise RuntimeError("synthetic stop after source commit")

    monkeypatch.setattr(attempt.service, "accept_source_revision", interrupted)
    with pytest.raises(RuntimeError, match="after source commit"):
        attempt.service.admit_capture_source(attempt.actor, admission, idempotency_key=key)
    assert len(observed) == 1
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"
        artifacts_after_commit = session.scalar(
            select(func.count()).select_from(ArtifactRevisionRecord)
        )
    monkeypatch.setattr(attempt.service, "accept_source_revision", adopt)
    restarted = KakaoCollectionAttemptService(
        attempt.engine,
        artifacts=attempt.artifacts,
        profile_id=attempt.service.profile_id,
        adapter_release_sha256=attempt.service.adapter_sha256,
    )
    recovered = restarted.admit_capture_source(attempt.actor, admission, idempotency_key=key)
    assert recovered.replayed and recovered.resolution.source_revision_id == observed[0]
    assert len(recovered.resolution.rows) == 2
    assert len({row.occurrence_id for row in recovered.resolution.rows}) == 2
    assert restarted.admit_capture_source(attempt.actor, admission, idempotency_key=key).replayed
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"
        assert session.get(Attempt, data.reserved.attempt_id).state == "RESULT_ACCEPTED"
        assert (
            session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
            == artifacts_after_commit
        )


def test_application_source_admission_competing_calls_adopt_one_revision(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    admission = source_input(attempt, data)
    key = "source-adoption-race-" + uuid4().hex
    barrier = Barrier(2)

    def accept(_):
        barrier.wait(timeout=10)
        return attempt.service.admit_capture_source(attempt.actor, admission, idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = tuple(pool.map(accept, range(2)))
    assert accepted[0].resolution == accepted[1].resolution
    assert accepted[0].manifest == accepted[1].manifest
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "LOCAL_ACCEPTED"


def test_application_source_admission_rejects_other_owner_without_adopting_task(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    admission = source_input(attempt, data)
    with pytest.raises(KakaoArchiveError):
        attempt.service.admit_capture_source(
            make_actor(attempt.engine), admission, idempotency_key="other-owner-" + uuid4().hex
        )
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"


def test_application_source_admission_cannot_use_an_unaccepted_result(attempt):
    data = result_input(attempt)
    admission = source_input(attempt, data)
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        attempt.service.admit_capture_source(
            attempt.actor, admission, idempotency_key="unaccepted-result-" + uuid4().hex
        )
    with Session(attempt.engine) as session:
        assert session.get(Task, data.reserved.task_id).state == "RUNNING"
        assert session.get(Attempt, data.reserved.attempt_id).state == "COMMAND_READY"


def test_failed_capture_history_cannot_be_replaced_by_success_or_restarted(attempt):
    data = result_input(attempt, status="FAILED", error="UI_CHANGED")
    result = attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    assert reserve(attempt).attempt_id == result.attempt_id
    with Session(attempt.engine) as session:
        row = session.get(Attempt, result.attempt_id)
        assert row.result_status == "FAILED" and row.error_code == "UI_CHANGED"
    with (
        pytest.raises(DBAPIError, match="ATTEMPT_IMMUTABLE"),
        Session(attempt.engine) as session,
        session.begin(),
    ):
        session.execute(
            update(Attempt)
            .where(Attempt.attempt_id == result.attempt_id)
            .values(error_code="TIMEOUT")
        )


def test_current_owner_revocation_during_artifact_io_blocks_adoption(attempt, monkeypatch):
    reserved, _, _, pointer, inventory_pointer = command_input(attempt)
    original = attempt.service._read

    def changed(*args):
        value = original(*args)
        with Session(attempt.engine) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == attempt.actor.operator_id)
                .values(must_change_password=True)
            )
        return value

    monkeypatch.setattr(attempt.service, "_read", changed)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        attempt.service.pin_command(
            reserved.attempt_id, pointer, inventory_pointer=inventory_pointer
        )
    assert attempt.service.get_attempt(reserved.attempt_id).state == "RESERVED"


def test_concurrent_result_acceptance_keeps_one_immutable_outcome(attempt):
    data = result_input(attempt)
    barrier = Barrier(2)

    def call(_):
        barrier.wait(timeout=10)
        return attempt.service.accept_result(data.reserved.attempt_id, data.pointer)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(call, range(2)))
    assert first == second
    with Session(attempt.engine) as session:
        assert session.get(Attempt, first.attempt_id).resource_version == 3


def test_late_result_after_observed_clean_close_adopts_original_attempt(attempt):
    data = result_input(attempt)
    attempt.browser.h.now = datetime.now(UTC)
    owner = attempt.browser.service
    stopping = owner.request_stop(attempt.active.browser_run_id)
    owner.accept_closed(
        stopping.browser_run_id, observe_stopped=lambda i: closed(attempt.browser, i)
    )
    accepted = attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    assert accepted.attempt_id == data.reserved.attempt_id and accepted.state == "RESULT_ACCEPTED"


def test_different_result_pointer_cannot_replace_failed_evidence(attempt):
    data = result_input(attempt, status="FAILED", error="TIMEOUT")
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    other = publish(
        attempt,
        {"result.json": data.result.model_copy(update=dict(error_code="UI_CHANGED"))},
        "result.json",
    )
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        attempt.service.accept_result(data.reserved.attempt_id, other)
    with Session(attempt.engine) as session:
        assert session.get(Attempt, data.reserved.attempt_id).error_code == "TIMEOUT"
