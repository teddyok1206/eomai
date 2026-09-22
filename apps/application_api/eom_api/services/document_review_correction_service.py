"""Application use case for authorized immutable HWPX redline successors."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts.document_review import (
    DocumentReviewCorrectionEligibilityView,
    DocumentReviewCorrectionView,
)
from eom_catalog_contracts import (
    ApplyDocumentReviewHwpxCorrections,
    DocumentReviewHwpxCorrectionMediaQuery,
    OfficeDocumentReviewMemberPointer,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory, transaction
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import (
    DocumentReviewHwpxCorrectionRecord,
    PdfDocumentReviewUploadIntentRecord,
)
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
    ProxiedItemMedia,
)
from eom_api.services.query_adapter import QueryAdapter


class DocumentReviewCorrectionApplicationService:
    """Resolve owned review pointers and persist only a small output pointer."""

    def __init__(
        self,
        engine: Engine,
        *,
        catalog: CatalogApplicationClient,
        queries: QueryAdapter,
    ) -> None:
        self.sessions = build_session_factory(engine)
        self.catalog = catalog
        self.queries = queries

    def eligibility(
        self,
        workflow_id: str,
        *,
        actor_id: str,
    ) -> DocumentReviewCorrectionEligibilityView:
        upload = self._owned_upload(workflow_id, actor_id=actor_id)
        if upload.source_format != "HWPX":
            return DocumentReviewCorrectionEligibilityView(
                workflow_id=workflow_id,
                source_format=upload.source_format,  # type: ignore[arg-type]
                correction_available=False,
                eligible_finding_ids=(),
                unavailable_reason="SOURCE_NOT_HWPX",
            )
        review = self.queries.pdf_document_review(actor_id=actor_id, workflow_id=workflow_id)
        if review.state != "COMPLETED" or review.result is None:
            return DocumentReviewCorrectionEligibilityView(
                workflow_id=workflow_id,
                source_format="HWPX",
                correction_available=False,
                eligible_finding_ids=(),
                unavailable_reason="REVIEW_NOT_COMPLETED",
            )
        eligible = tuple(
            finding.finding_id
            for finding in review.result.findings
            if finding.recommendation.operation == "REPLACE"
            and finding.recommendation.before_text is not None
            and finding.recommendation.after_text is not None
        )
        return DocumentReviewCorrectionEligibilityView(
            workflow_id=workflow_id,
            source_format="HWPX",
            correction_available=bool(eligible),
            eligible_finding_ids=eligible,
            unavailable_reason=None if eligible else "NO_SAFE_REPLACEMENTS",
        )

    def apply(
        self,
        workflow_id: str,
        *,
        actor_id: str,
        finding_ids: tuple[str, ...],
        idempotency_key: str,
    ) -> DocumentReviewCorrectionView:
        finding_ids = tuple(sorted(finding_ids))
        upload = self._owned_upload(workflow_id, actor_id=actor_id)
        eligibility = self.eligibility(workflow_id, actor_id=actor_id)
        if not eligibility.correction_available:
            raise ApiError(
                409,
                eligibility.unavailable_reason or "DOCUMENT_REVIEW_CORRECTION_UNAVAILABLE",
                "Document review correction is unavailable",
                "Only a completed HWPX review with exact text replacements can be corrected.",
            )
        if not set(finding_ids).issubset(eligibility.eligible_finding_ids):
            raise ApiError(
                422,
                "DOCUMENT_REVIEW_CORRECTION_FINDING_UNSUPPORTED",
                "A selected correction cannot be applied safely",
                "Select only exact replacement findings exposed by this completed review.",
            )
        review = self.queries.pdf_document_review(actor_id=actor_id, workflow_id=workflow_id)
        if review.result_artifact is None or review.result is None:
            raise ApiError(
                409,
                "REVIEW_NOT_COMPLETED",
                "Document review correction is unavailable",
                "The review result is not committed yet.",
            )
        review_result = self.queries.pdf_document_review_result_pointer(
            actor_id=actor_id,
            workflow_id=workflow_id,
        )
        if (
            upload.source_artifact_id is None
            or upload.source_artifact_revision_id is None
            or upload.upload_sha256 is None
        ):
            raise ApiError(
                500,
                "DOCUMENT_REVIEW_SOURCE_POINTER_INVALID",
                "Document source pointer is invalid",
                "The reviewed HWPX source was not pinned to one immutable Artifact revision.",
            )
        base_hwpx = OfficeDocumentReviewMemberPointer(
            artifact_id=upload.source_artifact_id,
            artifact_revision_id=upload.source_artifact_revision_id,
            member_path="source/original.hwpx",
            sha256=upload.upload_sha256,
            content_length=upload.content_length,
            media_type="application/vnd.hancom.hwpx",
            schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
        )
        command = ApplyDocumentReviewHwpxCorrections(
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            workflow_id=workflow_id,
            review_result=review_result,
            base_hwpx=base_hwpx,
            finding_ids=finding_ids,
        )
        try:
            response = self.catalog.apply_document_review_hwpx_corrections(command)
        except CatalogApplicationClientError as exc:
            raise ApiError(
                503,
                exc.code,
                "HWPX correction is temporarily unavailable",
                "No source document was changed. Retry the same request after recovery.",
            ) from exc
        if response.output is None or response.result is None:
            raise ApiError(
                503,
                "DOCUMENT_REVIEW_CORRECTION_RESPONSE_INVALID",
                "HWPX correction response is invalid",
                "Catalog did not return a complete immutable corrected HWPX pointer.",
            )
        record = DocumentReviewHwpxCorrectionRecord(
            correction_id=response.result.correction_id,
            operator_id=actor_id,
            workflow_id=workflow_id,
            applied_finding_ids=list(response.result.applied_finding_ids),
            finding_set_sha256=content_sha256(list(response.result.applied_finding_ids)),
            review_result_artifact_id=review_result.artifact_id,
            review_result_artifact_revision_id=review_result.artifact_revision_id,
            review_result_sha256=review_result.sha256,
            base_hwpx_sha256=base_hwpx.sha256,
            output_artifact_id=response.output.artifact_id,
            output_artifact_revision_id=response.output.artifact_revision_id,
            output_member_path=response.output.member_path,
            output_sha256=response.output.sha256,
            output_content_length=response.output.content_length,
            output_media_type=response.output.media_type,
            output_schema_ref=response.output.schema_ref,
            lock_version=1,
            created_at=datetime.now(UTC),
        )
        try:
            with transaction(self.sessions) as session:
                existing = session.get(
                    DocumentReviewHwpxCorrectionRecord,
                    record.correction_id,
                    with_for_update=True,
                )
                if existing is None:
                    session.add(record)
                    session.flush()
                else:
                    self._require_exact_replay(existing, record)
                    record = existing
        except IntegrityError:
            with self.sessions() as session:
                existing = session.get(DocumentReviewHwpxCorrectionRecord, record.correction_id)
                if existing is None:
                    raise
                self._require_exact_replay(existing, record)
                record = existing
        return self._view(record)

    def correction(
        self,
        workflow_id: str,
        correction_id: str,
        *,
        actor_id: str,
    ) -> DocumentReviewCorrectionView:
        return self._view(self._owned_correction(workflow_id, correction_id, actor_id=actor_id))

    def download(
        self,
        workflow_id: str,
        correction_id: str,
        *,
        actor_id: str,
    ) -> ProxiedItemMedia:
        record = self._owned_correction(workflow_id, correction_id, actor_id=actor_id)
        pointer = OfficeDocumentReviewMemberPointer(
            artifact_id=record.output_artifact_id,
            artifact_revision_id=record.output_artifact_revision_id,
            member_path=record.output_member_path,
            sha256=record.output_sha256,
            content_length=record.output_content_length,
            media_type=record.output_media_type,  # type: ignore[arg-type]
            schema_ref=record.output_schema_ref,
        )
        return self.catalog.download_document_review_corrected_hwpx(
            DocumentReviewHwpxCorrectionMediaQuery(
                workflow_id=workflow_id,
                correction_id=correction_id,
                output=pointer,
            )
        )

    def _owned_upload(
        self,
        workflow_id: str,
        *,
        actor_id: str,
    ) -> PdfDocumentReviewUploadIntentRecord:
        with self.sessions() as session:
            value = session.scalar(
                select(PdfDocumentReviewUploadIntentRecord).where(
                    PdfDocumentReviewUploadIntentRecord.workflow_id == workflow_id,
                    PdfDocumentReviewUploadIntentRecord.operator_id == actor_id,
                )
            )
            if value is None:
                raise self._not_found()
            session.expunge(value)
            return value

    def _owned_correction(
        self,
        workflow_id: str,
        correction_id: str,
        *,
        actor_id: str,
    ) -> DocumentReviewHwpxCorrectionRecord:
        with self.sessions() as session:
            value = session.scalar(
                select(DocumentReviewHwpxCorrectionRecord).where(
                    DocumentReviewHwpxCorrectionRecord.correction_id == correction_id,
                    DocumentReviewHwpxCorrectionRecord.workflow_id == workflow_id,
                    DocumentReviewHwpxCorrectionRecord.operator_id == actor_id,
                )
            )
            if value is None:
                raise self._not_found()
            session.expunge(value)
            return value

    @staticmethod
    def _require_exact_replay(
        existing: DocumentReviewHwpxCorrectionRecord,
        candidate: DocumentReviewHwpxCorrectionRecord,
    ) -> None:
        fields = (
            "operator_id",
            "workflow_id",
            "applied_finding_ids",
            "finding_set_sha256",
            "review_result_artifact_id",
            "review_result_artifact_revision_id",
            "review_result_sha256",
            "base_hwpx_sha256",
            "output_artifact_id",
            "output_artifact_revision_id",
            "output_member_path",
            "output_sha256",
            "output_content_length",
            "output_media_type",
            "output_schema_ref",
        )
        if any(getattr(existing, field) != getattr(candidate, field) for field in fields):
            raise ApiError(
                409,
                "DOCUMENT_REVIEW_CORRECTION_IDEMPOTENCY_CONFLICT",
                "HWPX correction replay differs",
                "The correction identity already belongs to different immutable inputs.",
            )

    @staticmethod
    def _view(record: DocumentReviewHwpxCorrectionRecord) -> DocumentReviewCorrectionView:
        created_at = (
            record.created_at.replace(tzinfo=UTC)
            if record.created_at.tzinfo is None
            else record.created_at.astimezone(UTC)
        )
        return DocumentReviewCorrectionView(
            correction_id=record.correction_id,
            workflow_id=record.workflow_id,
            applied_finding_ids=tuple(record.applied_finding_ids),
            output_sha256=record.output_sha256,
            output_content_length=record.output_content_length,
            download_url=(
                f"/api/v1/pdf-document-reviews/{record.workflow_id}/corrections/"
                f"{record.correction_id}/download"
            ),
            created_at=created_at,
            resource_version=record.lock_version,
        )

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(
            404,
            "DOCUMENT_REVIEW_CORRECTION_NOT_FOUND",
            "Document review correction not found",
            "The review or corrected HWPX does not exist or is not visible to this Operator.",
        )
