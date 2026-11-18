"""Existing C1 shapes from synthetic bytes, without a browser or permission grant."""

from dataclasses import replace
from datetime import timedelta

import pytest
from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization, KakaoMessageObservation
from eom_catalog_service.kakao_capture_proposal import (
    PartialRoomEvidence,
    build_partial_room_capture,
)
from eom_kakao_archive_contracts.capture import CaptureResult, CaptureRoomReport
from eom_kakao_archive_contracts.render import sha256

from tests.unit.test_kakao_capture_contracts import (
    NOW,
    attachment,
    capability,
    change,
    command,
    inventory,
)

RAW = (
    b"DATE,USER,MESSAGE\r\n"
    b"2026-11-16 12:00:00,anonymous,same\r\n"
    b"2026-11-16 12:00:00,anonymous,same\r\n"
)


def test_partial_report_derives_duplicate_occurrence_evidence_from_one_input():
    cap, rooms = capability(), inventory()
    cmd = command(cap, rooms)
    photos = (
        attachment(2, row_ordinal=2, association="SEQUENCE_INFERRED"),
        attachment(1, association="SEQUENCE_INFERRED"),
    )
    evidence = PartialRoomEvidence(NOW, NOW + timedelta(seconds=2), attachments=photos)
    output = build_partial_room_capture(cmd, cap, rooms, source=RAW, evidence=evidence)
    assert output == build_partial_room_capture(cmd, cap, rooms, source=RAW, evidence=evidence)
    parsed = KakaoMessageNormalization.model_validate_json(output.normalization_bytes)
    report, result = (
        CaptureRoomReport.model_validate_json(output.report_bytes),
        CaptureResult.model_validate_json(output.result_bytes),
    )
    assert result.report is not None and result.report.sha256 == sha256(output.report_bytes)
    assert report.normalization.sha256 == sha256(output.normalization_bytes)
    assert report.raw_csv.sha256 == sha256(RAW)
    assert result.status == "PARTIAL" and not report.room_complete
    assert report.csv_rows == report.unknown_sender_rows == 2 and report.source_order == "unknown"
    assert not report.attachment_inventory_complete
    assert parsed.messages[0].text == parsed.messages[1].text == "same"
    assert [a.attachment_id for a in report.attachments] == [
        message.attachments[0].attachment_id for message in parsed.messages
    ]
    assert all(
        message.role == "unknown" and message.sent_at_utc is None for message in parsed.messages
    )


def test_explicit_known_direction_and_time_need_capability_and_keep_unknown_rows():
    cap, rooms = capability(), inventory()
    row = KakaoMessageObservation(row_ordinal=1, role="student", role_evidence_id="synthetic-dom")
    evidence = PartialRoomEvidence(
        NOW,
        NOW + timedelta(seconds=2),
        order="ascending",
        timezone="Asia/Seoul",
        direction="dom_verified",
        messages=(row,),
        unresolved_attachment_bubbles=1,
    )
    output = build_partial_room_capture(
        command(cap, rooms), cap, rooms, source=RAW, evidence=evidence
    )
    assert output.report.unknown_sender_rows == output.report.unresolved_attachment_bubbles == 1
    assert output.report.first_source_at_utc == output.report.last_source_at_utc
    weaker = change(cap, direction_evidence="unknown")
    with pytest.raises(ValueError, match="CAPABILITY_ESCALATION"):
        build_partial_room_capture(
            command(weaker, rooms), weaker, rooms, source=RAW, evidence=evidence
        )


def test_inconsistent_inventory_or_source_observations_are_rejected():
    cap, rooms = capability(), inventory()
    cmd = command(cap, rooms)
    evidence = PartialRoomEvidence(NOW, NOW + timedelta(seconds=2))
    with pytest.raises(ValueError, match="MANIFEST_HASH_MISMATCH"):
        build_partial_room_capture(
            cmd,
            cap,
            change(rooms, reconciliation_pass_at=NOW + timedelta(minutes=5)),
            source=RAW,
            evidence=evidence,
        )
    with pytest.raises(ValueError, match="ROW_EVIDENCE_OUT_OF_RANGE"):
        build_partial_room_capture(
            cmd,
            cap,
            rooms,
            source=RAW,
            evidence=replace(evidence, attachments=(attachment(row_ordinal=3),)),
        )
    with pytest.raises(ValueError, match="OBSERVATION_UNSUPPORTED"):
        build_partial_room_capture(
            cmd,
            cap,
            rooms,
            source=RAW,
            evidence=replace(
                evidence,
                messages=(KakaoMessageObservation(row_ordinal=1, source_message_id="fake"),),
            ),
        )
