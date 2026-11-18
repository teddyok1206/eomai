"""Assemble the established C1 output for one room without granting source authority."""

from dataclasses import dataclass, field
from datetime import datetime

from eom_catalog_contracts.kakao_archive import (
    KakaoAttachmentObservation,
    KakaoMessageObservation,
)
from eom_kakao_archive_contracts.capture import (
    CaptureAttachment,
    CaptureCapability,
    CaptureCommand,
    CaptureInventory,
    CaptureResult,
    CaptureRoomReport,
    CsvMember,
    CsvScope,
    DirectionEvidence,
    SourceOrder,
    SourceTimezone,
    validate_capture_inputs,
    validate_capture_result,
)
from eom_kakao_archive_contracts.render import LocalMember, canonical_bytes, sha256

from .kakao_csv_parser import parse_kakao_csv


@dataclass(frozen=True, slots=True)
class PartialRoomEvidence:
    """Only actual collector evidence; this value is not a public or worker authority grant."""

    started_at: datetime
    ended_at: datetime
    csv_scope: CsvScope = "unknown"
    order: SourceOrder = "unknown"
    timezone: SourceTimezone = "unknown"
    direction: DirectionEvidence = "unknown"
    messages: tuple[KakaoMessageObservation, ...] = field(default=(), repr=False)
    attachments: tuple[CaptureAttachment, ...] = field(default=(), repr=False)
    unresolved_attachment_bubbles: int = 0


@dataclass(frozen=True, slots=True)
class RoomCaptureDocuments:
    """Local documents that accompany the already captured CSV and image members."""

    report: CaptureRoomReport
    result: CaptureResult
    normalization_bytes: bytes = field(repr=False)
    report_bytes: bytes = field(repr=False)
    result_bytes: bytes = field(repr=False)


def _attach_observations(evidence: PartialRoomEvidence) -> tuple[KakaoMessageObservation, ...]:
    rows: dict[int, KakaoMessageObservation] = {}
    for message in evidence.messages:
        if message.row_ordinal in rows or message.attachments:
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_OBSERVATION_UNSUPPORTED")
        if evidence.direction == "unknown" and message.role != "unknown":
            raise ValueError("KAKAO_ARCHIVE_CAPTURE_OBSERVATION_UNSUPPORTED")
        rows[message.row_ordinal] = message
    attachments: dict[int, list[KakaoAttachmentObservation]] = {}
    for entry in evidence.attachments:
        attachments.setdefault(entry.row_ordinal, []).append(
            KakaoAttachmentObservation(
                attachment_id=entry.attachment_id,
                attachment_revision_id=entry.attachment_revision_id,
                album_ordinal=entry.album_ordinal,
                availability=entry.availability,
                association=entry.association,
            )
        )
    for ordinal, images in attachments.items():
        row = rows.get(ordinal)
        fields = {} if row is None else row.model_dump(exclude={"attachments", "row_ordinal"})
        rows[ordinal] = KakaoMessageObservation(
            row_ordinal=ordinal,
            attachments=tuple(sorted(images, key=lambda image: image.album_ordinal)),
            **fields,
        )
    return tuple(rows.values())


def build_partial_room_capture(
    command: CaptureCommand,
    capability: CaptureCapability,
    inventory: CaptureInventory,
    *,
    source: bytes,
    evidence: PartialRoomEvidence,
) -> RoomCaptureDocuments:
    """Derive both report and parser input from the same bounded acquisition evidence."""
    validate_capture_inputs(command, capability, inventory)
    room, snapshot, normalization = (
        command.room_id,
        command.snapshot_revision_id,
        command.normalization_revision_id,
    )
    if room is None or snapshot is None or normalization is None:
        raise ValueError("KAKAO_CAPTURE_OPERATION_INVALID")
    if len(evidence.messages) > 100000 or len(evidence.attachments) > 2000:
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_OBSERVATION_UNSUPPORTED")
    if capability.message_identity != "stable_source_id" and any(
        message.source_message_id is not None for message in evidence.messages
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_OBSERVATION_UNSUPPORTED")
    parsed = parse_kakao_csv(
        source,
        source_binding_id=command.source_binding_id,
        room_id=room,
        snapshot_revision_id=snapshot,
        normalization_revision_id=normalization,
        observed_at_utc=evidence.ended_at,
        source_order=evidence.order,
        source_timezone=evidence.timezone,
        observations=_attach_observations(evidence),
    )
    normalized = canonical_bytes(parsed.model_dump(mode="json"))
    count = len(parsed.messages)
    timestamps = tuple(m.sent_at_utc for m in parsed.messages if m.sent_at_utc is not None)
    attachment_bubbles = len({entry.row_ordinal for entry in evidence.attachments})
    report = CaptureRoomReport(
        execution=command.execution,
        run_id=command.run_id,
        source_binding_id=command.source_binding_id,
        room_id=room,
        inventory_revision_id=command.inventory_revision_id,
        snapshot_revision_id=snapshot,
        normalization_revision_id=normalization,
        observed_start_at=evidence.started_at,
        observed_end_at=evidence.ended_at,
        raw_csv=CsvMember(
            relative_path="outputs/source.csv",
            sha256=parsed.source_sha256,
            size_bytes=parsed.source_bytes,
        ),
        normalization=LocalMember(
            relative_path="outputs/normalization.json",
            sha256=sha256(normalized),
            size_bytes=len(normalized),
            media_type="application/json",
        ),
        csv_scope=evidence.csv_scope,
        source_order=evidence.order,
        source_timezone=evidence.timezone,
        direction_evidence=evidence.direction,
        csv_rows=count,
        unknown_sender_rows=sum(message.role == "unknown" for message in parsed.messages),
        first_source_at_utc=min(timestamps, default=None),
        last_source_at_utc=max(timestamps, default=None),
        attachment_bubbles_observed=attachment_bubbles + evidence.unresolved_attachment_bubbles,
        attachment_inventory_complete=False,
        unresolved_attachment_bubbles=evidence.unresolved_attachment_bubbles,
        attachments=tuple(
            sorted(evidence.attachments, key=lambda a: (a.row_ordinal, a.album_ordinal))
        ),
        room_complete=False,
    )
    report_bytes = canonical_bytes(report.model_dump(mode="json"))
    result = CaptureResult(
        execution=command.execution,
        run_id=command.run_id,
        source_binding_id=command.source_binding_id,
        room_id=room,
        command_sha256=sha256(canonical_bytes(command.model_dump(mode="json"))),
        adapter_release_sha256=command.adapter_release_sha256,
        capability_revision_id=command.capability_revision_id,
        status="PARTIAL",
        report=LocalMember(
            relative_path="outputs/room-report.json",
            sha256=sha256(report_bytes),
            size_bytes=len(report_bytes),
            media_type="application/json",
        ),
        error_code=None,
    )
    validate_capture_result(
        command, result, report, capability=capability, current_fence=command.execution.fence
    )
    return RoomCaptureDocuments(
        report, result, normalized, report_bytes, canonical_bytes(result.model_dump(mode="json"))
    )
