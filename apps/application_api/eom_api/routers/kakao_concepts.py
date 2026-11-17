"""Thin current-session recommendation routes; GET never runs a model."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, cast

from eom_api_contracts import SingleResponse
from eom_catalog_contracts.kakao_concept_rpc import (
    CONCEPT_ERRORS,
    ConceptHistory,
    ConceptRequest,
    ConceptResult,
    ConceptStarted,
    ConceptView,
    ListConceptsRequest,
    ReadConceptPageRequest,
    ReadConceptRequest,
    StartConceptRequest,
)
from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptCreate
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/concepts", tags=["kakao-archive"])
BindingId = Annotated[str, Query(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
TaskId = Annotated[str, Path(pattern=r"^kakaoconcepttask_[0-9a-f]{32}$")]
EDIT = require_permission(PermissionKey.KAKAO_ARCHIVE_EDIT)
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)


def _identity(request: Request) -> dict[str, object]:
    actor = request.state.request_context.actor()
    return dict(
        actor_id=actor.operator_id,
        session_id=actor.session_id,
        request_id=actor.request_id,
        authentication_time=actor.authentication_time,
    )


@contextmanager
def _boundary() -> Iterator[None]:
    try:
        yield
    except CatalogApplicationClientError as error:
        code = error.code if error.code in CONCEPT_ERRORS else "KAKAO_ARCHIVE_UNAVAILABLE"
        status = {
            "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
            "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
            "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
            "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
            "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
            "KAKAO_CONCEPT_RESULT_NOT_READY": 409,
            "KAKAO_CONCEPT_PAGE_POINTER_INVALID": 409,
            "CONTROL_PRESET_POINTER_STALE": 409,
        }.get(code, 503)
        raise ApiError(
            status,
            code,
            "KakaoTalk concept request failed",
            "The authorized recommendation operation could not be completed.",
        ) from error


def _call(request: Request, command: ConceptRequest) -> ConceptResult:
    with _boundary():
        return cast(
            ConceptResult,
            request.app.state.services.catalog_application.request_kakao_concept(command),
        )


@router.post(
    "",
    status_code=202,
    response_model=SingleResponse[ConceptStarted],
    operation_id="kakao_concept_start",
    dependencies=[Depends(EDIT)],
)
def start(
    request: Request,
    response: Response,
    body: KakaoConceptCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ConceptStarted]:
    result = cast(
        ConceptStarted,
        _call(
            request,
            StartConceptRequest.model_validate(
                {
                    **_identity(request),
                    "command": body,
                    "idempotency_key": idempotency_key,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "",
    response_model=SingleResponse[ConceptHistory],
    operation_id="kakao_concept_list",
    dependencies=[Depends(READ)],
)
def history(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaoconcepttask_[0-9a-f]{32}$"),
) -> SingleResponse[ConceptHistory]:
    result = cast(
        ConceptHistory,
        _call(
            request,
            ListConceptsRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "limit": limit,
                    "cursor": cursor,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "/{task_id}",
    response_model=SingleResponse[ConceptView],
    operation_id="kakao_concept_read",
    dependencies=[Depends(READ)],
)
def read(
    request: Request,
    response: Response,
    task_id: TaskId,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[ConceptView]:
    result = cast(
        ConceptView,
        _call(
            request,
            ReadConceptRequest.model_validate(
                {
                    **_identity(request),
                    "source_binding_id": source_binding_id,
                    "task_id": task_id,
                }
            ),
        ),
    )
    response.headers["Cache-Control"] = "no-store"
    return one(request, result)


@router.get(
    "/{task_id}/pages/{page_key}", operation_id="kakao_concept_page", dependencies=[Depends(READ)]
)
def page(
    request: Request,
    task_id: TaskId,
    source_binding_id: BindingId,
    authentication: Auth,
    page_key: Annotated[str, Path(pattern=r"^E[1-3]P[1-9][0-9]{0,4}$")],
) -> StreamingResponse:
    command = ReadConceptPageRequest.model_validate(
        {
            **_identity(request),
            "source_binding_id": source_binding_id,
            "task_id": task_id,
            "page_key": page_key,
        }
    )
    with _boundary():
        result = request.app.state.services.catalog_application.download_kakao_concept_page(command)
    return StreamingResponse(
        result.iter_chunks(),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(result.content_length),
            "Content-Disposition": "inline",
            "ETag": '"' + result.sha256 + '"',
        },
    )
