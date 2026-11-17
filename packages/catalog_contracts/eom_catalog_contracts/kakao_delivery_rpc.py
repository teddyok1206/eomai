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
from .kakao_study_export import KakaoStudyExport, KakaoStudyExportCreate, KakaoStudyExportMutation
from .kakao_study_store import (
    KakaoStoredStudy,
    KakaoStudyCreate,
    KakaoStudyMutation,
    KakaoStudyPage,
    KakaoStudyQuestionEdit,
    KakaoStudyRevise,
    StudyId,
    StudyRevisionId,
)
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
    "SAVE_KAKAO_STUDY",
    "READ_KAKAO_STUDY",
    "LIST_KAKAO_STUDIES",
    "CREATE_KAKAO_STUDY_EXPORT",
    "READ_KAKAO_STUDY_EXPORT",
    "READ_KAKAO_STUDY_SELECTION",
]
KAKAO_DELIVERY_OPERATIONS = frozenset(get_args(KakaoDeliveryOperation.__value__))
KAKAO_STUDY_OPERATIONS = frozenset(
    {
        "SAVE_KAKAO_STUDY",
        "READ_KAKAO_STUDY",
        "LIST_KAKAO_STUDIES",
        "CREATE_KAKAO_STUDY_EXPORT",
        "READ_KAKAO_STUDY_EXPORT",
        "READ_KAKAO_STUDY_SELECTION",
    }
)

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
    "KAKAO_STUDY_RUNTIME_UNAVAILABLE",
    "KAKAO_STUDY_PACKET_CHANGED",
    "KAKAO_STUDY_QUESTION_SET_MISMATCH",
    "KAKAO_STUDY_CONCEPT_QUESTION_MISMATCH",
    "KAKAO_STUDY_BLOCK_SELECTION_INVALID",
    "KAKAO_STUDY_SOURCE_CHANGED",
    "KAKAO_STUDY_MANIFEST_INVALID",
    "KAKAO_STUDY_PUBLICATION_MISMATCH",
    "KAKAO_STUDY_EXPORT_INVALID",
    "KAKAO_STUDY_CONTRACT_INVALID",
    "KAKAO_CONCEPT_RUNTIME_UNAVAILABLE",
    "KAKAO_CONCEPT_RESULT_NOT_READY",
    "KAKAO_CONCEPT_RESULT_POINTER_INVALID",
]
KAKAO_DELIVERY_ERRORS = frozenset(get_args(KakaoDeliveryError.__value__))
KAKAO_STUDY_ERRORS = frozenset(
    {
        "KAKAO_STUDY_RUNTIME_UNAVAILABLE",
        "KAKAO_STUDY_PACKET_CHANGED",
        "KAKAO_STUDY_QUESTION_SET_MISMATCH",
        "KAKAO_STUDY_CONCEPT_QUESTION_MISMATCH",
        "KAKAO_STUDY_BLOCK_SELECTION_INVALID",
        "KAKAO_STUDY_SOURCE_CHANGED",
        "KAKAO_STUDY_MANIFEST_INVALID",
        "KAKAO_STUDY_PUBLICATION_MISMATCH",
        "KAKAO_STUDY_EXPORT_INVALID",
        "KAKAO_STUDY_CONTRACT_INVALID",
        "KAKAO_CONCEPT_RUNTIME_UNAVAILABLE",
        "KAKAO_CONCEPT_RESULT_NOT_READY",
        "KAKAO_CONCEPT_RESULT_POINTER_INVALID",
    }
)


