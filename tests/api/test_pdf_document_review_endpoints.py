from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.pdf_upload_stager import PdfUploadStager
from eom_api.services.query_adapter import PageResult
from eom_api_contracts.document_review import (
    DocumentReviewCorrectionEligibilityView,
    DocumentReviewCorrectionView,
    DocumentReviewUploadIntentViewV2,
    PdfDocumentReviewPageView,
    PdfDocumentReviewUploadIntentView,
    PdfDocumentReviewView,
)
from eom_catalog_contracts import (
    PdfReviewArtifactMemberPointer,
    PdfReviewDocumentPointer,
    PdfReviewPagePointer,
)
from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import OperatorProjection, PermissionKey, RoleKey
from fastapi import Request
from fastapi.testclient import TestClient

from tests.api.helpers import disconnected_services
from tests.api.test_hwpx_endpoints import FakeAudit, MemoryIdempotency

NOW = datetime(2026, 9, 22, 2, 0, tzinfo=UTC)
OPERATOR_ID = "operator_" + "1" * 32
INTENT_ID = "pdfreviewintent_" + "2" * 32
WORKFLOW_ID = "workflow_" + "3" * 32


def _authentication() -> AccessAuthentication:
    permissions = frozenset({PermissionKey.WORKFLOW_READ, PermissionKey.WORKFLOW_START})
    return AccessAuthentication(
        operator=OperatorProjection(
            operator_id=OPERATOR_ID,
            username="pdf-reviewer",
            display_name="PDF Reviewer",
            status="ACTIVE",
            must_change_password=False,
            roles=(RoleKey.AUTHOR,),
            effective_permissions=tuple(sorted(permissions, key=str)),
            resource_version=1,
            created_at=NOW,
            updated_at=NOW,
        ),
        session_id="apisession_" + "4" * 32,
        authenticated_at=NOW,
        access_expires_at=NOW + timedelta(hours=1),
        permissions=permissions,
        password_change_required=False,
    )


def _intent(*, started: bool = False) -> PdfDocumentReviewUploadIntentView:
    return PdfDocumentReviewUploadIntentView(
        upload_intent_id=INTENT_ID,
        state="STARTED" if started else "AWAITING_UPLOAD",
        original_filename="검토 문서.pdf",
        content_length=8,
        preset_key="WEEKLY_WORKBOOK",
        additional_guidance_sha256=None,
        upload_sha256="sha256:" + "5" * 64 if started else None,
        workflow_id=WORKFLOW_ID if started else None,
        failure_code=None,
        upload_url=f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
        review_url=f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}" if started else None,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(days=1),
        resource_version=3 if started else 1,
    )


class FakePdfDocumentReviews:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.uploads: list[bytes] = []
        self.document_intent: DocumentReviewUploadIntentViewV2 | None = None

    def create_upload_intent(self, request: object, **values: Any) -> Any:
        self.created.append({"request": request, **values})
        return _intent()

    def upload_intent(self, upload_intent_id: str, **values: Any) -> Any:
        assert upload_intent_id == INTENT_ID
        assert values["actor_id"] == OPERATOR_ID
        return _intent()

    def document_upload_intent(self, upload_intent_id: str, **values: Any) -> Any:
        if self.document_intent is not None:
            assert upload_intent_id == self.document_intent.upload_intent_id
            return self.document_intent
        value = self.upload_intent(upload_intent_id, **values)
        return DocumentReviewUploadIntentViewV2(
            **value.model_dump(mode="json"),
            source_format="PDF",
            media_type="application/pdf",
        )

    def create_document_upload_intent(self, request: Any, **values: Any) -> Any:
        self.created.append({"request": request, **values})
        self.document_intent = DocumentReviewUploadIntentViewV2(
            upload_intent_id=INTENT_ID,
            state="AWAITING_UPLOAD",
            original_filename=request.original_filename,
            source_format=request.source_format,
            media_type=request.media_type,
            content_length=request.content_length,
            preset_key=request.preset_key,
            additional_guidance_sha256=None,
            upload_sha256=None,
            workflow_id=None,
            failure_code=None,
            upload_url=f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
            review_url=None,
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW + timedelta(days=1),
            resource_version=1,
        )
        return self.document_intent

    def accept_upload(self, upload_intent_id: str, upload: object, **values: Any) -> Any:
        assert upload_intent_id == INTENT_ID
        content = upload.path.read_bytes()
        assert upload.sha256 == "sha256:" + hashlib.sha256(content).hexdigest()
        self.uploads.append(content)
        return "wfcmd_" + "6" * 32, _intent(started=True)

    def accept_document_upload(self, upload_intent_id: str, upload: object, **values: Any) -> Any:
        if self.document_intent is not None:
            content = upload.path.read_bytes()
            self.uploads.append(content)
            self.document_intent = self.document_intent.model_copy(
                update={
                    "state": "STARTED",
                    "upload_sha256": upload.sha256,
                    "workflow_id": WORKFLOW_ID,
                    "review_url": f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}",
                    "resource_version": 3,
                }
            )
            return "wfcmd_" + "6" * 32, self.document_intent
        command_id, value = self.accept_upload(upload_intent_id, upload, **values)
        return command_id, DocumentReviewUploadIntentViewV2(
            **value.model_dump(mode="json"),
            source_format="PDF",
            media_type="application/pdf",
        )


