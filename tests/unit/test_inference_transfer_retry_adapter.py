"""Bounded failed-parent admission guards; no database, files or model execution."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_api.errors import ApiError
from eom_api.services import inference_transfer_retry_adapter as retry_adapter
from eom_api.services.inference_transfer_retry import AuthorizedInferenceTransferRetry
from eom_api.services.inference_transfer_retry_adapter import (
    RETRY_CONTEXT,
    InferenceTransferRetryAdapter,
    _failed_comparison,
    _validate_child,
)
from eom_identifiers import content_sha256
from eom_orchestrator.models import JobRecord
from eom_workflow.inference_transfer_control import ResolvedExecutionPlanV22
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_api_fixtures import authentication
from tests.unit.inference_transfer_invocation_fixtures import WORKFLOW_ID
from tests.unit.test_inference_transfer_retry_application import (
    configured,
    retry_actor,
    retry_request,
)
from tests.unit.test_inference_transfer_workflow_v11 import _plan


def failed_fixture() -> tuple[Mock, Any, Any, Any, AuthorizedInferenceTransferRetry]:
    service, snapshots, _, _, _ = configured()
    authorized = service.authorize_retry(authentication(), WORKFLOW_ID, retry_request(snapshots))
    parent = SimpleNamespace(
        workflow_id=WORKFLOW_ID, state="FAILED", stage="FAILED", current_step_key="compare_pair"
    )
    step = SimpleNamespace(
        step_run_id=authorized.request.failed_step_run_id,
        attempt=1,
        state="FAILED",
        step_type="agent",
        worker_role="support",
        result_schema="item-inference-transfer-pair-result@1.1",
        platform_job_id="job_" + "2" * 32,
        output_pointer_manifest=None,
        superseded_by_step_run_id=None,
    )
    job = SimpleNamespace(
        job_id=step.platform_job_id,
        status="FAILED",
        error_code="WORKER_RESULT_INVALID",
        request={
            "workflow_id": WORKFLOW_ID,
            "step_run_id": step.step_run_id,
            "attempt": 1,
            "role": "support",
        },
    )
    session = Mock(spec=Session)
    session.scalar.side_effect = [step, None, None, None]
    session.get.return_value = job
    return session, parent, step, job, authorized


def test_only_exact_failed_first_attempt_without_work_or_artifact_is_admitted() -> None:
    session, parent, step, job, authorized = failed_fixture()
    assert _failed_comparison(cast(Session, session), parent, authorized) == (step, job)
    assert session.scalar.call_count == 4


def test_terminal_step_query_is_select_only_but_failed_job_lock_is_retained() -> None:
    session, parent, _, job, authorized = failed_fixture()
    _failed_comparison(cast(Session, session), parent, authorized)
    query = session.scalar.call_args_list[0].args[0]
    sql = str(query)
    assert "workflow_step_runs" in sql and "FOR UPDATE" not in sql
    assert "ORDER BY" in sql and "LIMIT" in sql
    session.get.assert_called_once_with(JobRecord, job.job_id, with_for_update=True)


def test_successor_admission_still_locks_parent_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _, _, _, authorized = failed_fixture()
    session.scalar.side_effect = [None]
    adapter = object.__new__(InferenceTransferRetryAdapter)
    adapter.sessions = Mock()
    monkeypatch.setattr(retry_adapter, "transaction", lambda _sessions: nullcontext(session))
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_WORKFLOW_NOT_FOUND"):
        adapter.retry(authorized, retry_actor(), expected_version=4, idempotency_key="exact-key")
    sql = str(session.scalar.call_args.args[0])
    assert "workflow_instances" in sql and "FOR UPDATE" in sql


@pytest.mark.parametrize(
    "field,value",
    [("state", "RUNNING"), ("stage", "INFERENCE_TRANSFER"), ("current_step_key", "publish_result")],
)
def test_nonfailed_parent_does_not_inspect_or_change_step(field: str, value: str) -> None:
    session, parent, _, _, authorized = failed_fixture()
    setattr(parent, field, value)
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)
    session.scalar.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("step_run_id", "steprun_" + "f" * 32),
        ("attempt", 2),
        ("state", "SUCCEEDED"),
        ("step_type", "decision"),
        ("worker_role", "authoring"),
        ("result_schema", "item-inference-transfer-pair-result@1.0"),
        ("platform_job_id", None),
        ("output_pointer_manifest", {}),
        ("superseded_by_step_run_id", "steprun_" + "f" * 32),
    ],
)
def test_other_attempt_output_or_changed_step_is_not_reinterpreted_as_retryable(
    field: str, value: Any
) -> None:
    session, parent, step, _, authorized = failed_fixture()
    setattr(step, field, value)
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)
    session.get.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "SUCCEEDED"),
        ("error_code", "CODEX_SLOT_UNAVAILABLE"),
        ("workflow_id", "workflow_" + "f" * 32),
        ("step_run_id", "steprun_" + "f" * 32),
        ("attempt", 2),
        ("role", "authoring"),
    ],
)
def test_wrong_job_or_nonresult_failure_is_not_generic_retry(field: str, value: Any) -> None:
    session, parent, _, job, authorized = failed_fixture()
    if field in {"status", "error_code"}:
        setattr(job, field, value)
    else:
        job.request[field] = value
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)
    assert session.scalar.call_count == 1


@pytest.mark.parametrize("active_index", [0, 1, 2])
def test_artifact_active_command_or_held_lease_blocks_before_creation(active_index: int) -> None:
    session, parent, step, _, authorized = failed_fixture()
    responses: list[str | None] = [None, None, None]
    responses[active_index] = "already-present"
    session.scalar.side_effect = [step, *responses]
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)
    assert session.scalar.call_count == active_index + 2


def test_missing_original_step_or_job_is_explicit_ineligible() -> None:
    session, parent, _, _, authorized = failed_fixture()
    session.scalar.side_effect = [None]
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)
    session, parent, _, _, authorized = failed_fixture()
    session.get.return_value = None
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_INELIGIBLE"):
        _failed_comparison(cast(Session, session), parent, authorized)


def child_plans() -> tuple[ResolvedExecutionPlanV22, ResolvedExecutionPlanV22]:
    parent = ResolvedExecutionPlanV22.model_validate(_plan())
    body = parent.model_dump(mode="json", exclude={"plan_sha256"})
    body.update(plan_id="execplan_" + "f" * 32, workflow_id="workflow_" + "f" * 32)
    return parent, ResolvedExecutionPlanV22.model_validate(
        body | {"plan_sha256": content_sha256(body)}
    )


def test_successor_may_change_execution_identity_not_immutable_controls() -> None:
    parent, child_plan = child_plans()
    lineage = {"parent_workflow_id": parent.workflow_id}
    child = cast(WorkflowInstanceRecord, SimpleNamespace(runtime_context={RETRY_CONTEXT: lineage}))
    _validate_child(parent, child, child_plan, lineage)


@pytest.mark.parametrize(
    "field,value",
    [
        ("capacity_policy_revision_id", "capacityrev_" + "f" * 32),
        ("preset_sha256", "sha256:" + "f" * 64),
        ("core_prompt_sha256", "sha256:" + "f" * 64),
        ("access_policy_sha256", "sha256:" + "f" * 64),
    ],
)
def test_changed_pinned_child_control_is_explicit_conflict(field: str, value: str) -> None:
    parent, child_plan = child_plans()
    body = child_plan.model_dump(mode="json", exclude={"plan_sha256"}) | {field: value}
    changed = ResolvedExecutionPlanV22.model_validate(body | {"plan_sha256": content_sha256(body)})
    lineage = {"parent_workflow_id": parent.workflow_id}
    child = cast(WorkflowInstanceRecord, SimpleNamespace(runtime_context={RETRY_CONTEXT: lineage}))
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_CONFLICT"):
        _validate_child(parent, child, changed, lineage)


def test_child_cannot_omit_or_replace_failed_parent_lineage() -> None:
    parent, child_plan = child_plans()
    child = cast(WorkflowInstanceRecord, SimpleNamespace(runtime_context={}))
    with pytest.raises(ApiError, match="INFERENCE_TRANSFER_RETRY_CONFLICT"):
        _validate_child(parent, child, child_plan, {"parent_workflow_id": parent.workflow_id})
