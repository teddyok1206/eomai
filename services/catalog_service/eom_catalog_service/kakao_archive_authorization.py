"""Current Identity permissions and owner-only access for private Kakao sources."""

from __future__ import annotations

from datetime import UTC, datetime

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

from eom_catalog_service.kakao_archive_models import KakaoChannelBindingRecord
from eom_catalog_service.kakao_room_models import KakaoRoomRecord


class KakaoArchiveError(ValueError):
    """Content-free failure safe for the application error mapper."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def authorize_kakao_binding_scope(
    session: Session,
    actor: ActorContext,
    binding_id: str,
    permission: PermissionKey,
    *,
    lock: bool,
) -> tuple[str, KakaoChannelBindingRecord]:
    """Metadata-only accepted-content access; finish the transaction before I/O."""
    owner = authorize_kakao_actor(session, actor, permission, now=datetime.now(UTC))
    binding_query = select(KakaoChannelBindingRecord).where(
        KakaoChannelBindingRecord.source_binding_id == binding_id,
        KakaoChannelBindingRecord.owner_operator_id == owner,
    )
    binding = session.scalar(binding_query.with_for_update() if lock else binding_query)
    if binding is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    if binding.state == "RETIRED":
        raise KakaoArchiveError("KAKAO_ARCHIVE_BINDING_RETIRED")
    return owner, binding


def authorize_kakao_room_scope(
    session: Session,
    actor: ActorContext,
    binding_id: str,
    room_id: str,
    permission: PermissionKey,
    *,
    lock: bool,
) -> tuple[str, KakaoRoomRecord]:
    """Same owner/lifecycle and binding→room lock order for source and question work."""
    owner, _ = authorize_kakao_binding_scope(session, actor, binding_id, permission, lock=lock)
    room_query = select(KakaoRoomRecord).where(
        KakaoRoomRecord.room_id == room_id,
        KakaoRoomRecord.source_binding_id == binding_id,
        KakaoRoomRecord.owner_operator_id == owner,
    )
    room = session.scalar(room_query.with_for_update() if lock else room_query)
    if room is None:
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    if room.state != "ACTIVE":
        raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
    return owner, room


def authorize_kakao_room_scopes(
    session: Session,
    actor: ActorContext,
    binding_id: str,
    room_ids: tuple[str, ...],
    permission: PermissionKey,
) -> str:
    """Bounded read scope for an actual multi-room packet; one indexed room query."""
    owner, _ = authorize_kakao_binding_scope(session, actor, binding_id, permission, lock=False)
    identities = set(room_ids)
    if not identities or len(identities) > 200:
        raise KakaoArchiveError("KAKAO_ARCHIVE_REQUEST_INVALID")
    rooms = tuple(
        session.scalars(
            select(KakaoRoomRecord).where(
                KakaoRoomRecord.owner_operator_id == owner,
                KakaoRoomRecord.source_binding_id == binding_id,
                KakaoRoomRecord.room_id.in_(identities),
            )
        )
    )
    if len(rooms) != len(identities):
        raise KakaoArchiveError("KAKAO_ARCHIVE_RESOURCE_NOT_FOUND")
    if any(room.state != "ACTIVE" for room in rooms):
        raise KakaoArchiveError("KAKAO_ARCHIVE_ROOM_RETIRED")
    return owner


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
    owner = authorize_kakao_current_operator(
        session, operator_id=operator_id, permission=permission, admin_only=admin_only
    )
    api_session = session.execute(
        select(
            ApiSessionRecord.operator_id,
            ApiSessionRecord.revoked_at,
            ApiSessionRecord.absolute_expires_at,
            ApiSessionRecord.idle_expires_at,
        ).where(ApiSessionRecord.api_session_id == identity_session_id)
    ).one_or_none()
    if (
        api_session is None
        or api_session.operator_id != owner
        or api_session.revoked_at is not None
        or api_session.absolute_expires_at <= now
        or api_session.idle_expires_at <= now
    ):
        raise KakaoArchiveError(denied)
    return owner


def authorize_kakao_current_operator(
    session: Session,
    *,
    operator_id: str,
    permission: PermissionKey,
    admin_only: bool = False,
) -> str:
    """Current Identity predicate, not request authentication or an execution grant.

    Background owners must obtain this ID from their own accepted DB intent, not
    from a caller/worker. Public requests still require authorize_kakao_actor.
    """
    operator = session.get(OperatorRecord, operator_id, populate_existing=True)
    if (
        operator is None
        or operator.status != "ACTIVE"
        or operator.deleted_at is not None
        or operator.must_change_password
        or permission not in effective_permissions(session, operator.operator_id)
        or (
            admin_only
            and not any(
                role.role_key == RoleKey.ADMIN
                for _, role in active_role_assignments(session, operator.operator_id)
            )
        )
    ):
        raise KakaoArchiveError("KAKAO_ARCHIVE_PERMISSION_DENIED")
    return operator.operator_id
