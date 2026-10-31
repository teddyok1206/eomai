"""A registered-Item full report traverses the real typed worker schema boundary."""

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceiptV10,
    validate_contract,
    validate_knowledge_solution_report_references,
)
from eom_orchestrator.errors import PlatformError
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal
from eom_workflow.models import (
    KnowledgeAnalysisProposalRoleResultV11,
    KnowledgeAnalysisWorkerRequest,
    WorkflowRequest,
)
from eom_workflow.schemas import (
    WorkflowSchemaError,
    constrained_result_schema,
    load_codex_result_schema,
    validate_role_input,
    validate_role_result,
    validate_schema_message,
)
from pydantic import ValidationError

from tests.unit.test_past_exam_solution_analysis_contracts import (
    _role_input_value,
    _role_result_value,
)
from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value

PROTOCOL = "workflow-role/1.35.0"
RESULT = "knowledge-analysis-proposal-result@11.0"


def worker_input():
    value = deepcopy(_role_input_value())
    value["protocol_version"] = PROTOCOL
    value["request"]["analysis_request"] = request_value()
    return validate_role_input(value, "support", PROTOCOL)


def worker_result():
    value = deepcopy(_role_result_value())
    value["protocol_version"] = PROTOCOL
    return value


def test_full_report_uses_ordinary_worker_contracts_with_no_fake_exam_images():
    request = request_value()
    workflow = WorkflowRequest(
        request_name="KNOWLEDGE_ANALYSIS_REQUEST", image_mode="skip", analysis_request=request
    )
    assert workflow.analysis_request is not None
    assert workflow.analysis_request.source.source_class == "APPROVED_ITEM"
    with pytest.raises(ValidationError, match="image mode"):
        WorkflowRequest(
            request_name="KNOWLEDGE_ANALYSIS_REQUEST",
            image_mode="required",
            analysis_request=request,
        )
    submitted = worker_input()
    assert isinstance(submitted.request, KnowledgeAnalysisWorkerRequest)
    result = validate_role_result(worker_result(), role="support", schema_id=RESULT)
    assert isinstance(result, KnowledgeAnalysisProposalRoleResultV11)
    validate_knowledge_solution_report_references(
        submitted.request.analysis_request, result.output.proposal
    )


def test_actual_codex_and_dynamic_result_schemas_close_base_report_and_reference_ids():
    submitted = worker_input()
    assert isinstance(submitted.request, KnowledgeAnalysisWorkerRequest)
    output = worker_result()
    validate_schema_message(load_codex_result_schema(RESULT), output, RESULT)
    closed = constrained_result_schema(RESULT, submitted)
    validate_schema_message(closed, output, RESULT)
    changed = deepcopy(output)
    proposal = changed["output"]["proposal"]
    proposal["base_analysis_result_id"] = "knowledgeanalysisresult_" + "0" * 32
    proposal["solution_report"]["base_analysis_result_id"] = proposal["base_analysis_result_id"]
    with pytest.raises(WorkflowSchemaError):
        validate_schema_message(closed, changed, RESULT)
    changed = deepcopy(output)
    changed["output"]["proposal"]["solution_report"]["solution_steps"][0]["node_ids"] = [
        "knode_concept_invented"
    ]
    with pytest.raises(WorkflowSchemaError):
        validate_schema_message(closed, changed, RESULT)


def test_registered_role_does_not_accept_the_old_past_exam_protocol_identity():
    changed = worker_result()
    changed["protocol_version"] = "workflow-role/1.21.0"
    with pytest.raises(WorkflowSchemaError):
        validate_role_result(changed, role="support", schema_id=RESULT)
    changed = deepcopy(_role_input_value())
    changed["protocol_version"] = PROTOCOL
    with pytest.raises(WorkflowSchemaError):
        validate_role_input(changed, "support", PROTOCOL)


def test_orchestrator_stages_only_new_report_and_receipt_not_original_base_files(tmp_path):
    submitted = worker_input()
    assert isinstance(submitted.request, KnowledgeAnalysisWorkerRequest)
    result = validate_role_result(worker_result(), role="support", schema_id=RESULT)
    assert isinstance(result, KnowledgeAnalysisProposalRoleResultV11)
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=result.output.proposal,
        request=submitted.request.analysis_request,
        job_id=submitted.job_id,
        logical_artifact_id="artifact_" + "4" * 32,
        revision_id="rev_" + "5" * 32,
        staging=tmp_path,
    )
    assert isinstance(receipt, KnowledgeAnalysisProposalReceiptV10)
    assert receipt.base_analysis == submitted.request.analysis_request.base_analysis
    assert {member.relative_path for member in staged.files} == {
        "normalized/solution-report.json",
        "normalized/proposal-receipt.json",
    }
    assert not (staged.directory / "normalized/nodes.jsonl").exists()
    validate_contract("knowledge-analysis-proposal-receipt-v10", receipt.model_dump(mode="json"))


def test_invalid_original_base_reference_fails_before_any_local_artifact_staging(tmp_path):
    submitted = worker_input()
    assert isinstance(submitted.request, KnowledgeAnalysisWorkerRequest)
    output = worker_result()
    output["output"]["proposal"]["solution_report"]["solution_steps"][0]["anchor_ids"] = [
        "anchor_not_in_the_original_analysis"
    ]
    result = validate_role_result(output, role="support", schema_id=RESULT)
    assert isinstance(result, KnowledgeAnalysisProposalRoleResultV11)
    with pytest.raises(PlatformError, match="does not resolve"):
        stage_knowledge_analysis_proposal(
            proposal=result.output.proposal,
            request=submitted.request.analysis_request,
            job_id=submitted.job_id,
            logical_artifact_id="artifact_" + "4" * 32,
            revision_id="rev_" + "5" * 32,
            staging=tmp_path,
        )
    assert not tuple(tmp_path.iterdir())
