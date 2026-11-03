"""Only the exact native slot03 prelaunch rejection may create a reviewed successor."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_launch_recovery import CreativeLaunchRecovery
from eom_workflow.models import WorkflowRequest
from eom_workflow_runner import external_item_learning_recovery as recovery
from eom_workflow_runner.external_item_learning_preparation import PreparedExternalItemLearning

from tests.unit.test_creative_result_recovery import failed_result
from tests.unit.test_office_item_learning import office_case


def failed_launch(monkeypatch):
    value = failed_result(monkeypatch)
    work, *_ = office_case()
    request = WorkflowRequest(
        request_name="EXTERNAL_ITEM_LEARNING_REQUEST",
        image_mode="skip",
        execution_preset_key="creative-office-learning",
        external_item_learning_work=work,
    ).model_dump(mode="json", exclude_none=True)
    for row in (value.parent, value.child):
        row.initial_request = deepcopy(request)
        row.request_payload = deepcopy(request)
        row.definition_version = "3.0.0"
        row.role_schema_version = "workflow-role/1.36.0"
    value.arguments["work"] = work
    value.arguments["definition"].definition_version = "3.0.0"
    value.parent.failure_code = value.step.error_code = value.job.error_code = "WORKER_UNAVAILABLE"
    value.step.result_schema = "external-item-learning-result@3.0"
    value.job.worker_slot_id = "03"
    value.job.error_message = "worker timeout does not match fixed unit contract"
    value.prepared = PreparedExternalItemLearning(
        value.prepared.selection.model_copy(update={"work_input_sha256": work.request_sha256}),
        True,
        True,
    )
    value.prepare.return_value = value.prepared
    value.confirm = Mock(return_value=True)
    return value


def test_exact_failed_launch_uses_same_source_and_preserves_failed_job(monkeypatch):
    value = failed_launch(monkeypatch)
    before = deepcopy(vars(value.parent)), deepcopy(vars(value.job))
    result = recovery.prepare_failed_launch_external_item_learning_recovery(
        value.session,
        **value.arguments,
        confirm_unit_absent=value.confirm,
    )
    note = CreativeLaunchRecovery.model_validate(value.event.call_args.kwargs["payload"])
    assert result == value.prepared
    assert note.reason == "FIXED_WORKER_CONTRACT_REJECTED"
    assert note.predecessor_job_id == value.job.job_id
    assert note.work_input_sha256 == value.arguments["work"].request_sha256
    assert before == (vars(value.parent), vars(value.job))
    assert value.child.runtime_context["creative_launch_recovery"] == note.model_dump(mode="json")
    value.confirm.assert_called_once_with("03", value.job.job_id)


@pytest.mark.parametrize("fault", ["other_error", "other_slot", "old_profile", "unit_uncertain"])
def test_other_or_unproven_failure_does_not_admit_reexecution(monkeypatch, fault):
    value = failed_launch(monkeypatch)
    if fault == "other_error":
        value.job.error_message = "some other failure"
    elif fault == "other_slot":
        value.job.worker_slot_id = "04"
    elif fault == "old_profile":
        value.parent.definition_version = "2.0.0"
    else:
        value.confirm.return_value = False
    with pytest.raises(ValueError):
        recovery.prepare_failed_launch_external_item_learning_recovery(
            value.session,
            **value.arguments,
            confirm_unit_absent=value.confirm,
        )
    value.prepare.assert_not_called()
    value.event.assert_not_called()


@pytest.mark.parametrize("position", range(4))
def test_commit_artifact_live_command_or_lease_each_blocks_launch_recovery(monkeypatch, position):
    value = failed_launch(monkeypatch)
    value.session.scalar.side_effect = [value.job] + [None] * position + ["present"]
    with pytest.raises(ValueError, match="COMMITTED_OR_ACTIVE"):
        recovery.prepare_failed_launch_external_item_learning_recovery(
            value.session,
            **value.arguments,
            confirm_unit_absent=value.confirm,
        )
    value.prepare.assert_not_called()
