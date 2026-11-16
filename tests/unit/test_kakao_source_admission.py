"""Anonymous accepted-owner fixtures only; no live collector or private account."""

import base64
import csv
import io
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_archive import KakaoAttachmentObservation, KakaoMessageObservation
from eom_catalog_contracts.kakao_media import (
    MEDIA_BLOB_REF,
    MEDIA_FORMAT_REF,
    KakaoMediaBlobReceipt,
)
from eom_catalog_contracts.kakao_question import NORMALIZATION_REF
from eom_catalog_contracts.kakao_snapshot import CSV_FORMAT_REF, SNAPSHOT_REF, KakaoRoomSnapshot
from eom_catalog_contracts.kakao_source import (
    CAPTURE_REF,
    KakaoSourceAdmission,
    KakaoSourceAttachment,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_catalog_service.kakao_source_resolution import (
    build_source_resolution,
    validate_capture_source,
)
from eom_catalog_service.kakao_source_service import KakaoSourceService
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_kakao_archive_contracts.capture import (
    CaptureAttachment,
    CaptureCapability,
    CaptureCommand,
    CaptureResult,
    CaptureRoomReport,
    CsvMember,
)
from eom_kakao_archive_contracts.execution import WorkerExecution
from eom_kakao_archive_contracts.render import LocalMember
from eom_protocol.artifact_members import ArtifactMemberPointer

NOW = datetime(2026, 11, 15, 10, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def identity(prefix):
    return prefix + "_" + uuid4().hex


def source_case(
    *,
    binding=None,
    room=None,
    texts=("동일한 질문", "동일한 질문"),
    roles=None,
    provider_ids=False,
    direction="dom_verified",
    scope="full_accessible_history",
    context=True,
    publish=None,
    previous=None,
):
    binding, room = binding or identity("kakaobinding"), room or identity("kakaoroom")
    sid, nid = identity("kakaosnapshotrev"), identity("kakaonormalizationrev")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("DATE", "USER", "MESSAGE"))
    for value in texts:
        writer.writerow(("2026-11-15 18:00:00", "private-name", value))
    raw = output.getvalue().encode("utf-8-sig")
    roles = roles or ("student",) * len(texts)
    norm = parse_kakao_csv(
        raw,
        source_binding_id=binding,
        room_id=room,
        snapshot_revision_id=sid,
        normalization_revision_id=nid,
        observed_at_utc=NOW,
        source_timezone="Asia/Seoul",
        source_order="ascending",
        context_start_verified=context,
        context_end_verified=context,
        observations=tuple(
            KakaoMessageObservation(
                row_ordinal=i,
                role=role,
                role_evidence_id="direction-observed" if role != "unknown" else None,
                source_message_id=f"observed-{i}" if provider_ids else None,
                kind="text",
            )
            for i, role in enumerate(roles, 1)
        ),
    )
    snapshot = KakaoRoomSnapshot(
        source_binding_id=binding,
        room_id=room,
        snapshot_revision_id=sid,
        source_sha256=sha256_bytes(raw),
        source_bytes=len(raw),
        observed_at_utc=NOW,
        csv_scope=scope,
    )

    def local(name, data, media="application/json"):
        return LocalMember(
            relative_path=name, sha256=sha256_bytes(data), size_bytes=len(data), media_type=media
        )

    cap = CaptureCapability(
        source_binding_id=binding,
        capability_revision_id=identity("kakaocapabilityrev"),
        adapter_release_sha256=sha256_bytes(b"synthetic release"),
        observed_at=NOW - timedelta(minutes=2),
        channel_verified=True,
        room_identity="manual_binding",
        message_identity="stable_source_id" if provider_ids else "unknown",
        csv_scope=scope,
        csv_order="ascending",
        source_timezone="Asia/Seoul",
        direction_evidence=direction,
        album_enumeration="verified",
        original_download="verified_ui_download",
        opening_marks_read="unknown",
        visible_scope_ids=("open",),
        evidence=(local("inputs/channel.json", b"synthetic proof"),),
    )
    capraw = canonical_json_bytes(cap.model_dump(mode="json"))
    command = CaptureCommand(
        execution=WorkerExecution(
            command_id=identity("kakaocommand"),
            task_id=identity("kakaotask"),
            attempt_id=identity("kakaoattempt"),
            attempt_number=1,
            fence=1,
        ),
        run_id=identity("kakaorun"),
        source_binding_id=binding,
        profile_id=identity("kakaoprofile"),
        browser_run_id=identity("kakaobrowserrun"),
        adapter_release_sha256=cap.adapter_release_sha256,
        capability_revision_id=cap.capability_revision_id,
        capability=local("inputs/capability.json", capraw),
        issued_at=NOW - timedelta(minutes=1),
        operation="CAPTURE_ROOM",
        requested_scope_ids=cap.visible_scope_ids,
        inventory_revision_id=identity("kakaoinventoryrev"),
        inventory=local("inputs/inventory.json", b"synthetic inventory"),
        room_id=room,
        snapshot_revision_id=sid,
        normalization_revision_id=nid,
    )
    normraw = canonical_json_bytes(norm.model_dump(mode="json"))
    complete = (
        direction != "unknown"
        and all(role != "unknown" for role in roles)
        and scope == "full_accessible_history"
    )
    times = [m.sent_at_utc for m in norm.messages if m.sent_at_utc is not None]
    report = CaptureRoomReport(
        execution=command.execution,
        run_id=command.run_id,
        source_binding_id=binding,
        room_id=room,
        inventory_revision_id=command.inventory_revision_id,
        snapshot_revision_id=sid,
        normalization_revision_id=nid,
        observed_start_at=command.issued_at,
        observed_end_at=NOW,
        raw_csv=CsvMember(
            relative_path="outputs/source.csv", sha256=sha256_bytes(raw), size_bytes=len(raw)
        ),
        normalization=local("outputs/normalization.json", normraw),
        csv_scope=scope,
        source_order="ascending",
        source_timezone="Asia/Seoul",
        direction_evidence=direction,
        csv_rows=len(norm.messages),
        unknown_sender_rows=sum(role == "unknown" for role in roles),
        first_source_at_utc=min(times) if times else None,
        last_source_at_utc=max(times) if times else None,
        attachment_bubbles_observed=0,
        attachment_inventory_complete=True,
        unresolved_attachment_bubbles=0,
        attachments=(),
        room_complete=complete,
    )
    commandraw = canonical_json_bytes(command.model_dump(mode="json"))
    reportraw = canonical_json_bytes(report.model_dump(mode="json"))
    result = CaptureResult(
        execution=command.execution,
        run_id=command.run_id,
        source_binding_id=binding,
        room_id=room,
        command_sha256=sha256_bytes(commandraw),
        adapter_release_sha256=cap.adapter_release_sha256,
        capability_revision_id=cap.capability_revision_id,
        status="COMPLETED" if complete else "PARTIAL",
        report=local("outputs/report.json", reportraw),
        error_code=None,
    )
    resultraw = canonical_json_bytes(result.model_dump(mode="json"))
    payloads = {}

    def pointer(name, data, schema, media="application/json"):
        value = (
            publish(name, data, schema, media)
            if publish
            else ArtifactMemberPointer(
                artifact_id=identity("artifact"),
                artifact_revision_id=identity("rev"),
                member_path=name,
                schema_ref=schema,
                media_type=media,
                sha256=sha256_bytes(data),
            )
        )
        payloads[(value.artifact_id, value.artifact_revision_id, value.member_path)] = data
        return value

    admission = KakaoSourceAdmission(
        source_binding_id=binding,
        room_id=room,
        snapshot_revision_id=sid,
        normalization_revision_id=nid,
        expected_source_revision_id=previous.source_revision_id if previous else None,
        expected_resource_version=previous.resource_version if previous else 0,
        source=pointer("source.csv", raw, CSV_FORMAT_REF, "text/csv"),
        snapshot=pointer(
            "snapshot.json", canonical_json_bytes(snapshot.model_dump(mode="json")), SNAPSHOT_REF
        ),
        normalization=pointer("normalization.json", normraw, NORMALIZATION_REF),
        authority=dict(
            run_id=command.run_id,
            attempt_id=command.execution.attempt_id,
            fence=command.execution.fence,
            command_sha256=sha256_bytes(commandraw),
            capability_revision_id=cap.capability_revision_id,
            adapter_release_sha256=cap.adapter_release_sha256,
            command=pointer("command.json", commandraw, CAPTURE_REF),
            capability=pointer("capability.json", capraw, CAPTURE_REF),
            capture_report=pointer("report.json", reportraw, CAPTURE_REF),
            capture_result=pointer("result.json", resultraw, CAPTURE_REF),
        ),
        attachments=(),
    )
    return (
        admission,
        dict(
            snapshot=snapshot,
            normalization=norm,
            source=raw,
            command_bytes=commandraw,
            capability_bytes=capraw,
            report_bytes=reportraw,
            result_bytes=resultraw,
            media_receipts={},
        ),
        payloads,
    )


def resolution(admission, data, **changes):
    values = dict(
        source_revision_id=identity("kakaosourcerev"),
        command_id=identity("kakaocommand"),
        owner=identity("operator"),
        reserved_at=NOW + timedelta(minutes=1),
    )
    values.update(changes)
    return build_source_resolution(admission, data["normalization"], **values)


def test_source_schemas_and_mirrors_are_exact():
    for key in ("kakao-source-admission-v1", "kakao-source-resolution-v1"):
        entry = CATALOG_SCHEMA_RESOURCES[key]
        raw = (ROOT / entry.canonical_path).read_bytes()
        assert sha256_bytes(raw) == entry.sha256
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
            ).read_bytes()
        )


