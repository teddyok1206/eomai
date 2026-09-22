"""Application API adapter for the private Catalog application socket."""

from __future__ import annotations

import grp
import hashlib
import json
import os
import pwd
import socket
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from eom_catalog_contracts import (
    CATALOG_APPLICATION_MAX_MESSAGE_BYTES,
    CATALOG_APPLICATION_SOCKET_MODE,
    CATALOG_APPLICATION_SOCKET_PATH,
    CATALOG_ASSESSMENT_PAGE_MAX_BYTES,
    CATALOG_ITEM_MEDIA_MAX_BYTES,
    PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES,
    ApplyDocumentReviewHwpxCorrections,
    ApprovedItemGraphPublicationResult,
    AssessmentItemContentContract,
    AssessmentPageImagePointer,
    AssessmentPageListQuery,
    AssessmentPageMediaQuery,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CatalogAssessmentPageListResponse,
    CatalogAssessmentPageMediaResponse,
    CatalogItemComponentMediaResponse,
    CatalogItemMediaResponse,
    CreateDocumentReviewAnnotatedPdfs,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CreateKnowledgeAnalysisBatchCommand,
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    CreateMockExamAssemblyCommand,
    CreatePlannedMockExamAssemblyCommand,
    DocumentReviewHwpxCorrectionMediaQuery,
    DocumentReviewHwpxCorrectionMediaResponse,
    DocumentReviewHwpxCorrectionResponse,
    DocumentReviewPdfAnnotationMediaQuery,
    DocumentReviewPdfAnnotationMediaResponse,
    DocumentReviewPdfAnnotationResponse,
    EvidenceBundlePublicationResult,
    EvidenceBundlePublicationResultV2,
    EvidenceBundlePublicationResultV3,
    EvidenceBundlePublicationResultV4,
    InspectMockExamAssemblyQuery,
    InspectMockExamReviewEligibilityQuery,
    ItemComponentMediaQuery,
    ItemContentQuery,
    ItemMediaQuery,
    KnowledgeAnalysisApplicationResult,
    KnowledgeAnalysisBatchApplicationResult,
    MockExamAssemblyManifestContract,
    MockExamAssemblyPlanContract,
    MockExamItemReviewPublicationResult,
    MockExamReviewEligibilityResult,
    OfficeDocumentReviewIntakeCommand,
    OfficeDocumentReviewIntakeResponse,
    OfficeDocumentReviewSourcePointer,
    PdfDocumentReviewIntakeCommand,
    PdfDocumentReviewIntakeResponse,
    PdfDocumentReviewPageMediaQuery,
    PdfDocumentReviewPageMediaResponse,
    PdfReviewArtifactMemberPointer,
    PreviewMockExamAssemblyPlanCommand,
    PublishApprovedItemAnalysesCommand,
    PublishMockExamItemReviewCommand,
    ReconcileKnowledgeAnalysisCommand,
    ReviewedItemContentImportCommand,
    ReviewedItemContentImportResult,
    ReviewKnowledgeAnalysisCommand,
    catalog_application_schema_route,
    validate_contract,
)
from eom_item_registry import RegistryError, RegistryErrorCode
from eom_workflow import PdfReviewDocumentPointer
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

CONNECT_TIMEOUT_SECONDS = 5.0
RESPONSE_TIMEOUT_SECONDS = 30.0
# Evidence selection validates and ranks a bounded Graph snapshot before publishing its immutable
# bundle. It can exceed the short metadata RPC bound, so these evidence-producing operations use a
# larger bounded window. API idempotency ownership is independently CAS-protected against a stale
# callback, and its default lease includes margin around this socket wait.
EVIDENCE_RESPONSE_TIMEOUT_SECONDS = 120.0
# Exact-cohort planning validates 25 immutable Item, review, Graph, and Artifact pointer chains.
# Keep this privileged Catalog/NAS work off the API process and give the bounded socket operation
# the same reviewed idle-response window as evidence construction.
ASSEMBLY_RESPONSE_TIMEOUT_SECONDS = 120.0
PDF_DOCUMENT_REVIEW_UPLOAD_TIMEOUT_SECONDS = 300.0
PDF_DOCUMENT_REVIEW_RESPONSE_TIMEOUT_SECONDS = 1800.0


