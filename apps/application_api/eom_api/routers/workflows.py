"""Workflow command/query endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.events import EventView
from eom_api_contracts.workflows import (
    WorkflowActionRequest,
    WorkflowStartRequest,
    WorkflowStepView,
    WorkflowView,
)
from eom_operator_identity import PermissionKey
from eom_workflow_runner.repository import CommandType
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get(
    "",
    operation_id="workflow_list",
    response_model=ListResponse[WorkflowView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def list_workflows(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    state: str | None = Query(default=None, max_length=40),
) -> ListResponse[WorkflowView]:
    page = request.app.state.services.queries.list_workflows(
        limit=limit, cursor=cursor, state=state
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
    operation_id="workflow_start",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def start_workflow(
    request: Request,
    body: WorkflowStartRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="workflow_start",
            raw_key=idempotency_key,
        )
        command_id, workflow_id, version = request.app.state.services.commands.start_workflow(
            body,
            actor,
            idempotency_key=submission_key,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="workflow",
            resource_id=workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=f"/api/v1/workflows/{workflow_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="workflow",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/{workflow_id}",
    operation_id="workflow_get",
    response_model=SingleResponse[WorkflowView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_workflow(
    request: Request, workflow_id: str, response: Response
) -> SingleResponse[WorkflowView]:
    value = request.app.state.services.queries.workflow(workflow_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/{workflow_id}/steps",
    operation_id="workflow_steps",
    response_model=ListResponse[WorkflowStepView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def workflow_steps(request: Request, workflow_id: str) -> ListResponse[WorkflowStepView]:
    values = request.app.state.services.queries.workflow_steps(workflow_id)
    return many(request, values, limit=200)


@router.get(
    "/{workflow_id}/events",
    operation_id="workflow_events",
    response_model=ListResponse[EventView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def workflow_events(request: Request, workflow_id: str) -> ListResponse[EventView]:
    values = request.app.state.services.queries.workflow_events(workflow_id)
    return many(request, values, limit=200)


def _action(
    request: Request,
    workflow_id: str,
    command_type: CommandType,
    body: WorkflowActionRequest,
    idempotency_key: str,
    expected_version: int,
) -> CommandResult:
    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key=f"workflow_action:{command_type.value}",
            raw_key=idempotency_key,
        )
        command_id, version = request.app.state.services.commands.workflow_action(
            workflow_id,
            command_type,
            body,
            actor,
            expected_version=expected_version,
            idempotency_key=submission_key,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="workflow",
            resource_id=workflow_id,
            status="ACCEPTED",
            resource_version=version,
            status_url=f"/api/v1/workflows/{workflow_id}",
        )

    return run_command(
        request,
        raw_key=idempotency_key,
        body={"action": command_type.value, **body.model_dump(mode="json")},
        resource_type="workflow",
        callback=execute,
        response_status=202,
    )


@router.post(
    "/{workflow_id}/approvals",
    operation_id="workflow_approve",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_APPROVE))],
)
def approve(
    request: Request,
    workflow_id: str,
    body: WorkflowActionRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication
    return one(
        request,
        _action(
            request,
            workflow_id,
            CommandType.APPROVE_WORKFLOW,
            body,
            idempotency_key,
            expected_version,
        ),
    )


@router.post(
    "/{workflow_id}/rework-requests",
    operation_id="workflow_request_rework",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_REQUEST_REWORK))],
)
def request_rework(
    request: Request,
    workflow_id: str,
    body: WorkflowActionRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication
    return one(
        request,
        _action(
            request,
            workflow_id,
            CommandType.REQUEST_REWORK,
            body,
            idempotency_key,
            expected_version,
        ),
    )


@router.post(
    "/{workflow_id}/cancellations",
    operation_id="workflow_cancel",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_CANCEL))],
)
def cancel(
    request: Request,
    workflow_id: str,
    body: WorkflowActionRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication
    return one(
        request,
        _action(
            request,
            workflow_id,
            CommandType.CANCEL_WORKFLOW,
            body,
            idempotency_key,
            expected_version,
        ),
    )


@router.post(
    "/{workflow_id}/reconciliations",
    operation_id="workflow_reconcile",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_RECONCILE, admin_only=True))],
)
def reconcile(
    request: Request,
    workflow_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication
    return one(
        request,
        _action(
            request,
            workflow_id,
            CommandType.RECONCILE_WORKFLOW,
            WorkflowActionRequest(),
            idempotency_key,
            expected_version,
        ),
    )
