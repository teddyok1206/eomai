"""API-only local input selection; not a collector or browser-control transport."""

from contextlib import suppress
from typing import TYPE_CHECKING, cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_capture_intake import KakaoPhotoCheckResult
from eom_catalog_contracts.kakao_capture_rpc import (
    KAKAO_CAPTURE_ERROR_CODES,
    KAKAO_CAPTURE_OPERATIONS,
    CheckKakaoPhotoReply,
    CheckKakaoPhotoRequest,
    ConfirmKakaoCaptureReply,
    ConfirmKakaoCaptureRequest,
    KakaoCaptureErrorCode,
    KakaoCaptureFailure,
    KakaoCaptureOperation,
    KakaoCaptureReply,
    KakaoCaptureRequest,
    ListKakaoCapturesReply,
    check_kakao_capture_reply,
    parse_kakao_capture_reply,
    parse_kakao_capture_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError

if TYPE_CHECKING:
    from .kakao_capture_intake_service import KakaoCaptureIntakeService


def dispatch_kakao_capture(
    service: "KakaoCaptureIntakeService | None", value: dict[str, object]
) -> bytes:
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in KAKAO_CAPTURE_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoCaptureFailure:
        return KakaoCaptureFailure(
            operation=cast(KakaoCaptureOperation, operation),
            request_id=request_id,
            error_code=cast(
                KakaoCaptureErrorCode,
                code if code in KAKAO_CAPTURE_ERROR_CODES else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    reply: KakaoCaptureReply
    try:
        request = parse_kakao_capture_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        try:
            reply = _dispatch_request(service, request)
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


def _dispatch_request(
    service: "KakaoCaptureIntakeService | None", request: KakaoCaptureRequest
) -> KakaoCaptureReply:
    reply: KakaoCaptureReply
    if service is None:
        return KakaoCaptureFailure(
            operation=request.operation,
            request_id=request.request_id,
            error_code="CATALOG_APPLICATION_UNAVAILABLE",
        )
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
        if isinstance(request, ConfirmKakaoCaptureRequest):
            reply = ConfirmKakaoCaptureReply(
                request_id=request.request_id,
                result=service.confirm_capture(
                    actor, request.command, idempotency_key=request.idempotency_key
                ),
            )
        elif isinstance(request, CheckKakaoPhotoRequest):
            selection = request.selection
            photo = service.inspect_photo_occurrence(
                actor,
                source_binding_id=selection.source_binding_id,
                manual_lease_id=selection.manual_lease_id,
                csv_capture_id=selection.csv_capture_id,
                photo_capture_id=selection.photo_capture_id,
            )
            reply = CheckKakaoPhotoReply(
                request_id=request.request_id,
                result=KakaoPhotoCheckResult(
                    selection=selection, row_ordinal=None if photo is None else photo.row_ordinal
                ),
            )
        else:
            reply = ListKakaoCapturesReply(
                request_id=request.request_id,
                result=service.list_captures(actor, request.source_binding_id),
            )
        reply = parse_kakao_capture_reply(reply.model_dump(mode="json"))
        check_kakao_capture_reply(request, reply)
    return reply
