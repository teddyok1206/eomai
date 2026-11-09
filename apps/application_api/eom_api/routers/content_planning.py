"""Content editing transport; Catalog owns all state, pins and idempotent replay."""

from __future__ import annotations

from eom_api_contracts import SingleResponse
from eom_catalog_contracts.content_delivery import ContentDeliveryPrepared, PrepareContentDelivery
from eom_catalog_contracts.content_planning_commands import (
    ContentPlanningCommand,
    ContentPlanningWriteResult,
    EditContentEdition,
)
from eom_catalog_contracts.content_planning_queries import (
    ContentPlanningQuery,
    ContentPlanningQueryResult,
)
from eom_catalog_contracts.content_print_commands import (
    ContentPrintCommand,
    ContentPrintMutationResult,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/content-planning", tags=["content-planning"])


@router.post(
    "/deliveries",
    operation_id="content_planning_delivery_prepare",
    response_model=SingleResponse[ContentDeliveryPrepared],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_BUILD_CREATE))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.DELIVERABLE_READ.value,
            PermissionKey.ITEM_READ.value,
        ]
    },
)
def prepare_content_delivery(
    request: Request,
    body: PrepareContentDelivery,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ContentDeliveryPrepared]:
    if not {PermissionKey.DELIVERABLE_READ, PermissionKey.ITEM_READ} <= authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Content read denied")
    result = request.app.state.services.catalog_application.prepare_content_delivery(
        body,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CONTENT_DELIVERY_PREPARED",
        operation_id="content_planning_delivery_prepare",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="content_edition",
        target_id=result.edition_id,
    )
    return one(request, result)


@router.post(
    "/prints",
    operation_id="content_planning_print",
    response_model=SingleResponse[ContentPrintMutationResult],
    dependencies=[Depends(require_permission(PermissionKey.USAGE_FULFILL_PLAN))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.DELIVERABLE_READ.value,
            PermissionKey.ITEM_READ.value,
        ]
    },
)
def record_content_print(
    request: Request,
    body: ContentPrintCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ContentPrintMutationResult]:
    if not {PermissionKey.DELIVERABLE_READ, PermissionKey.ITEM_READ} <= authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Content read denied")
    result = request.app.state.services.catalog_application.record_content_print(
        body,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CONTENT_PRINT_COMMAND_COMPLETED",
        operation_id="content_planning_print",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="content_print",
        target_id=result.record.print_record_id,
    )
    return one(request, result)


@router.post(
    "/commands",
    operation_id="content_planning_write",
    response_model=SingleResponse[ContentPlanningWriteResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
    openapi_extra={
        "x-eom-conditional-permissions": {
            "CREATE_CONTENT": [PermissionKey.DELIVERABLE_CREATE.value],
            "CREATE_EDITION": [PermissionKey.DELIVERABLE_CREATE.value],
            "COPY_EDITION": [PermissionKey.DELIVERABLE_CREATE.value],
            "EDIT_EDITION": [PermissionKey.DELIVERABLE_UPDATE.value],
        }
    },
)
def write_content_planning(
    request: Request,
    body: ContentPlanningCommand,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ContentPlanningWriteResult]:
    required = (
        PermissionKey.DELIVERABLE_UPDATE
        if isinstance(body, EditContentEdition)
        else PermissionKey.DELIVERABLE_CREATE
    )
    if not {required, PermissionKey.ITEM_READ} <= authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Content editing denied")
    result = request.app.state.services.catalog_application.write_content_planning(
        body,
        actor=request.state.request_context.actor(),
        idempotency_key=idempotency_key,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CONTENT_PLANNING_COMMAND_COMPLETED",
        operation_id="content_planning_write",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="content_edition",
        target_id=result.composition.edition_id,
    )
    return one(request, result)


@router.post(
    "/query",
    operation_id="content_planning_query",
    response_model=SingleResponse[ContentPlanningQueryResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
    openapi_extra={
        "x-eom-additional-permissions": [PermissionKey.ITEM_READ.value],
        "x-eom-read-only": True,
    },
)
def query_content_planning(
    request: Request, body: ContentPlanningQuery, authentication: Auth
) -> SingleResponse[ContentPlanningQueryResult]:
    if PermissionKey.ITEM_READ not in authentication.permissions:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Item read denied")
    return one(
        request,
        request.app.state.services.catalog_application.query_content_planning(
            body,
            actor=request.state.request_context.actor(),
        ),
    )