def test_exact_capture_preserves_duplicate_occurrences_and_replay_allocation():
    admission, data, _ = source_case()
    validate_capture_source(admission, **data)
    first = resolution(admission, data)
    again = resolution(
        admission,
        data,
        source_revision_id=first.source_revision_id,
        command_id=first.command_id,
        owner=first.created_by,
        reserved_at=first.created_at,
    )
    assert first == again
    assert len(first.rows) == 2
    assert len({r.occurrence_id for r in first.rows}) == 2
    assert all(r.association == "SNAPSHOT_ONLY" for r in first.rows)
    assert "private-name" not in canonical_json_bytes(first.model_dump(mode="json")).decode()


def test_new_snapshot_reuses_verified_sequence_without_erasing_old_observations():
    admission, data, _ = source_case()
    old = resolution(admission, data)
    newer, next_data, _ = source_case(
        binding=admission.source_binding_id, room=admission.room_id, previous=old
    )
    current = resolution(
        newer, next_data, previous=old, previous_normalization=data["normalization"]
    )
    assert [r.occurrence_id for r in current.rows] == [r.occurrence_id for r in old.rows]
    assert all(r.association == "SEQUENCE_INFERRED" for r in current.rows)


def test_corrected_roles_mark_evidence_changed_without_replacing_occurrence_identity():
    admission, data, _ = source_case()
    old = resolution(admission, data)
    newer, next_data, _ = source_case(
        binding=admission.source_binding_id,
        room=admission.room_id,
        previous=old,
        roles=("staff", "student"),
    )
    current = resolution(
        newer, next_data, previous=old, previous_normalization=data["normalization"]
    )
    assert current.rows[0].occurrence_id == old.rows[0].occurrence_id
    assert current.rows[0].evidence_changed and not current.rows[0].source_content_changed


