"""Catalog-owned immutable annotated-PDF application service."""

from __future__ import annotations

import io
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol, cast

from eom_catalog_contracts import (
    DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER,
    CreateDocumentReviewAnnotatedPdfs,
    CreateDocumentReviewAnnotatedPdfsV2,
    DocumentReviewAnnotatedPdfMember,
    DocumentReviewAnnotatedPdfPointer,
    DocumentReviewPdfAnnotationManifest,
    DocumentReviewPdfAnnotationManifestV2,
    DocumentReviewPdfAnnotationMark,
    DocumentReviewPdfAnnotationMediaQuery,
    DocumentReviewPdfAnnotationRenderer,
    DocumentReviewPdfAnnotationRendererV2,
    DocumentReviewPdfAnnotationResponse,
    DocumentReviewPdfAnnotationResponseV2,
    DocumentReviewPdfAnnotationResult,
    DocumentReviewPdfAnnotationResultV2,
    DocumentReviewPdfPanelComment,
    DocumentReviewResultMemberPointer,
    OfficeDocumentReviewMemberPointer,
    PdfReviewArtifactMemberPointer,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes, sha256_file
from eom_workflow import (
    PairedDocumentReviewRoleResult,
    PairedReviewFinding,
    PdfDocumentReviewRoleResult,
    PdfReviewFinding,
)
from eom_workflow.schemas import validate_role_result
from jsonschema import ValidationError as JsonSchemaValidationError
from sqlalchemy import Engine

from eom_catalog_service.artifacts import CatalogArtifact, CatalogArtifactService
from eom_catalog_service.document_review_pdf_annotation import (
    DocumentReviewPdfAnnotationError,
    NativePanelCommentPayload,
    annotate_pdf,
    annotate_pdf_with_native_comments,
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
DOCUMENT_REVIEW_PDF_ANNOTATION_V2_PROTOCOL_VERSION = "catalog/1.21"
DOCUMENT_REVIEW_PDF_ANNOTATION_V2_SCHEMA_HASH = content_sha256(
    {
        "protocol": DOCUMENT_REVIEW_PDF_ANNOTATION_V2_PROTOCOL_VERSION,
        "contracts": [
            "document-review-pdf-annotation-request/2.0",
            "document-review-pdf-annotation-manifest/2.0",
            "document-review-pdf-annotation-result/2.0",
            "document-review-pdf-annotation-response/2.0",
        ],
    }
)


class DocumentReviewPdfAnnotationServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AnnotationArtifacts(Protocol):
    def load_json_revision(
        self,
        *,
        artifact_id: str,
        revision_id: str,
        content_hash: str,
        max_bytes: int,
    ) -> dict[str, Any]: ...

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
        command: CreateDocumentReviewAnnotatedPdfs | CreateDocumentReviewAnnotatedPdfsV2,
    ) -> DocumentReviewPdfAnnotationResponse | DocumentReviewPdfAnnotationResponseV2:
        parsed = self._validated_result(command)
        native_panel = isinstance(command, CreateDocumentReviewAnnotatedPdfsV2)
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
        panel_payloads = _native_panel_comments(parsed, command.annotations) if native_panel else ()
        try:
            with tempfile.TemporaryDirectory(
                prefix="document-review-annotation.",
                dir=self.settings.staging_root,
            ) as raw_workspace:
                workspace = Path(raw_workspace)
                output_members: list[DocumentReviewAnnotatedPdfMember] = []
                files: dict[str, Path] = {}
                renderer: (
                    DocumentReviewPdfAnnotationRenderer
                    | DocumentReviewPdfAnnotationRendererV2
                    | None
                ) = None
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
                    current_renderer: (
                        DocumentReviewPdfAnnotationRenderer | DocumentReviewPdfAnnotationRendererV2
                    )
                    if native_panel:
                        role_comments = tuple(
                            value
                            for value in panel_payloads
                            if value.descriptor.document_role == source.role
                        )
                        current_renderer = annotate_pdf_with_native_comments(
                            source_path,
                            destination,
                            role=source.role,
                            page_count=source.page_count,
                            annotations=role_marks,
                            panel_comments=role_comments,
                        )
                    else:
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
                manifest: (
                    DocumentReviewPdfAnnotationManifest | DocumentReviewPdfAnnotationManifestV2
                )
                result: DocumentReviewPdfAnnotationResult | DocumentReviewPdfAnnotationResultV2
                if native_panel:
                    panel_descriptors = tuple(value.descriptor for value in panel_payloads)
                    panel_comment_set_sha256 = content_sha256(
                        [value.model_dump(mode="json") for value in panel_descriptors]
                    )
                    manifest_payload: dict[str, object] = {
                        "schema_version": "document-review-pdf-annotation-manifest/2.0",
                        "annotation_profile": "NUMBERED_BOXES_WITH_NATIVE_COMMENTS",
                        "annotation_id": annotation_id,
                        "workflow_id": command.workflow_id,
                        "request_sha256": command.request_sha256,
                        "review_result_sha256": command.review_result.sha256,
                        "sources": command.sources,
                        "annotations": command.annotations,
                        "annotation_set_sha256": command.annotation_set_sha256,
                        "panel_comments": panel_descriptors,
                        "panel_comment_set_sha256": panel_comment_set_sha256,
                        "renderer": renderer,
                        "outputs": tuple(output_members),
                    }
                    manifest_payload["manifest_sha256"] = content_sha256(manifest_payload)
                    manifest = DocumentReviewPdfAnnotationManifestV2.model_validate(
                        manifest_payload
                    )
                    result_payload: dict[str, object] = {
                        "schema_version": "document-review-pdf-annotation-result/2.0",
                        "annotation_profile": "NUMBERED_BOXES_WITH_NATIVE_COMMENTS",
                        "annotation_id": annotation_id,
                        "workflow_id": command.workflow_id,
                        "request_sha256": command.request_sha256,
                        "review_result_sha256": command.review_result.sha256,
                        "annotation_set_sha256": command.annotation_set_sha256,
                        "panel_comment_set_sha256": panel_comment_set_sha256,
                        "panel_comment_count": len(panel_descriptors),
                        "outputs": tuple(output_members),
                        "manifest_sha256": manifest.manifest_sha256,
                    }
                    result_payload["result_sha256"] = content_sha256(result_payload)
                    result = DocumentReviewPdfAnnotationResultV2.model_validate(result_payload)
                    manifest_contract = "document-review-pdf-annotation-manifest-v2"
                    result_contract = "document-review-pdf-annotation-result-v2"
                    manifest_schema_ref = (
                        "eom://schemas/document-review/document-review-pdf-annotation-manifest/2.0"
                    )
                    result_schema_ref = (
                        "eom://schemas/document-review/document-review-pdf-annotation-result/2.0"
                    )
                    manifest_version = "document-review-pdf-annotation-file-set/2.0"
                    protocol_version = DOCUMENT_REVIEW_PDF_ANNOTATION_V2_PROTOCOL_VERSION
                    protocol_schema_hash = DOCUMENT_REVIEW_PDF_ANNOTATION_V2_SCHEMA_HASH
                else:
                    manifest_payload = {
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
                    result_payload = {
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
                    manifest_contract = "document-review-pdf-annotation-manifest"
                    result_contract = "document-review-pdf-annotation-result"
                    manifest_schema_ref = (
                        "eom://schemas/document-review/document-review-pdf-annotation-manifest/1.0"
                    )
                    result_schema_ref = (
                        "eom://schemas/document-review/document-review-pdf-annotation-result/1.0"
                    )
                    manifest_version = "document-review-pdf-annotation-file-set/1.0"
                    protocol_version = DOCUMENT_REVIEW_PDF_ANNOTATION_PROTOCOL_VERSION
                    protocol_schema_hash = DOCUMENT_REVIEW_PDF_ANNOTATION_SCHEMA_HASH
                validate_contract(manifest_contract, manifest.model_dump(mode="json"))
                validate_contract(result_contract, result.model_dump(mode="json"))
                manifest_path = workspace / DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER
                result_path = workspace / "result.json"
                manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
                result_bytes = canonical_json_bytes(result.model_dump(mode="json"))
                manifest_path.write_bytes(manifest_bytes)
                result_path.write_bytes(result_bytes)
                manifest_path.chmod(0o600)
                result_path.chmod(0o600)
                files.update(
                    {
                        DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER: manifest_path,
                        "result.json": result_path,
                    }
                )
                expected = {name: sha256_file(path) for name, path in files.items()}
                file_metadata = {
                    DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER: {
                        "media_type": "application/json",
                        "schema_ref": manifest_schema_ref,
                    },
                    "result.json": {
                        "media_type": "application/json",
                        "schema_ref": result_schema_ref,
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
                    manifest_version=manifest_version,
                    protocol_version=protocol_version,
                    protocol_schema_hash=protocol_schema_hash,
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
            member_path=DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER,
            sha256=expected[DOCUMENT_REVIEW_PDF_ANNOTATION_MANIFEST_MEMBER],
            content_length=len(manifest_bytes),
            media_type="application/json",
            schema_ref=manifest_schema_ref,
        )
        response: DocumentReviewPdfAnnotationResponse | DocumentReviewPdfAnnotationResponseV2
        if native_panel:
            assert isinstance(result, DocumentReviewPdfAnnotationResultV2)
            response = DocumentReviewPdfAnnotationResponseV2(
                status="OK",
                outputs=output_pointers,
                manifest=manifest_pointer,
                result=result,
            )
            response_contract = "document-review-pdf-annotation-response-v2"
        else:
            assert isinstance(result, DocumentReviewPdfAnnotationResult)
            response = DocumentReviewPdfAnnotationResponse(
                status="OK",
                outputs=output_pointers,
                manifest=manifest_pointer,
                result=result,
            )
            response_contract = "document-review-pdf-annotation-response"
        validate_contract(response_contract, response.model_dump(mode="json", exclude_none=True))
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
        command: CreateDocumentReviewAnnotatedPdfs | CreateDocumentReviewAnnotatedPdfsV2,
    ) -> PdfDocumentReviewRoleResult | PairedDocumentReviewRoleResult:
        try:
            raw = self.artifacts.load_json_revision(
                artifact_id=command.review_result.artifact_id,
                revision_id=command.review_result.artifact_revision_id,
                content_hash=command.review_result.sha256,
                max_bytes=16 * 1024 * 1024,
            )
            canonical_bytes = canonical_json_bytes(raw)
            if (
                len(canonical_bytes) != command.review_result.content_length
                or content_sha256(raw) != command.review_result.sha256
            ):
                raise ValueError("document review result pointer metadata differs")
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_POINTER_INVALID",
                "The document review result pointer could not be resolved",
            ) from exc
        try:
            result_schema = (
                "pdf-document-review-result@2.0"
                if command.review_result.schema_ref.endswith(
                    "/paired-document-review-result-v2.schema.json"
                )
                else "pdf-document-review-result@1.0"
            )
            parsed = validate_role_result(raw, "support", result_schema)
        except (JsonSchemaValidationError, ValueError) as exc:
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


def _native_panel_comments(
    parsed: PdfDocumentReviewRoleResult | PairedDocumentReviewRoleResult,
    annotations: tuple[DocumentReviewPdfAnnotationMark, ...],
) -> tuple[NativePanelCommentPayload, ...]:
    findings: tuple[PdfReviewFinding | PairedReviewFinding, ...] = parsed.output.findings
    by_finding = {value.finding_id: value for value in findings}
    primary: dict[tuple[str, str], DocumentReviewPdfAnnotationMark] = {}
    for mark in annotations:
        primary.setdefault((mark.finding_id, mark.document_role), mark)
    comments: list[NativePanelCommentPayload] = []
    for mark in primary.values():
        finding = by_finding.get(mark.finding_id)
        if finding is None or finding.ordinal != mark.ordinal:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_FINDINGS_MISMATCH",
                "A native PDF panel comment differs from the validated review finding",
            )
        contents = _native_panel_comment_contents(finding)
        encoded = contents.encode("utf-8")
        if not 1 <= len(encoded) <= 65536:
            raise DocumentReviewPdfAnnotationServiceError(
                "DOCUMENT_REVIEW_ANNOTATION_COMMENT_TOO_LARGE",
                "A native PDF panel comment exceeds its fixed bound",
            )
        contents_sha256 = sha256_bytes(encoded)
        comment_digest = content_sha256(
            {
                "profile": "NUMBERED_BOXES_WITH_NATIVE_COMMENTS",
                "finding_id": mark.finding_id,
                "anchor_id": mark.anchor_id,
                "document_role": mark.document_role,
                "contents_sha256": contents_sha256,
            }
        ).removeprefix("sha256:")
        descriptor = DocumentReviewPdfPanelComment(
            comment_id=f"reviewcomment_{comment_digest[:32]}",
            finding_id=mark.finding_id,
            anchor_id=mark.anchor_id,
            ordinal=mark.ordinal,
            document_role=mark.document_role,
            page_number=mark.page_number,
            contents_sha256=contents_sha256,
            contents_utf8_length=len(encoded),
        )
        comments.append(
            NativePanelCommentPayload(
                descriptor=descriptor,
                contents=contents,
                region=mark.region,
            )
        )
    return tuple(comments)


def _native_panel_comment_contents(
    finding: PdfReviewFinding | PairedReviewFinding,
) -> str:
    recommendation = finding.recommendation
    lines = [
        f"검토 #{finding.ordinal} · {finding.title}",
        f"분류: {finding.category}",
        f"중요도: {finding.severity}",
        "",
        finding.description,
        "",
        f"수정 권고 ({recommendation.operation})",
        recommendation.instruction,
    ]
    if recommendation.before_text is not None:
        lines.extend(("", "기존 문구", recommendation.before_text))
    if recommendation.after_text is not None:
        lines.extend(("", "제안 문구", recommendation.after_text))
    return "\n".join(lines)
