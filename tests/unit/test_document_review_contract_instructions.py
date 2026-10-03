"""Contract-specific instructions do not require unavailable paired/Graph inputs."""

from eom_orchestrator.execution_materializer import _predecessor_document_review_contract
from eom_workflow import ResolvedExecutionPlanV13, ResolvedExecutionPlanV14


def test_single_document_contract_does_not_invent_a_solution_or_graph_evidence() -> None:
    instructions = _predecessor_document_review_contract(
        ResolvedExecutionPlanV13.model_construct()
    ).decode("utf-8")
    assert "PDF_DOCUMENT_REVIEW_REQUEST" in instructions
    assert "workflow-role/1.25.0, pdf-document-review-result@1.0" in instructions
    assert "Do not require a separate QUESTION/SOLUTION pair" in instructions
    assert "No Graph evidence files are staged or authorized" in instructions
    assert "take precedence over incompatible newer role requirements" in instructions
    assert "Preserve all platform safety rules" in instructions


def test_paired_predecessor_keeps_cross_document_checks_without_claiming_graph() -> None:
    instructions = _predecessor_document_review_contract(
        ResolvedExecutionPlanV14.model_construct()
    ).decode("utf-8")
    assert "workflow-role/1.26.0, pdf-document-review-result@2.0" in instructions
    assert "perform the required cross-document checks" in instructions
    assert "SINGLE-DOCUMENT" not in instructions
    assert "Do not require V3 item_reviews or evidence_usage fields" in instructions
    assert "No Graph evidence files are staged or authorized" in instructions
