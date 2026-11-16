"""Existing API-peer transport for question owners, never an admission bypass."""

from contextlib import suppress
from typing import BinaryIO, cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_question_rpc import (
    KAKAO_QUESTION_ERROR_CODES,
    KAKAO_QUESTION_OPERATIONS,
    ChangeKakaoQuestionReply,
    ChangeKakaoQuestionRequest,
    CreateKakaoQuestionReply,
    CreateKakaoQuestionRequest,
    KakaoQuestionErrorCode,
    KakaoQuestionFailure,
    KakaoQuestionOperation,
    KakaoQuestionReply,
    ListKakaoQuestionsReply,
    ListKakaoQuestionsRequest,
    ReadKakaoQuestionImageReply,
    ReadKakaoQuestionImageRequest,
    ReadKakaoQuestionReply,
    check_kakao_question_reply,
    parse_kakao_question_reply,
    parse_kakao_question_request,
)
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .kakao_archive_authorization import KakaoArchiveError
from .kakao_question_reads import KakaoOpenedQuestionImage, KakaoQuestionReads
from .kakao_question_service import KakaoQuestionService


def dispatch_kakao_question(
    questions: KakaoQuestionService | None,
    reads: KakaoQuestionReads | None,
    value: dict[str, object],
    output: BinaryIO,
) -> None:
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in KAKAO_QUESTION_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> KakaoQuestionFailure:
        return KakaoQuestionFailure(
            operation=cast(KakaoQuestionOperation, operation),
            request_id=request_id,
            error_code=cast(
                KakaoQuestionErrorCode,
                code
                if code in KAKAO_QUESTION_ERROR_CODES
                else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    image: KakaoOpenedQuestionImage | None = None
    reply: KakaoQuestionReply
    try:
        request = parse_kakao_question_request(value)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    else:
        if questions is None or reads is None:
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
                if isinstance(request, CreateKakaoQuestionRequest):
                    reply = CreateKakaoQuestionReply(
                        request_id=request_id,
                        result=questions.create_question(
                            actor, request.command, idempotency_key=request.idempotency_key
                        ),
                    )
                elif isinstance(request, ChangeKakaoQuestionRequest):
                    reply = ChangeKakaoQuestionReply(
                        request_id=request_id,
                        result=questions.change_question(
                            actor, request.command, idempotency_key=request.idempotency_key
                        ),
                    )
                elif isinstance(request, ListKakaoQuestionsRequest):
                    reply = ListKakaoQuestionsReply(
                        request_id=request_id,
                        result=questions.list_questions(
                            actor,
                            request.source_binding_id,
                            room_id=request.room_id,
                            limit=request.limit,
                            cursor=request.cursor,
                        ),
                    )
                elif isinstance(request, ReadKakaoQuestionImageRequest):
                    image = reads.open_image(
                        actor,
                        request.source_binding_id,
                        request.room_id,
                        request.question_id,
                        request.question_revision_id,
                        request.attachment_id,
                    )
                    reply = ReadKakaoQuestionImageReply(
                        request_id=request_id, result=image.descriptor
                    )
                else:
                    reply = ReadKakaoQuestionReply(
                        request_id=request_id,
                        result=reads.read_question(
                            actor,
                            request.source_binding_id,
                            request.room_id,
                            request.question_id,
                            request.question_revision_id,
                        ),
                    )
                reply = parse_kakao_question_reply(reply.model_dump(mode="json"))
                check_kakao_question_reply(request, reply)
            except KakaoArchiveError as error:
                reply = failure(error.code)
            except (ValueError, SchemaError):
                reply = failure("KAKAO_ARCHIVE_RESULT_INVALID")
            except Exception:
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(raw) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        reply = failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE")
        raw = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    try:
        output.write(raw)
        if image is not None and reply.status == "OK":
            for chunk in image.member.iter_chunks():
                output.write(chunk)
        output.flush()
    finally:
        if image is not None:
            image.member.stream.close()
