"""Current-authorized question read/review routes, never raw source admission."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_questions import (
    KakaoQuestionComposition,
    KakaoQuestionCompositionResult,
    KakaoQuestionCreate,
    KakaoQuestionEditContext,
    KakaoQuestionMutation,
    KakaoQuestionPage,
    KakaoQuestionReview,
    KakaoQuestionView,
)
from eom_catalog_contracts.kakao_question_store import KakaoQuestionChange
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/questions", tags=["kakao-archive"])
QuestionId = Annotated[str, Path(pattern=r"^kakaoquestion_[0-9a-f]{32}$")]
RevisionId = Annotated[str, Path(pattern=r"^kakaoquestionrev_[0-9a-f]{32}$")]
BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
RoomId = Annotated[str, Query(pattern=r"^kakaoroom_[0-9a-f]{32}$")]
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
EDIT = require_permission(PermissionKey.KAKAO_ARCHIVE_EDIT)
_ERROR_STATUS = {
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_ROOM_RETIRED": 409,
    "KAKAO_ARCHIVE_STUDENT_RETIRED": 409,
    "KAKAO_ARCHIVE_CANDIDATE_ALREADY_REGISTERED": 409,
    "KAKAO_ARCHIVE_CANDIDATE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_IMAGE_UNAVAILABLE": 409,
    "KAKAO_ARCHIVE_COMPOSITION_SCOPE_INVALID": 422,
    "KAKAO_ARCHIVE_QUESTION_SELECTION_INVALID": 422,
    "KAKAO_ARCHIVE_QUESTION_EDIT_INVALID": 422,
}


@contextmanager
def _boundary() -> Iterator[None]:
    try:
        yield
    except CatalogApplicationClientError as error:
        code = error.code if error.code in _ERROR_STATUS else "KAKAO_ARCHIVE_UNAVAILABLE"
        raise ApiError(
            _ERROR_STATUS.get(code, 503),
            code,
            "KakaoTalk request failed",
            "The private question operation could not be completed.",
        ) from error


@router.post(
    "/compose",
    operation_id="kakao_question_compose",
    response_model=SingleResponse[KakaoQuestionCompositionResult],
    dependencies=[Depends(EDIT)],
)
def compose_questions(
    request: Request,
    response: Response,
    body: KakaoQuestionComposition,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoQuestionCompositionResult]:
    # Each input carries its own expected revision/version; a single If-Match cannot
    # describe a merge. The owner applies their CAS together in one transaction.
    with _boundary():
        result = request.app.state.services.catalog_application.compose_kakao_questions(
            body, actor=request.state.request_context.actor(), idempotency_key=idempotency_key
        )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "",
    operation_id="kakao_question_list",
    response_model=SingleResponse[KakaoQuestionPage],
    dependencies=[Depends(READ)],
)
def list_questions(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaoquestion_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoQuestionPage]:
    with _boundary():
        result = request.app.state.services.catalog_application.list_kakao_questions(
            source_binding_id,
            actor=request.state.request_context.actor(),
            room_id=room_id,
            limit=limit,
            cursor=cursor,
        )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.post(
    "",
    operation_id="kakao_question_create",
    status_code=201,
    response_model=SingleResponse[KakaoQuestionMutation],
    dependencies=[Depends(EDIT)],
)
def create_question(
    request: Request,
    response: Response,
    body: KakaoQuestionCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoQuestionMutation]:
    with _boundary():
        result = request.app.state.services.catalog_application.create_kakao_question(
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(result.question.resource_version)
    return one(request, result)


@router.get(
    "/{question_id}/revisions/{revision_id}",
    operation_id="kakao_question_read",
    response_model=SingleResponse[KakaoQuestionView],
    dependencies=[Depends(READ)],
)
def read_question(
    request: Request,
    response: Response,
    question_id: QuestionId,
    revision_id: RevisionId,
    source_binding_id: BindingId,
    authentication: Auth,
    room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoQuestionView]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_question(
            source_binding_id,
            room_id,
            question_id,
            revision_id,
            actor=request.state.request_context.actor(),
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(result.question.resource_version)
    return one(request, result)


@router.get(
    "/{question_id}/revisions/{revision_id}/edit-context",
    operation_id="kakao_question_edit_context",
    response_model=SingleResponse[KakaoQuestionEditContext],
    dependencies=[Depends(EDIT)],
)
def read_edit_context(
    request: Request,
    response: Response,
    question_id: QuestionId,
    revision_id: RevisionId,
    source_binding_id: BindingId,
    authentication: Auth,
    room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoQuestionEditContext]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_question_edit_context(
            source_binding_id,
            room_id,
            question_id,
            revision_id,
            actor=request.state.request_context.actor(),
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(result.resource_version)
    return one(request, result)


@router.post(
    "/{question_id}/review",
    operation_id="kakao_question_review",
    response_model=SingleResponse[KakaoQuestionMutation],
    dependencies=[Depends(EDIT)],
)
def review_question(
    request: Request,
    response: Response,
    question_id: QuestionId,
    source_binding_id: BindingId,
    room_id: RoomId,
    body: KakaoQuestionReview,
    authentication: Auth,
    expected: ExpectedVersion,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoQuestionMutation]:
    command = KakaoQuestionChange(
        source_binding_id=source_binding_id,
        room_id=room_id,
        question_id=question_id,
        expected_resource_version=expected,
        edit=body,
    )
    with _boundary():
        result = request.app.state.services.catalog_application.change_kakao_question(
            command,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(result.question.resource_version)
    return one(request, result)


@router.get(
    "/{question_id}/revisions/{revision_id}/images/{attachment_id}",
    operation_id="kakao_question_image",
    response_class=StreamingResponse,
    dependencies=[Depends(READ)],
)
def read_image(
    request: Request,
    question_id: QuestionId,
    revision_id: RevisionId,
    attachment_id: Annotated[str, Path(pattern=r"^kakaoattachment_[0-9a-f]{32}$")],
    source_binding_id: BindingId,
    authentication: Auth,
    room_id: str | None = Query(default=None, pattern=r"^kakaoroom_[0-9a-f]{32}$"),
) -> StreamingResponse:
    with _boundary():
        result = request.app.state.services.catalog_application.download_kakao_question_image(
            source_binding_id,
            room_id,
            question_id,
            revision_id,
            attachment_id,
            actor=request.state.request_context.actor(),
        )
    return StreamingResponse(
        result.iter_chunks(),
        media_type=result.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(result.content_length),
            "Content-Disposition": "inline",
            "ETag": '"' + result.sha256 + '"',
        },
    )
