"""Current Identity permissions and owner-only access for private Kakao sources."""

from __future__ import annotations

from datetime import datetime

from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_identity_service.repository import active_role_assignments, effective_permissions
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class KakaoArchiveError(ValueError):
    """Content-free failure safe for the application error mapper."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def authorize_kakao_actor(
    session: Session,
    actor: ActorContext,
    permission: PermissionKey,
    *,
    now: datetime,
    admin_only: bool = False,
) -> str:
    """Actor comes from API authentication, never from a browser/worker authority claim.

    Re-read current Identity state through its existing repository; no credential or
    independent token verifier is created here. No IAM writes/locks are performed.
    """
    denied = "KAKAO_ARCHIVE_PERMISSION_DENIED"
    if (
        actor.actor_type is not ActorType.OPERATOR
        or actor.source is not ActorSource.APPLICATION_API
        or actor.operator_id is None
        or actor.session_id is None
    ):
        raise KakaoArchiveError(denied)
    return authorize_kakao_identity_session(
        session,
        operator_id=actor.operator_id,
        identity_session_id=actor.session_id,
        permission=permission,
        now=now,
        admin_only=admin_only,
    )


def authorize_kakao_identity_session(
    session: Session,
    *,
    operator_id: str,
    identity_session_id: str,
    permission: PermissionKey,
    now: datetime,
    admin_only: bool = False,
) -> str:
    """Current lookup for a previously accepted owner intent, not request authentication.

    Application callers first use authorize_kakao_actor. Background callers may pass
    only IDs pinned in their own accepted intent, never arbitrary browser/worker IDs.
    No token, ActorSource or synthetic authenticated HTTP context is created here.
    """
    denied = "KAKAO_ARCHIVE_PERMISSION_DENIED"
    operator = session.get(OperatorRecord, operator_id, populate_existing=True)
    api_session = session.execute(
        select(
            ApiSessionRecord.operator_id,
            ApiSessionRecord.revoked_at,
            ApiSessionRecord.absolute_expires_at,
            ApiSessionRecord.idle_expires_at,
        ).where(ApiSessionRecord.api_session_id == identity_session_id)
    ).one_or_none()
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
        or api_session is None
        or api_session.operator_id != operator.operator_id
        or api_session.revoked_at is not None
        or api_session.absolute_expires_at <= now
        or api_session.idle_expires_at <= now
        or permission not in effective_permissions(session, operator.operator_id)
        or (
            admin_only
            and not any(
                role.role_key == RoleKey.ADMIN
                for _, role in active_role_assignments(session, operator.operator_id)
            )
        )
    ):
        raise KakaoArchiveError(denied)
    return operator.operator_id
