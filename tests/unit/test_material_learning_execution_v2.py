"""Future material envelopes use existing admission, worker and commit boundaries; no live I/O."""

import json
import os
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationReply,
    MaterialLearningAuthorizationRequest,
)
from eom_identifiers import content_sha256
from eom_orchestrator import execution_materializer as materializer
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.material_learning_execution import (
    MaterialLearningExecutionContext,
    validate_material_learning_execution_plan,
)
from eom_orchestrator.material_learning_plan_resolution import (
    resolve_material_learning_plan_for_request,
)
from eom_orchestrator.worker import WorkerRun
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedExecutionPlanV40
from eom_workflow.material_learning_request import (
    MaterialLearningWorkerRequestV2,
    MaterialLearningWorkflowRequest,
    MaterialLearningWorkflowRequestV2,
)
from eom_workflow_runner import engine as engine_owner
from eom_workflow_runner import material_learning_catalog_client as catalog_client
from eom_workflow_runner import material_learning_start as start_owner
from eom_workflow_runner.engine import PlatformRoleJobExecutor, _prompt_name_for_request
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.material_learning_admission import (
    material_learning_fingerprint,
    reauthorize_material_learning_submission,
    validate_material_learning_definition,
)
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
from tests.unit.test_material_learning_materialization import fixture as page_fixture
from tests.unit.test_material_learning_role_contracts import material_plan
from tests.unit.test_material_learning_role_v2 import request_input
from tests.unit.test_material_native_visual_selection import FIGURE, LOGO, SOURCE, _catalog

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = "operator_" + "a" * 32


def definition():
    compiled = compile_definition(ROOT / "config/workflows/material-learning.v2.yaml", {"support"})
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "c" * 32,
        definition_key="material-learning",
        definition_version="2.0.0",
        schema_version="1.0",
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        source_path=compiled.source_path,
        active=True,
    )


def requested(kind="native", **kwargs):
    message, result = request_input(kind, **kwargs)
    worker = MaterialLearningWorkerRequestV2.model_validate(message["request"])
    return (
        MaterialLearningWorkflowRequestV2(**message["request"]),
        worker,
        result,
    )


