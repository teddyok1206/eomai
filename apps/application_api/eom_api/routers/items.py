"""Item Registry query and retirement endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.items import (
    ItemComponentView,
    ItemRelationshipView,
    ItemRetirementRequest,
    ItemRevisionView,
    ItemView,
    StructuredItemContentImportRequest,
)
from eom_api_contracts.usage import UsageRecordView
from eom_catalog_contracts import AssessmentItemContent
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(tags=["items"])


@router.post(
    "/item-revisions/{item_revision_id}/structured-content-imports",
    operation_id="item_structured_content_import",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(
                PermissionKey.ITEM_STRUCTURED_CONTENT_IMPORT,
                admin_only=True,
            )
        )
    ],
)
def import_structured_content(
    request: Request,
    item_revision_id: str,
    body: StructuredItemContentImportRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, revision_id, version = (
            request.app.state.services.commands.import_structured_item_content(
                item_revision_id,
                body,
                request.state.request_context.actor(),
                expected_version=expected_version,
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type="item_revision",
            resource_id=revision_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/item-revisions/{revision_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="item_revision",
            callback=execute,
        ),
    )


@router.get(
    "/items",
    operation_id="item_list",
    response_model=ListResponse[ItemView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def list_items(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    state: str | None = Query(default=None, max_length=40),
) -> ListResponse[ItemView]:
    page = request.app.state.services.queries.list_items(limit=limit, cursor=cursor, state=state)
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/items/{item_id}",
    operation_id="item_get",
    response_model=SingleResponse[ItemView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def get_item(request: Request, item_id: str, response: Response) -> SingleResponse[ItemView]:
    value = request.app.state.services.queries.item(item_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/items/{item_id}/revisions",
    operation_id="item_revision_list",
    response_model=ListResponse[ItemRevisionView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def list_revisions(request: Request, item_id: str) -> ListResponse[ItemRevisionView]:
    values = request.app.state.services.queries.item_revisions(item_id)
    return many(request, values, limit=200)


@router.get(
    "/item-revisions/{item_revision_id}",
    operation_id="item_revision_get",
    response_model=SingleResponse[ItemRevisionView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def get_revision(
    request: Request, item_revision_id: str, response: Response
) -> SingleResponse[ItemRevisionView]:
    value = request.app.state.services.queries.revision(item_revision_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/item-revisions/{item_revision_id}/structured-content",
    operation_id="item_structured_content_get",
    response_model=SingleResponse[AssessmentItemContent],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def get_structured_content(
    request: Request,
    item_revision_id: str,
) -> SingleResponse[AssessmentItemContent]:
    return one(request, request.app.state.services.registry.load_item_content(item_revision_id))


@router.get(
    "/item-revisions/{item_revision_id}/components",
    operation_id="item_component_list",
    response_model=ListResponse[ItemComponentView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def list_components(request: Request, item_revision_id: str) -> ListResponse[ItemComponentView]:
    values = request.app.state.services.queries.components(item_revision_id)
    return many(request, values, limit=200)


@router.get(
    "/items/{item_id}/relationships",
    operation_id="item_relationship_list",
    response_model=ListResponse[ItemRelationshipView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def relationships(request: Request, item_id: str) -> ListResponse[ItemRelationshipView]:
    values = request.app.state.services.queries.relationships(item_id)
    return many(request, values, limit=200)


@router.get(
    "/items/{item_id}/usage-history",
    operation_id="item_usage_history",
    response_model=ListResponse[UsageRecordView],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_READ))],
)
def usage_history(request: Request, item_id: str) -> ListResponse[UsageRecordView]:
    request.app.state.services.queries.item(item_id)
    values = request.app.state.services.queries.list_usage_records(item_id=item_id)
    return many(request, values, limit=200)


@router.post(
    "/items/{item_id}/retirements",
    operation_id="item_retire",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.ITEM_RETIRE))],
)
def retire_item(
    request: Request,
    item_id: str,
    body: ItemRetirementRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, version = request.app.state.services.commands.retire_item(
            item_id,
            body,
            request.state.request_context.actor(),
            expected_version=expected_version,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="item",
            resource_id=item_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/items/{item_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="item",
            callback=execute,
        ),
    )
