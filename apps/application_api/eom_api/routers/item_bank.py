"""Graph-pinned Item Bank read API."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_api_contracts import (
    ItemBankEntryView,
    ListResponse,
    ProductionContentProfileV2,
    ProductionItemCandidateViewContract,
    SingleResponse,
)
from eom_api_contracts.external_item_db import ExternalItemDbFilterRequest
from eom_api_contracts.item_db_registration import (
    AiItemDbEntryView,
    ApprovalState,
    CreativeItemDbEntryView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request

from eom_api.dependencies import Auth, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one

router = APIRouter(tags=["item-bank"])


@router.post(
    "/item-db/creative/search",
    operation_id="item_db_creative_search",
    response_model=ListResponse[CreativeItemDbEntryView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
    openapi_extra={
        "x-eom-read-only": True,
        "x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value],
    },
)
def creative_item_db_search(
    request: Request,
    authentication: Auth,
    filters: ExternalItemDbFilterRequest,
    approval_state: Annotated[ApprovalState | None, Query()] = None,
) -> ListResponse[CreativeItemDbEntryView]:
    if PermissionKey.CONTENT_INTAKE_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Source read denied")
    page = request.app.state.services.external_item_db_reads.creative_list(filters, approval_state)
    return many(
        request,
        page.data,
        limit=filters.limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/item-db/ai",
    operation_id="item_db_ai_list",
    response_model=ListResponse[AiItemDbEntryView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def ai_item_db_entries(
    request: Request,
    approval_state: Annotated[ApprovalState | None, Query()] = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> ListResponse[AiItemDbEntryView]:
    page = request.app.state.services.queries.ai_item_db_entries(
        approval_state=approval_state, limit=limit, cursor=cursor
    )
    return many(
        request, page.data, limit=limit, next_cursor=page.next_cursor, has_more=page.has_more
    )


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


@router.get(
    "/item-bank/production-candidates",
    operation_id="production_item_candidate_list",
    response_model=ListResponse[ProductionItemCandidateViewContract],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def production_item_candidates(
    request: Request,
    curriculum_unit_key: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,191}$"),
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"] | None = Query(default=None),
    content_profile: Annotated[ProductionContentProfileV2 | None, Query()] = None,
    eligible: bool | None = Query(default=None),
    item_type_key: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$"),
    difficulty_band: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
    administration_year: int | None = Query(default=None, ge=1900, le=2200),
    administration_month: int | None = Query(default=None, ge=1, le=12),
    item_number: int | None = Query(default=None, ge=1, le=200),
    approval_state: Annotated[ApprovalState | None, Query()] = None,
) -> ListResponse[ProductionItemCandidateViewContract]:
    page = request.app.state.services.queries.production_item_candidates(
        curriculum_unit_key=curriculum_unit_key,
        source_class=source_class,
        content_profile=content_profile,
        eligible=eligible,
        item_type_key=item_type_key,
        difficulty_band=difficulty_band,
        limit=limit,
        cursor=cursor,
        administration_year=administration_year,
        administration_month=administration_month,
        item_number=item_number,
        **({"approval_state": approval_state} if approval_state else {}),
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/item-db/registrations/{revision_id}/graph",
    operation_id="item_db_registration_graph",
    response_model=SingleResponse[ProductionItemCandidateViewContract | None],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def registration_graph(
    request: Request,
    revision_id: Annotated[str, Path(pattern=r"^itemrev_[0-9a-f]{32}$")],
    manifest_sha256: str = Query(pattern=r"^sha256:[0-9a-f]{64}$"),
) -> SingleResponse[ProductionItemCandidateViewContract | None]:
    page = request.app.state.services.queries.production_item_candidates(
        curriculum_unit_key=None,
        source_class="APPROVED_ITEM",
        content_profile=None,
        eligible=None,
        item_type_key=None,
        difficulty_band=None,
        limit=1,
        cursor=None,
        selected_revision_id=revision_id,
    )
    candidate = page.data[0] if page.data else None
    if candidate is not None and candidate.item_manifest_sha256 != manifest_sha256:
        raise ApiError(409, "ITEM_DB_SOURCE_STALE", "Item changed", "Pinned manifest differs")
    if candidate is not None and candidate.item_revision_state not in {"APPROVED", "SUPERSEDED"}:
        candidate = None
    return one(request, candidate)
