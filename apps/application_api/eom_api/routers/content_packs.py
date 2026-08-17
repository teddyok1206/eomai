"""Content Pack release and activation endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.content_packs import (
    ActivateContentPackRequest,
    ContentPackActivationView,
    ContentPackReleaseView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import Auth, ExpectedVersion, IdempotencyKey, etag, require_permission
from eom_api.routers.common import many, one, run_command

router = APIRouter(tags=["content-packs"])


@router.get(
    "/content-pack-releases",
    operation_id="content_pack_release_list",
    response_model=ListResponse[ContentPackReleaseView],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_READ))],
)
def list_releases(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=1024),
    pack_key: str | None = Query(default=None, max_length=64),
) -> ListResponse[ContentPackReleaseView]:
    page = request.app.state.services.queries.list_pack_releases(
        limit=limit, cursor=cursor, pack_key=pack_key
    )
    return many(
        request,
        page.data,
        limit=limit,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/content-pack-releases/{release_id}",
    operation_id="content_pack_release_get",
    response_model=SingleResponse[ContentPackReleaseView],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_READ))],
)
def get_release(
    request: Request, release_id: str, response: Response
) -> SingleResponse[ContentPackReleaseView]:
    value = request.app.state.services.queries.pack_release(release_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/content-pack-activations",
    operation_id="content_pack_activation_list",
    response_model=ListResponse[ContentPackActivationView],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_READ))],
)
def list_activations(request: Request) -> ListResponse[ContentPackActivationView]:
    values = request.app.state.services.queries.list_activations()
    return many(request, values, limit=200)


@router.get(
    "/content-pack-resolutions",
    operation_id="content_pack_resolution_list",
    response_model=ListResponse[ContentPackActivationView],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_READ))],
)
def list_resolutions(request: Request) -> ListResponse[ContentPackActivationView]:
    values = request.app.state.services.queries.list_activations(active_only=True)
    return many(request, values, limit=200)


@router.post(
    "/content-pack-releases/{release_id}/release",
    operation_id="content_pack_release",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_RELEASE, fresh=True))],
)
def release_pack(
    request: Request,
    release_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication

    def execute() -> CommandResult:
        command_id, version = request.app.state.services.commands.release_pack(
            release_id, request.state.request_context.actor(), expected_version=expected_version
        )
        return CommandResult(
            command_id=command_id,
            resource_type="content_pack_release",
            resource_id=release_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/content-pack-releases/{release_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body={"action": "release"},
            resource_type="content_pack_release",
            callback=execute,
        ),
    )


@router.post(
    "/content-pack-releases/{release_id}/activations",
    operation_id="content_pack_activate",
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.CONTENT_PACK_ACTIVATE, fresh=True))],
)
def activate_pack(
    request: Request,
    release_id: str,
    body: ActivateContentPackRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, activation_id, version = request.app.state.services.commands.activate_pack(
            release_id,
            body,
            request.state.request_context.actor(),
            expected_version=expected_version,
        )
        return CommandResult(
            command_id=command_id,
            resource_type="content_pack_activation",
            resource_id=activation_id,
            status="COMPLETED",
            resource_version=version,
            status_url="/api/v1/content-pack-activations",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="content_pack_activation",
            callback=execute,
        ),
    )
