from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from eom_api_contracts.mock_exam_execution import (
    MockExamGenerationBlockResolutionV3,
    MockExamProductionExecution,
    MockExamProductionExecutionV3,
    MockExamProductionItemRunV3,
    MockExamReviewEligibilityObservationV3,
    MockExamReviewPointerV3,
    MockExamWorkflowKnowledgeProvenancePointerV1,
)
from eom_catalog_contracts.application import CatalogApplicationResponse
from eom_catalog_contracts.assessment_assembly import (
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
)
from eom_catalog_contracts.curriculum import load_integrated_science_editorial_outline
from eom_catalog_contracts.item_review import (
    MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA,
    MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_V3_SCHEMA,
    MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA,
    MockExamAuthoringEvidenceUsageReceiptPointerV1,
    MockExamEligibilityFindingCounts,
    MockExamHumanApprovalPointer,
    MockExamItemReviewDecisionV3,
    MockExamItemReviewPublicationResultContract,
    MockExamItemReviewPublicationResultV3,
    MockExamReviewEligibilityResultContract,
    MockExamReviewEligibilityResultV3,
    MockExamReviewEvidenceUsageReceiptPointerV1,
    MockExamReviewFindingCountsV3,
    MockExamSourceReviewPointerV3,
    MockExamTrustedEvidenceUsageReceiptPairV1,
    mock_exam_item_review_decision_sha256,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V3,
    CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V3,
    CONTENT_TEAM_ROLE_SCHEMA_BUNDLE_SHA256_V3,
    MockExamOneItemGenerationBlockV3,
    MockExamPlannedWorkflowCallV3,
    MockExamProductionPlanContract,
    MockExamProductionPlanV3,
    build_integrated_science_mock_exam_production_plan_v2,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 10, 4, 5, 6, tzinfo=UTC)


def _id(prefix: str, value: int) -> str:
    return prefix + f"{value:032x}"


def _sha(value: int) -> str:
    return "sha256:" + f"{value:064x}"


def _receipt_pair(
    *,
    workflow_id: str | None = None,
    seed: int = 1,
) -> MockExamTrustedEvidenceUsageReceiptPairV1:
    workflow_id = workflow_id or _id("workflow_", seed)
    return MockExamTrustedEvidenceUsageReceiptPairV1(
        schema_version="mock-exam-trusted-evidence-usage-receipt-pair/1.0",
        role_protocol_version="workflow-role/1.20.0",
        receipt_schema_version="evidence-usage-validation-receipt/1.0",
        authoring=MockExamAuthoringEvidenceUsageReceiptPointerV1(
            workflow_id=workflow_id,
            step_run_id=_id("steprun_", seed * 100 + 1),
            attempt=1,
            job_id=_id("job_", seed * 100 + 2),
            artifact_id=_id("artifact_", seed * 100 + 3),
            artifact_revision_id=_id("rev_", seed * 100 + 4),
            sha256=_sha(seed * 100 + 5),
            receipt_sha256=_sha(seed * 100 + 6),
            step_key="authoring",
            result_schema="authoring-result@10.0",
        ),
        review=MockExamReviewEvidenceUsageReceiptPointerV1(
            workflow_id=workflow_id,
            step_run_id=_id("steprun_", seed * 100 + 11),
            attempt=1,
            job_id=_id("job_", seed * 100 + 12),
            artifact_id=_id("artifact_", seed * 100 + 13),
            artifact_revision_id=_id("rev_", seed * 100 + 14),
            sha256=_sha(seed * 100 + 15),
            receipt_sha256=_sha(seed * 100 + 16),
            step_key="review",
            result_schema="review-result@10.0",
        ),
    )


def _generation_block() -> MockExamOneItemGenerationBlockV3:
    return MockExamOneItemGenerationBlockV3(
        block_key="content-team-one-item-generation",
        block_revision="3.0",
        workflow_definition_key="generic-item-development",
        workflow_definition_version="1.10.0",
        request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST",
        image_mode="required",
        content_pack_key="generated-knowledge-item",
        content_pack_version="1.15.1",
        content_pack_source_tree_sha256=CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V3,
        execution_preset_key="knowledge-grounded-item",
        registry_mode="CREATE_ITEM",
        role_protocol_version="workflow-role/1.20.0",
        role_schema_bundle_sha256=CONTENT_TEAM_ROLE_SCHEMA_BUNDLE_SHA256_V3,
        knowledge_source_mode="graph_grounded",
        authoring_result_schema="authoring-result@10.0",
        review_result_schema="review-result@10.0",
        evidence_usage_receipt_schema_version="evidence-usage-validation-receipt/1.0",
        trusted_evidence_usage_receipts_required=True,
        block_sha256=CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V3,
    )


