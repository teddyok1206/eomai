"""Authentication request and response DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, model_validator

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class LoginRequest(ApiModel):
    username: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)
    client_name: str = Field(min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")


class RefreshRequest(ApiModel):
    refresh_token: SecretStr = Field(min_length=73, max_length=73)


class ChangePasswordRequest(ApiModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=1, max_length=128)


class UpdateCredentialsRequest(ApiModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_username: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    new_password: SecretStr | None = Field(default=None, min_length=1, max_length=128)
    expected_resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_a_change(self) -> UpdateCredentialsRequest:
        if self.new_username is None and self.new_password is None:
            raise ValueError("new_username or new_password is required")
        if "new_username" in self.model_fields_set and self.new_username is None:
            raise ValueError("new_username must be omitted instead of null")
        if "new_password" in self.model_fields_set and self.new_password is None:
            raise ValueError("new_password must be omitted instead of null")
        return self


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


class CurrentAccount(CurrentOperator):
    schema_version: Literal["auth-current-account/1.0"] = "auth-current-account/1.0"
    resource_version: int = Field(ge=1)


class CredentialUpdateResult(ApiModel):
    tokens: TokenPair
    operator: CurrentAccount


class LogoutResult(ApiModel):
    logged_out: bool


class LogoutAllResult(ApiModel):
    revoked_sessions: int = Field(ge=0)
