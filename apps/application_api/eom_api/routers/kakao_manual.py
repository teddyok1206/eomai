"""Start accepts an intent; a read never launches or renews a remote browser."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from eom_api_contracts import SingleResponse
from eom_api_contracts.kakao_manual import (
    KakaoManualEnd,
    KakaoManualMutation,
    KakaoManualRenew,
    KakaoManualSession,
    KakaoManualStart,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Path, Request, Response
from pydantic import Field

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one
from eom_api.services.catalog_application_client import CatalogApplicationClientError

router = APIRouter(prefix="/kakao-archive/manual-sessions", tags=["kakao-archive"])
LeaseId = Annotated[str, Path(pattern=r"^kakaoremotelease_[0-9a-f]{32}$")]
Command = Annotated[KakaoManualRenew | KakaoManualEnd, Field(discriminator="action")]
REMOTE = require_permission(PermissionKey.KAKAO_ARCHIVE_REMOTE, admin_only=True)
_ERROR_STATUS = {
    "KAKAO_ARCHIVE_PERMISSION_DENIED": 403,
    "KAKAO_ARCHIVE_RESOURCE_NOT_FOUND": 404,
    "KAKAO_ARCHIVE_PRECONDITION_FAILED": 412,
    "KAKAO_ARCHIVE_IDEMPOTENCY_CONFLICT": 409,
    "KAKAO_ARCHIVE_BINDING_RETIRED": 409,
    "KAKAO_ARCHIVE_REQUEST_INVALID": 422,
    "KAKAO_ARCHIVE_REMOTE_PROFILE_BUSY": 409,
    "KAKAO_ARCHIVE_REMOTE_PROFILE_UNASSIGNED": 409,
    "KAKAO_ARCHIVE_REMOTE_FENCE_STALE": 409,
    "KAKAO_ARCHIVE_REMOTE_LEASE_EXPIRED": 409,
    "KAKAO_ARCHIVE_REMOTE_NOT_READY": 409,
    "KAKAO_ARCHIVE_REMOTE_PROFILE_UNAVAILABLE": 503,
    "KAKAO_ARCHIVE_REMOTE_RUNTIME_UNAVAILABLE": 503,
    "KAKAO_ARCHIVE_REMOTE_OBSERVATION_STALE": 503,
    "KAKAO_ARCHIVE_REMOTE_OBSERVATION_MISMATCH": 503,
    "KAKAO_ARCHIVE_REMOTE_STOP_UNCONFIRMED": 503,
    "KAKAO_ARCHIVE_STORED_MANUAL_SESSION_INVALID": 503,
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
            "KakaoTalk remote request failed",
            "The private manual session could not be completed.",
        ) from error


def _headers(response: Response, session: KakaoManualSession) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = etag(session.resource_version)


@router.post(
    "",
    operation_id="kakao_manual_start",
    status_code=202,
    response_model=SingleResponse[KakaoManualMutation],
    dependencies=[Depends(REMOTE)],
)
def start_session(
    request: Request,
    response: Response,
    body: KakaoManualStart,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[KakaoManualMutation]:
    with _boundary():
        result = request.app.state.services.catalog_application.start_kakao_manual(
            body, actor=request.state.request_context.actor(), idempotency_key=idempotency_key
        )
    _headers(response, result.session)
    return one(request, result)


@router.get(
    "/{lease_id}",
    operation_id="kakao_manual_read",
    response_model=SingleResponse[KakaoManualSession],
    dependencies=[Depends(REMOTE)],
)
def read_session(
    request: Request, response: Response, lease_id: LeaseId, authentication: Auth
) -> SingleResponse[KakaoManualSession]:
    with _boundary():
        result = request.app.state.services.catalog_application.read_kakao_manual(
            lease_id, actor=request.state.request_context.actor()
        )
    _headers(response, result)
    return one(request, result)


@router.post(
    "/{lease_id}/commands",
    operation_id="kakao_manual_command",
    response_model=SingleResponse[KakaoManualMutation],
    dependencies=[Depends(REMOTE)],
)
def command_session(
    request: Request,
    response: Response,
    lease_id: LeaseId,
    body: Command,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SingleResponse[KakaoManualMutation]:
    if isinstance(body, KakaoManualEnd) and if_match != etag(body.expected_resource_version):
        raise ApiError(
            412, "API_PRECONDITION_FAILED", "Precondition failed", "The session ETag must match."
        )
    with _boundary():
        result = request.app.state.services.catalog_application.command_kakao_manual(
            lease_id,
            body,
            actor=request.state.request_context.actor(),
            idempotency_key=idempotency_key,
        )
    _headers(response, result.session)
    return one(request, result)
