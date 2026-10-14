"""Application service composition and lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from eom_catalog_service.registry_service import RegistryService
from eom_hwpx_manager import (
    ExamHwpxApplicationService,
    HwpxApplicationService,
    HwpxCapabilityService,
)
from eom_identity_service.auth_service import AuthService, LoginPolicy
from eom_identity_service.service import OperatorService
from eom_identity_service.tokens import SessionTokenService, TokenCodec, TokenPolicy
from eom_orchestrator.database import build_engine
from eom_orchestrator.general_chat_client import GeneralChatOwnerClient
from fastapi import FastAPI
from sqlalchemy import Engine

from eom_api.rate_limit import BoundedRateLimiter
from eom_api.services.audit_service import AuditService
from eom_api.services.catalog_application_client import CatalogApplicationClient
from eom_api.services.chat_knowledge_query_adapter import ChatKnowledgeQueryAdapter
from eom_api.services.chat_knowledge_service import ChatKnowledgeApplicationService
from eom_api.services.command_adapter import CommandAdapter
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_api.services.document_review_annotation_service import (
    DocumentReviewAnnotationApplicationService,
)
from eom_api.services.document_review_correction_service import (
    DocumentReviewCorrectionApplicationService,
)
from eom_api.services.educational_quality_service import (
    EducationalQualityReviewApplicationService,
)
from eom_api.services.general_chat_service import GeneralChatApplicationService
from eom_api.services.hwpx_download_client import HwpxDownloadClient
from eom_api.services.hwpx_item_revision_resolver import (
    CatalogBackedHwpxItemRevisionResolver,
)
from eom_api.services.idempotency_service import IdempotencyService
from eom_api.services.inference_transfer_metadata import (
    InferenceTransferMetadataApplicationService,
)
from eom_api.services.inference_transfer_metadata_client import (
    CatalogInferenceTransferMetadataClient,
)
from eom_api.services.inference_transfer_retry import InferenceTransferRetryApplicationService
from eom_api.services.inference_transfer_retry_adapter import InferenceTransferRetryAdapter
from eom_api.services.inference_transfer_snapshot import InferenceTransferSnapshotApplicationService
from eom_api.services.inference_transfer_snapshot_client import (
    CatalogInferenceTransferSnapshotClient,
)
from eom_api.services.inference_transfer_start_adapter import InferenceTransferStartAdapter
from eom_api.services.inference_transfer_submission import (
    InferenceTransferSubmissionApplicationService,
)
from eom_api.services.inference_transfer_workflow_client import (
    CatalogInferenceTransferWorkflowClient,
)
from eom_api.services.inference_transfer_workflow_read import (
    InferenceTransferWorkflowReadApplicationService,
    InferenceTransferWorkflowReadApplicationServiceV11,
)
from eom_api.services.item_approval_service import ItemApprovalApplicationService
from eom_api.services.paired_document_review_service import (
    PairedDocumentReviewApplicationService,
)
from eom_api.services.pdf_document_review_service import PdfDocumentReviewApplicationService
from eom_api.services.pdf_upload_stager import PdfUploadStager
from eom_api.services.preset_model_selection_adapter import PresetModelSelectionAdapter
from eom_api.services.query_adapter import QueryAdapter
from eom_api.services.similarity_context_client import CatalogSimilarityContextClient
from eom_api.services.similarity_context_read import SimilarityContextReadApplicationService
from eom_api.settings import ApiSecrets, ApiSettings, load_secrets, load_settings


class AppServices:
    def __init__(self, settings: ApiSettings, secrets: ApiSecrets, engine: Engine) -> None:
        token_key = secrets.token_hash_key.get_secret_value().encode("utf-8")
        fingerprint_key = secrets.fingerprint_key.get_secret_value().encode("utf-8")
        self.settings = settings
        self.secrets = secrets
        self.engine = engine
        token_service = SessionTokenService(
            TokenCodec(token_key),
            TokenPolicy(
                access_seconds=settings.auth.access_token_seconds,
                refresh_seconds=settings.auth.refresh_token_seconds,
                session_absolute_seconds=settings.auth.session_absolute_seconds,
                session_idle_seconds=settings.auth.session_idle_seconds,
            ),
        )
        self.auth = AuthService(
            engine,
            token_service,
            login_policy=LoginPolicy(
                failure_limit=settings.auth.login_failure_limit,
                failure_window_seconds=settings.auth.login_failure_window_seconds,
                lock_seconds=settings.auth.lock_seconds,
            ),
        )
        self.operators = OperatorService(engine)
        self.catalog_application = CatalogApplicationClient()
        self.inference_transfer_metadata = InferenceTransferMetadataApplicationService(
            CatalogInferenceTransferMetadataClient()
        )
        self.similarity_context_reads = SimilarityContextReadApplicationService(
            CatalogSimilarityContextClient()
        )
        self.inference_transfer_snapshots = InferenceTransferSnapshotApplicationService(
            CatalogInferenceTransferSnapshotClient()
        )
        self.inference_transfer_submissions = InferenceTransferSubmissionApplicationService(
            self.inference_transfer_snapshots, InferenceTransferStartAdapter(engine)
        )
        self.inference_transfer_workflow_reads = InferenceTransferWorkflowReadApplicationService(
            CatalogInferenceTransferWorkflowClient()
        )
        self.inference_transfer_workflow_reads_v11 = (
            InferenceTransferWorkflowReadApplicationServiceV11(
                CatalogInferenceTransferWorkflowClient()
            )
        )
        self.inference_transfer_retries = InferenceTransferRetryApplicationService(
            self.inference_transfer_submissions,
            self.inference_transfer_workflow_reads_v11,
            InferenceTransferRetryAdapter(engine),
        )
        self.queries = QueryAdapter(
            engine,
            fingerprint_key,
            catalog_application=self.catalog_application,
        )
        self.registry = RegistryService(engine)
        self.commands = CommandAdapter(engine, catalog_application=self.catalog_application)
        self.pdf_review_upload_stager = PdfUploadStager(
            settings.pdf_document_review.upload_staging_root,
            maximum_bytes=settings.pdf_document_review.max_upload_bytes,
        )
        self.pdf_document_reviews = PdfDocumentReviewApplicationService(
            engine,
            catalog=self.catalog_application,
            commands=self.commands,
            intent_ttl_seconds=settings.pdf_document_review.intent_ttl_seconds,
            processing_lease_seconds=settings.pdf_document_review.processing_lease_seconds,
        )
        self.paired_document_reviews = PairedDocumentReviewApplicationService(
            engine,
            catalog=self.catalog_application,
            commands=self.commands,
            intent_ttl_seconds=settings.pdf_document_review.intent_ttl_seconds,
            processing_lease_seconds=settings.pdf_document_review.processing_lease_seconds,
        )
        self.document_review_corrections = DocumentReviewCorrectionApplicationService(
            engine,
            catalog=self.catalog_application,
            queries=self.queries,
        )
        self.document_review_annotations = DocumentReviewAnnotationApplicationService(
            engine,
            catalog=self.catalog_application,
            queries=self.queries,
        )
        self.control_plane = ControlPlaneAdapter(engine)
        self.preset_models = PresetModelSelectionAdapter(engine)
        self.idempotency = IdempotencyService(engine, token_key)
        self.audit = AuditService(engine)
        self.general_chat = GeneralChatApplicationService(GeneralChatOwnerClient())
        self.chat_knowledge = ChatKnowledgeApplicationService(
            ChatKnowledgeQueryAdapter(engine, self.queries.item_revision_views)
        )
        self.hwpx_item_revisions = CatalogBackedHwpxItemRevisionResolver(
            self.registry,
            self.catalog_application,
        )
        self.hwpx = HwpxApplicationService(engine, registry=self.hwpx_item_revisions)
        self.item_approvals = ItemApprovalApplicationService(
            hwpx=self.hwpx,
            catalog=self.catalog_application,
        )
        self.educational_quality_reviews = EducationalQualityReviewApplicationService(
            engine,
            catalog=self.catalog_application,
        )
        self.exam_hwpx = ExamHwpxApplicationService(engine, registry=self.registry)
        self.hwpx_downloads = HwpxDownloadClient()
        self.hwpx_capability = HwpxCapabilityService(manager_registered=True)
        self.rate_limiter = BoundedRateLimiter(settings.rate_limit.maximum_buckets)
        self.fingerprint_key = fingerprint_key


def build_services(
    settings: ApiSettings | None = None,
    secrets: ApiSecrets | None = None,
) -> AppServices:
    actual_settings = settings or load_settings()
    actual_secrets = secrets or load_secrets()
    engine = build_engine(actual_secrets.database_url.get_secret_value())
    return AppServices(actual_settings, actual_secrets, engine)


def lifespan_for(
    services: AppServices,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        services.engine.dispose()

    return lifespan
