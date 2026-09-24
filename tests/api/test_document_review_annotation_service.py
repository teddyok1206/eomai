from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from eom_api.pdf_document_review_models import (
    DocumentReviewPdfAnnotationOutputRecord,
    DocumentReviewPdfAnnotationRecord,
)
from eom_api.runtime_privileges import UPDATE_TABLES
from eom_api.services.document_review_annotation_service import (
    DocumentReviewAnnotationApplicationService,
)
from eom_catalog_contracts import (
    DocumentReviewAnnotatedPdfPointer,
    DocumentReviewResultMemberPointer,
    OfficeDocumentReviewMemberPointer,
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_identifiers import content_sha256
from eom_workflow import PdfDocumentReviewRoleResult
from sqlalchemy import Table, create_engine, select

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
ANNOTATION_ID = "docannotation_" + "3" * 32
RESULT_ARTIFACT_ID = "artifact_" + "4" * 32
RESULT_REVISION_ID = "rev_" + "5" * 32
RESULT_SHA = "sha256:" + "6" * 64
SOURCE_ARTIFACT_ID = "artifact_" + "7" * 32
SOURCE_REVISION_ID = "rev_" + "8" * 32
SOURCE_SHA = "sha256:" + "9" * 64
PAGE_SHA = "sha256:" + "a" * 64
OUTPUT_ARTIFACT_ID = "artifact_" + "b" * 32
OUTPUT_REVISION_ID = "rev_" + "c" * 32
OUTPUT_SHA = "sha256:" + "d" * 64


def _source_member(path: str, media_type: str, schema_ref: str, sha256: str) -> Any:
    return PdfReviewArtifactMemberPointer(
        artifact_id=SOURCE_ARTIFACT_ID,
        artifact_revision_id=SOURCE_REVISION_ID,
        member_path=path,
        sha256=sha256,
        schema_ref=schema_ref,
        media_type=media_type,
        content_length=4096,
    )


def _source() -> PdfReviewDocumentPointer:
    return PdfReviewDocumentPointer(
        document_id="document_" + "e" * 32,
        document_revision_id="documentrev_" + "f" * 32,
        original_filename="검토.pdf",
        source_pdf=_source_member(
            "source/original.pdf",
            "application/pdf",
            "eom://schemas/document-review/pdf-source/1.0",
            SOURCE_SHA,
        ),
        page_count=1,
        pages=(
            PdfReviewPagePointer(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                page_image=_source_member(
                    "pages/page-0001.png",
                    "image/png",
                    "eom://schemas/document-review/pdf-page-render/1.0",
                    PAGE_SHA,
                ),
                text_layer=None,
            ),
        ),
    )


def _result() -> PdfDocumentReviewRoleResult:
    anchor = SimpleNamespace(
        anchor_id="reviewanchor_" + "1" * 32,
        page_number=1,
        page_image_sha256=PAGE_SHA,
        region=SimpleNamespace(
            model_dump=lambda **_: {
                "x_ppm": 100_000,
                "y_ppm": 200_000,
                "width_ppm": 300_000,
                "height_ppm": 100_000,
            }
        ),
    )
    finding = SimpleNamespace(
        finding_id="reviewfinding_" + "2" * 32,
        ordinal=1,
        anchors=(anchor,),
    )
    artifact = SimpleNamespace(
        logical_artifact_id=RESULT_ARTIFACT_ID,
        revision_id=RESULT_REVISION_ID,
    )
    return PdfDocumentReviewRoleResult.model_construct(
        workflow_id=WORKFLOW_ID,
        artifact=artifact,
        output=SimpleNamespace(findings=(finding,)),
    )


class _Queries:
    def document_review_annotation_inputs(self, **values: Any) -> Any:
        assert values == {"actor_id": OPERATOR_ID, "workflow_id": WORKFLOW_ID}
        return (
            DocumentReviewResultMemberPointer(
                artifact_id=RESULT_ARTIFACT_ID,
                artifact_revision_id=RESULT_REVISION_ID,
                sha256=RESULT_SHA,
                content_length=2048,
                schema_ref=(
                    "https://eom.local/schemas/workflow/roles/"
                    "pdf-document-review-result-v1.schema.json"
                ),
            ),
            (("DOCUMENT", _source()),),
            _result(),
        )


class _Catalog:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    def create_document_review_annotated_pdfs(self, command: Any) -> Any:
        self.commands.append(command)
        output = DocumentReviewAnnotatedPdfPointer(
            artifact_id=OUTPUT_ARTIFACT_ID,
            artifact_revision_id=OUTPUT_REVISION_ID,
            document_role="DOCUMENT",
            member_path="annotated/document.pdf",
            sha256=OUTPUT_SHA,
            content_length=8192,
        )
        manifest = OfficeDocumentReviewMemberPointer(
            artifact_id=OUTPUT_ARTIFACT_ID,
            artifact_revision_id=OUTPUT_REVISION_ID,
            member_path="manifest.json",
            sha256="sha256:" + "e" * 64,
            content_length=4096,
            media_type="application/json",
            schema_ref=(
                "eom://schemas/document-review/document-review-pdf-annotation-manifest/1.0"
            ),
        )
        return SimpleNamespace(
            outputs=(output,),
            manifest=manifest,
            result=SimpleNamespace(
                annotation_id=ANNOTATION_ID,
                manifest_sha256="sha256:" + "f" * 64,
            ),
        )

    def download_document_review_annotated_pdf(self, query: Any) -> Any:
        assert query.annotation_id == ANNOTATION_ID
        assert query.document_role == "DOCUMENT"
        return SimpleNamespace(
            sha256=OUTPUT_SHA,
            content_length=8192,
            iter_chunks=lambda: iter((b"annotated",)),
        )


def _service() -> tuple[DocumentReviewAnnotationApplicationService, Any, _Catalog]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, DocumentReviewPdfAnnotationRecord.__table__).create(engine)
    cast(Table, DocumentReviewPdfAnnotationOutputRecord.__table__).create(engine)
    catalog = _Catalog()
    return (
        DocumentReviewAnnotationApplicationService(
            engine,
            catalog=cast(Any, catalog),
            queries=cast(Any, _Queries()),
        ),
        engine,
        catalog,
    )


