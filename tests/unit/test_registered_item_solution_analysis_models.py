"""AI and registered Items retain real accepted bases and the same public report logic."""

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceiptV10,
    KnowledgeAnalysisRequestV11,
    KnowledgeAnalysisResultV11,
    RegisteredItemSolutionBasePointer,
    validate_contract,
    validate_knowledge_solution_report_references,
)
from eom_catalog_contracts.knowledge import (
    KnowledgeAnalysisWorkerProposalV8,
    knowledge_solution_content_set_sha256,
)
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_identifiers import content_sha256
from pydantic import ValidationError

from tests.unit.test_past_exam_solution_analysis_contracts import (
    _role_result_value,
)
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value


def receipt_value():
    request = request_value()
    pointer = deepcopy(request["base_analysis"]["base_members"]["nodes"])
    pointer.update(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id="rev_" + "c" * 32,
        member_path="normalized/solution-report.json",
        logical_name="solution-report.json",
        schema_ref="eom://schemas/knowledge/knowledge-analysis-solution-report/1.0",
        media_type="application/json",
    )
    base = RegisteredItemSolutionBasePointer.model_validate(request["base_analysis"])
    from eom_catalog_contracts.knowledge import KnowledgeProposalArtifactMember

    return dict(
        schema_version="knowledge-analysis-proposal-receipt/10.0",
        analysis_request_id=request["analysis_request_id"],
        source=request["source"],
        base_analysis=request["base_analysis"],
        status="PROPOSED_VALIDATED",
        solution_report=pointer,
        solution_counts=dict(
            solution_steps=2, concept_assessment_links=1, choice_diagnostics=1, unresolved_issues=0
        ),
        general_knowledge_used=False,
        content_set_sha256=knowledge_solution_content_set_sha256(
            base.base_members, KnowledgeProposalArtifactMember.model_validate(pointer)
        ),
        completed_at=request["created_at"],
    )


def result_value():
    request, receipt = request_value(), receipt_value()
    pointer = deepcopy(receipt["solution_report"])
    pointer.update(
        member_path="normalized/proposal-receipt.json",
        logical_name="proposal-receipt.json",
        schema_ref="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/10.0",
    )
    value = dict(
        schema_version="knowledge-analysis-result/11.0",
        analysis_result_id="knowledgeanalysisresult_" + "b" * 32,
        analysis_request_id=request["analysis_request_id"],
        analysis_request_sha256=request["request_sha256"],
        source=request["source"],
        status="ACCEPTED",
        proposal_receipt=pointer,
        proposal_content_set_sha256=receipt["content_set_sha256"],
        risk_policy_revision_id=request["risk_policy_revision_id"],
        acceptance_mode="AUTO_POLICY",
        review_decision=None,
        counts=request["base_analysis"]["base_counts"],
        general_knowledge_used=False,
        minimum_confidence_milli=950,
        blocking_ambiguity_count=0,
        accepted_at=request["created_at"],
        base_analysis=request["base_analysis"],
        solution_counts=receipt["solution_counts"],
    )
    return value | {"result_sha256": content_sha256(value)}


@pytest.mark.parametrize(
    "model,factory,schema",
    [
        (KnowledgeAnalysisRequestV11, request_value, "knowledge-analysis-request-v11"),
        (
            KnowledgeAnalysisProposalReceiptV10,
            receipt_value,
            "knowledge-analysis-proposal-receipt-v10",
        ),
        (KnowledgeAnalysisResultV11, result_value, "knowledge-analysis-result-v11"),
    ],
)
def test_candidate_wire_and_frozen_models_have_the_same_shape(model, factory, schema):
    document = factory()
    validate_contract(schema, document)
    value = model.model_validate(document)
    assert model.model_validate_json(value.model_dump_json()) == value
    assert model.model_validate(value) == value
    assert value.source.source_class == "APPROVED_ITEM"


