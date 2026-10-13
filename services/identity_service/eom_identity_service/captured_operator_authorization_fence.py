"""Adapt an actual Identity session capture to the existing Catalog owner interface."""

from __future__ import annotations

from dataclasses import dataclass

from eom_operator_identity.contracts import PermissionKey
from sqlalchemy.orm import Session

from eom_identity_service.authenticated_session_fence import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
)
from eom_identity_service.operator_authorization_fence_sql import OperatorAuthorizationFenceError


@dataclass(frozen=True, slots=True)
class CapturedOperatorAuthorizationFence:
    """No capture minting or cached grant; every call fences the actual caller root.

    Trusted composition supplies a capture from the supported Identity provider.
    Catalog still checks its current source/read/publish permissions and policy.
    """

    capture: AuthenticatedOperatorSession
    fence: AuthenticatedSessionFence
    required_permission: PermissionKey

    def __post_init__(self) -> None:
        if (
            type(self.capture) is not AuthenticatedOperatorSession
            or type(self.fence) is not AuthenticatedSessionFence
            or type(self.required_permission) is not PermissionKey
        ):
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_CONFIGURATION_INVALID"
            )

    def fence_current_operator(self, session: Session, operator_id: str) -> None:
        try:
            if operator_id != self.capture.operator_id:
                raise OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
            self.fence.assert_current(
                session, self.capture, required_permission=self.required_permission
            )
        except AuthenticatedSessionFenceError as exc:
            if exc.code == "AUTHENTICATED_SESSION_FORBIDDEN":
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                ) from None
            if exc.code == "AUTHENTICATED_SESSION_CONTEXT_INVALID":
                raise OperatorAuthorizationFenceError(
                    "OPERATOR_AUTHORIZATION_FENCE_CONTEXT_INVALID"
                ) from None
            raise OperatorAuthorizationFenceError(
                "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"
            ) from None
