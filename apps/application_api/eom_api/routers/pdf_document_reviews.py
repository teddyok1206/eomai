"""Authenticated upload-intent endpoints for immutable PDF document review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.document_review import (
    ApplyDocumentReviewCorrectionRequest,
    CreateDocumentReviewAnnotationRequest,
    CreateDocumentReviewAnnotationRequestV2,
    CreateDocumentReviewSetRequest,
    CreateDocumentReviewUploadIntentRequestV2,
    CreatePdfDocumentReviewUploadIntentRequest,
    DocumentReviewAnnotationView,
    DocumentReviewCorrectionEligibilityView,
    DocumentReviewCorrectionView,
    DocumentReviewSetView,
    DocumentReviewUploadIntentViewV2,
    PairedDocumentReviewView,
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
    response_model=ListResponse[PdfDocumentReviewView | PairedDocumentReviewView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def list_pdf_document_reviews(
    request: Request,
    authentication: Auth,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=1024),
) -> ListResponse[PdfDocumentReviewView | PairedDocumentReviewView]:
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


@router.post(
    "/upload-intents-v2",
    operation_id="document_review_upload_intent_v2_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def create_document_review_upload_intent_v2(
    request: Request,
    body: CreateDocumentReviewUploadIntentRequestV2,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    def execute() -> CommandResult:
        view = request.app.state.services.pdf_document_reviews.create_document_upload_intent(
            body,
            actor_id=authentication.operator.operator_id,
            observed_at=datetime.now(UTC),
        )
        return CommandResult(
            command_id=new_api_command_id(),
            resource_type="document_review_upload_intent",
            resource_id=view.upload_intent_id,
            status="COMPLETED",
            resource_version=view.resource_version,
            status_url=(f"/api/v1/pdf-document-reviews/upload-intents-v2/{view.upload_intent_id}"),
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="document_review_upload_intent",
            callback=execute,
            response_status=201,
        ),
    )


@router.post(
    "/sets",
    operation_id="paired_document_review_set_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def create_paired_document_review_set(
    request: Request,
    body: CreateDocumentReviewSetRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    def execute() -> CommandResult:
        view = request.app.state.services.paired_document_reviews.create_set(
            body,
            actor_id=authentication.operator.operator_id,
            observed_at=datetime.now(UTC),
        )
        return CommandResult(
            command_id=new_api_command_id(),
            resource_type="paired_document_review_set",
            resource_id=view.review_set_id,
            status="COMPLETED",
            resource_version=view.resource_version,
            status_url=f"/api/v1/pdf-document-reviews/sets/{view.review_set_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="paired_document_review_set",
            callback=execute,
            response_status=201,
        ),
    )


@router.get(
    "/sets/{review_set_id}",
    operation_id="paired_document_review_set_get",
    response_model=SingleResponse[DocumentReviewSetView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_paired_document_review_set(
    request: Request,
    authentication: Auth,
    response: Response,
    review_set_id: str = Path(pattern=r"^docreviewset_[0-9a-f]{32}$"),
) -> SingleResponse[DocumentReviewSetView]:
    value = request.app.state.services.paired_document_reviews.review_set(
        review_set_id,
        actor_id=authentication.operator.operator_id,
    )
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.put(
    "/sets/{review_set_id}/documents/{document_role}/content",
    operation_id="paired_document_review_member_upload",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in (
                    "application/pdf",
                    "application/vnd.hancom.hwp",
                    "application/vnd.hancom.hwpx",
                )
            },
        }
    },
)
async def upload_paired_document_review_member(
    request: Request,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    review_set_id: str = Path(pattern=r"^docreviewset_[0-9a-f]{32}$"),
    document_role: Literal["QUESTION", "SOLUTION"] = Path(pattern=r"^(?:QUESTION|SOLUTION)$"),
) -> SingleResponse[CommandResult]:
    review_set = request.app.state.services.paired_document_reviews.review_set(
        review_set_id,
        actor_id=authentication.operator.operator_id,
    )
    member = next(value for value in review_set.documents if value.role == document_role)
    raw_length = request.headers.get("content-length", "")
    if not raw_length.isdigit() or int(raw_length) != member.content_length:
        raise ApiError(
            422,
            "PAIRED_DOCUMENT_REVIEW_UPLOAD_LENGTH_MISMATCH",
            "Document upload length differs",
            "The Content-Length must exactly match the declared review-set member.",
        )
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != member.media_type:
        raise ApiError(
            422,
            "PAIRED_DOCUMENT_REVIEW_UPLOAD_MEDIA_TYPE_MISMATCH",
            "Document upload media type differs",
            "The Content-Type must exactly match the declared review-set member.",
        )
    async with request.app.state.services.pdf_review_upload_stager.stage(
        request,
        declared_length=int(raw_length),
        source_format=member.source_format,
        media_type=member.media_type,
    ) as upload:

        def execute() -> CommandResult:
            command_id, view = (
                request.app.state.services.paired_document_reviews.accept_member_upload(
                    review_set_id,
                    document_role,
                    upload,
                    actor=request.state.request_context.actor(),
                    observed_at=datetime.now(UTC),
                )
            )
            if view.workflow_id is not None:
                if command_id is None:
                    raise RuntimeError("started paired review set lost its command pointer")
                return CommandResult(
                    command_id=command_id,
                    resource_type="pdf_document_review",
                    resource_id=view.workflow_id,
                    status="ACCEPTED",
                    resource_version=view.resource_version,
                    status_url=view.review_url,
                )
            return CommandResult(
                command_id=new_api_command_id(),
                resource_type="paired_document_review_set",
                resource_id=view.review_set_id,
                status="COMPLETED",
                resource_version=view.resource_version,
                status_url=f"/api/v1/pdf-document-reviews/sets/{view.review_set_id}",
            )

        result = await run_in_threadpool(
            run_command,
            request,
            raw_key=idempotency_key,
            body={
                "review_set_id": review_set_id,
                "document_role": document_role,
                "content_length": upload.content_length,
                "sha256": upload.sha256,
            },
            resource_type="paired_document_review_member",
            callback=execute,
            response_status=202,
        )
    return one(request, result)


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


@router.get(
    "/upload-intents-v2/{upload_intent_id}",
    operation_id="document_review_upload_intent_v2_get",
    response_model=SingleResponse[DocumentReviewUploadIntentViewV2],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_document_review_upload_intent_v2(
    request: Request,
    upload_intent_id: str,
    authentication: Auth,
    response: Response,
) -> SingleResponse[DocumentReviewUploadIntentViewV2]:
    value = request.app.state.services.pdf_document_reviews.document_upload_intent(
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
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in (
                    "application/pdf",
                    "application/vnd.hancom.hwp",
                    "application/vnd.hancom.hwpx",
                )
            },
        }
    },
)
async def upload_pdf_document_review_content(
    request: Request,
    upload_intent_id: str,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    intent = request.app.state.services.pdf_document_reviews.document_upload_intent(
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
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != intent.media_type:
        raise ApiError(
            422,
            "DOCUMENT_REVIEW_UPLOAD_MEDIA_TYPE_MISMATCH",
            "Document upload media type differs",
            "The Content-Type must exactly match the immutable upload intent.",
        )
    async with request.app.state.services.pdf_review_upload_stager.stage(
        request,
        declared_length=int(raw_length),
        source_format=intent.source_format,
        media_type=intent.media_type,
    ) as upload:

        def execute() -> CommandResult:
            command_id, view = (
                request.app.state.services.pdf_document_reviews.accept_document_upload(
                    upload_intent_id,
                    upload,
                    actor=request.state.request_context.actor(),
                    observed_at=datetime.now(UTC),
                )
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
    "/{workflow_id}/corrections/eligibility",
    operation_id="document_review_hwpx_correction_eligibility_get",
    response_model=SingleResponse[DocumentReviewCorrectionEligibilityView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_document_review_hwpx_correction_eligibility(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
) -> SingleResponse[DocumentReviewCorrectionEligibilityView]:
    return one(
        request,
        request.app.state.services.document_review_corrections.eligibility(
            workflow_id,
            actor_id=authentication.operator.operator_id,
        ),
    )


@router.post(
    "/{workflow_id}/corrections",
    operation_id="document_review_hwpx_correction_apply",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def apply_document_review_hwpx_corrections(
    request: Request,
    body: ApplyDocumentReviewCorrectionRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
) -> SingleResponse[CommandResult]:
    operation_id = "document_review_hwpx_correction_apply"
    domain_key = request.app.state.services.idempotency.submission_key(
        operator_id=authentication.operator.operator_id,
        endpoint_key=operation_id,
        raw_key=idempotency_key,
    )

    def execute() -> CommandResult:
        view = request.app.state.services.document_review_corrections.apply(
            workflow_id,
            actor_id=authentication.operator.operator_id,
            finding_ids=body.finding_ids,
            idempotency_key=domain_key,
        )
        return CommandResult(
            command_id=new_api_command_id(),
            resource_type="document_review_hwpx_correction",
            resource_id=view.correction_id,
            status="COMPLETED",
            resource_version=view.resource_version,
            status_url=(
                f"/api/v1/pdf-document-reviews/{workflow_id}/corrections/{view.correction_id}"
            ),
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="document_review_hwpx_correction",
            callback=execute,
            response_status=201,
        ),
    )


@router.get(
    "/{workflow_id}/corrections/{correction_id}",
    operation_id="document_review_hwpx_correction_get",
    response_model=SingleResponse[DocumentReviewCorrectionView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_document_review_hwpx_correction(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    correction_id: str = Path(pattern=r"^doccorrection_[0-9a-f]{32}$"),
) -> SingleResponse[DocumentReviewCorrectionView]:
    return one(
        request,
        request.app.state.services.document_review_corrections.correction(
            workflow_id,
            correction_id,
            actor_id=authentication.operator.operator_id,
        ),
    )


@router.get(
    "/{workflow_id}/corrections/{correction_id}/download",
    operation_id="document_review_hwpx_correction_download",
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def download_document_review_hwpx_correction(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    correction_id: str = Path(pattern=r"^doccorrection_[0-9a-f]{32}$"),
) -> StreamingResponse:
    value = request.app.state.services.document_review_corrections.download(
        workflow_id,
        correction_id,
        actor_id=authentication.operator.operator_id,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="DOCUMENT_REVIEW_CORRECTED_HWPX_READ_AUTHORIZED",
        operation_id="document_review_hwpx_correction_download",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="document_review_hwpx_correction",
        target_id=correction_id,
    )
    return StreamingResponse(
        value.iter_chunks(),
        media_type="application/vnd.hancom.hwpx",
        headers={
            "Content-Length": str(value.content_length),
            "Content-Disposition": 'attachment; filename="document-review-corrected.hwpx"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )


@router.post(
    "/{workflow_id}/annotations",
    operation_id="document_review_annotation_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_START))],
)
def create_document_review_annotation(
    request: Request,
    body: CreateDocumentReviewAnnotationRequestV2 | CreateDocumentReviewAnnotationRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
) -> SingleResponse[CommandResult]:
    operation_id = "document_review_annotation_create"
    domain_key = request.app.state.services.idempotency.submission_key(
        operator_id=authentication.operator.operator_id,
        endpoint_key=operation_id,
        raw_key=idempotency_key,
    )

    def execute() -> CommandResult:
        view = request.app.state.services.document_review_annotations.create(
            workflow_id,
            actor_id=authentication.operator.operator_id,
            idempotency_key=domain_key,
            annotation_profile=(
                body.annotation_profile
                if isinstance(body, CreateDocumentReviewAnnotationRequestV2)
                else None
            ),
        )
        return CommandResult(
            command_id=new_api_command_id(),
            resource_type="document_review_pdf_annotation",
            resource_id=view.annotation_id,
            status="COMPLETED",
            resource_version=view.resource_version,
            status_url=(
                f"/api/v1/pdf-document-reviews/{workflow_id}/annotations/{view.annotation_id}"
            ),
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="document_review_pdf_annotation",
            callback=execute,
            response_status=201,
        ),
    )


@router.get(
    "/{workflow_id}/annotations/{annotation_id}",
    operation_id="document_review_annotation_get",
    response_model=SingleResponse[DocumentReviewAnnotationView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_document_review_annotation(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    annotation_id: str = Path(pattern=r"^docannotation_[0-9a-f]{32}$"),
) -> SingleResponse[DocumentReviewAnnotationView]:
    return one(
        request,
        request.app.state.services.document_review_annotations.annotation(
            workflow_id,
            annotation_id,
            actor_id=authentication.operator.operator_id,
        ),
    )


@router.get(
    "/{workflow_id}/annotations/{annotation_id}/documents/{document_role}/download",
    operation_id="document_review_annotation_download",
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def download_document_review_annotation(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    annotation_id: str = Path(pattern=r"^docannotation_[0-9a-f]{32}$"),
    document_role: Literal["DOCUMENT", "QUESTION", "SOLUTION"] = Path(),
) -> StreamingResponse:
    value = request.app.state.services.document_review_annotations.download(
        workflow_id,
        annotation_id,
        document_role,
        actor_id=authentication.operator.operator_id,
    )
    request.app.state.services.audit.append(
        request.state.request_context,
        event_type="DOCUMENT_REVIEW_ANNOTATED_PDF_READ_AUTHORIZED",
        operation_id="document_review_annotation_download",
        outcome="SUCCEEDED",
        http_status=200,
        target_type="document_review_pdf_annotation",
        target_id=annotation_id,
    )
    filename = {
        "DOCUMENT": "document-review-annotated.pdf",
        "QUESTION": "question-document-annotated.pdf",
        "SOLUTION": "solution-document-annotated.pdf",
    }[document_role]
    return StreamingResponse(
        value.iter_chunks(),
        media_type="application/pdf",
        headers={
            "Content-Length": str(value.content_length),
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{value.sha256}"',
        },
    )


@router.get(
    "/{workflow_id}",
    operation_id="pdf_document_review_get",
    response_model=SingleResponse[PdfDocumentReviewView | PairedDocumentReviewView],
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_pdf_document_review(
    request: Request,
    authentication: Auth,
    response: Response,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
) -> SingleResponse[PdfDocumentReviewView | PairedDocumentReviewView]:
    value = request.app.state.services.queries.pdf_document_review(
        actor_id=authentication.operator.operator_id,
        workflow_id=workflow_id,
    )
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.get(
    "/{workflow_id}/documents/{document_role}/pages/{page_number}/image",
    operation_id="paired_document_review_page_image_get",
    dependencies=[Depends(require_permission(PermissionKey.WORKFLOW_READ))],
)
def get_paired_document_review_page_image(
    request: Request,
    authentication: Auth,
    workflow_id: str = Path(pattern=r"^workflow_[0-9a-f]{32}$"),
    document_role: Literal["QUESTION", "SOLUTION"] = Path(pattern=r"^(?:QUESTION|SOLUTION)$"),
    page_number: int = Path(ge=1, le=64),
) -> StreamingResponse:
    document, page = request.app.state.services.queries.paired_document_review_page_pointer(
        actor_id=authentication.operator.operator_id,
        workflow_id=workflow_id,
        document_role=document_role,
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
        event_type="PAIRED_DOCUMENT_REVIEW_PAGE_READ_AUTHORIZED",
        operation_id="paired_document_review_page_image_get",
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
