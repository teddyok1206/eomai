"""Read-only assessment archive extraction and Graph-learning progress."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import ListResponse
from eom_api_contracts.assessment_learning import (
    AssessmentLearningBatchView,
    AssessmentLearningExamView,
    AssessmentLearningPageView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.responses import StreamingResponse

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


@router.get(
    "/{batch_id}/exams/{occurrence_revision_id}/pages",
    operation_id="assessment_learning_page_list",
    response_model=ListResponse[AssessmentLearningPageView],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def list_assessment_learning_pages(
    request: Request,
    batch_id: str = Path(pattern=r"^legacybatch_[0-9a-f]{32}$"),
    occurrence_revision_id: str = Path(pattern=r"^occurrev_[0-9a-f]{32}$"),
) -> ListResponse[AssessmentLearningPageView]:
    pointers = request.app.state.services.catalog_application.assessment_pages(
        batch_id,
        occurrence_revision_id,
    )
    values = tuple(
        AssessmentLearningPageView(
            extraction_batch_id=batch_id,
            assessment_occurrence_revision_id=occurrence_revision_id,
            page_input_id=pointer.page_input_id,
            source_role=pointer.source_role,
            physical_page=pointer.physical_page,
            artifact_id=pointer.artifact_id,
            artifact_revision_id=pointer.artifact_revision_id,
            artifact_member=pointer.member_path,
            sha256=pointer.sha256,
            content_length=pointer.content_length,
            width_px=pointer.width_px,
            height_px=pointer.height_px,
        )
        for pointer in pointers
    )
    return many(request, values, limit=max(1, len(values)), next_cursor=None, has_more=False)


@router.get(
    "/{batch_id}/exams/{occurrence_revision_id}/pages/{page_input_id}/image",
    operation_id="assessment_learning_page_image_get",
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def get_assessment_learning_page_image(
    request: Request,
    batch_id: str = Path(pattern=r"^legacybatch_[0-9a-f]{32}$"),
    occurrence_revision_id: str = Path(pattern=r"^occurrev_[0-9a-f]{32}$"),
    page_input_id: str = Path(pattern=r"^assessmentpage_[0-9a-f]{32}$"),
) -> StreamingResponse:
    value = request.app.state.services.catalog_application.download_assessment_page(
        batch_id,
        occurrence_revision_id,
        page_input_id,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="ASSESSMENT_PAGE_IMAGE_READ_AUTHORIZED",
        operation_id="assessment_learning_page_image_get",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="assessment_page_input",
        target_id=page_input_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type="image/png",
        headers={
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )
