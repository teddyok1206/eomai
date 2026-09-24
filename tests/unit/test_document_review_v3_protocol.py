from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_workflow import PairedDocumentReviewOutputV3
from eom_workflow.schemas import load_role_result_schema, validate_role_result
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SHA = "sha256:" + "1" * 64
QUESTION_DOCUMENT = "document_" + "2" * 32
SOLUTION_DOCUMENT = "document_" + "3" * 32
QUESTION_REVISION = "documentrev_" + "4" * 32
SOLUTION_REVISION = "documentrev_" + "5" * 32
ITEM_KEY = "reviewitem_" + "6" * 32


def _anchor(role: str, marker: str) -> dict[str, object]:
    return {
        "anchor_id": "reviewanchor_" + marker * 32,
        "document_role": role,
        "page_number": 1,
        "page_image_sha256": "sha256:" + marker * 64,
        "region": {
            "x_ppm": 100000,
            "y_ppm": 100000,
            "width_ppm": 200000,
            "height_ppm": 100000,
        },
        "quote": None,
        "quote_sha256": None,
    }


def _output() -> dict[str, object]:
    question_anchor = _anchor("QUESTION", "7")
    solution_anchor = _anchor("SOLUTION", "8")
    axes = (
        "ANSWER_UNIQUENESS",
        "ASSESSMENT_BALANCE",
        "CURRICULUM_SCOPE",
        "DOCUMENT_STRUCTURE",
        "EDITORIAL_CLARITY",
        "ORIGINALITY",
        "SCIENTIFIC_ACCURACY",
        "SOLUTION_CONSISTENCY",
        "TYPOGRAPHY",
        "VISUAL_CONTENT",
    )
    evidence_ids = tuple("evidenceitem_" + marker * 32 for marker in ("a", "b", "c"))
    return {
        "review_request_sha256": SHA,
        "documents": [
            {
                "role": "QUESTION",
                "document_id": QUESTION_DOCUMENT,
                "document_revision_id": QUESTION_REVISION,
                "source_pdf_sha256": "sha256:" + "2" * 64,
            },
            {
                "role": "SOLUTION",
                "document_id": SOLUTION_DOCUMENT,
                "document_revision_id": SOLUTION_REVISION,
                "source_pdf_sha256": "sha256:" + "3" * 64,
            },
        ],
        "preset_key": "MOCK_EXAM",
        "preset_revision_id": "reviewpresetrev_" + "9" * 32,
        "preset_sha256": "sha256:" + "4" * 64,
        "additional_guidance_sha256": None,
        "review_status": "COMPLETE",
        "summary": "모든 페이지와 문항별 풀이·단위·선지·해설·근거를 확인했습니다.",
        "verification_targets": [
            {
                "target_id": f"reviewtarget_{index:032x}",
                "axis": axis,
                "page_refs": [
                    {"document_role": "QUESTION", "page_number": 1},
                    {"document_role": "SOLUTION", "page_number": 1},
                ],
                "anchors": [],
                "status": "VERIFIED",
                "conclusion": f"{axis} 세부 항목을 독립 검증했습니다.",
            }
            for index, axis in enumerate(axes, start=1)
        ],
        "candidate_findings": [],
        "findings": [],
        "page_coverage": [
            {"document_role": "QUESTION", "page_number": 1},
            {"document_role": "SOLUTION", "page_number": 1},
        ],
        "item_reviews": [
            {
                "item_key": ITEM_KEY,
                "ordinal": 1,
                "question_label": "1번",
                "response_format": "MULTIPLE_CHOICE",
                "question_anchors": [question_anchor],
                "solution_anchors": [solution_anchor],
                "solve_summary": "조건을 식으로 정리하고 각 선지를 독립적으로 판정했습니다.",
                "solve_steps": [
                    {
                        "ordinal": 1,
                        "status": "VERIFIED",
                        "claim_summary": "문제 조건을 식으로 정리합니다.",
                        "verification_summary": "제시된 조건과 독립 풀이가 일치합니다.",
                        "question_anchors": [question_anchor],
                    }
                ],
                "final_answer": "1",
                "answer_status": "VERIFIED",
                "condition_sufficiency": "VERIFIED",
                "unit_checks": [
                    {
                        "check_id": "reviewunit_" + "d" * 32,
                        "quantity": "명시적 물리량 없음",
                        "value_expression": None,
                        "expected_unit": None,
                        "observed_unit": None,
                        "status": "NOT_APPLICABLE",
                        "anchors": [question_anchor],
                        "conclusion": "단위를 검증할 수치 물리량이 없습니다.",
                    }
                ],
                "choice_checks": [
                    {
                        "ordinal": 1,
                        "choice_key": "1",
                        "verdict": "CORRECT",
                        "question_anchors": [question_anchor],
                        "solution_anchors": [solution_anchor],
                        "rationale": "독립 풀이와 일치합니다.",
                    },
                    {
                        "ordinal": 2,
                        "choice_key": "2",
                        "verdict": "INCORRECT",
                        "question_anchors": [question_anchor],
                        "solution_anchors": [solution_anchor],
                        "rationale": "조건과 모순됩니다.",
                    },
                ],
                "explanation_steps": [
                    {
                        "ordinal": 1,
                        "status": "VERIFIED",
                        "claim_summary": "공식 해설의 핵심 단계",
                        "verification_summary": "독립 풀이와 논리적으로 일치합니다.",
                        "question_anchors": [question_anchor],
                        "solution_anchors": [solution_anchor],
                    }
                ],
                "evidence_status": "SUPPORTED",
                "evidence_citation_ids": list(evidence_ids),
                "conclusion": "정답·선지·해설과 Graph 근거가 일치합니다.",
            }
        ],
        "cross_document_checks": [
            {
                "check_id": "reviewcross_" + "e" * 32,
                "item_key": ITEM_KEY,
                "question_anchors": [question_anchor],
                "solution_anchors": [solution_anchor],
                "status": "MATCHED",
                "conclusion": "문제와 해설이 일치합니다.",
            }
        ],
        "evidence_usage": {
            "evidence_bundle_id": "evidence_" + "1" * 32,
            "evidence_bundle_revision_id": "evidencerev_" + "2" * 32,
            "retrieval_request_id": "retrieval_" + "3" * 32,
            "graph_snapshot_revision_id": "graphrev_" + "4" * 32,
            "manifest_sha256": "sha256:" + "5" * 64,
            "context_sha256": "sha256:" + "6" * 64,
            "citations": [
                {
                    "evidence_id": evidence_ids[0],
                    "anchor_ids": ["anchor_concept"],
                    "application": "CONCEPT_VERIFICATION",
                    "item_keys": [ITEM_KEY],
                    "review_json_paths": ["/item_reviews/0/solve_summary"],
                },
                {
                    "evidence_id": evidence_ids[1],
                    "anchor_ids": ["anchor_solution"],
                    "application": "SOLUTION_VERIFICATION",
                    "item_keys": [ITEM_KEY],
                    "review_json_paths": ["/item_reviews/0/final_answer"],
                },
                {
                    "evidence_id": evidence_ids[2],
                    "anchor_ids": ["anchor_originality"],
                    "application": "ORIGINALITY_COMPARISON",
                    "item_keys": [ITEM_KEY],
                    "review_json_paths": ["/item_reviews/0/conclusion"],
                },
            ],
        },
        "mutation_performed": False,
    }


