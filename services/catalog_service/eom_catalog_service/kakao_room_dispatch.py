"""Narrow adapter on the existing API-only Catalog socket; no new transport or IAM."""

from __future__ import annotations

from contextlib import suppress
from typing import cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_room_rpc import (
    KAKAO_ROOM_ERROR_CODES,
    KAKAO_ROOM_OPERATIONS,
    CommandKakaoRoomReply,
    CommandKakaoRoomRequest,
    KakaoRoomErrorCode,
    KakaoRoomFailure,
    KakaoRoomOperation,
    KakaoRoomReply,
    ListKakaoRoomsReply,
    ReadKakaoRoomReply,
    ReadKakaoRoomRequest,
    check_kakao_room_reply,
    parse_kakao_room_reply,
    parse_kakao_room_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_room_service import KakaoRoomService


def dispatch_kakao_room(service: KakaoRoomService | None, value: dict[str, object]) -> bytes:
    raw_operation = value.get("operation")
    if not isinstance(raw_operation, str) or raw_operation not in KAKAO_ROOM_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    operation = cast(KakaoRoomOperation, raw_operation)
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoRoomFailure:
        safe_code = code if code in KAKAO_ROOM_ERROR_CODES else "CATALOG_APPLICATION_INTERNAL_ERROR"
        return KakaoRoomFailure(
            operation=operation,
            request_id=request_id,
            error_code=cast(KakaoRoomErrorCode, safe_code),
        )

    reply: KakaoRoomReply
    try:
        request = parse_kakao_room_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        if service is None:
            reply = failure("CATALOG_APPLICATION_UNAVAILABLE")
        else:
            actor = ActorContext(
                actor_type=ActorType.OPERATOR,
                operator_id=request.actor_id,
                session_id=request.session_id,
                request_id=request.request_id,
                authentication_time=request.authentication_time,
                permissions=frozenset(),
                source=ActorSource.APPLICATION_API,
            )
            try:
                if isinstance(request, CommandKakaoRoomRequest):
                    reply = CommandKakaoRoomReply(
                        request_id=request.request_id,
                        result=service.command_room(
                            actor,
                            request.source_binding_id,
                            request.room_id,
                            request.command,
                            idempotency_key=request.idempotency_key,
                        ),
                    )
                elif isinstance(request, ReadKakaoRoomRequest):
                    reply = ReadKakaoRoomReply(
                        request_id=request.request_id,
                        result=service.get_room(
                            actor,
                            request.source_binding_id,
                            request.room_id,
                            mapping_revision_id=request.mapping_revision_id,
                        ),
                    )
                else:
                    reply = ListKakaoRoomsReply(
                        request_id=request.request_id,
                        result=service.list_rooms(
                            actor,
                            request.source_binding_id,
                            limit=request.limit,
                            cursor=request.cursor,
                        ),
                    )
                # Validate service results and correlation before returning any private projection.
                reply = parse_kakao_room_reply(reply.model_dump(mode="json"))
                check_kakao_room_reply(request, reply)
            except KakaoArchiveError as exc:
                reply = failure(exc.code)
            except (ValueError, SchemaError):
                reply = failure("KAKAO_ARCHIVE_RESULT_INVALID")
            except Exception:
                # Never include arbitrary exception text, source content or credentials.
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    encoded = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(encoded) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        encoded = (
            canonical_json_bytes(failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE").model_dump(mode="json"))
            + b"\n"
        )
    return encoded
