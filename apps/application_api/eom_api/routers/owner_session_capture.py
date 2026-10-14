"""Bounded auth-control handoff; no native execution, source access or installed admission."""

from __future__ import annotations

from typing import Annotated

from eom_identity_service.owner_session_transport import (
    OwnerSessionTransportError,
    export_owner_session_capture,
)
from eom_operator_identity.errors import IdentityError
from eom_operator_identity.owner_session_capture import (
    MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES,
    OwnerSessionCaptureResponse,
    owner_session_capture_schema,
)
from eom_operator_identity.owner_session_capture_v11 import (
    OwnerSessionCaptureResponseV11,
    owner_session_capture_v11_schema,
    parse_supported_owner_session_capture_request,
    supported_owner_session_capture_bytes,
)
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from eom_api.dependencies import bearer, get_services
from eom_api.errors import ApiError

router = APIRouter(prefix="/auth", tags=["authentication"])


def _failure(status: int, code: str) -> ApiError:
    return ApiError(
        status, code, "Owner session unavailable", "The authenticated owner exchange failed."
    )


@router.post(
    "/owner-session-capture",
    operation_id="auth_owner_session_capture",
    response_model=OwnerSessionCaptureResponse | OwnerSessionCaptureResponseV11,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            owner_session_capture_schema()["$defs"]["request"],
                            owner_session_capture_v11_schema()["$defs"]["request"],
                        ]
                    }
                }
            },
        }
    },
)
async def capture_owner_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Response:
    """Authenticate exactly once; decoded request is never an opaque mint or grant."""
    try:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not 0 < len(credentials.credentials) <= 512
        ):
            raise _failure(401, "OWNER_SESSION_AUTHENTICATION_DENIED")
        length = request.headers.get("content-length", "")
        if (
            request.headers.get("transfer-encoding") is not None
            or not length.isascii()
            or not length.isdigit()
            or len(length) > 10
            or not 0 < int(length) <= MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES
            or request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise _failure(422, "OWNER_SESSION_REQUEST_INVALID")
        chunks: list[bytes] = []
        size = 0
        async for member in request.stream():
            size += len(member)
            if size > MAX_OWNER_SESSION_CAPTURE_REQUEST_BYTES:
                raise _failure(422, "OWNER_SESSION_REQUEST_INVALID")
            chunks.append(member)
        if size != int(length):
            raise _failure(422, "OWNER_SESSION_REQUEST_INVALID")
        try:
            checked = parse_supported_owner_session_capture_request(b"".join(chunks))
        except Exception:
            raise _failure(422, "OWNER_SESSION_REQUEST_INVALID") from None
        services = get_services(request)
        try:
            capture = await run_in_threadpool(services.auth.capture_access, credentials.credentials)
        except IdentityError:
            raise _failure(401, "OWNER_SESSION_AUTHENTICATION_DENIED") from None
        response = export_owner_session_capture(checked, capture)
        decision = services.rate_limiter.check(
            f"general:{response.session_id}",
            limit=services.settings.rate_limit.general_per_minute,
            window_seconds=60,
        )
        if not decision.allowed:
            raise _failure(429, "API_RATE_LIMITED")
        return Response(
            supported_owner_session_capture_bytes(response),
            media_type="application/json",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    except ApiError:
        raise
    except OwnerSessionTransportError:
        raise _failure(503, "OWNER_SESSION_TRANSPORT_UNAVAILABLE") from None
    except Exception:
        raise _failure(503, "OWNER_SESSION_TRANSPORT_UNAVAILABLE") from None
