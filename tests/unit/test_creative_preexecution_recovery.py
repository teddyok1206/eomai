"""No-Job recovery proves absence before preparing a distinct auditable successor."""

from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_preexecution_recovery import CreativePreexecutionRecovery
from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningRoleSelection,
)
from eom_identifiers import content_sha256
from eom_workflow_runner import external_item_learning_recovery as recovery
from eom_workflow_runner.engine import _step_job_idempotency_key
from eom_workflow_runner.external_item_learning_preparation import PreparedExternalItemLearning
from eom_workflow_runner.role_job_identity import role_job_idempotency_key

from tests.unit.test_external_item_learning_authorization import _case


def case(monkeypatch):
    original = _case(successor=True)
    parent, step = original.workflow, original.step
    parent.state = parent.stage = "FAILED"
    parent.failure_code = "WORKFLOW_STEP_FAILED"
    parent.current_step_key = "extract"
    parent.runtime_context = {}
    step.state = "FAILED"
    step.error_code = "WORKFLOW_STEP_FAILED"
    step.platform_job_id = step.output_pointer_manifest = step.superseded_by_step_run_id = None
    child = NS(**vars(parent))
    child.workflow_id = "workflow_" + "f" * 32
    child.state, child.stage = "REQUESTED", "KNOWLEDGE_ANALYSIS"
    child.runtime_context = {}
    session = Mock()
    session.in_transaction.return_value = True
    session.get.side_effect = lambda model, identity, **kwargs: (
        parent if identity == parent.workflow_id else child
    )
    session.scalars.side_effect = [(step,), ()]
    session.scalar.return_value = None
    selection = ExternalItemLearningRoleSelection.model_validate(
        original.request.selection.model_dump() | {"workflow_id": child.workflow_id}
    )
    prepared = PreparedExternalItemLearning(selection, True, True)
    prepare = Mock(return_value=prepared)
    event = Mock()
    monkeypatch.setattr(recovery, "prepare_external_item_learning_workflow", prepare)
    monkeypatch.setattr(recovery, "record_workflow_event", event)
    arguments = dict(
        predecessor_workflow_id=parent.workflow_id,
        definition=NS(
            definition_hash=parent.definition_hash, definition_version=parent.definition_version
        ),
        work=original.worker_request.work_input,
        operator_id=parent.created_actor_id,
        source_authorizer=Mock(),
        page_publisher=Mock(),
        expected_preset=Mock(),
    )
    return NS(**locals())


def test_preparation_keeps_failed_history_and_records_an_exact_successor_link(monkeypatch):
    value = case(monkeypatch)
    before = deepcopy(vars(value.parent))
    actual = recovery.prepare_unstarted_external_item_learning_recovery(
        value.session, **value.arguments
    )
    assert actual == value.prepared and vars(value.parent) == before
    note = CreativePreexecutionRecovery.model_validate(value.event.call_args.kwargs["payload"])
    assert note.predecessor_workflow_id == value.parent.workflow_id
    assert note.successor_workflow_id == value.child.workflow_id
    assert note.work_input_sha256 == value.original.worker_request.work_input.request_sha256
    assert value.child.runtime_context["creative_preexecution_recovery"] == note.model_dump(
        mode="json"
    )
    assert value.prepare.call_args.kwargs["work"] == value.arguments["work"]


@pytest.mark.parametrize(
    "fault", ["workflow_state", "job_pointer", "step_state", "output", "owner"]
)
def test_an_ineligible_predecessor_never_prepares_or_relabels_history(monkeypatch, fault):
    value = case(monkeypatch)
    if fault == "workflow_state":
        value.parent.state = "RUNNING"
    elif fault == "step_state":
        value.step.state = "SUCCEEDED"
    elif fault == "job_pointer":
        value.step.platform_job_id = "job_" + "a" * 32
    elif fault == "output":
        value.step.output_pointer_manifest = {"artifact": "not empty"}
    else:
        value.arguments["operator_id"] = "operator_" + "2" * 32
    with pytest.raises(ValueError):
        recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    value.prepare.assert_not_called()
    value.event.assert_not_called()


def test_other_active_equivalent_workflow_cannot_have_its_provenance_replaced(monkeypatch):
    value = case(monkeypatch)
    value.prepare.return_value = PreparedExternalItemLearning(
        value.prepared.selection, False, False
    )
    with pytest.raises(ValueError, match="SUCCESSOR_CONFLICT"):
        recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    assert value.child.runtime_context == {}
    value.event.assert_not_called()


@pytest.mark.parametrize("position", [0, 1, 2])
def test_unbound_job_or_live_command_or_held_lease_blocks_recovery(monkeypatch, position):
    value = case(monkeypatch)
    value.session.scalar.side_effect = [None] * position + ["existing work"]
    with pytest.raises(ValueError, match="WORK_EXISTS"):
        recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    value.prepare.assert_not_called()


def test_a_failed_workflow_without_a_recorded_link_is_not_automatically_retried(monkeypatch):
    value = case(monkeypatch)
    value.session.scalars.side_effect = [()]
    assert (
        recovery.resolve_external_item_learning_recovery(value.session, value.parent)
        is value.parent
    )
    value.prepare.assert_not_called()


def test_role_job_key_remains_byte_identical_to_the_original_engine_rule():
    args = ("workflow_" + "a" * 32, "extract", 1, "sha256:" + "b" * 64)
    expected = (
        "wfstep-"
        + content_sha256(
            dict(zip(("workflow_id", "step_key", "attempt", "definition_hash"), args, strict=True))
        )[7:]
    )
    assert role_job_idempotency_key(*args) == _step_job_idempotency_key(*args) == expected


def test_recovery_record_cannot_point_to_itself_or_hide_hash_changes(monkeypatch):
    value = case(monkeypatch)
    recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    note = value.event.call_args.kwargs["payload"]
    for change in (
        {"successor_workflow_id": note["predecessor_workflow_id"]},
        {"work_input_sha256": "sha256:" + "0" * 64},
    ):
        with pytest.raises(ValueError):
            CreativePreexecutionRecovery.model_validate(note | change)


@pytest.mark.parametrize("fault", [None, "owner", "initial", "payload", "role", "record"])
def test_recorded_successor_must_retain_exact_owner_source_family_and_link(monkeypatch, fault):
    value = case(monkeypatch)
    recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    note = CreativePreexecutionRecovery.model_validate(value.event.call_args.kwargs["payload"])
    monkeypatch.setattr(recovery, "_successor_event", lambda *args: note)
    monkeypatch.setattr(
        recovery, "_failed_input", lambda *args: (value.arguments["work"], value.step)
    )
    if fault == "owner":
        value.child.created_actor_id = "operator_" + "9" * 32
    elif fault == "initial":
        value.child.initial_request = {}
    elif fault == "payload":
        value.child.request_payload = {}
    elif fault == "role":
        value.child.role_schema_version = "workflow-role/1.33.0"
    elif fault == "record":
        value.child.runtime_context = {}
    if fault:
        with pytest.raises(ValueError, match="LINK_MISMATCH"):
            recovery.resolve_external_item_learning_recovery(value.session, value.parent)
    else:
        assert recovery.resolve_external_item_learning_recovery(value.session, value.parent) is (
            value.child
        )
