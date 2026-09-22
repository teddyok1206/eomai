from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_api_contracts.document_review import (
    CreatePdfDocumentReviewUploadIntentRequest,
    PdfDocumentReviewUploadIntentView,
    PdfDocumentReviewView,
)
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "schemas/api/v1/pdf-document-review-v1.schema.json"
PACKAGED = (
    ROOT / "packages/api_contracts/eom_api_contracts/schemas/pdf-document-review-v1.schema.json"
)
RESULT_VIEW_CANONICAL = ROOT / "schemas/api/v1/pdf-document-review-result-view-v1.schema.json"
RESULT_VIEW_PACKAGED = (
    ROOT / "packages/api_contracts/eom_api_contracts/schemas/"
    "pdf-document-review-result-view-v1.schema.json"
)
WORKFLOW_RESULT = ROOT / "schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
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


def _result_output() -> dict[str, object]:
    return {
        "review_request_sha256": "sha256:" + "4" * 64,
        "document_id": "document_" + "5" * 32,
        "document_revision_id": "documentrev_" + "6" * 32,
        "source_pdf_sha256": "sha256:" + "7" * 64,
        "preset_key": "MOCK_EXAM",
        "preset_revision_id": "reviewpresetrev_" + "8" * 32,
        "preset_sha256": "sha256:" + "9" * 64,
        "additional_guidance_sha256": None,
        "review_status": "COMPLETE",
        "summary": "검토가 완료되었습니다.",
        "verification_targets": [
            {
                "target_id": "reviewtarget_" + "a" * 32,
                "axis": "SCIENTIFIC_ACCURACY",
                "page_numbers": [1],
                "anchors": [],
                "status": "VERIFIED",
                "conclusion": "검증 완료",
            }
        ],
        "candidate_findings": [],
        "findings": [],
        "mutation_performed": False,
    }


def _completed_review_view() -> dict[str, object]:
    output = _result_output()
    result = {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.25.0",
        "job_id": "job_" + "b" * 32,
        "workflow_id": WORKFLOW_ID,
        "step_run_id": "steprun_" + "c" * 32,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "d" * 32,
            "revision_id": "rev_" + "e" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "role": "support",
        "output": output,
    }
    return {
        "workflow_id": WORKFLOW_ID,
        "state": "COMPLETED",
        "document_id": output["document_id"],
        "document_revision_id": output["document_revision_id"],
        "original_filename": "9월 모의고사.pdf",
        "source_pdf_sha256": output["source_pdf_sha256"],
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "width_px": 1200,
                "height_px": 1600,
                "rotation_degrees": 0,
                "image_sha256": "sha256:" + "f" * 64,
                "image_content_length": 4096,
                "image_url": f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/pages/1/image",
            }
        ],
        "preset_key": "MOCK_EXAM",
        "preset_display_name": "모의고사",
        "additional_guidance_sha256": None,
        "result_artifact": {
            "artifact_id": result["artifact"]["logical_artifact_id"],
            "artifact_revision_id": result["artifact"]["revision_id"],
            "sha256": content_sha256(result),
        },
        "result": output,
        "failure_code": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
        "resource_version": 8,
    }


def test_pdf_document_review_result_view_is_mirrored_and_reuses_worker_output() -> None:
    assert RESULT_VIEW_CANONICAL.read_bytes() == RESULT_VIEW_PACKAGED.read_bytes()
    schema = json.loads(RESULT_VIEW_CANONICAL.read_text(encoding="utf-8"))
    worker_schema = json.loads(WORKFLOW_RESULT.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    registry = Registry().with_resource(
        worker_schema["$id"],
        Resource.from_contents(worker_schema),
    )
    value = _completed_review_view()
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(value)
    PdfDocumentReviewView.model_validate(value)

    invalid = dict(value)
    invalid["pages"] = [dict(value["pages"][0], image_url="/api/v1/pdf-document-reviews/x")]
    with pytest.raises(ValidationError):
        PdfDocumentReviewView.model_validate(invalid)