class KakaoStudyView(FrozenModel):
    """Only editable values, not copied question/textbook/model result bodies."""

    schema_version: Literal["kakao-study-view/1.0"] = "kakao-study-view/1.0"
    study: KakaoStoredStudy
    questions: tuple[KakaoStudyQuestionEdit, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def exact_questions(self) -> "KakaoStudyView":
        if len(self.questions) != self.study.question_count or len(
            {q.question_revision_id for q in self.questions}
        ) != len(self.questions):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


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


class SaveKakaoStudyRequest(_Identity):
    operation: Literal["SAVE_KAKAO_STUDY"] = "SAVE_KAKAO_STUDY"
    command: Annotated[KakaoStudyCreate | KakaoStudyRevise, Field(discriminator="schema_version")]
    idempotency_key: IdempotencyKey


class ReadKakaoStudyRequest(_Identity):
    operation: Literal["READ_KAKAO_STUDY"] = "READ_KAKAO_STUDY"
    source_binding_id: KakaoBindingId
    study_id: StudyId
    study_revision_id: StudyRevisionId


class ListKakaoStudiesRequest(_Page):
    operation: Literal["LIST_KAKAO_STUDIES"] = "LIST_KAKAO_STUDIES"
    cursor: StudyId | None = None


class CreateKakaoStudyExportRequest(_Identity):
    operation: Literal["CREATE_KAKAO_STUDY_EXPORT"] = "CREATE_KAKAO_STUDY_EXPORT"
    command: KakaoStudyExportCreate
    idempotency_key: IdempotencyKey


class ReadKakaoStudyExportRequest(_Identity):
    operation: Literal["READ_KAKAO_STUDY_EXPORT"] = "READ_KAKAO_STUDY_EXPORT"
    source_binding_id: KakaoBindingId
    export_id: ExportId


class ReadKakaoStudySelectionRequest(_Identity):
    operation: Literal["READ_KAKAO_STUDY_SELECTION"] = "READ_KAKAO_STUDY_SELECTION"
    source_binding_id: KakaoBindingId
    packet_id: PacketId
    packet_revision_id: PacketRevisionId
    student_id: StudentId


type KakaoDeliveryRequest = Annotated[
    SaveKakaoPacketRequest
    | ReadKakaoPacketRequest
    | ListKakaoPacketsRequest
    | CreateKakaoExportRequest
    | ReadKakaoExportRequest
    | ListKakaoExportsRequest
    | ReadKakaoExportPdfRequest
    | SaveKakaoStudyRequest
    | ReadKakaoStudyRequest
    | ListKakaoStudiesRequest
    | CreateKakaoStudyExportRequest
    | ReadKakaoStudyExportRequest
    | ReadKakaoStudySelectionRequest,
    Field(discriminator="operation"),
]
type KakaoDeliveryResult = Annotated[
    KakaoPacketMutation
    | KakaoPacketView
    | KakaoPacketPage
    | KakaoExportMutation
    | KakaoExport
    | KakaoExportPage
    | KakaoExportPdf
    | KakaoStudyMutation
    | KakaoStudyView
    | KakaoStudyPage
    | KakaoStudyExportMutation
    | KakaoStudyExport
    | KakaoStudyCreate,
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
    operation = value.get("operation")
    validate_contract(
        "catalog-kakao-study-v1"
        if isinstance(operation, str) and operation in KAKAO_STUDY_OPERATIONS
        else "catalog-kakao-delivery-v1",
        value,
    )
    return _REQUEST.validate_python(value)


def parse_kakao_delivery_reply(value: dict[str, object]) -> KakaoDeliveryReply:
    operation = value.get("operation")
    if isinstance(operation, str) and operation in KAKAO_STUDY_OPERATIONS:
        validate_contract("catalog-kakao-study-v1", value)
        return _REPLY.validate_python(value)
    result = value.get("result")
    study = isinstance(result, dict) and result.get("schema_version") in {
        "kakao-export/2.0",
        "kakao-export-mutation/2.0",
        "kakao-export-page/2.0",
    }
    validate_contract("catalog-kakao-delivery-v2" if study else "catalog-kakao-delivery-v1", value)
    return _REPLY.validate_python(value)


def check_kakao_delivery_reply(request: KakaoDeliveryRequest, reply: KakaoDeliveryReply) -> None:
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if (request.operation, request.request_id) != (reply.operation, reply.request_id):
        raise ValueError(invalid)
    if isinstance(reply, KakaoDeliveryFailure):
        return
    result = reply.result
    if isinstance(request, SaveKakaoStudyRequest):
        if not isinstance(result, KakaoStudyMutation):
            raise ValueError(invalid)
        study, study_command = result.study, request.command
        if any(
            getattr(study, key) != getattr(study_command, key)
            for key in (
                "source_binding_id",
                "packet_id",
                "packet_revision_id",
                "student_id",
                "title",
            )
        ) or study.question_count != len(study_command.questions):
            raise ValueError(invalid)
        if isinstance(study_command, KakaoStudyRevise):
            if (study.study_id, study.previous_revision_id, study.resource_version) != (
                study_command.study_id,
                study_command.parent_revision_id,
                study_command.expected_resource_version + 1,
            ):
                raise ValueError(invalid)
        elif study.previous_revision_id is not None or study.resource_version != 1:
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoStudyRequest):
        if not isinstance(result, KakaoStudyView) or (
            result.study.source_binding_id,
            result.study.study_id,
            result.study.study_revision_id,
        ) != (request.source_binding_id, request.study_id, request.study_revision_id):
            raise ValueError(invalid)
    elif isinstance(request, ListKakaoStudiesRequest):
        if not isinstance(result, KakaoStudyPage) or (
            len(result.items) > request.limit
            or any(
                row.source_binding_id != request.source_binding_id
                or (request.cursor is not None and row.study_id <= request.cursor)
                for row in result.items
            )
            or (result.next_cursor is not None and len(result.items) != request.limit)
        ):
            raise ValueError(invalid)
    elif isinstance(request, CreateKakaoStudyExportRequest):
        if (
            not isinstance(result, KakaoStudyExportMutation)
            or result.result.study != request.command.study
            or result.result.export.source_binding_id != request.command.source_binding_id
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoStudyExportRequest):
        if not isinstance(result, KakaoStudyExport) or (
            result.export.source_binding_id,
            result.export.export_id,
        ) != (request.source_binding_id, request.export_id):
            raise ValueError(invalid)
    elif isinstance(request, ReadKakaoStudySelectionRequest):
        if not isinstance(result, KakaoStudyCreate) or any(
            getattr(result, key) != getattr(request, key)
            for key in ("source_binding_id", "packet_id", "packet_revision_id", "student_id")
        ):
            raise ValueError(invalid)
    elif isinstance(request, SaveKakaoPacketRequest):
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
