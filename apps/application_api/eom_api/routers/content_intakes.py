"""Content Intake metadata query and decision endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.content_intakes import (
    ContentIntakeSummary,
    IntakeDecisionRequest,
    IntakeDetail,
)
from eom_api_contracts.events import EventView
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/content-intakes", tags=["content-intakes"])


@router.get(
    "",
    operation_id="content_intake_list",
    response_model=ListResponse[ContentIntakeSummary],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_INTAKE_READ))],
)
def list_intakes(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    state: str | None = Query(default=None, max_length=40),
) -> ListResponse[ContentIntakeSummary]:
    page = request.app.state.services.queries.list_intakes(limit=limit, cursor=cursor, state=state)
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{intake_batch_id}",
    operation_id="content_intake_get",
    response_model=SingleResponse[IntakeDetail],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_INTAKE_READ))],
)
def get_intake(
    request: Request, intake_batch_id: str, response: Response
) -> SingleResponse[IntakeDetail]:
    value = request.app.state.services.queries.intake(intake_batch_id)
    response.headers["ETag"] = etag(value.intake.resource_version)
    return one(request, value)


@router.get(
    "/{intake_batch_id}/events",
    operation_id="content_intake_events",
    response_model=ListResponse[EventView],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_INTAKE_READ))],
)
def intake_events(request: Request, intake_batch_id: str) -> ListResponse[EventView]:
    values = request.app.state.services.queries.intake_events(intake_batch_id)
    return many(request, values, limit=min(200, max(1, len(values))))


@router.post(
    "/{intake_batch_id}/decisions",
    operation_id="content_intake_decide",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_INTAKE_DECIDE))],
)
def decide_intake(
    request: Request,
    intake_batch_id: str,
    body: IntakeDecisionRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def unavailable() -> CommandResult:
        raise ApiError(
            503,
            "API_DEPENDENCY_UNAVAILABLE",
            "Decision artifact gateway unavailable",
            "Content Intake decisions require the deferred validated artifact gateway.",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="content_intake",
            callback=unavailable,
        ),
    )
