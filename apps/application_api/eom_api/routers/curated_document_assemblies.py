"""Persist an ordered, pinned mixed-source selection; delivery is a separate use case."""

from __future__ import annotations

from eom_api_contracts import ListResponse, SingleResponse
from eom_api_contracts.curated_document_assembly import CuratedDocumentAssemblyDraftV1
from eom_catalog_contracts.curated_document_assembly import CuratedDocumentAssemblyManifestV1
from eom_catalog_contracts.curated_document_assembly_application import (
    CuratedDocumentAssemblyListEntryV1,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one

router = APIRouter(prefix="/item-db/assemblies", tags=["item-db"])


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
    body: CuratedDocumentAssemblyDraftV1,
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
