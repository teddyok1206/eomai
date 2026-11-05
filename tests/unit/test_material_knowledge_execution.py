"""Uploaded explanations use the existing prepare/execute/commit fence, without Codex."""

import json
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_knowledge_analysis import KnowledgeAnalysisRequestV12
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker import WorkerRun
from eom_workflow.control_plane import ResolvedExecutionPlanV34
from eom_workflow.models import KnowledgeAnalysisWorkerRequest

from tests.unit.test_external_item_learning_execution import _fixture
from tests.unit.test_knowledge_analysis_document_contracts import stable_identity_proposal
from tests.unit.test_material_knowledge_contracts import analysis_request, knowledge_plan
from tests.unit.test_material_learning_execution import record


def fixture(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(owner_module, "commit_file_set_artifact", value.commit)
    value.plan = ResolvedExecutionPlanV34.model_validate(knowledge_plan())
    value.request = KnowledgeAnalysisWorkerRequest(
        analysis_request=KnowledgeAnalysisRequestV12.model_validate(analysis_request())
    )
    value.orchestrator.sessions().__enter__().scalar.return_value = record(value.plan)

    def run(**_values):
        request = value.jobs[0].request
        body = {
            key: request[key]
            for key in (
                "schema_version",
                "protocol_version",
                "job_id",
                "workflow_id",
                "step_run_id",
                "role",
                "artifact",
            )
        }
        body.update(
            status="ok",
            completed_at="2026-11-05T22:00:00Z",
            output={"proposal": stable_identity_proposal(value.request.analysis_request)},
        )
        path = tmp_path / "knowledge-result.json"
        path.write_text(json.dumps(body))
        return WorkerRun(0, path, tmp_path / "stdout", tmp_path / "stderr", "synthetic")

    value.worker.run_prepared.side_effect = run
    return value


def execute(value, authority):
    return value.orchestrator.submit_workflow_role(
        workflow_id=value.plan.workflow_id,
        step_run_id="steprun_" + "0" * 32,
        step_key="analyze",
        attempt=1,
        role="support",
        request=value.request,
        upstream_artifacts=(),
        result_schema="knowledge-analysis-proposal-result@12.0",
        idempotency_key="synthetic-uploaded-knowledge",
        prompt_text="synthetic prompt",
        reauthorize_knowledge_source=authority,
    )


def test_uploaded_explanation_has_no_unchecked_generic_execution(monkeypatch, tmp_path):
    value = fixture(monkeypatch, tmp_path)
    with pytest.raises(ControlPlaneError):
        execute(value, None)
    assert not value.jobs
    value.worker.run_prepared.assert_not_called()


def test_uploaded_explanation_commits_existing_stable_proposal_after_source_checks(
    monkeypatch, tmp_path
):
    value = fixture(monkeypatch, tmp_path)
    source = Mock()
    result = execute(value, source)
    assert result.status == "SUCCEEDED", (result.error_code, result.error_message)
    assert source.call_count == 4
    value.worker.run_prepared.assert_called_once()
    value.worker.run_structured.assert_not_called()
    value.commit.assert_called_once()
    value.orchestrator.capacity.release.assert_called_once()


@pytest.mark.parametrize("at", [2, 3, 4])
def test_revoked_uploaded_knowledge_never_commits_or_holds_uncertain_lease(
    monkeypatch, tmp_path, at
):
    value = fixture(monkeypatch, tmp_path)
    source = Mock(side_effect=[None] * (at - 1) + [ValueError("synthetic revocation")])
    result = execute(value, source)
    assert result.status == "FAILED"
    value.commit.assert_not_called()
    assert value.worker.run_prepared.call_count == (1 if at == 4 else 0)
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()
