"""Closed source-authorization protocol and real private Unix transport.

The persisted rows/source port are synthetic; no model, live DB or NAS is used.
"""

from __future__ import annotations

import os
import threading
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.external_item_learning_authorization import (
    MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES,
    ExternalItemLearningAuthorizationReply,
    ExternalItemLearningAuthorizationRequest,
    ExternalItemLearningRoleSelection,
    validate_external_item_learning_authorization_reply,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.external_creative_learning_source import (
    ExternalCreativeLearningSourceError,
)
from eom_catalog_service.external_item_learning_authorization_dispatch import (
    dispatch_external_item_learning_authorization_frame,
)
from eom_catalog_service.external_item_learning_authorization_service import (
    CatalogExternalItemLearningAuthorizationService,
    ExternalItemLearningAuthorizationServiceError,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_workflow.control_plane import parse_creative_learning_execution_plan
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.models import ExternalItemLearningWorkerRequest, WorkflowRequest
from eom_workflow_runner import external_item_learning_catalog_client as client_module
from eom_workflow_runner.external_item_learning_catalog_client import (
    CatalogExternalItemLearningSourceReader,
    prepare_external_item_learning_execution_context,
)
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_external_item_learning_execution import _record


def _case(*, successor=False):
    record = _record(successor=successor)
    plan = parse_creative_learning_execution_plan(record.canonical_document)
    profile = creative_learning_profile(plan.workflow_definition_version)
    worker_request = ExternalItemLearningWorkerRequest(work_input=plan.work_input)
    request = ExternalItemLearningAuthorizationRequest(
        schema_version="external-item-learning-authorization-request/1.0",
        operation="AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
        selection=ExternalItemLearningRoleSelection(
            workflow_id=plan.workflow_id,
            step_run_id="steprun_" + "0" * 32,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            work_input_sha256=plan.work_input.request_sha256,
        ),
    )
    workflow_request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key=profile.preset_key,
        external_item_learning_work=plan.work_input,
    ).model_dump(mode="json", exclude_none=True)
    workflow = SimpleNamespace(
        workflow_id=plan.workflow_id,
        definition_key="external-item-learning",
        definition_version=profile.definition_version,
        definition_hash=plan.workflow_definition_sha256,
        role_schema_version=profile.role_protocol,
        created_actor_type="human",
        created_actor_id="operator_" + "1" * 32,
        stage="KNOWLEDGE_ANALYSIS",
        initial_request=workflow_request,
        request_payload=deepcopy(workflow_request),
    )
    step = SimpleNamespace(
        step_run_id=request.selection.step_run_id,
        workflow_id=workflow.workflow_id,
        step_key="extract",
        step_type="agent",
        worker_role="support",
        result_schema=profile.result_schema,
        attempt=1,
        state="RUNNING",
    )
    rows = {
        WorkflowInstanceRecord: workflow,
        WorkflowStepRunRecord: step,
        ResolvedExecutionPlanRecord: record,
    }
    session = Mock()
    session.get.side_effect = lambda model, _identity, **_kwargs: rows.get(model)
    service = object.__new__(CatalogExternalItemLearningAuthorizationService)
    service.sessions = SimpleNamespace(begin=lambda: nullcontext(session))
    service.source = Mock()
    service.source.reauthorize.return_value = plan.work_input.source
    return SimpleNamespace(
        request=request,
        plan=plan,
        record=record,
        worker_request=worker_request,
        workflow=workflow,
        step=step,
        rows=rows,
        session=session,
        service=service,
    )


def test_authorization_schema_is_pinned_and_has_no_actor_override():
    root = Path(__file__).resolve().parents[2]
    entry = CATALOG_SCHEMA_RESOURCES["external-item-learning-authorization-v1"]
    raw = (root / entry.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == entry.sha256
    Draft202012Validator.check_schema(load_schema("external-item-learning-authorization-v1"))
    value = _case()
    reply = value.service.authorize(value.request)
    validate_external_item_learning_authorization_reply(
        value.request, reply, expected_source_input_sha256=value.plan.work_input.source.input_sha256
    )
    assert set(value.request.model_dump()) == {"schema_version", "operation", "selection"}
    assert reply.status == "SUCCESS"
    assert (
        value.service.source.reauthorize.call_args.kwargs["operator_id"]
        == value.workflow.created_actor_id
    )


def test_runner_context_uses_exact_step_plan_and_existing_page_owner():
    value = _case()
    value.session.scalar.return_value = value.record
    publisher = Mock()
    context = prepare_external_item_learning_execution_context(
        value.session,
        workflow=value.workflow,
        step=value.step,
        request=value.worker_request,
        publisher=publisher,
    )
    assert context.page_publisher is publisher
    assert context.source_authorizer.selection == value.request.selection
    assert value.service.source.reauthorize.call_count == 0


@pytest.mark.parametrize("successor", [False, True])
@pytest.mark.parametrize("fault", [None, "role_family", "result_family", "definition_family"])
def test_catalog_authorization_accepts_exact_released_families_not_mixed_versions(successor, fault):
    value = _case(successor=successor)
    other = creative_learning_profile("1.0.0" if successor else "2.0.0")
    if fault == "role_family":
        value.workflow.role_schema_version = other.role_protocol
    elif fault == "result_family":
        value.step.result_schema = other.result_schema
    elif fault == "definition_family":
        value.workflow.definition_version = other.definition_version
        value.workflow.role_schema_version = other.role_protocol
        value.step.result_schema = other.result_schema
    if fault:
        with pytest.raises(ExternalItemLearningAuthorizationServiceError):
            value.service.authorize(value.request)
        value.service.source.reauthorize.assert_not_called()
    else:
        assert value.service.authorize(value.request).status == "SUCCESS"
        assert value.service.source.reauthorize.call_args.kwargs["operator_id"] == (
            value.workflow.created_actor_id
        )


@pytest.mark.parametrize(
    "field", ["operator_id", "permissions", "actor_id", "session_id", "path", "source"]
)
def test_authorization_request_cannot_supply_authority(field):
    raw = _case().request.model_dump(mode="json")
    raw[field] = "not-authority"
    with pytest.raises((ValueError, SchemaError)):
        ExternalItemLearningAuthorizationRequest.model_validate(raw)


@pytest.mark.parametrize(
    "fault", ["missing_hash", "partial_failure", "wrong_source", "wrong_request"]
)
def test_reply_cannot_cross_input_or_turn_into_partial_success(fault):
    value = _case()
    raw = value.service.authorize(value.request).model_dump(mode="json")
    if fault == "missing_hash":
        raw["request_sha256"] = None
    elif fault == "partial_failure":
        raw["status"] = "FAILED"
        raw["error_code"] = "EXTERNAL_CREATIVE_AUTHORIZATION_SOURCE_STALE"
    elif fault == "wrong_source":
        raw["source_input_sha256"] = "sha256:" + "0" * 64
    else:
        raw["request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises((ValueError, SchemaError)):
        validate_external_item_learning_authorization_reply(
            value.request,
            ExternalItemLearningAuthorizationReply.model_validate(raw),
            expected_source_input_sha256=value.plan.work_input.source.input_sha256,
        )


@pytest.mark.parametrize(
    "fault", ["missing", "owner", "definition", "step", "role", "attempt", "plan", "hash", "input"]
)
def test_binding_rejection_precedes_any_source_read(fault):
    value = _case()
    if fault == "missing":
        value.rows[WorkflowInstanceRecord] = None
    elif fault == "owner":
        value.workflow.created_actor_type = "worker"
    elif fault == "definition":
        value.workflow.definition_key = "customer-support"
    elif fault == "step":
        value.step.workflow_id = "workflow_" + "0" * 32
    elif fault == "role":
        value.step.worker_role = "authoring"
    elif fault == "attempt":
        value.step.attempt = 2
    elif fault == "plan":
        value.record.workflow_id = "workflow_" + "0" * 32
    elif fault == "hash":
        value.record.plan_sha256 = "sha256:" + "0" * 64
    else:
        value.workflow.request_payload = {}
    with pytest.raises(ExternalItemLearningAuthorizationServiceError) as error:
        value.service.authorize(value.request)
    assert error.value.code == "EXTERNAL_CREATIVE_AUTHORIZATION_BINDING_INVALID"
    value.service.source.reauthorize.assert_not_called()


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"{}\n{}\n",
        b'{"selection": 1.5}\n',
        b'{"x":1,"x":2}\n',
        b"\xff\n",
        b"x" * (MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES + 1),
    ],
)
def test_bad_frames_never_reach_the_service(raw):
    service = Mock()
    reply = ExternalItemLearningAuthorizationReply.model_validate_json(
        dispatch_external_item_learning_authorization_frame(service, raw)
    )
    assert reply.status == "FAILED" and reply.request_sha256 is None
    service.authorize.assert_not_called()


@pytest.fixture(params=[False, True], ids=["original", "source-visual"])
def authorization_socket(request, tmp_path):
    value = _case(successor=request.param)
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.workflow_runner_uid = os.getuid()
    server.external_item_learning_authorization = value.service
    server.chat_owner_uid = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    value.server = server
    value.endpoint = ChatSocketEndpoint(server.socket_path, os.geteuid(), os.getegid())
    try:
        yield value
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_private_socket_reauthorizes_every_time_with_stored_owner(authorization_socket):
    value = authorization_socket
    reader = CatalogExternalItemLearningSourceReader(
        value.request.selection, value.worker_request, endpoint=value.endpoint
    )
    reader(value.worker_request)
    assert (
        value.service.source.reauthorize.call_args.kwargs["operator_id"]
        == value.workflow.created_actor_id
    )
    value.service.source.reauthorize.side_effect = ExternalCreativeLearningSourceError(
        "EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED"
    )
    with pytest.raises(ControlPlaneError) as error:
        reader(value.worker_request)
    assert error.value.code == "CONTROL_CREATIVE_SOURCE_AUTHORIZATION_FAILED"
    assert value.service.source.reauthorize.call_count == 2


def test_api_peer_cannot_use_the_runner_only_read(authorization_socket):
    value = authorization_socket
    value.server.allowed_uid = os.getuid()
    value.server.workflow_runner_uid = os.getuid() + 100001
    reader = CatalogExternalItemLearningSourceReader(
        value.request.selection, value.worker_request, endpoint=value.endpoint
    )
    with pytest.raises(ControlPlaneError) as error:
        reader(value.worker_request)
    assert error.value.code == "CONTROL_CREATIVE_SOURCE_AUTHORITY_UNAVAILABLE"
    value.service.source.reauthorize.assert_not_called()


def test_reader_refuses_a_reply_for_another_request(monkeypatch):
    value = _case()
    raw = value.service.authorize(value.request).model_dump(mode="json")
    raw["request_sha256"] = "sha256:" + "0" * 64
    exchange = Mock(return_value=raw)
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    reader = CatalogExternalItemLearningSourceReader(
        value.request.selection,
        value.worker_request,
        endpoint=ChatSocketEndpoint(Path("/synthetic/socket"), 1, 1),
    )
    with pytest.raises(ControlPlaneError, match="reply differs"):
        reader(value.worker_request)
    assert (
        len(canonical_json_bytes(exchange.call_args.args[1]))
        < MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES
    )