def _result() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "protocol_version": "workflow-role/1.27.0",
        "job_id": "job_" + "1" * 32,
        "workflow_id": "workflow_" + "2" * 32,
        "step_run_id": "steprun_" + "3" * 32,
        "status": "ok",
        "artifact": {
            "logical_artifact_id": "artifact_" + "4" * 32,
            "revision_id": "rev_" + "5" * 32,
            "file_name": "result.json",
            "media_type": "application/json",
        },
        "completed_at": datetime(2026, 9, 24, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "role": "support",
        "output": _output(),
    }


def test_document_review_v3_schema_and_pydantic_accept_exhaustive_result() -> None:
    for file_name in (
        "paired-document-review-input-v3.schema.json",
        "paired-document-review-result-v3.schema.json",
    ):
        canonical = ROOT / "schemas/workflow/roles" / file_name
        packaged = ROOT / "packages/workflow/eom_workflow/resources/roles" / file_name
        assert canonical.read_bytes() == packaged.read_bytes()
        Draft202012Validator.check_schema(json.loads(canonical.read_text(encoding="utf-8")))
    parsed = validate_role_result(_result(), "support", "pdf-document-review-result@3.0")
    assert parsed.output.review_status == "COMPLETE"
    assert len(parsed.output.verification_targets) == 10
    assert len(parsed.output.item_reviews) == 1


