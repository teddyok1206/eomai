"""Shared private2 Runner/terminal transitions with synthetic authority and receipts.

Canonical publication and real PostgreSQL ownership are covered separately;
these views do not authorize a new Workflow or execute a model/unit.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_workflow.compiler import compile_definition
from eom_workflow_runner.errors import WorkflowError

from tests.unit import test_private_chat_query_step_execution as lifecycle_cases
from tests.unit import test_private_chat_query_terminal as terminal_cases
from tests.unit.test_private_chat_public_query_source_owner import make_private_public_source_case
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_workflow import completed as completed


@pytest.fixture
def terminal(public_completed, monkeypatch):
    return terminal_cases.make_private_terminal_case(public_completed, monkeypatch)


@pytest.fixture
def lifecycle(terminal, tmp_path, monkeypatch):
    compiled = compile_definition(
        Path(__file__).resolve().parents[2]
        / "config/workflows/local-embedding-private-chat-query.v2.yaml",
        set(),
    )
    current = make_private_public_source_case(
        tmp_path, monkeypatch, definition_sha256=compiled.sha256
    )
    source = SimpleNamespace(
        publisher=current.old.publisher,
        fault=current.old.fault,
        owner=current.owner,
        request=current.request,
        projection=current.old.projection,
    )
    return lifecycle_cases.make_private_lifecycle_case(
        terminal, source, compiled.definition, monkeypatch
    )


@pytest.mark.parametrize(
    "case",
    [
        terminal_cases.test_private_terminal_preserves_exact_original_context_and_revalidates_replay,
        terminal_cases.test_private_terminal_requires_current_completion_owner_even_for_replay,
        terminal_cases.test_private_completed_replay_requires_exact_successful_terminal_shape,
    ],
)
def test_common_private_terminal_uses_same_exact_context_and_replay_rules(terminal, case):
    case(terminal)


@pytest.mark.parametrize("fault", ["extra_final", "missing_origin", "actor", "request"])
def test_common_private_terminal_rejects_changed_original_before_writes(terminal, fault):
    terminal_cases.test_private_terminal_refuses_bad_original_context_before_transition(
        terminal, fault
    )


@pytest.mark.parametrize(
    "case",
    [
        lifecycle_cases.test_running_private_step_success_and_terminal_preserve_context_without_sql_through_execute,
        lifecycle_cases.test_successful_private_step_replay_validates_receipt_without_another_execution,
        lifecycle_cases.test_late_completion_fence_rolls_back_step_promotion,
        lifecycle_cases.test_private_terminal_audit_actor_cannot_differ_from_original_operator,
        lifecycle_cases.test_original_start_with_unexplained_existing_step_is_not_repaired,
    ],
)
def test_common_private_step_reuses_original_success_replay_and_rollback(lifecycle, case):
    case(lifecycle)


@pytest.mark.parametrize("fault", ["foreign", "malformed", "replacement"])
def test_common_private_wrong_outcome_cannot_promote_step(lifecycle, fault):
    lifecycle_cases.test_wrong_private_outcome_never_promotes_step_or_terminal(lifecycle, fault)


@pytest.mark.parametrize(
    "actor_type,actor_id", [("system", None), ("human", "operator_" + "f" * 32)]
)
def test_common_private_wrong_actor_cannot_read_sources(lifecycle, actor_type, actor_id):
    lifecycle_cases.test_private_progression_rejects_wrong_audit_actor_before_source_read(
        lifecycle, actor_type, actor_id
    )


def test_common_private_original_start_creates_result2_in_same_allocation_root(
    lifecycle, monkeypatch
):
    lifecycle_cases.test_original_start_resolves_sources_before_writing_and_allocates_in_same_root(
        lifecycle, monkeypatch
    )
    assert lifecycle.step.result_schema == "embedding-reference-query-result@2.0"


def test_common_private_failed_initial_allocation_rolls_back_before_numerics(
    lifecycle, monkeypatch
):
    lifecycle_cases.test_failed_initial_allocation_rolls_back_workflow_start_before_physical_work(
        lifecycle, monkeypatch
    )


def test_common_private_unproven_pending_cannot_invent_another_launch(lifecycle, monkeypatch):
    lifecycle_cases.test_unproven_pending_launch_cannot_enqueue_another_operation(
        lifecycle, monkeypatch
    )


def test_common_private_cannot_accept_valid_legacy_completion(lifecycle, public_completed):
    lifecycle.executor.execute.side_effect = lambda **_kw: public_completed.previous.output
    with pytest.raises(WorkflowError):
        lifecycle.advance()
    lifecycle.executor.validate_completion.assert_not_called()
    assert lifecycle.step.state == "RUNNING" and lifecycle.terminal is None


def test_common_private_terminal_cannot_relabel_legacy_original(terminal, public_completed):
    terminal.workflow.initial_request = public_completed.previous.request.model_dump(mode="json")
    with pytest.raises(WorkflowError):
        terminal.complete()
    assert terminal.terminal is None
    terminal.session.add.assert_not_called()