@dataclass(frozen=True)
class ProxiedItemMedia:
    connection: socket.socket
    media_type: str
    content_length: int
    sha256: str

    def iter_chunks(self) -> Iterator[bytes]:
        digest = hashlib.sha256()
        remaining = self.content_length
        try:
            while remaining:
                chunk = self.connection.recv(min(1024 * 1024, remaining))
                if not chunk:
                    raise RuntimeError("Catalog media stream ended before its declared size")
                remaining -= len(chunk)
                digest.update(chunk)
                yield chunk
            if self.connection.recv(1):
                raise RuntimeError("Catalog media stream exceeded its declared size")
            if "sha256:" + digest.hexdigest() != self.sha256:
                raise RuntimeError("Catalog media stream failed end-to-end SHA-256 validation")
        finally:
            self.connection.close()


class CatalogApplicationClientError(RuntimeError):
    def __init__(self, code: str | CatalogApplicationErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


class CatalogApplicationClient:
    def __init__(
        self,
        socket_path: Path = Path(CATALOG_APPLICATION_SOCKET_PATH),
        *,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.expected_uid = expected_uid
        self.expected_gid = grp.getgrnam("eom-api").gr_gid if expected_gid is None else expected_gid

    def import_reviewed(
        self,
        command: ReviewedItemContentImportCommand,
    ) -> ReviewedItemContentImportResult:
        response = self._request(command)
        if response.operation != command.operation or response.result is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application import response is invalid",
            )
        return response.result

    def ingest_pdf_document_review_source(
        self,
        source: Path,
        *,
        actor_id: str,
        original_filename: str,
        idempotency_key: str,
    ) -> PdfReviewDocumentPointer:
        """Stream one stable local PDF to Catalog and return its immutable pointer."""

        descriptor = -1
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            descriptor = os.open(
                source,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 8 <= before.st_size <= 256 * 1024 * 1024
            ):
                raise ValueError("PDF review upload is not one bounded regular file")
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("PDF review upload ended before its opened size")
                digest.update(chunk)
                remaining -= len(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
            command = PdfDocumentReviewIntakeCommand(
                actor_id=actor_id,
                original_filename=original_filename,
                idempotency_key=idempotency_key,
                content_length=before.st_size,
                sha256="sha256:" + digest.hexdigest(),
            )
            payload = command.model_dump(mode="json")
            validate_contract("pdf-document-review-intake-request", payload)
            self._validate_socket()
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            header = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            if len(header) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
                raise ValueError("PDF review intake header exceeds its fixed bound")
            connection.settimeout(PDF_DOCUMENT_REVIEW_UPLOAD_TIMEOUT_SECONDS)
            connection.sendall(header + b"\n")
            sent_digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("PDF review upload changed while streaming")
                connection.sendall(chunk)
                sent_digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            ) or "sha256:" + sent_digest.hexdigest() != command.sha256:
                raise ValueError("PDF review upload identity changed while streaming")
            connection.shutdown(socket.SHUT_WR)
            connection.settimeout(PDF_DOCUMENT_REVIEW_RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_response(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("PDF review intake response is not an object")
            validate_contract("pdf-document-review-intake-response", value)
            response = PdfDocumentReviewIntakeResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.document is not None
            return response.document
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog PDF document-review intake boundary is unavailable",
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            connection.close()

    def ingest_office_document_review_source(
        self,
        source: Path,
        *,
        actor_id: str,
        original_filename: str,
        source_format: Literal["PDF", "HWP", "HWPX"],
        media_type: Literal[
            "application/pdf",
            "application/vnd.hancom.hwp",
            "application/vnd.hancom.hwpx",
        ],
        idempotency_key: str,
    ) -> OfficeDocumentReviewSourcePointer:
        """Stream one stable document to Catalog and return its immutable PDF projection."""

        descriptor = -1
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            descriptor = os.open(
                source,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 8 <= before.st_size <= 256 * 1024 * 1024
            ):
                raise ValueError("Document review upload is not one bounded regular file")
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Document review upload ended before its opened size")
                digest.update(chunk)
                remaining -= len(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
            command = OfficeDocumentReviewIntakeCommand(
                actor_id=actor_id,
                original_filename=original_filename,
                source_format=source_format,
                media_type=media_type,
                idempotency_key=idempotency_key,
                content_length=before.st_size,
                sha256="sha256:" + digest.hexdigest(),
            )
            payload = command.model_dump(mode="json")
            validate_contract("document-review-intake-request-v2", payload)
            self._validate_socket()
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            header = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            if len(header) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
                raise ValueError("Document review intake header exceeds its fixed bound")
            connection.settimeout(PDF_DOCUMENT_REVIEW_UPLOAD_TIMEOUT_SECONDS)
            connection.sendall(header + b"\n")
            sent_digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Document review upload changed while streaming")
                connection.sendall(chunk)
                sent_digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_mode,
                before.st_uid,
                before.st_gid,
                before.st_nlink,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_mode,
                after.st_uid,
                after.st_gid,
                after.st_nlink,
                after.st_size,
                after.st_mtime_ns,
            ) or "sha256:" + sent_digest.hexdigest() != command.sha256:
                raise ValueError("Document review upload identity changed while streaming")
            connection.shutdown(socket.SHUT_WR)
            connection.settimeout(PDF_DOCUMENT_REVIEW_RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_response(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Document review intake response is not an object")
            validate_contract("document-review-intake-response-v2", value)
            response = OfficeDocumentReviewIntakeResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.document is not None
            return response.document
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog Office document-review intake boundary is unavailable",
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            connection.close()

    def apply_document_review_hwpx_corrections(
        self,
        command: ApplyDocumentReviewHwpxCorrections,
    ) -> DocumentReviewHwpxCorrectionResponse:
        payload = command.model_dump(mode="json")
        validate_contract("document-review-hwpx-correction-request", payload)
        value = self._raw_request(
            payload, timeout_seconds=PDF_DOCUMENT_REVIEW_RESPONSE_TIMEOUT_SECONDS
        )
        validate_contract("document-review-hwpx-correction-response", value)
        response = DocumentReviewHwpxCorrectionResponse.model_validate(value)
        if response.status == "ERROR":
            self._raise_remote_error(response.error_code)
        return response

    def download_document_review_corrected_hwpx(
        self,
        query: DocumentReviewHwpxCorrectionMediaQuery,
    ) -> ProxiedItemMedia:
        payload = query.model_dump(mode="json")
        validate_contract("document-review-hwpx-correction-media-request", payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_media_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("HWPX correction media header is not an object")
            validate_contract("document-review-hwpx-correction-media-response", value)
            response = DocumentReviewHwpxCorrectionMediaResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.media_type is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            if (
                response.content_length != query.output.content_length
                or response.sha256 != query.output.sha256
            ):
                raise ValueError("Catalog HWPX bytes differ from their pinned pointer")
            return ProxiedItemMedia(
                connection=connection,
                media_type=response.media_type,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except CatalogApplicationClientError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog corrected HWPX media boundary is unavailable",
            ) from exc

    def create_document_review_annotated_pdfs(
        self,
        command: CreateDocumentReviewAnnotatedPdfs,
    ) -> DocumentReviewPdfAnnotationResponse:
        payload = command.model_dump(mode="json")
        validate_contract("document-review-pdf-annotation-request", payload)
        value = self._raw_request(
            payload,
            timeout_seconds=PDF_DOCUMENT_REVIEW_RESPONSE_TIMEOUT_SECONDS,
        )
        validate_contract("document-review-pdf-annotation-response", value)
        response = DocumentReviewPdfAnnotationResponse.model_validate(value)
        if response.status == "ERROR":
            self._raise_remote_error(response.error_code)
        return response

    def download_document_review_annotated_pdf(
        self,
        query: DocumentReviewPdfAnnotationMediaQuery,
    ) -> ProxiedItemMedia:
        payload = query.model_dump(mode="json")
        validate_contract("document-review-pdf-annotation-media-request", payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_media_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("PDF annotation media header is not an object")
            validate_contract("document-review-pdf-annotation-media-response", value)
            response = DocumentReviewPdfAnnotationMediaResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.media_type is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            if (
                response.content_length != query.output.content_length
                or response.sha256 != query.output.sha256
            ):
                raise ValueError("Catalog annotated PDF bytes differ from their pinned pointer")
            return ProxiedItemMedia(
                connection=connection,
                media_type=response.media_type,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except CatalogApplicationClientError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog annotated PDF media boundary is unavailable",
            ) from exc

    def download_pdf_document_review_page(
        self,
        *,
        document_id: str,
        document_revision_id: str,
        page_number: int,
        page_image: PdfReviewArtifactMemberPointer,
    ) -> ProxiedItemMedia:
        command = PdfDocumentReviewPageMediaQuery(
            document_id=document_id,
            document_revision_id=document_revision_id,
            page_number=page_number,
            page_image=page_image,
        )
        payload = command.model_dump(mode="json")
        validate_contract("pdf-document-review-page-media-request", payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_media_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("pdf-document-review-page-media-response", value)
            response = PdfDocumentReviewPageMediaResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.media_type is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            if (
                response.content_length > PDF_DOCUMENT_REVIEW_PAGE_MAX_BYTES
                or response.content_length != page_image.content_length
                or response.sha256 != page_image.sha256
            ):
                raise ValueError("Catalog PDF review page differs from its pinned pointer")
            return ProxiedItemMedia(
                connection=connection,
                media_type=response.media_type,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except CatalogApplicationClientError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog PDF document-review page boundary is unavailable",
            ) from exc

    def load_item_content(self, item_revision_id: str) -> AssessmentItemContentContract:
        command = ItemContentQuery(item_revision_id=item_revision_id)
        response = self._request(command)
        if response.operation != command.operation or response.content is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application content response is invalid",
            )
        return response.content

    def download_item_media(self, item_revision_id: str, block_id: str) -> ProxiedItemMedia:
        command = ItemMediaQuery(item_revision_id=item_revision_id, block_id=block_id)
        return self._download_item_media(command)

    def download_item_component_media(
        self,
        item_revision_id: str,
        component_type: Literal["IMAGE"],
        ordinal: int,
    ) -> ProxiedItemMedia:
        command = ItemComponentMediaQuery.model_validate(
            {
                "item_revision_id": item_revision_id,
                "component_type": component_type,
                "ordinal": ordinal,
            }
        )
        return self._download_item_media(command)

    def _download_item_media(
        self,
        command: ItemMediaQuery | ItemComponentMediaQuery,
    ) -> ProxiedItemMedia:
        component_request = isinstance(command, ItemComponentMediaQuery)
        request_contract = (
            "catalog-item-component-media-request"
            if component_request
            else "catalog-item-media-request"
        )
        response_contract = (
            "catalog-item-component-media-response"
            if component_request
            else "catalog-item-media-response"
        )
        payload = command.model_dump(mode="json")
        validate_contract(request_contract, payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_media_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract(response_contract, value)
            response = (
                CatalogItemComponentMediaResponse.model_validate(value)
                if component_request
                else CatalogItemMediaResponse.model_validate(value)
            )
            if response.operation != command.operation:
                raise ValueError("Catalog media response operation differs")
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.media_type is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            if response.content_length > CATALOG_ITEM_MEDIA_MAX_BYTES:
                raise ValueError("Catalog media response exceeds its fixed bound")
            return ProxiedItemMedia(
                connection=connection,
                media_type=response.media_type,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except CatalogApplicationClientError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog media boundary is unavailable",
            ) from exc

    def assessment_pages(
        self,
        extraction_batch_id: str,
        assessment_occurrence_revision_id: str,
    ) -> tuple[AssessmentPageImagePointer, ...]:
        command = AssessmentPageListQuery(
            extraction_batch_id=extraction_batch_id,
            assessment_occurrence_revision_id=assessment_occurrence_revision_id,
        )
        payload = command.model_dump(mode="json")
        validate_contract("catalog-assessment-page-list-request", payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_response(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("catalog-assessment-page-list-response", value)
            response = CatalogAssessmentPageListResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.pages is not None
            return response.pages
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog assessment page-list boundary is unavailable",
            ) from exc
        finally:
            connection.close()

    def download_assessment_page(
        self,
        extraction_batch_id: str,
        assessment_occurrence_revision_id: str,
        page_input_id: str,
    ) -> ProxiedItemMedia:
        command = AssessmentPageMediaQuery(
            extraction_batch_id=extraction_batch_id,
            assessment_occurrence_revision_id=assessment_occurrence_revision_id,
            page_input_id=page_input_id,
        )
        payload = command.model_dump(mode="json")
        validate_contract("catalog-assessment-page-media-request", payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
            connection.sendall(encoded + b"\n")
            connection.settimeout(RESPONSE_TIMEOUT_SECONDS)
            raw = self._read_media_header(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            validate_contract("catalog-assessment-page-media-response", value)
            response = CatalogAssessmentPageMediaResponse.model_validate(value)
            if response.status == "ERROR":
                self._raise_remote_error(response.error_code)
            assert response.media_type is not None
            assert response.content_length is not None
            assert response.sha256 is not None
            if response.content_length > CATALOG_ASSESSMENT_PAGE_MAX_BYTES:
                raise ValueError("Catalog assessment page exceeds its fixed bound")
            return ProxiedItemMedia(
                connection=connection,
                media_type=response.media_type,
                content_length=response.content_length,
                sha256=response.sha256,
            )
        except CatalogApplicationClientError:
            connection.close()
            raise
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            ValidationError,
            JsonSchemaValidationError,
        ) as exc:
            connection.close()
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog assessment page-media boundary is unavailable",
            ) from exc

    def create_knowledge_analysis(
        self, command: CreateKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def create_knowledge_solution_analysis(
        self, command: CreateKnowledgeSolutionAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def create_knowledge_analysis_batch(
        self, command: CreateKnowledgeAnalysisBatchCommand
    ) -> KnowledgeAnalysisBatchApplicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.analysis_batch is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog Knowledge Analysis batch response is invalid",
            )
        return response.analysis_batch

    def reconcile_knowledge_analysis(
        self, command: ReconcileKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def review_knowledge_analysis(
        self, command: ReviewKnowledgeAnalysisCommand
    ) -> KnowledgeAnalysisApplicationResult:
        return self._analysis_request(command)

    def create_evidence_bundle(
        self, command: CreateEvidenceBundleCommand
    ) -> (
        EvidenceBundlePublicationResult
        | EvidenceBundlePublicationResultV3
        | EvidenceBundlePublicationResultV4
    ):
        response = self._request(command)
        if response.operation != command.operation or response.evidence is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog Evidence Bundle response is invalid",
            )
        return response.evidence

    def create_item_production_evidence(
        self, command: CreateItemProductionEvidenceCommand
    ) -> (
        EvidenceBundlePublicationResultV2
        | EvidenceBundlePublicationResultV3
        | EvidenceBundlePublicationResultV4
    ):
        response = self._request(command)
        if response.operation != command.operation or response.item_production_evidence is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog item production Evidence Bundle response is invalid",
            )
        return response.item_production_evidence

    def publish_approved_item_analyses(
        self,
        command: PublishApprovedItemAnalysesCommand,
    ) -> ApprovedItemGraphPublicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.graph_publication is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog approved Item Graph publication response is invalid",
            )
        return response.graph_publication

    def publish_mock_exam_item_review(
        self,
        command: PublishMockExamItemReviewCommand,
    ) -> MockExamItemReviewPublicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.item_review is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog mock-exam Item review response is invalid",
            )
        return response.item_review

    def inspect_mock_exam_review_eligibility(
        self,
        query: InspectMockExamReviewEligibilityQuery,
    ) -> MockExamReviewEligibilityResult:
        response = self._request(query)
        if response.operation != query.operation or response.review_eligibility is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog mock-exam review eligibility response is invalid",
            )
        return response.review_eligibility

    def preview_mock_exam_assembly_plan(
        self,
        command: PreviewMockExamAssemblyPlanCommand,
    ) -> MockExamAssemblyPlanContract:
        response = self._request(command)
        if response.operation != command.operation or response.assembly_plan is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog mock-exam assembly plan response is invalid",
            )
        return response.assembly_plan

    def create_mock_exam_assembly(
        self,
        command: CreateMockExamAssemblyCommand,
    ) -> MockExamAssemblyManifestContract:
        return self._assembly_request(command)

    def create_planned_mock_exam_assembly(
        self,
        command: CreatePlannedMockExamAssemblyCommand,
    ) -> MockExamAssemblyManifestContract:
        return self._assembly_request(command)

    def inspect_mock_exam_assembly(
        self,
        query: InspectMockExamAssemblyQuery,
    ) -> MockExamAssemblyManifestContract:
        return self._assembly_request(query)

    def _assembly_request(
        self,
        command: (
            CreateMockExamAssemblyCommand
            | CreatePlannedMockExamAssemblyCommand
            | InspectMockExamAssemblyQuery
        ),
    ) -> MockExamAssemblyManifestContract:
        response = self._request(command)
        if response.operation != command.operation or response.assembly is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog mock-exam assembly response is invalid",
            )
        return response.assembly

    def _analysis_request(
        self,
        command: CreateKnowledgeAnalysisCommand
        | CreateKnowledgeSolutionAnalysisCommand
        | ReconcileKnowledgeAnalysisCommand
        | ReviewKnowledgeAnalysisCommand,
    ) -> KnowledgeAnalysisApplicationResult:
        response = self._request(command)
        if response.operation != command.operation or response.analysis is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog knowledge analysis response is invalid",
            )
        return response.analysis

    def _raw_request(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
                raise ValueError("Catalog application request exceeds its fixed bound")
            connection.sendall(encoded + b"\n")
            connection.settimeout(timeout_seconds)
            raw = self._read_response(connection)
            value: object = json.loads(raw)
            if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
                raise ValueError("Catalog application response is not an object")
            return value
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application boundary is unavailable",
            ) from exc
        finally:
            connection.close()

    def _request(
        self,
        command: ReviewedItemContentImportCommand
        | ItemContentQuery
        | CreateKnowledgeAnalysisCommand
        | CreateKnowledgeSolutionAnalysisCommand
        | ReconcileKnowledgeAnalysisCommand
        | ReviewKnowledgeAnalysisCommand
        | CreateKnowledgeAnalysisBatchCommand
        | CreateEvidenceBundleCommand
        | CreateItemProductionEvidenceCommand
        | PublishApprovedItemAnalysesCommand
        | PublishMockExamItemReviewCommand
        | InspectMockExamReviewEligibilityQuery
        | PreviewMockExamAssemblyPlanCommand
        | CreateMockExamAssemblyCommand
        | CreatePlannedMockExamAssemblyCommand
        | InspectMockExamAssemblyQuery,
    ) -> CatalogApplicationResponse:
        payload = CatalogApplicationRequest(root=command).model_dump(mode="json")
        content_schema_version = (
            command.content.schema_version
            if isinstance(command, ReviewedItemContentImportCommand)
            else None
        )
        request_schemas = catalog_application_schema_route(
            command.operation,
            content_schema_version=content_schema_version,
        )
        validate_contract(request_schemas.request_schema, payload)
        self._validate_socket()
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(str(self.socket_path))
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) + 1 > CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
                raise ValueError("Catalog application request exceeds its fixed bound")
            connection.sendall(encoded + b"\n")
            connection.settimeout(self._response_timeout_seconds(command))
            raw = self._read_response(connection)
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            response_content_schema_version: str | None = content_schema_version
            raw_content = value.get("content")
            if isinstance(raw_content, dict):
                raw_content_schema_version = raw_content.get("schema_version")
                if isinstance(raw_content_schema_version, str):
                    response_content_schema_version = raw_content_schema_version
            review_result_schema: str | None = None
            for field in ("item_review", "review_eligibility"):
                raw_review = value.get(field)
                if isinstance(raw_review, dict):
                    raw_review_result_schema = raw_review.get("review_result_schema")
                    if isinstance(raw_review_result_schema, str):
                        review_result_schema = raw_review_result_schema
                        break
            response_schemas = catalog_application_schema_route(
                command.operation,
                content_schema_version=response_content_schema_version,
                review_result_schema=review_result_schema,
            )
            validate_contract(response_schemas.response_schema, value)
            response = CatalogApplicationResponse.model_validate(value)
        except CatalogApplicationClientError:
            raise
        except (
            OSError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application boundary is unavailable",
            ) from exc
        finally:
            connection.close()
        if response.status == "ERROR":
            self._raise_remote_error(response.error_code)
        return response

    @staticmethod
    def _response_timeout_seconds(
        command: ReviewedItemContentImportCommand
        | ItemContentQuery
        | CreateKnowledgeAnalysisCommand
        | CreateKnowledgeSolutionAnalysisCommand
        | ReconcileKnowledgeAnalysisCommand
        | ReviewKnowledgeAnalysisCommand
        | CreateKnowledgeAnalysisBatchCommand
        | CreateEvidenceBundleCommand
        | CreateItemProductionEvidenceCommand
        | PublishApprovedItemAnalysesCommand
        | PublishMockExamItemReviewCommand
        | InspectMockExamReviewEligibilityQuery
        | PreviewMockExamAssemblyPlanCommand
        | CreateMockExamAssemblyCommand
        | CreatePlannedMockExamAssemblyCommand
        | InspectMockExamAssemblyQuery,
    ) -> float:
        if isinstance(command, (CreateEvidenceBundleCommand, CreateItemProductionEvidenceCommand)):
            return EVIDENCE_RESPONSE_TIMEOUT_SECONDS
        if isinstance(
            command,
            (
                PreviewMockExamAssemblyPlanCommand,
                CreateMockExamAssemblyCommand,
                CreatePlannedMockExamAssemblyCommand,
                InspectMockExamAssemblyQuery,
            ),
        ):
            return ASSEMBLY_RESPONSE_TIMEOUT_SECONDS
        return RESPONSE_TIMEOUT_SECONDS

    def _validate_socket(self) -> None:
        try:
            metadata = self.socket_path.lstat()
            expected_uid = (
                pwd.getpwnam("eom-catalog-manager").pw_uid
                if self.expected_uid is None
                else self.expected_uid
            )
        except (KeyError, OSError) as exc:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application socket is unavailable",
            ) from exc
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or self.socket_path.is_symlink()
            or metadata.st_uid != expected_uid
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != CATALOG_APPLICATION_SOCKET_MODE
        ):
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application socket metadata is invalid",
            )

    @staticmethod
    def _read_response(connection: socket.socket) -> bytes:
        value = bytearray()
        while len(value) <= CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
            chunk = connection.recv(
                min(64 * 1024, CATALOG_APPLICATION_MAX_MESSAGE_BYTES + 1 - len(value))
            )
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                value.extend(chunk[:newline])
                if newline != len(chunk) - 1:
                    raise ValueError("Catalog application response has trailing bytes")
                return bytes(value)
            value.extend(chunk)
        raise ValueError("Catalog application response is absent or exceeds its fixed bound")

    @staticmethod
    def _read_media_header(connection: socket.socket) -> bytes:
        value = bytearray()
        while len(value) <= CATALOG_APPLICATION_MAX_MESSAGE_BYTES:
            chunk = connection.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                return bytes(value)
            value.extend(chunk)
        raise ValueError("Catalog media header is absent or exceeds its fixed bound")

    @staticmethod
    def _raise_remote_error(error_code: str | None) -> None:
        if error_code is None:
            raise CatalogApplicationClientError(
                CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                "Catalog application response omitted its error code",
            )
        try:
            registry_code = RegistryErrorCode(error_code)
        except ValueError:
            try:
                catalog_code = CatalogApplicationErrorCode(error_code)
            except ValueError as exc:
                if error_code.startswith("KNOWLEDGE_ANALYSIS_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog knowledge analysis operation failed",
                    ) from None
                if error_code.startswith("KNOWLEDGE_RETRIEVAL_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog knowledge retrieval operation failed",
                    ) from None
                if error_code.startswith("KNOWLEDGE_GRAPH_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog knowledge Graph operation failed",
                    ) from None
                if error_code.startswith("APPROVED_ITEM_GRAPH_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog approved Item Graph publication failed",
                    ) from None
                if error_code.startswith("ITEM_REVIEW_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog mock-exam Item review publication failed",
                    ) from None
                if error_code.startswith("ASSEMBLY_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog mock-exam assembly operation failed",
                    ) from None
                if error_code.startswith("PDF_DOCUMENT_REVIEW_"):
                    raise CatalogApplicationClientError(
                        error_code,
                        "Catalog PDF document-review intake failed",
                    ) from None
                raise CatalogApplicationClientError(
                    CatalogApplicationErrorCode.CATALOG_APPLICATION_UNAVAILABLE,
                    "Catalog application returned an unknown error code",
                ) from exc
            raise CatalogApplicationClientError(
                catalog_code,
                "Catalog application operation failed",
            ) from None
        raise RegistryError(registry_code, "Catalog application operation failed")