@pytest.mark.parametrize("missing_axis", ["EDITORIAL_CLARITY", "TYPOGRAPHY"])
def test_document_review_v3_requires_each_editorial_axis(missing_axis: str) -> None:
    value = _result()
    output = value["output"]
    assert isinstance(output, dict)
    targets = output["verification_targets"]
    assert isinstance(targets, list)
    output["verification_targets"] = [
        target for target in targets if target["axis"] != missing_axis
    ]
    with pytest.raises((JsonSchemaValidationError, ValidationError, ValueError)):
        validate_role_result(value, "support", "pdf-document-review-result@3.0")


def test_document_review_v3_originality_insufficient_blocks_complete() -> None:
    value = _output()
    targets = value["verification_targets"]
    assert isinstance(targets, list)
    next(target for target in targets if target["axis"] == "ORIGINALITY")["status"] = "INSUFFICIENT"
    with pytest.raises(ValidationError, match="exhaustive verification evidence"):
        PairedDocumentReviewOutputV3.model_validate(value)
    value["review_status"] = "NEEDS_HUMAN_DECISION"
    assert PairedDocumentReviewOutputV3.model_validate(value).review_status == (
        "NEEDS_HUMAN_DECISION"
    )


@pytest.mark.parametrize(
    "field",
    ["solve_summary", "solve_steps", "unit_checks", "choice_checks", "explanation_steps"],
)
def test_document_review_v3_structurally_requires_item_verification(field: str) -> None:
    value = _result()
    output = value["output"]
    assert isinstance(output, dict)
    items = output["item_reviews"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    if field == "solve_summary":
        item.pop(field)
    else:
        item[field] = []
    schema = load_role_result_schema("pdf-document-review-result@3.0")
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(value)
    with pytest.raises((ValidationError, ValueError)):
        validate_role_result(value, "support", "pdf-document-review-result@3.0")


def test_document_review_v3_solve_steps_are_ordered_and_block_complete() -> None:
    value = copy.deepcopy(_output())
    items = value["item_reviews"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    solve_steps = item["solve_steps"]
    assert isinstance(solve_steps, list)
    solve_steps.append({**solve_steps[0], "ordinal": 3})
    with pytest.raises(ValidationError, match="solve steps must be contiguous"):
        PairedDocumentReviewOutputV3.model_validate(value)

    value = copy.deepcopy(_output())
    items = value["item_reviews"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    solve_steps = item["solve_steps"]
    assert isinstance(solve_steps, list)
    solve_steps[0]["status"] = "INSUFFICIENT"
    with pytest.raises(ValidationError, match="exhaustive verification evidence"):
        PairedDocumentReviewOutputV3.model_validate(value)


def test_document_review_v3_rejects_evidence_path_or_item_drift() -> None:
    value = copy.deepcopy(_output())
    usage = value["evidence_usage"]
    assert isinstance(usage, dict)
    citations = usage["citations"]
    assert isinstance(citations, list)
    citations[0]["review_json_paths"] = ["/summary"]
    with pytest.raises(ValidationError, match="declared review item"):
        PairedDocumentReviewOutputV3.model_validate(value)

    value = copy.deepcopy(_output())
    usage = value["evidence_usage"]
    assert isinstance(usage, dict)
    citations = usage["citations"]
    assert isinstance(citations, list)
    citations[1]["review_json_paths"] = ["/item_reviews/0/solve_summary"]
    with pytest.raises(ValidationError, match="declared review item application"):
        PairedDocumentReviewOutputV3.model_validate(value)
