"""Legacy source-only item DB reads; registered Item and Graph routes remain canonical."""

from __future__ import annotations

from urllib.parse import quote

from eom_api_contracts import ListResponse, SingleResponse
from eom_api_contracts.external_item_db import (
    ExternalItemDbDetailView,
    ExternalItemDbEntryView,
    ExternalItemDbFilterRequest,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response, StreamingResponse

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one

router = APIRouter(prefix="/item-db/external-sources", tags=["item-db"])
_PERMISSIONS = [Depends(require_permission(PermissionKey.ITEM_READ))]


def _source_access(authentication: Auth) -> None:
    if PermissionKey.CONTENT_INTAKE_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Source read denied")


@router.get(
    "",
    operation_id="item_db_external_source_list",
    response_model=ListResponse[ExternalItemDbEntryView],
    dependencies=_PERMISSIONS,
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value]},
)
def list_external_sources(
    request: Request,
    authentication: Auth,
    exact_number: str | None = Query(default=None, pattern=r"^[0-9]{5}$"),
    major_unit: str | None = Query(default=None, min_length=1, max_length=255),
    field_label: str | None = Query(default=None, min_length=1, max_length=255),
    match_status: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, min_length=1, max_length=1024),
) -> ListResponse[ExternalItemDbEntryView]:
    _source_access(authentication)
    page = request.app.state.services.external_item_db_reads.list(
        exact_number=exact_number,
        major_unit=major_unit,
        field_label=field_label,
        match_status=match_status,
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


@router.post(
    "/search",
    operation_id="item_db_external_source_search",
    response_model=ListResponse[ExternalItemDbEntryView],
    dependencies=_PERMISSIONS,
    openapi_extra={
        "x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value],
        "x-eom-read-only": True,
    },
)
def search_external_sources(
    request: Request,
    authentication: Auth,
    filters: ExternalItemDbFilterRequest,
) -> ListResponse[ExternalItemDbEntryView]:
    _source_access(authentication)
    page = request.app.state.services.external_item_db_reads.list(
        exact_number=None,
        major_unit=None,
        field_label=None,
        match_status=None,
        limit=filters.limit,
        cursor=filters.cursor,
        advanced=filters,
    )
    return many(
        request,
        page.data,
        limit=filters.limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.post(
    "/export",
    operation_id="item_db_external_source_export",
    dependencies=_PERMISSIONS,
    openapi_extra={
        "x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value],
        "x-eom-read-only": True,
    },
)
def export_external_sources(
    request: Request,
    authentication: Auth,
    filters: ExternalItemDbFilterRequest,
) -> Response:
    _source_access(authentication)
    result = request.app.state.services.external_item_db_reads.export(filters)
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="EXTERNAL_ITEM_DB_EXPORT_AUTHORIZED",
        operation_id="item_db_external_source_export",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="external_item_source_collection",
        target_id="notion-integrated-science",
    )
    return Response(
        content=result.payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=EOM-item-database.xlsx",
            "Content-Length": str(len(result.payload)),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{result.sha256}"',
            "X-EOM-Row-Count": str(result.row_count),
        },
    )


@router.get(
    "/{source_id}",
    operation_id="item_db_external_source_detail",
    response_model=SingleResponse[ExternalItemDbDetailView],
    dependencies=_PERMISSIONS,
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value]},
)
def get_external_source(
    request: Request,
    authentication: Auth,
    source_id: str = Path(pattern=r"^extitem_[0-9a-f]{32}$"),
) -> SingleResponse[ExternalItemDbDetailView]:
    _source_access(authentication)
    return one(request, request.app.state.services.external_item_db_reads.detail(source_id))


@router.get(
    "/{source_id}/editions/{edition}/download",
    operation_id="item_db_external_source_document_download",
    dependencies=_PERMISSIONS,
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value]},
)
def download_external_source_document(
    request: Request,
    authentication: Auth,
    source_id: str = Path(pattern=r"^extitem_[0-9a-f]{32}$"),
    edition: int = Path(ge=1, le=3),
    source_revision_id: str = Query(pattern=r"^extitemrev_[0-9a-f]{32}$"),
) -> StreamingResponse:
    _source_access(authentication)
    detail = request.app.state.services.external_item_db_reads.detail(source_id)
    if detail.entry.source_revision_id != source_revision_id:
        raise ApiError(
            409, "ITEM_DB_SOURCE_STALE", "Item source changed", "Pinned source revision is stale"
        )
    value = request.app.state.services.catalog_application.download_external_item_document(
        source_id, source_revision_id, edition
    )
    fallback = f"external-item-{detail.entry.external_number}-{edition}." + (
        "hwpx" if value.media_type.endswith("hwpx") else "hwp"
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="EXTERNAL_ITEM_DOCUMENT_READ_AUTHORIZED",
        operation_id="item_db_external_source_document_download",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="external_item_source",
        target_id=source_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type=value.media_type,
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(value.filename)}"
            ),
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )


@router.get(
    "/{source_id}/editions/{edition}/preview.pdf",
    operation_id="item_db_external_source_preview",
    dependencies=_PERMISSIONS,
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value]},
)
def preview_external_source_document(
    request: Request,
    authentication: Auth,
    source_id: str = Path(pattern=r"^extitem_[0-9a-f]{32}$"),
    edition: int = Path(ge=1, le=3),
    source_revision_id: str = Query(pattern=r"^extitemrev_[0-9a-f]{32}$"),
) -> StreamingResponse:
    _source_access(authentication)
    detail = request.app.state.services.external_item_db_reads.detail(source_id)
    if detail.entry.source_revision_id != source_revision_id:
        raise ApiError(
            409, "ITEM_DB_SOURCE_STALE", "Item source changed", "Pinned source revision is stale"
        )
    value = request.app.state.services.catalog_application.download_external_item_preview(
        source_id, source_revision_id, edition
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="EXTERNAL_ITEM_PREVIEW_READ_AUTHORIZED",
        operation_id="item_db_external_source_preview",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="external_item_source",
        target_id=source_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="external-item-preview.pdf"',
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )


@router.post(
    "/{source_id}/editions/{edition}/preview",
    operation_id="item_db_external_source_prepare_preview",
    dependencies=_PERMISSIONS,
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.CONTENT_INTAKE_READ.value]},
)
def prepare_external_source_preview(
    request: Request,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    source_id: str = Path(pattern=r"^extitem_[0-9a-f]{32}$"),
    edition: int = Path(ge=1, le=3),
    source_revision_id: str = Query(pattern=r"^extitemrev_[0-9a-f]{32}$"),
) -> dict[str, str]:
    _source_access(authentication)
    if idempotency_key != f"external-item-preview-v1:{source_revision_id}:{edition}":
        raise ApiError(
            409,
            "API_IDEMPOTENCY_CONFLICT",
            "Idempotency key differs",
            "The preview request key does not match its pinned source revision.",
        )
    detail = request.app.state.services.external_item_db_reads.detail(source_id)
    if detail.entry.source_revision_id != source_revision_id:
        raise ApiError(
            409, "ITEM_DB_SOURCE_STALE", "Item source changed", "Pinned source revision is stale"
        )
    sha256 = request.app.state.services.catalog_application.prepare_external_item_preview(
        source_id, source_revision_id, edition
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="EXTERNAL_ITEM_PREVIEW_PREPARED",
        operation_id="item_db_external_source_prepare_preview",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="external_item_source",
        target_id=source_id,
    )
    return {"sha256": sha256}
