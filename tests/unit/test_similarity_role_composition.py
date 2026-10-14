"""Actual execution wiring under explicit synthetic Session/IAM/QUERY/worker observations."""

from __future__ import annotations

import grp
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_image_contracts import SVG_LABEL_LAYOUT_PACK_BUNDLES
from eom_orchestrator import orchestrator as owner_module
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.models import JobRecord
from eom_orchestrator.orchestrator import Orchestrator
from eom_orchestrator.similarity_materialization import SimilarityMaterializationContext
from eom_workflow.models import WorkerRequest, WorkflowRequest
from eom_workflow_runner import engine as engine_module
from eom_workflow_runner import similarity_role_preparation as preparation_module
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.engine import PlatformRoleJobExecutor
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.repository import workflow_business_fingerprint
from eom_workflow_runner.similarity_role_preparation import CatalogSimilarityRoleContextProvider
from sqlalchemy import create_engine

from scripts.workflow.generate_similarity_reference_pack_v12017 import TARGET
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_execution_materializer import GROUP_ID, _workspace
from tests.unit.test_similarity_execution_materializer import workspace_case
from tests.unit.test_similarity_reference_pack import prompt_case
from tests.unit.test_workflow_composition import _platform_settings, _workflow_settings


def provider_case(tmp_path, monkeypatch, role="authoring"):
    case, record, workflow, step, _old_session = prompt_case(tmp_path, monkeypatch, role=role)
    raw = record.canonical_document | {
        "content_pack_sha256": SVG_LABEL_LAYOUT_PACK_BUNDLES["1.20.17"]
    }
    record.canonical_document = seal(raw, "plan_sha256")
    record.plan_sha256 = record.canonical_document["plan_sha256"]
    workflow.runtime_context["execution_plan"]["plan_sha256"] = record.plan_sha256
    workflow.runtime_context["content_pack"]["release_sha256"] = raw["content_pack_sha256"]
    request = WorkflowRequest.model_validate_json(
        (TARGET / "fixtures/smoke-request.json").read_bytes()
    )
    document = request.model_dump(mode="json") | {
        "educational_retrieval": raw["retrieval_requirement"],
        "execution_preset_key": "standard-item",
    }
    request = WorkflowRequest.model_validate(document)
    workflow.initial_request = document
    workflow.request_payload = deepcopy(document)
    workflow.definition_hash = raw["workflow_definition_sha256"]
    workflow.definition_id = "wfdef_" + "c" * 32
    definition = SimpleNamespace(
        definition_key=workflow.definition_key,
        definition_version=workflow.definition_version,
        definition_hash=workflow.definition_hash,
    )
    workflow.request_hash = workflow_business_fingerprint(definition, request)
    workflow.current_step_key = role
    workflow.role_schema_version = "workflow-role/1.24.0"
    workflow.created_actor_id = "operator_" + "a" * 32
    workflow.created_actor_type = "human"
    workflow.state = "RUNNING"
    step.step_run_id = "steprun_" + "b" * 32
    step.workflow_id = workflow.workflow_id
    step.attempt = 1
    step.result_schema = f"{role}-result@12.0"
    step.state = "RUNNING"
    step.step_type = "agent"
    query = object.__new__(CatalogCompletedReferenceQueryRead)
    # Native QUERY/captured Identity are synthetic here; this is NOT execution admission.
    query.request = SimpleNamespace(
        context_request=case["context"].request,
        operator_audit=SimpleNamespace(operator_id=workflow.created_actor_id),
    )
    query.owner = SimpleNamespace(identity=Mock(), catalog=Mock())
    provider = CatalogSimilarityRoleContextProvider(query)
    rows = {
        WorkflowInstanceRecord: workflow,
        WorkflowStepRunRecord: step,
        ResolvedExecutionPlanRecord: record,
        WorkflowDefinitionRecord: definition,
    }

    class Session:
        def get_transaction(self):
            return SimpleNamespace(is_active=True)

        def in_nested_transaction(self):
            return False

        def get(self, model, identity, **options):
            return rows[model]

    session = Session()
    monkeypatch.setattr(preparation_module, "object_session", lambda value: session)
    return SimpleNamespace(
        case=case,
        record=record,
        workflow=workflow,
        step=step,
        request=request,
        query=query,
        provider=provider,
        session=session,
    )


