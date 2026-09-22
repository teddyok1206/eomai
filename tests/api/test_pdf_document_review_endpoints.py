from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eom_api.app import create_app
from eom_api.dependencies import get_authentication
from eom_api.services.pdf_upload_stager import PdfUploadStager
from eom_api_contracts.document_review import PdfDocumentReviewUploadIntentView
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

    def create_upload_intent(self, request: object, **values: Any) -> Any:
        self.created.append({"request": request, **values})
        return _intent()

    def upload_intent(self, upload_intent_id: str, **values: Any) -> Any:
        assert upload_intent_id == INTENT_ID
        assert values["actor_id"] == OPERATOR_ID
        return _intent()

    def accept_upload(self, upload_intent_id: str, upload: object, **values: Any) -> Any:
        assert upload_intent_id == INTENT_ID
        content = upload.path.read_bytes()
        assert upload.sha256 == "sha256:" + hashlib.sha256(content).hexdigest()
        self.uploads.append(content)
        return "wfcmd_" + "6" * 32, _intent(started=True)


def _client(tmp_path: Path) -> tuple[TestClient, Any, FakePdfDocumentReviews]:
    os.chmod(tmp_path, 0o700)
    services = disconnected_services()
    pdf_reviews = FakePdfDocumentReviews()
    services.pdf_document_reviews = pdf_reviews  # type: ignore[assignment]
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
    return TestClient(app, base_url="http://localhost"), services, pdf_reviews


def test_pdf_review_upload_intent_and_raw_pdf_endpoints(tmp_path: Path) -> None:
    client, services, reviews = _client(tmp_path)
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
    client, services, reviews = _client(tmp_path)
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
