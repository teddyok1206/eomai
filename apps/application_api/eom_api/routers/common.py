"""Router response and idempotent-command helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eom_api_contracts import CommandResult, ListResponse, PageMeta, ResponseMeta, SingleResponse
from fastapi import Request

from eom_api.request_context import RequestContext


def context(request: Request) -> RequestContext:
    value: RequestContext = request.state.request_context
    return value


def one(request: Request, data: Any) -> SingleResponse[Any]:
    return SingleResponse(data=data, meta=ResponseMeta(request_id=context(request).request_id))


def many(
    request: Request,
    data: tuple[Any, ...],
    *,
    limit: int,
    next_cursor: str | None = None,
    has_more: bool = False,
) -> ListResponse[Any]:
    return ListResponse(
        data=data,
        page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        meta=ResponseMeta(request_id=context(request).request_id),
    )


def run_command(
    request: Request,
    *,
    raw_key: str,
    body: dict[str, Any] | None,
    resource_type: str,
    callback: Callable[[], CommandResult],
    response_status: int = 200,
) -> CommandResult:
    request_context = context(request)
    authentication = request_context.authentication
    if authentication is None:
        raise RuntimeError("idempotent command requires authentication")
    operation_id = getattr(request.scope.get("route"), "operation_id", "unknown")
    services = request.app.state.services
    request_hash = services.idempotency.request_hash(
        method=request.method,
        operation_id=operation_id,
        path_parameters=dict(request.path_params),
        body=body,
        operator_id=authentication.operator.operator_id,
    )
    try:
        claim = services.idempotency.claim(
            operator_id=authentication.operator.operator_id,
            endpoint_key=operation_id,
            raw_key=raw_key,
            request_sha256=request_hash,
            lease_owner=request_context.request_id,
        )
    except Exception as exc:
        error_code = getattr(exc, "error_code", "API_IDEMPOTENCY_CONFLICT")
        services.audit.append(
            request_context,
            event_type="IDEMPOTENCY_CONFLICT",
            operation_id=operation_id,
            outcome="DENIED",
            http_status=getattr(exc, "status", 409),
            error_code=str(error_code),
            target_type=resource_type,
        )
        raise
    if claim.replayed:
        assert claim.replay_body is not None
        services.audit.append(
            request_context,
            event_type="IDEMPOTENCY_REPLAY",
            operation_id=operation_id,
            outcome="REPLAYED",
            http_status=claim.replay_status or response_status,
            target_type=resource_type,
            target_id=claim.replay_body.get("resource_id"),
        )
        return CommandResult.model_validate(claim.replay_body)
    services.audit.append(
        request_context,
        event_type="DOMAIN_COMMAND_SUBMITTED",
        operation_id=operation_id,
        outcome="SUBMITTED",
        http_status=202,
        target_type=resource_type,
    )
    try:
        result = callback()
    except Exception as exc:
        error_code = getattr(getattr(exc, "code", None), "value", None) or getattr(
            exc, "error_code", "DOMAIN_COMMAND_FAILED"
        )
        services.idempotency.fail_final(claim, str(error_code))
        services.audit.append(
            request_context,
            event_type="DOMAIN_COMMAND_FAILED",
            operation_id=operation_id,
            outcome="FAILED",
            http_status=getattr(exc, "status", 409),
            error_code=str(error_code),
            target_type=resource_type,
        )
        raise
    payload = result.model_dump(mode="json")
    services.idempotency.complete(
        claim,
        status=response_status,
        body=payload,
        resource_type=resource_type,
        resource_id=result.resource_id,
    )
    services.audit.append(
        request_context,
        event_type="DOMAIN_COMMAND_SUCCEEDED",
        operation_id=operation_id,
        outcome="SUCCEEDED",
        http_status=response_status,
        target_type=resource_type,
        target_id=result.resource_id,
    )
    return result
