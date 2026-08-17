"""Public liveness and sanitized readiness endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts import SingleResponse
from eom_api_contracts.system import LiveStatus, ReadyStatus
from fastapi import APIRouter, Request, Response

from eom_api.health import readiness
from eom_api.routers.common import one

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    operation_id="health_live",
    response_model=SingleResponse[LiveStatus],
)
def live(request: Request) -> SingleResponse[LiveStatus]:
    return one(request, LiveStatus(timestamp=datetime.now(UTC)))


@router.get(
    "/ready",
    operation_id="health_ready",
    response_model=SingleResponse[ReadyStatus],
    responses={503: {"description": "Application dependencies are not ready"}},
)
def ready(request: Request, response: Response) -> SingleResponse[ReadyStatus]:
    value = readiness(request.app.state.services)
    if not value:
        response.status_code = 503
    return one(request, ReadyStatus(status="READY" if value else "NOT_READY"))
