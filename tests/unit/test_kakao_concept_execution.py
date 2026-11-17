"""Existing Runner/Orchestrator execution with synthetic storage/worker, never Codex or NAS."""

import json
import os
import socket
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_concept_authorization import (
    KakaoConceptAuthorizationReply,
    KakaoConceptAuthorizationRequest,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service.application_server import CatalogApplicationServer
from eom_catalog_service.kakao_concept_authorization import dispatch_kakao_concept_authorization
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.kakao_concept_execution import KakaoConceptExecutionContext
from eom_orchestrator.worker import WorkerRun
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import KakaoConceptWork, KakaoConceptWorkerRequest
from eom_workflow.models import KakaoConceptRoleResultHeader
from eom_workflow.schemas import constrained_result_schema, validate_codex_structured_output_schema
from eom_workflow_runner import engine as engine_owner
from eom_workflow_runner import kakao_concept_catalog_client as client
from eom_workflow_runner.engine import PlatformRoleJobExecutor
from jsonschema import Draft202012Validator

from tests.unit.test_external_item_learning_execution import _fixture
from tests.unit.test_kakao_concept_contracts import (
    ROOT,
    compose_request,
    composed,
    plan,
    plan_request,
    result,
)
from tests.unit.test_kakao_concept_workflow_contracts import message, plan_value, rehash, work_value
from tests.unit.test_material_learning_execution import record


def selection(work=None):
    selected = KakaoConceptExecutionPlan.model_validate(plan_value())
    return KakaoConceptAuthorizationRequest(
        workflow_id=selected.workflow_id,
        step_run_id="steprun_" + "1" * 32,
        plan_id=selected.plan_id,
        plan_sha256=selected.plan_sha256,
        work_sha256=content_sha256(work or selected.work_input),
    )


def success(request):
    return KakaoConceptAuthorizationReply(
        status="SUCCESS",
        request_sha256=content_sha256(request),
        work_sha256=request.work_sha256,
        error_code=None,
    )


def test_authorization_schema_mirror_and_identity_are_closed():
    entry = CATALOG_SCHEMA_RESOURCES["kakao-concept-authorization-v1"]
    canonical = (ROOT / entry.canonical_path).read_bytes()
    assert (
        canonical
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(canonical) == entry.sha256
    assert not set(type(selection()).model_fields) & {
        "operator_id",
        "session_id",
        "task_id",
        "slot_id",
        "role",
        "work_input",
    }


@pytest.mark.parametrize(
    "case", ["success", "denied", "unavailable", "disabled", "foreign", "oversized"]
)
def test_narrow_dispatch_validates_before_authority_and_correlates_reply(case):
    request = selection()
    body = request.model_dump(mode="json")
    service = Mock()
    service.authorize.return_value = success(request)
    if case == "denied":
        service.authorize.side_effect = ValueError("not admitted")
    elif case == "unavailable":
        service.authorize.side_effect = OSError("unavailable")
    elif case in {"foreign", "oversized"}:
        body["operator_id"] = "operator_" + ("a" * 32 if case == "foreign" else "a" * 17000)
        with pytest.raises(ValueError):
            dispatch_kakao_concept_authorization(body, service)
        service.authorize.assert_not_called()
        return
    reply = KakaoConceptAuthorizationReply.model_validate_json(
        dispatch_kakao_concept_authorization(body, None if case == "disabled" else service)
    )
    reply.validate_for(request)
    assert reply.status == ("SUCCESS" if case == "success" else "FAILED")
    if case == "denied":
        assert reply.error_code == "KAKAO_CONCEPT_AUTHORIZATION_FAILED"


@pytest.mark.parametrize("uid", ["runner", "api", "chat", "other"])
def test_socket_purpose_never_grants_api_chat_or_worker_authority(uid):
    server = object.__new__(CatalogApplicationServer)
    server.allowed_uid = os.getuid() + 100001
    server.chat_owner_uid = os.getuid() + 100002
    server.workflow_runner_uid = os.getuid() + 100003
    server.kakao_concept_authorizations = Mock()
    setattr(
        server,
        {
            "runner": "workflow_runner_uid",
            "api": "allowed_uid",
            "chat": "chat_owner_uid",
            "other": "irrelevant",
        }[uid],
        os.getuid(),
    )
    left, right = socket.socketpair()
    try:
        assert server.peer_can_operate(left, "AUTHORIZE_KAKAO_CONCEPT_INPUT") == (uid == "runner")
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize(
    "case", ["success", "request", "work", "denied", "io", "different_work", "extra"]
)
def test_runner_client_has_exact_work_and_typed_transport_failure(monkeypatch, tmp_path, case):
    work = KakaoConceptWork.model_validate(work_value())
    request = selection(work)
    reply = success(request).model_dump(mode="json")
    if case in {"request", "work"}:
        reply[case + "_sha256"] = "sha256:" + "0" * 64
    elif case == "denied":
        reply.update(
            status="FAILED", work_sha256=None, error_code="KAKAO_CONCEPT_AUTHORIZATION_FAILED"
        )
    elif case == "extra":
        reply["allow_network"] = True
    exchange = Mock(
        return_value=reply, side_effect=OSError("unavailable") if case == "io" else None
    )
    monkeypatch.setattr(client, "exchange_chat_frame", exchange)
    reader = client.CatalogKakaoConceptSourceReader(
        request,
        work,
        endpoint=ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid()),
    )
    if case == "success":
        reader(work)
        assert exchange.call_args.kwargs["request_limit"] == 16384
    else:
        with pytest.raises(ControlPlaneError):
            reader(
                work.model_copy(update={"request_bytes": work.request_bytes + 1})
                if case == "different_work"
                else work
            )
    if case == "different_work":
        exchange.assert_not_called()


def fixture(monkeypatch, tmp_path, *, compose=False):
    value = _fixture(monkeypatch, tmp_path)
    request = compose_request() if compose else plan_request()
    work = KakaoConceptWork.model_validate(work_value(request))
    document = plan_value()
    document["work_input"] = work.model_dump(mode="json")
    value.plan = KakaoConceptExecutionPlan.model_validate(rehash(document))
    value.request = KakaoConceptWorkerRequest(work_input=work)
    value.context = KakaoConceptExecutionContext(work, value.source, canonical_json_bytes(request))
    value.orchestrator.sessions().__enter__().scalar.return_value = record(value.plan)

    def run(**_kwargs):
        original = value.jobs[0].request
        body = {
            key: original[key]
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
            status="ok",
            completed_at="2026-11-17T10:00:00Z",
            output=result(request, composed() if compose else plan()),
        )
        value.body = body
        path = tmp_path / "concept-result.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        value.run = WorkerRun(
            0, path, tmp_path / "stdout.log", tmp_path / "stderr.log", "synthetic-concept"
        )
        return value.run

    value.worker.run_prepared.side_effect = run
    return value


