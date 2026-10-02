"""Operator management DTOs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator

from eom_api_contracts.common import ApiModel, UtcDatetime

OperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
OperatorRoleKey = Literal["VIEWER", "AUTHOR", "REVIEWER", "EDITOR", "ADMIN"]


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
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    )
    display_name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    )
    temporary_password: SecretStr = Field(min_length=1, max_length=128)
    initial_roles: tuple[OperatorRoleKey, ...] = Field(min_length=1, max_length=5)

    @field_validator("initial_roles")
    @classmethod
    def roles_must_be_unique(
        cls, value: tuple[OperatorRoleKey, ...]
    ) -> tuple[OperatorRoleKey, ...]:
        if len(value) != len(set(value)):
            raise ValueError("initial roles must be unique")
        return value


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
