"""Actual local C1 files→Artifact/source/task in guarded disposable PostgreSQL."""

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_capture_proposal import (
    OpenRoomDownloadEvidence,
    PartialRoomEvidence,
    build_open_room_proposal,
    build_partial_room_capture,
)
from eom_catalog_service.kakao_collection_attempt_models import (
    KakaoCollectionAttemptRecord as Attempt,
)
from eom_catalog_service.kakao_collection_attempt_service import KakaoCollectionAttemptService
from eom_catalog_service.kakao_collection_continuation import KakaoCollectionContinuation
from eom_catalog_service.kakao_collection_models import KakaoCollectionTaskRecord as Task
from eom_catalog_service.kakao_collection_source_composition import (
    admit_staged_kakao_capture_source,
    admit_staged_kakao_open_room,
)
from eom_catalog_service.kakao_one_room_collection import KakaoOneRoomCollection
from eom_identifiers import canonical_json_bytes
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_kakao_archive_contracts.capture import CaptureInventory, CsvMember
from eom_kakao_archive_contracts.manual_observation import ManualDocument
from eom_kakao_archive_contracts.open_room_download import OpenRoomDownloadReceipt, RoomPhotoReceipt
from eom_kakao_archive_contracts.render import sha256
from eom_orchestrator import kakao_capture_inputs as capture_inputs
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.kakao_collection_browser_runtime import KakaoCollectionBrowserRuntimeError
from eom_orchestrator.settings import Settings
from sqlalchemy.orm import Session

from tests.integration.test_kakao_collection_attempt_storage import result_proposal
from tests.integration.test_kakao_collection_browser_storage import closed
from tests.integration.test_kakao_collection_source_access import attempt as attempt
from tests.integration.test_kakao_collection_source_access import browser as browser
from tests.integration.test_kakao_collection_source_access import cap as cap
from tests.integration.test_kakao_collection_source_access import collection as collection
from tests.integration.test_kakao_collection_source_access import counts, photo
from tests.integration.test_kakao_collection_source_access import h as h
from tests.integration.test_kakao_collection_source_access import intake as intake
from tests.unit.test_kakao_archive_rules import csv_bytes
from tests.unit.test_kakao_photo_alignment import GROUPS, OTHER_PHOTO, TARGET, document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def staged(attempt):
    data = result_proposal(attempt, images=(photo(), photo()))
    files = data.members | {
        "outputs/result.json": canonical_json_bytes(data.result.model_dump(mode="json")),
        "outputs/room-report.json": canonical_json_bytes(data.report.model_dump(mode="json")),
    }
    with tempfile.TemporaryDirectory(
        prefix="kakao-staged-pg-", dir=Path.home() / ".cache"
    ) as folder:
        root = Path(folder)
        root.chmod(0o2750)
        workspace = root / data.reserved.attempt_id
        workspace.mkdir(mode=0o750)
        workspace.chmod(0o750)
        for name, raw in files.items():
            path = workspace / name
            path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            path.parent.chmod(0o750)
            path.write_bytes(raw)
            path.chmod(0o640)
        yield SimpleNamespace(
            attempt=attempt,
            data=data,
            files=files,
            root=root,
            workspace=workspace,
            key="staged-capture-" + uuid4().hex,
            publisher=ControlFileSetPublisher(
                attempt.engine,
                Settings(
                    staging_root=attempt.artifacts.settings.staging_root,
                    nas_artifact_root=attempt.artifacts.settings.nas_artifact_root,
                ),
            ),
        )


def admit(staged, *, service=None, key=None, **changes):
    arguments = (
        dict(
            output_root=staged.root,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
            result_publisher=staged.publisher,
            source_commit="a" * 40,
            idempotency_key=key or staged.key,
            expected_source_revision_id=None,
            expected_resource_version=0,
        )
        | changes
    )
    return admit_staged_kakao_capture_source(
        service or staged.attempt.service, staged.data.reserved.attempt_id, **arguments
    )


def _verified_inventory(staged):
    pointer = staged.data.inventory_pointer
    opened = staged.attempt.artifacts.open_verified_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        max_bytes=4 * 1024 * 1024,
    )
    with opened.stream as stream:
        return CaptureInventory.model_validate_json(stream.read())


