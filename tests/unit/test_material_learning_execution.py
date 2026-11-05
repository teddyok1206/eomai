"""Source-bound material roles share the existing capacity and Artifact commit owner."""

import json
import os
import socket
from copy import deepcopy
from io import BytesIO
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning_authorization import (
    MaterialLearningAuthorizationReply,
    MaterialLearningAuthorizationRequest,
)
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.material_learning_dispatch import dispatch_material_learning
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.material_learning_execution import (
    MaterialLearningExecutionContext,
    validate_material_learning_execution_plan,
)
from eom_orchestrator.material_learning_plan_resolution import resolve_material_learning_plan
from eom_orchestrator.worker import WorkerRun
from eom_workflow.control_plane import ExecutionPresetRevision, ResolvedExecutionPlanV33
from eom_workflow.material_learning_request import MaterialLearningWorkerRequest
from eom_workflow_runner import material_learning_catalog_client as catalog_client
from pydantic import ValidationError

from tests.unit.test_external_item_learning_execution import _fixture
from tests.unit.test_external_item_learning_execution_resolver import _published_preset, _Session
from tests.unit.test_material_learning_contracts import discovery
from tests.unit.test_material_learning_role_contracts import material_plan


def record(plan):
    return ResolvedExecutionPlanRecord(
        plan_id=plan.plan_id,
        workflow_id=plan.workflow_id,
        preset_id=plan.preset_id,
        preset_revision_id=plan.preset_revision_id,
        capacity_policy_revision_id=plan.capacity_policy_revision_id,
        graph_snapshot_revision_id=None,
        evidence_bundle_revision_id=None,
        canonical_document=plan.model_dump(mode="json"),
        plan_sha256=plan.plan_sha256,
        resolver_version=plan.resolver_version,
        resolved_at=plan.resolved_at,
    )


@pytest.mark.parametrize(
    "field",
    [
        None,
        "workflow_id",
        "plan_sha256",
        "preset_revision_id",
        "graph_snapshot_revision_id",
        "resolved_at",
    ],
)
def test_material_plan_checks_immutable_row_and_full_request(field):
    plan = ResolvedExecutionPlanV33.model_validate(material_plan())
    row = record(plan)
    request = MaterialLearningWorkerRequest(work_input=plan.work_input)
    if field:
        setattr(
            row, field, "graphrev_" + "0" * 32 if field == "graph_snapshot_revision_id" else None
        )
        with pytest.raises(ControlPlaneError):
            validate_material_learning_execution_plan(
                row, workflow_id=plan.workflow_id, step_key="learn", request=request
            )
    else:
        assert (
            validate_material_learning_execution_plan(
                row, workflow_id=plan.workflow_id, step_key="learn", request=request
            )
            == plan
        )


def request():
    plan = ResolvedExecutionPlanV33.model_validate(material_plan())
    return MaterialLearningAuthorizationRequest(
        workflow_id=plan.workflow_id,
        step_run_id="steprun_" + "1" * 32,
        plan_id=plan.plan_id,
        plan_sha256=plan.plan_sha256,
        input_sha256=plan.work_input.input_sha256,
    )


@pytest.mark.parametrize("case", ["success", "denied", "unavailable", "forged_actor"])
def test_authorization_rpc_has_no_browser_or_model_supplied_actor(case):
    selected = request()
    body = selected.model_dump(mode="json")
    service = Mock()
    service.authorize.return_value = MaterialLearningAuthorizationReply(
        status="SUCCESS",
        request_sha256=content_sha256(body),
        input_sha256=selected.input_sha256,
        error_code=None,
    )
    if case == "denied":
        service.authorize.side_effect = ValueError("synthetic denial")
    elif case == "unavailable":
        service.authorize.side_effect = OSError("synthetic unavailable")
    elif case == "forged_actor":
        body["actor_id"] = "operator_" + "0" * 32
        with pytest.raises(ValidationError):
            MaterialLearningAuthorizationRequest.model_validate(body)
    output = BytesIO()
    dispatch_material_learning(
        body, BytesIO(), output, sources=None, intake=None, reads=None, authorizations=service
    )
    raw = json.loads(output.getvalue())
    if case == "forged_actor":
        assert raw["status"] == "ERROR"
        service.authorize.assert_not_called()
    else:
        reply = MaterialLearningAuthorizationReply.model_validate(raw)
        reply.validate_for(selected)
        assert reply.status == ("SUCCESS" if case == "success" else "FAILED")


def fixture(monkeypatch, tmp_path):
    value = _fixture(monkeypatch, tmp_path)
    plan = ResolvedExecutionPlanV33.model_validate(material_plan())
    value.plan = plan
    value.request = MaterialLearningWorkerRequest(work_input=plan.work_input)
    value.context = MaterialLearningExecutionContext(value.source, Mock())
    session = value.orchestrator.sessions().__enter__()
    session.scalar.return_value = record(plan)

    def run(**_values):
        source = value.jobs[0].request
        output = discovery()
        output["input_sha256"] = plan.work_input.input_sha256
        path = tmp_path / "material-result.json"
        body = {
            key: source[key]
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
            status="ok", completed_at="2026-11-05T21:00:00Z", output={"learning_result": output}
        )
        path.write_text(json.dumps(body))
        return WorkerRun(
            0, path, tmp_path / "stdout.log", tmp_path / "stderr.log", "synthetic-material-unit"
        )

    value.worker.run_prepared.side_effect = run
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
        result_schema="material-learning-result@1.0",
        idempotency_key="synthetic-material-role",
        prompt_text="synthetic prompt",
        material_learning=value.context,
    )