def execute(value, **changes):
    return value.orchestrator.submit_workflow_role(
        **(
            dict(
                workflow_id=value.plan.workflow_id,
                step_run_id="steprun_" + "0" * 32,
                step_key="assist",
                attempt=1,
                role="support",
                request=value.request,
                upstream_artifacts=(),
                result_schema="kakao-concepts-result@1.0",
                idempotency_key="synthetic-concept-role",
                prompt_text="synthetic prompt",
                kakao_concepts=value.context,
            )
            | changes
        )
    )


@pytest.mark.parametrize("compose", [False, True])
def test_plan_and_compose_use_existing_claim_prepare_commit_and_small_db_header(
    monkeypatch, tmp_path, compose
):
    value = fixture(monkeypatch, tmp_path, compose=compose)
    job = execute(value)
    assert job.status == "SUCCEEDED", job.error_message
    value.worker.run_prepared.assert_called_once()
    value.worker.run_structured.assert_not_called()
    value.worker.run_resolved_structured.assert_not_called()
    value.commit.assert_called_once()
    assert (
        value.orchestrator.capacity.claim.call_args.args[0].workload_class == "KNOWLEDGE_ANALYSIS"
    )
    assert (
        value.materialize.call_args.kwargs["kakao_concept_authorize"]
        == value.context.authorize_work
    )
    stored = owner_module.create_artifact_records.call_args.kwargs["result"]
    assert "output" not in stored
    assert KakaoConceptRoleResultHeader.model_validate(stored).job_id == job.job_id
    owner_module.stage_structured_artifact.assert_not_called()
    staged = value.commit.call_args.args[0]
    assert "output" in json.loads(staged.result_path.read_bytes())
    assert staged.content_hash == sha256_bytes(staged.result_path.read_bytes())
    value.orchestrator.capacity.release.assert_called_once()


