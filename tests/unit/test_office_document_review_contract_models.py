from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from eom_catalog_contracts import (
    ApplyDocumentReviewHwpxCorrections,
    DocumentReviewHwpxCorrectionMediaQuery,
    DocumentReviewHwpxCorrectionPlan,
    DocumentReviewHwpxCorrectionResponse,
    DocumentReviewHwpxCorrectionResult,
    OfficeDocumentReviewIntakeCommand,
    OfficeDocumentReviewIntakeManifest,
    validate_contract,
)
from eom_identifiers import content_sha256
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _member(
    member_path: str,
    *,
    media_type: str,
    schema_ref: str,
    sha256: str = SHA_A,
    with_identity: bool = False,
) -> dict[str, object]:
    value: dict[str, object] = {
        "member_path": member_path,
        "sha256": sha256,
        "content_length": 1024,
        "media_type": media_type,
        "schema_ref": schema_ref,
    }
    if with_identity:
        value.update(
            artifact_id="artifact_" + "1" * 32,
            artifact_revision_id="rev_" + "2" * 32,
        )
    return value


def _hwpx_manifest() -> dict[str, Any]:
    source = _member(
        "source/original.hwpx",
        media_type="application/vnd.hancom.hwpx",
        schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
    )
    value: dict[str, Any] = {
        "schema_version": "document-review-intake-manifest/2.0",
        "document_id": "document_" + "3" * 32,
        "document_revision_id": "documentrev_" + "4" * 32,
        "original_filename": "source.hwpx",
        "source_format": "HWPX",
        "original_source": source,
        "review_pdf": _member(
            "source/original.pdf",
            media_type="application/pdf",
            schema_ref="eom://schemas/document-review/pdf-source/1.0",
            sha256=SHA_B,
        ),
        "editable_hwpx": deepcopy(source),
        "conversion": {
            "conversion_kind": "LIBREOFFICE_H2ORESTART_PDF",
            "review_pdf_sha256": SHA_B,
            "libreoffice_version": "24.2.7.2",
            "libreoffice_sha256": SHA_A,
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
    }
    value["manifest_sha256"] = content_sha256(value)
    return value


def _correction_plan() -> dict[str, Any]:
    before = "바꾸기 전 문장"
    after = "바꾼 문장"
    value: dict[str, Any] = {
        "schema_version": "document-review-hwpx-correction-plan/1.0",
        "correction_id": "doccorrection_" + "5" * 32,
        "workflow_id": "workflow_" + "6" * 32,
        "review_result": _member(
            "result.json",
            media_type="application/json",
            schema_ref="eom://schemas/document-review/review-result/1.0",
            with_identity=True,
        ),
        "base_hwpx": _member(
            "source/original.hwpx",
            media_type="application/vnd.hancom.hwpx",
            schema_ref="eom://schemas/document-review/editable-hwpx/1.0",
            sha256=SHA_B,
            with_identity=True,
        ),
        "text_color": "#FF0000",
        "edits": [
            {
                "finding_id": "reviewfinding_" + "7" * 32,
                "finding_code": "TYPO_CONFIRMED",
                "before_text": before,
                "before_sha256": content_sha256(before),
                "after_text": after,
                "after_sha256": content_sha256(after),
                "address": {
                    "section_member": "Contents/section0.xml",
                    "paragraph_ordinal": 3,
                    "paragraph_sha256": content_sha256("문단 전체"),
                    "start_offset": 2,
                    "end_offset": 10,
                    "source_char_property_id": 4,
                },
            }
        ],
    }
    value["plan_sha256"] = content_sha256(value)
    return value


def test_office_intake_command_matches_schema_and_pydantic_semantics() -> None:
    value = {
        "schema_version": "document-review-intake-request/2.0",
        "operation": "INGEST_DOCUMENT_REVIEW_SOURCE",
        "actor_id": "operator_test",
        "original_filename": "review.hwpx",
        "source_format": "HWPX",
        "media_type": "application/vnd.hancom.hwpx",
        "idempotency_key": "office-review-test-key",
        "content_length": 1024,
        "sha256": SHA_A,
    }
    validate_contract("document-review-intake-request-v2", value)
    assert OfficeDocumentReviewIntakeCommand.model_validate(value).source_format == "HWPX"

    invalid = dict(value, media_type="application/pdf")
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("document-review-intake-request-v2", invalid)
    with pytest.raises(ValidationError):
        OfficeDocumentReviewIntakeCommand.model_validate(invalid)


def test_office_intake_manifest_binds_exact_hwpx_projection_and_self_hash() -> None:
    value = _hwpx_manifest()
    validate_contract("document-review-intake-manifest-v2", value)
    manifest = OfficeDocumentReviewIntakeManifest.model_validate(value)
    assert manifest.editable_hwpx == manifest.original_source

    tampered = deepcopy(value)
    tampered["pages"][0]["sha256"] = SHA_A
    with pytest.raises(ValidationError, match="manifest hash differs"):
        OfficeDocumentReviewIntakeManifest.model_validate(tampered)


def test_office_intake_manifest_rejects_editable_hwp_source() -> None:
    value = _hwpx_manifest()
    value.update(original_filename="source.hwp", source_format="HWP")
    value["original_source"].update(
        member_path="source/original.hwp",
        media_type="application/vnd.hancom.hwp",
        schema_ref="eom://schemas/document-review/hwp-source/2.0",
    )
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    with pytest.raises(ValidationError, match="cannot expose an editable HWPX"):
        OfficeDocumentReviewIntakeManifest.model_validate(value)


def test_correction_request_rejects_duplicate_findings_in_both_contract_layers() -> None:
    finding_id = "reviewfinding_" + "7" * 32
    value = {
        "schema_version": "document-review-hwpx-correction-request/1.0",
        "operation": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS",
        "actor_id": "operator_test",
        "idempotency_key": "office-correction-test-key",
        "workflow_id": "workflow_" + "6" * 32,
        "review_result": _correction_plan()["review_result"],
        "base_hwpx": _correction_plan()["base_hwpx"],
        "finding_ids": [finding_id, finding_id],
    }
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("document-review-hwpx-correction-request", value)
    with pytest.raises(ValidationError, match="must be unique"):
        ApplyDocumentReviewHwpxCorrections.model_validate(value)


def test_correction_plan_requires_text_hashes_order_and_self_hash() -> None:
    value = _correction_plan()
    validate_contract("document-review-hwpx-correction-plan", value)
    plan = DocumentReviewHwpxCorrectionPlan.model_validate(value)
    assert plan.text_color == "#FF0000"

    tampered = deepcopy(value)
    tampered["edits"][0]["after_text"] = "해시와 다른 문장"
    with pytest.raises(ValidationError, match="after-text hash differs"):
        DocumentReviewHwpxCorrectionPlan.model_validate(tampered)


def test_correction_result_requires_new_hwpx_and_self_hash() -> None:
    plan = _correction_plan()
    value: dict[str, Any] = {
        "schema_version": "document-review-hwpx-correction-result/1.0",
        "correction_id": plan["correction_id"],
        "workflow_id": plan["workflow_id"],
        "plan_sha256": plan["plan_sha256"],
        "base_hwpx_sha256": SHA_B,
        "output_member": {
            "member_path": "corrected/document-review-redline.hwpx",
            "sha256": SHA_C,
            "content_length": 2048,
            "media_type": "application/vnd.hancom.hwpx",
        },
        "applied_finding_ids": [plan["edits"][0]["finding_id"]],
        "text_color": "#FF0000",
    }
    value["result_sha256"] = content_sha256(value)
    validate_contract("document-review-hwpx-correction-result", value)
    assert DocumentReviewHwpxCorrectionResult.model_validate(value).output_member.sha256 == SHA_C

    same_bytes = deepcopy(value)
    same_bytes["output_member"]["sha256"] = SHA_B
    same_bytes["result_sha256"] = content_sha256(
        {key: item for key, item in same_bytes.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="must differ"):
        DocumentReviewHwpxCorrectionResult.model_validate(same_bytes)


def test_correction_response_and_media_query_pin_one_hwpx_artifact() -> None:
    plan = _correction_plan()
    raw_result: dict[str, Any] = {
        "schema_version": "document-review-hwpx-correction-result/1.0",
        "correction_id": plan["correction_id"],
        "workflow_id": plan["workflow_id"],
        "plan_sha256": plan["plan_sha256"],
        "base_hwpx_sha256": SHA_B,
        "output_member": {
            "member_path": "corrected/document-review-redline.hwpx",
            "sha256": SHA_C,
            "content_length": 2048,
            "media_type": "application/vnd.hancom.hwpx",
        },
        "applied_finding_ids": [plan["edits"][0]["finding_id"]],
        "text_color": "#FF0000",
    }
    raw_result["result_sha256"] = content_sha256(raw_result)
    output = _member(
        "corrected/document-review-redline.hwpx",
        media_type="application/vnd.hancom.hwpx",
        schema_ref="eom://schemas/document-review/corrected-hwpx/1.0",
        sha256=SHA_C,
        with_identity=True,
    )
    output["content_length"] = 2048
    value = {
        "schema_version": "document-review-hwpx-correction-response/1.0",
        "operation": "APPLY_DOCUMENT_REVIEW_HWPX_CORRECTIONS",
        "status": "OK",
        "output": output,
        "result": raw_result,
    }
    validate_contract("document-review-hwpx-correction-response", value)
    response = DocumentReviewHwpxCorrectionResponse.model_validate(value)
    assert response.output is not None
    query = DocumentReviewHwpxCorrectionMediaQuery(
        workflow_id=str(plan["workflow_id"]),
        correction_id=str(plan["correction_id"]),
        output=response.output,
    )
    validate_contract(
        "document-review-hwpx-correction-media-request",
        query.model_dump(mode="json"),
    )

    mismatch = deepcopy(value)
    cast(dict[str, object], mismatch["output"])["sha256"] = SHA_A
    with pytest.raises(ValidationError, match="pointer differs"):
        DocumentReviewHwpxCorrectionResponse.model_validate(mismatch)
