"""Existing private API socket adapter for shared content planning."""

from __future__ import annotations

import logging

from eom_catalog_contracts.application import CATALOG_APPLICATION_MAX_MESSAGE_BYTES
from eom_catalog_contracts.content_delivery import ContentDeliveryPrepared
from eom_catalog_contracts.content_planning_commands import ContentPlanningWriteResult
from eom_catalog_contracts.content_planning_queries import ContentPlanningQueryResult
from eom_catalog_contracts.content_planning_rpc import (
    CONTENT_PLANNING_OPERATIONS,
    ContentPlanningDeliveryRequest,
    ContentPlanningPrintRequest,
    ContentPlanningReply,
    ContentPlanningWriteRequest,
    parse_content_planning_reply,
    parse_content_planning_request,
)
from eom_catalog_contracts.content_print_commands import ContentPrintMutationResult
from eom_identifiers import canonical_json_bytes
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import ContentPlanningConflict
from eom_catalog_service.content_planning_service import ContentPlanningService
from eom_catalog_service.curated_document_assembly_item import CuratedDocumentAssemblyItemError
from eom_catalog_service.curated_document_assembly_source import CuratedDocumentAssemblySourceError

_LOG = logging.getLogger(__name__)


def dispatch_content_planning(
    service: ContentPlanningService | None, value: dict[str, object]
) -> bytes:
    operation = value.get("operation")
    if operation not in CONTENT_PLANNING_OPERATIONS:
        raise ValueError("unknown content operation")

    def failure(code: str) -> ContentPlanningReply:
        return ContentPlanningReply.model_validate(
            {"operation": operation, "status": "ERROR", "error_code": code}
        )

    try:
        request = parse_content_planning_request(value)
    except (ValueError, SchemaError):
        reply = failure("CONTENT_PLANNING_REQUEST_INVALID")
    else:
        if service is None:
            reply = failure("CATALOG_APPLICATION_UNAVAILABLE")
        else:
            actor = ActorContext(
                actor_type=ActorType.OPERATOR,
                operator_id=request.actor_id,
                session_id=request.session_id,
                request_id=request.request_id,
                authentication_time=request.authentication_time,
                permissions=frozenset(),
                source=ActorSource.APPLICATION_API,
            )
            try:
                result: (
                    ContentPlanningWriteResult
                    | ContentPlanningQueryResult
                    | ContentPrintMutationResult
                    | ContentDeliveryPrepared
                )
                if isinstance(request, ContentPlanningWriteRequest):
                    result = service.execute(
                        request.command, actor=actor, idempotency_key=request.idempotency_key
                    )
                elif isinstance(request, ContentPlanningPrintRequest):
                    result = service.prints.execute(
                        request.command, actor=actor, idempotency_key=request.idempotency_key
                    )
                elif isinstance(request, ContentPlanningDeliveryRequest):
                    result = service.deliveries.prepare(
                        request.command, actor=actor, idempotency_key=request.idempotency_key
                    )
                else:
                    result = service.query(request.query, actor=actor)
                reply = ContentPlanningReply(
                    operation=request.operation, status="OK", result=result
                )
            except (
                ContentPlanningError,
                ContentPlanningConflict,
                CuratedDocumentAssemblyItemError,
                CuratedDocumentAssemblySourceError,
            ) as exc:
                reply = failure(exc.code)
            except Exception as exc:
                _LOG.error(
                    "content planning failed operation=%s request_id=%s exception=%s",
                    operation,
                    request.request_id,
                    type(exc).__name__,
                )
                reply = failure("CATALOG_APPLICATION_INTERNAL_ERROR")
    parsed = parse_content_planning_reply(reply.model_dump(mode="json"))
    encoded = canonical_json_bytes(parsed.model_dump(mode="json")) + b"\n"
    if len(encoded) > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
        return (
            canonical_json_bytes(failure("CONTENT_RESULT_TOO_LARGE").model_dump(mode="json"))
            + b"\n"
        )
    return encoded