def _stage_proposal(staged, proposal):
    for name, contents in {
        "outputs/result.json": proposal.result_bytes,
        "outputs/room-report.json": proposal.report_bytes,
        "outputs/normalization.json": proposal.normalization_bytes,
    }.items():
        (staged.workspace / name).write_bytes(contents)


def test_built_room_receipts_become_one_canonical_source(staged):
    data = staged.data
    proposal = build_partial_room_capture(
        data.command,
        data.cap.capability,
        _verified_inventory(staged),
        source=data.raw,
        evidence=PartialRoomEvidence(
            started_at=data.report.observed_start_at,
            ended_at=data.report.observed_end_at,
            attachments=data.report.attachments,
        ),
    )
    _stage_proposal(staged, proposal)
    accepted = admit(staged)
    photos = accepted.resolution.admission.attachments
    assert len(accepted.resolution.rows) == len(photos) == 2
    assert photos[0].original == photos[1].original
    assert photos[0].attachment_id != photos[1].attachment_id
    assert admit(staged).replayed


def test_scoped_downloads_align_to_distinct_rows_and_replay_through_source_admission(staged):
    data = staged.data
    inventory = _verified_inventory(staged)
    raw_csv = csv_bytes(
        [
            ["2026-11-16 12:00:00", "anonymous", message]
            for message in ("질문\n이어서", "사진", "사진", "답변")
        ]
    )
    (staged.workspace / "outputs/source.csv").write_bytes(raw_csv)
    image = photo()
    page = ManualDocument.model_validate(document(GROUPS))
    photos = tuple(
        RoomPhotoReceipt(
            relative_path=f"outputs/photo-{index}.bin",
            sha256=sha256(image),
            size_bytes=len(image),
            target=target,
            document=page,
        )
        for index, target in enumerate((TARGET, OTHER_PHOTO), 1)
    )
    for receipt in photos:
        path = staged.workspace / receipt.relative_path
        path.write_bytes(image)
        path.chmod(0o640)
    evidence = OpenRoomDownloadEvidence(
        raw_csv=CsvMember(
            relative_path="outputs/source.csv", sha256=sha256(raw_csv), size_bytes=len(raw_csv)
        ),
        started_at=data.report.observed_start_at,
        ended_at=data.report.observed_end_at,
        expected_room=("channel1", "room1"),
        csv_document=page,
        photos=photos,
    )
    reads = []

    def read(receipt):
        reads.append(receipt.relative_path)
        return (staged.workspace / receipt.relative_path).read_bytes()

    def build(observed):
        return build_open_room_proposal(
            data.command,
            data.cap.capability,
            inventory,
            source=raw_csv,
            evidence=observed,
            read_photo=read,
        )

    for insufficient in (
        replace(evidence, expected_room=("channel1", "room2")),
        replace(evidence, photos=(photos[0], photos[1].model_copy(update={"target": TARGET}))),
        replace(evidence, csv_document=None),
    ):
        incomplete = build(insufficient)
        assert not incomplete.report.attachments
        assert incomplete.report.unresolved_attachment_bubbles == 2
    assert reads == []
    with pytest.raises(ValueError, match="CAPTURE_DOWNLOAD_INVALID"):
        build(
            replace(
                evidence, photos=(photos[0].model_copy(update={"relative_path": "../photo.bin"}),)
            )
        )
    with pytest.raises(ValueError, match="CAPTURE_DOWNLOAD_MISMATCH"):
        build(
            replace(evidence, photos=(photos[0].model_copy(update={"sha256": sha256(b"wrong")}),))
        )
    reads.clear()
    proposal = build(evidence)
    assert [item.row_ordinal for item in proposal.report.attachments] == [2, 3]
    assert all(item.association == "SEQUENCE_INFERRED" for item in proposal.report.attachments)
    assert reads == [receipt.relative_path for receipt in photos]
    assert proposal.result.status == "PARTIAL"
    assert build(evidence).report_bytes == proposal.report_bytes
    _stage_proposal(staged, proposal)

    accepted = admit(staged)
    saved = accepted.resolution.admission.attachments
    assert len(accepted.resolution.rows) == 4
    assert len(saved) == 2 and saved[0].attachment_id != saved[1].attachment_id
    assert saved[0].original == saved[1].original
    assert admit(staged).replayed


