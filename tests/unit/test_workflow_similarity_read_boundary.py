"""Real SQLite roots/private Unix transport; current IAM/source/member ports are synthetic.

No privileged DB role, real corpus, native QUERY, worker/model, NAS or installed
service is admitted. The existing physical source/member tests retain that scope.
"""

from __future__ import annotations

import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_materials import build_similarity_materials
from eom_catalog_contracts.workflow_similarity_read import (
    MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
    WorkflowSimilarityReadReply,
    WorkflowSimilarityReadRequest,
    WorkflowSimilarityRoleSelection,
)
from eom_catalog_service import workflow_similarity_read_service as service_module
from eom_catalog_service.similarity_read_runtime import (
    SimilarityReaderRuntimeError,
    build_catalog_workflow_similarity_reads,
)
from eom_catalog_service.workflow_similarity_read_dispatch import (
    dispatch_workflow_similarity_read_frame,
)
from eom_catalog_service.workflow_similarity_read_service import (
    CatalogWorkflowSimilarityReadService,
    WorkflowSimilarityReadServiceError,
)
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.similarity_materialization import (
    SimilarityWorkspaceMaterials,
    resolve_similarity_materials,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow.similarity_control import parse_supported_similarity_execution_plan
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.settings import WorkflowSettings
from eom_workflow_runner.similarity_role_catalog_client import (
    CatalogSocketSimilarityRoleContextProvider,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_similarity_workflow_role_context import workflows as workflows
from tests.unit.test_workflow_composition import _platform_settings, _workflow_settings
from tests.unit.test_workflow_similarity_read_contract import pair


@pytest.fixture
def source_rpc(workflows, tmp_path, monkeypatch):
    value = workflows
    payloads, calls, hooks = {}, [], []
    with value.sessions() as session:
        for pointer in value.pointers:
            row = session.get(WorkflowInstanceRecord, pointer.query_id)
            query = parse_supported_reference_query_workflow_request(row.initial_request)
            raw = deepcopy(value.template.case["context"].model_dump(mode="json"))
            raw["request"] = query.context_request.model_dump(mode="json")
            for view in raw["population"]["views"]:
                view["reason"] = "QUERY_NOT_OFFERED"
            context = parse_similarity_context(seal(raw, "context_sha256"))
            materials = build_similarity_materials(
                context,
                anchor_profile=value.template.case["anchor_profile"],
                entries=value.template.case["reference_entries"],
            )
            payloads[pointer.item_id] = SimilarityWorkspaceMaterials(
                canonical_json_bytes(context.model_dump(mode="json")),
                canonical_json_bytes(materials.model_dump(mode="json")),
            )

    def materialized(session, **arguments):
        root = session.get_transaction()
        assert root is not None and root.is_active and not session.in_nested_transaction()
        context = arguments["context"]
        assert context.operator_id in {pointer.operator_id for pointer in value.pointers}
        calls.append((session, root, context.operator_id, context.workflow_id))
        if hooks:
            hooks.pop(0)()
        return payloads[context.workflow_id]

    monkeypatch.setattr(service_module, "resolve_similarity_materials", materialized)
    service = CatalogWorkflowSimilarityReadService(value.owner)
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    # Real kernel peer is the test process, not the installed runner identity.
    server.workflow_runner_uid = os.getuid()
    server.workflow_similarity_reads = service
    server.chat_owner_uid = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            value=value,
            service=service,
            server=server,
            calls=calls,
            hooks=hooks,
            payloads=payloads,
            provider=CatalogSocketSimilarityRoleContextProvider(
                ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def role_read(data, pointer):
    with data.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        step = session.get(WorkflowStepRunRecord, pointer.step_id)
        context = data.provider.prepare(
            session,
            workflow=workflow,
            step=step,
            request=data.value.requests[pointer.item_id].worker_request(),
        )
        record = session.get(ResolvedExecutionPlanRecord, context.reader.selection.plan_id)
        plan = parse_supported_similarity_execution_plan(record.canonical_document)
        root = session.get_transaction()
        result = resolve_similarity_materials(
            session,
            plan=plan,
            step_key=step.step_key,
            context=context,
            original_source=context.request.anchor.source,
            canonical_artifact_root=data.value.owner.settings.nas_artifact_root,
            authorized_artifact_revision_ids=frozenset(
                {plan.similarity_delivery.context_member.artifact_revision_id}
            ),
        )
        assert session.get_transaction() is root and not session.new and not session.dirty
        return result, root


def wire_for(data, pointer):
    with data.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        pin = workflow.runtime_context["execution_plan"]
        return WorkflowSimilarityReadRequest(
            schema_version="system-rag-workflow-similarity-read-request/1.0",
            operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
            selection=WorkflowSimilarityRoleSelection(
                workflow_id=pointer.item_id,
                step_run_id=pointer.step_id,
                plan_id=pin["plan_id"],
                plan_sha256=pin["plan_sha256"],
                query=pointer.selection,
            ),
        )


def test_ordinary_runner_reauthorizes_over_real_socket_without_catalog_session_or_files(source_rpc):
    data, pointer = source_rpc, source_rpc.value.pointers[0]
    result, root = role_read(data, pointer)
    assert result == data.payloads[pointer.item_id]
    assert len(data.calls) == 1 and data.calls[0][1] is not root
    assert all(observation[2] is data.calls[0][1] for observation in data.value.observations)
    assert role_read(data, pointer)[0] == result
    assert len(data.calls) == 2  # No cached authorization/materialization replay.
    assert vars(data.provider) == {"endpoint": data.provider.endpoint}


def test_one_shared_client_keeps_concurrent_operators_and_roots_separate(source_rpc):
    data = source_rpc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda pointer: role_read(data, pointer), data.value.pointers))
    assert {call[2] for call in data.calls} == {p.operator_id for p in data.value.pointers}
    assert data.calls[0][1] is not data.calls[1][1]
    for pointer, result in zip(data.value.pointers, results, strict=True):
        assert result[0] == data.payloads[pointer.item_id]


@pytest.mark.parametrize("attempt", (2, 3))
def test_review_feedback_rounds_keep_the_original_exact_query(source_rpc, attempt):
    data, pointer = source_rpc, source_rpc.value.pointers[1]
    with data.value.sessions.begin() as session:
        session.get(WorkflowStepRunRecord, pointer.step_id).attempt = attempt
        session.get(WorkflowInstanceRecord, pointer.item_id).rework_cycle_count = attempt - 1
    assert role_read(data, pointer)[0] == data.payloads[pointer.item_id]
    assert data.calls[-1][2:] == (pointer.operator_id, pointer.item_id)


@pytest.mark.parametrize("fault", ("operator", "request"))
def test_substituted_reply_does_not_reach_the_role_workspace(source_rpc, fault):
    data, pointer = source_rpc, source_rpc.value.pointers[0]
    original_read = data.service.read

    def substituted(request):
        reply = original_read(request)
        return reply.model_copy(
            update={
                "operator_id" if fault == "operator" else "request_sha256": data.value.pointers[
                    1
                ].operator_id
                if fault == "operator"
                else "sha256:" + "0" * 64
            }
        )

    data.service.read = substituted
    with pytest.raises(ControlPlaneError):
        role_read(data, pointer)
    assert len(data.calls) == 1


def test_fixed_catalog_server_identity_is_checked_before_source_read(source_rpc):
    data = source_rpc
    endpoint = data.provider.endpoint
    data.provider = CatalogSocketSimilarityRoleContextProvider(
        replace(endpoint, owner_uid=endpoint.owner_uid + 1)
    )
    with pytest.raises(ControlPlaneError) as caught:
        role_read(data, data.value.pointers[0])
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    assert not data.calls


@pytest.mark.parametrize("fault", ("plan", "foreign_step", "foreign_query", "stopped", "missing"))
def test_catalog_rejects_stale_or_foreign_role_bindings_before_materialization(source_rpc, fault):
    data = source_rpc
    first, second = data.value.pointers
    request = wire_for(data, first)
    raw = request.model_dump(mode="json")
    if fault == "plan":
        raw["selection"]["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "foreign_step":
        raw["selection"]["step_run_id"] = second.step_id
    elif fault == "foreign_query":
        raw["selection"]["query"] = second.selection.model_dump(mode="json")
    elif fault == "missing":
        raw["selection"]["workflow_id"] = "workflow_" + "0" * 32
    else:
        with data.value.sessions.begin() as session:
            session.get(WorkflowInstanceRecord, first.item_id).state = "CANCELLED"
    with pytest.raises(WorkflowSimilarityReadServiceError):
        data.service.read(WorkflowSimilarityReadRequest.model_validate(raw))
    assert not data.calls


def test_role_cancelled_during_source_read_is_rejected_before_reply(source_rpc):
    data, pointer = source_rpc, source_rpc.value.pointers[0]

    def cancelled():
        with data.value.sessions.begin() as session:
            session.get(WorkflowInstanceRecord, pointer.item_id).state = "CANCELLED"

    data.hooks.append(cancelled)
    with pytest.raises(ControlPlaneError):
        role_read(data, pointer)
    assert len(data.calls) == 1


def test_current_identity_failure_never_uses_prior_success(source_rpc):
    data, pointer = source_rpc, source_rpc.value.pointers[0]
    role_read(data, pointer)
    data.value.owner.identity.fence_current_operator.side_effect = OperatorAuthorizationFenceError(
        "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
    )
    with pytest.raises(ControlPlaneError) as caught:
        role_read(data, pointer)
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    assert len(data.calls) == 1


@pytest.mark.parametrize("peer", ("api", "chat", "worker"))
def test_other_peers_cannot_use_runner_operation(source_rpc, peer):
    data = source_rpc
    data.server.workflow_runner_uid = os.getuid() + 200000
    if peer == "api":
        data.server.allowed_uid = os.getuid()
    elif peer == "chat":
        data.server.chat_owner_uid = os.getuid()
    with pytest.raises(ControlPlaneError) as caught:
        role_read(data, data.value.pointers[0])
    assert caught.value.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
    assert not data.calls
    data.value.owner.identity.fence_current_operator.assert_not_called()


def test_runner_peer_cannot_call_other_catalog_operations(source_rpc):
    data = source_rpc
    left, right = socket.socketpair()
    try:
        assert data.server.peer_is_allowed(left)
        assert data.server.peer_can_operate(left, "READ_WORKFLOW_SIMILARITY_MATERIALS")
        for operation in (
            "GET_ITEM_CONTENT",
            "READ_SIMILARITY_CONTEXT",
            "CHAT_RAG",
            "CREATE_KNOWLEDGE_ANALYSIS",
        ):
            assert not data.server.peer_can_operate(left, operation)
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("fault", ("oversize", "duplicate", "extra_actor", "two_lines", "invalid"))
def test_invalid_frames_do_not_call_owner_or_echo_private_values(fault):
    request, _ = pair()
    raw = canonical_json_bytes(request) + b"\n"
    if fault == "oversize":
        raw = b"x" * (MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES + 1)
    elif fault == "duplicate":
        raw = raw.replace(b'"selection":', b'"selection":{},"selection":', 1)
    elif fault == "extra_actor":
        raw = (
            canonical_json_bytes(request.model_dump(mode="json") | {"actor_id": "do-not-echo"})
            + b"\n"
        )
    elif fault == "two_lines":
        raw += raw
    else:
        raw = b'{"private":"do-not-echo"\n'
    service = SimpleNamespace(read=Mock())
    response = dispatch_workflow_similarity_read_frame(service, raw)
    reply = WorkflowSimilarityReadReply.model_validate_json(response)
    assert reply.status == "FAILED" and reply.context is None and reply.materials is None
    assert reply.operator_id is None and reply.request_sha256 is None
    assert b"do-not-echo" not in response
    service.read.assert_not_called()


def test_separate_runtime_opt_in_does_not_reuse_api_flag_or_open_owner_on_disable():
    assert build_catalog_workflow_similarity_reads(mode="DISABLED", context_reads=None) is None
    for mode in ("ENABLED", "TRUE", ""):
        with pytest.raises(SimilarityReaderRuntimeError):
            build_catalog_workflow_similarity_reads(mode=mode, context_reads=None)


@pytest.mark.parametrize("enabled", (False, True))
def test_actual_ordinary_composition_uses_unprivileged_socket_provider_only_if_enabled(
    tmp_path, enabled
):
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://")
    try:
        runtime = build_workflow_runtime(
            engine=engine,
            workflow_settings=replace(
                _workflow_settings(tmp_path),
                similarity_read_mode="ENABLED" if enabled else "DISABLED",
            ),
            platform_settings=_platform_settings(tmp_path),
        )
        provider = runtime.runner.executor.similarity_context_provider
        assert (
            isinstance(provider, CatalogSocketSimilarityRoleContextProvider)
            if enabled
            else provider is None
        )
        assert runtime.runner.reference_query_owner is None
        assert runtime.runner.reference_query_executor is None
    finally:
        engine.dispose()


def test_environment_mode_is_closed_and_default_off(monkeypatch):
    monkeypatch.delenv("EOM_WORKFLOW_SIMILARITY_READ_MODE", raising=False)
    assert WorkflowSettings.from_environment().similarity_read_mode == "DISABLED"
    monkeypatch.setenv("EOM_WORKFLOW_SIMILARITY_READ_MODE", "ENABLED")
    assert WorkflowSettings.from_environment().similarity_read_mode == "ENABLED"
    monkeypatch.setenv("EOM_WORKFLOW_SIMILARITY_READ_MODE", "yes")
    with pytest.raises(ValueError):
        WorkflowSettings.from_environment()
