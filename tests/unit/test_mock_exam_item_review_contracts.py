from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts.item_review import (
    MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_PUBLICATION_COMMAND_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_SCHEMA,
    MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA,
    MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA,
    InspectMockExamReviewEligibilityQuery,
    MockExamEligibilityFinding,
    MockExamEligibilityFindingCounts,
    MockExamItemReviewDecisionV1,
    MockExamItemReviewPublicationResult,
    MockExamReviewEligibilityResult,
    PublishMockExamItemReviewCommand,
    mock_exam_item_review_decision_sha256,
)
from eom_catalog_contracts.validation import validate_contract
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SHA = "sha256:" + "a" * 64


def _id(prefix: str, digit: str) -> str:
    return prefix + digit * 32


def _decision_value() -> dict[str, Any]:
    decided_at = datetime(2026, 9, 8, 3, 15, tzinfo=UTC)
    unsigned: dict[str, Any] = {
        "schema_version": "mock-exam-item-review-decision/1.0",
        "item_review_record_id": _id("itemreview_", "1"),
        "item_revision_id": _id("itemrev_", "2"),
        "workflow_id": _id("workflow_", "3"),
        "source_review": {
            "step_run_id": _id("steprun_", "4"),
            "artifact_id": _id("artifact_", "5"),
            "artifact_revision_id": _id("rev_", "6"),
            "sha256": "sha256:" + "7" * 64,
            "result_schema": "review-result@7.0",
            "worker_decision": "ready_for_human",
            "finding_counts": {"info": 1, "warning": 2, "blocking": 0},
        },
        "human_approval": {
            "approval_request_id": _id("approval_", "8"),
            "reviewer_operator_id": _id("operator_", "9"),
            "approved_at": decided_at.isoformat().replace("+00:00", "Z"),
        },
        "decision": "APPROVE",
        "final_rating": "A",
        "rating_policy_key": "integrated-science-item-rating",
        "rating_policy_revision_id": _id("ratingpolicyrev_", "a"),
        "rating_policy_sha256": "sha256:" + "b" * 64,
        "idempotency_key_sha256": "sha256:" + "c" * 64,
        "decided_at": decided_at.isoformat().replace("+00:00", "Z"),
    }
    return {**unsigned, "decision_sha256": mock_exam_item_review_decision_sha256(unsigned)}


