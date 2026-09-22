"""Authenticated upload-intent endpoints for immutable PDF document review."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.document_review import (
    CreatePdfDocumentReviewUploadIntentRequest,
    PdfDocumentReviewUploadIntentView,
    PdfDocumentReviewView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import many, one, run_command
from eom_api.services.command_adapter import new_api_command_id

router = APIRouter(prefix="/pdf-document-reviews", tags=["pdf-document-reviews"])


@router.get(
    "",
    operation_id="pdf_document_review_list",
    response_model=ListResponse[PdfDocumentReviewView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def list_pdf_document_reviews(
    request: Request,
    authentication: Auth,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1024),
) -> ListResponse[PdfDocumentReviewView]:
    page = request.app.state.services.queries.list_pdf_document_reviews(
        actor_id=authentication.operator.operator_id,
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
    "/upload-intents",
    operation_id="pdf_document_review_upload_intent_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def create_pdf_document_review_upload_intent(
    request: Request,
    body: CreatePdfDocumentReviewUploadIntentRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    def execute() -> CommandResult:
        view = request.app.state.services.pdf_document_reviews.create_upload_intent(
            body,
            actor_id=authentication.operator.operator_id,
            observed_at=datetime.now(UTC),
        )
        return CommandResult(
            command_id=new_api_command_id(),
            resource_type="pdf_document_review_upload_intent",
            resource_id=view.upload_intent_id,
            status="COMPLETED",
            resource_version=view.resource_version,
            status_url=f"/api/v1/pdf-document-reviews/upload-intents/{view.upload_intent_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="pdf_document_review_upload_intent",
            callback=execute,
            response_status=201,
        ),
    )


@router.get(
    "/upload-intents/{upload_intent_id}",
    operation_id="pdf_document_review_upload_intent_get",
    response_model=SingleResponse[PdfDocumentReviewUploadIntentView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_pdf_document_review_upload_intent(
    request: Request,
    upload_intent_id: str,
    authentication: Auth,
    response: Response,
) -> SingleResponse[PdfDocumentReviewUploadIntentView]:
    value = request.app.state.services.pdf_document_reviews.upload_intent(
        upload_intent_id,
        actor_id=authentication.operator.operator_id,
    )
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.put(
    "/upload-intents/{upload_intent_id}/content",
    operation_id="pdf_document_review_upload_content",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_pdf_document_review_content(
    request: Request,
    upload_intent_id: str,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    intent = request.app.state.services.pdf_document_reviews.upload_intent(
        upload_intent_id,
        actor_id=authentication.operator.operator_id,
    )
    raw_length = request.headers.get("content-length", "")
    if not raw_length.isdigit() or int(raw_length) != intent.content_length:
        raise ApiError(
            422,
            "PDF_DOCUMENT_REVIEW_UPLOAD_LENGTH_MISMATCH",
            "PDF upload length differs",
            "The Content-Length must exactly match the upload intent.",
        )
    async with request.app.state.services.pdf_review_upload_stager.stage(
        request,
        declared_length=int(raw_length),
    ) as upload:

        def execute() -> CommandResult:
            command_id, view = request.app.state.services.pdf_document_reviews.accept_upload(
                upload_intent_id,
                upload,
                actor=request.state.request_context.actor(),
                observed_at=datetime.now(UTC),
            )
            assert view.workflow_id is not None
            assert view.review_url is not None
            return CommandResult(
                command_id=command_id,
                resource_type="pdf_document_review",
                resource_id=view.workflow_id,
                status="ACCEPTED",
                resource_version=view.resource_version,
                status_url=view.review_url,
            )

        result = await run_in_threadpool(
            run_command,
            request,
            raw_key=idempotency_key,
            body={
                "upload_intent_id": upload_intent_id,
                "content_length": upload.content_length,
                "sha256": upload.sha256,
            },
            resource_type="pdf_document_review",
            callback=execute,
            response_status=202,
        )
    return one(request, result)


@router.get(
    "/{workflow_id}",
    operation_id="pdf_document_review_get",
    response_model=SingleResponse[PdfDocumentReviewView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_pdf_document_review(
    request: Request,
    authentication: Auth,
    response: Response,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
) -> SingleResponse[PdfDocumentReviewView]:
    value = request.app.state.services.queries.pdf_document_review(
        actor_id=authentication.operator.operator_id,
        workflow_id=workflow_id,
    )
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/{workflow_id}/pages/{page_number}/image",
    operation_id="pdf_document_review_page_image_get",
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_pdf_document_review_page_image(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    page_number: int = Path(ge=1, le=32),
) -> StreamingResponse:
    document, page = request.app.state.services.queries.pdf_document_review_page_pointer(
        actor_id=authentication.operator.operator_id,
        workflow_id=workflow_id,
        page_number=page_number,
    )
    value = request.app.state.services.catalog_application.download_pdf_document_review_page(
        document_id=document.document_id,
        document_revision_id=document.document_revision_id,
        page_number=page.page_number,
        page_image=page.page_image,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="PDF_DOCUMENT_REVIEW_PAGE_READ_AUTHORIZED",
        operation_id="pdf_document_review_page_image_get",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="pdf_document_review",
        target_id=workflow_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type="image/png",
        headers={
            "Content-Length": str(value.content_length),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )
