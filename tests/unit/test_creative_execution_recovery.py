"""Terminal process proof permits one successor, not a retry/commit bypass."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_execution_recovery import CreativeExecutionRecovery
from eom_orchestrator.models import JobRecord
from eom_workflow_runner import external_item_learning_recovery as recovery

from tests.unit.test_creative_result_recovery import failed_result


def failed_execution(monkeypatch):
    value = failed_result(monkeypatch)
    value.parent.failure_code = value.step.error_code = value.job.error_code = "WORKER_EXEC_FAILED"
    value.job.worker_slot_id, value.job.worker_exit_code = "04", 1
    original_get = value.session.get.side_effect
    value.session.get.side_effect = lambda model, identity, **kwargs: (
        value.job if model is JobRecord else original_get(model, identity, **kwargs)
    )
    value.confirm = Mock(return_value=True)
    return value


def test_terminated_process_uses_same_input_and_preserves_failed_job(monkeypatch):
    value = failed_execution(monkeypatch)
    before = deepcopy(vars(value.parent)), deepcopy(vars(value.job))
    result = recovery.prepare_failed_execution_external_item_learning_recovery(
        value.session, **value.arguments, confirm_unit_terminal=value.confirm
    )
    assert result == value.prepared and before == (vars(value.parent), vars(value.job))
    note = CreativeExecutionRecovery.model_validate(value.event.call_args.kwargs["payload"])
    assert note.predecessor_job_id == value.job.job_id
    assert note.work_input_sha256 == value.arguments["work"].request_sha256
    assert value.child.runtime_context["creative_execution_recovery"] == note.model_dump(
        mode="json"
    )
    value.confirm.assert_called_once_with("04", value.job.job_id)


def test_historical_orphan_requires_real_process_absence_without_rewriting_metadata(monkeypatch):
    value = failed_execution(monkeypatch)
    value.parent.failure_code = value.step.error_code = "WORKFLOW_STEP_FAILED"
    value.job.status, value.job.error_code, value.job.worker_exit_code = "RUNNING", None, None
    before = deepcopy(vars(value.parent)), deepcopy(vars(value.job))
    result = recovery.prepare_failed_execution_external_item_learning_recovery(
        value.session, **value.arguments, confirm_unit_terminal=value.confirm
    )
    assert result == value.prepared and before == (vars(value.parent), vars(value.job))
    value.confirm.assert_called_once_with("04", value.job.job_id)


def test_an_orphan_with_uncertain_process_is_not_reexecuted(monkeypatch):
    value = failed_execution(monkeypatch)
    value.parent.failure_code = value.step.error_code = "WORKFLOW_STEP_FAILED"
    value.job.status, value.job.error_code, value.job.worker_exit_code = "RUNNING", None, None
    value.confirm.return_value = False
    with pytest.raises(ValueError, match="UNIT_UNCERTAIN"):
        recovery.prepare_failed_execution_external_item_learning_recovery(
            value.session, **value.arguments, confirm_unit_terminal=value.confirm
        )
    value.prepare.assert_not_called()


@pytest.mark.parametrize(
    "fault", ["running", "no_exit", "successful_exit", "no_slot", "uncertain_unit", "other_error"]
)
def test_unproven_or_other_failure_cannot_start_another_process(monkeypatch, fault):
    value = failed_execution(monkeypatch)
    if fault == "running":
        value.job.status = "RUNNING"
    elif fault == "no_exit":
        value.job.worker_exit_code = None
    elif fault == "successful_exit":
        value.job.worker_exit_code = 0
    elif fault == "no_slot":
        value.job.worker_slot_id = None
    elif fault == "uncertain_unit":
        value.confirm.return_value = False
    else:
        value.job.error_code = "WORKER_RESULT_INVALID"
    with pytest.raises(ValueError):
        recovery.prepare_failed_execution_external_item_learning_recovery(
            value.session, **value.arguments, confirm_unit_terminal=value.confirm
        )
    value.prepare.assert_not_called()
    value.event.assert_not_called()


@pytest.mark.parametrize("position", range(4))
def test_artifact_commit_command_and_lease_each_prevent_reexecution(monkeypatch, position):
    value = failed_execution(monkeypatch)
    value.session.scalar.side_effect = [value.job] + [None] * position + ["present"]
    with pytest.raises(ValueError, match="COMMITTED_OR_ACTIVE"):
        recovery.prepare_failed_execution_external_item_learning_recovery(
            value.session, **value.arguments, confirm_unit_terminal=value.confirm
        )
    value.prepare.assert_not_called()


def test_changed_record_hash_and_self_link_are_rejected(monkeypatch):
    value = failed_execution(monkeypatch)
    recovery.prepare_failed_execution_external_item_learning_recovery(
        value.session, **value.arguments, confirm_unit_terminal=value.confirm
    )
    payload = value.event.call_args.kwargs["payload"]
    with pytest.raises(ValueError, match="LINK_INVALID"):
        CreativeExecutionRecovery.model_validate(payload | {"record_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="LINK_INVALID"):
        CreativeExecutionRecovery.model_validate(
            payload | {"successor_workflow_id": payload["predecessor_workflow_id"]}
        )