def _plan() -> MockExamProductionPlanV3:
    predecessor = build_integrated_science_mock_exam_production_plan_v2(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    block = _generation_block()
    calls: list[MockExamPlannedWorkflowCallV3] = []
    for predecessor_call in predecessor.workflow_calls:
        call_body: dict[str, object] = {
            "generation_block_key": block.block_key,
            "generation_block_revision": block.block_revision,
            "generation_block_sha256": block.block_sha256,
            "item_brief": predecessor_call.item_brief.model_dump(mode="json"),
        }
        call_sha256 = content_sha256(call_body)
        calls.append(
            MockExamPlannedWorkflowCallV3.model_validate(
                {
                    **call_body,
                    "workflow_call_id": (
                        "workflowcall_" + call_sha256.removeprefix("sha256:")[:32]
                    ),
                }
            )
        )
    plan_body = predecessor.model_dump(
        mode="json",
        exclude={"production_plan_id", "plan_sha256"},
    )
    plan_body.update(
        {
            "schema_version": "mock-exam-production-plan/3.0",
            "one_item_generation_block": block.model_dump(mode="json"),
            "workflow_calls": [call.model_dump(mode="json") for call in calls],
        }
    )
    plan_sha256 = content_sha256(plan_body)
    return MockExamProductionPlanV3.model_validate(
        {
            **plan_body,
            "production_plan_id": ("productionplan_" + plan_sha256.removeprefix("sha256:")[:32]),
            "plan_sha256": plan_sha256,
        }
    )


def _catalog_eligibility(
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamReviewEligibilityResultV3:
    review = receipts.review
    return MockExamReviewEligibilityResultV3(
        schema_version="mock-exam-review-eligibility-result/3.0",
        operation="INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY",
        workflow_id=review.workflow_id,
        workflow_lock_version=3,
        approval_state="PENDING",
        approval_request_id=_id("approval_", 51),
        approval_lock_version=2,
        reviewer_operator_id=None,
        approved_at=None,
        review_step_run_id=review.step_run_id,
        review_artifact_id=review.artifact_id,
        review_artifact_revision_id=review.artifact_revision_id,
        review_sha256=review.sha256,
        review_result_schema="review-result@10.0",
        decision="ready_for_human",
        review_summary="검증된 근거 사용 영수증과 함께 운영자 검토가 가능하다.",
        findings=(),
        finding_counts=MockExamEligibilityFindingCounts(info=0, warning=0, blocking=0),
        eligible=True,
        eligibility_reason="ELIGIBLE",
        trusted_evidence_usage_receipts=receipts,
    )


def _api_eligibility(
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamReviewEligibilityObservationV3:
    review = receipts.review
    return MockExamReviewEligibilityObservationV3(
        schema_version="mock-exam-review-eligibility/3.0",
        workflow_id=review.workflow_id,
        workflow_resource_version=3,
        approval_request_id=_id("approval_", 51),
        approval_resource_version=2,
        approval_state="PENDING",
        reviewer_operator_id=None,
        approved_at=None,
        eligibility="ELIGIBLE",
        step_run_id=review.step_run_id,
        artifact_id=review.artifact_id,
        artifact_revision_id=review.artifact_revision_id,
        sha256=review.sha256,
        result_schema="review-result@10.0",
        worker_decision="ready_for_human",
        finding_info_count=0,
        finding_warning_count=0,
        finding_blocking_count=0,
        trusted_evidence_usage_receipts=receipts,
    )


def _source_review(
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamSourceReviewPointerV3:
    review = receipts.review
    return MockExamSourceReviewPointerV3(
        step_run_id=review.step_run_id,
        artifact_id=review.artifact_id,
        artifact_revision_id=review.artifact_revision_id,
        sha256=review.sha256,
        result_schema="review-result@10.0",
        worker_decision="ready_for_human",
        finding_counts=MockExamReviewFindingCountsV3(info=0, warning=0, blocking=0),
        trusted_evidence_usage_receipts=receipts,
    )


def _decision(
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamItemReviewDecisionV3:
    unsigned: dict[str, Any] = {
        "schema_version": "mock-exam-item-review-decision/3.0",
        "item_review_record_id": _id("itemreview_", 61),
        "item_revision_id": _id("itemrev_", 62),
        "workflow_id": receipts.review.workflow_id,
        "source_review": _source_review(receipts).model_dump(mode="json"),
        "human_approval": MockExamHumanApprovalPointer(
            approval_request_id=_id("approval_", 51),
            reviewer_operator_id=_id("operator_", 63),
            approved_at=NOW,
        ).model_dump(mode="json"),
        "decision": "APPROVE",
        "final_rating": "A",
        "rating_policy_key": "integrated-science-item-rating",
        "rating_policy_revision_id": _id("ratingpolicyrev_", 64),
        "rating_policy_sha256": _sha(65),
        "idempotency_key_sha256": _sha(66),
        "decided_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    return MockExamItemReviewDecisionV3.model_validate(
        {**unsigned, "decision_sha256": mock_exam_item_review_decision_sha256(unsigned)}
    )


def _publication(
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamItemReviewPublicationResultV3:
    decision = _decision(receipts)
    review = receipts.review
    return MockExamItemReviewPublicationResultV3(
        schema_version="mock-exam-item-review-publication-result/3.0",
        operation="PUBLISH_MOCK_EXAM_ITEM_REVIEW",
        item_review_record_id=decision.item_review_record_id,
        item_revision_id=decision.item_revision_id,
        workflow_id=decision.workflow_id,
        review_step_run_id=review.step_run_id,
        human_approval_request_id=decision.human_approval.approval_request_id,
        review_artifact_id=_id("artifact_", 71),
        review_artifact_revision_id=_id("rev_", 72),
        review_sha256=_sha(73),
        decision_sha256=decision.decision_sha256,
        review_result_schema="review-result@10.0",
        decision="APPROVE",
        final_rating=decision.final_rating,
        finding_counts=MockExamReviewFindingCountsV3(info=0, warning=0, blocking=0),
        reviewer_operator_id=decision.human_approval.reviewer_operator_id,
        rating_policy_revision_id=decision.rating_policy_revision_id,
        rating_policy_sha256=decision.rating_policy_sha256,
        created=True,
        source_review_artifact_id=review.artifact_id,
        source_review_artifact_revision_id=review.artifact_revision_id,
        source_review_sha256=review.sha256,
        trusted_evidence_usage_receipts=receipts,
    )


def _planned_item_run(call_id: str, position: int) -> MockExamProductionItemRunV3:
    return MockExamProductionItemRunV3(
        workflow_call_id=call_id,
        position=position,
        state="PLANNED",
        start_command_id=None,
        workflow_id=None,
        workflow_resource_version=None,
        knowledge_provenance=None,
        review=None,
        approval_command_id=None,
        human_approval=None,
        registration=None,
        analysis=None,
        graph_publication_id=None,
        rating=None,
        failure=None,
    )


def _initial_execution(plan: MockExamProductionPlanV3) -> MockExamProductionExecutionV3:
    production_request_id = _id("productionreq_", 81)
    execution_sha256 = content_sha256(
        {
            "production_request_id": production_request_id,
            "production_plan_id": plan.production_plan_id,
            "production_plan_sha256": plan.plan_sha256,
        }
    )
    execution_id = "productionexec_" + execution_sha256.removeprefix("sha256:")[:32]
    value: dict[str, Any] = {
        "schema_version": "mock-exam-production-execution/3.0",
        "execution_id": execution_id,
        "production_request_id": production_request_id,
        "production_plan_id": plan.production_plan_id,
        "production_plan_sha256": plan.plan_sha256,
        "operator_id": _id("operator_", 82),
        "checkpoint_sequence": 0,
        "predecessor_execution_revision_id": None,
        "predecessor_checkpoint_sha256": None,
        "state": "ITEM_PRODUCTION",
        "generation_block_resolution": None,
        "analysis_policy": None,
        "analysis_general_knowledge_mode": None,
        "analysis_review_authorizations": [],
        "item_runs": [
            _planned_item_run(call.workflow_call_id, position).model_dump(mode="json")
            for position, call in enumerate(plan.workflow_calls, start=1)
        ],
        "graph_publication_authorization": None,
        "graph_publications": [],
        "rating_authorization": None,
        "assembly_intent": None,
        "assembly_plan": None,
        "assembly": None,
        "hwpx_build": None,
        "failure": None,
        "created_at": NOW.isoformat().replace("+00:00", "Z"),
        "checkpointed_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    checkpoint_sha256 = content_sha256(value)
    return MockExamProductionExecutionV3.model_validate(
        {
            **value,
            "execution_revision_id": (
                "productionexecrev_" + checkpoint_sha256.removeprefix("sha256:")[:32]
            ),
            "checkpoint_sha256": checkpoint_sha256,
        }
    )


def _schema(path: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((ROOT / path).read_text(encoding="utf-8")))


def test_v3_schemas_are_2020_12_and_package_mirrors_are_byte_exact() -> None:
    pairs = (
        (
            "schemas/assessment-assembly/mock-exam-production-plan-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-production-plan-v3.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-review-eligibility-result-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-review-eligibility-result-v3.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-item-review-decision-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-item-review-decision-v3.schema.json",
        ),
        (
            "schemas/assessment-assembly/mock-exam-item-review-publication-result-v3.schema.json",
            "packages/catalog_contracts/eom_catalog_contracts/resources/assessment-assembly/"
            "mock-exam-item-review-publication-result-v3.schema.json",
        ),
        (
            "schemas/api/v1/mock-exam-production-execution-v3.schema.json",
            "packages/api_contracts/eom_api_contracts/schemas/"
            "mock-exam-production-execution-v3.schema.json",
        ),
        (
            "schemas/api/v1/mock-exam-review-eligibility-v3.schema.json",
            "packages/api_contracts/eom_api_contracts/schemas/"
            "mock-exam-review-eligibility-v3.schema.json",
        ),
    )
    for canonical_name, package_name in pairs:
        canonical = ROOT / canonical_name
        package = ROOT / package_name
        assert canonical.read_bytes() == package.read_bytes()
        schema = json.loads(canonical.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["properties"]["schema_version"]["const"].endswith("/3.0")
        Draft202012Validator.check_schema(schema)


def test_v3_models_and_schemas_require_the_same_closed_wire_fields() -> None:
    models_and_schemas: tuple[tuple[type[BaseModel], str], ...] = (
        (
            MockExamProductionPlanV3,
            "schemas/assessment-assembly/mock-exam-production-plan-v3.schema.json",
        ),
        (
            MockExamReviewEligibilityResultV3,
            "schemas/assessment-assembly/mock-exam-review-eligibility-result-v3.schema.json",
        ),
        (
            MockExamItemReviewDecisionV3,
            "schemas/assessment-assembly/mock-exam-item-review-decision-v3.schema.json",
        ),
        (
            MockExamItemReviewPublicationResultV3,
            "schemas/assessment-assembly/mock-exam-item-review-publication-result-v3.schema.json",
        ),
        (
            MockExamProductionExecutionV3,
            "schemas/api/v1/mock-exam-production-execution-v3.schema.json",
        ),
        (
            MockExamReviewEligibilityObservationV3,
            "schemas/api/v1/mock-exam-review-eligibility-v3.schema.json",
        ),
    )
    for model, schema_name in models_and_schemas:
        generated = model.model_json_schema(mode="validation")
        canonical = _schema(schema_name)
        for document in (generated, canonical):
            objects = (document, *document.get("$defs", {}).values())
            for value in objects:
                properties = value.get("properties")
                if properties is None:
                    continue
                assert value.get("additionalProperties") is False
                assert set(value.get("required", ())) == set(properties)


def test_v3_standalone_contracts_do_not_widen_active_v1_v2_dispatch() -> None:
    plan = _plan()
    execution = _initial_execution(plan)
    receipts = _receipt_pair()
    eligibility = _catalog_eligibility(receipts)
    publication = _publication(receipts)

    rejected: tuple[tuple[object, dict[str, Any]], ...] = (
        (MockExamProductionPlanContract, plan.model_dump(mode="json")),
        (MockExamProductionExecution, execution.model_dump(mode="json")),
        (MockExamReviewEligibilityResultContract, eligibility.model_dump(mode="json")),
        (MockExamItemReviewPublicationResultContract, publication.model_dump(mode="json")),
    )
    for contract, value in rejected:
        with pytest.raises(PydanticValidationError):
            TypeAdapter(contract).validate_python(value)

    with pytest.raises(PydanticValidationError):
        CatalogApplicationResponse.model_validate(
            {
                "status": "OK",
                "operation": "INSPECT_MOCK_EXAM_REVIEW_ELIGIBILITY",
                "review_eligibility": eligibility.model_dump(mode="json"),
            }
        )


def test_v3_plan_pins_exact_workflow_role_pack_and_receipt_policy() -> None:
    plan = _plan()
    block = plan.one_item_generation_block
    assert len(plan.workflow_calls) == 25
    assert (
        block.workflow_definition_version,
        block.role_protocol_version,
        block.content_pack_version,
        block.content_pack_source_tree_sha256,
        block.role_schema_bundle_sha256,
        block.authoring_result_schema,
        block.review_result_schema,
        block.evidence_usage_receipt_schema_version,
        block.trusted_evidence_usage_receipts_required,
    ) == (
        "1.10.0",
        "workflow-role/1.20.0",
        "1.15.1",
        CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V3,
        CONTENT_TEAM_ROLE_SCHEMA_BUNDLE_SHA256_V3,
        "authoring-result@10.0",
        "review-result@10.0",
        "evidence-usage-validation-receipt/1.0",
        True,
    )
    assert (
        content_sha256(block.model_dump(mode="json", exclude={"block_sha256"}))
        == CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V3
    )
    validate_contract("mock-exam-production-plan-v3", plan.model_dump(mode="json"))

    invalid = plan.model_dump(mode="json")
    invalid["one_item_generation_block"]["workflow_definition_version"] = "1.9.0"
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("mock-exam-production-plan-v3", invalid)
    with pytest.raises(PydanticValidationError):
        MockExamProductionPlanV3.model_validate(invalid)


def test_v3_receipt_identity_fields_are_required_by_schema_and_pydantic() -> None:
    receipts = _receipt_pair()
    result = _catalog_eligibility(receipts)
    value = result.model_dump(mode="json")
    validate_contract(MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA, value)

    missing_attempt = deepcopy(value)
    del missing_attempt["trusted_evidence_usage_receipts"]["authoring"]["attempt"]
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA, missing_attempt)
    with pytest.raises(PydanticValidationError):
        MockExamReviewEligibilityResultV3.model_validate(missing_attempt)

    missing_protocol = deepcopy(value)
    del missing_protocol["trusted_evidence_usage_receipts"]["role_protocol_version"]
    with pytest.raises(JsonSchemaValidationError):
        validate_contract(MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA, missing_protocol)
    with pytest.raises(PydanticValidationError):
        MockExamReviewEligibilityResultV3.model_validate(missing_protocol)


@pytest.mark.parametrize(
    "field_name",
    ("step_run_id", "job_id", "artifact_id", "artifact_revision_id", "receipt_sha256"),
)
def test_v3_receipt_pair_rejects_duplicate_authoring_review_identity(
    field_name: str,
) -> None:
    value = _receipt_pair().model_dump(mode="json")
    value["review"][field_name] = value["authoring"][field_name]

    with pytest.raises(PydanticValidationError, match="receipt identities must be distinct"):
        MockExamTrustedEvidenceUsageReceiptPairV1.model_validate(value)


def test_v3_review_contracts_keep_source_review_and_decision_artifacts_distinct() -> None:
    receipts = _receipt_pair()
    eligibility = _catalog_eligibility(receipts)
    decision = _decision(receipts)
    publication = _publication(receipts)
    validate_contract(
        MOCK_EXAM_REVIEW_ELIGIBILITY_RESULT_V3_SCHEMA,
        eligibility.model_dump(mode="json"),
    )
    validate_contract(
        MOCK_EXAM_ITEM_REVIEW_DECISION_V3_SCHEMA,
        decision.model_dump(mode="json"),
    )
    validate_contract(
        MOCK_EXAM_ITEM_REVIEW_PUBLICATION_RESULT_V3_SCHEMA,
        publication.model_dump(mode="json"),
    )
    assert publication.review_artifact_id != publication.source_review_artifact_id
    assert publication.review_artifact_revision_id != publication.source_review_artifact_revision_id
    assert publication.review_sha256 != publication.source_review_sha256
    assert publication.source_review_artifact_id == receipts.review.artifact_id
    assert publication.source_review_artifact_revision_id == receipts.review.artifact_revision_id
    assert publication.source_review_sha256 == receipts.review.sha256

    stale = publication.model_dump(mode="json")
    stale["source_review_artifact_revision_id"] = _id("rev_", 999)
    with pytest.raises(PydanticValidationError, match="differs from publication review"):
        MockExamItemReviewPublicationResultV3.model_validate(stale)


def test_api_v3_eligibility_and_initial_execution_validate_against_schemas() -> None:
    receipts = _receipt_pair()
    observation = _api_eligibility(receipts)
    observation_schema = _schema("schemas/api/v1/mock-exam-review-eligibility-v3.schema.json")
    Draft202012Validator(
        observation_schema,
        format_checker=FormatChecker(),
    ).validate(observation.model_dump(mode="json"))
    approved_value = observation.model_dump(mode="json") | {
        "approval_state": "APPROVED",
        "reviewer_operator_id": _id("operator_", 901),
        "approved_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    approved = MockExamReviewEligibilityObservationV3.model_validate(approved_value)
    assert approved.approved_pointer().trusted_evidence_usage_receipts == receipts

    execution = _initial_execution(_plan())
    execution_schema = _schema("schemas/api/v1/mock-exam-production-execution-v3.schema.json")
    Draft202012Validator(
        execution_schema,
        format_checker=FormatChecker(),
    ).validate(execution.model_dump(mode="json"))
    assert execution.state == "ITEM_PRODUCTION"
    assert execution.generation_block_resolution is None


def test_v3_api_models_and_schemas_reject_unprefixed_hashes() -> None:
    resolution_value = {
        "generation_block_key": "content-team-one-item-generation",
        "generation_block_revision": "3.0",
        "generation_block_sha256": CONTENT_TEAM_ONE_ITEM_BLOCK_SHA256_V3,
        "workflow_definition_key": "generic-item-development",
        "workflow_definition_version": "1.10.0",
        "workflow_definition_sha256": _sha(1).removeprefix("sha256:"),
        "content_pack_release_id": _id("packrel_", 2),
        "content_pack_key": "generated-knowledge-item",
        "content_pack_version": "1.15.1",
        "content_pack_release_sha256": _sha(3),
        "content_pack_source_tree_sha256": CONTENT_TEAM_ONE_ITEM_PACK_SOURCE_TREE_SHA256_V3,
        "execution_preset_id": _id("execpreset_", 4),
        "execution_preset_revision_id": _id("execpresetrev_", 5),
        "execution_preset_key": "knowledge-grounded-item",
        "execution_preset_sha256": _sha(6),
        "resolved_at": NOW.isoformat().replace("+00:00", "Z"),
        "role_protocol_version": "workflow-role/1.20.0",
        "role_schema_bundle_sha256": CONTENT_TEAM_ROLE_SCHEMA_BUNDLE_SHA256_V3,
        "knowledge_source_mode": "graph_grounded",
        "authoring_result_schema": "authoring-result@10.0",
        "review_result_schema": "review-result@10.0",
        "evidence_usage_receipt_schema_version": "evidence-usage-validation-receipt/1.0",
        "trusted_evidence_usage_receipts_required": True,
    }
    with pytest.raises(PydanticValidationError, match="sha256: prefix"):
        MockExamGenerationBlockResolutionV3.model_validate(resolution_value)

    for schema_name in (
        "schemas/api/v1/mock-exam-production-execution-v3.schema.json",
        "schemas/api/v1/mock-exam-review-eligibility-v3.schema.json",
    ):
        serialized = json.dumps(_schema(schema_name), sort_keys=True)
        assert r"^(?:sha256:)?[0-9a-f]{64}$" not in serialized
        assert r"^sha256:[0-9a-f]{64}$" in serialized


def test_v3_receipt_pair_and_plan_are_frozen() -> None:
    receipts = _receipt_pair()
    plan = _plan()
    with pytest.raises(PydanticValidationError):
        receipts.review.receipt_sha256 = _sha(999)
    with pytest.raises(PydanticValidationError):
        plan.one_item_generation_block.content_pack_version = "1.15.0"  # type: ignore[assignment]


def test_relevant_v1_v2_schema_bytes_remain_pinned() -> None:
    expected = {
        "schemas/assessment-assembly/mock-exam-production-plan-v1.schema.json": (
            "9f0cd769669d7394c59a8683f467bcc93a0846f6e6620a64d374f17802099f41"
        ),
        "schemas/assessment-assembly/mock-exam-production-plan-v2.schema.json": (
            "d3bddcbbb236cbfba595587ea373445224de9d02bfa2e975a7dd5010ca48483f"
        ),
        "schemas/api/v1/mock-exam-production-execution-v1.schema.json": (
            "aafa7465142ae1fec36082b2a167a21a099dcd7c3379ad4224be03bab235ab80"
        ),
        "schemas/api/v1/mock-exam-production-execution-v2.schema.json": (
            "4a2e14db2d429af67716c164a3758e23199ea88c1d22304cbb0be693f0eadc39"
        ),
        "schemas/api/v1/mock-exam-review-eligibility-v1.schema.json": (
            "1bf1e2299d838c526983880ce85a3fd38add3fc494edbdd2cffabaf194c366e0"
        ),
        "schemas/api/v1/mock-exam-review-eligibility-v2.schema.json": (
            "83e133895e08171849815326bea02e90a80f301481eb6fc738a4916e77ebea49"
        ),
        "schemas/assessment-assembly/mock-exam-review-eligibility-result-v1.schema.json": (
            "5d8ce21540dbda8f38cda3f008e3379646e06505c6435e95b16095f1a6e8f7c2"
        ),
        "schemas/assessment-assembly/mock-exam-review-eligibility-result-v2.schema.json": (
            "d1de598f3f8d754df44aff968199eb532eb0bb3ba0c00a72a04ac09a5f5e1557"
        ),
        "schemas/assessment-assembly/mock-exam-item-review-decision-v1.schema.json": (
            "5f0934dfb60d8daf03f32aee080ea0f75b5930553e7bc697a592954552e9fd80"
        ),
        "schemas/assessment-assembly/mock-exam-item-review-decision-v2.schema.json": (
            "7cb83fc19ce124f49bdd9829e3a846c318f85dfa6f3578d69594404fd414bf76"
        ),
        "schemas/assessment-assembly/mock-exam-item-review-publication-result-v1.schema.json": (
            "7c5925cea23b97b882ed12776c993db611fabac35b5056c41833f727eb989061"
        ),
        "schemas/assessment-assembly/mock-exam-item-review-publication-result-v2.schema.json": (
            "50dddba5c0167a0edb6993825d7ad62abb6c56bb6c707e2d103e7a2adedaa065"
        ),
    }
    assert {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in expected
    } == expected


def _knowledge_provenance(seed: int) -> MockExamWorkflowKnowledgeProvenancePointerV1:
    return MockExamWorkflowKnowledgeProvenancePointerV1(
        schema_version="workflow-knowledge-provenance/1.0",
        plan_id=_id("execplan_", seed * 100 + 1),
        plan_sha256=_sha(seed * 100 + 2),
        preset_revision_id=_id("execpresetrev_", seed * 100 + 3),
        corpus_key="integrated-science-textbooks",
        query_kind="ITEM_PREPARATION",
        curriculum_root_key="eom.is.middle.1-1",
        required_item_elements=("choice", "paragraph"),
        source_classes=("PAST_EXAM", "TEXTBOOK"),
        graph_snapshot_revision_id=_id("graphrev_", seed * 100 + 4),
        evidence_bundle_revision_id=_id("evidencerev_", seed * 100 + 5),
        retrieval_request_id=_id("retrieval_", seed * 100 + 6),
        retrieval_request_sha256=_sha(seed * 100 + 7),
        access_policy_revision_id=_id("accessrev_", seed * 100 + 8),
        access_policy_sha256=_sha(seed * 100 + 9),
        evidence_manifest_sha256=_sha(seed * 100 + 10),
        resolved_at=NOW,
    )


def _review_blocked_item_run(
    *,
    call_id: str,
    position: int,
    workflow_id: str,
    receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
) -> MockExamProductionItemRunV3:
    review = receipts.review
    return MockExamProductionItemRunV3.model_validate(
        {
            "workflow_call_id": call_id,
            "position": position,
            "state": "REVIEW_BLOCKED",
            "start_command_id": f"start-{position}",
            "workflow_id": workflow_id,
            "workflow_resource_version": 2,
            "knowledge_provenance": _knowledge_provenance(position).model_dump(mode="json"),
            "review": MockExamReviewPointerV3(
                approval_request_id=_id("approval_", 1000 + position),
                approval_resource_version=1,
                step_run_id=review.step_run_id,
                artifact_id=review.artifact_id,
                artifact_revision_id=review.artifact_revision_id,
                sha256=review.sha256,
                result_schema="review-result@10.0",
                finding_info_count=0,
                finding_warning_count=0,
                finding_blocking_count=0,
                trusted_evidence_usage_receipts=receipts,
            ).model_dump(mode="json"),
            "approval_command_id": None,
            "human_approval": None,
            "registration": None,
            "analysis": None,
            "graph_publication_id": None,
            "rating": None,
            "failure": {
                "stage": "REVIEW_GATE",
                "category": "QUALITY_GATE_FAILED",
                "code": "TRUSTED_RECEIPT_TEST_BLOCK",
                "retryable": False,
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
            },
        }
    )


def test_execution_rejects_receipt_identity_reuse_across_item_runs() -> None:
    plan = _plan()
    execution = _initial_execution(plan)
    value = execution.model_dump(mode="json")
    workflow_one = _id("workflow_", 2001)
    workflow_two = _id("workflow_", 2002)
    receipts_one = _receipt_pair(workflow_id=workflow_one, seed=31)
    receipts_two_value = receipts_one.model_dump(mode="json")
    receipts_two_value["authoring"]["workflow_id"] = workflow_two
    receipts_two_value["review"]["workflow_id"] = workflow_two
    receipts_two = MockExamTrustedEvidenceUsageReceiptPairV1.model_validate(receipts_two_value)
    value["item_runs"][0] = _review_blocked_item_run(
        call_id=plan.workflow_calls[0].workflow_call_id,
        position=1,
        workflow_id=workflow_one,
        receipts=receipts_one,
    ).model_dump(mode="json")
    value["item_runs"][1] = _review_blocked_item_run(
        call_id=plan.workflow_calls[1].workflow_call_id,
        position=2,
        workflow_id=workflow_two,
        receipts=receipts_two,
    ).model_dump(mode="json")
    block = _generation_block()
    value["generation_block_resolution"] = MockExamGenerationBlockResolutionV3(
        generation_block_key=block.block_key,
        generation_block_revision=block.block_revision,
        generation_block_sha256=block.block_sha256,
        workflow_definition_key=block.workflow_definition_key,
        workflow_definition_version=block.workflow_definition_version,
        workflow_definition_sha256=_sha(3001),
        content_pack_release_id=_id("packrel_", 3002),
        content_pack_key=block.content_pack_key,
        content_pack_version=block.content_pack_version,
        content_pack_release_sha256=_sha(3003),
        content_pack_source_tree_sha256=block.content_pack_source_tree_sha256,
        execution_preset_id=_id("execpreset_", 3004),
        execution_preset_revision_id=_id("execpresetrev_", 3005),
        execution_preset_key=block.execution_preset_key,
        execution_preset_sha256=_sha(3006),
        resolved_at=NOW,
        role_protocol_version=block.role_protocol_version,
        role_schema_bundle_sha256=block.role_schema_bundle_sha256,
        knowledge_source_mode=block.knowledge_source_mode,
        authoring_result_schema=block.authoring_result_schema,
        review_result_schema=block.review_result_schema,
        evidence_usage_receipt_schema_version=block.evidence_usage_receipt_schema_version,
        trusted_evidence_usage_receipts_required=True,
    ).model_dump(mode="json")
    value["state"] = "BLOCKED"
    value["checkpointed_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    value.pop("execution_revision_id")
    value.pop("checkpoint_sha256")
    checkpoint_sha256 = content_sha256(value)
    value["execution_revision_id"] = (
        "productionexecrev_" + checkpoint_sha256.removeprefix("sha256:")[:32]
    )
    value["checkpoint_sha256"] = checkpoint_sha256

    with pytest.raises(PydanticValidationError, match="duplicate receipt step run pointers"):
        MockExamProductionExecutionV3.model_validate(value)
