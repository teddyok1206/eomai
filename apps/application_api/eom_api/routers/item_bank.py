"""Graph-pinned Item Bank read API."""

from __future__ import annotations

from typing import Literal

from eom_api_contracts import ItemBankEntryView, ListResponse
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request

from eom_api.dependencies import require_permission
from eom_api.routers.common import many

router = APIRouter(tags=["item-bank"])


@router.get(
    "/item-bank/entries",
    operation_id="item_bank_entry_list",
    response_model=ListResponse[ItemBankEntryView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def item_bank_entries(
    request: Request,
    curriculum_unit_key: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$"),
    administration_year: int | None = Query(default=None, ge=1900, le=2200),
    administration_month: int | None = Query(default=None, ge=1, le=12),
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"] | None = Query(
        default=None
    ),
    target_grade: int | None = Query(default=None, ge=1, le=6),
    assessment_occurrence_revision_id: str | None = Query(
        default=None, pattern=r"^occurrev_[0-9a-f]{32}$"
    ),
    item_number: int | None = Query(default=None, ge=1, le=200),
    item_type_key: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"),
    difficulty_band: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> ListResponse[ItemBankEntryView]:
    page = request.app.state.services.queries.item_bank_entries(
        curriculum_unit_key=curriculum_unit_key,
        administration_year=administration_year,
        administration_month=administration_month,
        target_school_level=target_school_level,
        target_grade=target_grade,
        assessment_occurrence_revision_id=assessment_occurrence_revision_id,
        item_number=item_number,
        item_type_key=item_type_key,
        difficulty_band=difficulty_band,
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
