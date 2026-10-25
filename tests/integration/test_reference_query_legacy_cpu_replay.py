"""Real disposable PG replay; source/Identity/physical execution are synthetic leaves.

Broken/terminal metadata is injected only in the guarded disposable database.
These tests never mutate a production request or launch a model.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from eom_catalog_contracts.reference_query_prepare import (
    parse_supported_reference_query_prepare_request,
)
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_prepare_application import (
    prepared_application as prepared_application,
)
from tests.integration.test_reference_query_prepare_application import workflow_counts
from tests.integration.test_reference_query_submission import prepared_query as prepared_query
from tests.unit.inference_transfer_embedding_fixtures import seal

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def test_absent_original_does_not_capture_sources_or_create_cpu_work(prepared_application):
    case = prepared_application
    case.initial.side_effect = AssertionError("absence is not permission to start CPU work")
    assert case.app.observe_existing(case.wire) is None
    assert workflow_counts(case) == (0, 0) and case.offers == []
    case.initial.assert_not_called()
    case.value.executor.execute.assert_not_called()
    case.value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize(
    "prepared_query", ("PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"), indirect=True
)
def test_concurrent_original_observation_reuses_one_pinned_cpu_workflow(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    assert first.status == "PENDING"
    with Session(case.value.engine) as session:
        pinned = session.get(WorkflowInstanceRecord, first.workflow_id).initial_request
    case.initial.side_effect = AssertionError("original source pins must not be recaptured")
    barrier = Barrier(2)

    def replay(_):
        barrier.wait(timeout=10)
        return case.app.observe_existing(case.wire)

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(pool.map(replay, range(2)))
    assert all(
        reply.status == "PENDING" and reply.workflow_id == first.workflow_id for reply in replies
    )
    with Session(case.value.engine) as session:
        assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == pinned
    assert workflow_counts(case) == (1, 1)
    assert case.offers == [first.workflow_id] * 3
    case.value.executor.execute.assert_not_called()
    case.value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "COMPLETED"))
def test_terminal_or_unproven_history_never_becomes_new_work(prepared_application, state):
    case = prepared_application
    first = case.app.prepare(case.wire)
    with Session(case.value.engine) as session, session.begin():
        session.get(WorkflowInstanceRecord, first.workflow_id).state = state
    reply = case.app.observe_existing(case.wire)
    assert reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
    with Session(case.value.engine) as session:
        assert session.get(WorkflowInstanceRecord, first.workflow_id).state == state


def test_existing_original_current_authority_denial_is_not_absence(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    case.value.source.deny = True
    reply = case.app.observe_existing(case.wire)
    assert reply is not None and reply.status == "FAILED"
    assert reply.error_code == "AUTHORITY_UNAVAILABLE"
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]


@pytest.mark.parametrize("field", ("source", "graph", "policy"))
def test_changed_original_intent_is_rejected_without_new_route(prepared_application, field):
    case = prepared_application
    first = case.app.prepare(case.wire)
    body = case.wire.model_dump(mode="json")
    if field == "source":
        body["source_item_revision_id"] = "itemrev_" + "f" * 32
    elif field == "graph":
        body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    else:
        body["policy_sha256"] = "sha256:" + "f" * 64
    reply = case.app.observe_existing(
        parse_supported_reference_query_prepare_request(seal(body, "request_sha256"))
    )
    assert reply is not None and reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]


def test_missing_original_start_is_not_recreated_on_device_cutover(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    # Deliberately broken fixture only; never delete a live command for a test.
    with Session(case.value.engine) as session, session.begin():
        session.execute(
            delete(WorkflowCommandRecord).where(
                WorkflowCommandRecord.workflow_id == first.workflow_id
            )
        )
    with pytest.raises(ValueError, match="REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID"):
        case.app.observe_existing(case.wire)
    assert workflow_counts(case) == (1, 0) and case.offers == [first.workflow_id]


def test_failed_original_command_is_preserved_and_never_offered_again(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    with Session(case.value.engine) as session, session.begin():
        command = session.scalar(
            select(WorkflowCommandRecord).where(
                WorkflowCommandRecord.workflow_id == first.workflow_id
            )
        )
        command.state = "FAILED"
        command.error_code = "SYNTHETIC_INTERRUPTED_COMMAND"
    reply = case.app.observe_existing(case.wire)
    assert reply.status == "FAILED" and reply.error_code == "REFERENCE_QUERY_EXECUTION_FAILED"
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
    with Session(case.value.engine) as session:
        command = session.scalar(
            select(WorkflowCommandRecord).where(
                WorkflowCommandRecord.workflow_id == first.workflow_id
            )
        )
        assert command.state == "FAILED" and command.error_code == "SYNTHETIC_INTERRUPTED_COMMAND"


@pytest.mark.parametrize("created", ("workflow_created", "command_created"))
def test_late_recreation_observation_rolls_back_the_actual_root(
    prepared_application, monkeypatch, created
):
    from eom_workflow_runner import reference_query_preparation as module

    case = prepared_application
    first = case.app.prepare(case.wire)
    original = module.start_reference_query_in_session

    def storage_changed(session, **kwargs):
        submitted = original(session, **kwargs)
        assert not submitted.workflow_created and not submitted.command_created
        # A synthetic late storage observation in real disposable PG, not a
        # production row repair. Even root-local writes must not escape the refusal.
        submitted.command.error_code = "SYNTHETIC_UNCOMMITTED_OBSERVATION"
        return replace(submitted, **{created: True})

    monkeypatch.setattr(module, "start_reference_query_in_session", storage_changed)
    with pytest.raises(ValueError, match="REFERENCE_QUERY_PREPARATION_REPLAY_MISMATCH"):
        case.app.observe_existing(case.wire)
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
    with Session(case.value.engine) as session:
        command = session.scalar(
            select(WorkflowCommandRecord).where(
                WorkflowCommandRecord.workflow_id == first.workflow_id
            )
        )
        assert command.error_code is None
