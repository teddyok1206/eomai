"""Closed API-only packet/PDF transport. No caller runtime paths or execution grants."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_export_store import (
    ExportId,
    ExportRevisionId,
    KakaoExport,
    KakaoExportCreate,
    KakaoExportMutation,
    KakaoExportPage,
)
from .kakao_packet_store import (
    KakaoPacketCreate,
    KakaoPacketMutation,
    KakaoPacketPage,
    KakaoPacketRevise,
    KakaoStoredPacket,
    PacketId,
    PacketRevisionId,
)
from .kakao_question import KakaoQuestionProvenance, StudentId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

type KakaoDeliveryOperation = Literal[
    "SAVE_KAKAO_PACKET",
    "READ_KAKAO_PACKET",
    "LIST_KAKAO_PACKETS",
    "CREATE_KAKAO_EXPORT",
    "READ_KAKAO_EXPORT",
    "LIST_KAKAO_EXPORTS",
    "READ_KAKAO_EXPORT_PDF",
]
KAKAO_DELIVERY_OPERATIONS = frozenset(get_args(KakaoDeliveryOperation.__value__))

type KakaoDeliveryError = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_RETIRED",
    "KAKAO_ARCHIVE_STUDENT_UNMAPPED",
    "KAKAO_ARCHIVE_QUESTION_EXCLUDED",
    "KAKAO_ARCHIVE_EMPTY_SELECTION",
    "KAKAO_ARCHIVE_STUDENT_NOT_IN_PACKET",
    "KAKAO_ARCHIVE_FINAL_BLOCKED",
    "KAKAO_ARCHIVE_QUESTION_OUTSIDE_PERIOD",
    "KAKAO_ARCHIVE_STUDENT_DISPLAY_CONFLICT",
    "KAKAO_ARCHIVE_PERIOD_INVALID",
    "KAKAO_ARCHIVE_TIME_INVALID",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "KAKAO_ARCHIVE_EXPORT_NOT_COMPLETED",
    "KAKAO_ARCHIVE_EXPORT_RUNTIME_MISMATCH",
    "KAKAO_ARCHIVE_EXPORT_EXECUTION_MISMATCH",
    "KAKAO_ARCHIVE_EXPORT_NOT_RUNNING",
    "KAKAO_ARCHIVE_EXPORT_RETRY_DENIED",
    "KAKAO_ARCHIVE_PDF_RUNTIME_UNAVAILABLE",
    "KAKAO_ARCHIVE_PDF_CAPACITY_BUSY",
    "KAKAO_ARCHIVE_STORED_PACKET_INVALID",
    "KAKAO_ARCHIVE_STORED_EXPORT_INVALID",
    "KAKAO_ARCHIVE_ADMISSION_EVIDENCE_INVALID",
    "KAKAO_ARCHIVE_STORED_SOURCE_INVALID",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_DELIVERY_ERRORS = frozenset(get_args(KakaoDeliveryError.__value__))


class KakaoPacketStudent(FrozenModel):
    student_id: StudentId
    student_display_revision_id: str = Field(pattern=r"^kakaostudentrev_[0-9a-f]{32}$")
    display_name: str = Field(min_length=1, max_length=128)
    question_count: int = Field(strict=True, ge=1, le=200)


class KakaoPacketView(FrozenModel):
    schema_version: Literal["kakao-packet-view/1.0"] = "kakao-packet-view/1.0"
    packet: KakaoStoredPacket
    questions: tuple[KakaoQuestionProvenance, ...] = Field(min_length=1, max_length=200)
    students: tuple[KakaoPacketStudent, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_members(self) -> "KakaoPacketView":
        if (
            len(self.questions) != self.packet.question_count
            or len({q.question_id for q in self.questions}) != len(self.questions)
            or len({s.student_id for s in self.students}) != len(self.students)
            or len(self.students) != self.packet.student_count
            or sum(s.question_count for s in self.students) != len(self.questions)
        ):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class KakaoExportPdf(FrozenModel):
    schema_version: Literal["kakao-export-pdf/1.0"] = "kakao-export-pdf/1.0"
    source_binding_id: KakaoBindingId
    export_id: ExportId
    export_revision_id: ExportRevisionId
    media_type: Literal["application/pdf"] = "application/pdf"
    content_length: int = Field(strict=True, ge=1, le=128 * 1024 * 1024)
    sha256: Sha256


class _Identity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class SaveKakaoPacketRequest(_Identity):
    operation: Literal["SAVE_KAKAO_PACKET"] = "SAVE_KAKAO_PACKET"
    command: Annotated[KakaoPacketCreate | KakaoPacketRevise, Field(discriminator="schema_version")]
    idempotency_key: IdempotencyKey


class ReadKakaoPacketRequest(_Identity):
    operation: Literal["READ_KAKAO_PACKET"] = "READ_KAKAO_PACKET"
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId


class _Page(_Identity):
    source_binding_id: KakaoBindingId
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class ListKakaoPacketsRequest(_Page):
    operation: Literal["LIST_KAKAO_PACKETS"] = "LIST_KAKAO_PACKETS"
    cursor: PacketId | None = None


class CreateKakaoExportRequest(_Identity):
    operation: Literal["CREATE_KAKAO_EXPORT"] = "CREATE_KAKAO_EXPORT"
    command: KakaoExportCreate
    idempotency_key: IdempotencyKey


class ReadKakaoExportRequest(_Identity):
    operation: Literal["READ_KAKAO_EXPORT"] = "READ_KAKAO_EXPORT"
    source_binding_id: KakaoBindingId
    export_id: ExportId


class ListKakaoExportsRequest(_Page):
    operation: Literal["LIST_KAKAO_EXPORTS"] = "LIST_KAKAO_EXPORTS"
    cursor: ExportId | None = None


class ReadKakaoExportPdfRequest(_Identity):
    operation: Literal["READ_KAKAO_EXPORT_PDF"] = "READ_KAKAO_EXPORT_PDF"
    source_binding_id: KakaoBindingId
    export_id: ExportId
    export_revision_id: ExportRevisionId


type KakaoDeliveryRequest = Annotated[
    SaveKakaoPacketRequest
    | ReadKakaoPacketRequest
    | ListKakaoPacketsRequest
    | CreateKakaoExportRequest
    | ReadKakaoExportRequest
    | ListKakaoExportsRequest
    | ReadKakaoExportPdfRequest,
    Field(discriminator="operation"),
]
type KakaoDeliveryResult = Annotated[
    KakaoPacketMutation
    | KakaoPacketView
    | KakaoPacketPage
    | KakaoExportMutation
    | KakaoExport
    | KakaoExportPage
    | KakaoExportPdf,
    Field(discriminator="schema_version"),
]


class KakaoDeliverySuccess(FrozenModel):
    operation: KakaoDeliveryOperation
    request_id: RequestId
    status: Literal["OK"] = "OK"
    result: KakaoDeliveryResult
    error_code: None = None


class KakaoDeliveryFailure(FrozenModel):
    operation: KakaoDeliveryOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: KakaoDeliveryError


type KakaoDeliveryReply = Annotated[
    KakaoDeliverySuccess | KakaoDeliveryFailure, Field(discriminator="status")
]
_REQUEST: TypeAdapter[KakaoDeliveryRequest] = TypeAdapter(KakaoDeliveryRequest)
_REPLY: TypeAdapter[KakaoDeliveryReply] = TypeAdapter(KakaoDeliveryReply)


def parse_kakao_delivery_request(value: dict[str, object]) -> KakaoDeliveryRequest:
    validate_contract("catalog-kakao-delivery-v1", value)
    return _REQUEST.validate_python(value)


def parse_kakao_delivery_reply(value: dict[str, object]) -> KakaoDeliveryReply:
    validate_contract("catalog-kakao-delivery-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_delivery_reply(request: KakaoDeliveryRequest, reply: KakaoDeliveryReply) -> None:
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if (request.operation, request.request_id) != (reply.operation, reply.request_id):
        raise ValueError(invalid)
    if isinstance(reply, KakaoDeliveryFailure):
        return
    result = reply.result
    if isinstance(request, SaveKakaoPacketRequest):
        if not isinstance(result, KakaoPacketMutation):
            raise ValueError(invalid)
        packet, command = result.packet, request.command
        if any(
            getattr(packet, key) != getattr(command, key)
            for key in (
                "source_binding_id",
                "title",
                "display_start_date",
                "display_end_date_inclusive",
                "mode",
                "include_replies",
            )
        ):
            raise ValueError(invalid)
        if isinstance(command, KakaoPacketRevise):
            if (packet.packet_id, packet.previous_revision_id, packet.resource_version) != (
                command.packet_id,
                command.parent_revision_id,
                command.expected_resource_version + 1,
            ):
                raise ValueError(invalid)
        elif packet.previous_revision_id is not None or packet.resource_version != 1:
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoPacketRequest):
        if not isinstance(result, KakaoPacketView) or (
            result.packet.source_binding_id,
            result.packet.packet_id,
            result.packet.packet_revision_id,
        ) != (request.source_binding_id, request.packet_id, request.packet_revision_id):
            raise ValueError(invalid)
    elif isinstance(request, CreateKakaoExportRequest):
        if not isinstance(result, KakaoExportMutation) or any(
            getattr(result.export, key) != getattr(request.command, key)
            for key in ("source_binding_id", "packet_id", "packet_revision_id", "student_id")
        ):
            raise ValueError(invalid)
    elif isinstance(request, (ListKakaoPacketsRequest, ListKakaoExportsRequest)):
        packet_page = isinstance(request, ListKakaoPacketsRequest)
        if not isinstance(result, KakaoPacketPage if packet_page else KakaoExportPage):
            raise ValueError(invalid)
        id_key = "packet_id" if packet_page else "export_id"
        if (
            len(result.items) > request.limit
            or any(
                row.source_binding_id != request.source_binding_id
                or (request.cursor is not None and getattr(row, id_key) <= request.cursor)
                for row in result.items
            )
            or (result.next_cursor is not None and len(result.items) != request.limit)
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoExportPdfRequest):
        if not isinstance(result, KakaoExportPdf) or (
            result.source_binding_id,
            result.export_id,
            result.export_revision_id,
        ) != (request.source_binding_id, request.export_id, request.export_revision_id):
            raise ValueError(invalid)
    elif not isinstance(result, KakaoExport) or (result.source_binding_id, result.export_id) != (
        request.source_binding_id,
        request.export_id,
    ):
        raise ValueError(invalid)
