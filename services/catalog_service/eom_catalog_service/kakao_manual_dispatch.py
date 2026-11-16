"""Manual-session transport composition; runtime probes are never request data."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_manual import (
    KakaoManualFreshProfile,
    KakaoManualIntent,
    KakaoManualRenew,
    KakaoManualRuntimeObservation,
)
from eom_catalog_contracts.kakao_manual_rpc import (
    KAKAO_MANUAL_ERROR_CODES,
    KAKAO_MANUAL_OPERATIONS,
    CommandKakaoManualReply,
    CommandKakaoManualRequest,
    KakaoManualErrorCode,
    KakaoManualFailure,
    KakaoManualOperation,
    KakaoManualReply,
    ReadKakaoManualReply,
    StartKakaoManualReply,
    StartKakaoManualRequest,
    check_kakao_manual_reply,
    parse_kakao_manual_reply,
    parse_kakao_manual_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_manual_service import KakaoManualService


@dataclass(frozen=True, slots=True)
class KakaoManualApplication:
    service: KakaoManualService
    observe_profile: Callable[[], KakaoManualFreshProfile]
    observe_runtime: Callable[[KakaoManualIntent], KakaoManualRuntimeObservation]


def dispatch_kakao_manual(
    application: KakaoManualApplication | None, value: dict[str, object]
) -> bytes:
    raw_operation = value.get("operation")
    if not isinstance(raw_operation, str) or raw_operation not in KAKAO_MANUAL_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    operation = cast(KakaoManualOperation, raw_operation)
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoManualFailure:
        return KakaoManualFailure(
            operation=operation,
            request_id=request_id,
            error_code=cast(
                KakaoManualErrorCode,
                code if code in KAKAO_MANUAL_ERROR_CODES else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    reply: KakaoManualReply
    try:
        request = parse_kakao_manual_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        if application is None:
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
            service = application.service
            try:
                if isinstance(request, StartKakaoManualRequest):
                    reply = StartKakaoManualReply(
                        request_id=request.request_id,
                        result=service.start_session(
                            actor,
                            request.command,
                            idempotency_key=request.idempotency_key,
                            observe_profile=application.observe_profile,
                        ),
                    )
                elif isinstance(request, CommandKakaoManualRequest):
                    if isinstance(request.command, KakaoManualRenew):
                        result = service.renew_session(
                            actor,
                            request.lease_id,
                            request.command,
                            idempotency_key=request.idempotency_key,
                            observe_runtime=application.observe_runtime,
                        )
                    else:
                        result = service.end_session(
                            actor,
                            request.lease_id,
                            request.command,
                            idempotency_key=request.idempotency_key,
                        )
                    reply = CommandKakaoManualReply(request_id=request.request_id, result=result)
                else:
                    reply = ReadKakaoManualReply(
                        request_id=request.request_id,
                        result=service.get_session(actor, request.lease_id),
                    )
                reply = parse_kakao_manual_reply(reply.model_dump(mode="json"))
                check_kakao_manual_reply(request, reply)
            except KakaoArchiveError as error:
                reply = failure(error.code)
            except (ValueError, SchemaError):
                reply = failure("KAKAO_ARCHIVE_RESULT_INVALID")
            except Exception:
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(raw) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        raw = (
            canonical_json_bytes(failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE").model_dump(mode="json"))
            + b"\n"
        )
    return raw
