"""Existing API-peer socket to the question composition owner, without collection authority."""

from contextlib import suppress
from typing import cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_question_compose_rpc import (
    KAKAO_COMPOSE_ERRORS,
    ComposeKakaoQuestionsReply,
    KakaoComposeError,
    KakaoComposeFailure,
    KakaoComposeReply,
    check_kakao_compose_reply,
    parse_kakao_compose_reply,
    parse_kakao_compose_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_question_compose_service import KakaoQuestionComposeService


def dispatch_kakao_compose(
    composer: KakaoQuestionComposeService | None, value: dict[str, object]
) -> bytes:
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoComposeFailure:
        return KakaoComposeFailure(
            request_id=request_id,
            error_code=cast(
                KakaoComposeError,
                code if code in KAKAO_COMPOSE_ERRORS else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    reply: KakaoComposeReply
    try:
        request = parse_kakao_compose_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        if composer is None:
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
                result = composer.compose_questions(
                    actor, request.command, idempotency_key=request.idempotency_key
                )
            except KakaoArchiveError as error:
                reply = failure(error.code)
            except (ValueError, SchemaError):
                reply = failure("KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID")
            except Exception:
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
            else:
                try:
                    reply = parse_kakao_compose_reply(
                        ComposeKakaoQuestionsReply(request_id=request_id, result=result).model_dump(
                            mode="json"
                        )
                    )
                    check_kakao_compose_reply(request, reply)
                except (ValueError, SchemaError):
                    reply = failure("KAKAO_ARCHIVE_RESULT_INVALID")
    raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(raw) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        raw = (
            canonical_json_bytes(failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE").model_dump(mode="json"))
            + b"\n"
        )
    return raw
