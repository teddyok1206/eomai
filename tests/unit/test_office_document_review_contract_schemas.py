from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = (
    "document-review-intake-manifest-v2.schema.json",
    "document-review-intake-manifest-v3.schema.json",
    "document-review-source-upload-manifest-v1.schema.json",
    "office-document-conversion-outcome-v1.schema.json",
    "document-review-intake-request-v2.schema.json",
    "document-review-intake-request-v3.schema.json",
    "document-review-intake-response-v2.schema.json",
    "document-review-intake-response-v3.schema.json",
    "document-review-hwpx-correction-request-v1.schema.json",
    "document-review-hwpx-correction-response-v1.schema.json",
    "document-review-hwpx-correction-media-request-v1.schema.json",
    "document-review-hwpx-correction-media-response-v1.schema.json",
    "document-review-hwpx-correction-plan-v1.schema.json",
    "document-review-hwpx-correction-result-v1.schema.json",
)
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _canonical(name: str) -> Path:
    if "request" in name or "response" in name:
        return ROOT / "schemas/catalog/catalog-application" / name
    return ROOT / "schemas/document-review" / name


def _packaged(name: str) -> Path:
    area = "catalog-application" if "request" in name or "response" in name else "document-review"
    return ROOT / "packages/catalog_contracts/eom_catalog_contracts/resources" / area / name


def _schema(name: str) -> dict[str, Any]:
    value: object = json.loads(_canonical(name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _member(
    path: str,
    *,
    media_type: str,
    schema_ref: str,
    sha256: str = SHA_A,
) -> dict[str, object]:
    return {
        "artifact_id": "artifact_" + "1" * 32,
        "artifact_revision_id": "rev_" + "2" * 32,
        "member_path": path,
        "sha256": sha256,
        "schema_ref": schema_ref,
        "media_type": media_type,
        "content_length": 1024,
    }


def test_office_review_schemas_are_draft_2020_12_and_packaged_exactly() -> None:
    for name in SCHEMA_NAMES:
        canonical = _canonical(name)
        packaged = _packaged(name)
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(_schema(name))


@pytest.mark.parametrize(
    ("source_format", "filename", "media_type"),
    (
        ("PDF", "document.pdf", "application/pdf"),
        ("HWP", "document.hwp", "application/vnd.hancom.hwp"),
        ("HWPX", "document.hwpx", "application/vnd.hancom.hwpx"),
    ),
)
def test_office_review_intake_request_binds_suffix_format_and_media_type(
    source_format: str,
    filename: str,
    media_type: str,
) -> None:
    value = {
        "schema_version": "document-review-intake-request/2.0",
        "operation": "INGEST_DOCUMENT_REVIEW_SOURCE",
        "actor_id": "operator_test",
        "original_filename": filename,
        "source_format": source_format,
        "media_type": media_type,
        "idempotency_key": "office-review-schema-test",
        "content_length": 1024,
        "sha256": SHA_A,
    }
    validator = Draft202012Validator(_schema("document-review-intake-request-v2.schema.json"))
    validator.validate(value)
    mismatched = dict(value)
    mismatched["media_type"] = "application/pdf"
    if source_format == "PDF":
        mismatched["original_filename"] = "document.hwpx"
    with pytest.raises(ValidationError):
        validator.validate(mismatched)


def test_office_review_intake_manifest_keeps_hwp_non_editable() -> None:
    value = {
        "schema_version": "document-review-intake-manifest/2.0",
        "document_id": "document_" + "1" * 32,
        "document_revision_id": "documentrev_" + "2" * 32,
        "original_filename": "source.hwp",
        "source_format": "HWP",
        "original_source": {
            key: item
            for key, item in _member(
                "source/original.hwp",
                media_type="application/vnd.hancom.hwp",
                schema_ref="eom://schemas/document-review/original-source/2.0",
            ).items()
            if key not in {"artifact_id", "artifact_revision_id"}
        },
        "review_pdf": {
            key: item
            for key, item in _member(
                "source/original.pdf",
                media_type="application/pdf",
                schema_ref="eom://schemas/document-review/review-pdf/2.0",
                sha256=SHA_B,
            ).items()
            if key not in {"artifact_id", "artifact_revision_id"}
        },
        "editable_hwpx": None,
        "conversion": {
            "conversion_kind": "LIBREOFFICE_H2ORESTART_PDF",
            "review_pdf_sha256": SHA_B,
            "libreoffice_version": "24.2.7.2",
            "libreoffice_sha256": SHA_B,
            "h2orestart_sha256": SHA_C,
        },
        "renderer": {
            "renderer_key": "poppler-pdftoppm",
            "pdfinfo_sha256": SHA_A,
            "pdftoppm_sha256": SHA_B,
            "scale_to_px": 2400,
            "output_format": "PNG",
        },
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "member_path": "pages/page-0001.png",
                "sha256": SHA_C,
                "content_length": 2048,
                "width_px": 1698,
                "height_px": 2400,
                "rotation_degrees": 0,
            }
        ],
        "manifest_sha256": SHA_A,
    }
    Draft202012Validator(_schema("document-review-intake-manifest-v2.schema.json")).validate(value)


def test_office_review_v3_error_response_retains_exact_source_pointer() -> None:
    retained_source = _member(
        "source/original.hwpx",
        media_type="application/vnd.hancom.hwpx",
        schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
    )
    value = {
        "schema_version": "document-review-intake-response/3.0",
        "operation": "INGEST_DOCUMENT_REVIEW_SOURCE",
        "status": "ERROR",
        "error_code": "OFFICE_DOCUMENT_CONVERSION_RETURNED_FAILURE",
        "retained_source": retained_source,
    }
    validator = Draft202012Validator(_schema("document-review-intake-response-v3.schema.json"))
    validator.validate(value)

    missing_pointer = dict(value, retained_source=None)
    validator.validate(missing_pointer)

    mismatched = deepcopy(value)
    mismatched["retained_source"]["artifact_revision_id"] = "revision_unsafe"
    with pytest.raises(ValidationError):
        validator.validate(mismatched)


def test_hwpx_correction_request_rejects_duplicate_findings() -> None:
    finding_id = "reviewfinding_" + "3" * 32
    value = {
        "schema_version": "document-review-hwpx-correction-request/1.0",
        "operation": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS",
        "actor_id": "operator_test",
        "idempotency_key": "office-review-correction-test",
        "workflow_id": "workflow_" + "4" * 32,
        "review_result": _member(
            "result.json",
            media_type="application/json",
            schema_ref=(
                "https://eom.local/schemas/workflow/roles/pdf-document-review-result-v1.schema.json"
            ),
        ),
        "base_hwpx": _member(
            "source/original.hwpx",
            media_type="application/vnd.hancom.hwpx",
            schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
        ),
        "finding_ids": [finding_id],
    }
    validator = Draft202012Validator(
        _schema("document-review-hwpx-correction-request-v1.schema.json")
    )
    validator.validate(value)
    duplicated = deepcopy(value)
    duplicated["finding_ids"] = [finding_id, finding_id]
    with pytest.raises(ValidationError):
        validator.validate(duplicated)
