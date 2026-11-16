"""Narrow adapter on the existing API-only Catalog socket; no new transport or IAM."""

from __future__ import annotations

from contextlib import suppress
from typing import cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_student_rpc import (
    KAKAO_STUDENT_ERROR_CODES,
    KAKAO_STUDENT_OPERATIONS,
    CommandKakaoStudentReply,
    CommandKakaoStudentRequest,
    CreateKakaoStudentReply,
    CreateKakaoStudentRequest,
    KakaoStudentErrorCode,
    KakaoStudentFailure,
    KakaoStudentOperation,
    KakaoStudentReply,
    ListKakaoStudentsReply,
    ReadKakaoStudentReply,
    ReadKakaoStudentRequest,
    check_kakao_student_reply,
    parse_kakao_student_reply,
    parse_kakao_student_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_student_service import KakaoStudentService


def dispatch_kakao_student(service: KakaoStudentService | None, value: dict[str, object]) -> bytes:
    raw_operation = value.get("operation")
    if not isinstance(raw_operation, str) or raw_operation not in KAKAO_STUDENT_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    operation = cast(KakaoStudentOperation, raw_operation)
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoStudentFailure:
        safe_code = (
            code if code in KAKAO_STUDENT_ERROR_CODES else "CATALOG_APPLICATION_INTERNAL_ERROR"
        )
        return KakaoStudentFailure(
            operation=operation,
            request_id=request_id,
            error_code=cast(KakaoStudentErrorCode, safe_code),
        )

    reply: KakaoStudentReply
    try:
        request = parse_kakao_student_request(value)
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
                if isinstance(request, CreateKakaoStudentRequest):
                    reply = CreateKakaoStudentReply(
                        request_id=request.request_id,
                        result=service.create_student(
                            actor, request.command, idempotency_key=request.idempotency_key
                        ),
                    )
                elif isinstance(request, CommandKakaoStudentRequest):
                    reply = CommandKakaoStudentReply(
                        request_id=request.request_id,
                        result=service.command_student(
                            actor,
                            request.student_id,
                            request.command,
                            idempotency_key=request.idempotency_key,
                        ),
                    )
                elif isinstance(request, ReadKakaoStudentRequest):
                    reply = ReadKakaoStudentReply(
                        request_id=request.request_id,
                        result=service.get_student(
                            actor,
                            request.student_id,
                            display_revision_id=request.display_revision_id,
                        ),
                    )
                else:
                    reply = ListKakaoStudentsReply(
                        request_id=request.request_id,
                        result=service.list_students(
                            actor, limit=request.limit, cursor=request.cursor
                        ),
                    )
                # Validate service results and correlation before returning any private projection.
                reply = parse_kakao_student_reply(reply.model_dump(mode="json"))
                check_kakao_student_reply(request, reply)
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
