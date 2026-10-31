"""Actual stored SQLite roles + kernel UDS peer; current QUERY/material IO is synthetic.

Actual pinned-member IO and question/report capture have separate bounded tests.
No native execution, production DB, NAS or user credential is used here.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.public_workflow_similarity_read import (
    PublicWorkflowSimilarityReadRequest,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_contracts.workflow_similarity_read import WorkflowSimilarityReadRequest
from eom_catalog_service import workflow_similarity_read_service as service_module
from eom_catalog_service.similarity_read_runtime import build_catalog_workflow_similarity_reads
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_catalog_service.workflow_similarity_read_service import (
    CatalogWorkflowSimilarityReadService,
)
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.public_similarity_materialization import (
    PublicSimilarityMaterializationContext,
    resolve_public_similarity_materials,
)
from eom_workflow.control_plane import ResolvedExecutionPlanV19
from eom_workflow.public_similarity_control import (
    bind_public_similarity_execution_plan,
    parse_public_similarity_execution_plan,
)
from eom_workflow.reference_query_execution import parse_supported_reference_query_workflow_request
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.similarity_role_catalog_client import (
    CatalogSocketSimilarityRoleContextProvider,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.public_similarity_materialization_fixtures import public_materialization_case
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_public_solution_reference_query_execution import public_workflow_case
from tests.unit.test_registered_public_reference_query_execution import (
    registered_public_workflow_case,
)
from tests.unit.test_similarity_workflow_role_context import workflows as workflows


@pytest.fixture(params=(False, True))
def public_rpc(workflows, request, tmp_path, monkeypatch):
    value, registered = workflows, request.param
    place = tmp_path / "public-template"
    place.mkdir()
    ordinary = value.template.case["plan"].schema_version == "resolved-execution-plan/24.0"
    case = public_materialization_case(place, monkeypatch, ordinary=ordinary, registered=registered)
    native = (registered_public_workflow_case if registered else public_workflow_case)().request
    selections, calls, hooks = {}, [], []
    with value.sessions.begin() as session:
        for pointer in value.pointers:
            workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
            pin = workflow.runtime_context["execution_plan"]
            record = session.get(ResolvedExecutionPlanRecord, pin["plan_id"])
            raw = deepcopy(record.canonical_document)
            raw.pop("similarity_delivery")
            raw.pop("similarity_reference", None)
            raw.update(schema_version="resolved-execution-plan/19.0", resolver_version="19.0.0")
            raw["content_pack_sha256"] = SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.18"]
            base = ResolvedExecutionPlanV19.model_validate(seal(raw, "plan_sha256"))
            plan = bind_public_similarity_execution_plan(base, case["delivery"], case["context"])
            record.canonical_document = plan.model_dump(mode="json")
            record.plan_sha256 = plan.plan_sha256
            original = parse_supported_reference_query_workflow_request(
                seal(
                    native.model_dump(mode="json")
                    | {
                        "context_request": case["context"].request.model_dump(mode="json"),
                        "operator_audit": native.operator_audit.model_dump(mode="json")
                        | {"operator_id": pointer.operator_id},
                    },
                    "request_sha256",
                )
            )
            query = session.get(WorkflowInstanceRecord, pointer.query_id)
            query.initial_request = original.model_dump(mode="json")
            query.request_payload = original.model_dump(mode="json")
            query.request_hash = original.request_sha256
            selection = CompletedSimilarityQuerySelection(
                workflow_id=query.workflow_id,
                workflow_request_sha256=original.request_sha256,
                context_request_sha256=original.context_request.request_sha256,
            )
            runtime = deepcopy(workflow.runtime_context)
            runtime["execution_plan"]["plan_sha256"] = plan.plan_sha256
            runtime["content_pack"]["version"] = "1.20.18"
            runtime["content_pack"]["release_sha256"] = plan.content_pack_sha256
            runtime["similarity_query"] = selection.model_dump(mode="json")
            workflow.runtime_context = runtime
            selections[pointer.item_id] = selection

    def materialized(session, **arguments):
        root = session.get_transaction()
        assert root and root.is_active and not session.in_nested_transaction()
        calls.append((session, root, arguments["context"].operator_id))
        if hooks:
            hooks.pop(0)()
        return case["payload"]

    monkeypatch.setattr(service_module, "resolve_public_similarity_materials", materialized)
    service = CatalogWorkflowSimilarityReadService(value.owner, public_owner=value.owner)
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.workflow_runner_uid, server.workflow_similarity_reads = os.getuid(), service
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
            case=case,
            selections=selections,
            provider=CatalogSocketSimilarityRoleContextProvider(
                ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
            ),
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def read(data, pointer):
    with data.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        step = session.get(WorkflowStepRunRecord, pointer.step_id)
        context = data.provider.prepare(
            session,
            workflow=workflow,
            step=step,
            request=data.value.requests[pointer.item_id].worker_request(),
        )
        assert isinstance(context, PublicSimilarityMaterializationContext)
        record = session.get(ResolvedExecutionPlanRecord, context.reader.selection.plan_id)
        plan = parse_public_similarity_execution_plan(record.canonical_document)
        root = session.get_transaction()
        result = resolve_public_similarity_materials(
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


def test_public_roles_reauthorize_over_actual_socket_on_every_replay(public_rpc):
    data, pointer = public_rpc, public_rpc.value.pointers[0]
    result, root = read(data, pointer)
    assert result == data.case["payload"]
    assert len(data.calls) == 1 and data.calls[0][1] is not root
    assert read(data, pointer)[0] == result and len(data.calls) == 2


def test_public_concurrent_roles_keep_original_operators_and_roots_separate(public_rpc):
    data = public_rpc
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda pointer: read(data, pointer), data.value.pointers))
    assert {row[2] for row in data.calls} == {
        pointer.operator_id for pointer in data.value.pointers
    }
    assert data.calls[0][1] is not data.calls[1][1]
    assert all(value[0] == data.case["payload"] for value in results)


@pytest.mark.parametrize("attempt", (2, 3))
def test_public_review_rounds_use_original_query_without_another_model(public_rpc, attempt):
    data, pointer = public_rpc, public_rpc.value.pointers[1]
    with data.value.sessions.begin() as session:
        session.get(WorkflowStepRunRecord, pointer.step_id).attempt = attempt
        session.get(WorkflowInstanceRecord, pointer.item_id).rework_cycle_count = attempt - 1
    assert read(data, pointer)[0] == data.case["payload"]


@pytest.mark.parametrize("fault", ("operator", "request", "legacy_reply"))
def test_public_runner_refuses_substituted_or_legacy_reply(public_rpc, fault):
    data = public_rpc
    original = data.service.read_public

    def substitute(request):
        reply = original(request)
        if fault == "legacy_reply":
            return reply.model_copy(
                update={"schema_version": "system-rag-workflow-similarity-read-reply/1.0"}
            )
        return reply.model_copy(
            update={
                "operator_id" if fault == "operator" else "request_sha256": "operator_" + "0" * 32
                if fault == "operator"
                else "sha256:" + "0" * 64
            }
        )

    data.service.read_public = substitute
    with pytest.raises(ControlPlaneError):
        read(data, data.value.pointers[0])


def test_v1_request_cannot_read_public_plan_or_receive_silent_family_upgrade(public_rpc):
    data, pointer = public_rpc, public_rpc.value.pointers[0]
    with data.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        pin = workflow.runtime_context["execution_plan"]
        public = PublicWorkflowSimilarityReadRequest(
            schema_version="system-rag-workflow-similarity-read-request/2.0",
            operation="READ_WORKFLOW_SIMILARITY_MATERIALS",
            selection=dict(
                workflow_id=pointer.item_id,
                step_run_id=pointer.step_id,
                plan_id=pin["plan_id"],
                plan_sha256=pin["plan_sha256"],
                query=data.selections[pointer.item_id],
            ),
        )
    legacy = WorkflowSimilarityReadRequest.model_validate(
        public.model_dump(mode="json")
        | {"schema_version": "system-rag-workflow-similarity-read-request/1.0"}
    )
    with pytest.raises(service_module.WorkflowSimilarityReadServiceError):
        data.service.read(legacy)
    assert not data.calls


@pytest.mark.parametrize("fault", ("plan", "query", "stopped", "creator"))
def test_current_stored_bindings_are_checked_before_public_materialization(public_rpc, fault):
    data, pointer = public_rpc, public_rpc.value.pointers[0]
    with data.value.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, pointer.item_id)
        if fault == "stopped":
            workflow.state = "CANCELLED"
        elif fault == "creator":
            workflow.created_actor_id = "operator_" + "0" * 32
        else:
            runtime = deepcopy(workflow.runtime_context)
            if fault == "plan":
                runtime["execution_plan"]["plan_sha256"] = "sha256:" + "0" * 64
            else:
                runtime["similarity_query"]["workflow_id"] = data.value.pointers[1].query_id
            workflow.runtime_context = runtime
    with pytest.raises(ControlPlaneError):
        read(data, pointer)
    assert not data.calls


def test_missing_explicit_public_owner_never_uses_legacy_owner(public_rpc):
    data = public_rpc
    data.service.public_owner = data.service.public_provider = None
    with pytest.raises(ControlPlaneError):
        read(data, data.value.pointers[0])
    assert not data.calls


@pytest.mark.parametrize("fault", ("cancel", "attempt", "plan_missing"))
def test_late_current_change_cannot_publish_previously_valid_role_materials(public_rpc, fault):
    data, pointer = public_rpc, public_rpc.value.pointers[0]

    def change():
        with data.value.sessions.begin() as other:
            workflow = other.get(WorkflowInstanceRecord, pointer.item_id)
            if fault == "cancel":
                workflow.state = "CANCELLED"
            elif fault == "attempt":
                other.get(WorkflowStepRunRecord, pointer.step_id).attempt += 1
            else:
                other.delete(
                    other.get(
                        ResolvedExecutionPlanRecord,
                        workflow.runtime_context["execution_plan"]["plan_id"],
                    )
                )

    data.hooks.append(change)
    with pytest.raises(ControlPlaneError):
        read(data, pointer)
    assert len(data.calls) == 1


def test_actual_runtime_builder_carries_exact_explicit_public_owner(public_rpc):
    data = public_rpc
    contexts = object.__new__(CatalogSimilarityContextReadService)
    contexts.owner, contexts.public_owner = data.value.owner, data.value.owner
    reader = build_catalog_workflow_similarity_reads(mode="ENABLED", context_reads=contexts)
    assert reader.public_owner is data.value.owner
    assert reader.public_provider.owner is data.value.owner


@pytest.mark.parametrize("peer", ("api", "chat"))
def test_public_successor_does_not_broaden_the_runner_only_peer_operation(public_rpc, peer):
    data = public_rpc
    import socket

    data.server.workflow_runner_uid = os.getuid() + 100001
    data.server.allowed_uid = os.getuid() if peer == "api" else os.getuid() + 100000
    data.server.chat_owner_uid = os.getuid() if peer == "chat" else None
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert not data.server.peer_can_operate(left, "READ_WORKFLOW_SIMILARITY_MATERIALS")
    finally:
        left.close()
        right.close()
