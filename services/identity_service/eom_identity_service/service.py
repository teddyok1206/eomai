"""Operator management application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    OperatorProjection,
    OperatorStatus,
    PermissionKey,
    RoleKey,
    normalize_username,
    validate_display_name,
    validate_username,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.identifiers import (
    new_credential_id,
    new_operator_id,
    new_role_assignment_id,
)
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select

from eom_identity_service.models import (
    OperatorCredentialRecord,
    OperatorRecord,
    OperatorRoleAssignmentRecord,
)
from eom_identity_service.repository import (
    active_admin_count,
    active_role_assignments,
    add_operator_event,
    effective_permissions,
    lock_identity_invariants,
    operator_by_username,
    operator_projection,
    require_operator,
    require_role,
    revoke_operator_sessions,
    seed_builtin_rbac,
    utc_now,
)


@dataclass(frozen=True)
class BootstrapResult:
    operator: OperatorProjection
    temporary_password: str


@dataclass(frozen=True)
class CreateOperatorCommand:
    username: str
    display_name: str
    temporary_password: str
    initial_roles: tuple[RoleKey, ...]


class OperatorService:
    def __init__(self, engine: Engine, passwords: PasswordService | None = None) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.passwords = passwords or PasswordService()

    def bootstrap_admin(self, *, username: str, display_name: str) -> BootstrapResult:
        validate_username(username)
        validate_display_name(display_name)
        temporary_password = self.passwords.generate_temporary_password()
        with transaction(self.sessions) as session:
            lock_identity_invariants(session)
            seed_builtin_rbac(session)
            if int(session.scalar(select(OperatorRecord).limit(1)) is not None):
                raise IdentityError(
                    IdentityErrorCode.OPERATOR_USERNAME_CONFLICT,
                    "bootstrap is allowed only before the first Operator",
                )
            actor = ActorContext(
                actor_type=ActorType.SYSTEM,
                operator_id=None,
                session_id=None,
                request_id="bootstrap-admin",
                authentication_time=datetime.now(UTC),
                permissions=frozenset(PermissionKey),
                source=ActorSource.CLI,
            )
            operator = self._create(
                session,
                CreateOperatorCommand(
                    username=username,
                    display_name=display_name,
                    temporary_password=temporary_password,
                    initial_roles=(RoleKey.ADMIN,),
                ),
                actor,
            )
            projection = operator_projection(session, operator)
        return BootstrapResult(projection, temporary_password)

    def create_operator(
        self, command: CreateOperatorCommand, actor: ActorContext
    ) -> OperatorProjection:
        with transaction(self.sessions) as session:
            self._require_admin(session, actor)
            operator = self._create(session, command, actor)
            return operator_projection(session, operator)

    def list_operators(self, *, limit: int = 200) -> list[OperatorProjection]:
        with self.sessions() as session:
            records = list(
                session.scalars(
                    select(OperatorRecord)
                    .order_by(OperatorRecord.created_at, OperatorRecord.operator_id)
                    .limit(limit)
                )
            )
            return [operator_projection(session, operator) for operator in records]

    def inspect_operator(self, operator_id: str) -> OperatorProjection:
        with self.sessions() as session:
            return operator_projection(session, require_operator(session, operator_id))

    def assign_role(
        self, operator_id: str, role_key: RoleKey, actor: ActorContext
    ) -> OperatorProjection:
        with transaction(self.sessions) as session:
            self._require_admin(session, actor)
            operator = require_operator(session, operator_id, for_update=True)
            role = require_role(session, role_key)
            if any(
                record.role_id == role.role_id
                for record, _ in active_role_assignments(session, operator_id)
            ):
                raise IdentityError(
                    IdentityErrorCode.OPERATOR_ROLE_ALREADY_ASSIGNED,
                    "role is already assigned",
                )
            now = utc_now()
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id=new_role_assignment_id(),
                    operator_id=operator_id,
                    role_id=role.role_id,
                    assigned_by=actor.actor_id,
                    assigned_at=now,
                )
            )
            operator.role_version += 1
            operator.lock_version += 1
            self._event(
                session, operator, "ROLE_ASSIGNED", actor, {"role_key": role_key.value}, now
            )
            session.flush()
            return operator_projection(session, operator)

    def revoke_role(
        self,
        operator_id: str,
        role_key: RoleKey,
        actor: ActorContext,
        *,
        reason: str,
    ) -> OperatorProjection:
        if not reason or len(reason) > 1000:
            raise ValueError("role revocation reason is required")
        with transaction(self.sessions) as session:
            lock_identity_invariants(session)
            self._require_admin(session, actor)
            operator = require_operator(session, operator_id, for_update=True)
            role = require_role(session, role_key)
            assignment = next(
                (
                    record
                    for record, assigned_role in active_role_assignments(session, operator_id)
                    if assigned_role.role_id == role.role_id
                ),
                None,
            )
            if assignment is None:
                raise IdentityError(
                    IdentityErrorCode.OPERATOR_ROLE_NOT_ASSIGNED,
                    "role is not assigned",
                )
            if (
                role_key is RoleKey.ADMIN
                and operator.status == OperatorStatus.ACTIVE.value
                and active_admin_count(session) <= 1
            ):
                raise IdentityError(IdentityErrorCode.OPERATOR_LAST_ADMIN, "last admin is required")
            now = utc_now()
            assignment.revoked_by = actor.actor_id
            assignment.revoked_at = now
            assignment.revoke_reason = reason
            operator.role_version += 1
            operator.lock_version += 1
            self._event(session, operator, "ROLE_REVOKED", actor, {"role_key": role_key.value}, now)
            session.flush()
            return operator_projection(session, operator)

    def disable(self, operator_id: str, actor: ActorContext, *, reason: str) -> OperatorProjection:
        if not reason or len(reason) > 1000:
            raise ValueError("disable reason is required")
        with transaction(self.sessions) as session:
            lock_identity_invariants(session)
            self._require_admin(session, actor)
            operator = require_operator(session, operator_id, for_update=True)
            if operator.status == OperatorStatus.DISABLED.value:
                return operator_projection(session, operator)
            has_admin = any(
                role.role_key == RoleKey.ADMIN.value
                for _, role in active_role_assignments(session, operator_id)
            )
            if has_admin and active_admin_count(session) <= 1:
                raise IdentityError(IdentityErrorCode.OPERATOR_LAST_ADMIN, "last admin is required")
            now = utc_now()
            operator.status = OperatorStatus.DISABLED.value
            operator.disabled_at = now
            operator.disabled_by = actor.actor_id
            operator.disable_reason = reason
            operator.lock_version += 1
            revoke_operator_sessions(
                session,
                operator_id,
                actor_id=actor.actor_id,
                reason="OPERATOR_DISABLED",
                now=now,
            )
            self._event(session, operator, "OPERATOR_DISABLED", actor, {"reason": reason}, now)
            session.flush()
            return operator_projection(session, operator)

    def enable(self, operator_id: str, actor: ActorContext) -> OperatorProjection:
        with transaction(self.sessions) as session:
            self._require_admin(session, actor)
            operator = require_operator(session, operator_id, for_update=True)
            if operator.status == OperatorStatus.ACTIVE.value:
                return operator_projection(session, operator)
            now = utc_now()
            operator.status = OperatorStatus.ACTIVE.value
            operator.disabled_at = None
            operator.disabled_by = None
            operator.disable_reason = None
            operator.lock_version += 1
            self._event(session, operator, "OPERATOR_ENABLED", actor, {}, now)
            session.flush()
            return operator_projection(session, operator)

    def revoke_sessions(self, operator_id: str, actor: ActorContext) -> int:
        with transaction(self.sessions) as session:
            self._require_admin(session, actor)
            operator = require_operator(session, operator_id, for_update=True)
            count = revoke_operator_sessions(
                session,
                operator_id,
                actor_id=actor.actor_id,
                reason="ADMIN_REVOKED_SESSIONS",
            )
            self._event(session, operator, "SESSIONS_REVOKED", actor, {"count": count}, utc_now())
            return count

    def _create(
        self, session: object, command: CreateOperatorCommand, actor: ActorContext
    ) -> OperatorRecord:
        # SQLAlchemy's Session type is kept at this service boundary for transaction ownership.
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        username = validate_username(command.username)
        display_name = validate_display_name(command.display_name)
        normalized = normalize_username(username)
        if operator_by_username(session, normalized) is not None:
            raise IdentityError(
                IdentityErrorCode.OPERATOR_USERNAME_CONFLICT,
                "username already exists",
            )
        password_hash = self.passwords.hash_password(
            command.temporary_password,
            username=username,
            display_name=display_name,
        )
        now = utc_now()
        operator = OperatorRecord(
            operator_id=new_operator_id(),
            username=username,
            normalized_username=normalized,
            display_name=display_name,
            status=OperatorStatus.ACTIVE.value,
            must_change_password=True,
            role_version=1,
            created_by=actor.actor_id,
            lock_version=1,
        )
        session.add(operator)
        session.flush()
        session.add(
            OperatorCredentialRecord(
                operator_credential_id=new_credential_id(),
                operator_id=operator.operator_id,
                password_hash=password_hash,
                password_algorithm="argon2id",
                password_version=1,
                must_change_password=True,
                password_changed_at=now,
                failed_login_count=0,
            )
        )
        roles = tuple(dict.fromkeys(command.initial_roles))
        for role_key in roles:
            role = require_role(session, role_key)
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id=new_role_assignment_id(),
                    operator_id=operator.operator_id,
                    role_id=role.role_id,
                    assigned_by=actor.actor_id,
                    assigned_at=now,
                )
            )
        self._event(
            session,
            operator,
            "OPERATOR_CREATED",
            actor,
            {"initial_roles": [role.value for role in roles]},
            now,
        )
        session.flush()
        return operator

    @staticmethod
    def _event(
        session: object,
        operator: OperatorRecord,
        event_type: str,
        actor: ActorContext,
        payload: dict[str, object],
        now: datetime,
    ) -> None:
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        add_operator_event(
            session,
            operator,
            event_type=event_type,
            actor_id=actor.actor_id,
            request_id=actor.request_id,
            payload={
                "actor_type": actor.actor_type.value,
                "source": actor.source.value,
                **payload,
            },
            now=now,
        )

    @staticmethod
    def _require_admin(session: object, actor: ActorContext) -> None:
        from sqlalchemy.orm import Session

        assert isinstance(session, Session)
        if actor.operator_id is None:
            raise IdentityError(IdentityErrorCode.OPERATOR_DISABLED, "operator actor is required")
        operator = require_operator(session, actor.operator_id)
        if operator.status != OperatorStatus.ACTIVE.value:
            raise IdentityError(IdentityErrorCode.OPERATOR_DISABLED, "operator is disabled")
        if PermissionKey.OPERATOR_CREATE not in effective_permissions(session, actor.operator_id):
            raise IdentityError(IdentityErrorCode.OPERATOR_DISABLED, "admin role is required")