def test_open_room_worker_receipt_admits_without_materializing_extra_proposals(staged):
    data = staged.data
    room = ("channel-one", "room-one")
    attempts = staged.attempt.service
    prepared = attempts.prepare_auto_room(
        data.reserved.attempt_id, space_key="scope", expected_room=room
    )
    assert prepared.command == data.command
    with pytest.raises(KakaoArchiveError, match="CAPTURE_IDENTITY_MISMATCH"):
        attempts.prepare_auto_room(
            data.reserved.attempt_id, space_key="scope", expected_room=(room[0], "other")
        )
    groups = [
        (kind, value.replace("/channel1/", "/channel-one/").replace("/room1/", "/room-one/"))
        for kind, value in GROUPS
    ]
    page = ManualDocument.model_validate(
        document(groups, path="/space/scope/channel/channel-one/chats")
    )
    raw = csv_bytes(
        [
            ["2026-11-16 12:00:00", "anonymous", message]
            for message in ("질문\n이어서", "사진", "사진", "답변")
        ]
    )
    outputs = staged.workspace / "outputs"
    # The source owner, not the worker, creates C1 documents from the protected receipt.
    for name in ("result.json", "room-report.json", "normalization.json"):
        (outputs / name).unlink()
    (outputs / "source.csv").write_bytes(raw)
    image = photo()
    path = outputs / "photo-1.bin"
    path.write_bytes(image)
    path.chmod(0o640)
    fixed = OpenRoomDownloadReceipt(
        command_sha256=data.command_pointer.sha256,
        started_at=data.report.observed_start_at,
        ended_at=data.report.observed_end_at,
        raw_csv=CsvMember(
            relative_path="outputs/source.csv", sha256=sha256(raw), size_bytes=len(raw)
        ),
        csv_document=page,
        photos=(
            RoomPhotoReceipt(
                relative_path="outputs/photo-1.bin",
                sha256=sha256(image),
                size_bytes=len(image),
                target=groups[1][1],
                document=page,
            ),
        ),
        unresolved_visible_bubbles=1,
    )
    receipt = outputs / "open-room.json"

    def accept(expected):
        return admit_staged_kakao_open_room(
            staged.attempt.service,
            data.reserved.attempt_id,
            output_root=staged.root,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
            expected_room=expected,
            result_publisher=staged.publisher,
            source_commit="a" * 40,
            idempotency_key=staged.key,
            expected_source_revision_id=None,
            expected_resource_version=0,
        )

    receipt.write_bytes(fixed.model_copy(update={"command_sha256": sha256(b"another")}).encoded())
    receipt.chmod(0o640)
    with pytest.raises(KakaoArchiveError, match="CAPTURE_IDENTITY_MISMATCH"):
        accept(room)
    receipt.write_bytes(fixed.encoded())
    with pytest.raises(KakaoArchiveError, match="CAPTURE_IDENTITY_MISMATCH"):
        accept((room[0], "another-room"))
    browser = staged.attempt.browser
    browser.h.now = max(browser.h.now, datetime.now(UTC))
    runtime = Mock()
    runtime.close.side_effect = lambda intent: closed(browser, intent)
    controller = KakaoOneRoomCollection(
        engine=staged.attempt.engine,
        collections=browser.collection.service,
        browsers=browser.service,
        attempts=attempts,
        runtime=runtime,
        observe_profile=browser.h.profile_proof,
        result_publisher=staged.publisher,
        source_commit="a" * 40,
        output_root=staged.root,
        worker_uid=os.getuid(),
        control_gid=os.getgid(),
    )
    options = dict(
        room=room,
        idempotency_key=staged.key,
        expected_source_revision_id=None,
        expected_resource_version=0,
    )
    saved_receipt = receipt.read_bytes()
    receipt.unlink()
    assert controller.finish(data.reserved.attempt_id, **options) is None
    runtime.running_handle.assert_called_once()
    runtime.close.assert_not_called()
    receipt.write_bytes(saved_receipt)
    receipt.chmod(0o640)
    accepted = controller.finish(data.reserved.attempt_id, **options)
    assert len(accepted.resolution.rows) == 4
    assert len(accepted.resolution.admission.attachments) == 1
    assert not (outputs / "normalization.json").exists()
    with pytest.raises(KakaoArchiveError, match="COLLECTION_TERMINAL"):
        attempts.prepare_auto_room(data.reserved.attempt_id, space_key="scope", expected_room=room)
    status = browser.collection.service.get_status(
        staged.attempt.actor, data.command.source_binding_id, data.command.run_id
    )
    assert status.state == "PARTIAL"
    receipt.unlink()
    assert controller.finish(data.reserved.attempt_id, **options).replayed
    runtime.close.assert_called_once()


