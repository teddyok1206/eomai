"""Actual operator authorization for shared content, not private assembly ownership."""

from __future__ import annotations

from eom_identity_service.models import OperatorRecord
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from sqlalchemy.orm import Session


class ContentPlanningError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def authorize_content_planning(
    session: Session, actor: ActorContext, permission: PermissionKey
) -> ActorContext:
    """Fresh RBAC from the authenticated API identity; no creator impersonation."""
    if (
        actor.actor_type is not ActorType.OPERATOR
        or actor.source is not ActorSource.APPLICATION_API
        or actor.operator_id is None
        or actor.session_id is None
    ):
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    operator = session.get(OperatorRecord, actor.operator_id)
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
    ):
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    permissions = effective_permissions(session, actor.operator_id)
    if not {permission, PermissionKey.DELIVERABLE_READ, PermissionKey.ITEM_READ} <= permissions:
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    return actor.model_copy(update={"permissions": permissions})