@pytest.mark.parametrize("at", [2, 3, 4, 5, 6])
def test_revocation_prevents_launch_or_adoption_and_releases_only_confirmed_work(
    monkeypatch, tmp_path, at
):
    value = fixture(monkeypatch, tmp_path)
    value.source.side_effect = [None] * (at - 1) + [ValueError("revoked")]
    job = execute(value)
    assert job.status == "FAILED"
    owner_module.create_artifact_records.assert_not_called()
    assert value.worker.run_prepared.call_count == (1 if at >= 4 else 0)
    value.orchestrator.capacity.defer_uncertain_process.assert_not_called()
    if at <= 5:
        value.commit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        dict(kakao_concepts=None),
        dict(attempt=2),
        dict(step_key="support"),
        dict(execution_tier="ESCALATED"),
        dict(material_learning=Mock()),
        dict(role="review"),
    ],
)
def test_context_mixing_or_missing_source_never_falls_back_to_generic_worker(
    monkeypatch, tmp_path, change
):
    value = fixture(monkeypatch, tmp_path)
    with pytest.raises(ControlPlaneError):
        execute(value, **change)
    value.worker.run_prepared.assert_not_called()
    assert value.jobs == []


@pytest.mark.parametrize("change", ["evidence", "page", "quote", "request"])
def test_actual_request_validation_blocks_invented_evidence_page_quote_and_hash(
    monkeypatch, tmp_path, change
):
    value = fixture(monkeypatch, tmp_path, compose=True)
    real_run = value.worker.run_prepared.side_effect

    def tampered(**kwargs):
        run = real_run(**kwargs)
        body = deepcopy(value.body)
        output = body["output"]
        block = output["output"]["blocks"][0]
        if change == "evidence":
            block["citations"][0]["evidence_key"] = "E3"
        elif change == "page":
            block["captures"][0]["page_key"] = "E1P4"
        elif change == "quote":
            block["citations"][0]["quote"] = "존재하지 않는 원문"
        else:
            output["request_sha256"] = "sha256:" + "0" * 64
        run.result_path.write_text(json.dumps(body), encoding="utf-8")
        return run

    value.worker.run_prepared.side_effect = tampered
    job = execute(value)
    assert job.status == "FAILED"
    assert job.error_code == "WORKER_RESULT_INVALID"
    value.commit.assert_not_called()


def test_compose_generation_schema_limits_actual_evidence_and_page_keys():
    request = compose_request()
    context = KakaoConceptExecutionContext(
        KakaoConceptWork.model_validate(work_value(request)), Mock(), canonical_json_bytes(request)
    )
    from eom_workflow.models import RoleWorkerInput

    original = constrained_result_schema(
        "kakao-concepts-result@1.0", RoleWorkerInput.model_validate(message(request))
    )
    narrowed = context.constrain_schema(original)
    validate_codex_structured_output_schema(narrowed)
    Draft202012Validator.check_schema(narrowed)
    assert narrowed["$defs"]["KakaoConcept_capture"]["properties"]["page_key"]["enum"] == ["E1P3"]
    assert narrowed["$defs"]["KakaoConcept_citation"]["properties"]["evidence_key"]["enum"] == [
        "E1"
    ]
    assert "enum" not in original["$defs"]["KakaoConcept_capture"]["properties"]["page_key"]


