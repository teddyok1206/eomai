"""Central authentication, permission, freshness, and concurrency dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, cast

from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey, RoleKey
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from eom_api.errors import ApiError, unauthorized
from eom_api.request_context import RequestContext

if TYPE_CHECKING:
    from eom_api.lifespan import AppServices

bearer = HTTPBearer(auto_error=False, scheme_name="OpaqueBearer", bearerFormat="opaque")
IDEMPOTENCY_KEY = re.compile(r"^[!-~]{16,128}$")
ETAG = re.compile(r'^"v(?P<version>[1-9][0-9]*)"$')


def get_services(request: Request) -> AppServices:
    return cast("AppServices", request.app.state.services)


def get_request_context(request: Request) -> RequestContext:
    context: RequestContext = request.state.request_context
    route = request.scope.get("route")
    if route is not None:
        context.route_template = route.path
    return context


def get_authentication(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AccessAuthentication:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    services = get_services(request)
    authentication = services.auth.authenticate_access(credentials.credentials)
    context = get_request_context(request)
    context.authentication = authentication
    operation_id = getattr(request.scope.get("route"), "operation_id", "")
    if authentication.password_change_required and operation_id not in {
        "auth_me",
        "auth_change_password",
        "auth_logout",
    }:
        raise ApiError(
            403,
            "AUTH_PASSWORD_CHANGE_REQUIRED",
            "Password change required",
            "The temporary password must be changed before this operation.",
        )
    result = services.rate_limiter.check(
        f"general:{authentication.session_id}",
        limit=services.settings.rate_limit.general_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise ApiError(
            429,
            "API_RATE_LIMITED",
            "Rate limit exceeded",
            "The session request limit has been exceeded.",
            {"Retry-After": str(result.retry_after)},
        )
    return authentication


Auth = Annotated[AccessAuthentication, Depends(get_authentication)]


@dataclass(frozen=True)
class PermissionDependency:
    permission_key: PermissionKey
    fresh_required: bool = False
    admin_only: bool = False

    def __call__(self, request: Request, authentication: Auth) -> AccessAuthentication:
        if self.permission_key not in authentication.permissions:
            get_services(request).audit.append(
                get_request_context(request),
                event_type="PERMISSION_DENIED",
                operation_id=getattr(request.scope.get("route"), "operation_id", "unknown"),
                outcome="DENIED",
                http_status=403,
                error_code="PERMISSION_DENIED",
            )
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "Permission denied",
                "The authenticated Operator does not have the required permission.",
            )
        if self.admin_only and RoleKey.ADMIN not in authentication.operator.roles:
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "Permission denied",
                "This operation requires the ADMIN role.",
            )
        if self.fresh_required:
            age = datetime.now(UTC) - authentication.authenticated_at
            if age.total_seconds() > get_services(request).settings.auth.fresh_auth_seconds:
                get_services(request).audit.append(
                    get_request_context(request),
                    event_type="FRESH_AUTH_REQUIRED",
                    operation_id=getattr(request.scope.get("route"), "operation_id", "unknown"),
                    outcome="DENIED",
                    http_status=403,
                    error_code="AUTH_REAUTHENTICATION_REQUIRED",
                )
                raise ApiError(
                    403,
                    "AUTH_REAUTHENTICATION_REQUIRED",
                    "Re-authentication required",
                    "A recent password authentication is required for this operation.",
                )
        return authentication


def require_permission(
    permission: PermissionKey,
    *,
    fresh: bool = False,
    admin_only: bool = False,
) -> PermissionDependency:
    return PermissionDependency(permission, fresh, admin_only)


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if idempotency_key is None:
        raise ApiError(
            400,
            "API_IDEMPOTENCY_REQUIRED",
            "Idempotency key required",
            "A valid Idempotency-Key header is required.",
        )
    if not IDEMPOTENCY_KEY.fullmatch(idempotency_key) or any(
        character.isspace() for character in idempotency_key
    ):
        raise ApiError(
            422,
            "API_REQUEST_INVALID",
            "Invalid idempotency key",
            "The Idempotency-Key header does not satisfy the API contract.",
        )
    return idempotency_key


IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]


def require_if_match(if_match: Annotated[str | None, Header(alias="If-Match")] = None) -> int:
    if if_match is None:
        raise ApiError(
            428,
            "API_PRECONDITION_REQUIRED",
            "Precondition required",
            "A strong resource ETag is required in If-Match.",
        )
    match = ETAG.fullmatch(if_match)
    if match is None:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The supplied resource ETag is invalid.",
        )
    return int(match.group("version"))


ExpectedVersion = Annotated[int, Depends(require_if_match)]


def check_version(expected: int, current: int) -> None:
    if expected != current:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The resource has changed since it was read.",
        )


def etag(version: int) -> str:
    return f'"v{version}"'