def plan_for(request):
    document = material_plan()
    document.update(
        schema_version="resolved-execution-plan/40.0",
        resolver_version="40.0.0",
        workflow_definition_version="2.0.0",
        work_input=request.work_input.model_dump(mode="json"),
        native_visual_scope=(
            None
            if request.native_visual_scope is None
            else request.native_visual_scope.model_dump(mode="json")
        ),
    )
    document["plan_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    )
    return ResolvedExecutionPlanV40.model_validate(document)


def owner_for(worker):
    owner = Mock()
    owner.authorize_future_input.return_value = worker
    owner.reauthorize.return_value = worker.work_input
    return owner


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_repository_preserves_explicit_null_or_exact_scope_and_actual_operator(kind):
    request, worker, _ = requested(kind)
    session, owner = _session(), owner_for(worker)
    workflow, created = create_workflow_instance(
        session,
        definition=definition(),
        request=request,
        actor_type="human",
        actor_id=OPERATOR,
        idempotency_key="synthetic-material-v2",
        material_learning_authorizer=owner,
    )
    assert created and workflow.role_schema_version == "workflow-role/1.39.0"
    assert workflow.created_actor_id == OPERATOR
    assert workflow.stage == "KNOWLEDGE_ANALYSIS"
    stored = workflow_request_storage_document(request)
    assert "native_visual_scope" in stored
    assert load_persisted_workflow_request(stored) == request
    assert workflow.initial_request == stored
    owner.reauthorize.assert_not_called()
    assert owner.authorize_future_input.call_count == 2
    for call in owner.authorize_future_input.call_args_list:
        assert call.args == (session,)
        assert call.kwargs == {"operator_id": OPERATOR, "work": worker.work_input}


@pytest.mark.parametrize("fault", ["scope", "revoked", "legacy-request"])
def test_future_source_authority_cannot_be_replaced_by_work_hash_only(fault):
    request, worker, _ = requested()
    owner = owner_for(worker)
    if fault == "scope":
        owner.authorize_future_input.return_value = worker.model_copy(
            update={"native_visual_scope": None}
        )
    elif fault == "revoked":
        owner.authorize_future_input.side_effect = ValueError("synthetic revoked source")
    else:
        request = MaterialLearningWorkflowRequest(work_input=worker.work_input)
    session = _session()
    with pytest.raises(WorkflowError):
        create_workflow_instance(
            session,
            definition=definition(),
            request=request,
            actor_type="human",
            actor_id=OPERATOR,
            idempotency_key="synthetic-material-authority-failure",
            material_learning_authorizer=owner,
        )
    session.add.assert_not_called()


def test_v2_authority_rechecks_the_whole_request_and_revocation_is_not_swallowed():
    request, worker, _ = requested()
    owner = owner_for(worker)
    reauthorize_material_learning_submission(
        _session(), request=request, operator_id=OPERATOR, source_authorizer=owner
    )
    owner.authorize_future_input.side_effect = ValueError("synthetic revoked source")
    with pytest.raises(WorkflowError):
        reauthorize_material_learning_submission(
            _session(), request=request, operator_id=OPERATOR, source_authorizer=owner
        )


def test_future_definition_retains_exact_existing_one_shot_limits():
    selected = definition()
    validate_material_learning_definition(selected)
    selected.canonical_definition["limits"]["max_step_attempts"] = 2
    selected.definition_hash = content_sha256(selected.canonical_definition)
    with pytest.raises(WorkflowError):
        validate_material_learning_definition(selected)


def test_native_scope_is_part_of_business_fingerprint_without_new_queue_or_purpose():
    request, worker, _ = requested()
    changed = request.model_copy(
        update={
            "native_visual_scope": worker.native_visual_scope.model_copy(
                update={"allowed_picture_use_ids": ()}
            )
        }
    )
    assert material_learning_fingerprint(definition(), request, operator_id=OPERATOR) != (
        material_learning_fingerprint(definition(), changed, operator_id=OPERATOR)
    )


@pytest.mark.parametrize("kind", ["discovery", "native"])
def test_resolver_pins_scope_in_v40_and_replays_exactly(kind):
    _, worker, _ = requested(kind)
    logical, revision = _published_preset()
    logical.preset_key = "material-learning"
    body = revision.canonical_document
    body["compatible_workflow_protocols"] = ["workflow-role/1.39.0"]
    body["content_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "content_sha256"}
    )
    revision.compatible_workflow_protocols = body["compatible_workflow_protocols"]
    revision.content_sha256 = body["content_sha256"]
    preset = ExecutionPresetRevision.model_validate(body)
    session = _Session(logical, revision)
    expected = plan_for(worker)
    args = dict(
        workflow_id=expected.workflow_id,
        workflow_definition_sha256=expected.workflow_definition_sha256,
        workflow_role_schema_version="workflow-role/1.39.0",
        request=worker,
        expected_preset=preset,
    )
    actual = resolve_material_learning_plan_for_request(session, **args)
    assert isinstance(actual, ResolvedExecutionPlanV40)
    assert actual.native_visual_scope == worker.native_visual_scope
    assert len(session.added) == 2
    replay = Mock()
    replay.scalar.return_value = session.added[0]
    assert resolve_material_learning_plan_for_request(replay, **args) == actual
    if worker.native_visual_scope is not None:
        args["request"] = worker.model_copy(update={"native_visual_scope": None})
        with pytest.raises(ControlPlaneError):
            resolve_material_learning_plan_for_request(replay, **args)


@pytest.mark.parametrize("fault", [None, "scope", "plan"])
def test_execution_context_uses_exact_new_plan_not_implicit_latest(fault):
    _, worker, _ = requested()
    selected = plan_for(worker)
    row = record(selected)
    if fault == "scope":
        worker = worker.model_copy(update={"native_visual_scope": None})
    elif fault == "plan":
        row.plan_sha256 = "sha256:" + "f" * 64
    if fault:
        with pytest.raises(ControlPlaneError):
            validate_material_learning_execution_plan(
                row, workflow_id=selected.workflow_id, step_key="learn", request=worker
            )
    else:
        assert (
            validate_material_learning_execution_plan(
                row, workflow_id=selected.workflow_id, step_key="learn", request=worker
            )
            == selected
        )


def test_rpc_dto_one_reauthorizes_new_request_without_browser_actor_or_scope_claim(
    monkeypatch, tmp_path
):
    _, worker, _ = requested()
    selected = plan_for(worker)
    authorization = MaterialLearningAuthorizationRequest(
        workflow_id=selected.workflow_id,
        step_run_id="steprun_" + "0" * 32,
        plan_id=selected.plan_id,
        plan_sha256=selected.plan_sha256,
        input_sha256=selected.work_input.input_sha256,
    )
    reply = MaterialLearningAuthorizationReply(
        status="SUCCESS",
        request_sha256=content_sha256(authorization.model_dump(mode="json")),
        input_sha256=authorization.input_sha256,
        error_code=None,
    )
    exchange = Mock(return_value=reply.model_dump(mode="json"))
    monkeypatch.setattr(catalog_client, "exchange_chat_frame", exchange)
    reader = catalog_client.CatalogMaterialLearningSourceReader(
        authorization,
        worker,
        endpoint=ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid()),
    )
    reader(worker)
    sent = exchange.call_args.args[1]
    assert not {"actor_id", "native_visual_scope"}.intersection(sent)
    assert sent["plan_sha256"] == selected.plan_sha256
    with pytest.raises(ControlPlaneError):
        reader(worker.model_copy(update={"native_visual_scope": None}))
    assert exchange.call_count == 1


