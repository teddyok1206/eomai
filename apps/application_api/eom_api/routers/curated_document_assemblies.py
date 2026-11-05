"""Persist an ordered, pinned mixed-source selection; delivery is a separate use case."""

from __future__ import annotations

from eom_api_contracts import ListResponse, SingleResponse
from eom_api_contracts.curated_document_assembly import (
    CuratedDocumentAssemblyDraftV1,
    CuratedDocumentAssemblyDraftV2,
    CuratedDocumentAssemblyRemovalInput,
    CuratedDocumentAssemblyRemovalReceipt,
)
from eom_api_contracts.curated_hwpx import CreateCuratedHwpxBuildRequest, CuratedHwpxBuildView
from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_application import (
    CuratedDocumentAssemblyListEntryV1,
)
from eom_catalog_contracts.curated_document_assembly_library import (
    CuratedDocumentAssemblyListEntryV2,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.responses import StreamingResponse

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one
from eom_api.services.hwpx_projection import project_curated_hwpx_build

router = APIRouter(prefix="/item-db/assemblies", tags=["item-db"])


@router.post(
    "/{assembly_id}/hwpx-builds",
    status_code=202,
    operation_id="item_db_curated_hwpx_build_create",
    response_model=SingleResponse[CuratedHwpxBuildView],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_BUILD_CREATE))],
)
def create_curated_build(
    request: Request,
    body: CreateCuratedHwpxBuildRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
) -> SingleResponse[CuratedHwpxBuildView]:
    record, _created = request.app.state.services.curated_hwpx.request_build(
        assembly_id,
        assembly_revision_id=body.assembly_revision_id,
        manifest_sha256=body.manifest_sha256,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CURATED_HWPX_BUILD_REQUEST_ACCEPTED",
        operation_id="item_db_curated_hwpx_build_create",
        outcome="SUCCEEDED",
        http_status=202,
        target_type="hwpx_build",
        target_id=record.build_id,
    )
    return one(request, project_curated_hwpx_build(record))


