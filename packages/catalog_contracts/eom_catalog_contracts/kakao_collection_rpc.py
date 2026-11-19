"""Private Catalog API-peer protocol; no browser instructions or credentials."""

from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter

from .kakao_archive import KakaoBindingId
from .kakao_archive_binding import KakaoPolicyRevisionId
from .kakao_archive_rpc import IdempotencyKey, RequestId
from .kakao_capability import ConfirmKakaoCapability
from .kakao_collection import KakaoCollectionStatus, KakaoCollectionStatusView, KakaoRunId
from .models import FrozenModel, UtcDatetime
from .validation import validate_contract

type Operation = Literal[
    "START_KAKAO_ROOM_COLLECTION", "GET_KAKAO_ROOM_COLLECTION", "GET_KAKAO_ROOM_COLLECTION_VIEW"
]
type ErrorCode = Literal[
    "KAKAO_ARCHIVE_REQUEST_INVALID",
    "KAKAO_ARCHIVE_PERMISSION_DENIED",
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND",
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT",
    "KAKAO_ARCHIVE_PRECONDITION_FAILED",
    "KAKAO_ARCHIVE_BINDING_RETIRED",
    "KAKAO_ARCHIVE_ROOM_RETIRED",
    "KAKAO_ARCHIVE_COLLECTION_ALREADY_PENDING",
    "KAKAO_ARCHIVE_COLLECTION_CAPABILITY_MISMATCH",
    "KAKAO_ARCHIVE_CAPABILITY_EVIDENCE_INVALID",
    "CATALOG_APPLICATION_UNAVAILABLE",
    "CATALOG_APPLICATION_INTERNAL_ERROR",
]
KAKAO_COLLECTION_OPERATIONS = frozenset(get_args(Operation.__value__))
KAKAO_COLLECTION_ERRORS = frozenset(get_args(ErrorCode.__value__))


class _Identity(FrozenModel):
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^apisession_[0-9a-f]{32}$")
    request_id: RequestId
    authentication_time: UtcDatetime


class StartKakaoRoomCollectionRequest(_Identity):
    operation: Literal["START_KAKAO_ROOM_COLLECTION"] = "START_KAKAO_ROOM_COLLECTION"
    selection: ConfirmKakaoCapability
    expected_policy_revision_id: KakaoPolicyRevisionId
    idempotency_key: IdempotencyKey


class _CollectionIdentity(_Identity):
    source_binding_id: KakaoBindingId
    run_id: KakaoRunId


class GetKakaoRoomCollectionRequest(_CollectionIdentity):
    operation: Literal["GET_KAKAO_ROOM_COLLECTION"] = "GET_KAKAO_ROOM_COLLECTION"


class GetKakaoRoomCollectionViewRequest(_CollectionIdentity):
    operation: Literal["GET_KAKAO_ROOM_COLLECTION_VIEW"] = "GET_KAKAO_ROOM_COLLECTION_VIEW"


class KakaoRoomCollectionReply(FrozenModel):
    operation: Operation
    request_id: RequestId
    status: Literal["OK"] = "OK"
    result: KakaoCollectionStatus | KakaoCollectionStatusView
    error_code: None = None


class KakaoRoomCollectionFailure(FrozenModel):
    operation: Operation
    request_id: RequestId
    status: Literal["ERROR"] = "ERROR"
    result: None = None
    error_code: ErrorCode


type CollectionRequest = Annotated[
    StartKakaoRoomCollectionRequest
    | GetKakaoRoomCollectionRequest
    | GetKakaoRoomCollectionViewRequest,
    Field(discriminator="operation"),
]
type CollectionReply = Annotated[
    KakaoRoomCollectionReply | KakaoRoomCollectionFailure, Field(discriminator="status")
]
_REQUEST: TypeAdapter[CollectionRequest] = TypeAdapter(CollectionRequest)
_REPLY: TypeAdapter[CollectionReply] = TypeAdapter(CollectionReply)


def _wire_schema(value: dict[str, object]) -> str:
    if value.get("operation") == "GET_KAKAO_ROOM_COLLECTION_VIEW":
        return "catalog-kakao-collection-view-v1"
    return "catalog-kakao-collection-v1"


def parse_collection_request(value: dict[str, object]) -> CollectionRequest:
    validate_contract(_wire_schema(value), value)
    return _REQUEST.validate_python(value)


def parse_collection_reply(value: dict[str, object]) -> CollectionReply:
    validate_contract(_wire_schema(value), value)
    return _REPLY.validate_python(value)


def check_collection_reply(request: CollectionRequest, reply: CollectionReply) -> None:
    if (request.operation, request.request_id) != (reply.operation, reply.request_id):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    if isinstance(reply, KakaoRoomCollectionFailure):
        return
    result = reply.result
    if isinstance(request, GetKakaoRoomCollectionViewRequest) != isinstance(
        result, KakaoCollectionStatusView
    ):
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
    status = result.collection if isinstance(result, KakaoCollectionStatusView) else result
    if isinstance(request, StartKakaoRoomCollectionRequest):
        matches = status.source_binding_id == request.selection.source_binding_id
    else:
        matches = (status.source_binding_id, status.run_id) == (
            request.source_binding_id,
            request.run_id,
        )
    if not matches:
        raise ValueError("KAKAO_ARCHIVE_RESULT_INVALID")
