"""Catalog derives private source authority from stored Workflow metadata, never the caller."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_service.kakao_concept_authorization import CatalogKakaoConceptAuthorizationService
from eom_catalog_service.kakao_concept_models import KakaoConceptPhaseRecord
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_workflow.compiler import compile_definition
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import KakaoConceptWorkflowRequest
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import workflow_request_storage_document

from tests.unit.test_kakao_concept_contracts import ROOT
from tests.unit.test_kakao_concept_execution import selection
from tests.unit.test_kakao_concept_workflow_contracts import plan_value, rehash
from tests.unit.test_material_learning_execution import record


def fixture():
    definition = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    document = plan_value()
    document["workflow_definition_sha256"] = definition.sha256
    plan = KakaoConceptExecutionPlan.model_validate(rehash(document))
    request = selection().model_copy(update={"plan_sha256": plan.plan_sha256})
    original = KakaoConceptWorkflowRequest(work_input=plan.work_input)
    workflow = SimpleNamespace(
        workflow_id=plan.workflow_id,
        definition_id="definition",
        definition_key="kakao-concepts",
        definition_version="1.0.0",
        created_actor_type="human",
        state="RUNNING",
        created_actor_id="operator_" + "a" * 32,
        role_schema_version="workflow-role/1.41.0",
        definition_hash=definition.sha256,
        initial_request=workflow_request_storage_document(original),
        request_payload=workflow_request_storage_document(original),
    )
    stored_definition = SimpleNamespace(
        canonical_definition=definition.as_dict(),
        source_path=str(ROOT / "config/workflows/kakao-concepts.v1.yaml"),
        definition_key=workflow.definition_key,
        definition_version=workflow.definition_version,
        definition_hash=definition.sha256,
    )
    step = SimpleNamespace(
        workflow_id=plan.workflow_id,
        step_key="assist",
        worker_role="support",
        step_type="agent",
        attempt=1,
        result_schema="kakao-concepts-result@1.0",
    )
    phase = SimpleNamespace(workflow_id=plan.workflow_id)
    records = {
        (WorkflowInstanceRecord, request.workflow_id): workflow,
        (WorkflowStepRunRecord, request.step_run_id): step,
        (WorkflowDefinitionRecord, "definition"): stored_definition,
        (ResolvedExecutionPlanRecord, plan.plan_id): record(plan),
        (KakaoConceptPhaseRecord, (plan.work_input.task_id, plan.work_input.phase)): phase,
    }
    session = Mock()
    session.get.side_effect = lambda model, identity, **_kw: records.get((model, identity))
    tasks = Mock()
    tasks.sessions = lambda: nullcontext(session)
    return SimpleNamespace(
        service=CatalogKakaoConceptAuthorizationService(tasks),
        tasks=tasks,
        session=session,
        request=request,
        workflow=workflow,
        step=step,
        definition=stored_definition,
        phase=phase,
        records=records,
        plan=plan,
    )


def test_exact_persisted_owner_phase_plan_and_original_input_are_required():
    value = fixture()
    reply = value.service.authorize(value.request)
    reply.validate_for(value.request)
    assert reply.status == "SUCCESS"
    value.tasks.accepted_source_authority.assert_called_once_with(
        task_id=value.plan.work_input.task_id,
        operator_id=value.workflow.created_actor_id,
    )
    value.tasks.accepted_source_authority.return_value.reauthorize.assert_called_once_with(
        value.session,
        operator_id=value.workflow.created_actor_id,
        work=value.plan.work_input,
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing-workflow",
        "missing-step",
        "missing-plan",
        "cancelled",
        "purpose",
        "actor",
        "protocol",
        "step-workflow",
        "step-key",
        "role",
        "attempt",
        "result",
        "definition",
        "original",
        "plan-hash",
        "work-hash",
        "unlinked",
        "revoked",
    ],
)
def test_mismatched_or_unaccepted_identity_cannot_authorize_a_worker(change):
    value = fixture()
    if change.startswith("missing-"):
        cls, identity = {
            "missing-workflow": (WorkflowInstanceRecord, value.request.workflow_id),
            "missing-step": (WorkflowStepRunRecord, value.request.step_run_id),
            "missing-plan": (ResolvedExecutionPlanRecord, value.plan.plan_id),
        }[change]
        value.records.pop((cls, identity))
    elif change == "cancelled":
        value.workflow.state = "CANCELLED"
    elif change in {"purpose", "actor", "protocol"}:
        setattr(
            value.workflow,
            {
                "purpose": "definition_key",
                "actor": "created_actor_type",
                "protocol": "role_schema_version",
            }[change],
            "other",
        )
    elif change in {"step-workflow", "step-key", "role", "attempt", "result"}:
        setattr(
            value.step,
            {
                "step-workflow": "workflow_id",
                "step-key": "step_key",
                "role": "worker_role",
                "attempt": "attempt",
                "result": "result_schema",
            }[change],
            2 if change == "attempt" else "other",
        )
    elif change == "definition":
        value.definition.definition_hash = "sha256:" + "0" * 64
    elif change == "original":
        value.workflow.request_payload = dict(
            value.workflow.request_payload,
            work_input=dict(value.workflow.request_payload["work_input"], request_bytes=1),
        )
    elif change in {"plan-hash", "work-hash"}:
        value.request = value.request.model_copy(
            update={change.replace("-hash", "_sha256"): "sha256:" + "0" * 64}
        )
    elif change == "unlinked":
        value.phase.workflow_id = "workflow_" + "0" * 32
    else:
        value.tasks.accepted_source_authority.return_value.reauthorize.side_effect = ValueError(
            "current source revoked"
        )
    with pytest.raises((ValueError, RuntimeError)):
        value.service.authorize(value.request)