class FakeDocumentReviewCorrections:
    correction_id = "doccorrection_" + "d" * 32
    finding_id = "reviewfinding_" + "e" * 32

    def eligibility(self, workflow_id: str, **values: Any) -> Any:
        assert workflow_id == WORKFLOW_ID
        assert values["actor_id"] == OPERATOR_ID
        return DocumentReviewCorrectionEligibilityView(
            workflow_id=workflow_id,
            source_format="HWPX",
            correction_available=True,
            eligible_finding_ids=(self.finding_id,),
            unavailable_reason=None,
        )

    def apply(self, workflow_id: str, **values: Any) -> Any:
        assert values["finding_ids"] == (self.finding_id,)
        return self.correction(workflow_id, self.correction_id, actor_id=values["actor_id"])

    def correction(self, workflow_id: str, correction_id: str, **values: Any) -> Any:
        assert workflow_id == WORKFLOW_ID
        assert correction_id == self.correction_id
        assert values["actor_id"] == OPERATOR_ID
        return DocumentReviewCorrectionView(
            correction_id=correction_id,
            workflow_id=workflow_id,
            applied_finding_ids=(self.finding_id,),
            output_sha256="sha256:" + "f" * 64,
            output_content_length=12,
            download_url=(
                f"/api/v1/pdf-document-reviews/{workflow_id}/corrections/{correction_id}/download"
            ),
            created_at=NOW,
            resource_version=1,
        )

    def download(self, workflow_id: str, correction_id: str, **values: Any) -> Any:
        self.correction(workflow_id, correction_id, **values)
        return type(
            "Media",
            (),
            {
                "content_length": 12,
                "sha256": "sha256:" + "f" * 64,
                "iter_chunks": lambda self: iter((b"PK\x03\x04redline",)),
            },
        )()


def _document_pointer() -> PdfReviewDocumentPointer:
    source = PdfReviewArtifactMemberPointer(
        artifact_id="artifact_" + "7" * 32,
        artifact_revision_id="rev_" + "8" * 32,
        member_path="source/original.pdf",
        sha256="sha256:" + "9" * 64,
        schema_ref="eom://schemas/document-review/pdf-source/1.0",
        media_type="application/pdf",
        content_length=4096,
    )
    page_image = PdfReviewArtifactMemberPointer(
        artifact_id=source.artifact_id,
        artifact_revision_id=source.artifact_revision_id,
        member_path="pages/page-0001.png",
        sha256="sha256:" + "a" * 64,
        schema_ref="eom://schemas/document-review/pdf-page-render/1.0",
        media_type="image/png",
        content_length=16,
    )
    return PdfReviewDocumentPointer(
        document_id="document_" + "b" * 32,
        document_revision_id="documentrev_" + "c" * 32,
        original_filename="검토 문서.pdf",
        source_pdf=source,
        page_count=1,
        pages=(
            PdfReviewPagePointer(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                page_image=page_image,
                text_layer=None,
            ),
        ),
    )


