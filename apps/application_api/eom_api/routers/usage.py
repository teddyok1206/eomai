"""Usage Plan and immutable Usage Record endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.usage import (
    CreateUsagePlanRequest,
    FulfillUsagePlanRequest,
    UsagePlanView,
    UsageRecordView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(tags=["usage"])


@router.get(
    "/usage-plans",
    operation_id="usage_plan_list",
    response_model=ListResponse[UsagePlanView],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_READ))],
)
def list_plans(request: Request) -> ListResponse[UsagePlanView]:
    values = request.app.state.services.queries.list_usage_plans()
    return many(request, values, limit=200)


@router.get(
    "/usage-plans/{usage_plan_id}",
    operation_id="usage_plan_get",
    response_model=SingleResponse[UsagePlanView],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_READ))],
)
def get_plan(
    request: Request, usage_plan_id: str, response: Response
) -> SingleResponse[UsagePlanView]:
    value = request.app.state.services.queries.usage_plan(usage_plan_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/usage-records",
    operation_id="usage_record_list",
    response_model=ListResponse[UsageRecordView],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_READ))],
)
def list_records(request: Request) -> ListResponse[UsageRecordView]:
    values = request.app.state.services.queries.list_usage_records()
    return many(request, values, limit=200)


@router.get(
    "/usage-records/{usage_record_id}",
    operation_id="usage_record_get",
    response_model=SingleResponse[UsageRecordView],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_READ))],
)
def get_record(request: Request, usage_record_id: str) -> SingleResponse[UsageRecordView]:
    return one(request, request.app.state.services.queries.usage_record(usage_record_id))


@router.post(
    "/usage-plans",
    operation_id="usage_plan_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_CREATE_PLAN))],
)
def create_plan(
    request: Request,
    body: CreateUsagePlanRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, plan_id, version = request.app.state.services.commands.create_usage_plan(
            body, request.state.request_context.actor()
        )
        return CommandResult(
            command_id=command_id,
            resource_type="usage_plan",
            resource_id=plan_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/usage-plans/{plan_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="usage_plan",
            callback=execute,
            response_status=201,
        ),
    )


def _plan_action(
    request: Request,
    plan_id: str,
    action: str,
    idempotency_key: str,
    expected_version: int,
    body: FulfillUsagePlanRequest | None = None,
) -> CommandResult:
    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        if action == "reserve":
            command_id, version = request.app.state.services.commands.reserve_usage_plan(
                plan_id, actor, expected_version=expected_version
            )
            resource_id = plan_id
            resource_type = "usage_plan"
            status_url = f"/api/v1/usage-plans/{plan_id}"
        elif action == "cancel":
            command_id, version = request.app.state.services.commands.cancel_usage_plan(
                plan_id, actor, expected_version=expected_version
            )
            resource_id = plan_id
            resource_type = "usage_plan"
            status_url = f"/api/v1/usage-plans/{plan_id}"
        else:
            assert body is not None
            command_id, resource_id, version = (
                request.app.state.services.commands.fulfill_usage_plan(
                    plan_id, body, actor, expected_version=expected_version
                )
            )
            resource_type = "usage_record"
            status_url = f"/api/v1/usage-records/{resource_id}"
        return CommandResult(
            command_id=command_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status="COMPLETED",
            resource_version=version,
            status_url=status_url,
        )

    return run_command(
        request,
        raw_key=idempotency_key,
        body={"action": action, **(body.model_dump(mode="json") if body else {})},
        resource_type="usage_plan",
        callback=execute,
    )


@router.post(
    "/usage-plans/{usage_plan_id}/reservations",
    operation_id="usage_plan_reserve",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_RESERVE_PLAN))],
)
def reserve_plan(
    request: Request,
    usage_plan_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication
    return one(
        request,
        _plan_action(request, usage_plan_id, "reserve", idempotency_key, expected_version),
    )


@router.post(
    "/usage-plans/{usage_plan_id}/cancellations",
    operation_id="usage_plan_cancel",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_CANCEL_PLAN))],
)
def cancel_plan(
    request: Request,
    usage_plan_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication
    return one(
        request,
        _plan_action(request, usage_plan_id, "cancel", idempotency_key, expected_version),
    )


@router.post(
    "/usage-plans/{usage_plan_id}/fulfillments",
    operation_id="usage_plan_fulfill",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_FULFILL_PLAN))],
)
def fulfill_plan(
    request: Request,
    usage_plan_id: str,
    body: FulfillUsagePlanRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication
    return one(
        request,
        _plan_action(
            request,
            usage_plan_id,
            "fulfill",
            idempotency_key,
            expected_version,
            body,
        ),
    )
