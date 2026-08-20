"""Typed authorization boundary for workflow human actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from eom_operator_identity import PermissionKey

OPERATOR_ACTOR_PATTERN = re.compile(r"^operator_[0-9a-f]{32}$")
WORKFLOW_HUMAN_PERMISSIONS = frozenset(
    {
        PermissionKey.WORKFLOW_APPROVE,
        PermissionKey.WORKFLOW_REQUEST_REWORK,
        PermissionKey.WORKFLOW_CANCEL,
        PermissionKey.WORKFLOW_RECONCILE,
    }
)


class WorkflowActorNamespace(StrEnum):
    OPERATOR_IDENTITY = "OPERATOR_IDENTITY"
    STATIC = "STATIC"


class WorkflowActorDenialReason(StrEnum):
    ACTOR_UNKNOWN = "ACTOR_UNKNOWN"
    ACTOR_MALFORMED = "ACTOR_MALFORMED"
    ACTOR_DISABLED = "ACTOR_DISABLED"
    PERMISSION_ABSENT = "PERMISSION_ABSENT"
    IDENTITY_BACKEND_UNAVAILABLE = "IDENTITY_BACKEND_UNAVAILABLE"


@dataclass(frozen=True)
class WorkflowActorAuthorization:
    canonical_actor_id: str
    namespace: WorkflowActorNamespace
    authorized: bool
    capabilities: frozenset[PermissionKey]
    workflow_roles: frozenset[str]
    denial_reason: WorkflowActorDenialReason | None = None

    def __post_init__(self) -> None:
        if self.authorized == (self.denial_reason is not None):
            raise ValueError("authorization result and denial reason disagree")


@dataclass(frozen=True)
class WorkflowActorAuthorizationReadiness:
    ready: bool
    code: str
    detail: str


class WorkflowActorAuthorizer(Protocol):
    def authorize(
        self, actor_id: str, required_permission: PermissionKey
    ) -> WorkflowActorAuthorization: ...

    def readiness(self) -> WorkflowActorAuthorizationReadiness: ...


class CompositeWorkflowActorAuthorizer:
    """Route canonical Operator identities without fallback to the static namespace."""

    def __init__(
        self,
        *,
        operator: WorkflowActorAuthorizer,
        static: WorkflowActorAuthorizer,
    ) -> None:
        self.operator = operator
        self.static = static

    def authorize(
        self, actor_id: str, required_permission: PermissionKey
    ) -> WorkflowActorAuthorization:
        if actor_id.startswith("operator_"):
            return self.operator.authorize(actor_id, required_permission)
        return self.static.authorize(actor_id, required_permission)

    def readiness(self) -> WorkflowActorAuthorizationReadiness:
        operator = self.operator.readiness()
        static = self.static.readiness()
        if not operator.ready:
            return operator
        if not static.ready:
            return static
        return WorkflowActorAuthorizationReadiness(
            ready=True,
            code="READY",
            detail="operator identity and static actor adapters configured",
        )
