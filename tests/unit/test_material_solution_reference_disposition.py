"""A known report-reference limitation is task-local; no authority failure is hidden."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import material_learning_processing as owner
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisServiceError
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.registered_item_solution_base import RegisteredItemSolutionReferenceError


def case(monkeypatch, error):
    tasks = [
        NS(
            task_id=f"synthetic-task-{i}",
            task_kind="QUESTION",
            state="ANALYZING",
            item_revision_id=f"synthetic-item-{i}",
        )
        for i in range(2)
    ]
    bases = [NS(analysis_run_id=f"synthetic-base-{i}", state="ACCEPTED") for i in range(2)]
    run = NS(run_id="synthetic-run", state="PROCESSING")
    claim = NS(run_id=run.run_id)
    context = NS(operator_id="synthetic-operator")
    session = NS(get=lambda *_: run, expunge=Mock())
    service = object.__new__(owner.MaterialLearningProcessingService)
    service.sessions = lambda: nullcontext(session)
    service.coordinator = Mock()
    service.coordinator.claim.return_value = claim
    service.coordinator.context.return_value = context
    service.coordinator.discovery_plan.return_value = None
    service._analysis_pins = Mock(return_value=("owned-base", None))
    service._paused = Mock(return_value=False)
    service._pin_analysis = Mock()
    service.graph = Mock()
    service.graph.advance_item_analysis.side_effect = bases
    service.graph.advance_item_solution.side_effect = [
        error,
        NS(state="QUEUED", workflow_id="synthetic-next-workflow"),
    ]

    def fail(actual_claim, task_id, code):
        assert actual_claim is claim
        task = next(task for task in tasks if task.task_id == task_id)
        task.state, task.error_code = "FAILED", code

    service.coordinator.fail_task.side_effect = fail
    monkeypatch.setattr(
        owner,
        "next_material_task",
        lambda *_: next((t for t in tasks if t.state != "FAILED"), None),
    )
    return service, claim, tasks, bases


def base_error(cause):
    error = KnowledgeAnalysisServiceError("KNOWLEDGE_ANALYSIS_BASE_INVALID", "synthetic")
    error.__cause__ = cause
    return error


def test_known_reference_limitation_marks_only_current_task_failed_and_next_task_progresses(
    monkeypatch,
):
    service, claim, tasks, bases = case(
        monkeypatch, base_error(RegisteredItemSolutionReferenceError())
    )
    first = service.advance_once()
    assert first.phase == "FAILED" and first.task_id == tasks[0].task_id
    service.coordinator.fail_task.assert_called_once_with(
        claim, tasks[0].task_id, RegisteredItemSolutionReferenceError.code
    )
    assert tasks[0].item_revision_id == "synthetic-item-0"
    assert bases[0].state == "ACCEPTED"
    assert tasks[1].state == "ANALYZING"

    second = service.advance_once()
    assert second.phase == "ANALYZING" and second.task_id == tasks[1].task_id
    assert second.workflow_to_drive == "synthetic-next-workflow"
    assert service.coordinator.release.call_count == 2
    assert service.coordinator.fail_task.call_count == 1
    assert bases[0].state == bases[1].state == "ACCEPTED"
    assert service._pin_analysis.call_count == 3  # Two accepted bases and only the next report.


@pytest.mark.parametrize("fault", ("plain_base", "hash", "source", "permission", "wrong_code"))
def test_unrelated_base_source_hash_and_authority_failures_still_propagate(monkeypatch, fault):
    if fault == "plain_base":
        error = base_error(None)
    elif fault == "hash":
        error = base_error(ValueError("synthetic hash mismatch"))
    elif fault == "source":
        error = MaterialLearningSourceError("MATERIAL_LEARNING_SOURCE_INVALID")
    elif fault == "permission":
        error = base_error(PermissionError("synthetic permission denied"))
    else:
        error = KnowledgeAnalysisServiceError("KNOWLEDGE_ANALYSIS_POINTER_INVALID", "synthetic")
        error.__cause__ = RegisteredItemSolutionReferenceError()
    service, _claim, tasks, bases = case(monkeypatch, error)
    with pytest.raises(type(error)) as raised:
        service.advance_once()
    assert raised.value is error
    service.coordinator.fail_task.assert_not_called()
    service.coordinator.release.assert_called_once()
    assert all(task.state == "ANALYZING" for task in tasks)
    assert all(base.state == "ACCEPTED" for base in bases)
