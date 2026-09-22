from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.pdf_document_review_models import PdfDocumentReviewUploadIntentRecord
from eom_api.services.catalog_application_client import CatalogApplicationClientError
from eom_api.services.pdf_document_review_service import (
    PdfDocumentReviewApplicationService,
    PdfReviewUploadClaim,
)
from eom_api.services.pdf_upload_stager import StagedPdfUpload
from eom_api_contracts.document_review import (
    CreateDocumentReviewUploadIntentRequestV2,
    CreatePdfDocumentReviewUploadIntentRequest,
)
from eom_catalog_contracts import (
    OfficeDocumentReviewConversionIdentity,
    OfficeDocumentReviewMemberPointer,
    OfficeDocumentReviewSourcePointer,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_identity_service import models as identity_models  # noqa: F401
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import ActorContext, ActorSource, ActorType, PermissionKey
from eom_orchestrator.database import build_engine, build_session_factory, transaction
from eom_workflow_runner import models as workflow_models  # noqa: F401
from sqlalchemy import Table, create_engine, select

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

    def ingest_office_document_review_source(self, source: Path, **values: Any) -> Any:
        self.calls.append({"source": source, **values})
        if self.failure is not None:
            failure = self.failure
            self.failure = None
            raise failure
        document = _document()
        source_format = values["source_format"]
        source_suffix = {"PDF": "pdf", "HWP": "hwp", "HWPX": "hwpx"}[source_format]
        source_media_type = values["media_type"]
        source_schema = {
            "PDF": "eom://schemas/document-review/pdf-source/1.0",
            "HWP": "eom://schemas/document-review/hwp-source/2.0",
            "HWPX": "eom://schemas/document-review/editable-hwpx/1.0",
        }[source_format]
        source_sha256 = (
            document.source_pdf.sha256
            if source_format == "PDF"
            else "sha256:" + __import__("hashlib").sha256(source.read_bytes()).hexdigest()
        )
        original_artifact_id = (
            document.source_pdf.artifact_id if source_format == "PDF" else "artifact_" + "e" * 32
        )
        original_revision_id = (
            document.source_pdf.artifact_revision_id
            if source_format == "PDF"
            else "rev_" + "f" * 32
        )
        if source_format != "PDF":
            source_pdf = document.source_pdf.model_copy(
                update={
                    "artifact_id": original_artifact_id,
                    "artifact_revision_id": original_revision_id,
                    "member_path": "source/original.pdf",
                }
            )
            pages = tuple(
                page.model_copy(
                    update={
                        "page_image": page.page_image.model_copy(
                            update={
                                "artifact_id": original_artifact_id,
                                "artifact_revision_id": original_revision_id,
                            }
                        )
                    }
                )
                for page in document.pages
            )
            document = document.model_copy(update={"source_pdf": source_pdf, "pages": pages})
        original = OfficeDocumentReviewMemberPointer(
            artifact_id=original_artifact_id,
            artifact_revision_id=original_revision_id,
            member_path=f"source/original.{source_suffix}",
            sha256=source_sha256,
            content_length=source.stat().st_size,
            media_type=source_media_type,
            schema_ref=source_schema,
        )
        manifest = OfficeDocumentReviewMemberPointer(
            artifact_id=original.artifact_id,
            artifact_revision_id=original.artifact_revision_id,
            member_path="manifest.json",
            sha256="sha256:" + "d" * 64,
            content_length=1024,
            media_type="application/json",
            schema_ref=("eom://schemas/document-review/document-review-intake-manifest/2.0"),
        )
        return OfficeDocumentReviewSourcePointer(
            document_id=document.document_id,
            document_revision_id=document.document_revision_id,
            original_filename=values["original_filename"],
            source_format=source_format,
            original_source=original,
            review_document=document,
            editable_hwpx=original if source_format == "HWPX" else None,
            intake_manifest=manifest,
            conversion=OfficeDocumentReviewConversionIdentity(
                conversion_kind=(
                    "IDENTITY_PDF" if source_format == "PDF" else "LIBREOFFICE_H2ORESTART_PDF"
                ),
                review_pdf_sha256=document.source_pdf.sha256,
                libreoffice_version=None if source_format == "PDF" else "LibreOffice 24.2.7.2",
                libreoffice_sha256=None if source_format == "PDF" else "sha256:" + "a" * 64,
                h2orestart_sha256=None if source_format == "PDF" else "sha256:" + "b" * 64,
            ),
        )


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
    cast(Table, PdfDocumentReviewUploadIntentRecord.__table__).create(engine)
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


def test_hwpx_review_pins_original_source_separately_from_derived_review_pdf(
    tmp_path: Path,
) -> None:
    service, engine, _catalog, _commands = _service()
    source = tmp_path / "upload.hwpx"
    source.write_bytes(b"PK\x03\x04HWPX")
    source_sha256 = "sha256:" + __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    intent = service.create_document_upload_intent(
        CreateDocumentReviewUploadIntentRequestV2(
            original_filename="문제지.hwpx",
            source_format="HWPX",
            media_type="application/vnd.hancom.hwpx",
            content_length=8,
            preset_key="PROBLEM_SET",
        ),
        actor_id=OPERATOR_ID,
        observed_at=NOW,
    )

    _, started = service.accept_document_upload(
        intent.upload_intent_id,
        StagedPdfUpload(
            source,
            8,
            source_sha256,
            source_format="HWPX",
            media_type="application/vnd.hancom.hwpx",
        ),
        actor=_actor(),
        observed_at=NOW + timedelta(seconds=1),
    )

    assert started.state == "STARTED"
    with service.sessions() as session:
        record = session.get(PdfDocumentReviewUploadIntentRecord, intent.upload_intent_id)
        assert record is not None
        assert record.source_artifact_id == "artifact_" + "e" * 32
        assert record.source_artifact_revision_id == "rev_" + "f" * 32
        assert record.source_sha256 == source_sha256
        assert record.source_sha256 != _document().source_pdf.sha256
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


@pytest.mark.integration
@pytest.mark.api_integration
def test_pdf_review_upload_claim_is_serialized_by_postgresql(tmp_path: Path) -> None:
    if os.environ.get("EOM_RUN_API_INTEGRATION") != "1":
        pytest.skip("run through the guarded disposable PostgreSQL database")
    engine = build_engine(os.environ["EOM_DATABASE_URL"])
    sessions = build_session_factory(engine)
    actor_id = "operator_" + uuid4().hex
    username = "pdf-review-" + uuid4().hex
    with transaction(sessions) as session:
        session.add(
            OperatorRecord(
                operator_id=actor_id,
                username=username,
                normalized_username=username,
                display_name="PDF Review Integration",
                status="ACTIVE",
                must_change_password=False,
                role_version=1,
                created_at=NOW,
                created_by="pdf-review-integration",
                updated_at=NOW,
                lock_version=1,
            )
        )
    service = PdfDocumentReviewApplicationService(
        engine,
        catalog=FakeCatalog(),  # type: ignore[arg-type]
        commands=FakeCommands(),  # type: ignore[arg-type]
        intent_ttl_seconds=86_400,
        processing_lease_seconds=300,
    )
    intent = service.create_upload_intent(
        CreatePdfDocumentReviewUploadIntentRequest(
            original_filename="문제지.pdf",
            content_length=8,
            preset_key="PROBLEM_SET",
            additional_guidance=None,
        ),
        actor_id=actor_id,
        observed_at=NOW,
    )
    source = tmp_path / "upload.pdf"
    source.write_bytes(b"%PDF-1.7")
    upload = StagedPdfUpload(source, 8, "sha256:" + "c" * 64)
    barrier = Barrier(2)

    def claim() -> PdfReviewUploadClaim | ApiError:
        barrier.wait(timeout=5)
        try:
            return service._claim_upload(
                intent.upload_intent_id,
                upload,
                actor_id=actor_id,
                observed_at=NOW + timedelta(seconds=1),
            )
        except ApiError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(lambda _index: claim(), range(2)))
        owned = tuple(value for value in outcomes if isinstance(value, PdfReviewUploadClaim))
        rejected = tuple(value for value in outcomes if isinstance(value, ApiError))
        assert len(owned) == len(rejected) == 1
        assert rejected[0].error_code == "PDF_DOCUMENT_REVIEW_UPLOAD_IN_PROGRESS"

        takeover = service._claim_upload(
            intent.upload_intent_id,
            upload,
            actor_id=actor_id,
            observed_at=NOW + timedelta(seconds=302),
        )
        assert takeover.lease_owner is not None
        assert takeover.lease_owner != owned[0].lease_owner
        service._fail_claim(
            owned[0],
            error_code="STALE_FAILURE",
            retryable=False,
            document=None,
        )
        service._fail_claim(
            takeover,
            error_code="CURRENT_FAILURE",
            retryable=True,
            document=None,
        )
        view = service.upload_intent(intent.upload_intent_id, actor_id=actor_id)
        assert view.state == "FAILED_RETRYABLE"
        assert view.failure_code == "CURRENT_FAILURE"
    finally:
        engine.dispose()