def test_report_reference_validator_and_public_projection_are_shared_with_past_exams():
    request = KnowledgeAnalysisRequestV11.model_validate(request_value())
    original = _role_result_value()["output"]["proposal"]
    report = KnowledgeAnalysisWorkerProposalV8.model_validate(original)
    validate_knowledge_solution_report_references(request, report)
    before = content_sha256(report.solution_report)
    text = project_public_solution_text(report.solution_report)
    assert text.status == "AVAILABLE"
    assert content_sha256(report.solution_report) == before


@pytest.mark.parametrize(
    "change",
    [
        "accepted_member_path",
        "receipt_revision",
        "base_member_hash",
        "member_schema",
        "reference_hash",
    ],
)
def test_base_pointer_cannot_hide_wrong_identity_hash_or_member_family(change):
    value = request_value()["base_analysis"]
    if change == "accepted_member_path":
        value["accepted_result_artifact"]["member_path"] = "normalized/accepted-result.json"
    elif change == "receipt_revision":
        value["proposal_receipt"]["artifact_revision_id"] = "rev_" + "d" * 32
    elif change == "base_member_hash":
        value["base_members"]["nodes"]["sha256"] = "sha256:" + "0" * 64
    elif change == "member_schema":
        value["base_members"]["nodes"]["schema_ref"] = "eom://schemas/knowledge/proposed-node/4.0"
    else:
        value["reference_index"]["index_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        RegisteredItemSolutionBasePointer.model_validate(value)


@pytest.mark.parametrize(
    "change",
    ["wrong_predecessor", "same_request", "request_hash", "coerced_boolean", "forged_nested_model"],
)
def test_request_closes_nested_typed_values_and_request_identity(change):
    value = request_value()
    if change == "wrong_predecessor":
        value["predecessor_analysis_run_id"] = "analysisrun_" + "0" * 32
    elif change == "same_request":
        value["analysis_request_id"] = value["base_analysis"]["analysis_request_id"]
    elif change == "request_hash":
        value["request_sha256"] = "sha256:" + "0" * 64
    elif change == "coerced_boolean":
        value["base_analysis"]["base_counts"]["nodes"] = True
    else:
        base = RegisteredItemSolutionBasePointer.model_validate(value["base_analysis"])
        value["base_analysis"] = base.model_copy(
            update={"proposal_content_set_sha256": "sha256:" + "0" * 64}
        )
    with pytest.raises(ValidationError):
        KnowledgeAnalysisRequestV11.model_validate(value)


def test_result_self_hash_is_not_confused_with_accepted_artifact_byte_hash():
    base = RegisteredItemSolutionBasePointer.model_validate(request_value()["base_analysis"])
    assert base.accepted_result_sha256 != base.accepted_result_artifact.sha256


def test_additive_receipt_rejects_in_place_base_rewrite_and_false_content_hash():
    value = receipt_value()
    value["solution_report"]["artifact_id"] = value["base_analysis"]["proposal_receipt"][
        "artifact_id"
    ]
    value["solution_report"]["artifact_revision_id"] = value["base_analysis"]["proposal_receipt"][
        "artifact_revision_id"
    ]
    with pytest.raises(ValidationError):
        KnowledgeAnalysisProposalReceiptV10.model_validate(value)
    value = receipt_value() | {"content_set_sha256": "sha256:" + "0" * 64}
    with pytest.raises(ValidationError):
        KnowledgeAnalysisProposalReceiptV10.model_validate(value)


def test_accepted_result_cannot_claim_different_base_counts_or_an_old_receipt():
    for change in ("counts", "receipt"):
        value = result_value()
        if change == "counts":
            value["counts"] = value["counts"] | {"nodes": 4}
        else:
            value["proposal_receipt"]["schema_ref"] = (
                "eom://schemas/knowledge/knowledge-analysis-proposal-receipt/9.0"
            )
        value["result_sha256"] = content_sha256(
            {key: item for key, item in value.items() if key != "result_sha256"}
        )
        with pytest.raises(ValidationError):
            KnowledgeAnalysisResultV11.model_validate(value)
