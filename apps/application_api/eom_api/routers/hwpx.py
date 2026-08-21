"""Authenticated HWPX capability, build resource, and secure download endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.hwpx import (
    CreateHwpxBuildRequest,
    HwpxBuildState,
    HwpxBuildView,
    HwpxCapabilityState,
    HwpxCapabilityView,
    HwpxSupports,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one, run_command
from eom_api.services.hwpx_projection import project_hwpx_build

router = APIRouter(tags=["hwpx"])
HWPX_CONTENT_TYPE = "application/vnd.hancom.hwpx"


@router.get(
    "/capabilities/hwpx",
    operation_id="hwpx_capability_get",
    response_model=SingleResponse[HwpxCapabilityView],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def capability(request: Request) -> SingleResponse[HwpxCapabilityView]:
    value = request.app.state.services.hwpx_capability.inspect()
    return one(
        request,
        HwpxCapabilityView(
            state=HwpxCapabilityState(value.state),
            renderer="kordoc",
            renderer_version="4.9.0",
            supports=HwpxSupports(
                native_equations=value.native_equations,
                native_tables=value.native_tables,
            ),
            manager_registered=value.manager_registered,
            detail_code=value.detail_code,
        ),
    )


@router.post(
    "/item-revisions/{item_revision_id}/hwpx-builds",
    operation_id="hwpx_build_create",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_BUILD_CREATE))],
)
def create_build(
    request: Request,
    item_revision_id: str,
    body: CreateHwpxBuildRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    if request.app.state.services.hwpx_capability.inspect().state != "READY":
        raise ApiError(
            503,
            "HWPX_RENDERER_NOT_READY",
            "HWPX renderer is not ready",
            "The pinned isolated HWPX renderer has not passed capability preflight.",
        )

    def execute() -> CommandResult:
        domain_key = request.app.state.services.idempotency.submission_key(
            operator_id=authentication.operator.operator_id,
            endpoint_key="hwpx_build_create",
            raw_key=idempotency_key,
        )
        record, _ = request.app.state.services.hwpx.request_build(
            item_revision_id,
            options=body.options.model_dump(mode="json"),
            operator_id=authentication.operator.operator_id,
            idempotency_key=domain_key,
        )
        return CommandResult(
            command_id=f"hwpxcmd_{record.build_id.removeprefix('hwpxbuild_')}",
            resource_type="hwpx_build",
            resource_id=record.build_id,
            status="ACCEPTED",
            resource_version=record.resource_version,
            status_url=f"/api/v1/hwpx-builds/{record.build_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="hwpx_build",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/hwpx-builds/{build_id}",
    operation_id="hwpx_build_get",
    response_model=SingleResponse[HwpxBuildView],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def get_build(request: Request, build_id: str) -> SingleResponse[HwpxBuildView]:
    return one(request, project_hwpx_build(request.app.state.services.hwpx.get_build(build_id)))


@router.get(
    "/hwpx-builds",
    operation_id="hwpx_build_list",
    response_model=ListResponse[HwpxBuildView],
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ, admin_only=True))],
)
def list_builds(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1024),
    state: HwpxBuildState | None = None,
) -> ListResponse[HwpxBuildView]:
    page = request.app.state.services.queries.list_hwpx_builds(
        limit=limit,
        cursor=cursor,
        state=state.value if state else None,
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/hwpx-builds/{build_id}/download",
    operation_id="hwpx_build_download",
    dependencies=[Depends(require_permission(PermissionKey.HWPX_READ))],
)
def download(request: Request, build_id: str) -> StreamingResponse:
    value = request.app.state.services.hwpx_downloads.download(build_id)
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="HWPX_DOWNLOAD_AUTHORIZED",
        operation_id="hwpx_build_download",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="hwpx_build",
        target_id=build_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type=HWPX_CONTENT_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{value.filename}"',
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