def test_document_review_annotation_is_pointer_only_idempotent_and_downloadable() -> None:
    service, engine, catalog = _service()
    first = service.create(
        WORKFLOW_ID,
        actor_id=OPERATOR_ID,
        idempotency_key="api:document-review-annotation-test",
    )
    replay = service.create(
        WORKFLOW_ID,
        actor_id=OPERATOR_ID,
        idempotency_key="api:document-review-annotation-replay",
    )
    assert first == replay
    assert first.annotation_id == ANNOTATION_ID
    assert len(catalog.commands) == 1
    command = catalog.commands[0]
    assert command.annotations[0].page_image_sha256 == PAGE_SHA
    assert command.sources[0].source_pdf.sha256 == SOURCE_SHA
    assert command.request_sha256 == content_sha256(
        command.model_dump(
            mode="json",
            exclude={"idempotency_key", "request_sha256"},
        )
    )
    with service.sessions() as session:
        records = tuple(session.scalars(select(DocumentReviewPdfAnnotationRecord)))
        outputs = tuple(session.scalars(select(DocumentReviewPdfAnnotationOutputRecord)))
        assert len(records) == 1
        assert len(outputs) == 1
        assert outputs[0].sha256 == OUTPUT_SHA
        assert all(
            not isinstance(value, (bytes, bytearray))
            for row in (records[0], outputs[0])
            for value in row.__dict__.values()
        )
    assert service.annotation(WORKFLOW_ID, ANNOTATION_ID, actor_id=OPERATOR_ID) == first
    assert (
        service.download(
            WORKFLOW_ID,
            ANNOTATION_ID,
            "DOCUMENT",
            actor_id=OPERATOR_ID,
        ).sha256
        == OUTPUT_SHA
    )
    engine.dispose()


def test_immutable_annotation_commit_does_not_require_update_or_row_lock() -> None:
    source = inspect.getsource(DocumentReviewAnnotationApplicationService.create)

    assert "with_for_update" not in source
    assert "document_review_pdf_annotations" not in UPDATE_TABLES
    assert "document_review_pdf_annotation_outputs" not in UPDATE_TABLES
