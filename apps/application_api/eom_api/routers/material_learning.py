"""Authenticated durable intake; expensive document learning runs off-request."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_api_contracts import SingleResponse
from eom_catalog_contracts.material_learning import MaterialLearningUpload
from eom_catalog_contracts.material_learning_intake import (
    ControlMaterialLearningRunCommand,
    CreateMaterialLearningCommand,
    GetMaterialLearningRunQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningAcceptance,
    MaterialLearningControlResult,
    MaterialLearningRunDetail,
    MaterialLearningRunList,
    MaterialLearningSourceSelection,
    MaterialSourceUploadCommand,
    MaterialSourceUploadReceipt,
)
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Path, Query, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/material-learning", tags=["material-learning"])


class CreateMaterialLearningRequest(FrozenModel):
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=1, max_length=2)


class MaterialLearningControlRequest(FrozenModel):
    action: Literal["PAUSE", "RESUME"]
    expected_updated_at: UtcDatetime


@router.post(
    "/{run_id}/control",
    operation_id="material_learning_control",
    response_model=SingleResponse[MaterialLearningControlResult],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, admin_only=True))
    ],
)
def control_material_learning(
    request: Request,
    body: MaterialLearningControlRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    run_id: str = Path(pattern=r"^materialrun_[0-9a-f]{32}$"),
) -> SingleResponse[MaterialLearningControlResult]:
    expected_key = (
        f"material-control-v1:{run_id}:{body.action}:{body.expected_updated_at.isoformat()}"
    )
    if idempotency_key != expected_key:
        raise ApiError(
            422,
            "MATERIAL_LEARNING_CONTROL_KEY_INVALID",
            "Invalid control key",
            "Reuse the exact observed run state and action.",
        )
    command = ControlMaterialLearningRunCommand(
        actor_id=authentication.operator.operator_id,
        run_id=run_id,
        action=body.action,
        expected_updated_at=body.expected_updated_at,
    )
    return one(
        request,
        request.app.state.services.catalog_application.control_material_learning_run(command),
    )


@router.put(
    "/sources",
    operation_id="material_learning_source_upload",
    status_code=201,
    response_model=SingleResponse[MaterialSourceUploadReceipt],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, admin_only=True))
    ],
)
async def upload_material_source(
    request: Request,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    content_length: Annotated[int, Header(ge=8, le=256 * 1024 * 1024)],
    rights_confirmed: Annotated[str, Header(alias="X-EOM-Rights-Confirmed")],
    original_filename: str = Query(min_length=1, max_length=255),
) -> SingleResponse[MaterialSourceUploadReceipt]:
    if rights_confirmed != "true":
        raise ApiError(
            422,
            "MATERIAL_LEARNING_RIGHTS_CONFIRMATION_REQUIRED",
            "Rights confirmation required",
            "Confirm the right to process and internally use this source.",
        )
    services = request.app.state.services
    async with services.pdf_review_upload_stager.stage_detected(
        request, declared_length=content_length
    ) as staged:
        command = MaterialSourceUploadCommand(
            actor_id=authentication.operator.operator_id,
            original_filename=original_filename,
            source_format=staged.source_format,
            media_type=staged.media_type,
            content_length=staged.content_length,
            sha256=staged.sha256,
            rights_confirmed=True,
            idempotency_key=idempotency_key,
        )
        receipt = await run_in_threadpool(
            services.catalog_application.ingest_material_learning_source, staged.path, command
        )
    return one(request, receipt)


@router.post(
    "",
    operation_id="material_learning_create",
    status_code=202,
    response_model=SingleResponse[MaterialLearningAcceptance],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, admin_only=True))
    ],
)
def create_material_learning(
    request: Request,
    body: CreateMaterialLearningRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[MaterialLearningAcceptance]:
    # Idempotency belongs to the durable Catalog command; an HTTP timeout must
    # replay this exact key, not leave a separate API command stuck IN_PROGRESS.
    command = CreateMaterialLearningCommand(
        actor_id=authentication.operator.operator_id,
        idempotency_key=idempotency_key,
        upload=body.upload,
        sources=body.sources,
    )
    return one(
        request, request.app.state.services.catalog_application.create_material_learning(command)
    )


@router.get(
    "",
    operation_id="material_learning_list",
    response_model=SingleResponse[MaterialLearningRunList],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def list_material_learning(
    request: Request,
    authentication: Auth,
    limit: int = Query(default=20, ge=1, le=50),
) -> SingleResponse[MaterialLearningRunList]:
    query = ListMaterialLearningRunsQuery(actor_id=authentication.operator.operator_id, limit=limit)
    return one(
        request, request.app.state.services.catalog_application.list_material_learning_runs(query)
    )


@router.get(
    "/{run_id}",
    operation_id="material_learning_read",
    response_model=SingleResponse[MaterialLearningRunDetail],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def read_material_learning(
    request: Request,
    authentication: Auth,
    run_id: str = Path(pattern=r"^materialrun_[0-9a-f]{32}$"),
    after_ordinal: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=50, ge=1, le=100),
) -> SingleResponse[MaterialLearningRunDetail]:
    query = GetMaterialLearningRunQuery(
        actor_id=authentication.operator.operator_id,
        run_id=run_id,
        after_ordinal=after_ordinal,
        limit=limit,
    )
    return one(
        request, request.app.state.services.catalog_application.read_material_learning_run(query)
    )