def v2_execution_fixture(monkeypatch, tmp_path, kind="native"):
    value = old_fixture(monkeypatch, tmp_path)
    _, worker, response = requested(kind)
    value.request = worker
    value.plan = plan_for(worker)
    session = value.orchestrator.sessions().__enter__()
    session.scalar.return_value = record(value.plan)
    catalog = _catalog(SOURCE, (FIGURE, LOGO))
    value.context = MaterialLearningExecutionContext(value.source, Mock(return_value=catalog))

    def run(**_kwargs):
        actual = value.jobs[0].request
        result = deepcopy(response)
        for field in ("job_id", "workflow_id", "step_run_id", "artifact"):
            result[field] = actual[field]
        path = tmp_path / "future-material-result.json"
        path.write_text(json.dumps(result))
        return WorkerRun(0, path, tmp_path / "out.log", tmp_path / "err.log", "synthetic-v2")

    value.worker.run_prepared.side_effect = run
    value.response = response
    return value


def execute(value):
    return value.orchestrator.submit_workflow_role(
        workflow_id=value.plan.workflow_id,
        step_run_id="steprun_" + "0" * 32,
        step_key="learn",
        attempt=1,
        role="support",
        request=value.request,
        upstream_artifacts=(),
        result_schema="material-learning-result@2.0",
        idempotency_key="synthetic-future-material-role",
        prompt_text="synthetic source-only prompt",
        material_learning=value.context,
    )


@pytest.mark.parametrize("kind", ["discovery", "extraction", "native"])
def test_future_work_executes_existing_lane_and_commits_only_small_receipt_v2(
    monkeypatch, tmp_path, kind
):
    value = v2_execution_fixture(monkeypatch, tmp_path, kind)
    result = execute(value)
    assert result.status == "SUCCEEDED"
    assert value.jobs[0].protocol_version == "workflow-role/1.39.0"
    assert (
        value.orchestrator.capacity.claim.call_args.args[0].workload_class == "KNOWLEDGE_ANALYSIS"
    )
    value.commit.assert_called_once()
    receipt = owner_module.create_artifact_records.call_args.kwargs["result"]
    assert receipt["schema_version"] == "material-learning-role-receipt/2.0"
    assert receipt["result_schema"] == "material-learning-result@2.0"
    assert not {"output", "regions", "native_visual_coverage"}.intersection(receipt)
    document = owner_module.stage_structured_artifact.call_args.kwargs["result"]
    assert (
        document["output"]["native_visual_coverage"]
        == value.response["output"]["native_visual_coverage"]
    )
    assert receipt["result_sha256"] == content_sha256(document)
    value.orchestrator.capacity.release.assert_called_once()


