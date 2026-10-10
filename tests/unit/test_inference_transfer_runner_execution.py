"""Source-only purpose composition with fake authority/job ports and no DB/model."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_service.inference_transfer_worker_preparation import (
    prepare_inference_transfer_worker_comparison,
)
from eom_identifiers import content_sha256
from eom_operator_identity import PermissionKey
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_workflow import ArtifactPointer, WorkflowRequest, compile_definition
from eom_workflow.inference_transfer import TRANSFER_PAIR_RESULT_SCHEMA, TRANSFER_PAIR_WORKFLOW_KEY
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV21
from eom_workflow_runner import engine as engine_module
from eom_workflow_runner.actor_authorization import (
    WorkflowActorAuthorization,
    WorkflowActorNamespace,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.inference_transfer_executor import PlatformInferenceTransferExecutor
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.role_execution_binding import bind_platform_role_job
from eom_workflow_runner.role_execution_port import RoleExecutionResult

from tests.unit.inference_transfer_execution_fixtures import transfer_plan
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_workflow_fixtures import workflow_request


class ScalarResult:
    def __init__(self, row: Any) -> None:
        self.row = row

    def scalar_one(self) -> Any:
        assert self.row is not None
        return self.row

    def scalar_one_or_none(self) -> Any:
        return self.row


class FakeSession:
    def __init__(self, records: dict[tuple[type[Any], str], Any]) -> None:
        self.records = records

    def get(self, model: type[Any], identity: str) -> Any:
        return self.records.get((model, identity))

    def execute(self, query: Any) -> ScalarResult:
        model = query.column_descriptions[0]["entity"]
        rows = [row for (kind, _), row in self.records.items() if kind is model]
        assert len(rows) <= 1
        return ScalarResult(rows[0] if rows else None)

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def fixture(monkeypatch: pytest.MonkeyPatch, *, status: str = "SUCCEEDED") -> SimpleNamespace:
    request = workflow_request()
    compiled = compile_definition(
        Path("config/workflows/item-inference-transfer-comparison.v1.yaml"), {"support"}
    )
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "1" * 32,
        definition_id="wfdef_" + "1" * 32,
        definition_key=TRANSFER_PAIR_WORKFLOW_KEY,
        definition_version="1.0.0",
        definition_hash=compiled.sha256,
        role_schema_version="workflow-role/1.29.0",
        protocol_version="1.0.1",
        state="RUNNING",
        stage="INFERENCE_TRANSFER",
        current_step_key="compare_pair",
        initial_request=request.model_dump(mode="json"),
        request_payload=request.model_dump(mode="json"),
        runtime_context={"artifact_pointers": []},
        created_actor_type="human",
        created_actor_id="operator_" + "1" * 32,
        lock_version=1,
        rework_cycle_count=0,
    )
    step = WorkflowStepRunRecord(
        step_run_id="steprun_" + "1" * 32,
        workflow_id=workflow.workflow_id,
        step_key="compare_pair",
        attempt=1,
        step_type="agent",
        worker_role="support",
        result_schema=TRANSFER_PAIR_RESULT_SCHEMA,
        state="RUNNING",
        platform_job_id=None,
        input_pointer_manifest={"upstream_artifacts": []},
    )
    definition = WorkflowDefinitionRecord(
        definition_id=workflow.definition_id,
        definition_key=TRANSFER_PAIR_WORKFLOW_KEY,
        definition_version="1.0.0",
        definition_hash=compiled.sha256,
        canonical_definition=compiled.as_dict(),
        source_path="synthetic-installed-definition",
    )
    job = SimpleNamespace(
        job_id="job_" + "7" * 32,
        status=status,
        worker_slot_id="06",
        logical_artifact_id="artifact_" + "7" * 32,
        revision_id="rev_" + "7" * 32,
        error_code="WORKER_EXEC_FAILED" if status == "FAILED" else None,
    )
    records = {
        (WorkflowInstanceRecord, workflow.workflow_id): workflow,
        (WorkflowStepRunRecord, step.step_run_id): step,
        (WorkflowDefinitionRecord, definition.definition_id): definition,
        (ArtifactRevisionRecord, job.revision_id): SimpleNamespace(content_hash=sha("7")),
    }
    session = FakeSession(records)
    events: list[str] = []

    @contextmanager
    def fenced() -> Iterator[FakeSession]:
        events.append("fence-enter")
        yield session
        events.append("fence-exit")

    class Authorizer:
        allowed = True
        namespace = WorkflowActorNamespace.OPERATOR_IDENTITY
        permissions = frozenset({PermissionKey.ITEM_READ})

        def __init__(self) -> None:
            self.calls: list[str] = []

        def authorize(self, actor_id: str, permission: PermissionKey) -> WorkflowActorAuthorization:
            assert permission is PermissionKey.ITEM_READ
            self.calls.append(actor_id)
            events.append("identity")
            from eom_workflow_runner.actor_authorization import WorkflowActorDenialReason

            return WorkflowActorAuthorization(
                canonical_actor_id=actor_id,
                namespace=self.namespace,
                authorized=self.allowed,
                capabilities=self.permissions,
                workflow_roles=frozenset({"reviewer"}),
                denial_reason=None if self.allowed else WorkflowActorDenialReason.PERMISSION_ABSENT,
            )

    class Source:
        fail_on: int | None = None

        def __init__(self) -> None:
            self.calls: list[Any] = []

        def authorize_pair(self, command: Any, left: Any, right: Any) -> None:
            events.append("source")
            self.calls.append((command, left, right))
            assert command.actor_id == workflow.created_actor_id
            assert command.access_policy_revision_id == request.access_policy_revision_id
            assert command.access_policy_sha256 == request.access_policy_sha256
            assert command.graph_snapshot == request.left_profile.source_basis.graph_snapshot
            assert command.maximum_candidates == command.top_k == 2
            assert left == request.left_profile and right == request.right_profile
            if self.fail_on == len(self.calls):
                raise ValueError("synthetic revoked source")

    class Orchestrator:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def submit_workflow_role(self, **kwargs: Any) -> Any:
            events.append("submit")
            self.calls.append(kwargs)
            assert kwargs["upstream_artifacts"] == ()
            assert kwargs["result_schema"] == TRANSFER_PAIR_RESULT_SCHEMA
            assert kwargs["transfer_workflow_request"] == request
            assert kwargs["role"] == "support"
            owner = kwargs["reauthorize_transfer_sources"]
            owner(kwargs["request"])
            kwargs["before_execute"](job.job_id)
            owner(kwargs["request"])
            owner(kwargs["request"])
            return job

    authorizer, source, orchestrator = Authorizer(), Source(), Orchestrator()
    calls: list[dict[str, Any]] = []

    def resolve(actual_session: Any, **kwargs: Any) -> ResolvedExecutionPlanV21:
        assert actual_session is session
        assert events[-1] == "source"
        calls.append(kwargs)
        body = transfer_plan(request.comparison).model_dump(mode="json")
        body.update(
            {
                key: kwargs[key]
                for key in ("workflow_definition_sha256", "core_prompt_sha256", "prompt_sha256")
            }
        )
        body.update(
            {
                key: getattr(request, key)
                for key in (
                    "access_policy_revision_id",
                    "access_policy_sha256",
                    "requester_permissions_sha256",
                )
            }
        )
        body["plan_sha256"] = content_sha256(
            {key: value for key, value in body.items() if key != "plan_sha256"}
        )
        return ResolvedExecutionPlanV21.model_validate(body)

    monkeypatch.setattr(
        "eom_workflow_runner.inference_transfer_executor.resolve_inference_transfer_execution_plan",
        resolve,
    )
    executor = PlatformInferenceTransferExecutor(
        orchestrator=orchestrator, source=source, actor_authorizer=authorizer
    )
    return SimpleNamespace(
        request=request,
        workflow=workflow,
        step=step,
        definition=definition,
        compiled=compiled,
        job=job,
        session=session,
        records=records,
        fenced=fenced,
        events=events,
        authorizer=authorizer,
        source=source,
        orchestrator=orchestrator,
        resolver_calls=calls,
        executor=executor,
    )


def execute(value: SimpleNamespace, **updates: Any) -> RoleExecutionResult:
    return value.executor.execute(
        **(
            {
                "workflow": value.workflow,
                "step": value.step,
                "request": value.request,
                "idempotency_key": "same-step-key",
                "fenced_transaction": value.fenced,
            }
            | updates
        )
    )


def test_leaf_binds_actual_principal_wrapper_prompt_and_same_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    result = execute(data)
    prepared = prepare_inference_transfer_worker_comparison(
        data.request.comparison, left=data.request.left_profile, right=data.request.right_profile
    )
    assert result.content_hash == sha("7") and result.status == "SUCCEEDED"
    assert data.step.platform_job_id == data.job.job_id
    assert set(data.authorizer.calls) == {data.workflow.created_actor_id}
    assert len(data.source.calls) == 4
    kwargs = data.resolver_calls[0]
    assert kwargs["workflow_request"] == data.request
    assert kwargs["core_prompt_sha256"] == prepared.core_prompt_sha256
    assert kwargs["prompt_sha256"] == prepared.prompt_sha256
    assert data.orchestrator.calls[0]["prompt_text"] == prepared.prompt_text
    assert "prompt_text" not in data.step.input_pointer_manifest
    assert (
        data.step.input_pointer_manifest["transfer_prompt"]["workflow_request_sha256"]
        == data.request.request_sha256
    )


def test_current_permissions_are_authority_not_an_initial_digest_equality_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    data.authorizer.permissions |= {PermissionKey.KNOWLEDGE_ANALYSIS_READ}
    assert (
        content_sha256(sorted(permission.value for permission in data.authorizer.permissions))
        != data.request.requester_permissions_sha256
    )
    assert execute(data).status == "SUCCEEDED"
    assert (
        data.orchestrator.calls[0]["transfer_workflow_request"].requester_permissions_sha256
        == data.request.requester_permissions_sha256
    )


@pytest.mark.parametrize("phase", [1, 2, 3, 4])
def test_source_revocation_at_every_supplied_boundary_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch, phase: int
) -> None:
    data = fixture(monkeypatch)
    data.source.fail_on = phase
    with pytest.raises(ValueError, match="revoked"):
        execute(data)
    assert len(data.source.calls) == phase
    if phase == 1:
        assert not data.resolver_calls and not data.orchestrator.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_actor_type", "system"),
        ("created_actor_id", "runner-system"),
        ("definition_key", "customer-support"),
        ("role_schema_version", "workflow-role/1.22.0"),
        ("state", "COMPLETED"),
        ("stage", "AUTHORING"),
        ("current_step_key", "diagnose"),
    ],
)
def test_stored_actual_context_cannot_be_replaced_by_a_support_label(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    data = fixture(monkeypatch)
    setattr(data.workflow, field, value)
    with pytest.raises(WorkflowError):
        execute(data)
    assert not data.source.calls and not data.resolver_calls and not data.orchestrator.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("step_type", "approval"),
        ("step_key", "diagnose"),
        ("worker_role", "authoring"),
        ("result_schema", "customer-support-result@1.0"),
        ("state", "SUCCEEDED"),
        ("input_pointer_manifest", {"upstream_artifacts": [{"pretend": "source"}]}),
    ],
)
def test_actual_step_purpose_and_empty_upstream_are_required(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    data = fixture(monkeypatch)
    setattr(data.step, field, value)
    with pytest.raises(WorkflowError):
        execute(data)
    assert not data.source.calls and not data.orchestrator.calls


@pytest.mark.parametrize(
    "namespace", [WorkflowActorNamespace.STATIC, WorkflowActorNamespace.OPERATOR_IDENTITY]
)
def test_current_identity_denial_or_static_identity_never_reaches_catalog(
    monkeypatch: pytest.MonkeyPatch, namespace: Any
) -> None:
    data = fixture(monkeypatch)
    data.authorizer.namespace = namespace
    data.authorizer.allowed = namespace is WorkflowActorNamespace.STATIC
    with pytest.raises(WorkflowError) as error:
        execute(data)
    assert error.value.code is WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE
    assert not data.source.calls


def test_same_key_leaf_replay_preserves_prompt_pins_and_reauthorizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    first = execute(data)
    pins = deepcopy(data.step.input_pointer_manifest)
    second = execute(data)
    assert first == second
    assert data.step.input_pointer_manifest == pins
    assert len(data.source.calls) == 8
    assert [call["idempotency_key"] for call in data.orchestrator.calls] == ["same-step-key"] * 2


@pytest.mark.parametrize(
    "field,value", [("definition_key", "customer-support"), ("definition_version", "9.0.0")]
)
def test_compiled_definition_identity_cannot_disagree_with_row_projection(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    from eom_workflow import compile_definition_data

    data = fixture(monkeypatch)
    document = deepcopy(data.definition.canonical_definition)
    document[field] = value
    compiled = compile_definition_data(document, "synthetic-drift", {"support"})
    data.definition.canonical_definition = compiled.as_dict()
    data.definition.definition_hash = data.workflow.definition_hash = compiled.sha256
    with pytest.raises(WorkflowError, match="stored purpose"):
        execute(data)
    assert not data.source.calls and not data.orchestrator.calls


@pytest.mark.parametrize("location", ["request_payload", "initial_request", "prompt", "plan"])
def test_stale_stored_request_and_prompt_plan_pins_are_not_repaired(
    monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    data = fixture(monkeypatch)
    if location in {"request_payload", "initial_request"}:
        getattr(data.workflow, location)["request_sha256"] = sha("9")
    elif location == "prompt":
        data.step.input_pointer_manifest["transfer_prompt"] = {"prompt_sha256": sha("9")}
    else:
        data.workflow.runtime_context["execution_plan"] = {"plan_sha256": sha("9")}
    with pytest.raises((WorkflowError, ValueError)):
        execute(data)
    assert not data.orchestrator.calls


def test_source_callback_rejects_copied_worker_value_before_authority_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    execute(data)
    count = len(data.source.calls)
    callback = data.orchestrator.calls[0]["reauthorize_transfer_sources"]
    forged = data.request.worker_request().model_copy(
        update={"request_name": "CUSTOMER_SUPPORT_REQUEST"}
    )
    with pytest.raises(ValueError):
        callback(forged)
    assert len(data.source.calls) == count


def test_callback_identity_revocation_uses_existing_owner_failure_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    execute(data)
    count = len(data.source.calls)
    callback = data.orchestrator.calls[0]["reauthorize_transfer_sources"]
    data.authorizer.allowed = False
    with pytest.raises(ValueError, match="Operator authorization") as error:
        callback(data.request.worker_request())
    assert isinstance(error.value.__cause__, WorkflowError)
    assert len(data.source.calls) == count


def runner_fixture(data: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> Any:
    runner = WorkflowRunner.__new__(WorkflowRunner)
    runner.sessions = lambda: data.session
    runner._fenced_transaction = data.fenced
    runner._latest_active_step = lambda *args: data.step
    runner._detached_step = lambda *args: data.step
    runner._input_upstream_pointers = lambda *args: ()
    runner._renew_command_lease = lambda *args: None
    runner.inference_transfer_executor = data.executor
    runner.executor = SimpleNamespace(
        execute=lambda **kwargs: pytest.fail("legacy executor selected")
    )
    runner.catalog = SimpleNamespace(
        prepare_prompt=lambda **kwargs: pytest.fail("authoring prompt selected")
    )
    runner.runner_config = SimpleNamespace(poll_interval_seconds=1)
    runner.runner_id = "system-command-processor"
    runner._record_agent_step_failure = lambda **kwargs: data.events.append("step-failure")
    runner._fail_workflow = lambda *args: setattr(data.workflow, "state", "FAILED")
    monkeypatch.setattr(engine_module, "record_workflow_event", lambda *args, **kwargs: None)
    return runner


def test_missing_optional_port_fails_before_step_or_job_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    runner = runner_fixture(data, monkeypatch)
    runner.inference_transfer_executor = None
    with pytest.raises(WorkflowError) as error:
        runner._execute_agent(
            data.workflow,
            data.compiled,
            data.compiled.steps_by_key["compare_pair"],
            None,
            "system",
            "processor",
        )
    assert error.value.code is WorkflowErrorCode.INFERENCE_TRANSFER_EXECUTION_UNAVAILABLE
    assert not data.events and not data.orchestrator.calls


@pytest.mark.parametrize("status", ["SUCCEEDED", "QUEUED", "FAILED"])
def test_engine_reuses_common_success_queue_and_failure_logic(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    data = fixture(monkeypatch, status=status)
    runner = runner_fixture(data, monkeypatch)
    queued: list[Any] = []
    monkeypatch.setattr(
        engine_module,
        "enqueue_command",
        lambda *args, **kwargs: (
            queued.append(kwargs) or SimpleNamespace(command_id="retry"),
            True,
        ),
    )
    if status == "FAILED":
        with pytest.raises(WorkflowError):
            runner._execute_agent(
                data.workflow,
                data.compiled,
                data.compiled.steps_by_key["compare_pair"],
                "wfcmd_test",
                "system",
                "processor",
            )
        assert data.step.state == "FAILED" and data.workflow.state == "FAILED"
    else:
        result = runner._execute_agent(
            data.workflow,
            data.compiled,
            data.compiled.steps_by_key["compare_pair"],
            "wfcmd_test",
            "system",
            "processor",
        )
        assert result is (status == "SUCCEEDED")
        if status == "SUCCEEDED":
            assert data.step.state == "SUCCEEDED" and data.workflow.current_step_key == "complete"
            assert len(data.workflow.runtime_context["artifact_pointers"]) == 1
        else:
            assert data.step.state == "RUNNING" and len(queued) == 1
            assert queued[0]["payload"]["job_id"] == data.job.job_id
    assert set(data.authorizer.calls) == {data.workflow.created_actor_id}


def test_legacy_request_still_selects_legacy_executor_and_material_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = fixture(monkeypatch)
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.yaml"),
        {"authoring", "image", "review", "item_management"},
    )
    request = WorkflowRequest(request_name="PLACEHOLDER_REQUEST", image_mode="skip")
    data.workflow.definition_key = compiled.definition.definition_key
    data.workflow.initial_request = request.model_dump(mode="json")
    data.workflow.current_step_key = data.step.step_key = "authoring"
    data.step.worker_role = "authoring"
    data.step.result_schema = "authoring-result@1.0"
    runner = runner_fixture(data, monkeypatch)
    calls: list[Any] = []

    def execute_legacy(**kwargs: Any) -> RoleExecutionResult:
        calls.append(kwargs)
        return RoleExecutionResult(
            job_id=data.job.job_id,
            status="SUCCEEDED",
            worker_slot="01",
            logical_artifact_id=data.job.logical_artifact_id,
            revision_id=data.job.revision_id,
            content_hash=sha("7"),
            error_code=None,
        )

    runner.executor = SimpleNamespace(execute=execute_legacy)
    assert runner._execute_agent(
        data.workflow, compiled, compiled.steps_by_key["authoring"], None, "system", "processor"
    )
    assert calls[0]["request"] == request.worker_request()
    assert calls[0]["prompt_text"] is None and calls[0]["material_requirement"] is None
    assert not data.source.calls and not data.resolver_calls and not data.orchestrator.calls


def test_terminal_comparison_is_not_an_item_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    data = fixture(monkeypatch)
    runner = runner_fixture(data, monkeypatch)
    pointer = ArtifactPointer(
        step_key="compare_pair",
        attempt=1,
        job_id=data.job.job_id,
        logical_artifact_id=data.job.logical_artifact_id,
        revision_id=data.job.revision_id,
        content_hash=sha("7"),
        result_schema=TRANSFER_PAIR_RESULT_SCHEMA,
    )
    runner._latest_active_step = lambda *args: SimpleNamespace(state="SUCCEEDED")
    runner._upstream_pointers = lambda *args: (pointer,)
    monkeypatch.setattr(engine_module, "link_superseded_attempts", lambda *args: None)
    monkeypatch.setattr(engine_module, "transition_stage", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine_module, "transition_workflow", lambda *args, **kwargs: None)
    runner._complete_terminal(
        data.workflow,
        data.compiled,
        data.compiled.steps_by_key["complete"],
        None,
        "system",
        "processor",
    )
    final = data.workflow.runtime_context["final_pointer_manifest"]
    assert final["comparison_result"] == pointer.model_dump(mode="json")
    assert final["registration"] is None and final["item_registration"] is None


@pytest.mark.parametrize(
    "field,value", [("attempt", 2), ("platform_job_id", "different-job"), ("state", "FAILED")]
)
def test_public_job_binder_does_not_replace_mismatched_running_step(
    monkeypatch: pytest.MonkeyPatch, field: str, value: Any
) -> None:
    data = fixture(monkeypatch)
    setattr(data.step, field, value)
    with pytest.raises(WorkflowError):
        bind_platform_role_job(
            data.session,
            workflow_id=data.workflow.workflow_id,
            step_run_id=data.step.step_run_id,
            step_key="compare_pair",
            attempt=1,
            worker_role="support",
            job_id=data.job.job_id,
        )


def test_engine_import_preserves_existing_execution_result_public_identity() -> None:
    assert engine_module.RoleExecutionResult is RoleExecutionResult
