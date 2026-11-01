"""Actual source values/temporary controls; no production identity or numerical dispatch."""

from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow_runner.private_chat_query_launch_preparation import (
    PrivateChatQueryLaunchCandidate,
    prepare_private_chat_query_launch_candidate,
)
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.private_chat_batch_plan_fixtures import private_planning_case_for_parent
from tests.unit.test_private_chat_batch_plan_admission import make_private_batch_admission_case
from tests.unit.test_private_chat_public_query_native_executor import (
    make_public_private_executor_case,
)
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_native_executor import make_private_executor_case


@pytest.fixture(params=("CPU1", "CPU2", "CUDA2"))
def inputs(tmp_path, monkeypatch, request):
    if request.param == "CUDA2":
        value = make_private_batch_admission_case(tmp_path, monkeypatch, key="8" * 32)
        planned = private_planning_case_for_parent(
            NS(
                request=value.request,
                selection=value.selection,
                routing=value.routing,
                cpu=value.policies["CPU"],
                cuda=value.policies["CUDA"],
            )
        )
        context = build_private_chat_query_submission_context(planned.child, value.selection.origin)
        with value.publisher.sessions.begin() as session:
            sources = value.owner.cuda.resolve_submission(session, planned.child, context)
        return sources, "workflow_" + "8" * 32, "steprun_" + "8" * 32
    build = (
        make_private_executor_case if request.param == "CPU1" else make_public_private_executor_case
    )
    value = build(tmp_path, monkeypatch)
    with value.root() as session:
        sources = value.owner.resolve_execution_sources(
            session,
            value.request,
            value.lease(),
            workflow_id=value.workflow.workflow_id,
            step_run_id=value.step.step_run_id,
        )
    return sources, value.workflow.workflow_id, value.step.step_run_id


def prepare(inputs, existing=None, *, generation=1):
    sources, workflow, step = inputs
    return prepare_private_chat_query_launch_candidate(
        sources,
        workflow_id=workflow,
        step_run_id=step,
        command_lease=CommandLeaseIdentity(
            "wfcmd_" + str(generation) * 32, "synthetic-private-runner", "test", generation
        ),
        existing=existing,
    )


def test_private_launch_candidate_replay_keeps_original_ids_time_and_generation(inputs):
    value = prepare(inputs)
    replay = prepare(inputs, value.association, generation=2)
    assert replay == value
    assert replay.association.original_command_generation == 1
    assert TEXT not in repr(value)


def test_private_launch_candidate_rejects_another_workflow_without_leaking_question(inputs):
    value = prepare(inputs)
    sources, _workflow, step = inputs
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_LAUNCH_CANDIDATE_INVALID") as error:
        prepare((sources, "workflow_" + "f" * 32, step), value.association)
    assert TEXT not in str(error.value)


def test_private_launch_candidate_detects_changed_native_hash_without_repair(inputs):
    value = prepare(inputs)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_LAUNCH_CANDIDATE_INVALID") as error:
        replace(
            value, request=value.request.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
        )
    assert TEXT not in str(error.value)
    assert PrivateChatQueryLaunchCandidate(value.association, value.request) == value
