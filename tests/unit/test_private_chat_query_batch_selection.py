"""Canonical selection/controls and real owned Chat; synthetic IAM/document heads, no compute."""

from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from eom_catalog_contracts.private_chat_query_prepare_v2 import PrivateChatQueryPrepareRequestV2
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.models import JobRecord
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.embedding_batch_plan_v17 import build_private_chat_batch_query_context
from eom_workflow.private_chat_query_owner_configuration import (
    PrivateChatQueryPublicServiceConfiguration,
)
from eom_workflow_runner.private_chat_query_batch_selection import CatalogPrivateChatBatchSelection
from sqlalchemy import func, select, update

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_batch_plan_admission import make_private_batch_admission_case
from tests.unit.test_private_chat_query_basis import TEXT


def selection_case(tmp_path, monkeypatch, *, cpu_index=True, publisher=None):
    key = uuid4().hex
    value = make_private_batch_admission_case(
        tmp_path,
        monkeypatch,
        cpu_index=cpu_index,
        publisher=publisher,
        key=key,
        identity_seed=key,
    )
    selection = value.selection
    configuration = PrivateChatQueryPublicServiceConfiguration.model_validate(
        dict(
            schema_version="private-chat-query-owner-configuration/2.0",
            reference_configuration_raw_sha256="sha256:" + "a" * 64,
            corpus_id=selection.corpus_id,
            namespace=value.owners["CPU"].configuration.registry.namespace,
            recipe=selection.recipe,
            source_classes=selection.source_classes,
            native_execution_policy=value.saved_policies["CPU"].member,
            native_execution_policy_sha256=value.policies["CPU"].policy_sha256,
            runtime_bundle=value.bundles["CPU"],
            owner_environment_raw_sha256="sha256:" + "b" * 64,
            cuda_native_execution_policy=value.saved_policies["CUDA"].member,
            cuda_native_execution_policy_sha256=value.policies["CUDA"].policy_sha256,
            routing_policy=value.saved_routing.member,
            routing_policy_sha256=value.routing.policy_sha256,
        )
    )
    request = PrivateChatQueryPrepareRequestV2.model_validate(
        seal(
            dict(
                schema_version="system-rag-private-chat-query-prepare-request/2.0",
                action="PREPARE_PRIVATE_CHAT_QUERY",
                request_id="chatqueryprepare_" + "1" * 32,
                origin=value.origin,
                graph_snapshot=selection.graph_snapshot,
                policy_revision_id=selection.access_policy_revision_id,
                policy_sha256=selection.scope.access_policy_sha256,
            ),
            "request_sha256",
        )
    )
    heads = {
        device: build_private_chat_batch_query_context(selection, device)
        for device in ("CPU", "CUDA")
    }
    captures, scopes = [], []
    for device, owner in value.owners.items():

        def authorize(session, caller, scope, *, expected=device):
            assert session.get_bind() is value.publisher.engine
            assert session.get_transaction().is_active and not session.in_nested_transaction()
            assert caller.operator_id == value.origin.actor_id
            assert scope.namespace == value.owners[expected].configuration.registry.namespace
            scopes.append(expected)
            if value.fault.value == "scope":
                raise ValueError("synthetic-current-source-denial")

        def prepare(session, caller, intent, *, expected=device):
            assert session.get_bind() is value.publisher.engine
            assert caller.operator_id == value.origin.actor_id
            assert intent.query_basis == value.origin.basis
            captures.append(expected)
            return heads[expected]

        monkeypatch.setattr(owner.catalog, "authorize_scope", authorize)
        monkeypatch.setattr(owner.catalog, "prepare_private_chat_context_in_session", prepare)
    arguments = dict(
        cpu=value.owners["CPU"],
        cuda=value.owners["CUDA"],
        publisher=value.publisher,
        configuration=configuration,
        policy=value.routing,
        cpu_policy=value.policies["CPU"],
        cuda_policy=value.policies["CUDA"],
        origin=value.origin,
        source_commit="a" * 40,
        controller_release="b" * 40,
        maximum_sources=selection.query.maximum_sources,
        top_k=selection.query.top_k,
    )
    selector = CatalogPrivateChatBatchSelection(**arguments)
    return NS(**locals())


@pytest.fixture(params=(True, False))
def selected(tmp_path, monkeypatch, request):
    return selection_case(tmp_path, monkeypatch, cpu_index=request.param)


