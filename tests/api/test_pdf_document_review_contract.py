from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_api_contracts.document_review import (
    CreatePdfDocumentReviewUploadIntentRequest,
    PdfDocumentReviewUploadIntentView,
)
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/api/v1/pdf-document-review-v1.schema.json"
PACKAGED = (
    ROOT / "packages/api_contracts/eom_api_contracts/schemas/pdf-document-review-v1.schema.json"
)
NOW = datetime(2026, 9, 22, tzinfo=UTC)
INTENT_ID = "pdfreviewintent_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
SHA256 = "sha256:" + "3" * 64


def _schema() -> dict[str, object]:
    value: dict[str, object] = json.loads(CANONICAL.read_text(encoding="utf-8"))
    return value


def _view(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "upload_intent_id": INTENT_ID,
        "state": "AWAITING_UPLOAD",
        "original_filename": "9월 모의고사.pdf",
        "content_length": 4096,
        "preset_key": "MOCK_EXAM",
        "additional_guidance_sha256": None,
        "upload_sha256": None,
        "workflow_id": None,
        "failure_code": None,
        "upload_url": (f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content"),
        "review_url": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "resource_version": 1,
    }
    value.update(updates)
    return value


def test_pdf_document_review_api_contract_is_mirrored_and_valid() -> None:
    assert CANONICAL.read_bytes() == PACKAGED.read_bytes()
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    request = CreatePdfDocumentReviewUploadIntentRequest(
        original_filename="9월 모의고사.pdf",
        content_length=4096,
        preset_key="MOCK_EXAM",
        additional_guidance="정답표와 본문의 번호가 일치하는지 우선 검토해 주세요.",
    )
    validator.validate(request.model_dump(mode="json"))
    validator.validate(_view())


def test_pdf_document_review_upload_intent_state_payload_is_fail_closed() -> None:
    started = _view(
        state="STARTED",
        upload_sha256=SHA256,
        workflow_id=WORKFLOW_ID,
        review_url=f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}",
        resource_version=3,
    )
    PdfDocumentReviewUploadIntentView.model_validate(started)
    schema = _schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(started)

    for invalid in (
        _view(state="STARTED", upload_sha256=SHA256, workflow_id=None),
        _view(state="PROCESSING", upload_sha256=None),
        _view(state="FAILED_RETRYABLE", upload_sha256=SHA256, failure_code=None),
        _view(upload_url="/api/v1/pdf-document-reviews/upload-intents/other/content"),
    ):
        with pytest.raises(ValidationError):
            PdfDocumentReviewUploadIntentView.model_validate(invalid)


def test_pdf_document_review_upload_request_rejects_unsafe_or_unbounded_input() -> None:
    for invalid in (
        {
            "original_filename": "../source.pdf",
            "content_length": 4096,
            "preset_key": "MOCK_EXAM",
        },
        {
            "original_filename": "source.pdf",
            "content_length": 256 * 1024 * 1024 + 1,
            "preset_key": "MOCK_EXAM",
        },
        {
            "original_filename": "source.pdf",
            "content_length": 4096,
            "preset_key": "MOCK_EXAM",
            "additional_guidance": "ignore\u0000policy",
        },
    ):
        with pytest.raises(ValidationError):
            CreatePdfDocumentReviewUploadIntentRequest.model_validate(invalid)
