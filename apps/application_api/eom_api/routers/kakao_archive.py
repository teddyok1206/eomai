"""Private KakaoTalk binding HTTP transport; Catalog owns state and replay."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_archive import (
    KakaoBindingCommand,
    KakaoBindingCreate,
    KakaoBindingMutation,
    KakaoBindingPage,
    KakaoSourceBinding,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/source-bindings", tags=["kakao-archive"])
BindingId = Annotated[str, Path(pattern=r"^kakaobinding_[0-9a-f]{32}$")]
READ = require_permission(PermissionKey.KAKAO_ARCHIVE_READ)
CHANGE = require_permission(PermissionKey.KAKAO_ARCHIVE_COLLECT, admin_only=True)
_ERROR_STATUS = {
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_STORED_POLICY_INVALID": 503,
    "KAKAO_ARCHIVE_STORED_BINDING_INVALID": 503,
    "KAKAO_ARCHIVE_POLICY_REFERENCE_INVALID": 503,
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


def _headers(response: Response, binding: KakaoSourceBinding | None = None) -> None:
    response.headers["Cache-Control"] = "no-store"
    if binding is not None:
        response.headers["ETag"] = etag(binding.resource_version)


@router.get(
    "",
    operation_id="kakao_binding_list",
    response_model=SingleResponse[KakaoBindingPage],
    dependencies=[Depends(READ)],
)
def list_bindings(
    request: Request,
    response: Response,
    authentication: Auth,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, pattern=r"^kakaobinding_[0-9a-f]{32}$"),
) -> SingleResponse[KakaoBindingPage]:
    with _boundary():
        result = request.app.state.services.catalog_application.list_kakao_bindings(
            actor=request.state.request_context.actor(),
            limit=limit,
            cursor=cursor,
        )
    _headers(response)
    return one(request, result)


@router.post(
    "",
    operation_id="kakao_binding_create",
    status_code=201,
    response_model=SingleResponse[KakaoBindingMutation],
    dependencies=[Depends(CHANGE)],
)
def create_binding(
    request: Request,
    response: Response,
    body: KakaoBindingCreate,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoBindingMutation]:
    with _boundary():
        result = request.app.state.services.catalog_application.create_kakao_binding(
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.binding)
    return one(request, result)


@router.get(
    "/{source_binding_id}",
    operation_id="kakao_binding_read",
    response_model=SingleResponse[KakaoSourceBinding],
    dependencies=[Depends(READ)],
)
def read_binding(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    authentication: Auth,
) -> SingleResponse[KakaoSourceBinding]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_binding(
            source_binding_id,
            actor=request.state.request_context.actor(),
        )
    _headers(response, result)
    return one(request, result)


@router.post(
    "/{source_binding_id}/commands",
    operation_id="kakao_binding_command",
    response_model=SingleResponse[KakaoBindingMutation],
    dependencies=[Depends(CHANGE)],
)
def command_binding(
    request: Request,
    response: Response,
    source_binding_id: BindingId,
    body: KakaoBindingCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected: ExpectedVersion,
) -> SingleResponse[KakaoBindingMutation]:
    if expected != body.expected_resource_version:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The command version must match its resource ETag.",
        )
    with _boundary():
        result = request.app.state.services.catalog_application.command_kakao_binding(
            source_binding_id,
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.binding)
    return one(request, result)
