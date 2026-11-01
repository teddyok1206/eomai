"""Legacy reconstruction is authorized by the original application, not worker claims."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock

import pytest
from eom_catalog_contracts import KnowledgeAnalysisRequestV2, KnowledgeProposalArtifactMember
from eom_catalog_service import knowledge_analysis_service as application
from eom_identifiers import content_sha256
from eom_orchestrator.knowledge_analysis_artifact import stage_knowledge_analysis_proposal

from tests.unit.test_curriculum_graph_structure import _approved_item_analysis
from tests.unit.test_knowledge_analysis_artifact import _proposal, _request


def authority_case(tmp_path, monkeypatch):
    raw = _request().model_dump(mode="json")
    raw["source"] = _approved_item_analysis().source.model_dump(mode="json")
    raw["request_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "request_sha256"})
    request = KnowledgeAnalysisRequestV2.model_validate(raw)
    proposal_data = _proposal().model_dump(mode="json")
    for anchor in proposal_data["anchors"]:
        anchor["artifact_revision_id"] = request.source.artifact_member.artifact_revision_id
        anchor["member_path"] = request.source.artifact_member.member_path
    (tmp_path / "proposal").mkdir()
    staged, receipt = stage_knowledge_analysis_proposal(
        proposal=type(_proposal()).model_validate(proposal_data),
        request=request,
        job_id="job_" + "1" * 32,
        logical_artifact_id="artifact_" + "2" * 32,
        revision_id="rev_" + "3" * 32,
        staging=tmp_path / "proposal",
    )
    pointer = KnowledgeProposalArtifactMember(
        artifact_id=staged.logical_artifact_id,
        artifact_revision_id=staged.revision_id,
        member_path="normalized/proposal-receipt.json",
        sha256=staged.primary_hash,
        schema_ref="eom://schemas/knowledge/knowledge-analysis-proposal-receipt/1.0",
        media_type="application/json",
        bytes=staged.primary_bytes,
        logical_name="proposal-receipt.json",
    )
    actor = "operator_" + "a" * 32
    run = NS(
        analysis_run_id="analysisrun_" + "b" * 32,
        state="VALIDATING",
        canonical_request=request.model_dump(mode="json"),
        workflow_id="workflow_" + "c" * 32,
        created_by_operator_id=actor,
        risk_policy_revision_id=request.risk_policy_revision_id,
    )
    operator = NS(status="ACTIVE", deleted_at=None, must_change_password=False)
    workflow = NS(state="COMPLETED")
    session = MagicMock()

    def get(model, _identifier, **_kwargs):
        return {
            application.KnowledgeAnalysisRunRecord: run,
            application.OperatorRecord: operator,
            application.WorkflowInstanceRecord: workflow,
        }[model]

    session.get.side_effect = get
    session.__enter__.return_value = session
    service = object.__new__(application.KnowledgeAnalysisApplicationService)
    service.sessions = Mock(return_value=session)
    service.artifacts = Mock()
    service._stored_receipt = Mock(return_value=receipt)
    service._proposal_receipt_pointer = Mock(return_value=pointer)
    service.risk_policy = Mock(
        return_value=NS(
            risk_policy_revision_id=request.risk_policy_revision_id,
            content_sha256="sha256:" + "d" * 64,
        )
    )
    permissions = {
        application.PermissionKey.ITEM_READ,
        application.PermissionKey.KNOWLEDGE_ANALYSIS_CREATE,
    }
    monkeypatch.setattr(application, "effective_permissions", lambda *_: permissions)
    resolver = Mock(return_value=request.source)
    monkeypatch.setattr(application, "resolve_approved_item_source", resolver)
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("captured before publication")

    service._commit_json_artifact = capture
    with pytest.raises(RuntimeError, match="captured before publication"):
        service._accept(
            run.analysis_run_id, acceptance_mode="AUTO_POLICY", review_pointer=None, actor_id=actor
        )
    callback = captured["recovery_authorizer"]
    assert callback is not None
    job = NS(
        task_type="knowledge-analysis-accepted-result",
        request={"analysis_run_id": run.analysis_run_id},
    )
    return NS(**locals())


def test_actual_acceptance_builds_current_exact_reconstruction_proof(tmp_path, monkeypatch):
    value = authority_case(tmp_path, monkeypatch)
    proof = value.callback(value.session, value.job)
    assert proof.actor_id == value.actor
    assert proof.kind == "PINNED_KNOWLEDGE_ACCEPTANCE"
    assert proof == value.callback(value.session, value.job)
    assert (
        value.resolver.call_args.kwargs["item_revision_id"] == value.request.source.item_revision_id
    )
    assert value.session.get.call_args.kwargs["populate_existing"] is True


@pytest.mark.parametrize(
    "change",
    [
        "run_state",
        "actor",
        "request",
        "operator",
        "deleted",
        "password",
        "permission",
        "workflow",
        "workflow_pointer",
        "job",
        "receipt",
        "policy",
        "source",
    ],
)
def test_current_acceptance_authority_cannot_be_borrowed_or_stale(tmp_path, monkeypatch, change):
    value = authority_case(tmp_path, monkeypatch)
    if change == "run_state":
        value.run.state = "FAILED"
    elif change == "actor":
        value.run.created_by_operator_id = "operator_" + "f" * 32
    elif change == "request":
        value.run.canonical_request = value.run.canonical_request | {
            "created_at": "2026-11-01T00:00:00Z"
        }
    elif change == "operator":
        value.operator.status = "DISABLED"
    elif change == "deleted":
        value.operator.deleted_at = value.receipt.completed_at
    elif change == "password":
        value.operator.must_change_password = True
    elif change == "permission":
        value.permissions.clear()
    elif change == "workflow":
        value.workflow.state = "RUNNING"
    elif change == "workflow_pointer":
        value.run.workflow_id = "workflow_" + "f" * 32
    elif change == "job":
        value.job.request = {"analysis_run_id": "analysisrun_" + "f" * 32}
    elif change == "receipt":
        value.service._stored_receipt.return_value = None
    elif change == "policy":
        value.service.risk_policy.return_value = None
    else:
        value.resolver.return_value = None
    with pytest.raises((application.KnowledgeAnalysisServiceError, ValueError)):
        value.callback(value.session, value.job)
