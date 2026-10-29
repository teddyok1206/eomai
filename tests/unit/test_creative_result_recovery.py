"""Only proven pre-commit result rejection admits an explicit new extraction."""

from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from eom_catalog_contracts.creative_result_recovery import CreativeResultRecovery
from eom_workflow_runner import external_item_learning_recovery as recovery

from tests.unit.test_creative_preexecution_recovery import case


def failed_result(monkeypatch):
    value = case(monkeypatch)
    value.parent.failure_code = value.step.error_code = "WORKER_RESULT_INVALID"
    value.step.platform_job_id = "job_" + "c" * 32
    value.job = NS(
        job_id=value.step.platform_job_id, status="FAILED", error_code="WORKER_RESULT_INVALID"
    )
    value.session.scalar.side_effect = [value.job, None, None, None, None]
    return value


def test_explicit_failed_result_preparation_preserves_history_and_exact_job(monkeypatch):
    value = failed_result(monkeypatch)
    before = deepcopy(vars(value.parent)), deepcopy(vars(value.step)), deepcopy(vars(value.job))
    prepared = recovery.prepare_invalid_result_external_item_learning_recovery(
        value.session, **value.arguments
    )
    note = CreativeResultRecovery.model_validate(value.event.call_args.kwargs["payload"])
    assert prepared == value.prepared
    assert note.predecessor_job_id == value.job.job_id
    assert note.reason == "INVALID_RESULT_BEFORE_COMMIT"
    assert before == (vars(value.parent), vars(value.step), vars(value.job))
    assert value.child.runtime_context["creative_result_recovery"] == note.model_dump(mode="json")
    assert value.event.call_args.args[2] == recovery.RESULT_RECOVERY_EVENT


@pytest.mark.parametrize(
    "fault", ["missing_job", "wrong_job", "running", "succeeded", "error", "step", "output"]
)
def test_ineligible_or_uncertain_work_cannot_be_reexecuted(monkeypatch, fault):
    value = failed_result(monkeypatch)
    if fault == "missing_job":
        value.session.scalar.side_effect = [None]
    elif fault == "wrong_job":
        value.job.job_id = "job_" + "d" * 32
    elif fault in {"running", "succeeded"}:
        value.job.status = fault.upper()
    elif fault == "error":
        value.job.error_code = "OTHER_FAILURE"
    elif fault == "step":
        value.step.state = "SUCCEEDED"
    else:
        value.step.output_pointer_manifest = {"unexpected": "output"}
    with pytest.raises(ValueError, match="NOT_ELIGIBLE"):
        recovery.prepare_invalid_result_external_item_learning_recovery(
            value.session, **value.arguments
        )
    value.prepare.assert_not_called()
    value.event.assert_not_called()


@pytest.mark.parametrize("position", range(4))
def test_artifact_commit_history_active_command_and_lease_each_block_reexecution(
    monkeypatch, position
):
    value = failed_result(monkeypatch)
    value.session.scalar.side_effect = [value.job] + [None] * position + ["existing"]
    with pytest.raises(ValueError, match="COMMITTED_OR_ACTIVE"):
        recovery.prepare_invalid_result_external_item_learning_recovery(
            value.session, **value.arguments
        )
    value.prepare.assert_not_called()


def test_failed_job_cannot_be_claimed_as_no_job_recovery(monkeypatch):
    value = failed_result(monkeypatch)
    with pytest.raises(ValueError):
        recovery.prepare_unstarted_external_item_learning_recovery(value.session, **value.arguments)
    value.prepare.assert_not_called()
