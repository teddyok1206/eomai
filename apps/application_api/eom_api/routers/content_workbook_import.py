"""Bounded Excel upload and proposal transport; Catalog owns import and matching."""

from __future__ import annotations

import hashlib
from typing import Annotated
from urllib.parse import quote

from eom_api_contracts import ProblemDetails, SingleResponse
from eom_catalog_contracts.content_workbook_import import (
    CONTENT_WORKBOOK_MAX_BYTES,
    CONTENT_WORKBOOK_MAX_ROWS,
    CommitContentWorkbookRequest,
    ContentWorkbookImportResult,
    ContentWorkbookPreview,
    PrepareContentWorkbookRequest,
    ReadContentWorkbookRequest,
)
from eom_catalog_contracts.content_workbook_template import render_template
from eom_catalog_contracts.item_origin import OriginArtifactMemberPointer
from eom_catalog_contracts.models import FrozenModel
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/content-planning/imports", tags=["content-planning"])
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_READ_PERMISSIONS = frozenset(
    {PermissionKey.DELIVERABLE_READ, PermissionKey.ITEM_READ, PermissionKey.CONTENT_INTAKE_READ}
)


class ReadContentWorkbookInput(FrozenModel):
    proposal: OriginArtifactMemberPointer
    offset: int = Field(default=0, strict=True, ge=0, le=CONTENT_WORKBOOK_MAX_ROWS)
    limit: int = Field(default=100, strict=True, ge=1, le=100)


class CommitContentWorkbookInput(FrozenModel):
    proposal: OriginArtifactMemberPointer


def _require_reads(authentication: Auth) -> None:
    if not authentication.permissions >= _READ_PERMISSIONS:
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Workbook read denied")


def _identity(request: Request) -> dict[str, object]:
    actor = request.state.request_context.actor()
    return {
        "actor_id": actor.operator_id,
        "session_id": actor.session_id,
        "request_id": actor.request_id,
        "authentication_time": actor.authentication_time,
    }


@router.get(
    "/template",
    operation_id="content_workbook_template",
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.CONTENT_INTAKE_READ.value,
        ]
    },
    response_class=Response,
    responses={
        200: {"content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def download_content_workbook_template(authentication: Auth) -> Response:
    _require_reads(authentication)
    filename = "EOM_교재_문항배치_입력양식_v1.xlsx"
    return Response(
        render_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                'attachment; filename="eom-content-placement-template-v1.xlsx"; '
                f"filename*=UTF-8''{quote(filename)}"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.put(
    "",
    operation_id="content_workbook_prepare",
    response_model=SingleResponse[ContentWorkbookPreview],
    responses={408: {"model": ProblemDetails, "description": "Workbook upload timed out"}},
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
    openapi_extra={
        "x-eom-additional-permissions": sorted(value.value for value in _READ_PERMISSIONS),
        "requestBody": {
            "required": True,
            "content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        },
    },
)
async def prepare_content_workbook(
    request: Request,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    content_length: Annotated[int, Header(ge=8, le=CONTENT_WORKBOOK_MAX_BYTES)],
    original_filename: Annotated[
        str, Query(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
    ],
) -> SingleResponse[ContentWorkbookPreview]:
    _require_reads(authentication)
    content = bytearray()
    digest = hashlib.sha256()
    async for chunk in request.stream():
        if len(content) + len(chunk) > content_length:
            raise ApiError(400, "CONTENT_IMPORT_LENGTH_INVALID", "Invalid upload", "Size differs")
        content.extend(chunk)
        digest.update(chunk)
    if len(content) != content_length:
        raise ApiError(400, "CONTENT_IMPORT_LENGTH_INVALID", "Invalid upload", "Size differs")
    command = PrepareContentWorkbookRequest.model_validate(
        {
            **_identity(request),
            "original_filename": original_filename,
            "content_length": content_length,
            "sha256": "sha256:" + digest.hexdigest(),
            "idempotency_key": idempotency_key,
        }
    )
    result = await run_in_threadpool(
        request.app.state.services.catalog_application.content_workbook,
        command,
        content=bytes(content),
    )
    if not isinstance(result, ContentWorkbookPreview):
        raise ApiError(502, "CONTENT_IMPORT_RESPONSE_INVALID", "Invalid result", "Preview expected")
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CONTENT_WORKBOOK_PREPARED",
        operation_id="content_workbook_prepare",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="artifact",
        target_id=result.proposal.artifact_id,
    )
    return one(request, result)


@router.post(
    "/query",
    operation_id="content_workbook_query",
    response_model=SingleResponse[ContentWorkbookPreview],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
    openapi_extra={
        "x-eom-additional-permissions": [
            PermissionKey.ITEM_READ.value,
            PermissionKey.CONTENT_INTAKE_READ.value,
        ],
        "x-eom-read-only": True,
    },
)
def read_content_workbook(
    request: Request, body: ReadContentWorkbookInput, authentication: Auth
) -> SingleResponse[ContentWorkbookPreview]:
    _require_reads(authentication)
    query = ReadContentWorkbookRequest.model_validate({**_identity(request), **body.model_dump()})
    result = request.app.state.services.catalog_application.content_workbook(query)
    if not isinstance(result, ContentWorkbookPreview):
        raise ApiError(502, "CONTENT_IMPORT_RESPONSE_INVALID", "Invalid result", "Preview expected")
    return one(request, result)


@router.post(
    "/commit",
    operation_id="content_workbook_commit",
    response_model=SingleResponse[ContentWorkbookImportResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
    openapi_extra={
        "x-eom-additional-permissions": sorted(value.value for value in _READ_PERMISSIONS),
    },
)
def commit_content_workbook(
    request: Request,
    body: CommitContentWorkbookInput,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[ContentWorkbookImportResult]:
    _require_reads(authentication)
    command = CommitContentWorkbookRequest.model_validate(
        {**_identity(request), **body.model_dump(), "idempotency_key": idempotency_key}
    )
    result = request.app.state.services.catalog_application.content_workbook(command)
    if not isinstance(result, ContentWorkbookImportResult):
        raise ApiError(502, "CONTENT_IMPORT_RESPONSE_INVALID", "Invalid result", "Import expected")
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="CONTENT_WORKBOOK_IMPORTED",
        operation_id="content_workbook_commit",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="content_edition",
        target_id=result.composition.edition_id,
    )
    return one(request, result)
