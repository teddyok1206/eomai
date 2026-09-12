"""Private Unix-socket boundary for orchestrator-owned Catalog application operations."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import socketserver
import stat
import struct
from pathlib import Path
from typing import Any, Literal, cast

from eom_catalog_contracts import (
    CATALOG_APPLICATION_MAX_MESSAGE_BYTES,
    CATALOG_APPLICATION_RUNTIME_DIRECTORY_MODE,
    CATALOG_APPLICATION_SOCKET_MODE,
    CATALOG_APPLICATION_SOCKET_PATH,
    AssessmentPageListQuery,
    AssessmentPageMediaQuery,
    CatalogApplicationErrorCode,
    CatalogApplicationRequest,
    CatalogApplicationResponse,
    CatalogAssessmentPageListResponse,
    CatalogAssessmentPageMediaResponse,
    CatalogItemMediaResponse,
    CreateEvidenceBundleCommand,
    CreateItemProductionEvidenceCommand,
    CreateKnowledgeAnalysisBatchCommand,
    CreateKnowledgeAnalysisCommand,
    CreateKnowledgeSolutionAnalysisCommand,
    InspectMockExamReviewEligibilityQuery,
    ItemContentQuery,
    ItemMediaQuery,
    PublishApprovedItemAnalysesCommand,
    PublishMockExamItemReviewCommand,
    ReconcileKnowledgeAnalysisCommand,
    ReviewedItemContentImportCommand,
    ReviewedItemContentImportResult,
    ReviewKnowledgeAnalysisCommand,
    catalog_application_schema_route,
    validate_contract,
)
from eom_item_registry import RegistryError
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from eom_catalog_service.approved_item_graph_publication_service import (
    ApprovedItemGraphPublicationError,
    ApprovedItemGraphPublicationService,
)
from eom_catalog_service.errors import CatalogError
from eom_catalog_service.item_content_import import StructuredItemContentImportService
from eom_catalog_service.knowledge_analysis_batch_service import (
    KnowledgeAnalysisBatchService,
    KnowledgeAnalysisBatchServiceError,
)
from eom_catalog_service.knowledge_analysis_service import (
    KnowledgeAnalysisApplicationService,
    KnowledgeAnalysisServiceError,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.mock_exam_item_review_publication_service import (
    MockExamItemReviewPublicationError,
    MockExamItemReviewPublicationService,
)
from eom_catalog_service.registry_service import RegistryService

CATALOG_APPLICATION_SOCKET = Path(CATALOG_APPLICATION_SOCKET_PATH)
MAX_MESSAGE_BYTES = CATALOG_APPLICATION_MAX_MESSAGE_BYTES
SOCKET_MODE = CATALOG_APPLICATION_SOCKET_MODE
RUNTIME_DIRECTORY_MODE = CATALOG_APPLICATION_RUNTIME_DIRECTORY_MODE


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = True


class _CatalogApplicationHandler(socketserver.StreamRequestHandler):
    server: CatalogApplicationServer

    def handle(self) -> None:
        if not self.server.peer_is_allowed(self.request):
            return
        raw = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE_BYTES:
            self.server.write_error(
                self.wfile,
                "GET_ITEM_CONTENT",
                CatalogApplicationErrorCode.CATALOG_APPLICATION_REQUEST_INVALID.value,
            )
            return
        operation = "GET_ITEM_CONTENT"
        content_schema_version: str | None = None
        try:
            value: Any = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            raw_operation = value.get("operation")
            if raw_operation == "GET_ITEM_MEDIA":
                try:
                    validate_contract("catalog-item-media-request", value)
                    media_request = ItemMediaQuery.model_validate(value)
                except (JsonSchemaValidationError, ValidationError, ValueError):
                    self.server.write_media_error(
                        self.wfile,
                        CatalogApplicationErrorCode.CATALOG_APPLICATION_REQUEST_INVALID.value,
                    )
                    return
                self._stream_item_media(media_request)
                return
            if raw_operation == "GET_ASSESSMENT_PAGE_IMAGES":
                try:
                    validate_contract("catalog-assessment-page-list-request", value)
                    page_list_request = AssessmentPageListQuery.model_validate(value)
                except (JsonSchemaValidationError, ValidationError, ValueError):
                    self.server.write_assessment_page_list_error(
                        self.wfile,
                        CatalogApplicationErrorCode.CATALOG_APPLICATION_REQUEST_INVALID.value,
                    )
                    return
                self._write_assessment_pages(page_list_request)
                return
            if raw_operation == "GET_ASSESSMENT_PAGE_IMAGE":
                try:
                    validate_contract("catalog-assessment-page-media-request", value)
                    page_media_request = AssessmentPageMediaQuery.model_validate(value)
                except (JsonSchemaValidationError, ValidationError, ValueError):
                    self.server.write_assessment_page_media_error(
                        self.wfile,
                        CatalogApplicationErrorCode.CATALOG_APPLICATION_REQUEST_INVALID.value,
                    )
                    return
                self._stream_assessment_page(page_media_request)
                return
            if raw_operation in {
                "IMPORT_REVIEWED_ITEM_CONTENT",
                "GET_ITEM_CONTENT",
                "CREATE_KNOWLEDGE_ANALYSIS",
                "CREATE_KNOWLEDGE_SOLUTION_ANALYSIS",
                "CREATE_KNOWLEDGE_ANALYSIS_BATCH",
                "RECONCILE_KNOWLEDGE_ANALYSIS",
                "REVIEW_KNOWLEDGE_ANALYSIS",
                "CREATE_EVIDENCE_BUNDLE",
                "CREATE_ITEM_PRODUCTION_EVIDENCE",
                "PUBLISH_APPROVED_ITEM_ANALYSES",
                "PUBLISH_MOCK_EXAM_ITEM_REVIEW",
                "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY",
            }:
                operation = raw_operation
            if raw_operation == "IMPORT_REVIEWED_ITEM_CONTENT":
                raw_content = value.get("content")
                if isinstance(raw_content, dict):
                    raw_content_schema_version = raw_content.get("schema_version")
                    if isinstance(raw_content_schema_version, str):
                        content_schema_version = raw_content_schema_version
            schemas = catalog_application_schema_route(
                operation,
                content_schema_version=content_schema_version,
            )
            validate_contract(schemas.request_schema, value)
            request = CatalogApplicationRequest.model_validate(value).root
        except (
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
            JsonSchemaValidationError,
            ValidationError,
        ):
            self.server.write_error(
                self.wfile,
                operation,
                CatalogApplicationErrorCode.CATALOG_APPLICATION_REQUEST_INVALID.value,
                content_schema_version=content_schema_version,
            )
            return
        try:
            if isinstance(request, ReviewedItemContentImportCommand):
                imported = self.server.imports.import_reviewed(
                    request.base_revision_id,
                    request.content,
                    reviewed_by=request.reviewed_by,
                    review_reason=request.review_reason,
                    expected_version=request.expected_version,
                )
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    result=ReviewedItemContentImportResult(
                        item_id=imported.item_id,
                        item_revision_id=imported.item_revision_id,
                        resource_version=imported.resource_version,
                        content_artifact_id=imported.content_artifact_id,
                        content_artifact_revision_id=imported.content_artifact_revision_id,
                        content_sha256=imported.content_sha256,
                    ),
                )
            elif isinstance(request, ItemContentQuery):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    content=self.server.registry.load_item_content(request.item_revision_id),
                )
            elif isinstance(request, CreateKnowledgeAnalysisCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    analysis=self.server.knowledge_analysis.create(request),
                )
            elif isinstance(request, CreateKnowledgeSolutionAnalysisCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    analysis=self.server.knowledge_analysis.create_solution(request),
                )
            elif isinstance(request, ReconcileKnowledgeAnalysisCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    analysis=self.server.knowledge_analysis.reconcile(request),
                )
            elif isinstance(request, ReviewKnowledgeAnalysisCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    analysis=self.server.knowledge_analysis.review(request),
                )
            elif isinstance(request, CreateKnowledgeAnalysisBatchCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    analysis_batch=self.server.knowledge_analysis_batches.create(request),
                )
            elif isinstance(request, CreateEvidenceBundleCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    evidence=self.server.knowledge_retrieval.create(request),
                )
            elif isinstance(request, CreateItemProductionEvidenceCommand):
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    item_production_evidence=(
                        self.server.knowledge_retrieval.create_item_production(request)
                    ),
                )
            elif isinstance(request, PublishApprovedItemAnalysesCommand):
                if self.server.approved_item_graph_publication is None:
                    raise RuntimeError("approved Item Graph publication is unavailable")
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    graph_publication=self.server.approved_item_graph_publication.publish(request),
                )
            elif isinstance(request, PublishMockExamItemReviewCommand):
                if self.server.mock_exam_item_reviews is None:
                    raise RuntimeError("mock-exam Item review publication is unavailable")
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    item_review=self.server.mock_exam_item_reviews.publish(request),
                )
            elif isinstance(request, InspectMockExamReviewEligibilityQuery):
                if self.server.mock_exam_item_reviews is None:
                    raise RuntimeError("mock-exam review eligibility inspection is unavailable")
                response = CatalogApplicationResponse(
                    status="OK",
                    operation=request.operation,
                    review_eligibility=self.server.mock_exam_item_reviews.inspect_eligibility(
                        request
                    ),
                )
            else:  # pragma: no cover - discriminated contract makes this unreachable
                raise TypeError("unsupported catalog application request")
        except (
            CatalogError,
            RegistryError,
            KnowledgeAnalysisServiceError,
            KnowledgeAnalysisBatchServiceError,
            KnowledgeRetrievalServiceError,
            ApprovedItemGraphPublicationError,
            MockExamItemReviewPublicationError,
        ) as exc:
            code = getattr(exc.code, "value", str(exc.code))
            self.server.write_error(
                self.wfile,
                request.operation,
                code,
                content_schema_version=content_schema_version,
            )
            return
        except Exception:
            self.server.write_error(
                self.wfile,
                request.operation,
                CatalogApplicationErrorCode.CATALOG_APPLICATION_INTERNAL_ERROR.value,
                content_schema_version=content_schema_version,
            )
            return
        self.server.write_response(
            self.wfile,
            response,
            content_schema_version=content_schema_version,
        )

    def _stream_item_media(self, request: ItemMediaQuery) -> None:
        try:
            media = self.server.registry.load_item_media(
                request.item_revision_id,
                request.block_id,
            )
        except RegistryError as exc:
            self.server.write_media_error(self.wfile, exc.code.value)
            return
        except Exception:
            self.server.write_media_error(
                self.wfile,
                CatalogApplicationErrorCode.CATALOG_APPLICATION_INTERNAL_ERROR.value,
            )
            return
        self.server.write_media_header(
            self.wfile,
            CatalogItemMediaResponse(
                status="OK",
                media_type=media.media_type,
                content_length=media.content_length,
                sha256=media.sha256,
            ),
        )
        chunks = media.iter_chunks()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
        finally:
            chunks.close()

    def _write_assessment_pages(self, request: AssessmentPageListQuery) -> None:
        try:
            value = self.server.registry.assessment_pages(
                request.extraction_batch_id,
                request.assessment_occurrence_revision_id,
            )
            self.server.write_assessment_page_list_response(
                self.wfile,
                CatalogAssessmentPageListResponse(status="OK", pages=value.pages),
            )
        except RegistryError as exc:
            self.server.write_assessment_page_list_error(self.wfile, exc.code.value)
        except Exception:
            self.server.write_assessment_page_list_error(
                self.wfile,
                CatalogApplicationErrorCode.CATALOG_APPLICATION_INTERNAL_ERROR.value,
            )

    def _stream_assessment_page(self, request: AssessmentPageMediaQuery) -> None:
        try:
            media = self.server.registry.load_assessment_page_media(
                request.extraction_batch_id,
                request.assessment_occurrence_revision_id,
                request.page_input_id,
            )
        except RegistryError as exc:
            self.server.write_assessment_page_media_error(self.wfile, exc.code.value)
            return
        except Exception:
            self.server.write_assessment_page_media_error(
                self.wfile,
                CatalogApplicationErrorCode.CATALOG_APPLICATION_INTERNAL_ERROR.value,
            )
            return
        self.server.write_assessment_page_media_header(
            self.wfile,
            CatalogAssessmentPageMediaResponse(
                status="OK",
                media_type="image/png",
                content_length=media.content_length,
                sha256=media.sha256,
            ),
        )
        chunks = media.iter_chunks()
        try:
            for chunk in chunks:
                self.wfile.write(chunk)
        finally:
            chunks.close()


class CatalogApplicationServer(_ThreadingUnixServer):
    """Closed protocol; only the fixed Application API UID may connect."""

    def __init__(
        self,
        imports: StructuredItemContentImportService,
        registry: RegistryService,
        knowledge_analysis: KnowledgeAnalysisApplicationService,
        knowledge_analysis_batches: KnowledgeAnalysisBatchService,
        knowledge_retrieval: KnowledgeRetrievalApplicationService,
        *,
        approved_item_graph_publication: ApprovedItemGraphPublicationService | None = None,
        mock_exam_item_reviews: MockExamItemReviewPublicationService | None = None,
        socket_path: Path = CATALOG_APPLICATION_SOCKET,
        allowed_uid: int | None = None,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        self.imports = imports
        self.registry = registry
        self.knowledge_analysis = knowledge_analysis
        self.knowledge_analysis_batches = knowledge_analysis_batches
        self.knowledge_retrieval = knowledge_retrieval
        self.approved_item_graph_publication = approved_item_graph_publication
        self.mock_exam_item_reviews = mock_exam_item_reviews
        self.socket_path = socket_path
        self.allowed_uid = pwd.getpwnam("eom-api").pw_uid if allowed_uid is None else allowed_uid
        self.expected_uid = os.geteuid() if expected_uid is None else expected_uid
        self.expected_gid = grp.getgrnam("eom-api").gr_gid if expected_gid is None else expected_gid
        self._validate_runtime_directory()
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("Catalog application socket path is not fresh")
        super().__init__(str(socket_path), _CatalogApplicationHandler)
        socket_path.chmod(SOCKET_MODE)
        metadata = socket_path.lstat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != self.expected_uid
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != SOCKET_MODE
        ):
            self.server_close()
            raise RuntimeError("Catalog application socket metadata mismatch")

    def _validate_runtime_directory(self) -> None:
        parent = self.socket_path.parent
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or parent.is_symlink()
            or metadata.st_uid != self.expected_uid
            or metadata.st_gid != self.expected_gid
            or stat.S_IMODE(metadata.st_mode) != RUNTIME_DIRECTORY_MODE
        ):
            raise RuntimeError("Catalog application runtime directory contract mismatch")

    def peer_is_allowed(self, connection: socket.socket) -> bool:
        try:
            raw = connection.getsockopt(
                socket.SOL_SOCKET,
                socket.SO_PEERCRED,
                struct.calcsize("3i"),
            )
            if not isinstance(raw, bytes):
                return False
            _pid, uid, _gid = cast(tuple[int, int, int], struct.unpack("3i", raw))
        except (OSError, struct.error):
            return False
        return uid == self.allowed_uid

    def handle_error(self, _request: object, _client_address: object) -> None:
        return

    @staticmethod
    def write_response(
        stream: Any,
        response: CatalogApplicationResponse,
        *,
        content_schema_version: str | None = None,
        review_result_schema: str | None = None,
    ) -> None:
        # Remove only inactive top-level response variants. Nested nullable contract fields such as
        # a content-team inquiry must remain explicit for canonical JSON Schema validation.
        payload = {
            key: value
            for key, value in response.model_dump(mode="json").items()
            if value is not None
        }
        if response.content is not None:
            content_schema_version = response.content.schema_version
        if response.item_review is not None:
            review_result_schema = response.item_review.review_result_schema
        elif response.review_eligibility is not None:
            review_result_schema = response.review_eligibility.review_result_schema
        schemas = catalog_application_schema_route(
            response.operation,
            content_schema_version=content_schema_version,
            review_result_schema=review_result_schema,
        )
        validate_contract(schemas.response_schema, payload)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        raw = encoded.encode("utf-8")
        if len(raw) + 1 > MAX_MESSAGE_BYTES:
            raise RuntimeError("Catalog application response exceeded its fixed bound")
        stream.write(raw + b"\n")

    @staticmethod
    def write_assessment_page_list_response(
        stream: Any, response: CatalogAssessmentPageListResponse
    ) -> None:
        payload = {
            key: value
            for key, value in response.model_dump(mode="json").items()
            if value is not None
        }
        validate_contract("catalog-assessment-page-list-response", payload)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(raw) + 1 > MAX_MESSAGE_BYTES:
            raise RuntimeError("Catalog assessment page response exceeded its fixed bound")
        stream.write(raw + b"\n")

    @classmethod
    def write_assessment_page_list_error(cls, stream: Any, error_code: str) -> None:
        cls.write_assessment_page_list_response(
            stream,
            CatalogAssessmentPageListResponse(status="ERROR", error_code=error_code),
        )

    @staticmethod
    def write_assessment_page_media_header(
        stream: Any, response: CatalogAssessmentPageMediaResponse
    ) -> None:
        payload = {
            key: value
            for key, value in response.model_dump(mode="json").items()
            if value is not None
        }
        validate_contract("catalog-assessment-page-media-response", payload)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        if len(raw) + 1 > MAX_MESSAGE_BYTES:
            raise RuntimeError("Catalog assessment page media header exceeded its fixed bound")
        stream.write(raw + b"\n")

    @classmethod
    def write_assessment_page_media_error(cls, stream: Any, error_code: str) -> None:
        cls.write_assessment_page_media_header(
            stream,
            CatalogAssessmentPageMediaResponse(status="ERROR", error_code=error_code),
        )

    @classmethod
    def write_error(
        cls,
        stream: Any,
        operation: str,
        error_code: str,
        *,
        content_schema_version: str | None = None,
        review_result_schema: str | None = None,
    ) -> None:
        cls.write_response(
            stream,
            CatalogApplicationResponse(
                status="ERROR",
                operation=cast(
                    Literal[
                        "IMPORT_REVIEWED_ITEM_CONTENT",
                        "GET_ITEM_CONTENT",
                        "CREATE_KNOWLEDGE_ANALYSIS",
                        "CREATE_KNOWLEDGE_ANALYSIS_BATCH",
                        "RECONCILE_KNOWLEDGE_ANALYSIS",
                        "REVIEW_KNOWLEDGE_ANALYSIS",
                        "CREATE_EVIDENCE_BUNDLE",
                        "CREATE_ITEM_PRODUCTION_EVIDENCE",
                        "PUBLISH_APPROVED_ITEM_ANALYSES",
                        "PUBLISH_MOCK_EXAM_ITEM_REVIEW",
                        "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY",
                    ],
                    operation,
                ),
                error_code=error_code,
            ),
            content_schema_version=content_schema_version,
            review_result_schema=review_result_schema,
        )

    @staticmethod
    def write_media_header(stream: Any, value: CatalogItemMediaResponse) -> None:
        payload = value.model_dump(mode="json", exclude_none=True)
        validate_contract("catalog-item-media-response", payload)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
        if len(raw) + 1 > MAX_MESSAGE_BYTES:
            raise RuntimeError("Catalog media response header exceeded its fixed bound")
        stream.write(raw + b"\n")

    @classmethod
    def write_media_error(cls, stream: Any, error_code: str) -> None:
        cls.write_media_header(
            stream,
            CatalogItemMediaResponse(status="ERROR", error_code=error_code),
        )

    def server_close(self) -> None:
        super().server_close()
        try:
            metadata = self.socket_path.lstat()
        except OSError:
            return
        if (
            stat.S_ISSOCK(metadata.st_mode)
            and metadata.st_uid == self.expected_uid
            and metadata.st_gid == self.expected_gid
        ):
            self.socket_path.unlink()