@pytest.mark.parametrize("before_close", [True, False])
def test_unreadable_open_room_receipt_fails_only_after_exact_browser_closure(staged, before_close):
    data, browser = staged.data, staged.attempt.browser
    attempts = staged.attempt.service
    room = ("channel-one", "room-one")
    attempts.prepare_auto_room(data.reserved.attempt_id, space_key="scope", expected_room=room)
    receipt = staged.workspace / "outputs" / "open-room.json"
    invalid = b'{"synthetic":"malformed receipt"}'

    def publish_invalid():
        receipt.write_bytes(invalid)
        receipt.chmod(0o640)

    if before_close:
        publish_invalid()

    def confirm_close(intent):
        assert (
            browser.collection.service.get_status(
                staged.attempt.actor, data.command.source_binding_id, data.command.run_id
            ).state
            == "COLLECTING"
        )
        if not before_close:
            publish_invalid()
        return closed(browser, intent)

    runtime = Mock()
    runtime.running_handle.side_effect = KakaoCollectionBrowserRuntimeError("ATTEMPT_CLOSED")
    runtime.close.side_effect = confirm_close
    browser.h.now = max(browser.h.now, datetime.now(UTC))
    owner = KakaoOneRoomCollection(
        engine=staged.attempt.engine,
        collections=browser.collection.service,
        browsers=browser.service,
        attempts=attempts,
        runtime=runtime,
        observe_profile=browser.h.profile_proof,
        result_publisher=staged.publisher,
        source_commit="a" * 40,
        output_root=staged.root,
        worker_uid=os.getuid(),
        control_gid=os.getgid(),
    )
    before = counts(staged.attempt)
    assert KakaoCollectionContinuation(owner).advance_once() == "FAILED"
    assert KakaoCollectionContinuation(owner).advance_once() == "IDLE"
    status = owner.collections.get_status(
        staged.attempt.actor, data.command.source_binding_id, data.command.run_id
    )
    assert status.state == "FAILED"
    assert attempts.get_attempt(data.reserved.attempt_id).state == "COMMAND_READY"
    assert counts(staged.attempt) == before and receipt.read_bytes() == invalid
    runtime.close.assert_called_once()
    runtime.ensure_started.assert_not_called()


def test_actual_files_admit_duplicate_occurrences_and_replay_without_workspace(staged):
    with Session(staged.attempt.engine) as session, session.begin():
        session.get(ApiSessionRecord, staged.attempt.actor.session_id).revoked_at = datetime.now(
            UTC
        )
    sessions_before, _ = counts(staged.attempt)
    first = admit(staged)
    assert len(first.resolution.rows) == 2
    assert len({row.occurrence_id for row in first.resolution.rows}) == 2
    photos = first.resolution.admission.attachments
    assert len(photos) == 2 and photos[0].attachment_id != photos[1].attachment_id
    assert photos[0].original == photos[1].original
    before = counts(staged.attempt)
    assert before[0] == sessions_before
    for name in staged.files:
        (staged.workspace / name).unlink()
    (staged.workspace / "outputs").rmdir()
    staged.workspace.rmdir()
    staged.root.rmdir()
    again = admit(staged)
    assert again.replayed and first.resolution == again.resolution
    assert counts(staged.attempt) == before
    with Session(staged.attempt.engine) as session:
        assert session.get(Task, staged.data.reserved.task_id).state == "LOCAL_ACCEPTED"


