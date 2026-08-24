"""Stable identity and RBAC value contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class OperatorStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class RoleKey(StrEnum):
    VIEWER = "VIEWER"
    AUTHOR = "AUTHOR"
    REVIEWER = "REVIEWER"
    EDITOR = "EDITOR"
    ADMIN = "ADMIN"


class PermissionKey(StrEnum):
    SYSTEM_READ = "system:read"
    SYSTEM_DOCTOR = "system:doctor"
    OPERATOR_READ = "operator:read"
    OPERATOR_CREATE = "operator:create"
    OPERATOR_ASSIGN_ROLE = "operator:assign_role"
    OPERATOR_REVOKE_ROLE = "operator:revoke_role"
    OPERATOR_DISABLE = "operator:disable"
    OPERATOR_ENABLE = "operator:enable"
    OPERATOR_REVOKE_SESSIONS = "operator:revoke_sessions"
    CONTENT_INTAKE_READ = "content_intake:read"
    CONTENT_INTAKE_CREATE = "content_intake:create"
    CONTENT_INTAKE_ATTACH_ANALYSIS = "content_intake:attach_analysis"
    CONTENT_INTAKE_DECIDE = "content_intake:decide"
    CONTENT_PACK_READ = "content_pack:read"
    CONTENT_PACK_RELEASE = "content_pack:release"
    CONTENT_PACK_ACTIVATE = "content_pack:activate"
    CONTENT_PACK_DEPRECATE = "content_pack:deprecate"
    WORKFLOW_READ = "workflow:read"
    WORKFLOW_START = "workflow:start"
    WORKFLOW_APPROVE = "workflow:approve"
    WORKFLOW_REQUEST_REWORK = "workflow:request_rework"
    WORKFLOW_CANCEL = "workflow:cancel"
    WORKFLOW_RECONCILE = "workflow:reconcile"
    ITEM_READ = "item:read"
    ITEM_STRUCTURED_CONTENT_IMPORT = "item:import_structured_content"
    ITEM_RETIRE = "item:retire"
    DELIVERABLE_READ = "deliverable:read"
    DELIVERABLE_CREATE = "deliverable:create"
    DELIVERABLE_UPDATE = "deliverable:update"
    USAGE_READ = "usage:read"
    USAGE_CREATE_PLAN = "usage:create_plan"
    USAGE_RESERVE_PLAN = "usage:reserve_plan"
    USAGE_CANCEL_PLAN = "usage:cancel_plan"
    USAGE_FULFILL_PLAN = "usage:fulfill_plan"
    EVENT_READ = "event:read"
    HWPX_READ = "hwpx:read"
    HWPX_BUILD_CREATE = "hwpx:build_create"
    CODEX_ACCOUNT_READ = "codex_account:read"
    CODEX_ACCOUNT_MANAGE = "codex_account:manage"
    EXECUTION_PRESET_READ = "execution_preset:read"
    EXECUTION_PRESET_MANAGE = "execution_preset:manage"
    KNOWLEDGE_ANALYSIS_READ = "knowledge_analysis:read"
    KNOWLEDGE_ANALYSIS_CREATE = "knowledge_analysis:create"
    KNOWLEDGE_ANALYSIS_REVIEW = "knowledge_analysis:review"


VIEWER_PERMISSIONS = frozenset(
    {
        PermissionKey.SYSTEM_READ,
        PermissionKey.CONTENT_INTAKE_READ,
        PermissionKey.CONTENT_PACK_READ,
        PermissionKey.WORKFLOW_READ,
        PermissionKey.ITEM_READ,
        PermissionKey.DELIVERABLE_READ,
        PermissionKey.USAGE_READ,
        PermissionKey.EVENT_READ,
        PermissionKey.HWPX_READ,
    }
)

ROLE_PERMISSIONS = MappingProxyType(
    {
        RoleKey.VIEWER: VIEWER_PERMISSIONS,
        RoleKey.AUTHOR: VIEWER_PERMISSIONS
        | {
            PermissionKey.CONTENT_INTAKE_CREATE,
            PermissionKey.CONTENT_INTAKE_ATTACH_ANALYSIS,
            PermissionKey.WORKFLOW_START,
        },
        RoleKey.REVIEWER: VIEWER_PERMISSIONS
        | {
            PermissionKey.CONTENT_INTAKE_DECIDE,
            PermissionKey.WORKFLOW_APPROVE,
            PermissionKey.WORKFLOW_REQUEST_REWORK,
        },
        RoleKey.EDITOR: VIEWER_PERMISSIONS
        | {
            PermissionKey.DELIVERABLE_CREATE,
            PermissionKey.DELIVERABLE_UPDATE,
            PermissionKey.HWPX_BUILD_CREATE,
            PermissionKey.USAGE_CREATE_PLAN,
            PermissionKey.USAGE_RESERVE_PLAN,
            PermissionKey.USAGE_CANCEL_PLAN,
            PermissionKey.USAGE_FULFILL_PLAN,
        },
        RoleKey.ADMIN: frozenset(PermissionKey),
    }
)


class ActorType(StrEnum):
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


class ActorSource(StrEnum):
    APPLICATION_API = "APPLICATION_API"
    CLI = "CLI"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]
OperatorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
ApiSessionId = Annotated[str, Field(pattern=r"^apisession_[0-9a-f]{32}$")]
RequestId = Annotated[
    str, Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]+$")
]


def normalize_username(value: str) -> str:
    return value.lower()


def validate_username(value: str) -> str:
    normalized = normalize_username(value)
    if value != normalized:
        raise ValueError("username must use lowercase ASCII")
    if not 3 <= len(value) <= 64 or USERNAME_PATTERN.fullmatch(value) is None:
        raise ValueError("username format is invalid")
    return value


def validate_display_name(value: str) -> str:
    if not 1 <= len(value) <= 128 or not value.strip():
        raise ValueError("display name length is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError("display name contains a control character")
    return value


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class ActorContext(FrozenModel):
    actor_type: ActorType
    operator_id: OperatorId | None
    session_id: ApiSessionId | None
    request_id: RequestId
    authentication_time: UtcDatetime
    permissions: frozenset[PermissionKey]
    source: ActorSource

    @model_validator(mode="after")
    def validate_identity(self) -> ActorContext:
        if self.actor_type is ActorType.OPERATOR and self.operator_id is None:
            raise ValueError("operator actor requires operator_id")
        if self.source is ActorSource.APPLICATION_API and self.session_id is None:
            raise ValueError("application API actor requires session_id")
        return self

    @property
    def actor_id(self) -> str:
        return self.operator_id or "system"


class OperatorProjection(FrozenModel):
    operator_id: OperatorId
    username: str
    display_name: str
    status: OperatorStatus
    must_change_password: bool
    roles: tuple[RoleKey, ...]
    effective_permissions: tuple[PermissionKey, ...]
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    disabled_at: UtcDatetime | None = None
    disable_reason: str | None = Field(default=None, max_length=1000)
    last_login_at: UtcDatetime | None = None
