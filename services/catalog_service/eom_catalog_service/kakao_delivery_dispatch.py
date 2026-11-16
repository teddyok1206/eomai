"""Existing API-peer wire adapter; PDF bytes follow a verified exact descriptor."""

from contextlib import suppress
from typing import BinaryIO, cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_delivery_rpc import (
    KAKAO_DELIVERY_ERRORS,
    KAKAO_DELIVERY_OPERATIONS,
    CreateKakaoExportRequest,
    KakaoDeliveryError,
    KakaoDeliveryFailure,
    KakaoDeliveryOperation,
    KakaoDeliveryReply,
    KakaoDeliveryResult,
    KakaoDeliverySuccess,
    KakaoExportPdf,
    ListKakaoExportsRequest,
    ListKakaoPacketsRequest,
    ReadKakaoExportRequest,
    ReadKakaoPacketRequest,
    SaveKakaoPacketRequest,
    check_kakao_delivery_reply,
    parse_kakao_delivery_reply,
    parse_kakao_delivery_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter, ValidationError

from .artifacts import VerifiedArtifactMemberStream
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_delivery_application import KakaoDeliveryApplication


def dispatch_kakao_delivery(
    application: KakaoDeliveryApplication | None, value: dict[str, object], output: BinaryIO
) -> None:
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in KAKAO_DELIVERY_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoDeliveryFailure:
        return KakaoDeliveryFailure(
            operation=cast(KakaoDeliveryOperation, operation),
            request_id=request_id,
            error_code=cast(
                KakaoDeliveryError,
                code if code in KAKAO_DELIVERY_ERRORS else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    opened: VerifiedArtifactMemberStream | None = None
    reply: KakaoDeliveryReply
    try:
        request = parse_kakao_delivery_request(value)
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
            try:
                result: KakaoDeliveryResult
                if isinstance(request, SaveKakaoPacketRequest):
                    result = application.packets.save_packet(
                        actor, request.command, idempotency_key=request.idempotency_key
                    )
                elif isinstance(request, ReadKakaoPacketRequest):
                    result = application.read_packet(
                        actor,
                        request.source_binding_id,
                        request.packet_id,
                        request.packet_revision_id,
                    )
                elif isinstance(request, ListKakaoPacketsRequest):
                    result = application.packets.list_packets(
                        actor, request.source_binding_id, limit=request.limit, cursor=request.cursor
                    )
                elif isinstance(request, CreateKakaoExportRequest):
                    result = application.request_export(
                        actor, request.command, idempotency_key=request.idempotency_key
                    )
                elif isinstance(request, ListKakaoExportsRequest):
                    result = application.export_owner().list_exports(
                        actor, request.source_binding_id, limit=request.limit, cursor=request.cursor
                    )
                elif isinstance(request, ReadKakaoExportRequest):
                    result = application.export_owner().get_export(
                        actor, request.source_binding_id, request.export_id
                    )
                else:
                    opened = application.export_owner().open_pdf(
                        actor,
                        request.source_binding_id,
                        request.export_id,
                        revision_id=request.export_revision_id,
                    )
                    result = KakaoExportPdf(
                        source_binding_id=request.source_binding_id,
                        export_id=request.export_id,
                        export_revision_id=request.export_revision_id,
                        content_length=opened.content_length,
                        sha256=opened.sha256,
                    )
                reply = KakaoDeliverySuccess(
                    operation=request.operation, request_id=request_id, result=result
                )
                reply = parse_kakao_delivery_reply(reply.model_dump(mode="json"))
                check_kakao_delivery_reply(request, reply)
            except KakaoArchiveError as error:
                reply = failure(error.code)
            except (ValueError, SchemaError) as error:
                code = str(error)
                # Domain model validators own these rules. Only a single root rule
                # rejection becomes a public code; never expose validation input/text.
                if isinstance(error, ValidationError):
                    issues = error.errors(include_input=False, include_url=False)
                    if len(issues) == 1 and issues[0]["loc"] == ():
                        cause = issues[0].get("ctx", {}).get("error")
                        if isinstance(cause, ValueError):
                            code = str(cause)
                reply = failure(
                    code if code in KAKAO_DELIVERY_ERRORS else "KAKAO_ARCHIVE_RESULT_INVALID"
                )
            except Exception:
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(raw) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        reply = failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE")
        raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    try:
        output.write(raw)
        if opened is not None and reply.status == "OK":
            for chunk in opened.iter_chunks():
                output.write(chunk)
        output.flush()
    finally:
        if opened is not None:
            opened.stream.close()
