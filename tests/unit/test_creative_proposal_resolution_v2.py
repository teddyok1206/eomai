"""Completed V2 proposal resolution closes Workflow, plan, Job and Artifact family."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import creative_learning_proposal as resolution
from eom_catalog_service.creative_learning_proposal import CreativeLearningProposalError
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.control_plane import parse_creative_learning_execution_plan
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord

from tests.unit.test_creative_registration_v2 import v2_registered
from tests.unit.test_external_item_learning_execution_plan import _plan


def _case(monkeypatch):
    *_, resolved, _, _ = v2_registered(monkeypatch)
    selection = resolved.selection
    raw = _plan(successor=True)
    raw.update(
        plan_id=selection.plan_id,
        workflow_id=selection.workflow_id,
        work_input=resolved.work.model_dump(mode="json"),
    )
    raw["plan_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "plan_sha256"})
    plan = parse_creative_learning_execution_plan(raw)
    selection = selection.model_copy(update={"plan_sha256": plan.plan_sha256})
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="creative-source-learning",
        external_item_learning_work=resolved.work,
    )
    workflow = NS(
        workflow_id=selection.workflow_id,
        state="COMPLETED",
        definition_key="external-item-learning",
        definition_version="2.0.0",
        role_schema_version="workflow-role/1.34.0",
        definition_hash=plan.workflow_definition_sha256,
        created_actor_type="human",
        created_actor_id=resolved.operator_id,
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        runtime_context={
            "execution_plan": {
                "plan_id": plan.plan_id,
                "plan_sha256": plan.plan_sha256,
                "preset_id": plan.preset_id,
                "preset_revision_id": plan.preset_revision_id,
            }
        },
    )
    role = resolved.role.model_dump(mode="json")
    role.update(workflow_id=selection.workflow_id, step_run_id=selection.step_run_id)
    role["artifact"].update(
        logical_artifact_id=resolved.pointer.artifact_id,
        revision_id=resolved.pointer.artifact_revision_id,
    )
    step = NS(
        step_run_id=selection.step_run_id,
        workflow_id=selection.workflow_id,
        step_key="extract",
        worker_role="support",
        result_schema="external-item-learning-result@2.0",
        state="SUCCEEDED",
        attempt=1,
        platform_job_id=role["job_id"],
    )
    job = NS(
        job_id=role["job_id"],
        status="SUCCEEDED",
        logical_artifact_id=resolved.pointer.artifact_id,
        revision_id=resolved.pointer.artifact_revision_id,
    )
    artifact = NS(
        approved=True,
        logical_artifact_id=job.logical_artifact_id,
        content_hash=resolved.pointer.sha256,
        manifest={
            "primary_file": "result.json",
            "files": [
                {
                    "file_name": "result.json",
                    "sha256": resolved.pointer.sha256,
                    "media_type": "application/json",
                    "schema_ref": step.result_schema,
                }
            ],
        },
    )
    row = NS(
        plan_id=plan.plan_id,
        workflow_id=plan.workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
        plan_sha256=plan.plan_sha256,
        resolver_version=plan.resolver_version,
        resolved_at=plan.resolved_at,
        canonical_document=raw,
    )
    records = {
        WorkflowInstanceRecord: workflow,
        WorkflowStepRunRecord: step,
        JobRecord: job,
        ArtifactRevisionRecord: artifact,
        ResolvedExecutionPlanRecord: row,
    }
    session = Mock()
    session.get.side_effect = lambda model, key, **kwargs: records[model]
    artifacts = Mock()
    artifacts.load_json_revision.return_value = role
    return NS(**locals())


@pytest.mark.parametrize(
    "preset", ("creative-source-learning", "creative-source-learning-parallel")
)
def test_exact_v2_proposal_uses_the_existing_source_and_artifact_read_contract(monkeypatch, preset):
    value = _case(monkeypatch)
    value.workflow.initial_request["execution_preset_key"] = preset
    value.workflow.request_payload["execution_preset_key"] = preset
    result = resolution.resolve_completed_creative_learning_proposal(
        value.session, value.artifacts, value.selection
    )
    assert result.role.protocol_version == "workflow-role/1.34.0"
    assert result.role.output.learning_result.solution_report.answer_labels == ("2",)
    assert result.work == value.resolved.work
    assert result.pointer == value.resolved.pointer


@pytest.mark.parametrize(
    "field",
    [
        "workflow_role",
        "result_schema",
        "purpose",
        "plan_family",
        "job_status",
        "artifact_approval",
        "job_id",
        "artifact_identity",
    ],
)
def test_v2_resolution_never_adopts_cross_family_or_unrelated_result(monkeypatch, field):
    value = _case(monkeypatch)
    if field == "workflow_role":
        value.workflow.role_schema_version = "workflow-role/1.33.0"
    elif field == "result_schema":
        value.step.result_schema = "external-item-learning-result@1.0"
    elif field == "purpose":
        value.workflow.initial_request["execution_preset_key"] = "external-item-learning"
        value.workflow.request_payload["execution_preset_key"] = "external-item-learning"
    elif field == "plan_family":
        value.row.canonical_document.update(
            schema_version="resolved-execution-plan/27.0",
            workflow_definition_version="1.0.0",
            resolver_version="27.0.0",
        )
        value.row.canonical_document["plan_sha256"] = content_sha256(
            {k: v for k, v in value.row.canonical_document.items() if k != "plan_sha256"}
        )
        value.row.plan_sha256 = value.row.canonical_document["plan_sha256"]
        value.row.resolver_version = "27.0.0"
    elif field == "job_status":
        value.job.status = "FAILED"
    elif field == "artifact_approval":
        value.artifact.approved = False
    elif field == "job_id":
        value.role["job_id"] = "job_" + "0" * 32
    else:
        value.role["artifact"]["logical_artifact_id"] = "artifact_" + "0" * 32
    with pytest.raises(ValueError):
        resolution.resolve_completed_creative_learning_proposal(
            value.session, value.artifacts, value.selection
        )


def test_v2_out_of_page_region_is_an_explicit_resolution_error(monkeypatch):
    value = _case(monkeypatch)
    result = value.role["output"]["learning_result"]
    result["regions"][0]["physical_page"] = len(value.resolved.work.page_set.pages) + 1
    result["result_sha256"] = content_sha256(
        {k: v for k, v in result.items() if k != "result_sha256"}
    )
    with pytest.raises(CreativeLearningProposalError, match="REGION_PAGE_INVALID"):
        resolution.resolve_completed_creative_learning_proposal(
            value.session, value.artifacts, value.selection
        )