def test_prepared_material_runs_through_capacity_and_commit_without_codex(monkeypatch, tmp_path):
    value = fixture(monkeypatch, tmp_path)
    result = execute(value)
    assert result.status == "SUCCEEDED"
    value.worker.run_prepared.assert_called_once()
    assert (
        value.orchestrator.capacity.claim.call_args.args[0].workload_class == "KNOWLEDGE_ANALYSIS"
    )
    value.commit.assert_called_once()
    value.orchestrator.capacity.release.assert_called_once()


@pytest.mark.parametrize("at", [2, 3, 4])
def test_material_revocation_fails_before_commit_without_uncertain_worker(
    monkeypatch, tmp_path, at
):
    value = fixture(monkeypatch, tmp_path)
    value.source.side_effect = [None] * (at - 1) + [ValueError("synthetic revoked input")]
    result = execute(value)
    assert result.status == "FAILED"
    value.commit.assert_not_called()
    assert value.worker.run_prepared.call_count == (1 if at == 4 else 0)
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()


def test_material_resolver_pins_the_exact_released_policy_and_replays_without_latest():
    logical, revision = _published_preset()
    logical.preset_key = "material-learning"
    revision.canonical_document["compatible_workflow_protocols"] = ["workflow-role/1.37.0"]
    revision.compatible_workflow_protocols = ["workflow-role/1.37.0"]
    revision.canonical_document["content_sha256"] = content_sha256(
        {
            key: value
            for key, value in revision.canonical_document.items()
            if key != "content_sha256"
        }
    )
    revision.content_sha256 = revision.canonical_document["content_sha256"]
    preset = ExecutionPresetRevision.model_validate(revision.canonical_document)
    session = _Session(logical, revision)
    expected = ResolvedExecutionPlanV33.model_validate(material_plan())
    arguments = dict(
        workflow_id=expected.workflow_id,
        workflow_definition_sha256=expected.workflow_definition_sha256,
        workflow_role_schema_version="workflow-role/1.37.0",
        work=expected.work_input,
        expected_preset=preset,
    )
    plan = resolve_material_learning_plan(session, **arguments)
    assert len(session.added) == 2
    replay = Mock()
    replay.scalar.return_value = session.added[0]
    assert resolve_material_learning_plan(replay, **arguments) == plan
    altered = deepcopy(arguments)
    altered["workflow_definition_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ControlPlaneError):
        resolve_material_learning_plan(replay, **altered)


def test_material_authorization_is_a_runner_only_socket_purpose():
    server = object.__new__(CatalogApplicationServer)
    server.allowed_uid = os.getuid() + 100001
    server.chat_owner_uid = os.getuid() + 100002
    server.workflow_runner_uid = os.getuid()
    server.material_learning_authorizations = Mock()
    left, right = socket.socketpair()
    try:
        assert server.peer_can_operate(left, "AUTHORIZE_MATERIAL_LEARNING_INPUT")
        assert not server.peer_can_operate(left, "CREATE_MATERIAL_LEARNING")
        server.workflow_runner_uid = os.getuid() + 100003
        server.allowed_uid = os.getuid()
        assert not server.peer_can_operate(left, "AUTHORIZE_MATERIAL_LEARNING_INPUT")
        assert server.peer_can_operate(left, "CREATE_MATERIAL_LEARNING")
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("case", ["success", "wrong_request", "wrong_input", "denied"])
def test_runner_source_reader_rejects_stale_or_foreign_reply(monkeypatch, tmp_path, case):
    selected = request()
    plan = ResolvedExecutionPlanV33.model_validate(material_plan())
    worker = MaterialLearningWorkerRequest(work_input=plan.work_input)
    reply = MaterialLearningAuthorizationReply(
        status="SUCCESS",
        request_sha256=content_sha256(selected.model_dump(mode="json")),
        input_sha256=selected.input_sha256,
        error_code=None,
    ).model_dump(mode="json")
    if case == "wrong_request":
        reply["request_sha256"] = "sha256:" + "0" * 64
    elif case == "wrong_input":
        reply["input_sha256"] = "sha256:" + "0" * 64
    elif case == "denied":
        reply.update(
            status="FAILED", input_sha256=None, error_code="MATERIAL_LEARNING_AUTHORIZATION_FAILED"
        )
    exchange = Mock(return_value=reply)
    monkeypatch.setattr(catalog_client, "exchange_chat_frame", exchange)
    reader = catalog_client.CatalogMaterialLearningSourceReader(
        selected,
        worker,
        endpoint=ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid()),
    )
    if case == "success":
        reader(worker)
        assert "actor_id" not in exchange.call_args.args[1]
    else:
        with pytest.raises(ControlPlaneError):
            reader(worker)
