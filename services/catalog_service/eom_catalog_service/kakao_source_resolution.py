"""Pure admission verification and deterministic occurrence allocation, no persistence."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid5

from eom_catalog_contracts.kakao_archive import KakaoMessageNormalization, KakaoMessageObservation
from eom_catalog_contracts.kakao_media import KakaoMediaBlobReceipt
from eom_catalog_contracts.kakao_snapshot import KakaoRoomSnapshot
from eom_catalog_contracts.kakao_source import (
    KakaoSourceAdmission,
    KakaoSourceResolution,
    KakaoSourceRow,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes

from eom_catalog_service.kakao_csv_parser import parse_kakao_csv
from eom_catalog_service.kakao_message_alignment import align_kakao_snapshots


def capture_attachment_quality(
    level: Literal["original_verified", "best_available", "thumbnail_only", "unknown"],
) -> Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"]:
    """Translate the capture observation without upgrading an unverified image."""
    if level == "original_verified":
        return "ORIGINAL"
    if level == "best_available":
        return "BEST_AVAILABLE"
    return "UNKNOWN"


def validate_capture_source(
    admission: KakaoSourceAdmission,
    *,
    snapshot: KakaoRoomSnapshot,
    normalization: KakaoMessageNormalization,
    source: bytes,
    command_bytes: bytes,
    capability_bytes: bytes,
    report_bytes: bytes,
    result_bytes: bytes,
    media_receipts: dict[str, KakaoMediaBlobReceipt],
) -> None:
    # Optional worker contracts are needed only by the activated source use case.
    from eom_kakao_archive_contracts.capture import (
        CaptureCapability,
        CaptureCommand,
        CaptureResult,
        CaptureRoomReport,
        validate_capture_result,
    )

    command = CaptureCommand.model_validate_json(command_bytes)
    capability = CaptureCapability.model_validate_json(capability_bytes)
    report = CaptureRoomReport.model_validate_json(report_bytes)
    result = CaptureResult.model_validate_json(result_bytes)
    authority = admission.authority
    validate_capture_result(
        command, result, report, capability=capability, current_fence=authority.fence
    )
    timestamps = [
        message.sent_at_utc for message in normalization.messages if message.sent_at_utc is not None
    ]
    # Re-parsing preserves observations; it cannot authenticate sender direction,
    # provider IDs or unseen context. Never exceed the measured capability ceiling.
    if (
        (
            capability.message_identity != "stable_source_id"
            and any(message.source_message_id is not None for message in normalization.messages)
        )
        or (
            report.direction_evidence == "unknown"
            and any(
                message.role != "unknown" or message.role_evidence_id is not None
                for message in normalization.messages
            )
        )
        or (
            (normalization.context_start_verified or normalization.context_end_verified)
            and (report.csv_scope != "full_accessible_history" or report.source_order == "unknown")
        )
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_OBSERVATION_UNSUPPORTED")
    if (
        result.status not in {"COMPLETED", "PARTIAL"}
        or command.run_id != authority.run_id
        or command.execution.attempt_id != authority.attempt_id
        or command.capability_revision_id != authority.capability_revision_id
        or command.adapter_release_sha256 != authority.adapter_release_sha256
        or sha256_bytes(command_bytes) != authority.command_sha256
        or result.command_sha256 != authority.command_sha256
        or report.source_binding_id != admission.source_binding_id
        or report.room_id != admission.room_id
        or report.snapshot_revision_id != admission.snapshot_revision_id
        or report.normalization_revision_id != admission.normalization_revision_id
        or (snapshot.source_binding_id, snapshot.room_id, snapshot.snapshot_revision_id)
        != (admission.source_binding_id, admission.room_id, admission.snapshot_revision_id)
        or snapshot.source_sha256 != admission.source.sha256
        or snapshot.source_bytes != len(source)
        or report.raw_csv.sha256 != admission.source.sha256
        or report.raw_csv.size_bytes != len(source)
        or sha256_bytes(source) != admission.source.sha256
        or report.normalization.sha256 != admission.normalization.sha256
        or report.csv_scope != snapshot.csv_scope
        or report.observed_end_at != snapshot.observed_at_utc
        or report.csv_rows != len(normalization.messages)
        or report.unknown_sender_rows != sum(m.role == "unknown" for m in normalization.messages)
        or report.source_order != normalization.source_order
        or report.source_timezone != normalization.source_timezone
        or report.first_source_at_utc != (min(timestamps) if timestamps else None)
        or report.last_source_at_utc != (max(timestamps) if timestamps else None)
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_SOURCE_MISMATCH")
    rebuilt = parse_kakao_csv(
        source,
        source_binding_id=admission.source_binding_id,
        room_id=admission.room_id,
        snapshot_revision_id=admission.snapshot_revision_id,
        normalization_revision_id=admission.normalization_revision_id,
        observed_at_utc=snapshot.observed_at_utc,
        source_timezone=normalization.source_timezone,
        source_order=normalization.source_order,
        context_start_verified=normalization.context_start_verified,
        context_end_verified=normalization.context_end_verified,
        observations=tuple(
            KakaoMessageObservation.model_validate(
                {key: getattr(message, key) for key in KakaoMessageObservation.model_fields}
            )
            for message in normalization.messages
        ),
    )
    if rebuilt != normalization:
        raise ValueError("KAKAO_ARCHIVE_NORMALIZATION_MISMATCH")
    if report.normalization.size_bytes != len(
        canonical_json_bytes(normalization.model_dump(mode="json"))
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_SOURCE_MISMATCH")
    declared = {entry.attachment_id: entry for entry in admission.attachments}
    observed = {
        entry.attachment_id: (message.row_ordinal, entry)
        for message in normalization.messages
        for entry in message.attachments
    }
    captured = {entry.attachment_id: entry for entry in report.attachments}
    if set(declared) != set(observed) or set(declared) != set(captured):
        raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_COVERAGE_INVALID")
    expected_media = {key for key, entry in declared.items() if entry.original is not None}
    if set(media_receipts) != expected_media:
        raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_COVERAGE_INVALID")
    for key, attachment in declared.items():
        row, observation = observed[key]
        actual = captured[key]
        if (
            actual.row_ordinal,
            actual.attachment_revision_id,
            actual.availability,
            actual.association,
            actual.album_ordinal,
        ) != (
            row,
            observation.attachment_revision_id,
            observation.availability,
            observation.association,
            observation.album_ordinal,
        ) or attachment.attachment_revision_id != observation.attachment_revision_id:
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_ASSOCIATION_INVALID")
        if (attachment.original is not None) != (observation.availability == "available"):
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_COVERAGE_INVALID")
        if attachment.original is not None:
            receipt = media_receipts[key]
            expected_quality = capture_attachment_quality(actual.quality_level)
            if (
                actual.member is None
                or receipt.source_binding_id != admission.source_binding_id
                or receipt.source_sha256 != attachment.original.sha256
                or receipt.media_type != attachment.original.media_type
                or (actual.member.sha256, actual.member.media_type, actual.member.size_bytes)
                != (receipt.source_sha256, receipt.media_type, receipt.source_bytes)
                or (actual.width_px, actual.height_px) != (receipt.width_px, receipt.height_px)
                or attachment.quality != expected_quality
            ):
                raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_MEDIA_INVALID")


def build_source_resolution(
    admission: KakaoSourceAdmission,
    normalization: KakaoMessageNormalization,
    *,
    source_revision_id: str,
    command_id: str,
    owner: str,
    reserved_at: datetime,
    previous: KakaoSourceResolution | None = None,
    previous_normalization: KakaoMessageNormalization | None = None,
) -> KakaoSourceResolution:
    if (previous is None) != (previous_normalization is None) or (previous is None) != (
        admission.expected_source_revision_id is None
    ):
        raise ValueError("KAKAO_ARCHIVE_SOURCE_PRECONDITION_INVALID")
    matches = {}
    old_rows = {}
    unmatched: tuple[int, ...] = ()
    if previous is not None and previous_normalization is not None:
        if (
            previous.source_revision_id != admission.expected_source_revision_id
            or previous.resource_version != admission.expected_resource_version
            or previous.admission.normalization_revision_id
            != previous_normalization.normalization_revision_id
            or (previous.admission.source_binding_id, previous.admission.room_id)
            != (admission.source_binding_id, admission.room_id)
        ):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_PRECONDITION_INVALID")
        proposal = align_kakao_snapshots(previous_normalization, normalization)
        matches = {match.current_row: match for match in proposal.matches}
        old_rows = {row.row_ordinal: row for row in previous.rows}
        if set(old_rows) != {m.row_ordinal for m in previous_normalization.messages}:
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        unmatched = proposal.previous_unmatched
    namespace = UUID(source_revision_id.removeprefix("kakaosourcerev_"))
    rows = []
    for message in normalization.messages:
        match = matches.get(message.row_ordinal)
        rows.append(
            KakaoSourceRow(
                row_ordinal=message.row_ordinal,
                occurrence_id=old_rows[match.previous_row].occurrence_id
                if match
                else "kakaomessage_" + uuid5(namespace, f"message:{message.row_ordinal}").hex,
                previous_row_ordinal=match.previous_row if match else None,
                association=cast(Literal["SOURCE_VERIFIED", "SEQUENCE_INFERRED"], match.level)
                if match
                else ("SNAPSHOT_ONLY" if previous is None else "UNRESOLVED"),
                source_content_changed=match.source_content_changed if match else False,
                evidence_changed=match.evidence_changed if match else False,
            )
        )
    return KakaoSourceResolution(
        source_revision_id=source_revision_id,
        command_id=command_id,
        resource_version=admission.expected_resource_version + 1,
        admission=admission,
        created_by=owner,
        created_at=reserved_at,
        observed_at=normalization.observed_at_utc,
        rows=tuple(rows),
        previous_unmatched_rows=unmatched,
    )
