from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_api_contracts.document_review import (
    ApplyDocumentReviewCorrectionRequest,
    CreateDocumentReviewUploadIntentRequestV2,
    DocumentReviewCorrectionEligibilityView,
    DocumentReviewCorrectionView,
    DocumentReviewUploadIntentViewV2,
)
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, tzinfo=UTC)
INTENT_ID = "pdfreviewintent_" + "1" * 32
WORKFLOW_ID = "workflow_" + "2" * 32
CORRECTION_ID = "doccorrection_" + "3" * 32
FINDING_ID = "reviewfinding_" + "4" * 32
SHA256 = "sha256:" + "5" * 64


def _schema(name: str) -> tuple[dict[str, object], Draft202012Validator]:
    canonical = ROOT / "schemas/api/v1" / name
    packaged = ROOT / "packages/api_contracts/eom_api_contracts/schemas" / name
    assert canonical.read_bytes() == packaged.read_bytes()
    value: dict[str, object] = json.loads(canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value, Draft202012Validator(value, format_checker=FormatChecker())


def _upload_view(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "upload_intent_id": INTENT_ID,
        "state": "AWAITING_UPLOAD",
        "original_filename": "검토 원고.hwpx",
        "source_format": "HWPX",
        "media_type": "application/vnd.hancom.hwpx",
        "content_length": 4096,
        "preset_key": "MOCK_EXAM",
        "additional_guidance_sha256": None,
        "upload_sha256": None,
        "workflow_id": None,
        "failure_code": None,
        "upload_url": f"/api/v1/pdf-document-reviews/upload-intents/{INTENT_ID}/content",
        "review_url": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "updated_at": NOW.isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "resource_version": 1,
    }
    value.update(updates)
    return value


def test_office_upload_v2_schema_and_models_are_exact() -> None:
    _, validator = _schema("document-review-upload-v2.schema.json")
    for source_format, suffix, media_type in (
        ("PDF", ".pdf", "application/pdf"),
        ("HWP", ".hwp", "application/vnd.hancom.hwp"),
        ("HWPX", ".hwpx", "application/vnd.hancom.hwpx"),
    ):
        request = CreateDocumentReviewUploadIntentRequestV2(
            original_filename="검토 원고" + suffix,
            source_format=source_format,
            media_type=media_type,
            content_length=4096,
            preset_key="MOCK_EXAM",
        )
        validator.validate(request.model_dump(mode="json"))

    view = _upload_view(
        state="STARTED",
        upload_sha256=SHA256,
        workflow_id=WORKFLOW_ID,
        review_url=f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}",
        resource_version=3,
    )
    validator.validate(view)
    DocumentReviewUploadIntentViewV2.model_validate(view)


@pytest.mark.parametrize(
    "invalid",
    [
        {
            "original_filename": "검토.hwpx",
            "source_format": "HWPX",
            "media_type": "application/pdf",
            "content_length": 4096,
            "preset_key": "MOCK_EXAM",
            "locale": "ko-KR",
        },
        _upload_view(state="PROCESSING", upload_sha256=None),
        _upload_view(
            state="FAILED_FINAL",
            upload_sha256=SHA256,
            failure_code=None,
        ),
    ],
)
def test_office_upload_v2_rejects_cross_field_drift(invalid: dict[str, object]) -> None:
    _, validator = _schema("document-review-upload-v2.schema.json")
    with pytest.raises(SchemaError):
        validator.validate(invalid)
    model = (
        DocumentReviewUploadIntentViewV2
        if "upload_intent_id" in invalid
        else CreateDocumentReviewUploadIntentRequestV2
    )
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_hwpx_correction_contract_is_hashed_and_downloadable() -> None:
    _, validator = _schema("document-review-hwpx-correction-v1.schema.json")
    request = ApplyDocumentReviewCorrectionRequest(finding_ids=(FINDING_ID,))
    validator.validate(request.model_dump(mode="json"))

    eligibility = DocumentReviewCorrectionEligibilityView(
        workflow_id=WORKFLOW_ID,
        source_format="HWPX",
        correction_available=True,
        eligible_finding_ids=(FINDING_ID,),
        unavailable_reason=None,
    )
    validator.validate(eligibility.model_dump(mode="json"))

    view = DocumentReviewCorrectionView(
        correction_id=CORRECTION_ID,
        workflow_id=WORKFLOW_ID,
        applied_finding_ids=(FINDING_ID,),
        output_sha256=SHA256,
        output_content_length=8192,
        download_url=(
            f"/api/v1/pdf-document-reviews/{WORKFLOW_ID}/corrections/{CORRECTION_ID}/download"
        ),
        created_at=NOW,
        resource_version=1,
    )
    validator.validate(view.model_dump(mode="json"))


def test_hwpx_correction_contract_rejects_duplicates_and_false_availability() -> None:
    for model, value in (
        (
            ApplyDocumentReviewCorrectionRequest,
            {"finding_ids": [FINDING_ID, FINDING_ID]},
        ),
        (
            DocumentReviewCorrectionEligibilityView,
            {
                "workflow_id": WORKFLOW_ID,
                "source_format": "PDF",
                "correction_available": True,
                "eligible_finding_ids": [FINDING_ID],
                "unavailable_reason": None,
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(value)
