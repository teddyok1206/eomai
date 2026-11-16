"""Real capture owner/source admission over anonymous artifacts in guarded disposable PG."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
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


def result_input(attempt, *, status="PARTIAL", error=None):
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
    norm = parse_kakao_csv(
        raw,
        source_binding_id=reserved.source_binding_id,
        room_id=reserved.room_id,
        snapshot_revision_id=reserved.snapshot_revision_id,
        normalization_revision_id=reserved.normalization_revision_id,
        observed_at_utc=now,
        source_timezone="unknown",
        source_order="unknown",
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
            attachment_bubbles_observed=0,
            attachment_inventory_complete=False,
            unresolved_attachment_bubbles=0,
            attachments=(),
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
    pointer = publish(
        attempt,
        {"result.json": result, **({"room-report.json": report} if report else {})},
        "result.json",
    )
    return SimpleNamespace(
        reserved=reserved,
        command=command,
        cap=cap,
        command_pointer=command_pointer,
        result=result,
        report=report,
        pointer=pointer,
        raw=raw,
        normalization=norm,
        snapshot=snapshot,
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


def test_real_capture_authorizer_admits_source_and_keeps_duplicate_messages(attempt):
    data = result_input(attempt)
    attempt.service.accept_result(data.reserved.attempt_id, data.pointer)
    publication = publish_kakao_capture(
        attempt.artifacts,
        snapshot=data.snapshot,
        source=data.raw,
        normalization=data.normalization,
        authorize=lambda: None,
    )
    admission = KakaoSourceAdmission(
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
