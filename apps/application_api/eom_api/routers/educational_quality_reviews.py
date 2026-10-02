"""Human educational-quality review workbench endpoints."""

from __future__ import annotations

from typing import Annotated

from eom_api_contracts import CommandResult, SingleResponse
from eom_api_contracts.educational_quality import (
    EducationalQualityReviewCommand,
    EducationalQualityReviewWorkbenchView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.routers.common import one, run_command

router = APIRouter(prefix="/educational-quality-reviews", tags=["educational-quality-reviews"])


@router.get(
    "/workbench",
    operation_id="educational_quality_review_workbench_get",
    response_model=SingleResponse[EducationalQualityReviewWorkbenchView],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def get_workbench(
    request: Request,
    plan_id: Annotated[
        str | None,
        Query(pattern=r"^qualityplan_[0-9a-f]{32}$"),
    ] = None,
) -> SingleResponse[EducationalQualityReviewWorkbenchView]:
    return one(request, request.app.state.services.educational_quality_reviews.workbench(plan_id))


@router.post(
    "/commands",
    operation_id="educational_quality_review_command_submit",
    status_code=200,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_APPROVE))],
)
def submit_command(
    request: Request,
    body: EducationalQualityReviewCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, resource_id, version, resource_type = (
            request.app.state.services.educational_quality_reviews.execute(
                body, request.state.request_context.actor()
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status="COMPLETED",
            resource_version=version,
            status_url="/api/v1/educational-quality-reviews/workbench",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="educational_quality_review",
            callback=execute,
        ),
    )
