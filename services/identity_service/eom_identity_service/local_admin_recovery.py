"""Audited application boundary for local Administrator credential recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    OperatorStatus,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine

from eom_identity_service.repository import (
    active_role_assignments,
    add_operator_event,
    lock_identity_invariants,
    require_credential,
    require_operator,
    revoke_operator_sessions,
    utc_now,
)

OPERATOR_ID_PATTERN = re.compile(r"^operator_[0-9a-f]{32}$")
RECOVERY_REQUEST_ID_PATTERN = re.compile(r"^cli_[0-9a-f]{24}$")


class EmergencyAdminPasswordResetReason(StrEnum):
    """Closed, non-secret reason codes allowed in the append-only event."""

    ADMIN_CREDENTIAL_LOSS = "ADMIN_CREDENTIAL_LOSS"


@dataclass(frozen=True)
class LocalAdminRecoveryAuthorization:
    """Identity returned by the trusted local OS authorization adapter."""

    os_principal: str
    os_uid: int
    os_gid: int

    def __post_init__(self) -> None:
        if self.os_principal != "eom" or self.os_uid <= 0 or self.os_gid <= 0:
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "emergency password reset requires the local eom principal",
            )


class LocalAdminRecoveryAuthorizer(Protocol):
    """Port implemented only by the trusted local CLI adapter."""

    def authorize(self) -> LocalAdminRecoveryAuthorization: ...


@dataclass(frozen=True)
class EmergencyAdminPasswordResetCommand:
    operator_id: str
    temporary_password: str = field(repr=False)
    reason_code: EmergencyAdminPasswordResetReason
    request_id: str

    def __post_init__(self) -> None:
        if OPERATOR_ID_PATTERN.fullmatch(self.operator_id) is None:
            raise ValueError("emergency password reset Operator ID is invalid")
        if not isinstance(self.reason_code, EmergencyAdminPasswordResetReason):
            raise ValueError("emergency password reset reason code is invalid")
        if RECOVERY_REQUEST_ID_PATTERN.fullmatch(self.request_id) is None:
            raise ValueError("emergency password reset request ID is invalid")


@dataclass(frozen=True)
class EmergencyAdminPasswordResetResult:
    operator_id: str
    password_version: int
    revoked_sessions: int
    reset_at: datetime
    must_change_password: bool


class LocalAdminPasswordRecoveryService:
    """Reset one active Administrator after the injected OS adapter authorizes the call."""

    def __init__(
        self,
        engine: Engine,
        authorizer: LocalAdminRecoveryAuthorizer,
        passwords: PasswordService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.authorizer = authorizer
        self.passwords = passwords or PasswordService()

    def reset_admin_password(
        self, command: EmergencyAdminPasswordResetCommand
    ) -> EmergencyAdminPasswordResetResult:
        authorization = self.authorizer.authorize()
        if not isinstance(authorization, LocalAdminRecoveryAuthorization):
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "local recovery authorization adapter returned an invalid result",
            )
        actor = ActorContext(
            actor_type=ActorType.SYSTEM,
            operator_id=None,
            session_id=None,
            request_id=command.request_id,
            authentication_time=datetime.now(UTC),
            permissions=frozenset(),
            source=ActorSource.CLI,
        )
        with transaction(self.sessions) as session:
            # Serialize role membership with the target and credential locks so the ADMIN gate,
            # credential replacement, session revocation, and audit sequence commit atomically.
            lock_identity_invariants(session)
            operator = require_operator(session, command.operator_id, for_update=True)
            if operator.status != OperatorStatus.ACTIVE.value:
                raise IdentityError(IdentityErrorCode.OPERATOR_DISABLED, "operator is disabled")
            if not any(
                role.role_key == RoleKey.ADMIN.value
                for _, role in active_role_assignments(session, operator.operator_id)
            ):
                raise IdentityError(
                    IdentityErrorCode.OPERATOR_ADMIN_REQUIRED,
                    "emergency password reset target must be an active Administrator",
                )
            credential = require_credential(session, operator.operator_id, for_update=True)
            password_hash = self.passwords.hash_password(
                command.temporary_password,
                username=operator.username,
                display_name=operator.display_name,
            )
            now = utc_now()
            credential.password_hash = password_hash
            credential.password_algorithm = "argon2id"
            credential.password_version += 1
            credential.must_change_password = True
            credential.password_changed_at = now
            credential.failed_login_count = 0
            credential.first_failed_at = None
            credential.last_failed_at = None
            credential.locked_until = None
            operator.must_change_password = True
            operator.lock_version += 1
            revoked_sessions = revoke_operator_sessions(
                session,
                operator.operator_id,
                actor_id=actor.actor_id,
                reason="EMERGENCY_PASSWORD_RESET",
                now=now,
            )
            add_operator_event(
                session,
                operator,
                event_type="EMERGENCY_PASSWORD_RESET",
                actor_id=actor.actor_id,
                request_id=actor.request_id,
                payload={
                    "actor_type": actor.actor_type.value,
                    "source": actor.source.value,
                    "os_principal": authorization.os_principal,
                    "os_uid": authorization.os_uid,
                    "os_gid": authorization.os_gid,
                    "password_version": credential.password_version,
                    "reason_code": command.reason_code.value,
                    "revoked_sessions": revoked_sessions,
                },
                now=now,
            )
            session.flush()
            return EmergencyAdminPasswordResetResult(
                operator_id=operator.operator_id,
                password_version=credential.password_version,
                revoked_sessions=revoked_sessions,
                reset_at=now,
                must_change_password=True,
            )


__all__ = [
    "EmergencyAdminPasswordResetCommand",
    "EmergencyAdminPasswordResetReason",
    "EmergencyAdminPasswordResetResult",
    "LocalAdminPasswordRecoveryService",
    "LocalAdminRecoveryAuthorization",
    "LocalAdminRecoveryAuthorizer",
]
