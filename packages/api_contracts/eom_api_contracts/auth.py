"""Authentication request and response DTOs."""

from typing import Literal

from pydantic import Field, SecretStr

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class LoginRequest(ApiModel):
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)
    client_name: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")


class RefreshRequest(ApiModel):
    refresh_token: SecretStr = Field(min_length=73, max_length=73)


class ChangePasswordRequest(ApiModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)


class TokenPair(ApiModel):
    access_token: str = Field(pattern=r"^eom_at_")
    refresh_token: str = Field(pattern=r"^eom_rt_")
    token_type: Literal["bearer"] = "bearer"
    access_expires_at: UtcDatetime
    refresh_expires_at: UtcDatetime
    session_id: OpaqueId
    password_change_required: bool


class CurrentOperator(ApiModel):
    operator_id: OpaqueId
    username: str
    display_name: str
    roles: tuple[str, ...]
    effective_permissions: tuple[str, ...]
    session_id: OpaqueId
    authenticated_at: UtcDatetime
    access_expires_at: UtcDatetime
    password_change_required: bool


class LogoutResult(ApiModel):
    logged_out: bool


class LogoutAllResult(ApiModel):
    revoked_sessions: int = Field(ge=0)
