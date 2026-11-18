"""Accept one durable collection intent or observe status without executing work."""

from contextlib import suppress
from typing import cast

from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_collection_rpc import (
    KAKAO_COLLECTION_ERRORS,
    KAKAO_COLLECTION_OPERATIONS,
    CollectionReply,
    ErrorCode,
    KakaoRoomCollectionFailure,
    KakaoRoomCollectionReply,
    Operation,
    StartKakaoRoomCollectionRequest,
    check_collection_reply,
    parse_collection_reply,
    parse_collection_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_collection_service import KakaoCollectionService


def dispatch_kakao_collection(
    service: KakaoCollectionService | None, value: dict[str, object]
) -> bytes:
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in KAKAO_COLLECTION_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoRoomCollectionFailure:
        return KakaoRoomCollectionFailure(
            operation=cast(Operation, operation),
            request_id=request_id,
            error_code=cast(
                ErrorCode,
                code if code in KAKAO_COLLECTION_ERRORS else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    reply: CollectionReply
    try:
        request = parse_collection_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        try:
            if service is None:
                return (
                    canonical_json_bytes(
                        failure("CATALOG_APPLICATION_UNAVAILABLE").model_dump(mode="json")
                    )
                    + b"\n"
                )
            actor = ActorContext(
                actor_type=ActorType.OPERATOR,
                operator_id=request.actor_id,
                session_id=request.session_id,
                request_id=request.request_id,
                authentication_time=request.authentication_time,
                permissions=frozenset(),
                source=ActorSource.APPLICATION_API,
            )
            if isinstance(request, StartKakaoRoomCollectionRequest):
                result = service.start_registered_room(
                    actor,
                    request.selection,
                    expected_policy_revision_id=request.expected_policy_revision_id,
                    idempotency_key=request.idempotency_key,
                )
            else:
                result = service.get_status(actor, request.source_binding_id, request.run_id)
            reply = KakaoRoomCollectionReply(
                operation=request.operation,
                request_id=request_id,
                result=result,
            )
            reply = parse_collection_reply(reply.model_dump(mode="json"))
            check_collection_reply(request, reply)
        except KakaoArchiveError as error:
            reply = failure(error.code)
        except Exception:
            reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    return canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
