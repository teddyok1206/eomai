"""Application service for durable PDF upload intake and Workflow creation."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from eom_api_contracts.document_review import (
    CreateDocumentReviewUploadIntentRequestV2,
    CreatePdfDocumentReviewUploadIntentRequest,
    DocumentReviewUploadIntentViewV2,
    PdfDocumentReviewUploadIntentView,
)
from eom_catalog_contracts import OfficeDocumentReviewSourcePointer
from eom_identifiers import content_sha256, new_pdf_review_upload_intent_id
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow import (
    PdfReviewPresetKey,
    build_pdf_document_review_request,
    normalize_pdf_review_guidance,
)
from eom_workflow_runner.errors import WorkflowError
from pydantic import ValidationError
from sqlalchemy import Engine, select

from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
)
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.pdf_upload_stager import StagedPdfUpload

_RETRYABLE_CATALOG_CODES = frozenset(
    {
        "CATALOG_APPLICATION_UNAVAILABLE",
        "CATALOG_APPLICATION_INTERNAL_ERROR",
        "CATALOG_ARTIFACT_COMMIT_FAILED",
        "CATALOG_CONCURRENCY_CONFLICT",
        "PDF_DOCUMENT_REVIEW_SOURCE_WRITE_FAILED",
        "PDF_DOCUMENT_REVIEW_RENDERER_FAILED",
        "PDF_DOCUMENT_REVIEW_PAGE_RENDER_FAILED",
        "PDF_DOCUMENT_REVIEW_UPLOAD_WRITE_FAILED",
    }
)


@dataclass(frozen=True)
class PdfReviewUploadClaim:
    upload_intent_id: str
    lease_owner: str | None
    original_filename: str
    source_format: str
    source_media_type: str
    preset_key: str
    additional_guidance: str | None
    replayed_command_id: str | None = None
    replayed_view: DocumentReviewUploadIntentViewV2 | None = None

    @property
    def replayed(self) -> bool:
        return self.replayed_view is not None


class PdfDocumentReviewApplicationService:
    """Own the bounded upload-intent state machine and downstream idempotent effects."""

    def __init__(
        self,
        engine: Engine,
        *,
        catalog: CatalogApplicationClient,
        commands: CommandAdapter,
        intent_ttl_seconds: int,
        processing_lease_seconds: int,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.catalog = catalog
        self.commands = commands
        self.intent_ttl_seconds = intent_ttl_seconds
        self.processing_lease_seconds = processing_lease_seconds

    def create_upload_intent(
        self,
        request: CreatePdfDocumentReviewUploadIntentRequest,
        *,
        actor_id: str,
        observed_at: datetime | None = None,
    ) -> PdfDocumentReviewUploadIntentView:
        value = self._create_upload_intent(
            CreateDocumentReviewUploadIntentRequestV2(
                original_filename=request.original_filename,
                source_format="PDF",
                media_type="application/pdf",
                content_length=request.content_length,
                preset_key=request.preset_key,
                additional_guidance=request.additional_guidance,
                locale=request.locale,
            ),
            actor_id=actor_id,
            observed_at=observed_at,
        )
        return self._legacy_view_from_v2(value)

    def create_document_upload_intent(
        self,
        request: CreateDocumentReviewUploadIntentRequestV2,
        *,
        actor_id: str,
        observed_at: datetime | None = None,
    ) -> DocumentReviewUploadIntentViewV2:
        return self._create_upload_intent(
            request,
            actor_id=actor_id,
            observed_at=observed_at,
        )

    def _create_upload_intent(
        self,
        request: CreateDocumentReviewUploadIntentRequestV2,
        *,
        actor_id: str,
        observed_at: datetime | None,
    ) -> DocumentReviewUploadIntentViewV2:
        now = observed_at or datetime.now(UTC)
        normalized_guidance = (
            None
            if request.additional_guidance is None
            else normalize_pdf_review_guidance(request.additional_guidance)
        )
        record = PdfDocumentReviewUploadIntentRecord(
            upload_intent_id=new_pdf_review_upload_intent_id(),
            operator_id=actor_id,
            state="AWAITING_UPLOAD",
            original_filename=request.original_filename,
            source_format=request.source_format,
            source_media_type=request.media_type,
            content_length=request.content_length,
            preset_key=request.preset_key,
            additional_guidance=normalized_guidance,
            additional_guidance_sha256=(
                None if normalized_guidance is None else content_sha256(normalized_guidance)
            ),
            attempts=0,
            lock_version=1,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.intent_ttl_seconds),
        )
        with transaction(self.sessions) as session:
            session.add(record)
            session.flush()
        return self._view_v2(record)

    def upload_intent(
        self,
        upload_intent_id: str,
        *,
        actor_id: str,
    ) -> PdfDocumentReviewUploadIntentView:
        record = self._owned_intent(upload_intent_id, actor_id=actor_id)
        if record.source_format != "PDF":
            raise ApiError(
                409,
                "DOCUMENT_REVIEW_UPLOAD_V2_REQUIRED",
                "Office document upload requires the V2 endpoint",
                "Read this HWP or HWPX upload intent through the Office review endpoint.",
            )
        return self._view_v1(record)

    def document_upload_intent(
        self,
        upload_intent_id: str,
        *,
        actor_id: str,
    ) -> DocumentReviewUploadIntentViewV2:
        return self._view_v2(self._owned_intent(upload_intent_id, actor_id=actor_id))

    def _owned_intent(
        self,
        upload_intent_id: str,
        *,
        actor_id: str,
    ) -> PdfDocumentReviewUploadIntentRecord:
        with self.sessions() as session:
            record = session.scalar(
                select(PdfDocumentReviewUploadIntentRecord).where(
                    PdfDocumentReviewUploadIntentRecord.upload_intent_id == upload_intent_id,
                    PdfDocumentReviewUploadIntentRecord.operator_id == actor_id,
                )
            )
            if record is None:
                raise self._not_found()
            session.expunge(record)
            return record

    def accept_upload(
        self,
        upload_intent_id: str,
        upload: StagedPdfUpload,
        *,
        actor: ActorContext,
        observed_at: datetime | None = None,
    ) -> tuple[str, PdfDocumentReviewUploadIntentView]:
        if upload.source_format != "PDF" or upload.media_type != "application/pdf":
            raise ApiError(
                422,
                "PDF_DOCUMENT_REVIEW_UPLOAD_FORMAT_MISMATCH",
                "PDF upload format differs",
                "The legacy PDF endpoint accepts only PDF bytes.",
            )
        command_id, _ = self._accept_document_upload(
            upload_intent_id,
            upload,
            actor=actor,
            observed_at=observed_at,
        )
        return command_id, self.upload_intent(upload_intent_id, actor_id=actor.actor_id)

    def accept_document_upload(
        self,
        upload_intent_id: str,
        upload: StagedPdfUpload,
        *,
        actor: ActorContext,
        observed_at: datetime | None = None,
    ) -> tuple[str, DocumentReviewUploadIntentViewV2]:
        return self._accept_document_upload(
            upload_intent_id,
            upload,
            actor=actor,
            observed_at=observed_at,
        )

    def _accept_document_upload(
        self,
        upload_intent_id: str,
        upload: StagedPdfUpload,
        *,
        actor: ActorContext,
        observed_at: datetime | None,
    ) -> tuple[str, DocumentReviewUploadIntentViewV2]:
        now = observed_at or datetime.now(UTC)
        claim = self._claim_upload(
            upload_intent_id,
            upload,
            actor_id=actor.actor_id,
            observed_at=now,
        )
        if claim.replayed:
            assert claim.replayed_command_id is not None
            assert claim.replayed_view is not None
            return claim.replayed_command_id, claim.replayed_view
        assert claim.lease_owner is not None
        source_document: OfficeDocumentReviewSourcePointer | None = None
        try:
            resolved_source = self.catalog.ingest_office_document_review_source(
                upload.path,
                actor_id=actor.actor_id,
                original_filename=claim.original_filename,
                source_format=claim.source_format,  # type: ignore[arg-type]
                media_type=claim.source_media_type,  # type: ignore[arg-type]
                idempotency_key=f"document-review-intake:{claim.upload_intent_id}",
            )
            if (
                resolved_source.original_filename != claim.original_filename
                or resolved_source.source_format != claim.source_format
                or resolved_source.original_source.sha256 != upload.sha256
                or resolved_source.original_source.content_length != upload.content_length
            ):
                raise ApiError(
                    503,
                    "PDF_DOCUMENT_REVIEW_INTAKE_POINTER_MISMATCH",
                    "PDF document intake pointer differs",
                    "Catalog did not return the exact immutable source that was uploaded.",
                )
            source_document = resolved_source
            review_request = build_pdf_document_review_request(
                document=resolved_source.review_document,
                preset_key=cast(PdfReviewPresetKey, claim.preset_key),
                additional_guidance=claim.additional_guidance,
            )
            command_id, workflow_id, _ = self.commands.start_pdf_document_review(
                review_request,
                actor,
                idempotency_key=f"pdf-review-workflow:{claim.upload_intent_id}",
            )
        except CatalogApplicationClientError as exc:
            retryable = exc.code in _RETRYABLE_CATALOG_CODES
            self._fail_claim(
                claim,
                error_code=exc.code,
                retryable=retryable,
                document=source_document,
            )
            raise ApiError(
                503 if retryable else 422,
                exc.code,
                "PDF document intake failed",
                "The PDF could not be registered for document review.",
            ) from exc
        except ApiError as exc:
            self._fail_claim(
                claim,
                error_code=str(exc.error_code),
                retryable=exc.status >= 500,
                document=source_document,
            )
            raise
        except WorkflowError as exc:
            code = getattr(exc.code, "value", str(exc.code))
            self._fail_claim(
                claim,
                error_code=code,
                retryable=False,
                document=source_document,
            )
            raise ApiError(
                409,
                code,
                "PDF review Workflow could not start",
                "The immutable PDF review request conflicts with an existing Workflow.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            self._fail_claim(
                claim,
                error_code="PDF_DOCUMENT_REVIEW_REQUEST_UNSUPPORTED",
                retryable=False,
                document=source_document,
            )
            raise ApiError(
                422,
                "PDF_DOCUMENT_REVIEW_REQUEST_UNSUPPORTED",
                "PDF review request is outside the supported boundary",
                "This PDF cannot be reviewed by the bounded V1 document-review workflow.",
            ) from exc
        except Exception as exc:
            self._fail_claim(
                claim,
                error_code="PDF_DOCUMENT_REVIEW_PROCESSING_FAILED",
                retryable=True,
                document=source_document,
            )
            raise ApiError(
                500,
                "PDF_DOCUMENT_REVIEW_PROCESSING_FAILED",
                "PDF review processing failed",
                "The same upload intent can be retried after the dependency recovers.",
            ) from exc
        view = self._complete_claim(
            claim,
            command_id=command_id,
            workflow_id=workflow_id,
            document=source_document,
        )
        return command_id, view

    def _claim_upload(
        self,
        upload_intent_id: str,
        upload: StagedPdfUpload,
        *,
        actor_id: str,
        observed_at: datetime,
    ) -> PdfReviewUploadClaim:
        lease_owner = "pdfreviewlease_" + secrets.token_hex(16)
        with transaction(self.sessions) as session:
            record = session.scalar(
                select(PdfDocumentReviewUploadIntentRecord)
                .where(
                    PdfDocumentReviewUploadIntentRecord.upload_intent_id == upload_intent_id,
                    PdfDocumentReviewUploadIntentRecord.operator_id == actor_id,
                )
                .with_for_update()
            )
            if record is None:
                raise self._not_found()
            if record.content_length != upload.content_length:
                raise ApiError(
                    422,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_LENGTH_MISMATCH",
                    "PDF upload length differs",
                    "The uploaded bytes do not match the declared upload intent.",
                )
            if (
                record.source_format != upload.source_format
                or record.source_media_type != upload.media_type
            ):
                raise ApiError(
                    422,
                    "DOCUMENT_REVIEW_UPLOAD_FORMAT_MISMATCH",
                    "Document upload format differs",
                    "The uploaded bytes must use the exact format and media type in the intent.",
                )
            if record.upload_sha256 is not None and not hmac.compare_digest(
                record.upload_sha256, upload.sha256
            ):
                raise ApiError(
                    409,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_HASH_MISMATCH",
                    "PDF upload differs from the pinned intent",
                    "Retry the intent only with the exact same PDF bytes.",
                )
            if record.state == "STARTED":
                if record.workflow_command_id is None:
                    raise RuntimeError("started PDF review intent lost its command pointer")
                return PdfReviewUploadClaim(
                    upload_intent_id=record.upload_intent_id,
                    lease_owner=None,
                    original_filename=record.original_filename,
                    preset_key=record.preset_key,
                    additional_guidance=record.additional_guidance,
                    replayed_command_id=record.workflow_command_id,
                    source_format=record.source_format,
                    source_media_type=record.source_media_type,
                    replayed_view=self._view_v2(record),
                )
            if self._as_utc(record.expires_at) <= observed_at:
                raise ApiError(
                    409,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_INTENT_EXPIRED",
                    "PDF upload intent expired",
                    "Create a new upload intent before sending the PDF again.",
                )
            if record.state == "FAILED_FINAL":
                raise ApiError(
                    409,
                    record.failure_code or "PDF_DOCUMENT_REVIEW_UPLOAD_FAILED",
                    "PDF upload cannot be retried",
                    "The upload intent ended with a non-retryable validation failure.",
                )
            if record.state == "PROCESSING" and (
                record.lease_expires_at is None
                or self._as_utc(record.lease_expires_at) > observed_at
            ):
                retry_after = max(
                    1,
                    int((self._as_utc(record.lease_expires_at) - observed_at).total_seconds())
                    if record.lease_expires_at is not None
                    else 1,
                )
                raise ApiError(
                    409,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_IN_PROGRESS",
                    "PDF upload is already being processed",
                    "Retry the exact upload after the current processing lease ends.",
                    {"Retry-After": str(retry_after)},
                )
            record.state = "PROCESSING"
            record.upload_sha256 = upload.sha256
            record.failure_code = None
            record.lease_owner = lease_owner
            record.lease_expires_at = observed_at + timedelta(seconds=self.processing_lease_seconds)
            record.attempts += 1
            record.lock_version += 1
            record.updated_at = observed_at
            return PdfReviewUploadClaim(
                upload_intent_id=record.upload_intent_id,
                lease_owner=lease_owner,
                original_filename=record.original_filename,
                source_format=record.source_format,
                source_media_type=record.source_media_type,
                preset_key=record.preset_key,
                additional_guidance=record.additional_guidance,
            )

    def _complete_claim(
        self,
        claim: PdfReviewUploadClaim,
        *,
        command_id: str,
        workflow_id: str,
        document: OfficeDocumentReviewSourcePointer,
    ) -> DocumentReviewUploadIntentViewV2:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(
                PdfDocumentReviewUploadIntentRecord,
                claim.upload_intent_id,
                with_for_update=True,
            )
            if record is None or not self._owns(record, claim):
                raise ApiError(
                    409,
                    "PDF_DOCUMENT_REVIEW_UPLOAD_CLAIM_LOST",
                    "PDF upload claim was superseded",
                    "Replay the exact upload to receive the committed result.",
                )
            record.state = "STARTED"
            record.workflow_id = workflow_id
            record.workflow_command_id = command_id
            review = document.review_document
            record.document_id = review.document_id
            record.document_revision_id = review.document_revision_id
            record.source_artifact_id = document.original_source.artifact_id
            record.source_artifact_revision_id = document.original_source.artifact_revision_id
            record.source_sha256 = document.original_source.sha256
            record.page_count = review.page_count
            record.failure_code = None
            record.lease_owner = None
            record.lease_expires_at = None
            record.lock_version += 1
            record.updated_at = now
            session.flush()
            return self._view_v2(record)

    def _fail_claim(
        self,
        claim: PdfReviewUploadClaim,
        *,
        error_code: str,
        retryable: bool,
        document: OfficeDocumentReviewSourcePointer | None,
    ) -> None:
        now = datetime.now(UTC)
        with transaction(self.sessions) as session:
            record = session.get(
                PdfDocumentReviewUploadIntentRecord,
                claim.upload_intent_id,
                with_for_update=True,
            )
            if record is None or not self._owns(record, claim):
                return
            record.state = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
            record.failure_code = error_code[:64]
            record.lease_owner = None
            record.lease_expires_at = None
            if document is not None:
                review = document.review_document
                record.document_id = review.document_id
                record.document_revision_id = review.document_revision_id
                record.source_artifact_id = document.original_source.artifact_id
                record.source_artifact_revision_id = document.original_source.artifact_revision_id
                record.source_sha256 = document.original_source.sha256
                record.page_count = review.page_count
            record.lock_version += 1
            record.updated_at = now

    @staticmethod
    def _owns(
        record: PdfDocumentReviewUploadIntentRecord,
        claim: PdfReviewUploadClaim,
    ) -> bool:
        return (
            record.state == "PROCESSING"
            and record.lease_owner is not None
            and claim.lease_owner is not None
            and hmac.compare_digest(record.lease_owner, claim.lease_owner)
        )

    @staticmethod
    def _view_v2(
        record: PdfDocumentReviewUploadIntentRecord,
    ) -> DocumentReviewUploadIntentViewV2:
        review_url = (
            f"/api/v1/pdf-document-reviews/{record.workflow_id}"
            if record.workflow_id is not None
            else None
        )
        return DocumentReviewUploadIntentViewV2(
            upload_intent_id=record.upload_intent_id,
            state=record.state,  # type: ignore[arg-type]
            original_filename=record.original_filename,
            source_format=record.source_format,  # type: ignore[arg-type]
            media_type=record.source_media_type,  # type: ignore[arg-type]
            content_length=record.content_length,
            preset_key=record.preset_key,  # type: ignore[arg-type]
            additional_guidance_sha256=record.additional_guidance_sha256,
            upload_sha256=record.upload_sha256,
            workflow_id=record.workflow_id,
            failure_code=record.failure_code,
            upload_url=(
                f"/api/v1/pdf-document-reviews/upload-intents/{record.upload_intent_id}/content"
            ),
            review_url=review_url,
            created_at=PdfDocumentReviewApplicationService._as_utc(record.created_at),
            updated_at=PdfDocumentReviewApplicationService._as_utc(record.updated_at),
            expires_at=PdfDocumentReviewApplicationService._as_utc(record.expires_at),
            resource_version=record.lock_version,
        )

    @staticmethod
    def _view_v1(
        record: PdfDocumentReviewUploadIntentRecord,
    ) -> PdfDocumentReviewUploadIntentView:
        return PdfDocumentReviewApplicationService._legacy_view_from_v2(
            PdfDocumentReviewApplicationService._view_v2(record)
        )

    @staticmethod
    def _legacy_view_from_v2(
        value: DocumentReviewUploadIntentViewV2,
    ) -> PdfDocumentReviewUploadIntentView:
        return PdfDocumentReviewUploadIntentView.model_validate(
            value.model_dump(mode="json", exclude={"source_format", "media_type"})
        )

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(
            404,
            "PDF_DOCUMENT_REVIEW_UPLOAD_INTENT_NOT_FOUND",
            "PDF upload intent not found",
            "The upload intent does not exist or is not visible to this Operator.",
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
