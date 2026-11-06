"""Typed child-result resolution with synthetic owner ports, not a live authorization proof."""

from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialLearningRoleReceipt
from eom_catalog_contracts.material_learning_authorization import MaterialLearningAuthorizationReply
from eom_catalog_service import material_task_results as owner
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord, JobRecord
from eom_workflow.control_plane import ResolvedExecutionPlanV33
from eom_workflow.schemas import validate_role_input, validate_role_result
from eom_workflow_runner.models import WorkflowInstanceRecord

from tests.unit.test_material_learning_contracts import discovery
from tests.unit.test_material_learning_execution import record
from tests.unit.test_material_learning_role_contracts import material_plan, worker_input


def case(monkeypatch):
    input_doc = worker_input()
    source = validate_role_input(input_doc, "support", "workflow-role/1.37.0")
    work = source.request.work_input
    plan_doc = material_plan()
    plan_doc.update(workflow_id=source.workflow_id, work_input=work.model_dump(mode="json"))
    plan_doc["plan_sha256"] = content_sha256(
        {key: value for key, value in plan_doc.items() if key != "plan_sha256"}
    )
    plan = ResolvedExecutionPlanV33.model_validate(plan_doc)
    body = {
        key: input_doc[key]
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
        status="ok", completed_at="2026-11-05T22:00:00Z", output={"learning_result": discovery()}
    )
    role = validate_role_result(body, "support", "material-learning-result@1.0")
    raw = canonical_json_bytes(role.model_dump(mode="json"))
    work_raw = canonical_json_bytes(work.model_dump(mode="json"))
    actor = "operator_" + "f" * 32
    task = SimpleNamespace(
        task_id=work.task_id,
        run_id="materialrun_" + "1" * 32,
        unit_key="discovery-main-31-32",
        state="RESULT_READY",
        task_kind="DISCOVER",
        workflow_id=source.workflow_id,
        input_artifact_id="artifact_" + "c" * 32,
        input_artifact_revision_id="rev_" + "d" * 32,
        input_sha256=sha256_bytes(work_raw),
        output_artifact_id=None,
        output_artifact_revision_id=None,
        output_sha256=None,
    )
    parent = SimpleNamespace(created_by=actor, state="DISCOVERING")
    step = SimpleNamespace(
        workflow_id=source.workflow_id,
        step_run_id=source.step_run_id,
        step_key="learn",
        step_type="agent",
        worker_role="support",
        attempt=1,
        state="SUCCEEDED",
        result_schema="material-learning-result@1.0",
        platform_job_id=role.job_id,
    )
    job = SimpleNamespace(
        job_id=role.job_id,
        revision_id=role.artifact.revision_id,
        logical_artifact_id=role.artifact.logical_artifact_id,
        status="SUCCEEDED",
        error_code=None,
        task_type="workflow_support",
        request=input_doc,
    )
    receipt = MaterialLearningRoleReceipt(
        task_kind=work.task_kind,
        input_sha256=work.input_sha256,
        result_sha256=content_sha256(role.model_dump(mode="json")),
    )
    revision = SimpleNamespace(
        revision_id=role.artifact.revision_id,
        logical_artifact_id=role.artifact.logical_artifact_id,
        job_id=role.job_id,
        approved=True,
        content_hash=sha256_bytes(raw),
        content_bytes=len(raw),
        result=receipt.model_dump(mode="json"),
    )
    logical = SimpleNamespace(
        logical_artifact_id=role.artifact.logical_artifact_id,
        job_id=role.job_id,
        approved=True,
        artifact_type="workflow_support",
    )
    workflow = SimpleNamespace(
        workflow_id=source.workflow_id,
        state="COMPLETED",
        definition_key="material-learning",
        definition_version="1.0.0",
        role_schema_version="workflow-role/1.37.0",
        created_actor_type="human",
        created_actor_id=actor,
        runtime_context={
            "final_pointer_manifest": {
                "artifact_pointers": [
                    dict(
                        step_key="learn",
                        attempt=1,
                        job_id=role.job_id,
                        logical_artifact_id=logical.logical_artifact_id,
                        revision_id=revision.revision_id,
                        content_hash=revision.content_hash,
                        result_schema="material-learning-result@1.0",
                    )
                ]
            }
        },
    )
    rows = {
        (owner.MaterialLearningTaskRecord, task.task_id): task,
        (owner.MaterialLearningRunRecord, task.run_id): parent,
        (WorkflowInstanceRecord, workflow.workflow_id): workflow,
        (ArtifactRevisionRecord, task.input_artifact_revision_id): SimpleNamespace(
            content_bytes=len(work_raw)
        ),
        (JobRecord, job.job_id): job,
        (ArtifactRevisionRecord, revision.revision_id): revision,
        (ArtifactRecord, logical.logical_artifact_id): logical,
    }
    session = SimpleNamespace(
        get=lambda model, key, **kwargs: rows.get((model, key)),
        scalars=lambda query: (step,),
        scalar=lambda query: record(plan),
    )
    monkeypatch.setattr(owner, "authorize_material_learning", lambda *args: None)

    class Authority:
        def authorize(self, selection):
            return MaterialLearningAuthorizationReply(
                status="SUCCESS",
                request_sha256=content_sha256(selection.model_dump(mode="json")),
                input_sha256=selection.input_sha256,
                error_code=None,
            )

    monkeypatch.setattr(
        owner, "CatalogMaterialLearningAuthorizationService", lambda *args: Authority()
    )
    reads = []

    def read_member(**pointer):
        reads.append(pointer["member_path"])
        data = work_raw if pointer["member_path"] == "material/work.json" else raw
        assert sha256_bytes(data) == pointer["sha256"]
        return data

    artifacts = SimpleNamespace(engine=None, settings=None, read_member=read_member)
    return SimpleNamespace(
        session=session,
        artifacts=artifacts,
        task=task,
        parent=parent,
        workflow=workflow,
        step=step,
        job=job,
        revision=revision,
        logical=logical,
        actor=actor,
        reads=reads,
        role=role,
    )


def test_completed_result_reads_canonical_members_not_the_small_db_receipt(monkeypatch):
    value = case(monkeypatch)
    result = owner.resolve_completed_material_task(
        value.session, value.artifacts, task_id=value.task.task_id, operator_id=value.actor
    )
    assert result.role == value.role
    assert value.reads == ["material/work.json", "result.json"]
    assert "output" not in value.revision.result


@pytest.mark.parametrize(
    "mutation",
    ["owner", "workflow", "role", "job", "logical", "final_hash", "receipt", "stored_output"],
)
def test_foreign_stale_or_failed_child_is_never_adopted(monkeypatch, mutation):
    value = case(monkeypatch)
    if mutation == "owner":
        value.parent.created_by = "operator_" + "0" * 32
    elif mutation == "workflow":
        value.workflow.state = "FAILED"
    elif mutation == "role":
        value.step.attempt = 2
    elif mutation == "job":
        value.job.status = "FAILED"
    elif mutation == "logical":
        value.logical.approved = False
    elif mutation == "final_hash":
        value.workflow.runtime_context["final_pointer_manifest"]["artifact_pointers"][0][
            "content_hash"
        ] = "sha256:" + "0" * 64
    elif mutation == "receipt":
        value.revision.result["result_sha256"] = "sha256:" + "0" * 64
    else:
        value.task.output_artifact_revision_id = "rev_" + "0" * 32
    with pytest.raises(ValueError):
        owner.resolve_completed_material_task(
            value.session, value.artifacts, task_id=value.task.task_id, operator_id=value.actor
        )
