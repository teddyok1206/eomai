"""Bounded saved-role reads reject partial, other-purpose and mismatched execution metadata."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.kakao_concept_models import KakaoConceptPhaseRecord
from eom_catalog_service.kakao_concept_phase_results import read_kakao_concept_phase_result
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_workflow.kakao_concept_request import KakaoConceptWork, KakaoConceptWorkflowRequest
from eom_workflow.kakao_concept_result import KakaoConceptRoleResult
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.unit.test_kakao_concept_contracts import plan, plan_request, result
from tests.unit.test_kakao_concept_workflow_contracts import message, work_value


def fixture():
    request = plan_request()
    work = KakaoConceptWork.model_validate(work_value(request))
    worker = message(request)
    body = {
        key: worker[key]
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
    body.update(status="ok", completed_at="2026-11-17T11:00:00Z", output=result(request, plan()))
    body = KakaoConceptRoleResult.model_validate(body).model_dump(mode="json")
    operator = "operator_" + "a" * 32
    original = workflow_request_storage_document(KakaoConceptWorkflowRequest(work_input=work))
    workflow = SimpleNamespace(
        workflow_id=worker["workflow_id"],
        state="COMPLETED",
        definition_key="kakao-concepts",
        definition_version="1.0.0",
        role_schema_version="workflow-role/1.41.0",
        created_actor_type="human",
        created_actor_id=operator,
        initial_request=original,
        request_payload=deepcopy(original),
    )
    step = SimpleNamespace(
        platform_job_id=worker["job_id"],
        worker_role="support",
        result_schema="kakao-concepts-result@1.0",
        state="SUCCEEDED",
        attempt=1,
        step_run_id=worker["step_run_id"],
    )
    job = SimpleNamespace(
        job_id=worker["job_id"],
        protocol_version=worker["protocol_version"],
        task_type="workflow_support",
        status="SUCCEEDED",
        logical_artifact_id=worker["artifact"]["logical_artifact_id"],
        revision_id=worker["artifact"]["revision_id"],
        request=worker,
    )
    revision = SimpleNamespace(
        approved=True,
        logical_artifact_id=job.logical_artifact_id,
        revision_id=job.revision_id,
        job_id=job.job_id,
        content_hash=content_sha256(body),
    )
    phase = SimpleNamespace(
        workflow_id=worker["workflow_id"], work_input=work.model_dump(mode="json")
    )
    records = {
        (KakaoConceptPhaseRecord, (work.task_id, "PLAN")): phase,
        (WorkflowInstanceRecord, workflow.workflow_id): workflow,
        (JobRecord, job.job_id): job,
        (ArtifactRevisionRecord, job.revision_id): revision,
    }
    session = Mock()
    session.get.side_effect = lambda cls, identity, **_kwargs: records.get((cls, identity))
    session.scalars.return_value = [step]
    service, authority = Mock(), Mock()
    service.sessions.side_effect = lambda: nullcontext(session)
    service.accepted_intent_row.return_value = SimpleNamespace(
        task_id=work.task_id, owner_operator_id=operator
    )
    service.artifacts.read_member.return_value = canonical_json_bytes(request)
    service.artifacts.load_json_revision.return_value = body
    authority.service, authority.owner_operator_id = service, operator
    return SimpleNamespace(
        service=service,
        authority=authority,
        work=work,
        body=body,
        workflow=workflow,
        step=step,
        job=job,
        revision=revision,
        phase=phase,
        records=records,
        session=session,
    )


def test_completed_phase_has_exact_execution_and_artifact_pins():
    value = fixture()
    completed = read_kakao_concept_phase_result(value.authority, "PLAN")
    assert completed.pin.job_id == value.job.job_id
    assert completed.pin.sha256 == value.revision.content_hash
    assert completed.work == value.work
    value.service.artifacts.load_json_revision.assert_called_once()
    assert value.authority.reauthorize.call_count == 2


@pytest.mark.parametrize(
    "change",
    [
        "missing-phase",
        "workflow-running",
        "purpose",
        "actor",
        "original",
        "step-failed",
        "job-failed",
        "job-purpose",
        "revision-job",
        "revision-unapproved",
        "frame-artifact",
        "result-frame",
        "result-hash",
        "input-hash",
        "two-steps",
    ],
)
def test_reader_never_replaces_failed_partial_or_foreign_result(change):
    value = fixture()
    if change == "missing-phase":
        value.records.pop((KakaoConceptPhaseRecord, (value.work.task_id, "PLAN")))
    elif change in {"workflow-running", "purpose", "actor"}:
        setattr(
            value.workflow,
            {"workflow-running": "state", "purpose": "definition_key", "actor": "created_actor_id"}[
                change
            ],
            "other",
        )
    elif change == "original":
        value.workflow.request_payload["work_input"]["request_bytes"] += 1
    elif change in {"step-failed", "job-failed"}:
        setattr(
            value.step if change == "step-failed" else value.job,
            "state" if change == "step-failed" else "status",
            "FAILED",
        )
    elif change == "job-purpose":
        value.job.task_type = "workflow_review"
    elif change == "revision-job":
        value.revision.job_id = "job_" + "f" * 32
    elif change == "revision-unapproved":
        value.revision.approved = False
    elif change == "frame-artifact":
        value.job.request["artifact"]["revision_id"] = "rev_" + "f" * 32
    elif change == "result-frame":
        value.body["step_run_id"] = "steprun_" + "f" * 32
        value.revision.content_hash = content_sha256(value.body)
    elif change == "result-hash":
        value.body["output"]["output"]["focus_summary"] = "changed canonical result"
    elif change == "input-hash":
        value.service.artifacts.read_member.return_value += b" "
    else:
        value.session.scalars.return_value = [value.step, value.step]
    with pytest.raises((ValueError, RuntimeError)):
        read_kakao_concept_phase_result(value.authority, "PLAN")
