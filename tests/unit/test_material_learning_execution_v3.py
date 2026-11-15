"""Score3 follows the real owner composition with synthetic ports, never live DB/NAS."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.source_score import PrintedSourceScoreV2
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator import orchestrator as orchestrator_owner
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.material_learning_execution import (
    MaterialLearningExecutionContext,
    validate_material_learning_execution_plan,
)
from eom_orchestrator.material_learning_plan_resolution import (
    resolve_material_learning_plan_for_request,
)
from eom_orchestrator.worker import WorkerRun
from eom_workflow.admission import workflow_admission
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedExecutionPlanV41
from eom_workflow.material_learning_prompt import material_learning_guidance
from eom_workflow.material_learning_request import (
    MaterialLearningWorkerRequestV3,
    MaterialLearningWorkflowRequestV3,
)
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.material_learning_admission import reauthorize_material_learning_submission
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import (
    create_workflow_instance,
    load_persisted_workflow_request,
    workflow_request_storage_document,
)

from tests.unit.test_external_item_learning_execution_resolver import _published_preset, _Session
from tests.unit.test_external_item_learning_workflow_admission import _session
from tests.unit.test_material_learning_execution import fixture as old_fixture
from tests.unit.test_material_learning_execution import record
from tests.unit.test_material_learning_role_contracts import material_plan
from tests.unit.test_material_learning_role_v3 import PROTOCOL, RESULT, request_v3
from tests.unit.test_material_native_visual_selection import FIGURE, LOGO, SOURCE, _catalog

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = "operator_" + "a" * 32


def requested(kind="native"):
    message, result = request_v3(kind)
    return (
        MaterialLearningWorkflowRequestV3(**message["request"]),
        MaterialLearningWorkerRequestV3(**message["request"]),
        result,
    )


def plan_for(request):
    value = material_plan()
    value.update(
        schema_version="resolved-execution-plan/41.0",
        resolver_version="41.0.0",
        workflow_definition_version="3.0.0",
        work_input=request.work_input.model_dump(mode="json"),
        native_visual_scope=None
        if request.native_visual_scope is None
        else request.native_visual_scope.model_dump(mode="json"),
        native_printed_score=None
        if request.native_printed_score is None
        else request.native_printed_score.model_dump(mode="json"),
    )
    value["plan_sha256"] = content_sha256(
        {key: child for key, child in value.items() if key != "plan_sha256"}
    )
    return ResolvedExecutionPlanV41.model_validate(value)


def definition():
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v3.yaml", {"support"})
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "c" * 32,
        definition_key="material-learning",
        definition_version="3.0.0",
        schema_version="1.0",
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        source_path=compiled.source_path,
        active=True,
    )


def test_score_definition_is_admitted_as_its_exact_protocol_not_just_an_imported_record():
    admission = workflow_admission("material-learning", "3.0.0")
    assert admission is not None and admission.role_protocol_version == PROTOCOL


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_existing_repository_preserves_null_or_observed_score_and_actual_actor(kind):
    request, worker, _ = requested(kind)
    session, source = _session(), Mock()
    source.authorize_exact_score_input.return_value = worker
    workflow, created = create_workflow_instance(
        session,
        definition=definition(),
        request=request,
        actor_type="human",
        actor_id=OPERATOR,
        idempotency_key="synthetic-material-score3",
        material_learning_authorizer=source,
    )
    assert created and workflow.role_schema_version == PROTOCOL
    assert workflow.created_actor_id == OPERATOR
    document = workflow_request_storage_document(request)
    assert load_persisted_workflow_request(document) == request
    assert "native_printed_score" in document
    assert workflow.initial_request == document
    assert source.authorize_exact_score_input.call_count == 2
    source.authorize_future_input.assert_not_called()
    source.reauthorize.assert_not_called()


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_existing_resolver_pins_exact_score_and_replays_without_new_plan(kind):
    _, worker, _ = requested(kind)
    logical, revision = _published_preset()
    logical.preset_key = "material-learning"
    body = revision.canonical_document
    body["compatible_workflow_protocols"] = [PROTOCOL]
    body["content_sha256"] = content_sha256(
        {key: child for key, child in body.items() if key != "content_sha256"}
    )
    revision.compatible_workflow_protocols, revision.content_sha256 = (
        body["compatible_workflow_protocols"],
        body["content_sha256"],
    )
    preset = ExecutionPresetRevision.model_validate(body)
    session = _Session(logical, revision)
    expected = plan_for(worker)
    args = dict(
        workflow_id=expected.workflow_id,
        workflow_definition_sha256=expected.workflow_definition_sha256,
        workflow_role_schema_version=PROTOCOL,
        request=worker,
        expected_preset=preset,
    )
    actual = resolve_material_learning_plan_for_request(session, **args)
    assert type(actual) is ResolvedExecutionPlanV41
    assert actual.native_printed_score == worker.native_printed_score
    assert len(session.added) == 2
    replay = Mock()
    replay.scalar.return_value = session.added[0]
    assert resolve_material_learning_plan_for_request(replay, **args) == actual
    if kind == "native":
        args["request"] = worker.model_copy(
            update={"native_printed_score": PrintedSourceScoreV2(state="PRINTED", points="2.5")}
        )
        with pytest.raises(ControlPlaneError):
            resolve_material_learning_plan_for_request(replay, **args)


def test_exact_score_authority_cannot_be_replaced_by_legacy_scope_only_reader():
    request, worker, _ = requested()
    source = Mock()
    source.authorize_exact_score_input.return_value = worker.model_copy(
        update={"native_printed_score": PrintedSourceScoreV2(state="PRINTED", points="2.5")}
    )
    with pytest.raises(WorkflowError):
        reauthorize_material_learning_submission(
            _session(), request=request, operator_id=OPERATOR, source_authorizer=source
        )
    source.authorize_future_input.assert_not_called()


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_real_orchestrator_composition_commits_artifact_and_only_small_db_receipt(
    monkeypatch, tmp_path, kind
):
    value = old_fixture(monkeypatch, tmp_path)
    _, worker, response = requested(kind)
    value.request, value.plan = worker, plan_for(worker)
    session = value.orchestrator.sessions().__enter__()
    session.scalar.return_value = record(value.plan)
    context = MaterialLearningExecutionContext(
        value.source, Mock(return_value=_catalog(SOURCE, (FIGURE, LOGO)))
    )

    def run(**_kwargs):
        actual = value.jobs[0].request
        result = deepcopy(response)
        for key in ("job_id", "workflow_id", "step_run_id", "artifact"):
            result[key] = actual[key]
        path = tmp_path / "score3-result.json"
        path.write_text(json.dumps(result))
        return WorkerRun(0, path, tmp_path / "out.log", tmp_path / "err.log", "synthetic-score3")

    value.worker.run_prepared.side_effect = run
    result = value.orchestrator.submit_workflow_role(
        workflow_id=value.plan.workflow_id,
        step_run_id="steprun_" + "0" * 32,
        step_key="learn",
        attempt=1,
        role="support",
        request=worker,
        upstream_artifacts=(),
        result_schema=RESULT,
        idempotency_key="synthetic-score3-role",
        prompt_text="synthetic source-only prompt",
        material_learning=context,
    )
    assert result.status == "SUCCEEDED"
    assert value.jobs[0].protocol_version == PROTOCOL
    value.commit.assert_called_once()
    receipt = orchestrator_owner.create_artifact_records.call_args.kwargs["result"]
    assert receipt["schema_version"] == "material-learning-role-receipt/3.0"
    assert receipt["result_schema"] == RESULT
    assert set(receipt) == {
        "schema_version",
        "result_schema",
        "task_kind",
        "input_sha256",
        "result_sha256",
    }
    assert len(canonical_json_bytes(receipt)) < 512
    document = orchestrator_owner.stage_structured_artifact.call_args.kwargs["result"]
    assert receipt["result_sha256"] == content_sha256(document)
    if kind == "native":
        assert (
            document["output"]["learning_result"]["proposal"]["content"]["score"]["points"] == "1.5"
        )
    value.orchestrator.capacity.release.assert_called_once()


def test_native_score_cannot_change_during_existing_row_replay():
    _, worker, _ = requested()
    plan = plan_for(worker)
    changed = worker.model_copy(
        update={"native_printed_score": PrintedSourceScoreV2(state="PRINTED", points=15)}
    )
    with pytest.raises(ControlPlaneError):
        validate_material_learning_execution_plan(
            record(plan), workflow_id=plan.workflow_id, step_key="learn", request=changed
        )
    assert "Never scale, round" in material_learning_guidance(worker)
