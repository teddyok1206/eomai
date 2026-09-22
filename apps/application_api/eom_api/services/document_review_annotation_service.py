"""Application use case for immutable visual annotations of completed reviews."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

from eom_api_contracts.document_review import (
    DocumentReviewAnnotationOutputView,
    DocumentReviewAnnotationView,
)
from eom_catalog_contracts import (
    CreateDocumentReviewAnnotatedPdfs,
    DocumentReviewAnnotatedPdfPointer,
    DocumentReviewAnnotationPage,
    DocumentReviewAnnotationRegion,
    DocumentReviewAnnotationSource,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationMediaQuery,
)
from eom_identifiers import content_sha256
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow import PairedDocumentReviewRoleResult, PdfDocumentReviewRoleResult
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import (
    DocumentReviewPdfAnnotationOutputRecord,
    DocumentReviewPdfAnnotationRecord,
)
from eom_api.services.catalog_application_client import (
    CatalogApplicationClient,
    CatalogApplicationClientError,
    ProxiedItemMedia,
)
from eom_api.services.query_adapter import QueryAdapter


class DocumentReviewAnnotationApplicationService:
    """Resolve validated findings and persist only Catalog-owned output pointers."""

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

    def create(
        self,
        workflow_id: str,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> DocumentReviewAnnotationView:
        review_result, source_values, parsed = self.queries.document_review_annotation_inputs(
            actor_id=actor_id,
            workflow_id=workflow_id,
        )
        sources = tuple(
            DocumentReviewAnnotationSource(
                role=cast(
                    Literal["DOCUMENT", "QUESTION", "SOLUTION"],
                    role,
                ),
                document_id=document.document_id,
                document_revision_id=document.document_revision_id,
                source_pdf=document.source_pdf,
                page_count=document.page_count,
                pages=tuple(
                    DocumentReviewAnnotationPage(
                        page_number=page.page_number,
                        page_image=page.page_image,
                    )
                    for page in document.pages
                ),
            )
            for role, document in source_values
        )
        marks: list[DocumentReviewPdfAnnotationMark] = []
        if isinstance(parsed, PdfDocumentReviewRoleResult):
            for finding in parsed.output.findings:
                for anchor in finding.anchors:
                    marks.append(
                        DocumentReviewPdfAnnotationMark(
                            finding_id=finding.finding_id,
                            anchor_id=anchor.anchor_id,
                            ordinal=finding.ordinal,
                            document_role="DOCUMENT",
                            page_number=anchor.page_number,
                            page_image_sha256=anchor.page_image_sha256,
                            region=DocumentReviewAnnotationRegion.model_validate(
                                anchor.region.model_dump(mode="json")
                            ),
                        )
                    )
        elif isinstance(parsed, PairedDocumentReviewRoleResult):
            for finding in parsed.output.findings:
                for anchor in finding.anchors:
                    marks.append(
                        DocumentReviewPdfAnnotationMark(
                            finding_id=finding.finding_id,
                            anchor_id=anchor.anchor_id,
                            ordinal=finding.ordinal,
                            document_role=anchor.document_role,
                            page_number=anchor.page_number,
                            page_image_sha256=anchor.page_image_sha256,
                            region=DocumentReviewAnnotationRegion.model_validate(
                                anchor.region.model_dump(mode="json")
                            ),
                        )
                    )
        marks.sort(
            key=lambda value: (
                value.document_role,
                value.page_number,
                value.ordinal,
                value.anchor_id,
            )
        )
        if not marks:
            raise ApiError(
                409,
                "DOCUMENT_REVIEW_ANNOTATION_FINDINGS_EMPTY",
                "There are no findings to annotate",
                "A completed review needs at least one located finding before annotation.",
            )
        annotations = tuple(marks)
        payload: dict[str, object] = {
            "schema_version": "document-review-pdf-annotation-request/1.0",
            "operation": "CREATE_DOCUMENT_REVIEW_ANNOTATED_PDFS",
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "workflow_id": workflow_id,
            "review_result": review_result,
            "sources": sources,
            "annotations": annotations,
            "annotation_set_sha256": content_sha256(
                [value.model_dump(mode="json") for value in annotations]
            ),
        }
        payload["request_sha256"] = content_sha256(
            {key: value for key, value in payload.items() if key != "idempotency_key"}
        )
        command = CreateDocumentReviewAnnotatedPdfs.model_validate(payload)
        prior = self._existing_for_request(
            workflow_id,
            command.request_sha256,
            actor_id=actor_id,
        )
        if prior is not None:
            return self._view(*prior)
        try:
            response = self.catalog.create_document_review_annotated_pdfs(command)
        except CatalogApplicationClientError as exc:
            raise ApiError(
                503,
                exc.code,
                "Annotated PDF creation is temporarily unavailable",
                "The source files were not changed. Retry the same request after recovery.",
            ) from exc
        if response.outputs is None or response.manifest is None or response.result is None:
            raise ApiError(
                503,
                "DOCUMENT_REVIEW_ANNOTATION_RESPONSE_INVALID",
                "Annotated PDF response is invalid",
                "Catalog did not return complete immutable annotation pointers.",
            )
        record = DocumentReviewPdfAnnotationRecord(
            annotation_id=response.result.annotation_id,
            operator_id=actor_id,
            workflow_id=workflow_id,
            request_sha256=command.request_sha256,
            review_result_artifact_id=review_result.artifact_id,
            review_result_artifact_revision_id=review_result.artifact_revision_id,
            review_result_sha256=review_result.sha256,
            annotation_set_sha256=command.annotation_set_sha256,
            manifest_artifact_id=response.manifest.artifact_id,
            manifest_artifact_revision_id=response.manifest.artifact_revision_id,
            manifest_member_sha256=response.manifest.sha256,
            manifest_self_sha256=response.result.manifest_sha256,
            lock_version=1,
            created_at=datetime.now(UTC),
        )
        outputs = tuple(
            DocumentReviewPdfAnnotationOutputRecord(
                annotation_id=record.annotation_id,
                document_role=pointer.document_role,
                artifact_id=pointer.artifact_id,
                artifact_revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                content_length=pointer.content_length,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
            )
            for pointer in response.outputs
        )
        try:
            with transaction(self.sessions) as session:
                existing_record = session.get(
                    DocumentReviewPdfAnnotationRecord,
                    record.annotation_id,
                    with_for_update=True,
                )
                if existing_record is None:
                    session.add(record)
                    session.add_all(outputs)
                    session.flush()
                else:
                    existing_outputs = self._outputs(session, record.annotation_id)
                    self._require_exact_replay(
                        existing_record,
                        existing_outputs,
                        record,
                        outputs,
                    )
                    record = existing_record
                    outputs = existing_outputs
        except IntegrityError:
            with self.sessions() as session:
                existing_record = session.scalar(
                    select(DocumentReviewPdfAnnotationRecord).where(
                        DocumentReviewPdfAnnotationRecord.operator_id == actor_id,
                        DocumentReviewPdfAnnotationRecord.workflow_id == workflow_id,
                        DocumentReviewPdfAnnotationRecord.request_sha256 == command.request_sha256,
                    )
                )
                if existing_record is None:
                    raise
                existing_outputs = self._outputs(session, existing_record.annotation_id)
                self._require_exact_replay(existing_record, existing_outputs, record, outputs)
                session.expunge(existing_record)
                for output in existing_outputs:
                    session.expunge(output)
                record = existing_record
                outputs = existing_outputs
        return self._view(record, outputs)

    def _existing_for_request(
        self,
        workflow_id: str,
        request_sha256: str,
        *,
        actor_id: str,
    ) -> (
        tuple[
            DocumentReviewPdfAnnotationRecord,
            tuple[DocumentReviewPdfAnnotationOutputRecord, ...],
        ]
        | None
    ):
        with self.sessions() as session:
            record = session.scalar(
                select(DocumentReviewPdfAnnotationRecord).where(
                    DocumentReviewPdfAnnotationRecord.operator_id == actor_id,
                    DocumentReviewPdfAnnotationRecord.workflow_id == workflow_id,
                    DocumentReviewPdfAnnotationRecord.request_sha256 == request_sha256,
                )
            )
            if record is None:
                return None
            outputs = self._outputs(session, record.annotation_id)
            session.expunge(record)
            for output in outputs:
                session.expunge(output)
            return record, outputs

    def annotation(
        self,
        workflow_id: str,
        annotation_id: str,
        *,
        actor_id: str,
    ) -> DocumentReviewAnnotationView:
        record, outputs = self._owned_annotation(workflow_id, annotation_id, actor_id=actor_id)
        return self._view(record, outputs)

    def download(
        self,
        workflow_id: str,
        annotation_id: str,
        document_role: str,
        *,
        actor_id: str,
    ) -> ProxiedItemMedia:
        _, outputs = self._owned_annotation(workflow_id, annotation_id, actor_id=actor_id)
        output = next((value for value in outputs if value.document_role == document_role), None)
        if output is None:
            raise self._not_found()
        pointer = DocumentReviewAnnotatedPdfPointer(
            artifact_id=output.artifact_id,
            artifact_revision_id=output.artifact_revision_id,
            document_role=cast(
                Literal["DOCUMENT", "QUESTION", "SOLUTION"],
                output.document_role,
            ),
            member_path=cast(
                Literal[
                    "annotated/document.pdf",
                    "annotated/question.pdf",
                    "annotated/solution.pdf",
                ],
                output.member_path,
            ),
            sha256=output.sha256,
            content_length=output.content_length,
            media_type=cast(Literal["application/pdf"], output.media_type),
            schema_ref=cast(
                Literal["eom://schemas/document-review/annotated-pdf/1.0"],
                output.schema_ref,
            ),
        )
        return self.catalog.download_document_review_annotated_pdf(
            DocumentReviewPdfAnnotationMediaQuery(
                workflow_id=workflow_id,
                annotation_id=annotation_id,
                document_role=cast(
                    Literal["DOCUMENT", "QUESTION", "SOLUTION"],
                    document_role,
                ),
                output=pointer,
            )
        )

    def _owned_annotation(
        self,
        workflow_id: str,
        annotation_id: str,
        *,
        actor_id: str,
    ) -> tuple[
        DocumentReviewPdfAnnotationRecord,
        tuple[DocumentReviewPdfAnnotationOutputRecord, ...],
    ]:
        with self.sessions() as session:
            record = session.scalar(
                select(DocumentReviewPdfAnnotationRecord).where(
                    DocumentReviewPdfAnnotationRecord.annotation_id == annotation_id,
                    DocumentReviewPdfAnnotationRecord.workflow_id == workflow_id,
                    DocumentReviewPdfAnnotationRecord.operator_id == actor_id,
                )
            )
            if record is None:
                raise self._not_found()
            outputs = self._outputs(session, annotation_id)
            session.expunge(record)
            for output in outputs:
                session.expunge(output)
            return record, outputs

    @staticmethod
    def _outputs(
        session: Session,
        annotation_id: str,
    ) -> tuple[DocumentReviewPdfAnnotationOutputRecord, ...]:
        values = tuple(
            session.scalars(
                select(DocumentReviewPdfAnnotationOutputRecord)
                .where(DocumentReviewPdfAnnotationOutputRecord.annotation_id == annotation_id)
                .order_by(DocumentReviewPdfAnnotationOutputRecord.document_role)
            )
        )
        return values

    @staticmethod
    def _require_exact_replay(
        existing: DocumentReviewPdfAnnotationRecord,
        existing_outputs: tuple[DocumentReviewPdfAnnotationOutputRecord, ...],
        candidate: DocumentReviewPdfAnnotationRecord,
        candidate_outputs: tuple[DocumentReviewPdfAnnotationOutputRecord, ...],
    ) -> None:
        fields = (
            "operator_id",
            "workflow_id",
            "request_sha256",
            "review_result_artifact_id",
            "review_result_artifact_revision_id",
            "review_result_sha256",
            "annotation_set_sha256",
            "manifest_artifact_id",
            "manifest_artifact_revision_id",
            "manifest_member_sha256",
            "manifest_self_sha256",
        )
        existing_values = tuple(
            (
                value.document_role,
                value.artifact_id,
                value.artifact_revision_id,
                value.member_path,
                value.sha256,
                value.content_length,
                value.media_type,
                value.schema_ref,
            )
            for value in existing_outputs
        )
        candidate_values = tuple(
            (
                value.document_role,
                value.artifact_id,
                value.artifact_revision_id,
                value.member_path,
                value.sha256,
                value.content_length,
                value.media_type,
                value.schema_ref,
            )
            for value in candidate_outputs
        )
        if (
            any(getattr(existing, field) != getattr(candidate, field) for field in fields)
            or existing_values != candidate_values
        ):
            raise ApiError(
                409,
                "DOCUMENT_REVIEW_ANNOTATION_IDEMPOTENCY_CONFLICT",
                "Annotated PDF replay differs",
                "The annotation identity already belongs to different immutable inputs.",
            )

    @staticmethod
    def _view(
        record: DocumentReviewPdfAnnotationRecord,
        outputs: tuple[DocumentReviewPdfAnnotationOutputRecord, ...],
    ) -> DocumentReviewAnnotationView:
        created_at = (
            record.created_at.replace(tzinfo=UTC)
            if record.created_at.tzinfo is None
            else record.created_at.astimezone(UTC)
        )
        return DocumentReviewAnnotationView(
            annotation_id=record.annotation_id,
            workflow_id=record.workflow_id,
            outputs=tuple(
                DocumentReviewAnnotationOutputView(
                    document_role=cast(
                        Literal["DOCUMENT", "QUESTION", "SOLUTION"],
                        value.document_role,
                    ),
                    sha256=value.sha256,
                    content_length=value.content_length,
                    download_url=(
                        f"/api/v1/pdf-document-reviews/{record.workflow_id}/annotations/"
                        f"{record.annotation_id}/documents/{value.document_role}/download"
                    ),
                )
                for value in outputs
            ),
            created_at=created_at,
            resource_version=record.lock_version,
        )

    @staticmethod
    def _not_found() -> ApiError:
        return ApiError(
            404,
            "DOCUMENT_REVIEW_ANNOTATION_NOT_FOUND",
            "Annotated PDF not found",
            "The annotation does not exist or is not visible to this Operator.",
        )