@router.get(
    "/{assembly_id}/hwpx-builds/latest",
    operation_id="item_db_curated_hwpx_build_latest",
    response_model=SingleResponse[CuratedHwpxBuildView | None],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def latest_curated_build(
    request: Request,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
    assembly_revision_id: str = Query(pattern=r"^assemblyrev_[0-9a-f]{32}$"),
    manifest_sha256: str = Query(pattern=r"^sha256:[0-9a-f]{64}$"),
) -> SingleResponse[CuratedHwpxBuildView | None]:
    record = request.app.state.services.curated_hwpx.latest_build(
        assembly_id,
        assembly_revision_id=assembly_revision_id,
        manifest_sha256=manifest_sha256,
        actor=request.state.request_context.actor(),
    )
    return one(request, project_curated_hwpx_build(record) if record is not None else None)


@router.get(
    "/{assembly_id}/hwpx-builds/{build_id}",
    operation_id="item_db_curated_hwpx_build_read",
    response_model=SingleResponse[CuratedHwpxBuildView],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def read_curated_build(
    request: Request,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
    build_id: str = Path(pattern=r"^hwpxbuild_[0-9a-f]{32}$"),
) -> SingleResponse[CuratedHwpxBuildView]:
    record = request.app.state.services.curated_hwpx.get_build(
        build_id, actor=request.state.request_context.actor()
    )
    if record.assembly_id != assembly_id:
        raise ApiError(
            404, "HWPX_APPLICATION_BUILD_NOT_FOUND", "Not found", "Assembly build not found"
        )
    return one(request, project_curated_hwpx_build(record))


@router.get(
    "/{assembly_id}/hwpx-builds/{build_id}/download",
    operation_id="item_db_curated_hwpx_build_download",
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def download_curated_build(
    request: Request,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
    build_id: str = Path(pattern=r"^hwpxbuild_[0-9a-f]{32}$"),
) -> StreamingResponse:
    record = request.app.state.services.curated_hwpx.get_build(
        build_id, actor=request.state.request_context.actor()
    )
    if record.assembly_id != assembly_id:
        raise ApiError(
            404, "HWPX_APPLICATION_BUILD_NOT_FOUND", "Not found", "Assembly build not found"
        )
    if record.state != "SUCCEEDED" or record.validation_state != "PASS":
        raise ApiError(
            409,
            "HWPX_APPLICATION_DOWNLOAD_UNAVAILABLE",
            "Not ready",
            "Validated assembly output is not available",
        )
    value = request.app.state.services.hwpx_downloads.download_curated(build_id)
    if value.sha256 != record.output_sha256 or value.content_length != record.output_size_bytes:
        value.connection.close()
        raise ApiError(
            502,
            "HWPX_RESULT_INVALID",
            "Invalid delivery",
            "Download differs from the committed output",
        )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CURATED_HWPX_DOWNLOAD_AUTHORIZED",
        operation_id="item_db_curated_hwpx_build_download",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="hwpx_build",
        target_id=build_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type="application/vnd.hancom.hwpx",
        headers={
            "Content-Disposition": f'attachment; filename="{value.filename}"',
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": value.sha256,
        },
    )


@router.get(
    "",
    operation_id="item_db_curated_assembly_list",
    response_model=ListResponse[CuratedDocumentAssemblyListEntryV1],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def list_curated_assemblies(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    ),
) -> ListResponse[CuratedDocumentAssemblyListEntryV1]:
    values, next_cursor = (
        request.app.state.services.catalog_application.list_curated_document_assemblies(
            actor=request.state.request_context.actor(), limit=limit, cursor=cursor
        )
    )
    return many(
        request, values, limit=limit, next_cursor=next_cursor, has_more=next_cursor is not None
    )


@router.get(
    "/library",
    operation_id="item_db_curated_assembly_library_list",
    response_model=ListResponse[CuratedDocumentAssemblyListEntryV2],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def list_titled_curated_assemblies(
    request: Request,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(
        default=None, max_length=70, pattern=r"^[0-9]{13,20}\|assembly_[0-9a-f]{32}$"
    ),
) -> ListResponse[CuratedDocumentAssemblyListEntryV2]:
    entries, next_cursor = (
        request.app.state.services.catalog_application.list_titled_curated_document_assemblies(
            actor=request.state.request_context.actor(), limit=limit, cursor=cursor
        )
    )
    return many(
        request, entries, limit=limit, next_cursor=next_cursor, has_more=next_cursor is not None
    )


@router.post(
    "/{assembly_id}/remove",
    operation_id="item_db_curated_assembly_remove",
    response_model=SingleResponse[CuratedDocumentAssemblyRemovalReceipt],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
    openapi_extra={"x-eom-additional-permissions": [PermissionKey.ITEM_READ.value]},
)
def remove_curated_assembly(
    request: Request,
    body: CuratedDocumentAssemblyRemovalInput,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
) -> SingleResponse[CuratedDocumentAssemblyRemovalReceipt]:
    if PermissionKey.ITEM_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Item read denied")
    receipt = request.app.state.services.catalog_application.remove_curated_document_assembly(
        assembly_id,
        body,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CURATED_DOCUMENT_ASSEMBLY_REMOVED_FROM_LIST",
        operation_id="item_db_curated_assembly_remove",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="curated_document_assembly",
        target_id=assembly_id,
    )
    return one(request, receipt)


@router.get(
    "/{assembly_id}",
    operation_id="item_db_curated_assembly_read",
    response_model=SingleResponse[CuratedDocumentAssemblyManifestV1],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
    openapi_extra={
        "x-eom-conditional-permissions": {
            "EXTERNAL_SOURCE_DOCUMENT": [PermissionKey.CONTENT_INTAKE_READ.value]
        }
    },
)
def read_curated_assembly(
    request: Request,
    assembly_id: str = Path(pattern=r"^assembly_[0-9a-f]{32}$"),
) -> SingleResponse[CuratedDocumentAssemblyManifestV1]:
    manifest = request.app.state.services.catalog_application.read_curated_document_assembly(
        assembly_id, actor=request.state.request_context.actor()
    )
    return one(request, manifest)


@router.post(
    "",
    operation_id="item_db_curated_assembly_create",
    status_code=201,
    response_model=SingleResponse[CuratedDocumentAssemblyManifestV1],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
    openapi_extra={
        "x-eom-additional-permissions": [PermissionKey.ITEM_READ.value],
        "x-eom-conditional-permissions": {
            "EXTERNAL_SOURCE_DOCUMENT": [PermissionKey.CONTENT_INTAKE_READ.value]
        },
    },
)
def create_curated_assembly(
    request: Request,
    body: CuratedDocumentAssemblyDraftV1 | CuratedDocumentAssemblyDraftV2,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CuratedDocumentAssemblyManifestV1]:
    if PermissionKey.ITEM_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Item read denied")
    if any(row.placement_kind == "EXTERNAL_SOURCE_DOCUMENT" for row in body.placements) and (
        PermissionKey.CONTENT_INTAKE_READ not in authentication.permissions
    ):
        raise ApiError(
            403,
            "PERMISSION_DENIED",
            "Permission denied",
            "Source document read permission is required for this selection.",
        )
    manifest = request.app.state.services.catalog_application.create_curated_document_assembly(
        body,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CURATED_DOCUMENT_ASSEMBLY_INPUT_PINNED",
        operation_id="item_db_curated_assembly_create",
        outcome="SUCCEEDED",
        http_status=201,
        target_type="curated_document_assembly_revision",
        target_id=manifest.assembly_revision_id,
    )
    return one(request, manifest)