def prepare(value):
    return value.provider.prepare(
        value.session,
        workflow=value.workflow,
        step=value.step,
        request=value.request.worker_request(),
    )


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_provider_binds_exact_current_creator_and_query_without_running_or_reading_sources(
    tmp_path, monkeypatch, role
):
    value = provider_case(tmp_path, monkeypatch, role)
    before = deepcopy(value.workflow.runtime_context)
    context = prepare(value)
    assert isinstance(context, SimilarityMaterializationContext)
    assert context.workflow_id == value.workflow.workflow_id
    assert context.operator_id == value.workflow.created_actor_id
    assert context.request == value.query.request.context_request
    assert context.reader.caller.operator_id == value.workflow.created_actor_id
    value.query.owner.identity.fence_current_operator.assert_called_once_with(
        value.session, context.operator_id
    )
    value.query.owner.catalog.assert_not_called()
    assert value.query.owner.catalog.mock_calls == []
    assert value.workflow.runtime_context == before


@pytest.mark.parametrize(
    "fault",
    (
        "root",
        "nested",
        "detached",
        "step_state",
        "workflow_state",
        "definition_hash",
        "protocol",
        "result_schema",
        "preset_pin",
        "pack_hash",
        "creator",
        "actor_type",
        "initial_request",
        "changed_request",
        "query_request",
        "wrong_role",
        "request_hash",
        "current_step",
        "step_type",
    ),
)
def test_bad_role_binding_fails_before_source_or_worker_work(tmp_path, monkeypatch, fault):
    value = provider_case(tmp_path, monkeypatch)
    if fault == "root":
        value.session.get_transaction = lambda: None
    elif fault == "nested":
        value.session.in_nested_transaction = lambda: True
    elif fault == "detached":
        monkeypatch.setattr(preparation_module, "object_session", lambda value: None)
    elif fault == "step_state":
        value.step.state = "SUCCEEDED"
    elif fault == "workflow_state":
        value.workflow.state = "COMPLETED"
    elif fault == "definition_hash":
        value.workflow.definition_hash = "sha256:" + "0" * 64
    elif fault == "protocol":
        value.workflow.role_schema_version = "workflow-role/1.23.0"
    elif fault == "result_schema":
        value.step.result_schema = "authoring-result@11.0"
    elif fault == "preset_pin":
        value.workflow.runtime_context["execution_plan"]["preset_revision_id"] = (
            "execpresetrev_" + "0" * 32
        )
    elif fault == "pack_hash":
        value.workflow.runtime_context["content_pack"]["release_sha256"] = "sha256:" + "0" * 64
    elif fault == "creator":
        value.workflow.created_actor_id = "operator_" + "0" * 32
    elif fault == "actor_type":
        value.workflow.created_actor_type = "system"
    elif fault == "initial_request":
        original = value.workflow.initial_request["image_mode"]
        value.workflow.initial_request["image_mode"] = (
            "skip" if original == "required" else "required"
        )
    elif fault == "changed_request":
        value.workflow.request_payload["execution_preset_key"] = "unexpected-preset"
    elif fault == "query_request":
        document = value.query.request.context_request.model_dump(mode="json")
        document["top_k"] = 3 if document["top_k"] != 3 else 4
        value.query.request.context_request = type(value.case["context"].request).model_validate(
            seal(document, "request_sha256")
        )
    elif fault == "wrong_role":
        value.step.worker_role = "image"
    elif fault == "request_hash":
        value.workflow.request_hash = "sha256:" + "0" * 64
    elif fault == "current_step":
        value.workflow.current_step_key = "registration"
    elif fault == "step_type":
        value.step.step_type = "application"
    with pytest.raises(ControlPlaneError):
        prepare(value)
    value.query.owner.identity.fence_current_operator.assert_not_called()
    assert value.query.owner.catalog.mock_calls == []


@pytest.mark.parametrize(
    "code,expected",
    (
        ("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN", "CONTROL_SIMILARITY_AUTHORITY_DENIED"),
        ("OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE", "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"),
    ),
)
def test_expired_or_revoked_current_owner_cannot_be_replaced_by_stored_actor(
    tmp_path, monkeypatch, code, expected
):
    value = provider_case(tmp_path, monkeypatch)
    value.query.owner.identity.fence_current_operator.side_effect = OperatorAuthorizationFenceError(
        code
    )
    with pytest.raises(ControlPlaneError) as error:
        prepare(value)
    assert error.value.code == expected
    assert value.query.owner.catalog.mock_calls == []


