"""Authenticated in-product customer-support endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.customer_support import (
    CreateCustomerSupportCaseRequest,
    CustomerSupportCaseView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.build_info import get_build_info
from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/customer-support/cases", tags=["customer-support"])


@router.get(
    "",
    operation_id="customer_support_case_list",
    response_model=ListResponse[CustomerSupportCaseView],
    dependencies=[Depends(require_permission(PermissionKey.CUSTOMER_SUPPORT_READ))],
)
def list_customer_support_cases(
    request: Request,
    authentication: Auth,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1024),
) -> ListResponse[CustomerSupportCaseView]:
    page = request.app.state.services.queries.list_customer_support_cases(
        actor_id=authentication.operator.operator_id,
        limit=limit,
        cursor=cursor,
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post(
    "",
    operation_id="customer_support_case_create",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.CUSTOMER_SUPPORT_CREATE))],
)
def create_customer_support_case(
    request: Request,
    body: CreateCustomerSupportCaseRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="customer_support_case_create",
            raw_key=idempotency_key,
        )
        command_id, workflow_id, version = (
            request.app.state.services.commands.start_customer_support(
                body,
                actor,
                idempotency_key=submission_key,
                api_release_commit=get_build_info().source_commit,
                observed_at=datetime.now(UTC),
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type="customer_support_case",
            resource_id=workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=f"/api/v1/customer-support/cases/{workflow_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(
                mode="json",
                exclude={"inquiry_id", "web_release_commit"},
            ),
            resource_type="customer_support_case",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/{workflow_id}",
    operation_id="customer_support_case_get",
    response_model=SingleResponse[CustomerSupportCaseView],
    dependencies=[Depends(require_permission(PermissionKey.CUSTOMER_SUPPORT_READ))],
)
def get_customer_support_case(
    request: Request,
    workflow_id: str,
    authentication: Auth,
    response: Response,
) -> SingleResponse[CustomerSupportCaseView]:
    value = request.app.state.services.queries.customer_support_case(
        actor_id=authentication.operator.operator_id,
        workflow_id=workflow_id,
    )
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)
