"""RFC 9457 rendering and exception-to-HTTP mapping."""

from __future__ import annotations

import re

from eom_api_contracts import ProblemDetails, ValidationIssue
from eom_content_intake import IntakeError
from eom_content_pack import ContentPackError
from eom_item_registry import RegistryError
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_workflow_runner.errors import WorkflowError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from eom_api.errors import ApiError
from eom_api.redaction import redact_text

PROBLEM_MEDIA_TYPE = "application/problem+json"

IDENTITY_STATUS = {
    IdentityErrorCode.AUTH_INVALID_CREDENTIALS: 401,
    IdentityErrorCode.AUTH_TOKEN_INVALID: 401,
    IdentityErrorCode.AUTH_TOKEN_EXPIRED: 401,
    IdentityErrorCode.AUTH_REFRESH_TOKEN_INVALID: 401,
    IdentityErrorCode.AUTH_REFRESH_TOKEN_REUSED: 401,
    IdentityErrorCode.AUTH_SESSION_REVOKED: 401,
    IdentityErrorCode.AUTH_PASSWORD_CHANGE_REQUIRED: 403,
    IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED: 422,
    IdentityErrorCode.OPERATOR_NOT_FOUND: 404,
    IdentityErrorCode.OPERATOR_USERNAME_CONFLICT: 409,
    IdentityErrorCode.OPERATOR_DISABLED: 409,
    IdentityErrorCode.OPERATOR_LAST_ADMIN: 409,
    IdentityErrorCode.OPERATOR_ROLE_ALREADY_ASSIGNED: 409,
    IdentityErrorCode.OPERATOR_ROLE_NOT_ASSIGNED: 409,
    IdentityErrorCode.ROLE_NOT_FOUND: 404,
    IdentityErrorCode.PERMISSION_NOT_FOUND: 404,
}


def _slug(code: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-")


def request_id(request: Request) -> str:
    context = getattr(request.state, "request_context", None)
    return context.request_id if context is not None else "req_unavailable"


def problem_response(
    request: Request,
    *,
    status: int,
    error_code: str,
    title: str,
    detail: str,
    errors: tuple[ValidationIssue, ...] = (),
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    identifier = request_id(request)
    body = ProblemDetails(
        type=f"urn:eom:problem:{_slug(error_code)}",
        title=title,
        status=status,
        detail=redact_text(detail),
        instance=f"urn:eom:request:{identifier}",
        error_code=error_code,
        request_id=identifier,
        errors=errors,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(mode="json"),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def _validation_pointer(location: tuple[int | str, ...]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in location]
    if parts and parts[0] in {"body", "query", "path", "header"}:
        parts = parts[1:]
    return "/" + "/".join(parts)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return problem_response(
            request,
            status=exc.status,
            error_code=exc.error_code,
            title=exc.title,
            detail=exc.detail,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        issues = tuple(
            ValidationIssue(
                pointer=_validation_pointer(tuple(error["loc"])),
                code=str(error["type"]).upper(),
                detail="The supplied value does not satisfy the request schema.",
            )
            for error in exc.errors()[:100]
        )
        return problem_response(
            request,
            status=422,
            error_code="API_REQUEST_INVALID",
            title="Request validation failed",
            detail="One or more request values are invalid.",
            errors=issues,
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = "API_REQUEST_INVALID"
        if exc.status_code == 404:
            code = "API_ROUTE_NOT_FOUND"
        elif exc.status_code == 405:
            code = "API_METHOD_NOT_ALLOWED"
        return problem_response(
            request,
            status=exc.status_code,
            error_code=code,
            title="HTTP request failed",
            detail="The requested API operation could not be completed.",
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(IdentityError)
    async def identity_handler(request: Request, exc: IdentityError) -> JSONResponse:
        status = IDENTITY_STATUS.get(exc.code, 409)
        generic = status == 401
        return problem_response(
            request,
            status=status,
            error_code=exc.code.value,
            title="Authentication failed" if generic else "Identity operation failed",
            detail=(
                "Authentication credentials are invalid or no longer active."
                if generic
                else "The identity operation could not be completed."
            ),
            headers={"WWW-Authenticate": "Bearer"} if generic else None,
        )

    async def domain_handler(request: Request, exc: Exception) -> JSONResponse:
        code = getattr(getattr(exc, "code", None), "value", "DOMAIN_CONFLICT")
        status = 404 if str(code).endswith("NOT_FOUND") else 409
        return problem_response(
            request,
            status=status,
            error_code=str(code),
            title="Domain operation failed",
            detail="The requested domain operation could not be completed.",
        )

    for exception_type in (IntakeError, ContentPackError, RegistryError, WorkflowError):
        app.add_exception_handler(exception_type, domain_handler)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return problem_response(
            request,
            status=500,
            error_code="API_INTERNAL_ERROR",
            title="Internal server error",
            detail="The request could not be completed.",
        )