def test_original_pair_is_published_without_question_workflow_or_physical_allocation(selected):
    case = selected
    with case.value.publisher.sessions() as session:
        prior_jobs = set(session.scalars(select(JobRecord.job_id)))
    result = case.selector.prepare(case.request)
    assert result.selection == case.selection
    assert result.parent.selection_manifest == result.manifest
    assert result.context("CUDA") == case.heads["CUDA"]
    assert result.context("CPU") == case.heads["CPU"]
    assert result.allocation_candidate().control_request.purpose == "PRIVATE_CHAT_QUERY"
    assert case.captures == ["CPU", "CUDA"]
    assert TEXT not in repr(result) and TEXT.encode() not in canonical_json_bytes(result.selection)
    assert result.operation.admission.cpu is case.value.owners["CPU"]
    assert not workflow_definition_is_admitted("local-embedding-private-chat-query", "2.0.0")
    with case.value.publisher.sessions() as session:
        new_jobs = []
        for job in session.scalars(select(JobRecord)):
            assert TEXT.encode() not in canonical_json_bytes(job.request)
            if job.job_id not in prior_jobs:
                new_jobs.append(job)
        assert len(new_jobs) == 1
        assert new_jobs[0].task_type == "control_embedding_batch_selection"


def test_exact_replay_keeps_original_selection_without_reading_current_heads(selected):
    case = selected
    first = case.selector.prepare(case.request)
    with case.value.publisher.sessions() as session:
        count = session.scalar(select(func.count()).select_from(JobRecord))
    case.heads.clear()  # Any accidental latest lookup would fail instead of passing this test.
    repeated = case.selector.prepare(case.request)
    assert repeated.manifest == first.manifest
    assert repeated.parent == first.parent and repeated.selection == first.selection
    assert case.captures == ["CPU", "CUDA"]
    with case.value.publisher.sessions() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == count


@pytest.mark.parametrize("change", ("graph", "policy", "options"))
def test_same_original_never_reselects_latest_for_changed_scope(selected, change):
    case = selected
    original = case.selector.prepare(case.request)
    request = case.request
    selector = case.selector
    if change == "options":
        selector = CatalogPrivateChatBatchSelection(**(case.arguments | {"top_k": 7}))
    else:
        body = request.model_dump(mode="json")
        if change == "graph":
            body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
        else:
            body["policy_revision_id"] = "accessrev_" + "f" * 32
        request = PrivateChatQueryPrepareRequestV2.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="PRIVATE_CHAT_BATCH_SELECTION_INVALID"):
        selector.prepare(request)
    assert case.captures == ["CPU", "CUDA"]
    assert case.selector.prepare(case.request).parent == original.parent


@pytest.mark.parametrize("fault", ("identity", "chat", "scope", "public", "producer"))
def test_replay_reauthorizes_current_private_origin_public_sources_and_producer(selected, fault):
    case = selected
    first = case.selector.prepare(case.request)
    case.value.fault.value = fault
    if fault == "chat":
        case.value.chat.repository.revoked = True
    if fault == "producer":
        with case.value.publisher.sessions.begin() as session:
            session.execute(
                update(JobRecord)
                .where(JobRecord.logical_artifact_id == first.manifest.artifact_id)
                .values(status="FAILED")
            )
    expected_error = {
        "identity": OperatorAuthorizationFenceError,
        "chat": ChatError,
        "scope": ValueError,
        "public": ValueError,
        "producer": ControlPlaneError,
    }[fault]
    with pytest.raises(expected_error):
        case.selector.prepare(case.request)
    assert case.captures == ["CPU", "CUDA"]


def test_read_action_never_enters_selection_or_publication(selected):
    case = selected
    body = case.request.model_dump(mode="json") | {"action": "READ_PRIVATE_CHAT_QUERY"}
    request = PrivateChatQueryPrepareRequestV2.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError, match="PRIVATE_CHAT_BATCH_SELECTION_INVALID"):
        case.selector.prepare(request)
    assert case.captures == case.scopes == []


def test_missing_cuda_is_not_relabelled_as_cpu_or_a_public_query(selected):
    case = selected
    context = case.heads["CUDA"]
    body = context.model_dump(mode="json")
    body["views"][0]["index"] = None
    case.heads["CUDA"] = type(context).model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        case.selector.prepare(case.request)


def test_private_scope_requires_actual_origin_even_with_same_actor(selected):
    case = selected
    origin = case.value.origin.model_dump(mode="json")
    origin["runtime_id"] = "chatrt_" + "f" * 32
    origin = seal(origin, "origin_sha256")
    body = case.request.model_dump(mode="json") | {"origin": origin}
    request = PrivateChatQueryPrepareRequestV2.model_validate(seal(body, "request_sha256"))
    with pytest.raises(ValueError):
        case.selector.prepare(request)
    assert case.captures == case.scopes == []


def test_incompatible_device_owners_fail_before_initial_index_capture(selected, monkeypatch):
    case = selected
    owner = case.value.owners["CUDA"]
    changed = replace(
        owner.configuration,
        registry=replace(owner.configuration.registry, corpus_id="corpus_" + "f" * 32),
    )
    monkeypatch.setattr(owner, "configuration", changed)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_BATCH_PLAN_ADMISSION_INVALID"):
        case.selector.prepare(case.request)
    assert case.captures == case.scopes == []
