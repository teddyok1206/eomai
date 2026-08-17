"""Persistence operations for Operator identity and RBAC."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from eom_operator_identity.contracts import (
    ROLE_PERMISSIONS,
    OperatorProjection,
    OperatorStatus,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.identifiers import (
    new_operator_event_id,
    new_permission_id,
    new_role_id,
)
from sqlalchemy import Select, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from eom_identity_service.models import (
    ApiSessionRecord,
    OperatorCredentialRecord,
    OperatorEventRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
    PermissionRecord,
    RolePermissionRecord,
    RoleRecord,
)

IDENTITY_INVARIANT_LOCK = 0x454F4D4150495630


def utc_now() -> datetime:
    return datetime.now(UTC)


def lock_identity_invariants(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(IDENTITY_INVARIANT_LOCK)))


def operator_by_username(
    session: Session, normalized_username: str, *, for_update: bool = False
) -> OperatorRecord | None:
    statement: Select[tuple[OperatorRecord]] = select(OperatorRecord).where(
        OperatorRecord.normalized_username == normalized_username
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def require_operator(
    session: Session, operator_id: str, *, for_update: bool = False
) -> OperatorRecord:
    statement: Select[tuple[OperatorRecord]] = select(OperatorRecord).where(
        OperatorRecord.operator_id == operator_id
    )
    if for_update:
        statement = statement.with_for_update()
    operator = session.scalar(statement)
    if operator is None:
        raise IdentityError(IdentityErrorCode.OPERATOR_NOT_FOUND, "operator not found")
    return operator


def require_credential(
    session: Session, operator_id: str, *, for_update: bool = False
) -> OperatorCredentialRecord:
    statement: Select[tuple[OperatorCredentialRecord]] = select(OperatorCredentialRecord).where(
        OperatorCredentialRecord.operator_id == operator_id
    )
    if for_update:
        statement = statement.with_for_update()
    credential = session.scalar(statement)
    if credential is None:
        raise IdentityError(IdentityErrorCode.OPERATOR_NOT_FOUND, "credential not found")
    return credential


def require_role(session: Session, role_key: RoleKey | str) -> RoleRecord:
    role = session.scalar(select(RoleRecord).where(RoleRecord.role_key == str(role_key)))
    if role is None:
        raise IdentityError(IdentityErrorCode.ROLE_NOT_FOUND, "role not found")
    return role


def active_role_assignments(
    session: Session, operator_id: str
) -> list[tuple[OperatorRoleAssignmentRecord, RoleRecord]]:
    return list(
        session.execute(
            select(OperatorRoleAssignmentRecord, RoleRecord)
            .join(RoleRecord, RoleRecord.role_id == OperatorRoleAssignmentRecord.role_id)
            .where(
                OperatorRoleAssignmentRecord.operator_id == operator_id,
                OperatorRoleAssignmentRecord.revoked_at.is_(None),
            )
            .order_by(RoleRecord.role_key)
        ).tuples()
    )


def effective_permissions(session: Session, operator_id: str) -> frozenset[PermissionKey]:
    keys = session.scalars(
        select(PermissionRecord.permission_key)
        .join(
            RolePermissionRecord,
            RolePermissionRecord.permission_id == PermissionRecord.permission_id,
        )
        .join(RoleRecord, RoleRecord.role_id == RolePermissionRecord.role_id)
        .join(
            OperatorRoleAssignmentRecord,
            OperatorRoleAssignmentRecord.role_id == RoleRecord.role_id,
        )
        .where(
            OperatorRoleAssignmentRecord.operator_id == operator_id,
            OperatorRoleAssignmentRecord.revoked_at.is_(None),
        )
        .distinct()
    )
    return frozenset(PermissionKey(key) for key in keys)


def active_admin_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(func.distinct(OperatorRecord.operator_id)))
            .join(
                OperatorRoleAssignmentRecord,
                OperatorRoleAssignmentRecord.operator_id == OperatorRecord.operator_id,
            )
            .join(RoleRecord, RoleRecord.role_id == OperatorRoleAssignmentRecord.role_id)
            .where(
                OperatorRecord.status == "ACTIVE",
                OperatorRoleAssignmentRecord.revoked_at.is_(None),
                RoleRecord.role_key == RoleKey.ADMIN.value,
            )
        )
        or 0
    )


def add_operator_event(
    session: Session,
    operator: OperatorRecord,
    *,
    event_type: str,
    actor_id: str,
    request_id: str,
    payload: dict[str, object],
    now: datetime | None = None,
) -> OperatorEventRecord:
    sequence = (
        int(
            session.scalar(
                select(func.coalesce(func.max(OperatorEventRecord.sequence), 0)).where(
                    OperatorEventRecord.operator_id == operator.operator_id
                )
            )
            or 0
        )
        + 1
    )
    event = OperatorEventRecord(
        operator_event_id=new_operator_event_id(),
        operator_id=operator.operator_id,
        sequence=sequence,
        event_type=event_type,
        actor_id=actor_id,
        request_id=request_id,
        payload=payload,
        created_at=now or utc_now(),
    )
    session.add(event)
    return event


def revoke_operator_sessions(
    session: Session,
    operator_id: str,
    *,
    actor_id: str,
    reason: str,
    except_session_id: str | None = None,
    now: datetime | None = None,
) -> int:
    timestamp = now or utc_now()
    statement = (
        update(ApiSessionRecord)
        .where(
            ApiSessionRecord.operator_id == operator_id,
            ApiSessionRecord.revoked_at.is_(None),
        )
        .values(
            revoked_at=timestamp,
            revoked_by=actor_id,
            revoke_reason=reason,
            lock_version=ApiSessionRecord.lock_version + 1,
        )
    )
    if except_session_id is not None:
        statement = statement.where(ApiSessionRecord.api_session_id != except_session_id)
    result = cast(CursorResult[tuple[Any, ...]], session.execute(statement))
    return int(result.rowcount or 0)


def operator_projection(session: Session, operator: OperatorRecord) -> OperatorProjection:
    credential = require_credential(session, operator.operator_id)
    assignments = active_role_assignments(session, operator.operator_id)
    roles = tuple(RoleKey(role.role_key) for _, role in assignments)
    permissions = tuple(sorted(effective_permissions(session, operator.operator_id), key=str))
    return OperatorProjection(
        operator_id=operator.operator_id,
        username=operator.username,
        display_name=operator.display_name,
        status=OperatorStatus(operator.status),
        must_change_password=credential.must_change_password,
        roles=roles,
        effective_permissions=permissions,
        resource_version=operator.lock_version,
        created_at=operator.created_at,
        updated_at=operator.updated_at,
        disabled_at=operator.disabled_at,
        disable_reason=operator.disable_reason,
        last_login_at=operator.last_login_at,
    )


def seed_builtin_rbac(session: Session) -> None:
    existing_roles = {record.role_key: record for record in session.scalars(select(RoleRecord))}
    existing_permissions = {
        record.permission_key: record for record in session.scalars(select(PermissionRecord))
    }
    for role_key in RoleKey:
        role = existing_roles.get(role_key.value)
        if role is None:
            role = RoleRecord(
                role_id=new_role_id(),
                role_key=role_key.value,
                display_name=role_key.value.title(),
                description=f"Built-in {role_key.value} role",
                built_in=True,
            )
            session.add(role)
            existing_roles[role_key.value] = role
        elif not role.built_in:
            raise IdentityError(IdentityErrorCode.ROLE_NOT_FOUND, "built-in role key conflict")
    for permission_key in PermissionKey:
        permission = existing_permissions.get(permission_key.value)
        if permission is None:
            permission = PermissionRecord(
                permission_id=new_permission_id(),
                permission_key=permission_key.value,
                description=f"Allows {permission_key.value}",
            )
            session.add(permission)
            existing_permissions[permission_key.value] = permission
    session.flush()

    existing_pairs = {
        (role_id, permission_id)
        for role_id, permission_id in session.execute(
            select(RolePermissionRecord.role_id, RolePermissionRecord.permission_id)
        )
    }
    expected_pairs = {
        (
            existing_roles[role_key.value].role_id,
            existing_permissions[permission.value].permission_id,
        )
        for role_key, permissions in ROLE_PERMISSIONS.items()
        for permission in permissions
    }
    built_in_role_ids = {existing_roles[key.value].role_id for key in RoleKey}
    unexpected = {pair for pair in existing_pairs if pair[0] in built_in_role_ids} - expected_pairs
    if unexpected:
        raise IdentityError(IdentityErrorCode.PERMISSION_NOT_FOUND, "built-in role matrix conflict")
    for role_id, permission_id in expected_pairs - existing_pairs:
        session.add(RolePermissionRecord(role_id=role_id, permission_id=permission_id))
