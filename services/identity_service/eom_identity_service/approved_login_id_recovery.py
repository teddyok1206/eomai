"""Version-pinned, pair-only local recovery with temporary login-ID passwords."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_operator_identity.contracts import ActorContext, ActorSource, ActorType, OperatorStatus
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_operator_identity.passwords import PasswordService
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine

from eom_identity_service.local_admin_recovery import (
    OPERATOR_ID_PATTERN,
    RECOVERY_REQUEST_ID_PATTERN,
    LocalAdminRecoveryAuthorization,
    LocalAdminRecoveryAuthorizer,
)
from eom_identity_service.repository import (
    add_operator_event,
    lock_identity_invariants,
    require_credential,
    require_operator,
    revoke_operator_sessions,
    utc_now,
)

# One-use owner approval, independent of CLI input. These are opaque identity/version pins,
# not login names. Retire this exception per ADR 0186 after the approved recovery is complete.
APPROVED_PAIR_PINS = frozenset(
    {
        ("operator_9237daf1ce9ebad3098ef2372fb6ff91", 1),
        ("operator_21501765843779a7c3a13cd9afaf255b", 1),
    }
)


@dataclass(frozen=True)
class ApprovedRecoveryTarget:
    operator_id: str
    expected_resource_version: int

    def __post_init__(self) -> None:
        if OPERATOR_ID_PATTERN.fullmatch(self.operator_id) is None:
            raise ValueError("invalid approved Operator ID")
        if type(self.expected_resource_version) is not int or self.expected_resource_version < 1:
            raise ValueError("invalid approved Operator version")


@dataclass(frozen=True)
class ApprovedLoginIdPasswordResetCommand:
    targets: tuple[ApprovedRecoveryTarget, ApprovedRecoveryTarget]
    request_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.targets, tuple)
            or len(self.targets) != 2
            or any(not isinstance(target, ApprovedRecoveryTarget) for target in self.targets)
            or len({target.operator_id for target in self.targets}) != 2
        ):
            raise ValueError("exactly two distinct approved targets are required")
        if {
            (target.operator_id, target.expected_resource_version) for target in self.targets
        } != APPROVED_PAIR_PINS:
            raise ValueError("targets must match the original one-use owner approval")
        if RECOVERY_REQUEST_ID_PATTERN.fullmatch(self.request_id) is None:
            raise ValueError("invalid approved recovery request ID")


@dataclass(frozen=True)
class ApprovedLoginIdPasswordResetResult:
    operator_id: str
    resource_version: int
    password_version: int
    revoked_sessions: int
    reset_at: datetime
    must_change_password: bool


class ApprovedLoginIdPasswordRecoveryService:
    """One atomic reset of the exact locally approved version-pinned pair."""

    def __init__(
        self,
        engine: Engine,
        authorizer: LocalAdminRecoveryAuthorizer,
        passwords: PasswordService | None = None,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.authorizer = authorizer
        self.passwords = passwords or PasswordService()

    def reset_approved_pair(
        self, command: ApprovedLoginIdPasswordResetCommand
    ) -> tuple[ApprovedLoginIdPasswordResetResult, ...]:
        authorization = self.authorizer.authorize()
        if not isinstance(authorization, LocalAdminRecoveryAuthorization):
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "approved recovery requires trusted local authorization",
            )
        now = utc_now()
        actor = ActorContext(
            actor_type=ActorType.SYSTEM,
            operator_id=None,
            session_id=None,
            request_id=command.request_id,
            authentication_time=now,
            permissions=frozenset(),
            source=ActorSource.CLI,
        )
        results = []
        with transaction(self.sessions) as session:
            lock_identity_invariants(session)
            operators = []
            for target in sorted(command.targets, key=lambda value: value.operator_id):
                operator = require_operator(session, target.operator_id, for_update=True)
                if operator.status != OperatorStatus.ACTIVE.value:
                    raise IdentityError(IdentityErrorCode.OPERATOR_DISABLED, "operator is disabled")
                if operator.lock_version != target.expected_resource_version:
                    raise IdentityError(
                        IdentityErrorCode.OPERATOR_VERSION_CONFLICT,
                        "approved Operator version changed; do not replay the reset",
                    )
                credential = require_credential(session, target.operator_id, for_update=True)
                operators.append((operator, credential))
            # Both targets are validated and both hashes prepared before any state mutation.
            hashes = tuple(
                self.passwords.hash_temporary_login_id_password(username=operator.username)
                for operator, _ in operators
            )
            for (operator, credential), password_hash in zip(operators, hashes, strict=True):
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
                revoked = revoke_operator_sessions(
                    session,
                    operator.operator_id,
                    actor_id=actor.actor_id,
                    reason="APPROVED_LOGIN_ID_PASSWORD_RESET",
                    now=now,
                )
                add_operator_event(
                    session,
                    operator,
                    event_type="APPROVED_LOGIN_ID_PASSWORD_RESET",
                    actor_id=actor.actor_id,
                    request_id=command.request_id,
                    payload={
                        "actor_type": actor.actor_type.value,
                        "source": actor.source.value,
                        "os_principal": authorization.os_principal,
                        "os_uid": authorization.os_uid,
                        "os_gid": authorization.os_gid,
                        "password_version": credential.password_version,
                        "reason_code": "USER_APPROVED_TEMPORARY_LOGIN_ID_PAIR",
                        "revoked_sessions": revoked,
                        "must_change_password": True,
                    },
                    now=now,
                )
                results.append(
                    ApprovedLoginIdPasswordResetResult(
                        operator_id=operator.operator_id,
                        resource_version=operator.lock_version,
                        password_version=credential.password_version,
                        revoked_sessions=revoked,
                        reset_at=now,
                        must_change_password=True,
                    )
                )
            session.flush()
        return tuple(results)
