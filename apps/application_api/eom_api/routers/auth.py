"""Opaque-token authentication endpoints."""

from __future__ import annotations

from eom_api_contracts import SingleResponse
from eom_api_contracts.auth import (
    ChangePasswordRequest,
    CurrentOperator,
    LoginRequest,
    LogoutAllResult,
    LogoutResult,
    RefreshRequest,
    TokenPair,
)
from eom_identity_service.auth_service import AuthenticationFailure
from eom_identity_service.tokens import TokenType
from eom_operator_identity import normalize_username
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from fastapi import APIRouter, Request

from eom_api.dependencies import Auth
from eom_api.errors import ApiError
from eom_api.redaction import fingerprint
from eom_api.routers.common import context, one

router = APIRouter(prefix="/auth", tags=["authentication"])


def _token_pair(pair) -> TokenPair:  # type: ignore[no-untyped-def]
    return TokenPair(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        session_id=pair.session_id,
        password_change_required=pair.password_change_required,
    )


@router.post(
    "/login",
    operation_id="auth_login",
    response_model=SingleResponse[TokenPair],
    responses={401: {"description": "Invalid credentials"}, 429: {"description": "Rate limited"}},
)
def login(request: Request, body: LoginRequest) -> SingleResponse[TokenPair]:
    services = request.app.state.services
    context(request).client_name = body.client_name
    global_limit = services.rate_limiter.check(
        "login:global",
        limit=services.settings.rate_limit.login_global_per_minute,
        window_seconds=60,
    )
    username_fingerprint = fingerprint(services.fingerprint_key, normalize_username(body.username))
    username_limit = services.rate_limiter.check(
        f"login:username:{username_fingerprint}",
        limit=services.settings.rate_limit.login_username_per_window,
        window_seconds=services.settings.auth.login_failure_window_seconds,
    )
    if not global_limit.allowed or not username_limit.allowed:
        retry = max(global_limit.retry_after, username_limit.retry_after)
        raise ApiError(
            429,
            "API_RATE_LIMITED",
            "Rate limit exceeded",
            "The login request limit has been exceeded.",
            {"Retry-After": str(retry)},
        )
    try:
        result = services.auth.login(
            username=body.username,
            password=body.password.get_secret_value(),
            client_name=body.client_name,
        )
    except AuthenticationFailure as exc:
        services.audit.append(
            context(request),
            event_type=(
                "ACCOUNT_LOCKED" if exc.internal_reason == "ACCOUNT_LOCKED" else "LOGIN_FAILED"
            ),
            operation_id="auth_login",
            outcome="FAILED",
            http_status=401,
            error_code="AUTH_INVALID_CREDENTIALS",
        )
        raise
    request_context = context(request)
    request_context.authentication = services.auth.authenticate_access(result.pair.access_token)
    services.audit.append(
        request_context,
        event_type="LOGIN_SUCCEEDED",
        operation_id="auth_login",
        outcome="SUCCEEDED",
        http_status=200,
    )
    return one(request, _token_pair(result.pair))


@router.post(
    "/refresh",
    operation_id="auth_refresh",
    response_model=SingleResponse[TokenPair],
    responses={401: {"description": "Invalid refresh token"}},
)
def refresh(request: Request, body: RefreshRequest) -> SingleResponse[TokenPair]:
    services = request.app.state.services
    raw = body.refresh_token.get_secret_value()
    parsed = services.auth.tokens.codec.parse(raw, TokenType.REFRESH)
    selector = parsed[0] if parsed is not None else "invalid"
    selector_key = fingerprint(services.fingerprint_key, selector)
    limit = services.rate_limiter.check(
        f"refresh:{selector_key}",
        limit=services.settings.rate_limit.refresh_per_minute,
        window_seconds=60,
    )
    if not limit.allowed:
        raise ApiError(
            429,
            "API_RATE_LIMITED",
            "Rate limit exceeded",
            "The refresh request limit has been exceeded.",
            {"Retry-After": str(limit.retry_after)},
        )
    try:
        pair = services.auth.refresh(raw)
    except IdentityError as exc:
        if exc.code is IdentityErrorCode.AUTH_REFRESH_TOKEN_REUSED:
            services.audit.append(
                context(request),
                event_type="REFRESH_REUSE_DETECTED",
                operation_id="auth_refresh",
                outcome="DENIED",
                http_status=401,
                error_code=exc.code.value,
            )
        raise
    request_context = context(request)
    request_context.authentication = services.auth.authenticate_access(pair.access_token)
    services.audit.append(
        request_context,
        event_type="TOKEN_REFRESHED",
        operation_id="auth_refresh",
        outcome="SUCCEEDED",
        http_status=200,
    )
    return one(request, _token_pair(pair))


@router.post(
    "/logout",
    operation_id="auth_logout",
    response_model=SingleResponse[LogoutResult],
)
def logout(request: Request, authentication: Auth) -> SingleResponse[LogoutResult]:
    services = request.app.state.services
    services.auth.logout(authentication.session_id, authentication.operator.operator_id)
    services.audit.append(
        context(request),
        event_type="LOGOUT",
        operation_id="auth_logout",
        outcome="SUCCEEDED",
        http_status=200,
    )
    return one(request, LogoutResult(logged_out=True))


@router.post(
    "/logout-all",
    operation_id="auth_logout_all",
    response_model=SingleResponse[LogoutAllResult],
)
def logout_all(request: Request, authentication: Auth) -> SingleResponse[LogoutAllResult]:
    services = request.app.state.services
    count = services.auth.logout_all(authentication.operator.operator_id)
    return one(request, LogoutAllResult(revoked_sessions=count))


@router.get("/me", operation_id="auth_me", response_model=SingleResponse[CurrentOperator])
def me(request: Request, authentication: Auth) -> SingleResponse[CurrentOperator]:
    operator = authentication.operator
    return one(
        request,
        CurrentOperator(
            operator_id=operator.operator_id,
            username=operator.username,
            display_name=operator.display_name,
            roles=tuple(role.value for role in operator.roles),
            effective_permissions=tuple(
                permission.value for permission in operator.effective_permissions
            ),
            session_id=authentication.session_id,
            authenticated_at=authentication.authenticated_at,
            access_expires_at=authentication.access_expires_at,
            password_change_required=authentication.password_change_required,
        ),
    )


@router.post(
    "/change-password",
    operation_id="auth_change_password",
    response_model=SingleResponse[TokenPair],
)
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    authentication: Auth,
) -> SingleResponse[TokenPair]:
    pair = request.app.state.services.auth.change_password(
        authentication,
        current_password=body.current_password.get_secret_value(),
        new_password=body.new_password.get_secret_value(),
    )
    request.app.state.services.audit.append(
        context(request),
        event_type="PASSWORD_CHANGED",
        operation_id="auth_change_password",
        outcome="SUCCEEDED",
        http_status=200,
    )
    return one(request, _token_pair(pair))
