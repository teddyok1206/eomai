"""Bounded Studio packet/export projections; Catalog retains rules and source authority."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from .contracts import UtcDatetime, WebModel
from .kakao_archive_contracts import Label, ResourceVersion
from .kakao_question_contracts import BindingId, QuestionId, RevisionId

PacketId = Annotated[str, Field(pattern=r"^kakaopacket_[0-9a-f]{32}$")]
PacketRevisionId = Annotated[str, Field(pattern=r"^kakaopacketrev_[0-9a-f]{32}$")]
StudentId = Annotated[str, Field(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
ExportId = Annotated[str, Field(pattern=r"^kakaoexport_[0-9a-f]{32}$")]
ExportRevisionId = Annotated[str, Field(pattern=r"^kakaoexportrev_[0-9a-f]{32}$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class KakaoArtifactPointer(WebModel):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    media_type: str = Field(min_length=1, max_length=128)
    schema_ref: str = Field(min_length=1, max_length=256)
    sha256: Sha256


class PacketQuestion(WebModel):
    question_id: QuestionId
    question_revision_id: RevisionId


class PacketCreate(WebModel):
    schema_version: Literal["kakao-packet-create/1.0"]
    source_binding_id: BindingId
    title: Label
    questions: tuple[PacketQuestion, ...] = Field(min_length=1, max_length=200)
    display_start_date: date
    display_end_date_inclusive: date
    mode: Literal["DRAFT", "FINAL"]
    include_replies: bool = Field(strict=True)


class StoredPacket(WebModel):
    schema_version: Literal["kakao-stored-packet/1.0"]
    source_binding_id: BindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    previous_revision_id: PacketRevisionId | None
    resource_version: ResourceVersion
    title: Label
    manifest: KakaoArtifactPointer
    display_start_date: date
    display_end_date_inclusive: date
    mode: Literal["DRAFT", "FINAL"]
    include_replies: bool = Field(strict=True)
    question_count: int = Field(strict=True, ge=1, le=200)
    student_count: int = Field(strict=True, ge=1, le=200)
    created_at: UtcDatetime


class PacketMutation(WebModel):
    schema_version: Literal["kakao-packet-mutation/1.0"]
    packet: StoredPacket
    replayed: bool = Field(strict=True)


class PacketPage(WebModel):
    schema_version: Literal["kakao-packet-page/1.0"]
    items: tuple[StoredPacket, ...] = Field(max_length=100)
    next_cursor: PacketId | None


class PacketStudent(WebModel):
    student_id: StudentId
    student_display_revision_id: str = Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")
    display_name: Label
    question_count: int = Field(strict=True, ge=1, le=200)


class PacketView(WebModel):
    schema_version: Literal["kakao-packet-view/1.0"]
    packet: StoredPacket
    questions: tuple[PacketQuestion, ...] = Field(min_length=1, max_length=200)
    students: tuple[PacketStudent, ...] = Field(min_length=1, max_length=200)


class ExportProfile(WebModel):
    renderer_release_sha256: Sha256
    font_sha256: Sha256
    font_size_bytes: int = Field(strict=True, ge=1, le=32 * 1024 * 1024)
    layout_policy: Literal["student-question-a4/1.0"]


class ExportCreate(WebModel):
    schema_version: Literal["kakao-export-create/1.0"]
    source_binding_id: BindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: StudentId


class StudentExport(WebModel):
    schema_version: Literal["kakao-export/1.0"]
    source_binding_id: BindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: StudentId
    export_id: ExportId
    profile: ExportProfile
    subset_sha256: Sha256
    mode: Literal["DRAFT", "FINAL"]
    state: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "NEEDS_LAYOUT_REVIEW"]
    created_at: UtcDatetime
    completed_at: UtcDatetime | None
    export_revision_id: ExportRevisionId | None
    page_count: int = Field(strict=True, ge=0, le=200)
    pdf: KakaoArtifactPointer | None
    layout: KakaoArtifactPointer | None
    error_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,79}$")


class ExportMutation(WebModel):
    schema_version: Literal["kakao-export-mutation/1.0"]
    export: StudentExport
    replayed: bool = Field(strict=True)


class ExportPage(WebModel):
    schema_version: Literal["kakao-export-page/1.0"]
    items: tuple[StudentExport, ...] = Field(max_length=100)
    next_cursor: ExportId | None
