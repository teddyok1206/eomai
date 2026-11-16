"""Synthetic collector contracts only; no Kakao login, selectors or network claims."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_kakao_archive_contracts.capture import (
    SCHEMA_SHA256,
    CaptureAttachment,
    CaptureCapability,
    CaptureCommand,
    CaptureInventory,
    CaptureResult,
    CaptureRoomReport,
    CollectionProgress,
    CsvMember,
    InventoryRoom,
    InventoryScope,
    UnresolvedRoom,
    capture_recovery,
    room_capture_members,
    transition_collection,
    validate_capture_contract,
    validate_capture_inputs,
    validate_capture_result,
)
from eom_kakao_archive_contracts.execution import WorkerExecution
from eom_kakao_archive_contracts.kakao_remote import ProfileFence, ProfileStopReceipt
from eom_kakao_archive_contracts.render import LocalMember, RenderExecution, canonical_bytes, sha256
from jsonschema import Draft202012Validator
from pydantic import ValidationError

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def identity(prefix, number=1):
    return f"{prefix}_{number:032x}"


def change(model, **updates):
    return type(model).model_validate({**model.model_dump(), **updates})


def member(path, value=None, media="application/json", size=None):
    raw = (
        b"synthetic-private-evidence"
        if value is None
        else canonical_bytes(value.model_dump(mode="json"))
    )
    return LocalMember(
        relative_path=path, sha256=sha256(raw), size_bytes=size or len(raw), media_type=media
    )


def execution(number=1, attempt=1, fence=3):
    return WorkerExecution(
        command_id=identity("kakaocommand", number),
        task_id=identity("kakaotask", number),
        attempt_id=identity("kakaoattempt", number),
        attempt_number=attempt,
        fence=fence,
    )


def capability(**updates):
    values = dict(
        source_binding_id=identity("kakaobinding"),
        capability_revision_id=identity("kakaocapabilityrev"),
        adapter_release_sha256=sha256(b"release"),
        observed_at=NOW - timedelta(hours=1),
        channel_verified=True,
        room_identity="manual_binding",
        message_identity="unknown",
        csv_scope="full_accessible_history",
        csv_order="ascending",
        source_timezone="Asia/Seoul",
        direction_evidence="dom_verified",
        album_enumeration="verified",
        original_download="verified_ui_download",
        opening_marks_read="unknown",
        visible_scope_ids=("open", "closed"),
        evidence=(member("inputs/channel.json"),),
    )
    return CaptureCapability.model_validate({**values, **updates})


def command(cap=None, inventory=None, **updates):
    cap = cap or capability()
    values = dict(
        execution=execution(1 if inventory is None else 2),
        run_id=identity("kakaorun"),
        source_binding_id=cap.source_binding_id,
        profile_id=identity("kakaoprofile"),
        browser_run_id=identity("kakaobrowserrun"),
        adapter_release_sha256=cap.adapter_release_sha256,
        capability_revision_id=cap.capability_revision_id,
        capability=member("inputs/capability.json", cap),
        issued_at=NOW,
        operation="INVENTORY" if inventory is None else "CAPTURE_ROOM",
        requested_scope_ids=cap.visible_scope_ids,
        inventory_revision_id=identity("kakaoinventoryrev"),
        inventory=member("inputs/inventory.json", inventory) if inventory else None,
        room_id=identity("kakaoroom") if inventory else None,
        snapshot_revision_id=identity("kakaosnapshotrev") if inventory else None,
        normalization_revision_id=identity("kakaonormalizationrev") if inventory else None,
    )
    return CaptureCommand.model_validate({**values, **updates})


def inventory(**updates):
    values = dict(
        execution=execution(),
        run_id=identity("kakaorun"),
        source_binding_id=identity("kakaobinding"),
        inventory_revision_id=identity("kakaoinventoryrev"),
        inventory_started_at=NOW,
        inventory_finished_at=NOW + timedelta(minutes=1),
        reconciliation_pass_at=NOW + timedelta(minutes=2),
        scopes=tuple(
            InventoryScope(
                scope_id=scope,
                filters_cleared=True,
                end_reached=True,
                pending_loading=False,
                stabilization_completed=True,
                new_rooms_on_stabilization=0,
                evidence=member(f"outputs/{scope}.json"),
            )
            for scope in ("open", "closed")
        ),
        rooms=(
            InventoryRoom(
                room_id=identity("kakaoroom"),
                scope_ids=("open",),
                identity_level="manual_binding",
                evidence=member("outputs/room.json"),
            ),
        ),
        unresolved=(),
        inventory_complete=True,
    )
    return CaptureInventory.model_validate({**values, **updates})


def attachment(number=1, **updates):
    values = dict(
        attachment_id=identity("kakaoattachment", number),
        attachment_revision_id=identity("kakaoattachmentrev", number),
        row_ordinal=1,
        album_ordinal=number,
        association="SOURCE_VERIFIED",
        availability="available",
        quality_level="original_verified",
        member=member("outputs/photo.png", media="image/png"),
        width_px=640,
        height_px=480,
        failure_reason=None,
    )
    return CaptureAttachment.model_validate({**values, **updates})


def room_report(cmd=None, **updates):
    cmd = cmd or command(inventory=inventory())
    values = dict(
        execution=cmd.execution,
        run_id=cmd.run_id,
        source_binding_id=cmd.source_binding_id,
        room_id=cmd.room_id,
        inventory_revision_id=cmd.inventory_revision_id,
        snapshot_revision_id=cmd.snapshot_revision_id,
        normalization_revision_id=cmd.normalization_revision_id,
        observed_start_at=NOW,
        observed_end_at=NOW + timedelta(minutes=1),
        raw_csv=CsvMember(
            relative_path="outputs/source.csv",
            sha256=sha256(b"DATE,USER,MESSAGE\r\n"),
            size_bytes=19,
        ),
        normalization=member("outputs/normalization.json"),
        csv_scope="full_accessible_history",
        source_order="ascending",
        source_timezone="Asia/Seoul",
        direction_evidence="dom_verified",
        csv_rows=2,
        unknown_sender_rows=0,
        first_source_at_utc=NOW - timedelta(days=1),
        last_source_at_utc=NOW - timedelta(minutes=5),
        attachment_bubbles_observed=1,
        attachment_inventory_complete=True,
        unresolved_attachment_bubbles=0,
        attachments=(attachment(),),
        room_complete=True,
    )
    return CaptureRoomReport.model_validate({**values, **updates})


def result(cmd, report_value=None, **updates):
    report = report_value
    complete = (
        report.inventory_complete
        if isinstance(report, CaptureInventory)
        else report.room_complete
        if report
        else False
    )
    values = dict(
        execution=cmd.execution,
        run_id=cmd.run_id,
        source_binding_id=cmd.source_binding_id,
        room_id=cmd.room_id,
        command_sha256=sha256(canonical_bytes(cmd.model_dump(mode="json"))),
        adapter_release_sha256=cmd.adapter_release_sha256,
        capability_revision_id=cmd.capability_revision_id,
        status=("COMPLETED" if complete else "PARTIAL") if report else "FAILED",
        report=member("outputs/report.json", report) if report else None,
        error_code=None if report else "AUTH_REQUIRED",
    )
    return CaptureResult.model_validate({**values, **updates})


def stop_values(cmd, mode="AUTO"):
    profile = ProfileFence(
        schema_version="kakao-profile-fence/1.0",
        profile_id=cmd.profile_id,
        browser_run_id=cmd.browser_run_id,
        fence_epoch=cmd.execution.fence,
        mode=mode,
    )
    stopped = ProfileStopReceipt(
        schema_version="kakao-profile-stop-receipt/1.0",
        profile_id=cmd.profile_id,
        browser_run_id=cmd.browser_run_id,
        fence_epoch=cmd.execution.fence,
        process_stopped=True,
        profile_lock_released=True,
        gateway_stopped=True,
        checkpoint_committed=True,
        observed_at=NOW,
    )
    return profile, stopped


def test_schema_mirror_hash_and_public_execution_alias():
    source = (ROOT / "schemas/kakao-archive/worker-collection-v1.schema.json").read_bytes()
    packaged = (
        ROOT
        / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas"
        / "worker-collection-v1.schema.json"
    ).read_bytes()
    assert source == packaged and sha256(source) == SCHEMA_SHA256
    Draft202012Validator.check_schema(json.loads(source))
    assert WorkerExecution is RenderExecution


def test_successful_inventory_and_room_protocols_pin_all_inputs_and_outputs():
    cap, inv = capability(), inventory()
    listing = command(cap)
    assert len(validate_capture_inputs(listing, cap)) == 2
    proposal = result(listing, inv)
    assert (
        len(validate_capture_result(listing, proposal, inv, capability=cap, current_fence=3)) == 4
    )
    capture = command(cap, inv)
    report = room_report(capture)
    assert len(validate_capture_inputs(capture, cap, inv)) == 6
    files = validate_capture_result(
        capture, result(capture, report), report, capability=cap, current_fence=3
    )
    assert [value.relative_path for value in files] == [
        "outputs/report.json",
        "outputs/source.csv",
        "outputs/normalization.json",
        "outputs/photo.png",
    ]
    for kind, value in (
        ("capability", cap),
        ("command", capture),
        ("inventory", inv),
        ("room-report", report),
        ("result", proposal),
    ):
        validate_capture_contract(kind, value.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel_verified", False),
        ("observed_at", NOW + timedelta(days=1)),
    ],
)
def test_capability_evidence_does_not_grant_channel_or_future_verification(field, value):
    cap = capability(**{field: value})
    with pytest.raises(ValueError, match="CAPABILITY_UNVERIFIED"):
        validate_capture_inputs(command(cap), cap)


@pytest.mark.parametrize(
    "updates",
    [
        {"requested_scope_ids": ("open",)},
        {"source_binding_id": identity("kakaobinding", 2)},
        {"adapter_release_sha256": sha256(b"another release")},
        {"capability_revision_id": identity("kakaocapabilityrev", 2)},
    ],
)
def test_exact_capability_scope_and_release_cannot_be_substituted(updates):
    cap = capability()
    with pytest.raises(ValueError, match="CAPABILITY_UNVERIFIED"):
        validate_capture_inputs(command(cap, **updates), cap)


def test_capability_hash_and_room_membership_are_revalidated():
    cap = capability()
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        validate_capture_inputs(command(cap, capability=member("inputs/capability.json")), cap)
    inv = inventory()
    with pytest.raises(ValueError, match="ROOM_NOT_IN_INVENTORY"):
        validate_capture_inputs(command(cap, inv, room_id=identity("kakaoroom", 2)), cap, inv)
    with pytest.raises(ValueError, match="INVENTORY_REQUIRED"):
        validate_capture_inputs(command(cap, inv), cap)


@pytest.mark.parametrize(
    "change_fields",
    [
        {"filters_cleared": False},
        {"end_reached": False},
        {"pending_loading": True},
        {"stabilization_completed": False},
        {"new_rooms_on_stabilization": 1},
    ],
)
def test_scroll_idle_is_not_inventory_completeness(change_fields):
    inv = inventory()
    scopes = (change(inv.scopes[0], **change_fields), inv.scopes[1])
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        inventory(scopes=scopes)
    partial = inventory(scopes=scopes, inventory_complete=False)
    assert result(command(), partial).status == "PARTIAL"


def test_unresolved_rooms_are_not_dropped_from_coverage():
    unresolved = UnresolvedRoom(
        observation_id="row_2",
        scope_id="open",
        reason="IDENTITY_UNVERIFIED",
        evidence=member("outputs/unresolved.json"),
    )
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        inventory(unresolved=(unresolved,))
    inv = inventory(unresolved=(unresolved,), inventory_complete=False)
    assert inv.unresolved == (unresolved,) and len(inv.rooms) == 1
    with pytest.raises(ValueError, match="OBSERVATION_DUPLICATED"):
        inventory(unresolved=(unresolved, unresolved), inventory_complete=False)
    with pytest.raises(ValueError, match="INVENTORY_SCOPE_INVALID"):
        inventory(unresolved=(change(unresolved, scope_id="hidden"),), inventory_complete=False)


def test_identical_picture_bytes_keep_two_occurrences_and_share_one_member():
    report = room_report(attachments=(attachment(1), attachment(2)))
    assert len(report.attachments) == 2
    assert len(room_capture_members(report)) == 3
    with pytest.raises(ValueError, match="ATTACHMENT_DUPLICATED"):
        room_report(attachments=(attachment(1), attachment(1)))


def test_missing_and_unassociated_pictures_cannot_be_complete():
    absent = attachment(
        availability="expired",
        quality_level="unknown",
        member=None,
        width_px=None,
        height_px=None,
        failure_reason="SOURCE_EXPIRED",
    )
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        room_report(attachments=(absent,))
    assert (
        room_report(attachments=(absent,), room_complete=False).attachments[0].availability
        == "expired"
    )
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        room_report(attachments=(attachment(association="SNAPSHOT_ONLY"),))
    with pytest.raises(ValueError, match="ATTACHMENT_COVERAGE_INVALID"):
        room_report(attachments=(), room_complete=False)
    assert (
        room_report(
            attachments=(), unresolved_attachment_bubbles=1, room_complete=False
        ).unresolved_attachment_bubbles
        == 1
    )


def test_unknown_time_order_direction_is_explicit_partial_not_guessed_from_name():
    report = room_report(
        source_timezone="unknown",
        source_order="unknown",
        direction_evidence="unknown",
        unknown_sender_rows=2,
        first_source_at_utc=None,
        last_source_at_utc=None,
        room_complete=False,
    )
    assert report.source_timezone == "unknown" and report.unknown_sender_rows == 2
    with pytest.raises(ValueError, match="SOURCE_TIME_UNVERIFIED"):
        change(report, first_source_at_utc=NOW)
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        change(report, room_complete=True)


def test_member_collisions_media_and_decoded_dimensions_are_bounded():
    collision = attachment(2, member=change(attachment().member, sha256=sha256(b"different")))
    with pytest.raises(ValueError, match="MEMBER_COLLISION"):
        room_report(attachments=(attachment(), collision))
    with pytest.raises(ValueError, match="IMAGE_INVALID"):
        attachment(member=member("outputs/login.json"))
    with pytest.raises(ValueError, match="IMAGE_INVALID"):
        attachment(width_px=20000, height_px=20000)
    with pytest.raises(ValueError, match="OUTPUT_LOCATION_INVALID"):
        room_report(normalization=member("inputs/normalization.json"))
    images = tuple(
        attachment(
            i, member=member(f"outputs/photo_{i}.png", media="image/png", size=64 * 1024 * 1024)
        )
        for i in range(1, 5)
    )
    with pytest.raises(ValueError, match="BYTES_EXCEEDED"):
        room_report(attachments=images)


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        "/mnt/nas/file.csv",
        "a//b.csv",
        "a/../b.csv",
        "https://example.invalid/x",
        "a\\b.csv",
        "secret?token=value",
    ],
)
def test_worker_paths_never_accept_external_or_parent_locations(path):
    with pytest.raises(ValidationError):
        CsvMember(relative_path=path, sha256=sha256(b"csv"), size_bytes=3)


@pytest.mark.parametrize(
    "updates",
    [
        {"execution": execution(9)},
        {"run_id": identity("kakaorun", 2)},
        {"source_binding_id": identity("kakaobinding", 2)},
        {"room_id": identity("kakaoroom", 2)},
        {"command_sha256": sha256(b"different")},
        {"adapter_release_sha256": sha256(b"different")},
        {"capability_revision_id": identity("kakaocapabilityrev", 2)},
    ],
)
def test_result_does_not_accept_late_or_other_identity(updates):
    cmd, inv = command(), inventory()
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        validate_capture_result(
            cmd, result(cmd, inv, **updates), inv, capability=capability(), current_fence=3
        )


def test_stale_fence_and_changed_result_bytes_fail_closed():
    cmd, inv = command(), inventory()
    with pytest.raises(ValueError, match="STALE_FENCE"):
        validate_capture_result(
            cmd, result(cmd, inv), inv, capability=capability(), current_fence=4
        )
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        validate_capture_result(
            cmd,
            result(cmd, inv, report=member("outputs/report.json")),
            inv,
            capability=capability(),
            current_fence=3,
        )
    with pytest.raises(ValueError, match="COMPLETENESS_INVALID"):
        validate_capture_result(
            cmd, result(cmd, inv, status="PARTIAL"), inv, capability=capability(), current_fence=3
        )


def test_failed_result_is_not_rewritten_and_contains_no_accepted_outputs():
    cmd = command()
    failed = result(cmd)
    assert (
        validate_capture_result(cmd, failed, None, capability=capability(), current_fence=3) == ()
    )
    assert failed.status == "FAILED" and failed.error_code == "AUTH_REQUIRED"
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        change(failed, report=member("outputs/report.json"))


@pytest.mark.parametrize(
    "field", ["cookie", "bearer_token", "nas_path", "database_dsn", "source_body", "download_url"]
)
def test_wire_rejects_secrets_and_body_fields_without_echoing_values(field):
    wire = command().model_dump(mode="json")
    wire[field] = "PRIVATE_VALUE_MUST_NOT_APPEAR"
    with pytest.raises(ValueError) as error:
        validate_capture_contract("command", wire)
    assert str(error.value) == "KAKAO_CAPTURE_SCHEMA_INVALID"
    assert error.value.__suppress_context__ is True
    with pytest.raises(ValidationError):
        CaptureCommand.model_validate(wire)


def test_active_cancel_waits_for_checkpoint_and_process_stop():
    progress = CollectionProgress("QUEUED")
    progress = transition_collection(progress, "CLAIM")
    progress = transition_collection(progress, "INVENTORY_ACCEPTED")
    progress = transition_collection(progress, "CANCEL_REQUESTED")
    assert progress == CollectionProgress("PAUSING", "CANCELLED")
    with pytest.raises(ValueError, match="PRIOR_STOP_UNCONFIRMED"):
        transition_collection(progress, "STOP_CONFIRMED")
    profile, stopped = stop_values(command(), mode="PAUSING")
    with pytest.raises(ValueError, match="PRIOR_STOP_UNCONFIRMED"):
        transition_collection(
            progress,
            "STOP_CONFIRMED",
            profile=profile,
            stopped=change(stopped, process_stopped=False),
            now=NOW,
        )
    finished = transition_collection(
        progress, "STOP_CONFIRMED", profile=profile, stopped=stopped, now=NOW
    )
    assert finished.state == "CANCELLED"
    with pytest.raises(ValueError, match="TRANSITION_INVALID"):
        transition_collection(finished, "RESUME")


@pytest.mark.parametrize(
    "error,action",
    [
        ("AUTH_REQUIRED", "WAIT_AUTH"),
        ("ACCESS_DENIED", "WAIT_AUTHORITY_CHANGE"),
        ("UI_CHANGED", "WAIT_ADAPTER_REVIEW"),
        ("HASH_MISMATCH", "WAIT_ADAPTER_REVIEW"),
        ("DISK_FULL", "WAIT_STORAGE"),
        ("RATE_LIMITED", "WAIT_RATE_LIMIT"),
        ("TIMEOUT", "RECONCILE_SAME_ATTEMPT"),
        ("INVALID_INPUT", "STOP"),
    ],
)
def test_recovery_never_blindly_relaunches_unknown_work(error, action):
    cmd = command()
    assert capture_recovery(cmd, error, outcome="UNKNOWN", now=NOW) == "RECONCILE_SAME_ATTEMPT"
    assert capture_recovery(cmd, error, outcome="TERMINAL_FAILED", now=NOW) == action
    assert capture_recovery(cmd, error, outcome="LOCAL_ACCEPTED", now=NOW) == "RECOVER_PUBLICATION"
    assert capture_recovery(cmd, error, outcome="PUBLISHED", now=NOW) == "RECOVER_PUBLICATION"


def test_transient_retry_is_bounded_and_requires_exact_stopped_profile():
    cmd = command()
    profile, stopped = stop_values(cmd)
    assert (
        capture_recovery(cmd, "NETWORK_TRANSIENT", outcome="TERMINAL_FAILED", now=NOW)
        == "WAIT_PRIOR_STOP"
    )
    assert (
        capture_recovery(
            cmd,
            "NETWORK_TRANSIENT",
            outcome="TERMINAL_FAILED",
            now=NOW,
            profile=profile,
            stopped=stopped,
        )
        == "RETRY_NEW_ATTEMPT"
    )
    assert (
        capture_recovery(
            cmd,
            "NETWORK_TRANSIENT",
            outcome="TERMINAL_FAILED",
            now=NOW,
            profile=profile,
            stopped=change(stopped, profile_lock_released=False),
        )
        == "WAIT_PRIOR_STOP"
    )
    assert (
        capture_recovery(
            cmd,
            "NETWORK_TRANSIENT",
            outcome="TERMINAL_FAILED",
            now=NOW,
            profile=change(profile, browser_run_id=identity("kakaobrowserrun", 2)),
            stopped=stopped,
        )
        == "WAIT_PRIOR_STOP"
    )
    exhausted = command(execution=execution(attempt=4))
    assert (
        capture_recovery(
            exhausted,
            "NETWORK_TRANSIENT",
            outcome="TERMINAL_FAILED",
            now=NOW,
            profile=profile,
            stopped=stopped,
        )
        == "STOP"
    )


def test_large_inventory_has_indexable_distinct_ids_and_no_payload_duplication():
    rooms = tuple(
        InventoryRoom(
            room_id=identity("kakaoroom", i),
            scope_ids=("open",),
            identity_level="manual_binding",
            evidence=member("outputs/room.json"),
        )
        for i in range(1, 10001)
    )
    observed = inventory(rooms=rooms)
    assert len(observed.rooms) == 10000
    with pytest.raises(ValueError, match="ROOM_DUPLICATED"):
        inventory(rooms=(*rooms[:-1], rooms[0]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("csv_scope", "unknown"),
        ("csv_scope", "loaded_window"),
        ("csv_order", "unknown"),
        ("source_timezone", "unknown"),
        ("direction_evidence", "unknown"),
        ("album_enumeration", "unknown"),
        ("original_download", "unknown"),
        ("original_download", "best_available"),
    ],
)
def test_result_cannot_upgrade_unverified_capability(field, value):
    cap = capability(**{field: value})
    inv = inventory()
    cmd = command(cap, inv)
    validate_capture_inputs(cmd, cap, inv)
    report = room_report(cmd)
    with pytest.raises(ValueError, match="CAPABILITY_ESCALATION"):
        validate_capture_result(cmd, result(cmd, report), report, capability=cap, current_fence=3)


def test_result_requires_exact_capability_body_not_same_revision_name():
    cap = capability()
    cmd = command(cap)
    inv = inventory()
    forged = change(cap, original_download="unknown")
    with pytest.raises(ValueError, match="MANIFEST_HASH_MISMATCH"):
        validate_capture_result(cmd, result(cmd, inv), inv, capability=forged, current_fence=3)
    unknown = capability(room_identity="unknown")
    cmd = command(unknown)
    with pytest.raises(ValueError, match="CAPABILITY_ESCALATION"):
        validate_capture_result(cmd, result(cmd, inv), inv, capability=unknown, current_fence=3)


def test_unknown_result_can_remain_partial_under_known_capability():
    cap = capability()
    cmd = command(cap, inventory())
    report = room_report(
        cmd,
        source_timezone="unknown",
        source_order="unknown",
        csv_scope="unknown",
        direction_evidence="unknown",
        first_source_at_utc=None,
        last_source_at_utc=None,
        room_complete=False,
    )
    assert validate_capture_result(
        cmd, result(cmd, report), report, capability=cap, current_fence=3
    )


def test_unsupported_attachment_stays_in_report_with_explicit_reason():
    unsupported = attachment(
        availability="failed",
        quality_level="unknown",
        member=None,
        width_px=None,
        height_px=None,
        failure_reason="UNSUPPORTED_MEDIA",
    )
    cap = capability()
    cmd = command(cap, inventory())
    report = room_report(cmd, attachments=(unsupported,), room_complete=False)
    assert len(report.attachments) == 1
    assert report.attachments[0].failure_reason == "UNSUPPORTED_MEDIA"
    assert (
        len(
            validate_capture_result(
                cmd, result(cmd, report), report, capability=cap, current_fence=3
            )
        )
        == 3
    )
    with pytest.raises(ValueError, match="ATTACHMENT_FAILURE_INVALID"):
        change(unsupported, failure_reason=None)