@pytest.mark.parametrize(
    "fault", ["raw", "normalization", "scope", "fence", "role", "provider_id", "context"]
)
def test_unsupported_or_mismatched_source_cannot_be_accepted(fault):
    if fault == "role":
        admission, data, _ = source_case(direction="unknown")
    elif fault == "context":
        admission, data, _ = source_case(scope="loaded_window", context=True)
    else:
        admission, data, _ = source_case(provider_ids=fault == "provider_id")
    if fault == "raw":
        data["source"] += b"private mutation"
    elif fault == "normalization":
        data["normalization"] = data["normalization"].model_copy(update={"source_bytes": 1})
    elif fault == "scope":
        admission = admission.model_copy(update={"room_id": identity("kakaoroom")})
    elif fault == "fence":
        admission = admission.model_copy(
            update={"authority": admission.authority.model_copy(update={"fence": 2})}
        )
    elif fault == "provider_id":
        # Change the whole capability+command+result hash chain consistently;
        # unsupported row observations still must not become verified IDs.
        import json

        cap = CaptureCapability.model_validate_json(data["capability_bytes"]).model_copy(
            update={"message_identity": "unknown"}
        )
        data["capability_bytes"] = canonical_json_bytes(cap.model_dump(mode="json"))
        cmd = json.loads(data["command_bytes"])
        cmd["capability"].update(
            sha256=sha256_bytes(data["capability_bytes"]), size_bytes=len(data["capability_bytes"])
        )
        data["command_bytes"] = canonical_json_bytes(cmd)
        result_value = json.loads(data["result_bytes"])
        result_value["command_sha256"] = sha256_bytes(data["command_bytes"])
        data["result_bytes"] = canonical_json_bytes(result_value)
        admission = admission.model_copy(
            update={
                "authority": admission.authority.model_copy(
                    update={"command_sha256": result_value["command_sha256"]}
                )
            }
        )
    with pytest.raises(ValueError, match="KAKAO_"):
        validate_capture_source(admission, **data)


