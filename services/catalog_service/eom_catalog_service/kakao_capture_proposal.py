"""Assemble the established C1 output for one room without granting source authority."""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from eom_catalog_contracts.kakao_archive import (
    KakaoAttachmentObservation,
    KakaoMessageObservation,
)
from eom_catalog_contracts.kakao_media import MAX_MEDIA_BYTES
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
from eom_kakao_archive_contracts.manual_observation import ManualDocument
from eom_kakao_archive_contracts.open_room_download import RoomPhotoReceipt
from eom_kakao_archive_contracts.render import LocalMember, canonical_bytes, sha256

from .kakao_csv_parser import parse_kakao_csv, read_kakao_csv_messages
from .kakao_media_publication import InvalidKakaoMedia, inspect_kakao_media
from .kakao_photo_alignment import infer_scoped_photo_occurrence

_PHOTO_MEMBER = re.compile(r"outputs/photo-[1-6]\.bin")


@dataclass(frozen=True, slots=True)
class OpenRoomDownloadEvidence:
    """Trusted composition input, already scoped to the command's room and attempt."""

    raw_csv: CsvMember
    started_at: datetime
    ended_at: datetime
    expected_room: tuple[str, str] = field(repr=False)
    csv_document: ManualDocument | None = field(repr=False)
    photos: tuple[RoomPhotoReceipt, ...] = field(default=(), repr=False)
    unresolved_visible_bubbles: int = 0


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


def _attachment(
    command: CaptureCommand,
    row: int,
    photo: RoomPhotoReceipt,
    read_photo: Callable[[RoomPhotoReceipt], bytes],
) -> CaptureAttachment:
    raw = read_photo(photo)
    if type(raw) is not bytes or len(raw) != photo.size_bytes:
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_DOWNLOAD_MISMATCH")
    try:
        receipt = inspect_kakao_media(command.source_binding_id, raw)
    except InvalidKakaoMedia:
        receipt = None
    if (receipt.source_sha256 if receipt else sha256(raw)) != photo.sha256:
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_DOWNLOAD_MISMATCH")
    identity = f"eom:kakao:attachment:{command.snapshot_revision_id}:{row}:1"
    return CaptureAttachment(
        attachment_id="kakaoattachment_" + uuid5(NAMESPACE_URL, identity).hex,
        attachment_revision_id="kakaoattachmentrev_"
        + uuid5(NAMESPACE_URL, f"{identity}:{photo.sha256}").hex,
        row_ordinal=row,
        album_ordinal=1,
        association="SEQUENCE_INFERRED",
        availability="failed" if receipt is None else "available",
        quality_level="unknown",
        member=(
            None
            if receipt is None
            else LocalMember(
                relative_path=photo.relative_path,
                media_type=receipt.media_type,
                sha256=photo.sha256,
                size_bytes=photo.size_bytes,
            )
        ),
        width_px=None if receipt is None else receipt.width_px,
        height_px=None if receipt is None else receipt.height_px,
        failure_reason="UNSUPPORTED_MEDIA" if receipt is None else None,
    )


def build_open_room_proposal(
    command: CaptureCommand,
    capability: CaptureCapability,
    inventory: CaptureInventory,
    *,
    source: bytes,
    evidence: OpenRoomDownloadEvidence,
    read_photo: Callable[[RoomPhotoReceipt], bytes],
) -> RoomCaptureDocuments:
    """Validate and join bounded downloads; this never admits or publishes a source."""
    validate_capture_inputs(command, capability, inventory)
    photos = evidence.photos
    if (
        len(photos) > 6
        or len({photo.relative_path for photo in photos}) != len(photos)
        or not 0 <= evidence.unresolved_visible_bubbles <= 100000
        or any(
            not _PHOTO_MEMBER.fullmatch(photo.relative_path)
            or not 0 < photo.size_bytes <= MAX_MEDIA_BYTES
            for photo in photos
        )
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_DOWNLOAD_INVALID")
    parsed = read_kakao_csv_messages(source)
    if (
        evidence.raw_csv.relative_path != "outputs/source.csv"
        or evidence.raw_csv.sha256 != parsed.source_sha256
        or evidence.raw_csv.size_bytes != parsed.source_bytes
    ):
        raise ValueError("KAKAO_ARCHIVE_CAPTURE_DOWNLOAD_MISMATCH")
    matches: list[tuple[int, RoomPhotoReceipt]] = []
    csv_doc = evidence.csv_document
    if csv_doc is not None:
        for photo in photos:
            if photo.document is None:
                continue
            occurrence = infer_scoped_photo_occurrence(
                parsed,
                csv_doc=csv_doc,
                photo_doc=photo.document,
                target=photo.target,
                expected_room=evidence.expected_room,
            )
            if occurrence is not None:
                matches.append((occurrence.row_ordinal, photo))
    row_counts = Counter(row for row, _ in matches)
    attachments = tuple(
        _attachment(command, row, photo, read_photo)
        for row, photo in matches
        if row_counts[row] == 1
    )
    return build_partial_room_capture(
        command,
        capability,
        inventory,
        source=source,
        evidence=PartialRoomEvidence(
            started_at=evidence.started_at,
            ended_at=evidence.ended_at,
            messages=tuple(
                KakaoMessageObservation(row_ordinal=photo.row_ordinal, kind="attachment")
                for photo in attachments
            ),
            attachments=attachments,
            unresolved_attachment_bubbles=(
                evidence.unresolved_visible_bubbles + len(photos) - len(attachments)
            ),
        ),
    )


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
