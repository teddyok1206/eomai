from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_api.services.pdf_document_review_service import PdfDocumentReviewApplicationService
from eom_api.services.pdf_upload_stager import StagedPdfUpload
from eom_api_contracts.document_review import CreatePdfDocumentReviewUploadIntentRequest
from eom_catalog_contracts import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_identity_service import models as identity_models  # noqa: F401
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_workflow_runner import models as workflow_models  # noqa: F401
from sqlalchemy import create_engine, select

NOW = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
ZERO_SHA = "sha256:" + "0" * 64


def _document() -> PdfReviewDocumentPointer:
    source = PdfReviewArtifactMemberPointer(
        artifact_id="artifact_" + "2" * 32,
        artifact_revision_id="rev_" + "3" * 32,
        member_path="source/original.pdf",
        sha256="sha256:" + "c" * 64,
        schema_ref="eom://schemas/document-review/pdf-source/1.0",
        media_type="application/pdf",
        content_length=8,
    )
    page = PdfReviewArtifactMemberPointer(
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        member_path="pages/page-0001.png",
        sha256="sha256:" + "5" * 64,
        schema_ref="eom://schemas/document-review/pdf-page-render/1.0",
        media_type="image/png",
        content_length=1024,
    )
    return PdfReviewDocumentPointer(
        document_id="document_" + "6" * 32,
        document_revision_id="documentrev_" + "7" * 32,
        original_filename="문제지.pdf",
        source_pdf=source,
        page_count=1,
        pages=(
            PdfReviewPagePointer(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                page_image=page,
                text_layer=None,
            ),
        ),
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failure: CatalogApplicationClientError | None = None

    def ingest_pdf_document_review_source(self, source: Path, **values: Any) -> Any:
        self.calls.append({"source": source, **values})
        if self.failure is not None:
            failure = self.failure
            self.failure = None
            raise failure
        return _document()


class FakeCommands:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_pdf_document_review(self, request: object, actor: object, **values: Any) -> Any:
        self.calls.append({"request": request, "actor": actor, **values})
        return "wfcmd_" + "8" * 32, "workflow_" + "9" * 32, 1


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "a" * 32,
        request_id="req_" + "b" * 32,
        authentication_time=NOW,
        permissions=frozenset({PermissionKey.WORKFLOW_START}),
        source=ActorSource.APPLICATION_API,
    )


def _service() -> tuple[PdfDocumentReviewApplicationService, Any, FakeCatalog, FakeCommands]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PdfDocumentReviewUploadIntentRecord.__table__.create(engine)
    catalog = FakeCatalog()
    commands = FakeCommands()
    service = PdfDocumentReviewApplicationService(
        engine,
        catalog=catalog,  # type: ignore[arg-type]
        commands=commands,  # type: ignore[arg-type]
        intent_ttl_seconds=86_400,
        processing_lease_seconds=300,
    )
    return service, engine, catalog, commands


def _create(service: PdfDocumentReviewApplicationService) -> str:
    view = service.create_upload_intent(
        CreatePdfDocumentReviewUploadIntentRequest(
            original_filename="문제지.pdf",
            content_length=8,
            preset_key="PROBLEM_SET",
            additional_guidance="시각 자료와 해설의 일치를 우선 확인해 주세요.",
        ),
        actor_id=OPERATOR_ID,
        observed_at=NOW,
    )
    return view.upload_intent_id


def test_pdf_review_upload_service_starts_once_and_replays_exact_identity(tmp_path: Path) -> None:
    service, engine, catalog, commands = _service()
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"%PDF-1.7")
    upload = StagedPdfUpload(source, 8, "sha256:" + "c" * 64)
    intent_id = _create(service)

    command_id, started = service.accept_upload(
        intent_id,
        upload,
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=1),
    )
    replay_command_id, replay = service.accept_upload(
        intent_id,
        upload,
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=2),
    )

    assert command_id == replay_command_id == "wfcmd_" + "8" * 32
    assert started == replay
    assert started.state == "STARTED"
    assert started.workflow_id == "workflow_" + "9" * 32
    assert len(catalog.calls) == len(commands.calls) == 1
    with service.sessions() as session:
        record = session.scalar(
            select(PdfDocumentReviewUploadIntentRecord).where(
                PdfDocumentReviewUploadIntentRecord.upload_intent_id == intent_id
            )
        )
        assert record is not None
        assert record.document_revision_id == "documentrev_" + "7" * 32
        assert record.source_artifact_revision_id == "rev_" + "3" * 32
        assert record.workflow_command_id == command_id
    engine.dispose()


