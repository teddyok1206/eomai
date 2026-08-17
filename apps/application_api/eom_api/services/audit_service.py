"""Append-only HTTP and security audit adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_identity_service.models import ApiAuditEventRecord
from eom_operator_identity.identifiers import new_api_audit_event_id
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine

from eom_api.request_context import RequestContext


class AuditService:
    def __init__(self, engine: Engine) -> None:
        self.sessions = build_session_factory(engine)

    def append(
        self,
        context: RequestContext,
        *,
        event_type: str,
        operation_id: str,
        outcome: str,
        http_status: int,
        error_code: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> None:
        authentication = context.authentication
        with transaction(self.sessions) as session:
            session.add(
                ApiAuditEventRecord(
                    api_audit_event_id=new_api_audit_event_id(),
                    request_id=context.request_id,
                    operator_id=(
                        authentication.operator.operator_id if authentication is not None else None
                    ),
                    api_session_id=(
                        authentication.session_id if authentication is not None else None
                    ),
                    event_type=event_type,
                    operation_id=operation_id,
                    http_method=context.method,
                    route_template=context.route_template,
                    target_type=target_type,
                    target_id=target_id,
                    outcome=outcome,
                    http_status=http_status,
                    error_code=error_code,
                    client_name=context.client_name,
                    source_address_hash=context.source_address_hash,
                    user_agent_hash=context.user_agent_hash,
                    created_at=datetime.now(UTC),
                )
            )
