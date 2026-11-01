"""Shared real Runner dispatch2; source, receipt, SQL and numerical ports are synthetic."""

import pytest
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2
from eom_workflow_runner.repository import CommandExecutionFamily, peek_command_candidate

from tests.unit import test_private_chat_query_runner_execution as runner_cases
from tests.unit.test_local_embedding_command_claim import candidate_fixture
from tests.unit.test_private_chat_public_query_step_execution import lifecycle as lifecycle
from tests.unit.test_private_chat_public_query_step_execution import terminal as terminal
from tests.unit.test_private_chat_public_query_workflow import public_completed as public_completed
from tests.unit.test_private_chat_query_workflow import completed as completed


def test_common_private_candidate_retains_exact_request2(lifecycle):
    fixture, workflow, _command = candidate_fixture()
    workflow.initial_request = workflow.request_payload = lifecycle.request.model_dump(mode="json")
    workflow.definition_key = lifecycle.request.workflow_definition_key
    workflow.role_schema_version = "private-chat-query/2.0"
    candidate = peek_command_candidate(
        fixture.session, family=CommandExecutionFamily.PRIVATE_CHAT_QUERY
    )
    assert isinstance(candidate.native_request, PrivateChatQueryWorkflowRequestV2)
    assert candidate.native_request == lifecycle.request
    fixture.owner.resolve_claim.assert_not_called()


def test_common_private_runner_reuses_original_dispatch_and_terminal(lifecycle):
    runner_cases.test_runner_dispatches_private_step_and_terminal_without_role_or_public_fallback(
        lifecycle
    )


@pytest.mark.parametrize(
    "fault", ["family", "owner", "executor", "command", "native_request", "native_lease"]
)
def test_common_private_runner_rejects_foreign_execution_before_mutation(lifecycle, fault):
    runner_cases.test_runner_refuses_unoffered_or_foreign_private_context_before_mutation(
        lifecycle, fault
    )


@pytest.mark.parametrize("fault", ["actor", "actor_type", "request", "source"])
def test_common_private_errors_do_not_disclose_question(lifecycle, fault):
    runner_cases.test_runner_private_errors_are_stable_and_never_render_question_or_adapter_details(
        lifecycle, fault
    )


def test_common_private_run_once_claims_only_its_pair(lifecycle, monkeypatch):
    runner_cases.test_run_once_passes_the_private_pair_and_completes_the_original_command(
        lifecycle, monkeypatch
    )


@pytest.mark.parametrize("fault", [None, "family", "owner", "executor", "request", "unready"])
def test_common_private_readiness_cannot_borrow_other_ports(lifecycle, monkeypatch, fault):
    runner_cases.test_private_candidate_readiness_requires_its_own_exact_ports(
        lifecycle, monkeypatch, fault
    )


def test_common_private_does_not_starve_ready_index_work(lifecycle, monkeypatch):
    runner_cases.test_unavailable_private_query_cannot_starve_ready_existing_index_work(
        lifecycle, monkeypatch
    )


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_common_private_cannot_revive_terminal_failure(lifecycle, state):
    runner_cases.test_runner_never_revives_failed_or_cancelled_original_private_work(
        lifecycle, state
    )


def test_common_private_pending_reuses_original_and_does_not_open_terminal(lifecycle, monkeypatch):
    runner_cases.test_runner_pending_result_returns_without_terminal_or_another_attempt(
        lifecycle, monkeypatch
    )


def test_common_private_native_root_uses_only_its_owner(lifecycle, monkeypatch):
    runner_cases.test_runner_native_root_uses_private_owner_never_reference_or_index(
        lifecycle, monkeypatch
    )
