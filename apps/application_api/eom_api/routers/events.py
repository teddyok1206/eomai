"""Sanitized cross-domain event feed."""

from __future__ import annotations

from datetime import datetime

from eom_api_contracts import ListResponse
from eom_api_contracts.events import EventView
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request

from eom_api.dependencies import require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many

router = APIRouter(prefix="/events", tags=["events"])


@router.get(
    "",
    operation_id="event_list",
    response_model=ListResponse[EventView],
    dependencies=[Depends(require_permission(PermissionKey.EVENT_READ))],
)
def list_events(
    request: Request,
    after_cursor: str | None = Query(default=None, max_length=256),
    aggregate_type: str | None = Query(default=None, max_length=64),
    aggregate_id: str | None = Query(default=None, max_length=128),
    event_type: str | None = Query(default=None, max_length=64),
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[EventView]:
    values = request.app.state.services.queries.events(limit=200)
    filtered = tuple(
        value
        for value in values
        if (aggregate_type is None or value.aggregate_type == aggregate_type)
        and (aggregate_id is None or value.aggregate_id == aggregate_id)
        and (event_type is None or value.event_type == event_type)
        and (from_time is None or value.created_at >= from_time)
        and (to_time is None or value.created_at <= to_time)
    )
    if after_cursor is not None:
        positions = [
            index for index, value in enumerate(filtered) if value.event_id == after_cursor
        ]
        if not positions:
            raise ApiError(
                400,
                "API_CURSOR_INVALID",
                "Invalid cursor",
                "The event cursor is not present in the retained result window.",
            )
        filtered = filtered[positions[0] + 1 :]
    page = filtered[:limit]
    more = len(filtered) > limit
    next_cursor = page[-1].event_id if more and page else None
    return many(request, page, limit=limit, next_cursor=next_cursor, has_more=more)
