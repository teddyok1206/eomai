"""Infrastructure adapters for workflow human actor authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eom_identity_service.models import (
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity import OperatorStatus, PermissionKey, RoleKey
from eom_orchestrator.database import build_session_factory
from sqlalchemy import Engine, select

from eom_workflow_runner.actor_authorization import (
    OPERATOR_ACTOR_PATTERN,
    WORKFLOW_HUMAN_PERMISSIONS,
    WorkflowActorAuthorization,
    WorkflowActorAuthorizationReadiness,
    WorkflowActorDenialReason,
    WorkflowActorNamespace,
)
from eom_workflow_runner.settings import HumanActorConfig

ROLE_TO_WORKFLOW_ROLE = {
    RoleKey.AUTHOR: "requester",
    RoleKey.REVIEWER: "reviewer",
    RoleKey.ADMIN: "admin",
}
STATIC_ROLE_PERMISSIONS = {
    "requester": frozenset[PermissionKey](),
    "reviewer": frozenset(
        {
            PermissionKey.WORKFLOW_APPROVE,
            PermissionKey.WORKFLOW_REQUEST_REWORK,
        }
    ),
    "admin": WORKFLOW_HUMAN_PERMISSIONS,
}


@dataclass(frozen=True)
class OperatorActorSnapshot:
    operator_id: str
    status: OperatorStatus
    roles: frozenset[RoleKey]
    permissions: frozenset[PermissionKey]


class OperatorActorSource(Protocol):
    def load(self, operator_id: str) -> OperatorActorSnapshot | None: ...

    def readiness(self) -> WorkflowActorAuthorizationReadiness: ...


class SqlAlchemyOperatorActorSource:
    """Read current Operator state and permissions from the authoritative identity store."""

    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def load(self, operator_id: str) -> OperatorActorSnapshot | None:
        with self.sessions() as session:
            operator = session.get(OperatorRecord, operator_id)
            if operator is None:
                return None
            roles = frozenset(
                RoleKey(role.role_key)
                for _, role in active_role_assignments(session, operator.operator_id)
            )
            permissions = effective_permissions(session, operator.operator_id)
            return OperatorActorSnapshot(
                operator_id=operator.operator_id,
                status=OperatorStatus(operator.status),
                roles=roles,
                permissions=permissions,
            )

    def readiness(self) -> WorkflowActorAuthorizationReadiness:
        try:
            with self.sessions() as session:
                session.scalar(select(OperatorRecord.operator_id).limit(1))
                session.scalar(
                    select(OperatorRoleAssignmentRecord.operator_role_assignment_id).limit(1)
                )
                session.scalar(select(RolePermissionRecord.role_id).limit(1))
                roles = frozenset(
                    RoleKey(key)
                    for key in session.scalars(
                        select(RoleRecord.role_key).where(
                            RoleRecord.role_key.in_((RoleKey.REVIEWER.value, RoleKey.ADMIN.value))
                        )
                    )
                )
                available = frozenset(
                    PermissionKey(key)
                    for key in session.scalars(
                        select(PermissionRecord.permission_key).where(
                            PermissionRecord.permission_key.in_(
                                permission.value for permission in WORKFLOW_HUMAN_PERMISSIONS
                            )
                        )
                    )
                )
            if roles != frozenset({RoleKey.REVIEWER, RoleKey.ADMIN}):
                return WorkflowActorAuthorizationReadiness(
                    ready=False,
                    code="WORKFLOW_ACTOR_ROLE_CATALOG_INVALID",
                    detail="required workflow roles are unavailable",
                )
            if available != WORKFLOW_HUMAN_PERMISSIONS:
                return WorkflowActorAuthorizationReadiness(
                    ready=False,
                    code="WORKFLOW_ACTOR_PERMISSION_CATALOG_INVALID",
                    detail="required workflow permissions are unavailable",
                )
            return WorkflowActorAuthorizationReadiness(
                ready=True,
                code="READY",
                detail="operator identity repository and permission catalog readable",
            )
        except Exception as exc:
            return WorkflowActorAuthorizationReadiness(
                ready=False,
                code="WORKFLOW_ACTOR_IDENTITY_UNAVAILABLE",
                detail=type(exc).__name__,
            )


class OperatorIdentityWorkflowActorAuthorizer:
    def __init__(self, source: OperatorActorSource) -> None:
        self.source = source

    def authorize(
        self, actor_id: str, required_permission: PermissionKey
    ) -> WorkflowActorAuthorization:
        if OPERATOR_ACTOR_PATTERN.fullmatch(actor_id) is None:
            return self._denied(actor_id, WorkflowActorDenialReason.ACTOR_MALFORMED)
        try:
            snapshot = self.source.load(actor_id)
        except Exception:
            return self._denied(actor_id, WorkflowActorDenialReason.IDENTITY_BACKEND_UNAVAILABLE)
        if snapshot is None:
            return self._denied(actor_id, WorkflowActorDenialReason.ACTOR_UNKNOWN)
        if snapshot.status is not OperatorStatus.ACTIVE:
            return self._denied(actor_id, WorkflowActorDenialReason.ACTOR_DISABLED)
        roles = frozenset(
            ROLE_TO_WORKFLOW_ROLE[role] for role in snapshot.roles if role in ROLE_TO_WORKFLOW_ROLE
        )
        if required_permission not in snapshot.permissions:
            return WorkflowActorAuthorization(
                canonical_actor_id=snapshot.operator_id,
                namespace=WorkflowActorNamespace.OPERATOR_IDENTITY,
                authorized=False,
                capabilities=snapshot.permissions,
                workflow_roles=roles,
                denial_reason=WorkflowActorDenialReason.PERMISSION_ABSENT,
            )
        return WorkflowActorAuthorization(
            canonical_actor_id=snapshot.operator_id,
            namespace=WorkflowActorNamespace.OPERATOR_IDENTITY,
            authorized=True,
            capabilities=snapshot.permissions,
            workflow_roles=roles,
        )

    def readiness(self) -> WorkflowActorAuthorizationReadiness:
        return self.source.readiness()

    @staticmethod
    def _denied(actor_id: str, reason: WorkflowActorDenialReason) -> WorkflowActorAuthorization:
        return WorkflowActorAuthorization(
            canonical_actor_id=actor_id,
            namespace=WorkflowActorNamespace.OPERATOR_IDENTITY,
            authorized=False,
            capabilities=frozenset(),
            workflow_roles=frozenset(),
            denial_reason=reason,
        )


class StaticWorkflowActorAuthorizer:
    def __init__(self, config: HumanActorConfig) -> None:
        self.config = config
        self.roles_by_actor_id = {
            actor.actor_id: actor.role for actor in config.actors if actor.enabled
        }

    def authorize(
        self, actor_id: str, required_permission: PermissionKey
    ) -> WorkflowActorAuthorization:
        role = self.roles_by_actor_id.get(actor_id)
        if role is None:
            return WorkflowActorAuthorization(
                canonical_actor_id=actor_id,
                namespace=WorkflowActorNamespace.STATIC,
                authorized=False,
                capabilities=frozenset(),
                workflow_roles=frozenset(),
                denial_reason=WorkflowActorDenialReason.ACTOR_UNKNOWN,
            )
        capabilities = STATIC_ROLE_PERMISSIONS[role]
        authorized = required_permission in capabilities
        return WorkflowActorAuthorization(
            canonical_actor_id=actor_id,
            namespace=WorkflowActorNamespace.STATIC,
            authorized=authorized,
            capabilities=capabilities,
            workflow_roles=frozenset({role}),
            denial_reason=None if authorized else WorkflowActorDenialReason.PERMISSION_ABSENT,
        )

    def readiness(self) -> WorkflowActorAuthorizationReadiness:
        enabled_roles = frozenset(actor.role for actor in self.config.actors if actor.enabled)
        ready = {"requester", "reviewer", "admin"}.issubset(enabled_roles)
        return WorkflowActorAuthorizationReadiness(
            ready=ready,
            code="READY" if ready else "WORKFLOW_ACTOR_CONFIG_INVALID",
            detail=f"{len(self.config.actors)} static actors configured",
        )
