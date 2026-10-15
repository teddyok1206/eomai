"""Actual guarded PostgreSQL application roots/replay; Identity/source/driver are synthetic.

No model, installed API capture or NAS writes. Synthetic failed/completed state
injection is confined to this disposable database and is not live acceptance.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.similarity_context_service import validate_similarity_preparation
from eom_identity_service import OperatorAuthorizationFenceError
from eom_workflow.reference_query_execution import parse_reference_query_workflow_request
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_prepare_application import (
    NativeReferenceQueryPreparation,
    reference_query_prepare_identity,
)
from eom_workflow_runner.reference_query_prepare_driver import ReferenceQueryPrepareDriver
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_reference_query_submission import prepared_query as prepared_query
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_prepare_application import query_runner, wire_request

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def prepared_application(prepared_query, monkeypatch):
    value = prepared_query
    wire = wire_request(value.source, key=value.key)
    key, context_id = reference_query_prepare_identity(
        value.caller.operator_id, wire.idempotency_key
    )
    context = value.context.model_dump(mode="json")
    context["request_id"] = context_id
    context["views"].append(
        {"view": "METADATA_ONLY", "recipe": context["views"][0]["recipe"], "index": None}
    )
    context = parse_similarity_context_request(seal(context, "request_sha256"))
    value.context = context
    value.source.request = parse_reference_query_workflow_request(
        seal(
            value.source.request.model_dump(mode="json")
            | {"context_request": context.model_dump(mode="json")},
            "request_sha256",
        )
    )
    value.source.prepared = replace(value.source.prepared, request_sha256=context.request_sha256)

    def anchor(session, caller, current):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert caller == value.caller and current == value.context
        validate_similarity_preparation(current, value.source.prepared)
        return value.source.prepared

    initial = Mock(side_effect=lambda *_: value.context)
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_anchor_in_session", anchor
    )
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", initial
    )
    driver = ReferenceQueryPrepareDriver()
    runner = query_runner(value.source.owner, value.executor)
    app = NativeReferenceQueryPreparation(
        owner=value.source.owner,
        executor=value.executor,
        runner=runner,
        driver=driver,
        spaces=value.source.policy.spaces,
    )
    offers = []

    def offer(workflow_id, actual_runner):
        # A distinct real PostgreSQL connection can see both rows: physical drive
        # is never offered before admission/START commit.
        assert actual_runner is runner
        with Session(value.engine) as session:
            workflow = session.get(WorkflowInstanceRecord, workflow_id)
            assert workflow is not None and workflow.idempotency_key == key
            assert (
                session.scalar(
                    select(WorkflowCommandRecord.command_id).where(
                        WorkflowCommandRecord.idempotency_key == "start:" + workflow_id
                    )
                )
                is not None
            )
        offers.append(workflow_id)
        return "BUSY"

    monkeypatch.setattr(driver, "offer", offer)
    return SimpleNamespace(value=value, app=app, wire=wire, key=key, offers=offers, initial=initial)


def workflow_counts(case):
    with Session(case.value.engine) as session:
        workflow = session.scalar(
            select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == case.key)
        )
        if workflow is None:
            return 0, 0
        return 1, session.scalar(
            select(func.count())
            .select_from(WorkflowCommandRecord)
            .where(WorkflowCommandRecord.workflow_id == workflow.workflow_id)
        )


def test_real_application_commits_before_offer_and_replay_preserves_original(prepared_application):
    case = prepared_application
    first = case.app.prepare(case.wire)
    assert first.status == "PENDING" and first.selection is None
    with Session(case.value.engine) as session:
        original = session.get(WorkflowInstanceRecord, first.workflow_id).initial_request
    case.initial.side_effect = AssertionError("recapturing initial source on replay")
    second = case.app.prepare(
        wire_request(case.value.source, key=case.wire.idempotency_key, operation="b")
    )
    assert second.status == "PENDING" and second.workflow_id == first.workflow_id
    assert second.request_sha256 != first.request_sha256
    with Session(case.value.engine) as session:
        assert session.get(WorkflowInstanceRecord, first.workflow_id).initial_request == original
    assert workflow_counts(case) == (1, 1)
    assert case.offers == [first.workflow_id, first.workflow_id]
    case.value.executor.execute.assert_not_called()
    case.value.executor.allocate_execution.assert_not_called()


def test_same_key_concurrent_application_uses_one_workflow_start(prepared_application):
    case = prepared_application
    barrier = Barrier(2)

    def initial(*_args):
        barrier.wait(timeout=10)
        return case.value.context

    case.initial.side_effect = initial
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = tuple(pool.map(lambda _: case.app.prepare(case.wire), range(2)))
    assert all(reply.status == "PENDING" for reply in replies)
    assert replies[0].workflow_id == replies[1].workflow_id
    assert workflow_counts(case) == (1, 1)
    case.value.executor.execute.assert_not_called()


@pytest.mark.parametrize("field", ("source", "policy", "graph"))
def test_changed_same_key_intent_never_creates_replacement_work(prepared_application, field):
    case = prepared_application
    first = case.app.prepare(case.wire)
    body = case.wire.model_dump(mode="json")
    if field == "source":
        body["source_item_revision_id"] = "itemrev_" + "f" * 32
    elif field == "policy":
        body["policy_sha256"] = "sha256:" + "f" * 64
    else:
        body["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    from eom_catalog_contracts.reference_query_prepare import ReferenceQueryPrepareRequest

    changed = ReferenceQueryPrepareRequest.model_validate(seal(body, "request_sha256"))
    reply = case.app.prepare(changed)
    assert reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]


@pytest.mark.parametrize("missing", ("report", "index"))
def test_known_absence_persists_no_queue_work(prepared_application, missing):
    case = prepared_application
    body = case.value.context.model_dump(mode="json")
    if missing == "report":
        body["anchor"]["profile"] = body["anchor"]["solution_evidence"] = None
    else:
        for row in body["views"]:
            row["index"] = None
    case.value.context = parse_similarity_context_request(seal(body, "request_sha256"))
    reply = case.app.prepare(case.wire)
    assert reply.status == "UNAVAILABLE"
    assert workflow_counts(case) == (0, 0) and case.offers == []


def test_late_current_denial_rolls_back_admission_and_start(prepared_application, monkeypatch):
    case = prepared_application
    original = case.value.source.owner.resolve_submission
    calls = 0

    def deny_late(session, request):
        nonlocal calls
        calls += 1
        result = original(session, request)
        if calls == 4:
            raise OperatorAuthorizationFenceError("synthetic late authority revocation")
        return result

    monkeypatch.setattr(case.value.source.owner, "resolve_submission", deny_late)
    reply = case.app.prepare(case.wire)
    assert reply.status == "FAILED" and reply.error_code == "AUTHORITY_UNAVAILABLE"
    assert calls == 4 and workflow_counts(case) == (0, 0) and case.offers == []


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED", "COMPLETED", "AWAITING_HUMAN_APPROVAL"))
def test_state_alone_never_grants_ready_or_restart(prepared_application, state):
    case = prepared_application
    first = case.app.prepare(case.wire)
    # Deliberately inject impossible terminal metadata in the disposable fixture.
    # No canonical Job/result/receipt is fabricated to make this a success.
    with Session(case.value.engine) as session, session.begin():
        session.get(WorkflowInstanceRecord, first.workflow_id).state = state
    reply = case.app.prepare(case.wire)
    assert reply.status == "FAILED" and reply.selection is None
    assert workflow_counts(case) == (1, 1) and case.offers == [first.workflow_id]
