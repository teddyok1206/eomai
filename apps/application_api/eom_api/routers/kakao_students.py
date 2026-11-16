"""Private KakaoTalk student HTTP transport; Catalog owns state and replay."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_students import (
    KakaoStudent,
    KakaoStudentCommand,
    KakaoStudentCreate,
    KakaoStudentMutation,
    KakaoStudentPage,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/students", tags=["kakao-archive"])
StudentId = Annotated[str, Path(pattern=r"^kakaostudent_[0-9a-f]{32}$")]
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
CHANGE = require_permission(PermissionKey.KAKAO_ARCHIVE_EDIT)
_ERROR_STATUS = {
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_STUDENT_RETIRED": 409,
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_STORED_STUDENT_INVALID": 503,
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
            "The private source operation could not be completed.",
        ) from error


def _headers(response: Response, student: KakaoStudent | None = None) -> None:
    response.headers["Cache-Control"] = "no-store"
    if student is not None:
        response.headers["ETag"] = etag(student.resource_version)


@router.get(
    "",
    operation_id="kakao_student_list",
    response_model=SingleResponse[KakaoStudentPage],
    dependencies=[Depends(READ)],
)
def list_students(
    request: Request,
    response: Response,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaostudent_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoStudentPage]:
    with _boundary():
        result = request.app.state.services.catalog_application.list_kakao_students(
            actor=request.state.request_context.actor(),
            limit=limit,
            cursor=cursor,
        )
    _headers(response)
    return one(request, result)


@router.post(
    "",
    operation_id="kakao_student_create",
    status_code=201,
    response_model=SingleResponse[KakaoStudentMutation],
    dependencies=[Depends(CHANGE)],
)
def create_student(
    request: Request,
    response: Response,
    body: KakaoStudentCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoStudentMutation]:
    with _boundary():
        result = request.app.state.services.catalog_application.create_kakao_student(
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.student)
    return one(request, result)


@router.get(
    "/{student_id}",
    operation_id="kakao_student_read",
    response_model=SingleResponse[KakaoStudent],
    dependencies=[Depends(READ)],
)
def read_student(
    request: Request,
    response: Response,
    student_id: StudentId,
    authentication: Auth,
    display_revision_id: str | None = Query(
        default=None, pattern=r"^kakaostudentrev_[0-9a-f]{32}$"
    ),
) -> SingleResponse[KakaoStudent]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_student(
            student_id,
            actor=request.state.request_context.actor(),
            display_revision_id=display_revision_id,
        )
    _headers(response, result)
    return one(request, result)


@router.post(
    "/{student_id}/commands",
    operation_id="kakao_student_command",
    response_model=SingleResponse[KakaoStudentMutation],
    dependencies=[Depends(CHANGE)],
)
def command_student(
    request: Request,
    response: Response,
    student_id: StudentId,
    body: KakaoStudentCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected: ExpectedVersion,
) -> SingleResponse[KakaoStudentMutation]:
    if expected != body.expected_resource_version:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The command version must match its resource ETag.",
        )
    with _boundary():
        result = request.app.state.services.catalog_application.command_kakao_student(
            student_id,
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.student)
    return one(request, result)
