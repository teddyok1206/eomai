"""Accepted private source identities, not a worker's authority declaration."""

from typing import Annotated, Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import Field, model_validator

from eom_catalog_contracts.kakao_archive import (
    KakaoBindingId,
    KakaoNormalizationRevisionId,
    KakaoRoomId,
    KakaoSnapshotRevisionId,
    RowOrdinal,
)
from eom_catalog_contracts.kakao_media import MEDIA_BLOB_REF, MEDIA_FORMAT_REF
from eom_catalog_contracts.kakao_question import NORMALIZATION_REF
from eom_catalog_contracts.kakao_snapshot import CSV_FORMAT_REF, SNAPSHOT_REF
from eom_catalog_contracts.models import FrozenModel, Sha256, UtcDatetime
from eom_catalog_contracts.validation import validate_contract

SOURCE_RESOLUTION_REF = "eom://schemas/kakao-archive/source-resolution-v1/1.0"
CAPTURE_REF = "eom://schemas/kakao-archive/worker-collection-v1/1.0"
SourceRevisionId = Annotated[str, Field(pattern=r"^kakaosourcerev_[0-9a-f]{32}$")]
CommandId = Annotated[str, Field(pattern=r"^kakaocommand_[0-9a-f]{32}$")]


def _pointer(pointer: ArtifactMemberPointer, schema: str, media: str) -> None:
    if pointer.schema_ref != schema or pointer.media_type != media:
        raise ValueError("KAKAO_ARCHIVE_SOURCE_POINTER_INVALID")


class KakaoCaptureAuthority(FrozenModel):
    """Pins to be resolved against the actual accepted capture owner, not permissions."""

    run_id: str = Field(pattern=r"^kakaorun_[0-9a-f]{32}$")
    attempt_id: str = Field(pattern=r"^kakaoattempt_[0-9a-f]{32}$")
    fence: int = Field(strict=True, ge=1, le=2147483647)
    command_sha256: Sha256
    capability_revision_id: str = Field(pattern=r"^kakaocapabilityrev_[0-9a-f]{32}$")
    adapter_release_sha256: Sha256
    command: ArtifactMemberPointer
    capability: ArtifactMemberPointer
    capture_report: ArtifactMemberPointer
    capture_result: ArtifactMemberPointer

    @model_validator(mode="after")
    def evidence_pointers(self) -> Self:
        for pointer in (self.command, self.capability, self.capture_report, self.capture_result):
            _pointer(pointer, CAPTURE_REF, "application/json")
        return self


class KakaoSourceAttachment(FrozenModel):
    attachment_id: str = Field(pattern=r"^kakaoattachment_[0-9a-f]{32}$")
    attachment_revision_id: str = Field(pattern=r"^kakaoattachmentrev_[0-9a-f]{32}$")
    original: ArtifactMemberPointer | None
    media_receipt: ArtifactMemberPointer | None
    quality: Literal["ORIGINAL", "BEST_AVAILABLE", "UNKNOWN"]

    @model_validator(mode="after")
    def media_pair(self) -> Self:
        if (self.original is None) != (self.media_receipt is None):
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_POINTER_INVALID")
        if self.original is None:
            if self.quality != "UNKNOWN":
                raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_QUALITY_INVALID")
        else:
            assert self.media_receipt is not None
            _pointer(self.media_receipt, MEDIA_BLOB_REF, "application/json")
            if self.original.schema_ref != MEDIA_FORMAT_REF or self.original.media_type not in {
                "image/png",
                "image/jpeg",
                "image/webp",
            }:
                raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_POINTER_INVALID")
        return self