def test_pdf_review_upload_service_retries_transient_catalog_failure(tmp_path: Path) -> None:
    service, engine, catalog, commands = _service()
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"%PDF-1.7")
    upload = StagedPdfUpload(source, 8, "sha256:" + "c" * 64)
    intent_id = _create(service)
    catalog.failure = CatalogApplicationClientError(
        "CATALOG_APPLICATION_UNAVAILABLE",
        "temporary test failure",
    )

    with pytest.raises(ApiError) as failed:
        service.accept_upload(
            intent_id,
            upload,
            actor=_actor(),
            observed_at=NOW + timedelta(seconds=1),
        )
    assert failed.value.status == 503
    assert service.upload_intent(intent_id, actor_id=OPERATOR_ID).state == "FAILED_RETRYABLE"

    _, started = service.accept_upload(
        intent_id,
        upload,
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=2),
    )
    assert started.state == "STARTED"
    assert len(catalog.calls) == 2
    assert len(commands.calls) == 1
    engine.dispose()


def test_pdf_review_upload_claim_takeover_fences_stale_owner(tmp_path: Path) -> None:
    service, engine, _catalog, _commands = _service()
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"%PDF-1.7")
    upload = StagedPdfUpload(source, 8, "sha256:" + "c" * 64)
    intent_id = _create(service)

    first = service._claim_upload(
        intent_id,
        upload,
        actor_id=OPERATOR_ID,
        observed_at=NOW,
    )
    with pytest.raises(ApiError) as in_progress:
        service._claim_upload(
            intent_id,
            upload,
            actor_id=OPERATOR_ID,
            observed_at=NOW + timedelta(seconds=299),
        )
    assert in_progress.value.error_code == "PDF_DOCUMENT_REVIEW_UPLOAD_IN_PROGRESS"

    second = service._claim_upload(
        intent_id,
        upload,
        actor_id=OPERATOR_ID,
        observed_at=NOW + timedelta(seconds=301),
    )
    assert first.lease_owner != second.lease_owner
    service._fail_claim(
        first,
        error_code="STALE_FAILURE",
        retryable=False,
        document=None,
    )
    service._fail_claim(
        second,
        error_code="CURRENT_FAILURE",
        retryable=True,
        document=None,
    )
    view = service.upload_intent(intent_id, actor_id=OPERATOR_ID)
    assert view.state == "FAILED_RETRYABLE"
    assert view.failure_code == "CURRENT_FAILURE"
    engine.dispose()


def test_pdf_review_upload_rejects_different_bytes_after_first_claim(tmp_path: Path) -> None:
    service, engine, catalog, _commands = _service()
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"%PDF-1.7")
    intent_id = _create(service)
    catalog.failure = CatalogApplicationClientError(
        "CATALOG_APPLICATION_UNAVAILABLE",
        "temporary test failure",
    )
    with pytest.raises(ApiError):
        service.accept_upload(
            intent_id,
            StagedPdfUpload(source, 8, "sha256:" + "c" * 64),
            actor=_actor(),
            observed_at=NOW,
        )
    with pytest.raises(ApiError) as mismatch:
        service.accept_upload(
            intent_id,
            StagedPdfUpload(source, 8, ZERO_SHA),
            actor=_actor(),
            observed_at=NOW + timedelta(seconds=1),
        )
    assert mismatch.value.error_code == "PDF_DOCUMENT_REVIEW_UPLOAD_HASH_MISMATCH"
    engine.dispose()
