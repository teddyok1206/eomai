"""API-peer only recommendation RPC over the existing task/Workflow owners."""

from contextlib import suppress
from typing import BinaryIO, cast

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.kakao_archive_rpc import RequestId
from eom_catalog_contracts.kakao_concept_rpc import (
    CONCEPT_ERRORS,
    CONCEPT_OPERATIONS,
    ConceptError,
    ConceptFailure,
    ConceptOperation,
    ConceptPageView,
    ConceptReply,
    ConceptResult,
    ConceptStarted,
    ConceptSuccess,
    ListConceptsRequest,
    ReadConceptPageRequest,
    ReadConceptRequest,
    StartConceptRequest,
    check_concept_reply,
    parse_concept_reply,
    parse_concept_request,
)
from eom_kakao_archive_contracts import canonical_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter

from .artifacts import VerifiedArtifactMemberStream
from .kakao_archive_authorization import KakaoArchiveError
from .kakao_concept_reads import (
    concept_summary,
    list_kakao_concepts,
    open_kakao_concept_page,
    read_kakao_concept,
)
from .kakao_concept_workflow_submission import start_kakao_concept_task
from .kakao_question_composition import KakaoQuestionApplication


def dispatch_kakao_concept(
    application: KakaoQuestionApplication | None,
    value: dict[str, object],
    output: BinaryIO,
) -> None:
    operation = value.get("operation")
    if not isinstance(operation, str) or operation not in CONCEPT_OPERATIONS:
        raise ValueError("KAKAO_ARCHIVE_REQUEST_INVALID")
    request_id = "invalid-request"
    with suppress(ValueError):
        request_id = TypeAdapter(RequestId).validate_python(value.get("request_id"))

    def failure(code: str) -> ConceptFailure:
        return ConceptFailure(
            operation=cast(ConceptOperation, operation),
            request_id=request_id,
            error_code=cast(
                ConceptError,
                code if code in CONCEPT_ERRORS else "CATALOG_APPLICATION_INTERNAL_ERROR",
            ),
        )

    opened: VerifiedArtifactMemberStream | None = None
    reply: ConceptReply
    try:
        request = parse_concept_request(value)
        if application is None or application.concepts is None:
            raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
        service = application.concepts
        actor = ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=request.actor_id,
            session_id=request.session_id,
            request_id=request.request_id,
            authentication_time=request.authentication_time,
            permissions=frozenset(),
            source=ActorSource.APPLICATION_API,
        )
        result: ConceptResult
        if isinstance(request, StartConceptRequest):
            # Do not accept work that cannot automatically continue after this HTTP request.
            if application.concept_coordinator is None:
                raise KakaoArchiveError("KAKAO_CONCEPT_RUNTIME_UNAVAILABLE")
            mutation, _ = start_kakao_concept_task(
                service,
                actor=actor,
                command=request.command,
                idempotency_key=request.idempotency_key,
            )
            result = ConceptStarted(task=concept_summary(mutation.task), replayed=mutation.replayed)
        elif isinstance(request, ReadConceptRequest):
            result = read_kakao_concept(service, actor, request.source_binding_id, request.task_id)
        elif isinstance(request, ListConceptsRequest):
            result = list_kakao_concepts(
                service,
                actor,
                request.source_binding_id,
                limit=request.limit,
                cursor=request.cursor,
            )
        else:
            assert isinstance(request, ReadConceptPageRequest)
            opened = open_kakao_concept_page(
                service, actor, request.source_binding_id, request.task_id, request.page_key
            )
            result = ConceptPageView(
                source_binding_id=request.source_binding_id,
                task_id=request.task_id,
                page_key=request.page_key,
                content_length=opened.content_length,
                sha256=opened.sha256,
            )
        reply = parse_concept_reply(
            ConceptSuccess(
                operation=request.operation, request_id=request_id, result=result
            ).model_dump(mode="json")
        )
        check_concept_reply(request, reply)
    except KakaoArchiveError as error:
        reply = failure(error.code)
    except (ValueError, SchemaError):
        reply = failure("KAKAO_ARCHIVE_REQUEST_INVALID")
    except Exception:
        reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    raw = canonical_bytes(reply.model_dump(mode="json")) + b"\n"
    if len(raw) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        reply = failure("KAKAO_ARCHIVE_RESULT_TOO_LARGE")
        raw = canonical_bytes(reply.model_dump(mode="json")) + b"\n"
    try:
        output.write(raw)
        if opened is not None and reply.status == "OK":
            for chunk in opened.iter_chunks():
                output.write(chunk)
        output.flush()
    finally:
        if opened is not None:
            opened.stream.close()
