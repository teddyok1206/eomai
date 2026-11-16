"""Pure collection contracts; observations are not authority or runtime proof.

The owner validates real permissions, profile exclusion and local bytes before using
these values. No browser, network, database, NAS, credentials or source content is
accessed here. Identity/coverage/member checks are linear in bounded inventories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Any, Literal, Self

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import Field, StrictBool, model_validator

from .execution import FrozenModel, WorkerExecution
from .kakao_remote import (
    BrowserRunId,
    ProfileFence,
    ProfileId,
    ProfileStopReceipt,
    UtcDatetime,
    validate_profile_handoff,
)
from .render import (
    AttachmentId,
    AttachmentRevisionId,
    BindingId,
    LocalMember,
    Sha256,
    canonical_bytes,
    sha256,
)

SCHEMA_SHA256 = "sha256:9c9cd7cc4438a194acd157775261b4ac846e0b7ab12ee2aa05e79560777746ce"
CAPTURE_BYTES_LIMIT = 256 * 1024 * 1024
MAX_FENCE = 2147483647
RoomId = Annotated[str, Field(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
RunId = Annotated[str, Field(pattern=r"^kakaorun_[0-9a-f]{32}$")]
CapabilityRevisionId = Annotated[str, Field(pattern=r"^kakaocapabilityrev_[0-9a-f]{32}$")]
InventoryRevisionId = Annotated[str, Field(pattern=r"^kakaoinventoryrev_[0-9a-f]{32}$")]
SnapshotRevisionId = Annotated[str, Field(pattern=r"^kakaosnapshotrev_[0-9a-f]{32}$")]
NormalizationRevisionId = Annotated[str, Field(pattern=r"^kakaonormalizationrev_[0-9a-f]{32}$")]
ScopeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
SourceOrder = Literal["ascending", "descending", "unknown"]
SourceTimezone = Literal["Asia/Seoul", "unknown"]
CsvScope = Literal["full_accessible_history", "loaded_window", "explicit_range", "unknown"]
DirectionEvidence = Literal["dom_verified", "source_metadata_verified", "unknown"]
CaptureError = Literal[
    "NETWORK_TRANSIENT",
    "RATE_LIMITED",
    "AUTH_REQUIRED",
    "ACCESS_DENIED",
    "UI_CHANGED",
    "ENUMERATION_STALLED",
    "HASH_MISMATCH",
    "DISK_FULL",
    "TIMEOUT",
    "PUBLICATION_UNAVAILABLE",
    "INVALID_INPUT",
]
SchemaKind = Literal["capability", "command", "result", "inventory", "room-report"]
_IMAGE_MEDIA = frozenset({"image/png", "image/jpeg", "image/webp"})
_ATTACHMENT_FAILURES = {
    "available": frozenset({None}),
    "expired": frozenset({"SOURCE_EXPIRED"}),
    "denied": frozenset({"ACCESS_DENIED"}),
    "not_found": frozenset({"SOURCE_NOT_FOUND"}),
    "pending": frozenset({"DOWNLOAD_PENDING"}),
    "failed": frozenset({"DOWNLOAD_FAILED", "UNSUPPORTED_MEDIA"}),
}


class CsvMember(FrozenModel):
    relative_path: str = Field(pattern=r"^[A-Za-z0-9_-]+(?:[/.][A-Za-z0-9_-]+)*$", max_length=240)
    sha256: Sha256
    size_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    media_type: Literal["text/csv"] = "text/csv"


def _members(
    values: tuple[LocalMember | CsvMember, ...], *, output: bool = False
) -> tuple[LocalMember | CsvMember, ...]:
    unique: dict[str, LocalMember | CsvMember] = {}
    for member in values:
        if member.media_type not in _IMAGE_MEDIA | {"application/json", "text/csv"}:
            raise ValueError("KAKAO_CAPTURE_MEMBER_TYPE_INVALID")
        if output and not member.relative_path.startswith("outputs/"):
            raise ValueError("KAKAO_CAPTURE_OUTPUT_LOCATION_INVALID")
        if unique.setdefault(member.relative_path, member) != member:
            raise ValueError("KAKAO_CAPTURE_MEMBER_COLLISION")
    if sum(member.size_bytes for member in unique.values()) > CAPTURE_BYTES_LIMIT:
        raise ValueError("KAKAO_CAPTURE_BYTES_EXCEEDED")
    return tuple(unique.values())


def _json_member(member: LocalMember) -> None:
    if member.media_type != "application/json":
        raise ValueError("KAKAO_CAPTURE_JSON_REQUIRED")


def _exact_value(member: LocalMember, value: FrozenModel) -> None:
    _json_member(member)
    raw = canonical_bytes(value.model_dump(mode="json"))
    if member.sha256 != sha256(raw) or member.size_bytes != len(raw):
        raise ValueError("KAKAO_CAPTURE_MANIFEST_HASH_MISMATCH")


def _execution(execution: WorkerExecution) -> None:
    if execution.fence > MAX_FENCE:
        raise ValueError("KAKAO_CAPTURE_FENCE_INVALID")


class CaptureCapability(FrozenModel):
    schema_version: Literal["kakao-collection-capability/1.0"] = "kakao-collection-capability/1.0"
    source_binding_id: BindingId
    capability_revision_id: CapabilityRevisionId
    adapter_release_sha256: Sha256
    observed_at: UtcDatetime
    channel_verified: StrictBool
    room_identity: Literal["stable_source_id", "manual_binding", "unknown"]
    message_identity: Literal["stable_source_id", "sequence_only", "unknown"]
    csv_scope: CsvScope
    csv_order: SourceOrder
    source_timezone: SourceTimezone
    direction_evidence: DirectionEvidence
    album_enumeration: Literal["verified", "unknown"]
    original_download: Literal["verified_ui_download", "best_available", "unavailable", "unknown"]
    opening_marks_read: Literal["yes", "no", "unknown"]
    visible_scope_ids: tuple[ScopeId, ...] = Field(max_length=32)
    evidence: tuple[LocalMember, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def evidence_scope(self) -> Self:
        if len(set(self.visible_scope_ids)) != len(self.visible_scope_ids):
            raise ValueError("KAKAO_CAPTURE_SCOPE_DUPLICATED")
        if len(_members(self.evidence)) != len(self.evidence):
            raise ValueError("KAKAO_CAPTURE_EVIDENCE_DUPLICATED")
        return self


class CaptureCommand(FrozenModel):
    schema_version: Literal["kakao-collection-command/1.0"] = "kakao-collection-command/1.0"
    execution: WorkerExecution
    run_id: RunId
    source_binding_id: BindingId
    profile_id: ProfileId
    browser_run_id: BrowserRunId
    adapter_release_sha256: Sha256
    capability_revision_id: CapabilityRevisionId
    capability: LocalMember
    issued_at: UtcDatetime
    operation: Literal["INVENTORY", "CAPTURE_ROOM"]
    requested_scope_ids: tuple[ScopeId, ...] = Field(min_length=1, max_length=32)
    inventory_revision_id: InventoryRevisionId
    inventory: LocalMember | None
    room_id: RoomId | None
    snapshot_revision_id: SnapshotRevisionId | None
    normalization_revision_id: NormalizationRevisionId | None

    @model_validator(mode="after")
    def operation_shape(self) -> Self:
        _execution(self.execution)
        _json_member(self.capability)
        fields = (
            self.inventory,
            self.room_id,
            self.snapshot_revision_id,
            self.normalization_revision_id,
        )
        if self.operation == "INVENTORY":
            if any(value is not None for value in fields):
                raise ValueError("KAKAO_CAPTURE_OPERATION_INVALID")
        elif any(value is None for value in fields):
            raise ValueError("KAKAO_CAPTURE_OPERATION_INVALID")
        if self.inventory is not None:
            _json_member(self.inventory)
            _members((self.capability, self.inventory))
        if len(set(self.requested_scope_ids)) != len(self.requested_scope_ids):
            raise ValueError("KAKAO_CAPTURE_SCOPE_DUPLICATED")
        return self


class InventoryScope(FrozenModel):
    scope_id: ScopeId
    filters_cleared: StrictBool
    end_reached: StrictBool
    pending_loading: StrictBool
    stabilization_completed: StrictBool
    new_rooms_on_stabilization: int = Field(strict=True, ge=0, le=10000)
    evidence: LocalMember

    @property
    def complete(self) -> bool:
        return (
            self.filters_cleared
            and self.end_reached
            and not self.pending_loading
            and self.stabilization_completed
            and self.new_rooms_on_stabilization == 0
        )


class InventoryRoom(FrozenModel):
    room_id: RoomId
    scope_ids: tuple[ScopeId, ...] = Field(min_length=1, max_length=32)
    identity_level: Literal["stable_source_id", "manual_binding"]
    evidence: LocalMember

    @model_validator(mode="after")
    def distinct_scopes(self) -> Self:
        if len(set(self.scope_ids)) != len(self.scope_ids):
            raise ValueError("KAKAO_CAPTURE_SCOPE_DUPLICATED")
        return self


class UnresolvedRoom(FrozenModel):
    observation_id: ScopeId
    scope_id: ScopeId
    reason: Literal["IDENTITY_UNVERIFIED", "ACCESS_DENIED", "ENUMERATION_STALLED", "UI_CHANGED"]
    evidence: LocalMember


class CaptureInventory(FrozenModel):
    schema_version: Literal["kakao-room-inventory/1.0"] = "kakao-room-inventory/1.0"
    execution: WorkerExecution
    run_id: RunId
    source_binding_id: BindingId
    inventory_revision_id: InventoryRevisionId
    inventory_started_at: UtcDatetime
    inventory_finished_at: UtcDatetime
    reconciliation_pass_at: UtcDatetime | None
    scopes: tuple[InventoryScope, ...] = Field(min_length=1, max_length=32)
    rooms: tuple[InventoryRoom, ...] = Field(max_length=10000)
    unresolved: tuple[UnresolvedRoom, ...] = Field(max_length=10000)
    inventory_complete: StrictBool

    @model_validator(mode="after")
    def coherent_inventory(self) -> Self:
        _execution(self.execution)
        if self.inventory_started_at > self.inventory_finished_at or (
            self.reconciliation_pass_at is not None
            and self.reconciliation_pass_at < self.inventory_finished_at
        ):
            raise ValueError("KAKAO_CAPTURE_OBSERVATION_INTERVAL_INVALID")
        scopes = {scope.scope_id for scope in self.scopes}
        if len(scopes) != len(self.scopes):
            raise ValueError("KAKAO_CAPTURE_SCOPE_DUPLICATED")
        if len({room.room_id for room in self.rooms}) != len(self.rooms):
            raise ValueError("KAKAO_CAPTURE_ROOM_DUPLICATED")
        if len({entry.observation_id for entry in self.unresolved}) != len(self.unresolved):
            raise ValueError("KAKAO_CAPTURE_OBSERVATION_DUPLICATED")
        if any(not set(room.scope_ids).issubset(scopes) for room in self.rooms) or any(
            entry.scope_id not in scopes for entry in self.unresolved
        ):
            raise ValueError("KAKAO_CAPTURE_INVENTORY_SCOPE_INVALID")
        expected = (
            self.reconciliation_pass_at is not None
            and not self.unresolved
            and all(scope.complete for scope in self.scopes)
        )
        if self.inventory_complete != expected:
            raise ValueError("KAKAO_CAPTURE_COMPLETENESS_INVALID")
        inventory_members(self)
        return self


def inventory_members(inventory: CaptureInventory) -> tuple[LocalMember | CsvMember, ...]:
    return _members(
        (
            *(entry.evidence for entry in inventory.scopes),
            *(entry.evidence for entry in inventory.rooms),
            *(entry.evidence for entry in inventory.unresolved),
        ),
        output=True,
    )


class CaptureAttachment(FrozenModel):
    attachment_id: AttachmentId
    attachment_revision_id: AttachmentRevisionId
    row_ordinal: int = Field(strict=True, ge=1, le=100000)
    album_ordinal: int = Field(strict=True, ge=1, le=1000)
    association: Literal[
        "SOURCE_VERIFIED", "SEQUENCE_INFERRED", "SNAPSHOT_ONLY", "MANUAL_CONFIRMED", "UNRESOLVED"
    ]
    availability: Literal["available", "expired", "denied", "not_found", "pending", "failed"]
    quality_level: Literal["original_verified", "best_available", "thumbnail_only", "unknown"]
    member: LocalMember | None
    width_px: int | None = Field(strict=True, ge=1, le=20000)
    height_px: int | None = Field(strict=True, ge=1, le=20000)
    failure_reason: (
        Literal[
            "SOURCE_EXPIRED",
            "ACCESS_DENIED",
            "SOURCE_NOT_FOUND",
            "DOWNLOAD_PENDING",
            "DOWNLOAD_FAILED",
            "UNSUPPORTED_MEDIA",
        ]
        | None
    )

    @model_validator(mode="after")
    def available_image(self) -> Self:
        if self.failure_reason not in _ATTACHMENT_FAILURES[self.availability]:
            raise ValueError("KAKAO_CAPTURE_ATTACHMENT_FAILURE_INVALID")
        if self.availability == "available":
            if (
                self.member is None
                or self.member.media_type not in _IMAGE_MEDIA
                or self.width_px is None
                or self.height_px is None
                or self.width_px * self.height_px > 100000000
            ):
                raise ValueError("KAKAO_CAPTURE_IMAGE_INVALID")
        elif (
            any(value is not None for value in (self.member, self.width_px, self.height_px))
            or self.quality_level != "unknown"
        ):
            raise ValueError("KAKAO_CAPTURE_UNAVAILABLE_IMAGE_INVALID")
        return self


class CaptureRoomReport(FrozenModel):
    schema_version: Literal["kakao-room-capture/1.0"] = "kakao-room-capture/1.0"
    execution: WorkerExecution
    run_id: RunId
    source_binding_id: BindingId
    room_id: RoomId
    inventory_revision_id: InventoryRevisionId
    snapshot_revision_id: SnapshotRevisionId
    normalization_revision_id: NormalizationRevisionId
    observed_start_at: UtcDatetime
    observed_end_at: UtcDatetime
    raw_csv: CsvMember
    normalization: LocalMember
    parser_revision: Literal["kakao-csv/1.0"] = "kakao-csv/1.0"
    csv_scope: CsvScope
    source_order: SourceOrder
    source_timezone: SourceTimezone
    direction_evidence: DirectionEvidence
    csv_rows: int = Field(strict=True, ge=0, le=100000)
    unknown_sender_rows: int = Field(strict=True, ge=0, le=100000)
    first_source_at_utc: UtcDatetime | None
    last_source_at_utc: UtcDatetime | None
    attachment_bubbles_observed: int = Field(strict=True, ge=0, le=100000)
    attachment_inventory_complete: StrictBool
    unresolved_attachment_bubbles: int = Field(strict=True, ge=0, le=100000)
    attachments: tuple[CaptureAttachment, ...] = Field(max_length=2000)
    room_complete: StrictBool

    @model_validator(mode="after")
    def coherent_capture(self) -> Self:
        _execution(self.execution)
        _json_member(self.normalization)
        if self.observed_start_at > self.observed_end_at:
            raise ValueError("KAKAO_CAPTURE_OBSERVATION_INTERVAL_INVALID")
        if self.source_timezone == "unknown" or self.csv_rows == 0:
            if self.first_source_at_utc is not None or self.last_source_at_utc is not None:
                raise ValueError("KAKAO_CAPTURE_SOURCE_TIME_UNVERIFIED")
        elif (
            self.first_source_at_utc is None
            or self.last_source_at_utc is None
            or self.first_source_at_utc > self.last_source_at_utc
        ):
            raise ValueError("KAKAO_CAPTURE_SOURCE_TIME_INVALID")
        if (
            self.unknown_sender_rows > self.csv_rows
            or self.attachment_bubbles_observed > self.csv_rows
        ):
            raise ValueError("KAKAO_CAPTURE_COUNT_INVALID")
        rows = {item.row_ordinal for item in self.attachments}
        if (
            any(row > self.csv_rows for row in rows)
            or not (
                len(rows)
                <= self.attachment_bubbles_observed
                <= len(rows) + self.unresolved_attachment_bubbles
            )
            or self.unresolved_attachment_bubbles > self.attachment_bubbles_observed
        ):
            raise ValueError("KAKAO_CAPTURE_ATTACHMENT_COVERAGE_INVALID")
        if (
            len({item.attachment_id for item in self.attachments}) != len(self.attachments)
            or len({item.attachment_revision_id for item in self.attachments})
            != len(self.attachments)
            or len({(item.row_ordinal, item.album_ordinal) for item in self.attachments})
            != len(self.attachments)
        ):
            raise ValueError("KAKAO_CAPTURE_ATTACHMENT_DUPLICATED")
        expected = (
            self.csv_scope == "full_accessible_history"
            and self.source_order != "unknown"
            and self.source_timezone != "unknown"
            and self.direction_evidence != "unknown"
            and self.unknown_sender_rows == 0
            and self.attachment_inventory_complete
            and self.unresolved_attachment_bubbles == 0
            and all(
                item.availability == "available"
                and item.association in {"SOURCE_VERIFIED", "MANUAL_CONFIRMED"}
                and item.quality_level == "original_verified"
                for item in self.attachments
            )
        )
        if self.room_complete != expected:
            raise ValueError("KAKAO_CAPTURE_COMPLETENESS_INVALID")
        room_capture_members(self)
        return self


def room_capture_members(report: CaptureRoomReport) -> tuple[LocalMember | CsvMember, ...]:
    return _members(
        (
            report.raw_csv,
            report.normalization,
            *(item.member for item in report.attachments if item.member is not None),
        ),
        output=True,
    )


class CaptureResult(FrozenModel):
    schema_version: Literal["kakao-collection-result/1.0"] = "kakao-collection-result/1.0"
    execution: WorkerExecution
    run_id: RunId
    source_binding_id: BindingId
    room_id: RoomId | None
    command_sha256: Sha256
    adapter_release_sha256: Sha256
    capability_revision_id: CapabilityRevisionId
    status: Literal["COMPLETED", "PARTIAL", "FAILED", "PAUSED", "CANCELLED"]
    report: LocalMember | None
    error_code: CaptureError | None

    @model_validator(mode="after")
    def result_shape(self) -> Self:
        _execution(self.execution)
        if self.status in {"COMPLETED", "PARTIAL"}:
            if self.report is None or self.error_code is not None:
                raise ValueError("KAKAO_CAPTURE_RESULT_INVALID")
            _json_member(self.report)
            _members((self.report,), output=True)
        elif self.report is not None or (
            (self.status == "FAILED") != (self.error_code is not None)
        ):
            raise ValueError("KAKAO_CAPTURE_RESULT_INVALID")
        return self


def _validate_capability(command: CaptureCommand, capability: CaptureCapability) -> None:
    validate_capture_contract("command", command.model_dump(mode="json"))
    validate_capture_contract("capability", capability.model_dump(mode="json"))
    _exact_value(command.capability, capability)
    if (
        not capability.channel_verified
        or capability.observed_at > command.issued_at
        or command.source_binding_id != capability.source_binding_id
        or command.capability_revision_id != capability.capability_revision_id
        or command.adapter_release_sha256 != capability.adapter_release_sha256
        or set(command.requested_scope_ids) != set(capability.visible_scope_ids)
    ):
        raise ValueError("KAKAO_CAPTURE_CAPABILITY_UNVERIFIED")


def _observations_supported(
    capability: CaptureCapability, report: CaptureInventory | CaptureRoomReport
) -> None:
    """A collector may report uncertainty, never silently strengthen pinned evidence."""
    if isinstance(report, CaptureInventory):
        if report.rooms and capability.room_identity == "unknown":
            raise ValueError("KAKAO_CAPTURE_CAPABILITY_ESCALATION")
        if capability.room_identity != "stable_source_id" and any(
            room.identity_level == "stable_source_id" for room in report.rooms
        ):
            raise ValueError("KAKAO_CAPTURE_CAPABILITY_ESCALATION")
        return
    for field, supported in (
        ("csv_scope", capability.csv_scope),
        ("source_order", capability.csv_order),
        ("source_timezone", capability.source_timezone),
        ("direction_evidence", capability.direction_evidence),
    ):
        if getattr(report, field) not in {"unknown", supported}:
            raise ValueError("KAKAO_CAPTURE_CAPABILITY_ESCALATION")
    if report.attachment_inventory_complete and capability.album_enumeration != "verified":
        raise ValueError("KAKAO_CAPTURE_CAPABILITY_ESCALATION")
    for attachment in report.attachments:
        if (
            attachment.quality_level == "original_verified"
            and capability.original_download != "verified_ui_download"
        ) or (
            attachment.quality_level in {"best_available", "thumbnail_only"}
            and capability.original_download not in {"verified_ui_download", "best_available"}
        ):
            raise ValueError("KAKAO_CAPTURE_CAPABILITY_ESCALATION")


def validate_capture_inputs(
    command: CaptureCommand,
    capability: CaptureCapability,
    inventory: CaptureInventory | None = None,
) -> tuple[LocalMember | CsvMember, ...]:
    """Exact materialized values only; owner must separately authorize current source access."""
    _validate_capability(command, capability)
    members: tuple[LocalMember | CsvMember, ...] = (command.capability, *capability.evidence)
    if command.operation == "INVENTORY":
        if inventory is not None:
            raise ValueError("KAKAO_CAPTURE_OPERATION_INVALID")
    else:
        if inventory is None or command.inventory is None:
            raise ValueError("KAKAO_CAPTURE_INVENTORY_REQUIRED")
        validate_capture_contract("inventory", inventory.model_dump(mode="json"))
        _exact_value(command.inventory, inventory)
        _observations_supported(capability, inventory)
        if (
            command.inventory_revision_id != inventory.inventory_revision_id
            or command.source_binding_id != inventory.source_binding_id
            or command.run_id != inventory.run_id
            or set(command.requested_scope_ids) != {scope.scope_id for scope in inventory.scopes}
            or command.room_id not in {room.room_id for room in inventory.rooms}
        ):
            raise ValueError("KAKAO_CAPTURE_ROOM_NOT_IN_INVENTORY")
        members += (command.inventory, *inventory_members(inventory))
    return _members(members)


def validate_capture_result(
    command: CaptureCommand,
    result: CaptureResult,
    report: CaptureInventory | CaptureRoomReport | None,
    *,
    capability: CaptureCapability,
    current_fence: int,
) -> tuple[LocalMember | CsvMember, ...]:
    """Result proposal, never publication authority. Bytes and ACL require owner rechecks."""
    _validate_capability(command, capability)
    validate_capture_contract("result", result.model_dump(mode="json"))
    if type(current_fence) is not int or current_fence != command.execution.fence:
        raise ValueError("KAKAO_CAPTURE_STALE_FENCE")
    if (
        result.execution != command.execution
        or result.run_id != command.run_id
        or result.source_binding_id != command.source_binding_id
        or result.room_id != command.room_id
        or result.adapter_release_sha256 != command.adapter_release_sha256
        or result.capability_revision_id != command.capability_revision_id
        or result.command_sha256 != sha256(canonical_bytes(command.model_dump(mode="json")))
    ):
        raise ValueError("KAKAO_CAPTURE_RESULT_IDENTITY_MISMATCH")
    if result.report is None:
        if report is not None:
            raise ValueError("KAKAO_CAPTURE_RESULT_INVALID")
        return ()
    if report is None:
        raise ValueError("KAKAO_CAPTURE_REPORT_REQUIRED")
    _exact_value(result.report, report)
    _observations_supported(capability, report)
    if (
        report.execution != command.execution
        or report.run_id != command.run_id
        or report.source_binding_id != command.source_binding_id
        or report.inventory_revision_id != command.inventory_revision_id
    ):
        raise ValueError("KAKAO_CAPTURE_REPORT_IDENTITY_MISMATCH")
    if isinstance(report, CaptureInventory):
        validate_capture_contract("inventory", report.model_dump(mode="json"))
        if command.operation != "INVENTORY" or set(command.requested_scope_ids) != {
            scope.scope_id for scope in report.scopes
        }:
            raise ValueError("KAKAO_CAPTURE_OPERATION_INVALID")
        complete = report.inventory_complete
        members = inventory_members(report)
        started_at = report.inventory_started_at
    else:
        validate_capture_contract("room-report", report.model_dump(mode="json"))
        if (
            command.operation != "CAPTURE_ROOM"
            or command.room_id != report.room_id
            or command.snapshot_revision_id != report.snapshot_revision_id
            or command.normalization_revision_id != report.normalization_revision_id
        ):
            raise ValueError("KAKAO_CAPTURE_REPORT_IDENTITY_MISMATCH")
        complete = report.room_complete
        members = room_capture_members(report)
        started_at = report.observed_start_at
    if (result.status == "COMPLETED") != complete or started_at < command.issued_at:
        raise ValueError("KAKAO_CAPTURE_COMPLETENESS_INVALID")
    closure = _members((result.report, *members), output=True)
    if result.report.relative_path in {member.relative_path for member in members}:
        raise ValueError("KAKAO_CAPTURE_MEMBER_COLLISION")
    return closure


CollectionState = Literal[
    "QUEUED",
    "INVENTORY",
    "COLLECTING",
    "RECONCILING",
    "PAUSING",
    "PAUSED",
    "AUTH_REQUIRED",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "CANCELLED",
]
CollectionEvent = Literal[
    "CLAIM",
    "INVENTORY_ACCEPTED",
    "ROOMS_FINISHED",
    "RECONCILED_COMPLETE",
    "RECONCILED_PARTIAL",
    "AUTH_LOST",
    "PAUSE_REQUESTED",
    "CANCEL_REQUESTED",
    "STOP_CONFIRMED",
    "RESUME",
    "FAIL",
]
_TRANSITIONS: dict[tuple[CollectionState, CollectionEvent], CollectionState] = {
    ("QUEUED", "CLAIM"): "INVENTORY",
    ("INVENTORY", "INVENTORY_ACCEPTED"): "COLLECTING",
    ("COLLECTING", "ROOMS_FINISHED"): "RECONCILING",
    ("RECONCILING", "RECONCILED_COMPLETE"): "COMPLETED",
    ("RECONCILING", "RECONCILED_PARTIAL"): "PARTIAL",
    ("PAUSED", "RESUME"): "QUEUED",
    ("AUTH_REQUIRED", "RESUME"): "QUEUED",
    ("QUEUED", "CANCEL_REQUESTED"): "CANCELLED",
    ("PAUSED", "CANCEL_REQUESTED"): "CANCELLED",
    ("AUTH_REQUIRED", "CANCEL_REQUESTED"): "CANCELLED",
    ("INVENTORY", "AUTH_LOST"): "AUTH_REQUIRED",
    ("COLLECTING", "AUTH_LOST"): "AUTH_REQUIRED",
    ("RECONCILING", "AUTH_LOST"): "AUTH_REQUIRED",
    ("QUEUED", "FAIL"): "FAILED",
    ("INVENTORY", "FAIL"): "FAILED",
    ("COLLECTING", "FAIL"): "FAILED",
    ("RECONCILING", "FAIL"): "FAILED",
}


@dataclass(frozen=True, slots=True)
class CollectionProgress:
    state: CollectionState
    stop_target: Literal["PAUSED", "CANCELLED"] | None = None

    def __post_init__(self) -> None:
        if (self.state == "PAUSING") != (self.stop_target is not None):
            raise ValueError("KAKAO_CAPTURE_STOP_TARGET_INVALID")


def transition_collection(
    current: CollectionProgress,
    event: CollectionEvent,
    *,
    profile: ProfileFence | None = None,
    stopped: ProfileStopReceipt | None = None,
    now: datetime | None = None,
) -> CollectionProgress:
    """Owner events; RESUME still requires fresh authorization/channel probe before claim."""
    if current.state in {"INVENTORY", "COLLECTING", "RECONCILING"} and event in {
        "PAUSE_REQUESTED",
        "CANCEL_REQUESTED",
    }:
        return CollectionProgress(
            "PAUSING", "PAUSED" if event == "PAUSE_REQUESTED" else "CANCELLED"
        )
    if current.state == "PAUSING" and event == "STOP_CONFIRMED":
        if profile is None or stopped is None or now is None or profile.mode != "PAUSING":
            raise ValueError("KAKAO_CAPTURE_PRIOR_STOP_UNCONFIRMED")
        validate_profile_handoff(
            profile, stopped, target_mode="STOPPED", next_fence=profile.fence_epoch + 1, now=now
        )
        assert current.stop_target is not None
        return CollectionProgress(current.stop_target)
    target = _TRANSITIONS.get((current.state, event))
    if target is None:
        raise ValueError("KAKAO_CAPTURE_TRANSITION_INVALID")
    return CollectionProgress(target)


RecoveryAction = Literal[
    "RECONCILE_SAME_ATTEMPT",
    "RECOVER_PUBLICATION",
    "WAIT_AUTH",
    "WAIT_AUTHORITY_CHANGE",
    "WAIT_ADAPTER_REVIEW",
    "WAIT_STORAGE",
    "WAIT_RATE_LIMIT",
    "WAIT_PRIOR_STOP",
    "RETRY_NEW_ATTEMPT",
    "STOP",
]
AttemptOutcome = Literal["UNKNOWN", "TERMINAL_FAILED", "LOCAL_ACCEPTED", "PUBLISHED"]
_RECOVERY: dict[CaptureError, RecoveryAction] = {
    "AUTH_REQUIRED": "WAIT_AUTH",
    "ACCESS_DENIED": "WAIT_AUTHORITY_CHANGE",
    "UI_CHANGED": "WAIT_ADAPTER_REVIEW",
    "ENUMERATION_STALLED": "WAIT_ADAPTER_REVIEW",
    "HASH_MISMATCH": "WAIT_ADAPTER_REVIEW",
    "DISK_FULL": "WAIT_STORAGE",
    "RATE_LIMITED": "WAIT_RATE_LIMIT",
    "INVALID_INPUT": "STOP",
    "PUBLICATION_UNAVAILABLE": "RECONCILE_SAME_ATTEMPT",
    "TIMEOUT": "RECONCILE_SAME_ATTEMPT",
}


def capture_recovery(
    command: CaptureCommand,
    error: CaptureError,
    *,
    outcome: AttemptOutcome,
    now: datetime,
    profile: ProfileFence | None = None,
    stopped: ProfileStopReceipt | None = None,
) -> RecoveryAction:
    """No automatic launch; even the retry decision requires a new authorized fenced claim."""
    if outcome == "UNKNOWN":
        return "RECONCILE_SAME_ATTEMPT"
    if outcome in {"LOCAL_ACCEPTED", "PUBLISHED"}:
        return "RECOVER_PUBLICATION"
    if error != "NETWORK_TRANSIENT":
        return _RECOVERY[error]
    if command.execution.attempt_number >= 4:
        return "STOP"
    if (
        profile is None
        or stopped is None
        or (profile.profile_id, profile.browser_run_id, profile.fence_epoch)
        != (command.profile_id, command.browser_run_id, command.execution.fence)
    ):
        return "WAIT_PRIOR_STOP"
    try:
        validate_profile_handoff(
            profile, stopped, target_mode="STOPPED", next_fence=profile.fence_epoch + 1, now=now
        )
    except ValueError:
        return "WAIT_PRIOR_STOP"
    return "RETRY_NEW_ATTEMPT"


@lru_cache(maxsize=5)
def _validator(kind: SchemaKind) -> Draft202012Validator:
    raw = (
        files("eom_kakao_archive_contracts")
        .joinpath("schemas/worker-collection-v1.schema.json")
        .read_bytes()
    )
    if sha256(raw) != SCHEMA_SHA256:
        raise ValueError("KAKAO_CAPTURE_SCHEMA_HASH_MISMATCH")
    schema: dict[str, Any] = json.loads(raw)
    Draft202012Validator.check_schema(schema)
    schema.pop("oneOf")
    schema["$ref"] = "#/$defs/" + kind
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_capture_contract(kind: SchemaKind, value: object) -> None:
    try:
        _validator(kind).validate(value)
    except ValidationError:
        # A JSON Schema error may embed untrusted source text; don't expose it upstream.
        raise ValueError("KAKAO_CAPTURE_SCHEMA_INVALID") from None