@pytest.mark.parametrize("fault", ["missing", "wrong-block", "revoked"])
def test_native_closure_and_current_source_revocation_fail_before_artifact_commit(
    monkeypatch, tmp_path, fault
):
    value = v2_execution_fixture(monkeypatch, tmp_path)
    if fault == "missing":
        value.response["output"]["native_visual_coverage"]["dispositions"] = []
    elif fault == "wrong-block":
        value.response["output"]["native_visual_coverage"]["dispositions"][0]["block_id"] = (
            "block_missing"
        )
    else:
        value.source.side_effect = ValueError("synthetic revoked source")
        with pytest.raises(ControlPlaneError, match="authorization failed"):
            execute(value)
        value.commit.assert_not_called()
        value.worker.run_prepared.assert_not_called()
        return
    result = execute(value)
    assert result.status == "FAILED"
    value.commit.assert_not_called()


def test_runner_prompt_selection_does_not_conflate_new_material_with_other_support():
    _, worker, _ = requested()
    assert _prompt_name_for_request(worker_role="support", request=worker) == "material-learning"


def test_definition_two_start_obtains_scope_from_owner_before_any_workflow_persistence(monkeypatch):
    request, worker, _ = requested()
    owner = owner_for(worker)
    owner.authorize_future_input.side_effect = ValueError("synthetic revoked source")
    create = Mock()
    monkeypatch.setattr(start_owner, "create_workflow_instance", create)
    with pytest.raises(ValueError, match="revoked"):
        start_owner.submit_material_learning_workflow(
            _session(),
            definition=definition(),
            work=request.work_input,
            operator_id=OPERATOR,
            idempotency_key="synthetic-never-submitted",
            source_authorizer=owner,
            expected_preset=SimpleNamespace(),
        )
    create.assert_not_called()


def test_definition_two_start_pins_owner_scope_in_existing_ready_role_and_command(monkeypatch):
    request, worker, _ = requested()
    owner = owner_for(worker)
    workflow = SimpleNamespace(
        workflow_id="workflow_" + "d" * 32,
        role_schema_version="workflow-role/1.39.0",
        runtime_context={},
        state="REQUESTED",
    )
    session = _session()
    session.in_transaction.return_value = True
    session.scalars.side_effect = [SimpleNamespace(one=lambda: workflow), (), ()]
    create = Mock(return_value=(workflow, True))
    monkeypatch.setattr(start_owner, "create_workflow_instance", create)
    selected = plan_for(worker).model_copy(update={"workflow_id": workflow.workflow_id})
    resolve = Mock(return_value=selected)
    monkeypatch.setattr(start_owner, "resolve_material_learning_plan_for_request", resolve)
    step = SimpleNamespace(
        step_run_id="steprun_" + "e" * 32,
        step_key="learn",
        step_type="agent",
        worker_role="support",
        result_schema="material-learning-result@2.0",
        attempt=1,
        state="READY",
        platform_job_id=None,
    )
    make_step = Mock(return_value=step)
    monkeypatch.setattr(start_owner, "create_step_run", make_step)
    monkeypatch.setattr(start_owner, "record_workflow_event", Mock())
    enqueue = Mock(
        return_value=(SimpleNamespace(command_id="wfcmd_" + "f" * 32, state="PENDING"), True)
    )
    monkeypatch.setattr(start_owner, "enqueue_command", enqueue)
    submitted = start_owner.submit_material_learning_workflow(
        session,
        definition=definition(),
        work=request.work_input,
        operator_id=OPERATOR,
        idempotency_key="synthetic-new-ready-role",
        source_authorizer=owner,
        expected_preset=SimpleNamespace(),
    )
    assert submitted.workflow_id == workflow.workflow_id
    assert create.call_args.kwargs["request"] == request
    assert resolve.call_args.kwargs["request"] == worker
    assert make_step.call_args.kwargs["result_schema"] == "material-learning-result@2.0"
    assert enqueue.call_args.kwargs["source"] == "material_learning"
    assert owner.authorize_future_input.call_count == 3
    owner.reauthorize.assert_not_called()


