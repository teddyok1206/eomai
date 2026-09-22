"""Catalog-owned immutable annotated-PDF application service."""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol, cast

from eom_catalog_contracts import (
    CreateDocumentReviewAnnotatedPdfs,
    DocumentReviewAnnotatedPdfMember,
    DocumentReviewAnnotatedPdfPointer,
    DocumentReviewPdfAnnotationManifest,
    DocumentReviewPdfAnnotationMediaQuery,
    DocumentReviewPdfAnnotationResponse,
    DocumentReviewPdfAnnotationResult,
    DocumentReviewResultMemberPointer,
    OfficeDocumentReviewMemberPointer,
    PdfReviewArtifactMemberPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_file
from eom_workflow import PairedDocumentReviewRoleResult, PdfDocumentReviewRoleResult
from eom_workflow.schemas import validate_role_result
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.document_review_pdf_annotation import (
    DocumentReviewPdfAnnotationError,
    annotate_pdf,
)
from eom_catalog_service.settings import CatalogSettings

DOCUMENT_REVIEW_PDF_ANNOTATION_PROTOCOL_VERSION = "catalog/1.19"
DOCUMENT_REVIEW_PDF_ANNOTATION_SCHEMA_HASH = content_sha256(
    {
        "protocol": DOCUMENT_REVIEW_PDF_ANNOTATION_PROTOCOL_VERSION,
        "contracts": [
            "document-review-pdf-annotation-request/1.0",
            "document-review-pdf-annotation-manifest/1.0",
            "document-review-pdf-annotation-result/1.0",
            "document-review-pdf-annotation-response/1.0",
        ],
    }
)


class DocumentReviewPdfAnnotationServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AnnotationArtifacts(Protocol):
    def read_member(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        member_path: str,
        sha256: str,
        media_type: str,
        schema_ref: str,
        max_bytes: int,
    ) -> bytes: ...

    def commit_file_set(
        self,
        *,
        files: dict[str, Path],
        primary_file: str,
        artifact_type: str,
        idempotency_key: str,
        request: dict[str, object],
        result: dict[str, object],
        file_metadata: dict[str, dict[str, str]] | None = None,
        manifest_version: str = "catalog-file-set/1.0",
        protocol_version: str,
        protocol_schema_hash: str,
        expected_file_sha256: dict[str, str] | None = None,
    ) -> CatalogArtifact: ...


ReadableAnnotationPointer = (
    DocumentReviewResultMemberPointer
    | DocumentReviewAnnotatedPdfPointer
    | OfficeDocumentReviewMemberPointer
    | PdfReviewArtifactMemberPointer
)


@dataclass(frozen=True)
class ResolvedDocumentReviewAnnotatedPdf:
    stream: BinaryIO
    content_length: int
    sha256: str
    media_type: str = "application/pdf"

    def iter_chunks(self) -> Generator[bytes, None, None]:
        try:
            while chunk := self.stream.read(1024 * 1024):
                yield chunk
        finally:
            self.stream.close()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


class DocumentReviewPdfAnnotationService:
    def __init__(
        self,
        engine: Engine,
        settings: CatalogSettings | None = None,
        *,
        artifacts: AnnotationArtifacts | None = None,
    ) -> None:
        self.settings = settings or CatalogSettings.from_environment()
        self.artifacts: AnnotationArtifacts = artifacts or CatalogArtifactService(
            engine,
            self.settings,
        )

    def create(
        self,
        command: CreateDocumentReviewAnnotatedPdfs,
    ) -> DocumentReviewPdfAnnotationResponse:
        parsed = self._validated_result(command)
        expected_documents: tuple[tuple[str, str, str, str], ...]
        expected_marks: list[tuple[str, str, int, str, int, str, dict[str, object]]] = []
        if isinstance(parsed, PdfDocumentReviewRoleResult):
            expected_documents = (
                (
                    "DOCUMENT",
                    parsed.output.document_id,
                    parsed.output.document_revision_id,
                    parsed.output.source_pdf_sha256,
                ),
            )
            for finding in parsed.output.findings:
                for anchor in finding.anchors:
                    expected_marks.append(
                        (
                            finding.finding_id,
                            anchor.anchor_id,
                            finding.ordinal,
                            "DOCUMENT",
                            anchor.page_number,
                            anchor.page_image_sha256,
                            anchor.region.model_dump(mode="json"),
                        )
                    )
        elif isinstance(parsed, PairedDocumentReviewRoleResult):
            expected_documents = tuple(
                (
                    value.role,
                    value.document_id,
                    value.document_revision_id,
                    value.source_pdf_sha256,
                )
                for value in parsed.output.documents
            )
            for finding in parsed.output.findings:
                for anchor in finding.anchors:
                    expected_marks.append(
                        (
                            finding.finding_id,
                            anchor.anchor_id,
                            finding.ordinal,
                            anchor.document_role,
                            anchor.page_number,
                            anchor.page_image_sha256,
                            anchor.region.model_dump(mode="json"),
                        )
                    )
        else:  # pragma: no cover - validate_role_result is a closed union
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_RESULT_INVALID",
                "The document review result schema is unsupported",
            )
        expected_marks.sort(key=lambda value: (value[3], value[4], value[2], value[1]))
        actual_marks = [
            (
                value.finding_id,
                value.anchor_id,
                value.ordinal,
                value.document_role,
                value.page_number,
                value.page_image_sha256,
                value.region.model_dump(mode="json"),
            )
            for value in command.annotations
        ]
        if actual_marks != expected_marks:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_FINDINGS_MISMATCH",
                "The annotation set differs from the validated review findings",
            )
        actual_documents = tuple(
            (
                value.role,
                value.document_id,
                value.document_revision_id,
                value.source_pdf.sha256,
            )
            for value in command.sources
        )
        if actual_documents != expected_documents:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_SOURCE_MISMATCH",
                "The annotation sources differ from the validated review result",
            )
        try:
            with tempfile.TemporaryDirectory(
                prefix="document-review-annotation.",
                dir=self.settings.staging_root,
            ) as raw_workspace:
                workspace = Path(raw_workspace)
                output_members: list[DocumentReviewAnnotatedPdfMember] = []
                files: dict[str, Path] = {}
                renderer = None
                for source in command.sources:
                    source_bytes = self._read_pointer(source.source_pdf, 256 * 1024 * 1024)
                    source_path = workspace / f"source-{source.role.lower()}.pdf"
                    source_path.write_bytes(source_bytes)
                    source_path.chmod(0o600)
                    member_path = cast(
                        Literal[
                            "annotated/document.pdf",
                            "annotated/question.pdf",
                            "annotated/solution.pdf",
                        ],
                        {
                            "DOCUMENT": "annotated/document.pdf",
                            "QUESTION": "annotated/question.pdf",
                            "SOLUTION": "annotated/solution.pdf",
                        }[source.role],
                    )
                    destination = workspace / member_path
                    destination.parent.mkdir(mode=0o700, parents=False, exist_ok=True)
                    role_marks = tuple(
                        value for value in command.annotations if value.document_role == source.role
                    )
                    current_renderer = annotate_pdf(
                        source_path,
                        destination,
                        role=source.role,
                        page_count=source.page_count,
                        annotations=role_marks,
                    )
                    if renderer is not None and current_renderer != renderer:
                        raise DocumentReviewPdfAnnotationServiceError(
                            "DOCUMENT_REVIEW_ANNOTATION_RENDERER_DRIFT",
                            "Renderer identity changed within one annotation operation",
                        )
                    renderer = current_renderer
                    descriptor = DocumentReviewAnnotatedPdfMember(
                        document_role=source.role,
                        member_path=member_path,
                        sha256=sha256_file(destination),
                        content_length=destination.stat().st_size,
                    )
                    output_members.append(descriptor)
                    files[member_path] = destination
                if renderer is None:
                    raise DocumentReviewPdfAnnotationServiceError(
                        "DOCUMENT_REVIEW_ANNOTATION_SOURCE_MISSING",
                        "No annotation source was supplied",
                    )
                annotation_digest = content_sha256(
                    {
                        "workflow_id": command.workflow_id,
                        "request_sha256": command.request_sha256,
                        "review_result_sha256": command.review_result.sha256,
                        "renderer": renderer.model_dump(mode="json"),
                    }
                ).removeprefix("sha256:")
                annotation_id = f"docannotation_{annotation_digest[:32]}"
                manifest_payload: dict[str, object] = {
                    "schema_version": "document-review-pdf-annotation-manifest/1.0",
                    "annotation_id": annotation_id,
                    "workflow_id": command.workflow_id,
                    "request_sha256": command.request_sha256,
                    "review_result_sha256": command.review_result.sha256,
                    "sources": command.sources,
                    "annotations": command.annotations,
                    "annotation_set_sha256": command.annotation_set_sha256,
                    "renderer": renderer,
                    "outputs": tuple(output_members),
                }
                manifest_payload["manifest_sha256"] = content_sha256(manifest_payload)
                manifest = DocumentReviewPdfAnnotationManifest.model_validate(manifest_payload)
                result_payload: dict[str, object] = {
                    "schema_version": "document-review-pdf-annotation-result/1.0",
                    "annotation_id": annotation_id,
                    "workflow_id": command.workflow_id,
                    "request_sha256": command.request_sha256,
                    "review_result_sha256": command.review_result.sha256,
                    "annotation_set_sha256": command.annotation_set_sha256,
                    "outputs": tuple(output_members),
                    "manifest_sha256": manifest.manifest_sha256,
                }
                result_payload["result_sha256"] = content_sha256(result_payload)
                result = DocumentReviewPdfAnnotationResult.model_validate(result_payload)
                validate_contract(
                    "document-review-pdf-annotation-manifest",
                    manifest.model_dump(mode="json"),
                )
                validate_contract(
                    "document-review-pdf-annotation-result",
                    result.model_dump(mode="json"),
                )
                manifest_path = workspace / "manifest.json"
                result_path = workspace / "result.json"
                manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
                result_bytes = canonical_json_bytes(result.model_dump(mode="json"))
                manifest_path.write_bytes(manifest_bytes)
                result_path.write_bytes(result_bytes)
                manifest_path.chmod(0o600)
                result_path.chmod(0o600)
                files.update({"manifest.json": manifest_path, "result.json": result_path})
                expected = {name: sha256_file(path) for name, path in files.items()}
                file_metadata = {
                    "manifest.json": {
                        "media_type": "application/json",
                        "schema_ref": (
                            "eom://schemas/document-review/"
                            "document-review-pdf-annotation-manifest/1.0"
                        ),
                    },
                    "result.json": {
                        "media_type": "application/json",
                        "schema_ref": (
                            "eom://schemas/document-review/"
                            "document-review-pdf-annotation-result/1.0"
                        ),
                    },
                }
                file_metadata.update(
                    {
                        value.member_path: {
                            "media_type": value.media_type,
                            "schema_ref": value.schema_ref,
                        }
                        for value in output_members
                    }
                )
                artifact = self.artifacts.commit_file_set(
                    files=files,
                    primary_file="result.json",
                    artifact_type="document-review-pdf-annotation",
                    idempotency_key=(f"document-review-pdf-annotation:{command.request_sha256}"),
                    request=command.model_dump(mode="json", exclude={"idempotency_key"}),
                    result=result.model_dump(mode="json"),
                    file_metadata=file_metadata,
                    manifest_version="document-review-pdf-annotation-file-set/1.0",
                    protocol_version=DOCUMENT_REVIEW_PDF_ANNOTATION_PROTOCOL_VERSION,
                    protocol_schema_hash=DOCUMENT_REVIEW_PDF_ANNOTATION_SCHEMA_HASH,
                    expected_file_sha256=expected,
                )
        except DocumentReviewPdfAnnotationError as exc:
            raise DocumentReviewPdfAnnotationServiceError(exc.code, str(exc)) from exc
        output_pointers = tuple(
            DocumentReviewAnnotatedPdfPointer(
                artifact_id=artifact.artifact_id,
                artifact_revision_id=artifact.revision_id,
                **value.model_dump(mode="python"),
            )
            for value in result.outputs
        )
        manifest_pointer = OfficeDocumentReviewMemberPointer(
            artifact_id=artifact.artifact_id,
            artifact_revision_id=artifact.revision_id,
            member_path="manifest.json",
            sha256=expected["manifest.json"],
            content_length=len(manifest_bytes),
            media_type="application/json",
            schema_ref=(
                "eom://schemas/document-review/document-review-pdf-annotation-manifest/1.0"
            ),
        )
        response = DocumentReviewPdfAnnotationResponse(
            status="OK",
            outputs=output_pointers,
            manifest=manifest_pointer,
            result=result,
        )
        validate_contract(
            "document-review-pdf-annotation-response",
            response.model_dump(mode="json", exclude_none=True),
        )
        return response

    def load_output(
        self,
        query: DocumentReviewPdfAnnotationMediaQuery,
    ) -> ResolvedDocumentReviewAnnotatedPdf:
        payload = self._read_pointer(query.output, 512 * 1024 * 1024)
        return ResolvedDocumentReviewAnnotatedPdf(
            stream=io.BytesIO(payload),
            content_length=len(payload),
            sha256=query.output.sha256,
        )

    def _validated_result(
        self,
        command: CreateDocumentReviewAnnotatedPdfs,
    ) -> PdfDocumentReviewRoleResult | PairedDocumentReviewRoleResult:
        raw_bytes = self._read_pointer(command.review_result, 16 * 1024 * 1024)
        try:
            raw: object = json.loads(
                raw_bytes.decode("utf-8", errors="strict"),
                object_pairs_hook=_unique_json_object,
            )
            result_schema = (
                "paired-document-review-result@2.0"
                if command.review_result.schema_ref.endswith(
                    "/paired-document-review-result-v2.schema.json"
                )
                else "pdf-document-review-result@1.0"
            )
            parsed = validate_role_result(raw, "support", result_schema)
        except (UnicodeError, JsonSchemaValidationError, ValueError) as exc:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_RESULT_INVALID",
                "The document review result is invalid",
            ) from exc
        if not isinstance(parsed, (PdfDocumentReviewRoleResult, PairedDocumentReviewRoleResult)):
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_RESULT_INVALID",
                "The document review result type is unsupported",
            )
        if parsed.workflow_id != command.workflow_id:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_RESULT_MISMATCH",
                "The document review result belongs to another Workflow",
            )
        return parsed

    def _read_pointer(
        self,
        pointer: ReadableAnnotationPointer,
        max_bytes: int,
    ) -> bytes:
        try:
            return self.artifacts.read_member(
                artifact_id=pointer.artifact_id,
                revision_id=pointer.artifact_revision_id,
                member_path=pointer.member_path,
                sha256=pointer.sha256,
                media_type=pointer.media_type,
                schema_ref=pointer.schema_ref,
                max_bytes=max_bytes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_POINTER_INVALID",
                "An annotation pointer could not be resolved",
            ) from exc
