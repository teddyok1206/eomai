"""Authenticated durable intake; expensive document learning runs off-request."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from eom_api_contracts import SingleResponse
from eom_catalog_contracts.material_learning import MaterialArtifactMember, MaterialLearningUpload
from eom_catalog_contracts.material_learning_intake import (
    ControlMaterialLearningRunCommand,
    GetMaterialLearningRunQuery,
    GetMaterialLearningTaskQuery,
    ListMaterialLearningRunsQuery,
    MaterialLearningAcceptance,
    MaterialLearningControlResult,
    MaterialLearningRetryResult,
    MaterialLearningRunDetail,
    MaterialLearningRunList,
    MaterialLearningSourceSelection,
    MaterialLearningTaskDetail,
    MaterialSourceUploadCommand,
    MaterialSourceUploadReceipt,
    RetryMaterialLearningRunCommand,
)
from eom_catalog_contracts.material_native_intake import parse_material_learning_create
from eom_catalog_contracts.material_native_prepare import (
    MATERIAL_NATIVE_METADATA_MAX_BYTES,
    MATERIAL_NATIVE_UPLOAD_MAX_BYTES,
    MATERIAL_NATIVE_UPLOAD_MEDIA_TYPE,
    MATERIAL_NATIVE_XLSX_MAX_BYTES,
    NativeMaterialExamUpload,
    PrepareNativeMaterialExamCommand,
)
from eom_catalog_contracts.models import FrozenModel, UtcDatetime
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Header, Path, Query, Request
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one

router = APIRouter(prefix="/material-learning", tags=["material-learning"])


class CreateMaterialLearningRequest(FrozenModel):
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=1, max_length=2)


class CreateNativeMaterialLearningRequest(FrozenModel):
    schema_version: Literal["material-learning-create/2.0"]
    upload: MaterialLearningUpload
    sources: tuple[MaterialLearningSourceSelection, ...] = Field(min_length=2, max_length=2)
    native_bundle: MaterialArtifactMember


class MaterialLearningControlRequest(FrozenModel):
    action: Literal["PAUSE", "RESUME"]
    expected_updated_at: UtcDatetime


class MaterialLearningRetryRequest(FrozenModel):
    expected_updated_at: UtcDatetime


@router.post(
    "/{run_id}/retry",
    operation_id="material_learning_retry",
    response_model=SingleResponse[MaterialLearningRetryResult],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, admin_only=True))
    ],
)
def retry_material_learning(
    request: Request,
    body: MaterialLearningRetryRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    run_id: str = Path(pattern=r"^materialrun_[0-9a-f]{32}$"),
) -> SingleResponse[MaterialLearningRetryResult]:
    if idempotency_key != f"material-retry-v1:{run_id}:{body.expected_updated_at.isoformat()}":
        raise ApiError(
            422,
            "MATERIAL_LEARNING_RETRY_KEY_INVALID",
            "Invalid retry key",
            "Reuse the exact observed predecessor run state.",
        )
    command = RetryMaterialLearningRunCommand(
        actor_id=authentication.operator.operator_id,
        run_id=run_id,
        expected_updated_at=body.expected_updated_at,
    )
    return one(
        request, request.app.state.services.catalog_application.retry_material_learning_run(command)
    )


@router.get(
    "/{run_id}/tasks/{task_id}",
    operation_id="material_learning_task_read",
    response_model=SingleResponse[MaterialLearningTaskDetail],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_READ, admin_only=True))
    ],
)
def read_material_learning_task(
    request: Request,
    authentication: Auth,
    run_id: str = Path(pattern=r"^materialrun_[0-9a-f]{32}$"),
    task_id: str = Path(pattern=r"^materialtask_[0-9a-f]{32}$"),
) -> SingleResponse[MaterialLearningTaskDetail]:
    query = GetMaterialLearningTaskQuery(
        actor_id=authentication.operator.operator_id, run_id=run_id, task_id=task_id
    )
    return one(
        request, request.app.state.services.catalog_application.read_material_learning_task(query)
    )


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


def _unique_metadata_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate metadata key")
        value[key] = item
    return value


def _invalid_native_upload() -> ApiError:
    return ApiError(
        422,
        "MATERIAL_NATIVE_UPLOAD_INVALID",
        "Invalid native exam upload",
        "Provide paired native sources and one bounded metadata workbook.",
    )


@router.post(
    "/native-exams",
    operation_id="material_native_exam_prepare",
    status_code=202,
    response_model=SingleResponse[MaterialLearningAcceptance],
    dependencies=[
        Depends(require_permission(PermissionKey.KNOWLEDGE_ANALYSIS_CREATE, admin_only=True))
    ],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                MATERIAL_NATIVE_UPLOAD_MEDIA_TYPE: {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        }
    },
)
async def prepare_native_material_exam(
    request: Request,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    content_length: Annotated[int, Header(ge=9, le=MATERIAL_NATIVE_UPLOAD_MAX_BYTES)],
) -> SingleResponse[MaterialLearningAcceptance]:
    # One bounded XLSX materialization; all workbook parsing and canonical commits
    # stay with Catalog, not the public API or browser.
    prefix = bytearray()
    content = bytearray()
    digest = hashlib.sha256()
    metadata: NativeMaterialExamUpload | None = None
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > content_length:
            raise _invalid_native_upload()
        if metadata is None:
            delimiter = chunk.find(b"\n")
            prefix.extend(chunk if delimiter < 0 else chunk[:delimiter])
            if len(prefix) > MATERIAL_NATIVE_METADATA_MAX_BYTES:
                raise _invalid_native_upload()
            if delimiter < 0:
                continue
            try:
                metadata = NativeMaterialExamUpload.model_validate(
                    json.loads(prefix.decode("utf-8"), object_pairs_hook=_unique_metadata_object)
                )
            except (ValueError, RecursionError, JsonSchemaValidationError) as exc:
                raise _invalid_native_upload() from exc
            chunk = chunk[delimiter + 1 :]
        if len(content) + len(chunk) > MATERIAL_NATIVE_XLSX_MAX_BYTES:
            raise _invalid_native_upload()
        content.extend(chunk)
        digest.update(chunk)
    if received != content_length or metadata is None or len(content) < 8:
        raise _invalid_native_upload()
    try:
        command = PrepareNativeMaterialExamCommand(
            actor_id=authentication.operator.operator_id,
            idempotency_key=idempotency_key,
            upload=metadata.upload,
            sources=metadata.sources,
            source_namespace=metadata.source_namespace,
            exam_key=metadata.exam_key,
            workbook_filename=metadata.workbook_filename,
            workbook_sha256="sha256:" + digest.hexdigest(),
            workbook_bytes=len(content),
        )
    except (ValueError, JsonSchemaValidationError) as exc:
        raise _invalid_native_upload() from exc
    acceptance = await run_in_threadpool(
        request.app.state.services.catalog_application.prepare_native_material_exam,
        command,
        content=bytes(content),
    )
    return one(request, acceptance)


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
    body: CreateMaterialLearningRequest | CreateNativeMaterialLearningRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[MaterialLearningAcceptance]:
    # Idempotency belongs to the durable Catalog command; an HTTP timeout must
    # replay this exact key, not leave a separate API command stuck IN_PROGRESS.
    try:
        command = parse_material_learning_create(
            {
                **body.model_dump(mode="json"),
                "actor_id": authentication.operator.operator_id,
                "idempotency_key": idempotency_key,
                "operation": "CREATE_MATERIAL_LEARNING",
            }
        )
    except (ValueError, JsonSchemaValidationError) as exc:
        raise ApiError(
            422,
            "MATERIAL_LEARNING_REQUEST_INVALID",
            "Invalid material learning request",
            "Provide sources owned by the authenticated operator and an explicit supported schema.",
        ) from exc
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