def test_unknown_direction_and_partial_context_remain_explicit():
    admission, data, _ = source_case(
        roles=("unknown", "unknown"), direction="unknown", scope="loaded_window", context=False
    )
    validate_capture_source(admission, **data)
    current = resolution(admission, data)
    assert len(current.rows) == 2
    assert data["normalization"].source_order == "ascending"
    assert not data["normalization"].context_end_verified


def test_cross_room_predecessor_and_invalid_previous_rows_fail():
    admission, data, _ = source_case()
    old = resolution(admission, data)
    other, next_data, _ = source_case(binding=admission.source_binding_id, previous=old)
    with pytest.raises(ValueError, match="PRECONDITION"):
        resolution(other, next_data, previous=old, previous_normalization=data["normalization"])


def test_repeated_blob_two_occurrences_validate_and_read_media_only_once(monkeypatch):
    admission, data, payloads = source_case()
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jD1kAAAAASUVORK5CYII="
    )
    receipt = KakaoMediaBlobReceipt(
        source_binding_id=admission.source_binding_id,
        source_sha256=sha256_bytes(raw),
        source_bytes=len(raw),
        media_type="image/png",
        width_px=1,
        height_px=1,
        pixel_count=1,
    )

    def pointer(name, content, schema, media="application/json"):
        result = ArtifactMemberPointer(
            artifact_id=identity("artifact"),
            artifact_revision_id=identity("rev"),
            member_path=name,
            schema_ref=schema,
            media_type=media,
            sha256=sha256_bytes(content),
        )
        payloads[(result.artifact_id, result.artifact_revision_id, result.member_path)] = content
        return result

    image = pointer("original.png", raw, MEDIA_FORMAT_REF, "image/png")
    receipt_pointer = pointer(
        "media.json", canonical_json_bytes(receipt.model_dump(mode="json")), MEDIA_BLOB_REF
    )
    observations = tuple(
        KakaoAttachmentObservation(
            attachment_id=identity("kakaoattachment"),
            attachment_revision_id=identity("kakaoattachmentrev"),
            album_ordinal=1,
            availability="available",
            association="SOURCE_VERIFIED",
        )
        for _ in range(2)
    )
    norm = data["normalization"]
    norm = type(norm).model_validate(
        {
            **norm.model_dump(),
            "messages": tuple(
                message.model_copy(update={"attachments": (observation,)})
                for message, observation in zip(norm.messages, observations, strict=True)
            ),
        }
    )
    normraw = canonical_json_bytes(norm.model_dump(mode="json"))
    norm_pointer = pointer("normalization.json", normraw, NORMALIZATION_REF)
    report = CaptureRoomReport.model_validate_json(data["report_bytes"])
    report = type(report).model_validate(
        {
            **report.model_dump(),
            "normalization": LocalMember(
                relative_path="outputs/normalization.json",
                sha256=sha256_bytes(normraw),
                size_bytes=len(normraw),
                media_type="application/json",
            ),
            "attachment_bubbles_observed": 2,
            "attachments": tuple(
                CaptureAttachment(
                    **obs.model_dump(),
                    row_ordinal=i,
                    quality_level="original_verified",
                    member=LocalMember(
                        relative_path="outputs/photo.png",
                        sha256=image.sha256,
                        size_bytes=len(raw),
                        media_type="image/png",
                    ),
                    width_px=1,
                    height_px=1,
                    failure_reason=None,
                )
                for i, obs in enumerate(observations, 1)
            ),
        }
    )
    reportraw = canonical_json_bytes(report.model_dump(mode="json"))
    result = CaptureResult.model_validate_json(data["result_bytes"])
    result = result.model_copy(
        update={
            "report": LocalMember(
                relative_path="outputs/report.json",
                sha256=sha256_bytes(reportraw),
                size_bytes=len(reportraw),
                media_type="application/json",
            )
        }
    )
    resultraw = canonical_json_bytes(result.model_dump(mode="json"))
    authority = admission.authority.model_copy(
        update={
            "capture_report": pointer("report.json", reportraw, CAPTURE_REF),
            "capture_result": pointer("result.json", resultraw, CAPTURE_REF),
        }
    )
    admission = type(admission).model_validate(
        {
            **admission.model_dump(),
            "normalization": norm_pointer,
            "authority": authority,
            "attachments": tuple(
                KakaoSourceAttachment(
                    attachment_id=obs.attachment_id,
                    attachment_revision_id=obs.attachment_revision_id,
                    original=image,
                    media_receipt=receipt_pointer,
                    quality="ORIGINAL",
                )
                for obs in observations
            ),
        }
    )
    data.update(
        normalization=norm,
        report_bytes=reportraw,
        result_bytes=resultraw,
        media_receipts={obs.attachment_id: receipt for obs in observations},
    )
    validate_capture_source(admission, **data)
    service = object.__new__(KakaoSourceService)
    counts = Counter()

    def read(pointer_value, *, limit):
        key = (
            pointer_value.artifact_id,
            pointer_value.artifact_revision_id,
            pointer_value.member_path,
        )
        counts[key] += 1
        return payloads[key]

    monkeypatch.setattr(service, "_read", read)
    assert service._inputs(admission) == norm
    assert counts[(image.artifact_id, image.artifact_revision_id, image.member_path)] == 1
    assert (
        counts[
            (
                receipt_pointer.artifact_id,
                receipt_pointer.artifact_revision_id,
                receipt_pointer.member_path,
            )
        ]
        == 1
    )
    assert len(admission.attachments) == 2
    # Omitting one observed picture is never a successful smaller required set.
    with pytest.raises(ValueError, match="ATTACHMENT_COVERAGE"):
        validate_capture_source(
            admission.model_copy(update={"attachments": admission.attachments[:1]}), **data
        )