def test_local_composition_recovers_source_committed_before_task_adoption(staged, monkeypatch):
    accepted = []

    def stopped(_access, _attempt_id, source_revision_id):
        accepted.append(source_revision_id)
        raise RuntimeError("synthetic process stop after source commit")

    monkeypatch.setattr(staged.attempt.service, "accept_source_revision", stopped)
    with pytest.raises(RuntimeError, match="after source commit"):
        admit(staged)
    for name in staged.files:
        (staged.workspace / name).unlink()
    before = counts(staged.attempt)
    restarted = KakaoCollectionAttemptService(
        staged.attempt.engine,
        artifacts=staged.attempt.artifacts,
        profile_id=staged.attempt.service.profile_id,
        adapter_release_sha256=staged.attempt.service.adapter_sha256,
    )
    recovered = admit(staged, service=restarted)
    assert recovered.replayed and recovered.resolution.source_revision_id == accepted[0]
    assert counts(staged.attempt) == before


def test_result_publication_recovers_before_attempt_adoption_without_result_files(
    staged, monkeypatch
):
    published = []

    def stopped(_attempt_id, pointer):
        published.append(pointer)
        raise RuntimeError("synthetic process stop after result publication")

    monkeypatch.setattr(staged.attempt.service, "accept_result", stopped)
    with pytest.raises(RuntimeError, match="after result publication"):
        admit(staged)
    assert len(published) == 1
    with Session(staged.attempt.engine) as session:
        assert session.get(Attempt, staged.data.reserved.attempt_id).state == "COMMAND_READY"
    for name in ("outputs/result.json", "outputs/room-report.json"):
        (staged.workspace / name).unlink()
    restarted = KakaoCollectionAttemptService(
        staged.attempt.engine,
        artifacts=staged.attempt.artifacts,
        profile_id=staged.attempt.service.profile_id,
        adapter_release_sha256=staged.attempt.service.adapter_sha256,
    )
    result = admit(staged, service=restarted)
    assert result.resolution.admission.authority.capture_result == published[0]
    before = counts(staged.attempt)
    assert admit(staged, service=restarted).replayed
    assert counts(staged.attempt) == before


@pytest.mark.parametrize(
    "status,error", [("FAILED", "UI_CHANGED"), ("PAUSED", None), ("CANCELLED", None)]
)
def test_non_successful_worker_result_is_stored_but_never_becomes_source(staged, status, error):
    failed = staged.data.result.model_copy(
        update={"status": status, "report": None, "error_code": error}
    )
    path = staged.workspace / "outputs/result.json"
    path.write_bytes(canonical_json_bytes(failed.model_dump(mode="json")))
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        admit(staged)
    with Session(staged.attempt.engine) as session:
        row = session.get(Attempt, staged.data.reserved.attempt_id)
        assert (row.state, row.result_status, row.error_code) == ("RESULT_ACCEPTED", status, error)
        original_pointer = (
            row.result_artifact_id,
            row.result_artifact_revision_id,
            row.result_sha256,
        )
    before = counts(staged.attempt)
    # A changed local success cannot overwrite an accepted FAILED/PAUSED/CANCELLED.
    path.write_bytes(staged.files["outputs/result.json"])
    with pytest.raises(KakaoArchiveError, match="AUTHORITY_REQUIRED"):
        admit(staged)
    assert counts(staged.attempt) == before
    with Session(staged.attempt.engine) as session:
        row = session.get(Attempt, staged.data.reserved.attempt_id)
        assert (
            row.result_artifact_id,
            row.result_artifact_revision_id,
            row.result_sha256,
        ) == original_pointer
        assert (row.result_status, row.error_code) == (status, error)