def test_legacy_plan_keeps_original_path_without_using_the_captured_query(tmp_path, monkeypatch):
    value = provider_case(tmp_path, monkeypatch)
    value.record.canonical_document = value.case["base"].model_dump(mode="json")
    assert prepare(value) is None
    value.query.owner.identity.fence_current_operator.assert_not_called()


@pytest.mark.parametrize(
    "role,tier",
    (
        ("authoring", "PRIMARY"),
        ("review", "PRIMARY"),
        ("review", "ESCALATED"),
        ("image", "PRIMARY"),
        ("item_management", "PRIMARY"),
    ),
)
def test_actual_platform_executor_passes_context_only_for_prepared_roles_and_keeps_job_binding(
    tmp_path, monkeypatch, role, tier
):
    value = provider_case(tmp_path, monkeypatch, role="authoring")
    context = prepare(value)
    calls = []
    provider = Mock()
    provider.prepare.side_effect = lambda session, **kw: calls.append("prepare") or context
    step = SimpleNamespace(
        worker_role=role,
        result_schema=f"{role}-result@12.0",
        step_key=role,
        step_run_id="steprun_" + "c" * 32,
        attempt=1,
        input_pointer_manifest={"review_escalation_directive": {}} if tier == "ESCALATED" else {},
    )
    executor = object.__new__(PlatformRoleJobExecutor)
    executor.sessions = lambda: nullcontext(value.session)
    executor.workflow_settings = _workflow_settings(tmp_path)
    executor.similarity_context_provider = provider

    @contextmanager
    def fenced(sessions):
        calls.append("root")
        yield value.session

    monkeypatch.setattr(engine_module, "_command_fenced_transaction", fenced)
    binding = Mock(side_effect=lambda *a, **kw: calls.append("bind"))
    monkeypatch.setattr(engine_module, "bind_platform_role_job", binding)
    result = SimpleNamespace(job_id="job_" + "d" * 32)

    def submit(**kw):
        calls.append("submit")
        assert kw["similarity_context"] is (context if role in {"authoring", "review"} else None)
        assert kw["execution_tier"] == tier
        assert "operator_id" not in kw["request"].model_dump(mode="json")
        kw["before_execute"](result.job_id)
        return result

    executor.orchestrator = SimpleNamespace(submit_workflow_role=submit)
    monkeypatch.setattr(engine_module, "read_platform_role_result", lambda session, job: job)
    assert (
        executor.execute(
            workflow=value.workflow,
            step=step,
            request=value.request.worker_request(),
            upstream=(),
            idempotency_key="synthetic-role",
            prompt_text="synthetic prompt",
        )
        is result
    )
    assert binding.call_count == 1
    assert binding.call_args.kwargs["job_id"] == result.job_id
    assert ("prepare" in calls) == (role in {"authoring", "review"})


@pytest.mark.parametrize("role", ("authoring", "review"))
def test_provider_denial_precedes_orchestrator_job_submission(tmp_path, monkeypatch, role):
    value = provider_case(tmp_path, monkeypatch, role)
    executor = object.__new__(PlatformRoleJobExecutor)
    executor.sessions = lambda: nullcontext(value.session)
    executor.workflow_settings = _workflow_settings(tmp_path)
    executor.similarity_context_provider = Mock()
    executor.similarity_context_provider.prepare.side_effect = ControlPlaneError(
        "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE", "expired actual session"
    )
    executor.orchestrator = Mock()
    monkeypatch.setattr(
        engine_module, "_command_fenced_transaction", lambda sessions: nullcontext(value.session)
    )
    with pytest.raises(ControlPlaneError):
        executor.execute(
            workflow=value.workflow,
            step=value.step,
            request=value.request.worker_request(),
            upstream=(),
            idempotency_key="synthetic-denied",
            prompt_text="synthetic prompt",
        )
    executor.orchestrator.submit_workflow_role.assert_not_called()


def test_production_composition_supplies_the_same_explicit_provider_without_touching_defaults(
    tmp_path,
):
    engine = create_engine("sqlite://")
    provider = Mock()
    runtime = build_workflow_runtime(
        engine=engine,
        workflow_settings=_workflow_settings(tmp_path),
        platform_settings=_platform_settings(tmp_path),
        similarity_context_provider=provider,
    )
    assert runtime.runner.executor.similarity_context_provider is provider
    provider.prepare.assert_not_called()
    engine.dispose()


