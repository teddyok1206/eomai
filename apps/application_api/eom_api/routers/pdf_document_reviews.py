"""Authenticated upload-intent endpoints for immutable PDF document review."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts import CommandResult, SingleResponse
from eom_api_contracts.document_review import (
    CreatePdfDocumentReviewUploadIntentRequest,
    PdfDocumentReviewUploadIntentView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from eom_api.dependencies import Auth, IdempotencyKey, etag, require_permission
from eom_api.errors import ApiError
from eom_api.routers.common import one, run_command
from eom_api.services.command_adapter import new_api_command_id

router = APIRouter(prefix="/pdf-document-reviews", tags=["pdf-document-reviews"])


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