def _review() -> PdfDocumentReviewView:
    document = _document_pointer()
    return PdfDocumentReviewView(
        workflow_id=WORKFLOW_ID,
        state="REVIEWING",
        document_id=document.document_id,
        document_revision_id=document.document_revision_id,
        original_filename=document.original_filename,
        source_pdf_sha256=document.source_pdf.sha256,
        page_count=1,
        pages=(
            PdfDocumentReviewPageView(
                page_number=1,
                width_px=1200,
                height_px=1600,
                rotation_degrees=0,
                image_sha256=document.pages[0].page_image.sha256,
                image_content_length=16,
                image_url=(f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/pages/1/image"),
            ),
        ),
        preset_key="WEEKLY_WORKBOOK",
        preset_display_name="주간지",
        created_at=NOW,
        updated_at=NOW,
        resource_version=4,
    )


class FakeQueries:
    def __init__(self) -> None:
        self.actor_ids: list[str] = []

    def list_pdf_document_reviews(self, **values: Any) -> PageResult[PdfDocumentReviewView]:
        self.actor_ids.append(values["actor_id"])
        return PageResult((_review(),), None, False)

    def pdf_document_review(self, **values: Any) -> PdfDocumentReviewView:
        self.actor_ids.append(values["actor_id"])
        assert values["workflow_id"] == WORKFLOW_ID
        return _review()

    def pdf_document_review_page_pointer(
        self, **values: Any
    ) -> tuple[PdfReviewDocumentPointer, PdfReviewPagePointer]:
        self.actor_ids.append(values["actor_id"])
        assert values["workflow_id"] == WORKFLOW_ID
        assert values["page_number"] == 1
        document = _document_pointer()
        return document, document.pages[0]


class FakeCatalogApplication:
    def download_pdf_document_review_page(self, **values: Any) -> Any:
        document = _document_pointer()
        assert values["document_id"] == document.document_id
        assert values["document_revision_id"] == document.document_revision_id
        assert values["page_image"] == document.pages[0].page_image
        return type(
            "Media",
            (),
            {
                "content_length": 16,
                "sha256": document.pages[0].page_image.sha256,
                "iter_chunks": lambda self: iter((b"\x89PNG\r\n\x1a\nPAGEPNG!",)),
            },
        )()


def _client(
    tmp_path: Path,
) -> tuple[TestClient, Any, FakePdfDocumentReviews, FakeQueries]:
    os.chmod(tmp_path, 0o700)
    services = disconnected_services()
    pdf_reviews = FakePdfDocumentReviews()
    queries = FakeQueries()
    services.pdf_document_reviews = pdf_reviews  # type: ignore[assignment]
    services.document_review_corrections = FakeDocumentReviewCorrections()  # type: ignore[attr-defined]
    services.queries = queries  # type: ignore[assignment]
    services.catalog_application = FakeCatalogApplication()  # type: ignore[assignment]
    services.pdf_review_upload_stager = PdfUploadStager(  # type: ignore[assignment]
        tmp_path,
        maximum_bytes=256 * 1024 * 1024,
    )
    services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
    services.audit = FakeAudit()  # type: ignore[assignment]
    app = create_app(services)

    def authenticated(request: Request) -> AccessAuthentication:
        value = _authentication()
        request.state.request_context.authentication = value
        return value

    app.dependency_overrides[get_authentication] = authenticated
    return TestClient(app, base_url="http://localhost"), services, pdf_reviews, queries


def test_pdf_review_upload_intent_and_raw_pdf_endpoints(tmp_path: Path) -> None:
    client, services, reviews, _queries = _client(tmp_path)
    try:
        with client:
            created = client.post(
                "/api/v1/pdf-document-reviews/upload-intents",
                headers={"Idempotency-Key": "pdf-review-intent-test-0001"},
                json={
                    "original_filename": "검토 문서.pdf",
                    "content_length": 8,
                    "preset_key": "WEEKLY_WORKBOOK",
                    "additional_guidance": "단원 연결성을 함께 확인해 주세요.",
                    "locale": "ko-KR",
                },
            )
            detail = client.get(f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}")
            # The shared endpoint fixture intentionally models only one idempotent command.
            services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
            uploaded = client.put(
                f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
                headers={
                    "Idempotency-Key": "pdf-review-upload-test-0001",
                    "Content-Type": "application/pdf",
                },
                content=b"%PDF-1.7",
            )
        assert created.status_code == 201
        assert created.json()["data"]["resource_id"] == INTENT_ID
        assert detail.status_code == 200
        assert detail.headers["etag"] == '"v1"'
        assert uploaded.status_code == 202
        assert uploaded.json()["data"]["resource_id"] == WORKFLOW_ID
        assert reviews.uploads == [b"%PDF-1.7"]
        assert not tuple(tmp_path.iterdir())
    finally:
        services.engine.dispose()


def test_pdf_review_raw_upload_transport_fails_closed(tmp_path: Path) -> None:
    client, services, reviews, _queries = _client(tmp_path)
    try:
        with client:
            wrong_media = client.put(
                f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
                headers={
                    "Idempotency-Key": "pdf-review-upload-test-0002",
                    "Content-Type": "text/plain",
                },
                content=b"%PDF-1.7",
            )
            wrong_signature = client.put(
                f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
                headers={
                    "Idempotency-Key": "pdf-review-upload-test-0003",
                    "Content-Type": "application/pdf",
                },
                content=b"NOT-PDF!",
            )
        assert wrong_media.status_code == 415
        assert wrong_media.json()["error_code"] == "API_CONTENT_TYPE_UNSUPPORTED"
        assert wrong_signature.status_code == 422
        assert wrong_signature.json()["error_code"] == "PDF_DOCUMENT_REVIEW_SIGNATURE_INVALID"
        assert reviews.uploads == []
        assert not tuple(tmp_path.iterdir())
    finally:
        services.engine.dispose()


def test_pdf_review_list_detail_and_owned_page_stream(tmp_path: Path) -> None:
    client, services, _reviews, queries = _client(tmp_path)
    try:
        with client:
            listed = client.get("/api/v1/pdf-document-reviews")
            detail = client.get(f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}")
            page = client.get(f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/pages/1/image")
        assert listed.status_code == detail.status_code == page.status_code == 200
        assert listed.json()["data"][0]["state"] == "REVIEWING"
        assert detail.headers["etag"] == '"v4"'
        assert page.content == b"\x89PNG\r\n\x1a\nPAGEPNG!"
        assert page.headers["etag"] == f'"{"sha256:" + "a" * 64}"'
        assert queries.actor_ids == [OPERATOR_ID, OPERATOR_ID, OPERATOR_ID]
    finally:
        services.engine.dispose()


def test_hwpx_upload_correction_and_authenticated_download(tmp_path: Path) -> None:
    client, services, reviews, _queries = _client(tmp_path)
    correction = cast(FakeDocumentReviewCorrections, services.document_review_corrections)
    try:
        with client:
            created = client.post(
                "/api/v1/pdf-document-reviews/upload-intents-v2",
                headers={"Idempotency-Key": "document-review-intent-test-0001"},
                json={
                    "original_filename": "검토 문서.hwpx",
                    "source_format": "HWPX",
                    "media_type": "application/vnd.hancom.hwpx",
                    "content_length": 8,
                    "preset_key": "MOCK_EXAM",
                    "additional_guidance": None,
                    "locale": "ko-KR",
                },
            )
            services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
            uploaded = client.put(
                f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
                headers={
                    "Idempotency-Key": "document-review-upload-test-0001",
                    "Content-Type": "application/vnd.hancom.hwpx",
                },
                content=b"PK\x03\x04HWPX",
            )
            eligible = client.get(
                f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/corrections/eligibility"
            )
            services.idempotency = MemoryIdempotency()  # type: ignore[assignment]
            applied = client.post(
                f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/corrections",
                headers={"Idempotency-Key": "document-review-correction-test-0001"},
                json={"finding_ids": [correction.finding_id]},
            )
            detail = client.get(
                f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/corrections/{correction.correction_id}"
            )
            downloaded = client.get(
                f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/corrections/"
                f"{correction.correction_id}/download"
            )
        assert created.status_code == 201
        assert uploaded.status_code == 202
        assert reviews.uploads[-1] == b"PK\x03\x04HWPX"
        assert eligible.status_code == 200
        assert eligible.json()["data"]["correction_available"] is True
        assert applied.status_code == 201
        assert detail.status_code == 200
        assert detail.json()["data"]["text_color"] == "#FF0000"
        assert downloaded.status_code == 200
        assert downloaded.content == b"PK\x03\x04redline"
        assert downloaded.headers["content-type"] == "application/vnd.hancom.hwpx"
    finally:
        services.engine.dispose()