@pytest.mark.parametrize("kind", ["discovery", "native"])
def test_actual_runner_executor_selects_new_context_and_native_only_guidance(monkeypatch, kind):
    _, worker, _ = requested(kind)
    executor = object.__new__(PlatformRoleJobExecutor)
    session = Mock()
    executor.sessions = lambda: nullcontext(session)
    executor.orchestrator = Mock()
    executor.workflow_settings = SimpleNamespace()
    executor.creative_page_publisher = Mock()
    executor.similarity_context_provider = None
    context = Mock()
    prepare = Mock(return_value=context)
    monkeypatch.setattr(engine_owner, "prepare_material_learning_execution_context", prepare)
    monkeypatch.setattr(engine_owner, "read_platform_role_result", Mock(return_value="observed"))
    step = SimpleNamespace(
        step_run_id="steprun_" + "e" * 32,
        step_key="learn",
        worker_role="support",
        result_schema="material-learning-result@2.0",
        attempt=1,
        input_pointer_manifest={},
    )
    workflow = SimpleNamespace(workflow_id="workflow_" + "d" * 32, definition_version="2.0.0")
    result = executor.execute(
        workflow=workflow,
        step=step,
        request=worker,
        upstream=(),
        idempotency_key="synthetic-runner-prompt",
        prompt_text="untrusted placeholder",
    )
    assert result == "observed"
    assert prepare.call_args.kwargs["request"] == worker
    submitted = executor.orchestrator.submit_workflow_role.call_args.kwargs
    assert submitted["material_learning"] is context
    assert submitted["prompt_path"] is None
    assert ("EVERY allowed_picture_use_id exactly once" in submitted["prompt_text"]) == (
        kind == "native"
    )


@pytest.mark.parametrize("exact_score", [False, True])
def test_materialization_reuses_verified_base_pages_and_analysis_size_limits(
    monkeypatch, tmp_path, exact_score
):
    work, root, session, _ = page_fixture(tmp_path)
    worker = MaterialLearningWorkerRequestV2(work_input=work, native_visual_scope=None)
    selected = plan_for(worker)
    if exact_score:
        from eom_workflow.material_learning_request import MaterialLearningWorkerRequestV3

        from tests.unit.test_material_learning_execution_v3 import plan_for as score_plan

        worker = MaterialLearningWorkerRequestV3(
            work_input=work, native_visual_scope=None, native_printed_score=None
        )
        selected = score_plan(worker)
    session.records[(materializer.ResolvedExecutionPlanRecord, selected.plan_id)] = record(selected)
    monkeypatch.setattr(materializer, "_authorized_step_bundle_revisions", lambda *_: frozenset())
    expected = frozenset(page.image.artifact_revision_id for page in work.pages)
    assert (
        materializer.authorized_execution_artifact_revisions(
            session, plan_id=selected.plan_id, step_key="learn"
        )
        == expected
    )
    monkeypatch.setattr(
        materializer,
        "_instruction_manifest",
        Mock(
            return_value=SimpleNamespace(
                components=tuple(
                    SimpleNamespace(
                        layer=layer, relative_path=f"instructions/{layer}.md", artifact=None
                    )
                    for layer in ("PLATFORM", "ROLE")
                )
            )
        ),
    )
    monkeypatch.setattr(materializer, "_reference_manifest", Mock(return_value=None))
    monkeypatch.setattr(
        materializer, "_materialize_member", Mock(return_value=b"# synthetic instruction")
    )
    budget = Mock(wraps=materializer._require_total_size)
    monkeypatch.setattr(materializer, "_require_total_size", budget)
    workspace = tmp_path / "worker"
    workspace.mkdir(mode=0o2770)
    workspace.chmod(0o2770)
    result = materializer.materialize_execution_step(
        session,
        plan_id=selected.plan_id,
        step_key="learn",
        workspace=workspace,
        canonical_artifact_root=root,
        worker_group_id=os.getgid(),
        authorized_artifact_revision_ids=expected,
    )
    assert result.plan_sha256 == selected.plan_sha256
    assert (workspace / "source/material/main/page-000031.png").is_file()
    assert (workspace / "codex-image-inputs.json").is_file()
    assert all(call.kwargs["analysis"] is True for call in budget.call_args_list)
