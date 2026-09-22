from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from eom_api.pdf_document_review_models import (
    DocumentReviewHwpxCorrectionRecord,
    PdfDocumentReviewUploadIntentRecord,
)
from eom_api.services.document_review_correction_service import (
    DocumentReviewCorrectionApplicationService,
)
from eom_catalog_contracts import OfficeDocumentReviewMemberPointer
from sqlalchemy import Table, create_engine, select

NOW = datetime(2026, 9, 22, 7, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
FINDING_ID = "reviewfinding_" + "3" * 32
RESULT_ARTIFACT_ID = "artifact_" + "4" * 32
RESULT_REVISION_ID = "rev_" + "5" * 32
RESULT_SHA = "sha256:" + "6" * 64
BASE_ARTIFACT_ID = "artifact_" + "7" * 32
BASE_REVISION_ID = "rev_" + "8" * 32
BASE_SHA = "sha256:" + "9" * 64
OUTPUT_ARTIFACT_ID = "artifact_" + "a" * 32
OUTPUT_REVISION_ID = "rev_" + "b" * 32
OUTPUT_SHA = "sha256:" + "c" * 64
CORRECTION_ID = "doccorrection_" + "d" * 32


class _Queries:
    def pdf_document_review(self, **values: Any) -> Any:
        assert values == {"actor_id": OPERATOR_ID, "workflow_id": WORKFLOW_ID}
        return SimpleNamespace(
            state="COMPLETED",
            result=SimpleNamespace(
                findings=(
                    SimpleNamespace(
                        finding_id=FINDING_ID,
                        recommendation=SimpleNamespace(
                            operation="REPLACE",
                            before_text="수정 전",
                            after_text="수정 후",
                        ),
                    ),
                )
            ),
            result_artifact=SimpleNamespace(
                artifact_id=RESULT_ARTIFACT_ID,
                artifact_revision_id=RESULT_REVISION_ID,
                sha256=RESULT_SHA,
            ),
        )

    def pdf_document_review_result_pointer(self, **values: Any) -> Any:
        assert values == {"actor_id": OPERATOR_ID, "workflow_id": WORKFLOW_ID}
        from eom_catalog_contracts import PdfDocumentReviewResultMemberPointer

        return PdfDocumentReviewResultMemberPointer(
            artifact_id=RESULT_ARTIFACT_ID,
            artifact_revision_id=RESULT_REVISION_ID,
            sha256=RESULT_SHA,
            content_length=2048,
        )


class _Catalog:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    def apply_document_review_hwpx_corrections(self, command: Any) -> Any:
        self.commands.append(command)
        output = OfficeDocumentReviewMemberPointer(
            artifact_id=OUTPUT_ARTIFACT_ID,
            artifact_revision_id=OUTPUT_REVISION_ID,
            member_path="corrected/document-review-redline.hwpx",
            sha256=OUTPUT_SHA,
            content_length=8192,
            media_type="application/vnd.hancom.hwpx",
            schema_ref="eom://schemas/document-review/corrected-hwpx/1.0",
        )
        return SimpleNamespace(
            output=output,
            result=SimpleNamespace(
                correction_id=CORRECTION_ID,
                applied_finding_ids=(FINDING_ID,),
            ),
        )

    def download_document_review_corrected_hwpx(self, query: Any) -> Any:
        assert query.correction_id == CORRECTION_ID
        return SimpleNamespace(
            sha256=OUTPUT_SHA,
            content_length=8192,
            iter_chunks=lambda: iter((b"corrected",)),
        )


def _service() -> tuple[DocumentReviewCorrectionApplicationService, Any, _Catalog]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, PdfDocumentReviewUploadIntentRecord.__table__).create(engine)
    cast(Table, DocumentReviewHwpxCorrectionRecord.__table__).create(engine)
    upload = PdfDocumentReviewUploadIntentRecord(
        upload_intent_id="pdfreviewintent_" + "e" * 32,
        operator_id=OPERATOR_ID,
        state="STARTED",
        original_filename="검토 원고.hwpx",
        source_format="HWPX",
        source_media_type="application/vnd.hancom.hwpx",
        content_length=4096,
        preset_key="MOCK_EXAM",
        upload_sha256=BASE_SHA,
        workflow_id=WORKFLOW_ID,
        workflow_command_id="wfcmd_" + "f" * 32,
        document_id="document_" + "0" * 32,
        document_revision_id="documentrev_" + "1" * 32,
        source_artifact_id=BASE_ARTIFACT_ID,
        source_artifact_revision_id=BASE_REVISION_ID,
        source_sha256="sha256:" + "2" * 64,
        page_count=1,
        attempts=1,
        lock_version=3,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    with engine.begin() as connection:
        connection.execute(PdfDocumentReviewUploadIntentRecord.__table__.insert(), upload.__dict__)
    catalog = _Catalog()
    return (
        DocumentReviewCorrectionApplicationService(
            engine,
            catalog=cast(Any, catalog),
            queries=cast(Any, _Queries()),
        ),
        engine,
        catalog,
    )


def test_hwpx_correction_application_is_owned_idempotent_and_downloadable() -> None:
    service, engine, catalog = _service()
    eligibility = service.eligibility(WORKFLOW_ID, actor_id=OPERATOR_ID)
    assert eligibility.correction_available
    assert eligibility.eligible_finding_ids == (FINDING_ID,)

    first = service.apply(
        WORKFLOW_ID,
        actor_id=OPERATOR_ID,
        finding_ids=(FINDING_ID,),
        idempotency_key="api:document-review-correction-test",
    )
    replay = service.apply(
        WORKFLOW_ID,
        actor_id=OPERATOR_ID,
        finding_ids=(FINDING_ID,),
        idempotency_key="api:document-review-correction-test",
    )
    assert first == replay
    assert first.correction_id == CORRECTION_ID
    assert first.text_color == "#FF0000"
    assert len(catalog.commands) == 2
    with service.sessions() as session:
        records = tuple(session.scalars(select(DocumentReviewHwpxCorrectionRecord)))
        assert len(records) == 1
        assert records[0].output_sha256 == OUTPUT_SHA
        assert records[0].applied_finding_ids == [FINDING_ID]
    assert (
        service.correction(
            WORKFLOW_ID,
            CORRECTION_ID,
            actor_id=OPERATOR_ID,
        )
        == first
    )
    assert (
        service.download(
            WORKFLOW_ID,
            CORRECTION_ID,
            actor_id=OPERATOR_ID,
        ).sha256
        == OUTPUT_SHA
    )
    engine.dispose()


def test_non_hwpx_source_is_review_only() -> None:
    service, engine, _catalog = _service()
    with service.sessions.begin() as session:
        upload = session.scalar(select(PdfDocumentReviewUploadIntentRecord))
        assert upload is not None
        upload.source_format = "HWP"
        upload.source_media_type = "application/vnd.hancom.hwp"
    eligibility = service.eligibility(WORKFLOW_ID, actor_id=OPERATOR_ID)
    assert not eligibility.correction_available
    assert eligibility.unavailable_reason == "SOURCE_NOT_HWPX"
    engine.dispose()
