"""Per-request security and actor context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_identity_service.tokens import AccessAuthentication
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