@pytest.mark.parametrize(
    "corruption",
    [
        "invalid-json",
        "noncanonical-result",
        "wrong-execution",
        "wrong-room",
        "report-tamper",
        "noncanonical-report",
        "oversized-report",
        "oversized-result",
    ],
)
def test_invalid_result_is_rejected_before_publishing_anything(staged, corruption):
    from eom_identifiers import sha256_bytes

    result = staged.data.result
    result_path = staged.workspace / "outputs/result.json"
    if corruption == "invalid-json":
        result_path.write_bytes(b"not JSON")
    elif corruption == "noncanonical-result":
        result_path.write_bytes(staged.files["outputs/result.json"] + b"\n")
    elif corruption == "wrong-execution":
        result = result.model_copy(
            update={
                "execution": result.execution.model_copy(
                    update={"fence": result.execution.fence + 1}
                )
            }
        )
    elif corruption == "wrong-room":
        result = result.model_copy(update={"room_id": "kakaoroom_" + "f" * 32})
    elif corruption == "report-tamper":
        path = staged.workspace / "outputs/room-report.json"
        path.write_bytes(b"x" * path.stat().st_size)
    elif corruption == "noncanonical-report":
        path = staged.workspace / "outputs/room-report.json"
        raw = path.read_bytes() + b"\n"
        path.write_bytes(raw)
        result = result.model_copy(
            update={
                "report": result.report.model_copy(
                    update={"size_bytes": len(raw), "sha256": sha256_bytes(raw)}
                )
            }
        )
    elif corruption == "oversized-report":
        result = result.model_copy(
            update={"report": result.report.model_copy(update={"size_bytes": 4 * 1024 * 1024 + 1})}
        )
    else:
        result_path.write_bytes(b"x" * 32769)
    if result != staged.data.result:
        result_path.write_bytes(canonical_json_bytes(result.model_dump(mode="json")))
    before = counts(staged.attempt)
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_INVALID"):
        admit(staged)
    assert counts(staged.attempt) == before
    with Session(staged.attempt.engine) as session:
        assert session.get(Attempt, staged.data.reserved.attempt_id).state == "COMMAND_READY"


@pytest.mark.parametrize(
    "name", ["outputs/source.csv", "outputs/normalization.json", "outputs/photo-1.png"]
)
def test_changed_actual_file_never_completes_source_adoption(staged, name):
    path = staged.workspace / name
    raw = path.read_bytes()
    path.write_bytes(b"x" * len(raw))
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_INVALID"):
        admit(staged)
    with Session(staged.attempt.engine) as session:
        assert session.get(Task, staged.data.reserved.task_id).state == "RUNNING"


def test_configured_root_never_falls_back_to_another_directory(staged):
    before = counts(staged.attempt)
    with pytest.raises(KakaoArchiveError, match="EVIDENCE_INVALID"):
        admit(staged, output_root=staged.root / "not-the-installed-root")
    assert counts(staged.attempt) == before


def test_current_permission_is_rechecked_after_actual_file_io(staged, monkeypatch):
    before = counts(staged.attempt)
    original = capture_inputs.read_protected

    def read(*args, **kwargs):
        raw = original(*args, **kwargs)
        with Session(staged.attempt.engine) as session, session.begin():
            session.get(OperatorRecord, staged.attempt.actor.operator_id).status = "DISABLED"
        return raw

    monkeypatch.setattr(capture_inputs, "read_protected", read)
    with pytest.raises(KakaoArchiveError, match="PERMISSION_DENIED"):
        admit(staged)
    assert counts(staged.attempt) == before


def test_two_local_consumers_publish_one_canonical_source(staged):
    barrier = Barrier(2)

    def call(_):
        barrier.wait(timeout=15)
        return admit(staged)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(call, range(2)))
    assert first.resolution == second.resolution and first.manifest == second.manifest
    with Session(staged.attempt.engine) as session:
        assert session.get(Task, staged.data.reserved.task_id).state == "LOCAL_ACCEPTED"


@pytest.mark.parametrize(
    "change", [{"expected_resource_version": 1}, {"idempotency_key": "different-original-key"}]
)
def test_completed_source_keeps_original_key_and_precondition(staged, change):
    admit(staged)
    before = counts(staged.attempt)
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        admit(staged, **change)
    assert counts(staged.attempt) == before
