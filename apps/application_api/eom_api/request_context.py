"""Per-request security and actor context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from eom_identity_service import AuthenticatedOperatorSession
from eom_identity_service.tokens import AccessAuthentication, AuthenticatedAccess
from eom_operator_identity import ActorContext, ActorSource, ActorType


@dataclass
class RequestContext:
    request_id: str
    started_at: datetime
    route_template: str
    method: str
    client_name: str | None
    source_address_hash: str | None
    user_agent_hash: str | None
    authentication: AccessAuthentication | None = None
    authenticated_access: AuthenticatedAccess | None = field(default=None, repr=False)

    def owner_capture(self) -> AuthenticatedOperatorSession:
        """Only the current request's real Identity pair, not its actor projection."""
        value = self.authenticated_access
        if (
            type(value) is not AuthenticatedAccess
            or self.authentication is not value.authentication
            or type(value.capture) is not AuthenticatedOperatorSession
            or value.capture.operator_id != value.authentication.operator.operator_id
        ):
            raise RuntimeError("OWNER_SESSION_REQUEST_CAPTURE_UNAVAILABLE")
        return value.capture

    def actor(self) -> ActorContext:
        if self.authentication is None:
            raise RuntimeError("request is not authenticated")
        authentication = self.authentication
        return ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=authentication.operator.operator_id,
            session_id=authentication.session_id,
            request_id=self.request_id,
            authentication_time=authentication.authenticated_at,
            permissions=authentication.permissions,
            source=ActorSource.APPLICATION_API,
        )
