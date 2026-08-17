"""Stable API adapter errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ApiErrorCode(StrEnum):
    AUTH_REAUTHENTICATION_REQUIRED = "AUTH_REAUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    API_REQUEST_INVALID = "API_REQUEST_INVALID"
    API_CONTENT_TYPE_UNSUPPORTED = "API_CONTENT_TYPE_UNSUPPORTED"
    API_BODY_TOO_LARGE = "API_BODY_TOO_LARGE"
    API_RATE_LIMITED = "API_RATE_LIMITED"
    API_IDEMPOTENCY_REQUIRED = "API_IDEMPOTENCY_REQUIRED"
    API_IDEMPOTENCY_CONFLICT = "API_IDEMPOTENCY_CONFLICT"
    API_IDEMPOTENCY_IN_PROGRESS = "API_IDEMPOTENCY_IN_PROGRESS"
    API_PRECONDITION_REQUIRED = "API_PRECONDITION_REQUIRED"
    API_PRECONDITION_FAILED = "API_PRECONDITION_FAILED"
    API_CURSOR_INVALID = "API_CURSOR_INVALID"
    API_DEPENDENCY_UNAVAILABLE = "API_DEPENDENCY_UNAVAILABLE"
    API_INTERNAL_ERROR = "API_INTERNAL_ERROR"
    API_MIGRATION_MISMATCH = "API_MIGRATION_MISMATCH"


@dataclass
class ApiError(Exception):
    status: int
    error_code: str | ApiErrorCode
    title: str
    detail: str
    headers: dict[str, str] | None = None


def unauthorized(error_code: str = "AUTH_TOKEN_INVALID") -> ApiError:
    return ApiError(
        401,
        error_code,
        "Authentication failed",
        "Authentication credentials are invalid or no longer active.",
        {"WWW-Authenticate": "Bearer"},
    )
