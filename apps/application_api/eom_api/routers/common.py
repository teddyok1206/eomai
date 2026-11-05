"""Router response and idempotent-command helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eom_api_contracts import CommandResult, ListResponse, PageMeta, ResponseMeta, SingleResponse
from eom_identity_service.service import OperatorService
from fastapi import Request

from eom_api.request_context import RequestContext
from eom_api.services.idempotency_service import IdempotencyClaim


def _domain_error_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    enum_value = getattr(code, "value", None)
    if isinstance(enum_value, str) and enum_value:
        return enum_value
    if isinstance(code, str) and code:
        return code
    error_code = getattr(exc, "error_code", None)
    return error_code if isinstance(error_code, str) and error_code else "DOMAIN_COMMAND_FAILED"


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
    def finalize(claim: IdempotencyClaim, result: CommandResult) -> None:
        request.app.state.services.idempotency.complete(
            claim,
            status=response_status,
            body=result.model_dump(mode="json"),
            resource_type=resource_type,
            resource_id=result.resource_id,
        )

    return _run_command(
        request,
        raw_key=raw_key,
        body=body,
        resource_type=resource_type,
        execute=lambda _claim: callback(),
        finalize=finalize,
        response_status=response_status,
    )


def run_operator_command(
    request: Request,
    *,
    raw_key: str,
    body: dict[str, Any] | None,
    resource_type: str,
    callback: Callable[[OperatorService], CommandResult],
    response_status: int = 200,
) -> CommandResult:
    services = request.app.state.services

    def execute(claim: IdempotencyClaim) -> CommandResult:
        result: CommandResult = services.idempotency.execute_atomic(
            claim,
            lambda session: callback(services.operators.join_transaction(session)),
            status=response_status,
            resource_type=resource_type,
        )
        return result

    return _run_command(
        request,
        raw_key=raw_key,
        body=body,
        resource_type=resource_type,
        execute=execute,
        finalize=None,
        response_status=response_status,
    )


def _run_command(
    request: Request,
    *,
    raw_key: str,
    body: dict[str, Any] | None,
    resource_type: str,
    execute: Callable[[IdempotencyClaim], CommandResult],
    finalize: Callable[[IdempotencyClaim, CommandResult], None] | None,
    response_status: int,
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
        result = execute(claim)
    except Exception as exc:
        error_code = _domain_error_code(exc)
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
    if finalize is not None:
        # RPC/durable-domain commands retain their original separate completion
        # semantics. A result-storage failure must not reinterpret domain success.
        finalize(claim, result)
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