def test_item_review_schemas_are_draft_2020_12_and_packaged_byte_identically() -> None:
    for file_name in (
        "mock-exam-item-review-publication-command-v1.schema.json",
        "mock-exam-item-review-publication-result-v1.schema.json",
        "mock-exam-item-review-decision-v1.schema.json",
        "mock-exam-review-eligibility-query-v1.schema.json",
        "mock-exam-review-eligibility-result-v1.schema.json",
    ):
        canonical = ROOT / "schemas/assessment-assembly" / file_name
        packaged = (
            ROOT
            / "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly"
            / file_name
        )
        assert canonical.read_bytes() == packaged.read_bytes()
        schema = json.loads(canonical.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_publication_command_requires_the_private_catalog_operation() -> None:
    command = PublishMockExamItemReviewCommand(
        item_revision_id=_id("itemrev_", "1"),
        expected_workflow_id=_id("workflow_", "4"),
        final_rating="B",
        reviewer_operator_id=_id("operator_", "2"),
        rating_policy_revision_id=_id("ratingpolicyrev_", "3"),
        rating_policy_sha256=SHA,
        idempotency_key="review-2026-09-08-001",
    )
    value = command.model_dump(mode="json")
    validate_contract(MOCK_EXAM_ITEM_REVIEW_PUBLICATION_COMMAND_SCHEMA, value)
    assert value["operation"] == "PUBLISH_MOCK_EXAM_ITEM_REVIEW"
    assert value["expected_workflow_id"] == _id("workflow_", "4")

    with pytest.raises(ValidationError):
        PublishMockExamItemReviewCommand.model_validate(
            {**value, "idempotency_key": "bad\nkey!"}
        )


def test_preapproval_eligibility_contract_exposes_review_content_and_stable_reason() -> None:
    query = InspectMockExamReviewEligibilityQuery(workflow_id=_id("workflow_", "1"))
    validate_contract(
        MOCK_EXAM_REVIEW_ELIGIBILITY_QUERY_SCHEMA,
        query.model_dump(mode="json"),
    )
    result = MockExamReviewEligibilityResult(
        workflow_id=query.workflow_id,
        workflow_lock_version=7,
        approval_state="PENDING",
        approval_request_id=_id("approval_", "2"),
        approval_lock_version=3,
        reviewer_operator_id=None,
        approved_at=None,
        review_step_run_id=_id("steprun_", "3"),
        review_artifact_id=_id("artifact_", "4"),
        review_artifact_revision_id=_id("rev_", "5"),
        review_sha256="sha256:" + "6" * 64,
        review_result_schema="review-result@8.0",
        review_summary="검토 결과를 운영자가 승인 전에 확인할 수 있다.",
        findings=(
            MockExamEligibilityFinding(
                code="STYLE_WARNING",
                severity="warning",
                message="표현을 확인한다.",
            ),
        ),
        finding_counts=MockExamEligibilityFindingCounts(
            info=0,
            warning=1,
            blocking=0,
        ),
        eligible=True,
        eligibility_reason="ELIGIBLE",
    )
    validate_contract(
        MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA,
        result.model_dump(mode="json"),
    )
    assert result.operation == "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY"

    with pytest.raises(ValidationError, match="reason differs"):
        MockExamReviewEligibilityResult.model_validate(
            {**result.model_dump(mode="json"), "eligible": False}
        )


def test_postapproval_eligibility_requires_atomic_reviewer_and_time() -> None:
    pending = MockExamReviewEligibilityResult(
        workflow_id=_id("workflow_", "1"),
        workflow_lock_version=8,
        approval_state="PENDING",
        approval_request_id=_id("approval_", "2"),
        approval_lock_version=1,
        reviewer_operator_id=None,
        approved_at=None,
        review_step_run_id=_id("steprun_", "3"),
        review_artifact_id=_id("artifact_", "4"),
        review_artifact_revision_id=_id("rev_", "5"),
        review_sha256="sha256:" + "6" * 64,
        review_result_schema="review-result@8.0",
        review_summary="동일한 검토 근거를 승인 전후에 조회한다.",
        findings=(),
        finding_counts=MockExamEligibilityFindingCounts(
            info=0,
            warning=0,
            blocking=0,
        ),
        eligible=True,
        eligibility_reason="ELIGIBLE",
    )
    approved = MockExamReviewEligibilityResult.model_validate(
        {
            **pending.model_dump(mode="json"),
            "approval_state": "APPROVED",
            "approval_lock_version": 2,
            "reviewer_operator_id": _id("operator_", "7"),
            "approved_at": "2026-09-08T05:00:00Z",
        }
    )
    validate_contract(
        MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_SCHEMA,
        approved.model_dump(mode="json"),
    )

    for mutation in (
        {"approval_state": "APPROVED", "reviewer_operator_id": None},
        {"approval_state": "PENDING", "approved_at": "2026-09-08T05:00:00Z"},
    ):
        with pytest.raises(ValidationError, match="must be atomic"):
            MockExamReviewEligibilityResult.model_validate(
                {**approved.model_dump(mode="json"), **mutation}
            )


def test_decision_self_hash_binds_rating_policy_reviewer_and_source_evidence() -> None:
    value = _decision_value()
    decision = MockExamItemReviewDecisionV1.model_validate(value)
    validate_contract(MOCK_EXAM_ITEM_REVIEW_DECISION_SCHEMA, decision.model_dump(mode="json"))

    for mutation in (
        {"final_rating": "C"},
        {"rating_policy_sha256": "sha256:" + "d" * 64},
        {
            "human_approval": {
                **value["human_approval"],
                "reviewer_operator_id": _id("operator_", "e"),
            }
        },
        {
            "source_review": {
                **value["source_review"],
                "sha256": "sha256:" + "f" * 64,
            }
        },
    ):
        with pytest.raises(ValidationError, match="self-hash mismatch"):
            MockExamItemReviewDecisionV1.model_validate({**value, **mutation})


def test_publication_result_is_a_schema_valid_decision_artifact_receipt() -> None:
    decision = MockExamItemReviewDecisionV1.model_validate(_decision_value())
    result = MockExamItemReviewPublicationResult(
        item_review_record_id=decision.item_review_record_id,
        item_revision_id=decision.item_revision_id,
        workflow_id=decision.workflow_id,
        review_step_run_id=decision.source_review.step_run_id,
        human_approval_request_id=decision.human_approval.approval_request_id,
        review_artifact_id=_id("artifact_", "d"),
        review_artifact_revision_id=_id("rev_", "e"),
        review_sha256="sha256:" + "f" * 64,
        decision_sha256=decision.decision_sha256,
        review_result_schema=decision.source_review.result_schema,
        final_rating=decision.final_rating,
        finding_counts=decision.source_review.finding_counts,
        reviewer_operator_id=decision.human_approval.reviewer_operator_id,
        rating_policy_revision_id=decision.rating_policy_revision_id,
        rating_policy_sha256=decision.rating_policy_sha256,
        created=True,
    )
    value = result.model_dump(mode="json")
    validate_contract(MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_SCHEMA, value)
    assert value["operation"] == "PUBLISH_MOCK_EXAM_ITEM_REVIEW"
