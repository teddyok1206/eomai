"""Read-only assessment archive extraction and Graph-learning progress."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import ListResponse
from eom_api_contracts.assessment_learning import (
    AssessmentLearningBatchView,
    AssessmentLearningExamView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request

from eom_api.dependencies import require_permission
from eom_api.routers.common import many

router = APIRouter(prefix="/assessment-learning-batches", tags=["assessment-learning"])


@router.get(
    "",
    operation_id="assessment_learning_batch_list",
    response_model=ListResponse[AssessmentLearningBatchView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def list_assessment_learning_batches(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=1024),
    state: Literal[
        "QUEUED",
        "RUNNING",
        "AWAITING_REVIEW",
        "SUCCEEDED",
        "COMPLETED_WITH_GAPS",
        "CANCELLED",
    ]
    | None = Query(default=None),
) -> ListResponse[AssessmentLearningBatchView]:
    page = request.app.state.services.queries.list_assessment_learning_batches(
        limit=limit,
        cursor=cursor,
        state=state,
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{batch_id}/exams",
    operation_id="assessment_learning_exam_list",
    response_model=ListResponse[AssessmentLearningExamView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def list_assessment_learning_exams(
    request: Request,
    batch_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None, max_length=1024),
) -> ListResponse[AssessmentLearningExamView]:
    page = request.app.state.services.queries.assessment_learning_exams(
        batch_id,
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
