"""Operator management DTOs."""

from typing import Annotated

from pydantic import Field, SecretStr

from eom_api_contracts.common import ApiModel, UtcDatetime

OperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]


class OperatorView(ApiModel):
    operator_id: OperatorId
    username: str
    display_name: str
    status: str
    must_change_password: bool
    roles: tuple[str, ...]
    effective_permissions: tuple[str, ...]
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    disabled_at: UtcDatetime | None = None
    disable_reason: str | None = Field(default=None, max_length=1000)
    last_login_at: UtcDatetime | None = None


class CreateOperatorRequest(ApiModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    temporary_password: SecretStr = Field(min_length=15, max_length=128)
    initial_roles: tuple[str, ...] = Field(min_length=1, max_length=5)


class ReasonRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)


class RoleRevocationRequest(ReasonRequest):
    role_key: str = Field(pattern=r"^(VIEWER|AUTHOR|REVIEWER|EDITOR|ADMIN)$")


class RoleAssignmentResult(ApiModel):
    operator_id: OperatorId
    role_key: str
    resource_version: int = Field(ge=1)


class SessionRevocationResult(ApiModel):
    operator_id: OperatorId
    revoked_sessions: int = Field(ge=0)
