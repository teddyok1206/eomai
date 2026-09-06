"""Read-only, pinned curriculum selection catalogs for item authoring."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import (
    AssessmentItemOccurrenceViewV2,
    CurriculumGraphCapabilityView,
    ListResponse,
    SingleResponse,
)
from eom_catalog_contracts import (
    IntegratedScienceEditorialOutline,
    load_integrated_science_editorial_outline,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request

from eom_api.dependencies import require_permission
from eom_api.routers.common import many, one

router = APIRouter(tags=["curriculum"])


@router.get(
    "/curriculum/integrated-science-editorial-outline",
    operation_id="integrated_science_editorial_outline_get",
    response_model=SingleResponse[IntegratedScienceEditorialOutline],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def integrated_science_editorial_outline(
    request: Request,
) -> SingleResponse[IntegratedScienceEditorialOutline]:
    return one(request, load_integrated_science_editorial_outline())


@router.get(
    "/curriculum/integrated-science-graph-capability",
    operation_id="integrated_science_graph_capability_get",
    response_model=SingleResponse[CurriculumGraphCapabilityView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def integrated_science_graph_capability(
    request: Request,
) -> SingleResponse[CurriculumGraphCapabilityView]:
    return one(request, request.app.state.services.queries.integrated_science_graph_capability())


@router.get(
    "/curriculum/assessment-occurrences/items",
    operation_id="assessment_occurrence_item_list",
    response_model=ListResponse[AssessmentItemOccurrenceViewV2],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def assessment_occurrence_items(
    request: Request,
    administration_year: int = Query(ge=1900, le=2200),
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"] = Query(),
    target_grade: int = Query(ge=1, le=6),
    administration_month: int = Query(ge=1, le=12),
    subject_key: str = Query(pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$"),
    assessment_occurrence_revision_id: str | None = Query(
        default=None, pattern=r"^occurrev_[0-9a-f]{32}$"
    ),
    item_number: int | None = Query(default=None, ge=1, le=200),
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> ListResponse[AssessmentItemOccurrenceViewV2]:
    page = request.app.state.services.queries.assessment_items_by_exam(
        administration_year=administration_year,
        target_school_level=target_school_level,
        target_grade=target_grade,
        administration_month=administration_month,
        subject_key=subject_key,
        assessment_occurrence_revision_id=assessment_occurrence_revision_id,
        item_number=item_number,
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
    "/curriculum/integrated-science-units/{curriculum_unit_id}/past-exam-items",
    operation_id="curriculum_unit_past_exam_item_list",
    response_model=ListResponse[AssessmentItemOccurrenceViewV2],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def curriculum_unit_past_exam_items(
    request: Request,
    curriculum_unit_id: str = Path(pattern=r"^currunit_[0-9a-f]{32}$"),
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> ListResponse[AssessmentItemOccurrenceViewV2]:
    page = request.app.state.services.queries.assessment_items_by_curriculum_unit(
        curriculum_unit_id=curriculum_unit_id,
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