def test_runner_executor_selects_exact_context_without_default_support_prompt(monkeypatch):
    executor = object.__new__(PlatformRoleJobExecutor)
    executor.sessions = lambda: nullcontext(Mock())
    executor.orchestrator, executor.creative_page_publisher = Mock(), Mock()
    executor.workflow_settings = SimpleNamespace()
    executor.similarity_context_provider = None
    context = Mock()
    prepare = Mock(return_value=context)
    monkeypatch.setattr(engine_owner, "prepare_kakao_concept_execution_context", prepare)
    monkeypatch.setattr(engine_owner, "read_platform_role_result", Mock(return_value="observed"))
    step = SimpleNamespace(
        step_run_id="steprun_" + "e" * 32,
        step_key="assist",
        worker_role="support",
        result_schema="kakao-concepts-result@1.0",
        attempt=1,
        input_pointer_manifest={},
    )
    workflow = SimpleNamespace(workflow_id="workflow_" + "d" * 32)
    request = KakaoConceptWorkerRequest(work_input=work_value())
    assert (
        executor.execute(
            workflow=workflow,
            step=step,
            request=request,
            upstream=(),
            idempotency_key="synthetic-concept-runner",
            prompt_text=None,
        )
        == "observed"
    )
    assert prepare.call_args.kwargs["request"] == request
    submitted = executor.orchestrator.submit_workflow_role.call_args.kwargs
    assert submitted["kakao_concepts"] is context
    assert (
        submitted["prompt_path"] is None
        and "source/concepts/request.json" in submitted["prompt_text"]
    )


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED"])
def test_terminal_replay_never_recalculates_or_rewrites_failed_history(
    monkeypatch, tmp_path, terminal
):
    value = fixture(monkeypatch, tmp_path)
    job = execute(value)
    assert job.status == "SUCCEEDED"
    job.status = terminal  # Synthetic persisted Job; no actual failed history is mutated.
    monkeypatch.setattr(value.orchestrator, "_job_by_idempotency_key", lambda _key: job)
    assert execute(value) is job
    value.worker.run_prepared.assert_called_once()
    value.commit.assert_called_once()
    value.source.side_effect = ValueError("current permission revoked")
    with pytest.raises(ControlPlaneError):
        execute(value)
    assert job.status == terminal
    value.worker.run_prepared.assert_called_once()


def test_confirmed_completed_process_is_revalidated_without_new_model_execution(
    monkeypatch, tmp_path
):
    value = fixture(monkeypatch, tmp_path)
    job = execute(value)
    assert job.status == "SUCCEEDED"
    job.status = "VALIDATING_RESULT"
    monkeypatch.setattr(value.orchestrator, "_job_by_idempotency_key", lambda _key: job)
    value.worker.recover_completed_structured.return_value = value.run
    session = value.orchestrator.sessions().__enter__()
    session.scalar.side_effect = [record(value.plan), None]
    assert execute(value).status == "SUCCEEDED"
    value.worker.recover_completed_structured.assert_called_once()
    value.worker.run_prepared.assert_called_once()


@pytest.mark.parametrize("case", ["success", "step", "revoked", "hash", "noncanonical"])
def test_runner_prepares_exact_authorized_request_before_exposing_it_to_execution(
    monkeypatch, case
):
    request = plan_request()
    work = KakaoConceptWork.model_validate(work_value(request))
    selected = KakaoConceptExecutionPlan.model_validate(plan_value())
    session = Mock()
    session.scalar.return_value = record(selected)
    workflow = SimpleNamespace(workflow_id=selected.workflow_id)
    step = SimpleNamespace(
        workflow_id=selected.workflow_id, step_key="assist", step_run_id="steprun_" + "f" * 32
    )
    factory, reader = Mock(), Mock()
    factory.return_value = reader
    monkeypatch.setattr(client, "CatalogKakaoConceptSourceReader", factory)
    raw = canonical_json_bytes(request)
    if case == "step":
        step.workflow_id = "workflow_" + "0" * 32
    elif case == "revoked":
        reader.side_effect = ControlPlaneError("SOURCE_REVOKED", "synthetic")
    elif case == "hash":
        raw += b" "
    elif case == "noncanonical":
        raw = json.dumps(request.model_dump(mode="json"), indent=2).encode()
    resolve = Mock(return_value=raw)
    monkeypatch.setattr(client, "resolve_control_artifact_member", resolve)
    args = dict(
        workflow=workflow,
        step=step,
        request=KakaoConceptWorkerRequest(work_input=work),
        publisher=Mock(),
    )
    if case == "success":
        context = client.prepare_kakao_concept_execution_context(session, **args)
        assert context.request == request and reader.call_count == 2
        resolve.assert_called_once()
        assert factory.call_args.args[0].work_sha256 == content_sha256(work)
    else:
        with pytest.raises((ValueError, ControlPlaneError)):
            client.prepare_kakao_concept_execution_context(session, **args)
        if case in {"step", "revoked"}:
            resolve.assert_not_called()
