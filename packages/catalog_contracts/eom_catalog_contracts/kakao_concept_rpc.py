"""Closed recommendation transport; no worker input, slot or caller source authority."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter, model_validator

from .kakao_archive import KakaoBindingId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_concept_tasks import ConceptTaskId, KakaoConceptCreate
from .kakao_question import QuestionId, QuestionRevisionId
from .models import FrozenModel, Sha256, UtcDatetime
from .validation import validate_contract

type ConceptOperation = Literal[
    "START_KAKAO_CONCEPT", "READ_KAKAO_CONCEPT", "LIST_KAKAO_CONCEPTS", "READ_KAKAO_CONCEPT_PAGE"
]
CONCEPT_OPERATIONS = frozenset(get_args(ConceptOperation.__value__))
type ConceptError = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_RESULT_INVALID",
    "KAKAO_ARCHIVE_RESULT_TOO_LARGE",
    "KAKAO_CONCEPT_RUNTIME_UNAVAILABLE",
    "KAKAO_CONCEPT_RESULT_NOT_READY",
    "KAKAO_CONCEPT_RESULT_POINTER_INVALID",
    "KAKAO_CONCEPT_KNOWLEDGE_NOT_CONFIGURED",
    "KAKAO_CONCEPT_PAGE_POINTER_INVALID",
    "CONTROL_PRESET_POINTER_STALE",
    "CONTROL_PRESET_NOT_PUBLISHED",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
CONCEPT_ERRORS = frozenset(get_args(ConceptError.__value__))
PageKey = Annotated[str, Field(pattern=r"^E[1-3]P[1-9][0-9]{0,4}$")]


class ConceptSummary(FrozenModel):
    task_id: ConceptTaskId
    source_binding_id: KakaoBindingId
    question_id: QuestionId
    question_revision_id: QuestionRevisionId
    created_at: UtcDatetime


class ConceptCitationView(FrozenModel):
    title: str = Field(min_length=1, max_length=256)
    location: str = Field(min_length=1, max_length=256)
    kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE", "ORIGINAL_PASSAGE"]
    quote: str | None = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def quote_kind(self) -> "ConceptCitationView":
        if (self.kind == "ORIGINAL_PASSAGE") != (self.quote is not None):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class ConceptRectangleView(FrozenModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_page(self) -> "ConceptRectangleView":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class ConceptCaptureView(FrozenModel):
    page_key: PageKey
    physical_page: int = Field(strict=True, ge=1, le=100000)
    rectangle: ConceptRectangleView
    reason: str = Field(min_length=1, max_length=500)
    source_title: str = Field(min_length=1, max_length=256)


class ConceptBlockView(FrozenModel):
    title: str = Field(min_length=1, max_length=128)
    relevance: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=8000)
    citations: tuple[ConceptCitationView, ...] = Field(min_length=1, max_length=6)
    captures: tuple[ConceptCaptureView, ...] = Field(max_length=4)


class ConceptView(FrozenModel):
    schema_version: Literal["kakao-concept-view/1.0"] = "kakao-concept-view/1.0"
    task: ConceptSummary
    state: Literal[
        "PREPARING",
        "PLAN_PENDING",
        "PLAN_RUNNING",
        "SEARCHING",
        "COMPOSE_PENDING",
        "COMPOSE_RUNNING",
        "COMPLETED",
        "NEEDS_INPUT",
        "FAILED",
        "CANCELLED",
    ]
    result_sha256: Sha256 | None = None
    focus_summary: str = Field(default="", max_length=1000)
    blocks: tuple[ConceptBlockView, ...] = Field(default=(), max_length=6)
    staff_checks: tuple[Annotated[str, Field(min_length=1, max_length=2200)], ...] = Field(
        default=(), max_length=6
    )
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = Field(
        default=(), max_length=24
    )

    @model_validator(mode="after")
    def completed_pin(self) -> "ConceptView":
        if self.blocks and (self.state != "COMPLETED" or self.result_sha256 is None):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        if (self.state in {"COMPLETED", "NEEDS_INPUT"}) != (self.result_sha256 is not None):
            raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
        return self


class ConceptStarted(FrozenModel):
    schema_version: Literal["kakao-concept-started/1.0"] = "kakao-concept-started/1.0"
    task: ConceptSummary
    replayed: bool = Field(strict=True)


class ConceptHistory(FrozenModel):
    schema_version: Literal["kakao-concept-history/1.0"] = "kakao-concept-history/1.0"
    items: tuple[ConceptSummary, ...] = Field(max_length=100)
    next_cursor: ConceptTaskId | None


class ConceptPageView(FrozenModel):
    schema_version: Literal["kakao-concept-page/1.0"] = "kakao-concept-page/1.0"
    source_binding_id: KakaoBindingId
    task_id: ConceptTaskId
    page_key: PageKey
    media_type: Literal["image/png"] = "image/png"
    content_length: int = Field(strict=True, ge=1, le=16 * 1024 * 1024)
    sha256: Sha256


class _Identity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class StartConceptRequest(_Identity):
    operation: Literal["START_KAKAO_CONCEPT"] = "START_KAKAO_CONCEPT"
    command: KakaoConceptCreate
    idempotency_key: IdempotencyKey


class ReadConceptRequest(_Identity):
    operation: Literal["READ_KAKAO_CONCEPT"] = "READ_KAKAO_CONCEPT"
    source_binding_id: KakaoBindingId
    task_id: ConceptTaskId


class ListConceptsRequest(_Identity):
    operation: Literal["LIST_KAKAO_CONCEPTS"] = "LIST_KAKAO_CONCEPTS"
    source_binding_id: KakaoBindingId
    limit: int = Field(default=50, strict=True, ge=1, le=100)
    cursor: ConceptTaskId | None = None


class ReadConceptPageRequest(_Identity):
    operation: Literal["READ_KAKAO_CONCEPT_PAGE"] = "READ_KAKAO_CONCEPT_PAGE"
    source_binding_id: KakaoBindingId
    task_id: ConceptTaskId
    page_key: PageKey


type ConceptRequest = Annotated[
    StartConceptRequest | ReadConceptRequest | ListConceptsRequest | ReadConceptPageRequest,
    Field(discriminator="operation"),
]
type ConceptResult = Annotated[
    ConceptStarted | ConceptView | ConceptHistory | ConceptPageView,
    Field(discriminator="schema_version"),
]


class ConceptSuccess(FrozenModel):
    operation: ConceptOperation
    request_id: RequestId
    status: Literal["OK"] = "OK"
    result: ConceptResult
    error_code: None = None


class ConceptFailure(FrozenModel):
    operation: ConceptOperation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: ConceptError


type ConceptReply = Annotated[ConceptSuccess | ConceptFailure, Field(discriminator="status")]
_REQUEST: TypeAdapter[ConceptRequest] = TypeAdapter(ConceptRequest)
_REPLY: TypeAdapter[ConceptReply] = TypeAdapter(ConceptReply)


def parse_concept_request(value: dict[str, object]) -> ConceptRequest:
    validate_contract("catalog-kakao-concept-v1", value)
    return _REQUEST.validate_python(value)


def parse_concept_reply(value: dict[str, object]) -> ConceptReply:
    validate_contract("catalog-kakao-concept-v1", value)
    return _REPLY.validate_python(value)


def check_concept_reply(request: ConceptRequest, reply: ConceptReply) -> None:
    invalid = "KAKAO_ARCHIVE_RESULT_INVALID"
    if (reply.operation, reply.request_id) != (request.operation, request.request_id):
        raise ValueError(invalid)
    if isinstance(reply, ConceptFailure):
        return
    result = reply.result
    if isinstance(request, StartConceptRequest):
        if not isinstance(result, ConceptStarted) or any(
            getattr(result.task, key) != getattr(request.command, key)
            for key in ("source_binding_id", "question_id", "question_revision_id")
        ):
            raise ValueError(invalid)
    elif isinstance(request, ReadConceptRequest):
        if not isinstance(result, ConceptView) or (
            result.task.source_binding_id,
            result.task.task_id,
        ) != (request.source_binding_id, request.task_id):
            raise ValueError(invalid)
    elif isinstance(request, ListConceptsRequest):
        if not isinstance(result, ConceptHistory):
            raise ValueError(invalid)
        ids = tuple(row.task_id for row in result.items)
        if (
            len(ids) > request.limit
            or ids != tuple(sorted(set(ids)))
            or any(
                row.source_binding_id != request.source_binding_id
                or (request.cursor is not None and row.task_id <= request.cursor)
                for row in result.items
            )
            or (
                result.next_cursor is not None
                and (len(ids) != request.limit or result.next_cursor != ids[-1])
            )
        ):
            raise ValueError(invalid)
    elif not isinstance(result, ConceptPageView) or (
        result.source_binding_id,
        result.task_id,
        result.page_key,
    ) != (request.source_binding_id, request.task_id, request.page_key):
        raise ValueError(invalid)
