"""Deliverable command/query endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.deliverables import CreateDeliverableRequest, DeliverableView
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/deliverables", tags=["deliverables"])


@router.get(
    "",
    operation_id="deliverable_list",
    response_model=ListResponse[DeliverableView],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def list_deliverables(request: Request) -> ListResponse[DeliverableView]:
    values = request.app.state.services.queries.list_deliverables()
    return many(request, values, limit=200)


@router.get(
    "/{deliverable_id}",
    operation_id="deliverable_get",
    response_model=SingleResponse[DeliverableView],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def get_deliverable(request: Request, deliverable_id: str) -> SingleResponse[DeliverableView]:
    return one(request, request.app.state.services.queries.deliverable(deliverable_id))


@router.post(
    "",
    operation_id="deliverable_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
)
def create_deliverable(
    request: Request,
    body: CreateDeliverableRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, deliverable_id, version = (
            request.app.state.services.commands.create_deliverable(
                body, request.state.request_context.actor()
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type="deliverable",
            resource_id=deliverable_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/deliverables/{deliverable_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="deliverable",
            callback=execute,
            response_status=201,
        ),
    )