@pytest.mark.parametrize("context_kind", ("correct", "missing", "foreign_workflow"))
def test_real_orchestrator_callback_receives_context_and_materializes_exact_sidecars_before_model(
    tmp_path, monkeypatch, context_kind
):
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    case = workspace_case(fixture_root, monkeypatch)
    plan = case["plan"]
    context = case["bound"]
    if context_kind == "missing":
        context = None
    elif context_kind == "foreign_workflow":
        context = replace(context, workflow_id="workflow_" + "0" * 32)
    workspace = _workspace(tmp_path, "worker")
    jobs = []
    base_session = case["session"]
    record = base_session.records[(ResolvedExecutionPlanRecord, case["plan_id"])]
    record.plan_id = plan.plan_id
    record.workflow_id = plan.workflow_id
    session = SimpleNamespace(
        scalar=lambda statement: record,
        get=lambda model, identity: (
            jobs[0] if model is JobRecord else base_session.get(model, identity)
        ),
    )
    orchestrator = object.__new__(Orchestrator)
    staging = tmp_path / "staging"
    staging.mkdir()
    orchestrator.settings = SimpleNamespace(
        staging_root=staging, nas_artifact_root=case["artifact_root"]
    )
    orchestrator.sessions = lambda: nullcontext(session)
    orchestrator.capacity = Mock()
    orchestrator.capacity.claim.return_value = SimpleNamespace(
        lease_id="synthetic-lease", slot_key="slot01"
    )
    orchestrator.worker_adapter = Mock()
    slot = SimpleNamespace(slot_id="01", linux_user="synthetic-worker")
    monkeypatch.setattr(orchestrator, "_slot_by_key", lambda key: slot)
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=GROUP_ID))
    monkeypatch.setattr(orchestrator, "_job_by_idempotency_key", lambda key: None)
    monkeypatch.setattr(orchestrator, "_sync_registry", Mock())
    monkeypatch.setattr(owner_module, "ensure_protocol_version", Mock())
    monkeypatch.setattr(owner_module, "transaction", lambda factory: nullcontext(session))

    def submit(session, **kw):
        job = JobRecord(
            job_id=kw["job_id"],
            status="CREATED",
            request=kw["request"],
            logical_artifact_id=kw["logical_artifact_id"],
            revision_id=kw["revision_id"],
        )
        jobs.append(job)
        return job, True

    monkeypatch.setattr(owner_module, "submit_structured_job", submit)
    monkeypatch.setattr(orchestrator, "get_job", lambda identity: jobs[0])

    def transition(job_id, state, event, **data):
        jobs[0].status = str(state)

    monkeypatch.setattr(orchestrator, "_transition", transition)
    monkeypatch.setattr(
        owner_module, "transition_job", lambda session, *a, **kw: transition(*a, **kw)
    )
    failures = []

    def fail(job_id, code, detail, slot):
        failures.append(detail)
        jobs[0].status = "FAILED"

    monkeypatch.setattr(orchestrator, "_fail", fail)

    def run(**kw):
        kw["materialize"](workspace)
        # A synthetic worker stops here: no process, result, model or publication.
        raise OSError("synthetic stop after real materialization")

    orchestrator.worker_adapter.run_resolved_structured.side_effect = run
    result = orchestrator.submit_workflow_role(
        workflow_id=plan.workflow_id,
        step_run_id="steprun_" + "d" * 32,
        step_key="authoring",
        attempt=1,
        role="authoring",
        request=WorkerRequest(request_name="GENERATED_KNOWLEDGE_ITEM_REQUEST", image_mode="skip"),
        upstream_artifacts=(),
        result_schema="authoring-result@12.0",
        idempotency_key="synthetic-real-callback",
        prompt_text="synthetic prompt",
        similarity_context=context,
    )
    assert result.status == "FAILED" and len(jobs) == 1
    if context_kind == "correct":
        assert (
            workspace / "references/similarity/context.json"
        ).read_bytes() == canonical_json_bytes(case["context"].model_dump(mode="json"))
        assert (
            workspace / "references/similarity/materials.json"
        ).read_bytes() == canonical_json_bytes(case["references"].model_dump(mode="json"))
        assert (workspace / "references/variation/source-item.json").read_bytes() == case[
            "source_payload"
        ]
        assert failures == ["workflow worker I/O failed"]
    else:
        assert not (workspace / "references").exists()
        assert failures == [
            "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
            if context_kind == "missing"
            else "CONTROL_SIMILARITY_CONTEXT_INVALID"
        ]
