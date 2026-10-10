"""Purpose-specific V22 Runner composition with fake official owner/job ports only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_operator_identity import PermissionKey
from eom_orchestrator.orchestrator import Orchestrator
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV22
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from eom_workflow_runner.actor_authorization import (
    WorkflowActorAuthorization,
    WorkflowActorNamespace,
)
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.inference_transfer_executor import PlatformInferenceTransferExecutor

from tests.unit.inference_transfer_service_v11_fixtures import owner_fixture_v11
from tests.unit.test_inference_transfer_runner_execution import FakeSession


def runner_fixture_v11(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    value = owner_fixture_v11(monkeypatch)
    value.workflow.state = "RUNNING"
    value.workflow.stage = "INFERENCE_TRANSFER"
    value.workflow.current_step_key = "compare_pair"
    value.step.state = "RUNNING"
    session = FakeSession(
        {(entity, _identity(row)): row for entity, row in value.rows.items()}
        | {(type(value.step), value.step.step_run_id): value.step}
    )

    @contextmanager
    def fenced() -> Iterator[Any]:
        yield session

    source, authorizer, orchestrator, resolver = Mock(), Mock(), Mock(), Mock()
    authorizer.authorize.return_value = WorkflowActorAuthorization(
        canonical_actor_id=value.workflow.created_actor_id,
        namespace=WorkflowActorNamespace.OPERATOR_IDENTITY,
        authorized=True,
        capabilities=frozenset({PermissionKey.ITEM_READ}),
        workflow_roles=frozenset({"reviewer"}),
        denial_reason=None,
    )
    resolver.return_value = ResolvedExecutionPlanV22.model_validate(value.plan.canonical_document)
    monkeypatch.setattr(
        "eom_workflow_runner.inference_transfer_executor.resolve_inference_transfer_execution_plan_v11",
        resolver,
    )

    def submit(**kwargs: Any) -> Any:
        callback = kwargs["reauthorize_transfer_sources"]
        callback(kwargs["request"])
        kwargs["before_execute"](value.job.job_id)
        callback(kwargs["request"])
        callback(kwargs["request"])
        return value.job

    orchestrator.submit_workflow_role.side_effect = submit
    value.executor = PlatformInferenceTransferExecutor(
        orchestrator=cast(Orchestrator, orchestrator),
        source=source,
        actor_authorizer=authorizer,
    )
    value.fenced, value.source, value.authorizer = fenced, source, authorizer
    value.orchestrator, value.resolver = orchestrator, resolver
    return value


def _identity(row: Any) -> str:
    # ORM objects may have several FK IDs: only each row's primary key counts.
    primary = next(iter(row.__table__.primary_key.columns)).name
    return cast(str, getattr(row, primary))


def execute_v11(value: SimpleNamespace) -> Any:
    return value.executor.execute(
        workflow=value.workflow,
        step=value.step,
        request=value.request,
        idempotency_key="synthetic-v11-same-step",
        fenced_transaction=value.fenced,
    )


def test_three_axis_runner_uses_exact_request_plan_prompt_and_actual_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = runner_fixture_v11(monkeypatch)
    result = execute_v11(value)
    assert result.status == "SUCCEEDED"
    calls = value.orchestrator.submit_workflow_role.call_args.kwargs
    assert calls["result_schema"] == "item-inference-transfer-pair-result@1.1"
    assert calls["request"].request_name == "ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11"
    assert calls["transfer_workflow_request"] == value.request
    assert "workflow-role/1.30.0" in calls["prompt_text"]
    assert "axes는 CONCEPT, MATERIAL, CRUX" in calls["prompt_text"]
    assert value.workflow.runtime_context["execution_plan"]["plan_sha256"] == (
        value.plan.plan_sha256
    )
    assert value.source.authorize_pair.call_count == 4
    assert {call.args[0].actor_id for call in value.source.authorize_pair.call_args_list} == {
        value.workflow.created_actor_id
    }
    args = value.resolver.call_args.kwargs
    assert isinstance(args["workflow_request"], InferenceTransferWorkflowRequestV11)
    assert args["workflow_definition_version"] == "1.1.0"
    assert args["workflow_role_schema_version"] == "workflow-role/1.30.0"
    assert (
        value.step.input_pointer_manifest["transfer_prompt"]["prompt_sha256"]
        == (value.plan.canonical_document["prompt_sha256"])
    )


@pytest.mark.parametrize("at", [1, 2, 3, 4])
def test_each_live_source_callback_is_rechecked_without_initial_permission_token(
    monkeypatch: pytest.MonkeyPatch, at: int
) -> None:
    value = runner_fixture_v11(monkeypatch)
    value.source.authorize_pair.side_effect = [None] * (at - 1) + [ValueError("revoked")]
    with pytest.raises(ValueError, match="revoked"):
        execute_v11(value)
    assert value.source.authorize_pair.call_count == at
    if at == 1:
        value.orchestrator.submit_workflow_role.assert_not_called()


@pytest.mark.parametrize(
    "entity,field,replacement",
    [
        ("workflow", "definition_version", "1.0.0"),
        ("workflow", "role_schema_version", "workflow-role/1.29.0"),
        ("step", "result_schema", "item-inference-transfer-pair-result@1.0"),
        ("definition", "definition_hash", "sha256:" + "f" * 64),
    ],
)
def test_version_or_pointer_drift_precedes_model_submission(
    monkeypatch: pytest.MonkeyPatch, entity: str, field: str, replacement: object
) -> None:
    value = runner_fixture_v11(monkeypatch)
    setattr(getattr(value, entity), field, replacement)
    with pytest.raises(WorkflowError):
        execute_v11(value)
    value.source.authorize_pair.assert_not_called()
    value.resolver.assert_not_called()
    value.orchestrator.submit_workflow_role.assert_not_called()