class KakaoSourceAdmission(FrozenModel):
    schema_version: Literal["kakao-source-admission/1.0"] = "kakao-source-admission/1.0"
    source_binding_id: KakaoBindingId
    room_id: KakaoRoomId
    snapshot_revision_id: KakaoSnapshotRevisionId
    normalization_revision_id: KakaoNormalizationRevisionId
    expected_source_revision_id: SourceRevisionId | None
    expected_resource_version: int = Field(strict=True, ge=0, le=2147483646)
    source: ArtifactMemberPointer
    snapshot: ArtifactMemberPointer
    normalization: ArtifactMemberPointer
    authority: KakaoCaptureAuthority
    attachments: tuple[KakaoSourceAttachment, ...] = Field(max_length=2000)

    @model_validator(mode="after")
    def exact_inputs(self) -> Self:
        _pointer(self.source, CSV_FORMAT_REF, "text/csv")
        _pointer(self.snapshot, SNAPSHOT_REF, "application/json")
        _pointer(self.normalization, NORMALIZATION_REF, "application/json")
        if (self.expected_source_revision_id is None) != (self.expected_resource_version == 0):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_PRECONDITION_INVALID")
        if len({a.attachment_id for a in self.attachments}) != len(self.attachments):
            raise ValueError("KAKAO_ARCHIVE_ATTACHMENT_DUPLICATED")
        validate_contract("kakao-source-admission-v1", self.model_dump(mode="json"))
        return self


class KakaoSourceRow(FrozenModel):
    row_ordinal: RowOrdinal
    occurrence_id: str = Field(pattern=r"^kakaomessage_[0-9a-f]{32}$")
    previous_row_ordinal: RowOrdinal | None
    association: Literal["SOURCE_VERIFIED", "SEQUENCE_INFERRED", "SNAPSHOT_ONLY", "UNRESOLVED"]
    source_content_changed: bool = Field(strict=True)
    evidence_changed: bool = Field(strict=True)

    @model_validator(mode="after")
    def correspondence(self) -> Self:
        if (self.previous_row_ordinal is not None) != (
            self.association in {"SOURCE_VERIFIED", "SEQUENCE_INFERRED"}
        ):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        if self.previous_row_ordinal is None and (
            self.source_content_changed or self.evidence_changed
        ):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        return self


class KakaoSourceResolution(FrozenModel):
    schema_version: Literal["kakao-source-resolution/1.0"] = "kakao-source-resolution/1.0"
    source_revision_id: SourceRevisionId
    command_id: CommandId
    resource_version: int = Field(strict=True, ge=1, le=2147483647)
    admission: KakaoSourceAdmission
    created_by: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    created_at: UtcDatetime
    observed_at: UtcDatetime
    rows: tuple[KakaoSourceRow, ...] = Field(max_length=100000)
    previous_unmatched_rows: tuple[RowOrdinal, ...] = Field(max_length=100000)

    @model_validator(mode="after")
    def exact_rows(self) -> Self:
        if self.resource_version != self.admission.expected_resource_version + 1:
            raise ValueError("KAKAO_ARCHIVE_SOURCE_VERSION_INVALID")
        if self.source_revision_id == self.admission.expected_source_revision_id:
            raise ValueError("KAKAO_ARCHIVE_REVISION_REUSED")
        if self.observed_at > self.created_at:
            raise ValueError("KAKAO_ARCHIVE_SOURCE_TIME_INVALID")
        if tuple(r.row_ordinal for r in self.rows) != tuple(range(1, len(self.rows) + 1)):
            raise ValueError("KAKAO_ARCHIVE_ROW_ORDER_INVALID")
        if len({r.occurrence_id for r in self.rows}) != len(self.rows):
            raise ValueError("KAKAO_ARCHIVE_OCCURRENCE_DUPLICATED")
        previous = tuple(
            r.previous_row_ordinal for r in self.rows if r.previous_row_ordinal is not None
        )
        if len(set(previous)) != len(previous) or set(previous) & set(self.previous_unmatched_rows):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        if tuple(sorted(set(self.previous_unmatched_rows))) != self.previous_unmatched_rows:
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        if self.admission.expected_source_revision_id is None and (
            previous or self.previous_unmatched_rows
        ):
            raise ValueError("KAKAO_ARCHIVE_SOURCE_CORRESPONDENCE_INVALID")
        validate_contract("kakao-source-resolution-v1", self.model_dump(mode="json"))
        return self
