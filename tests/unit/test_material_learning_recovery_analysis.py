"""Analysis reuse decisions with explicit synthetic authority/storage ports."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts import CreateKnowledgeSolutionAnalysisCommand
from eom_catalog_service import material_graph_learning as owner
from eom_catalog_service.knowledge_analysis_service import KnowledgeAnalysisApplicationService
from eom_catalog_service.material_learning_models import MaterialLearningTaskRecord
from eom_catalog_service.material_learning_recovery import _quiescent_failed_workflows
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_task_history import MaterialTaskHistory
from eom_orchestrator.knowledge_analysis_models import KnowledgeAnalysisRunRecord
from pydantic import ValidationError

from tests.unit.test_material_learning_contracts import extraction_work

ITEM = "itemrev_" + "1" * 32
BASE = "analysisrun_" + "2" * 32
SOLUTION = "analysisrun_" + "3" * 32
ACTOR = "operator_" + "4" * 32


def test_material_solution_uses_internal_purpose_without_relaxing_public_command():
    command = CreateKnowledgeSolutionAnalysisCommand(
        base_analysis_run_id=BASE,
        requested_by=ACTOR,
        idempotency_key="material-solution-purpose-regression",
    )
    service = Mock(spec=KnowledgeAnalysisApplicationService)
    KnowledgeAnalysisApplicationService.create_material_solution_with_pinned_preset(
        service,
        command,
        preset_id="preset",
        preset_revision_id="revision",
    )
    assert service._create_solution.call_args.args == (command,)
    assert service._create_solution.call_args.kwargs == {
        "pinned_preset": ("preset", "revision"),
        "pinned_preset_key": "material-item-solution",
    }
    with pytest.raises(ValidationError):
        CreateKnowledgeSolutionAnalysisCommand.model_validate(
            {**command.model_dump(mode="json"), "preset_key": "material-item-solution"}
        )


def case(monkeypatch, *, base_state="ACCEPTED", solution_state="FAILED"):
    old = MaterialLearningTaskRecord(
        task_id="materialtask_" + "a" * 32,
        input_artifact_id="artifact_" + "b" * 32,
        input_artifact_revision_id="rev_" + "c" * 32,
        input_sha256="sha256:" + "d" * 64,
        item_revision_id=ITEM,
        analysis_run_id=BASE,
        solution_analysis_run_id=SOLUTION,
    )
    current = MaterialLearningTaskRecord(
        task_id="materialtask_" + "e" * 32,
        predecessor_task_id=old.task_id,
        input_artifact_id=old.input_artifact_id,
        input_artifact_revision_id=old.input_artifact_revision_id,
        input_sha256=old.input_sha256,
        item_revision_id=ITEM,
    )
    history = MaterialTaskHistory((current, old))
    base = SimpleNamespace(
        analysis_run_id=BASE,
        state=base_state,
        canonical_request={"source": {"item_revision_id": ITEM}},
    )
    solution = SimpleNamespace(
        analysis_run_id=SOLUTION, state=solution_state, predecessor_analysis_run_id=BASE
    )
    rows = {
        (MaterialLearningTaskRecord, current.task_id): current,
        (KnowledgeAnalysisRunRecord, BASE): base,
        (KnowledgeAnalysisRunRecord, SOLUTION): solution,
    }
    session = SimpleNamespace(get=lambda model, key: rows.get((model, key)))
    graph = object.__new__(owner.MaterialGraphLearningService)
    graph.sessions = lambda: nullcontext(session)
    graph.artifacts = Mock()
    graph.sources = Mock()
    preset = SimpleNamespace(preset_id="preset", preset_revision_id="revision")
    graph.controls = SimpleNamespace(
        item=preset, solution=preset, risk_policy_revision_id="analysisriskrev_" + "f" * 32
    )
    graph.analyses = Mock()
    graph.analyses.reconcile.side_effect = lambda command: SimpleNamespace(
        analysis_run_id=command.analysis_run_id,
        state=base_state
        if command.analysis_run_id == BASE
        else solution_state
        if command.analysis_run_id == SOLUTION
        else "ACCEPTED",
    )
    monkeypatch.setattr(
        owner, "read_material_task_histories", lambda *_args: {current.task_id: history}
    )
    monkeypatch.setattr(
        owner,
        "resolve_completed_material_task",
        lambda *_args, **_kwargs: SimpleNamespace(work=extraction_work()),
    )
    monkeypatch.setattr(owner, "authorize_material_learning", lambda *_args: None)
    return graph, current, old, base, solution


def test_retry_reuses_accepted_base_without_new_worker(monkeypatch):
    graph, task, old, base, _ = case(monkeypatch)
    result = graph.advance_item_analysis(
        task_id=task.task_id, item_revision_id=ITEM, operator_id=ACTOR
    )
    assert result.analysis_run_id == BASE and result.state == "ACCEPTED"
    graph.analyses.create_with_pinned_preset.assert_not_called()
    assert old.analysis_run_id == BASE and base.state == "ACCEPTED"
    assert task.analysis_run_id is None  # Do not duplicate a unique child owner.


def test_retry_creates_only_failed_base_successor_and_keeps_old_failure(monkeypatch):
    graph, task, old, base, _ = case(monkeypatch, base_state="FAILED")
    graph.analyses.create_with_pinned_preset.return_value = SimpleNamespace(
        state="QUEUED", analysis_run_id="analysisrun_" + "7" * 32
    )
    result = graph.advance_item_analysis(
        task_id=task.task_id, item_revision_id=ITEM, operator_id=ACTOR
    )
    command = graph.analyses.create_with_pinned_preset.call_args.args[0]
    assert command.predecessor_analysis_run_id == BASE
    assert command.idempotency_key == "material-base:" + task.task_id
    assert result.state == "ACCEPTED" and base.state == "FAILED" and old.analysis_run_id == BASE


@pytest.mark.parametrize("state", ["ACCEPTED", "FAILED"])
def test_solution_retry_reuses_base_and_never_rewrites_failed_report(monkeypatch, state):
    graph, task, old, _base, solution = case(monkeypatch, solution_state=state)
    graph.analyses.create_material_solution_with_pinned_preset.return_value = SimpleNamespace(
        state="QUEUED", analysis_run_id="analysisrun_" + "8" * 32
    )
    result = graph.advance_item_solution(
        base_analysis_run_id=BASE, task_id=task.task_id, operator_id=ACTOR
    )
    if state == "ACCEPTED":
        graph.analyses.create_material_solution_with_pinned_preset.assert_not_called()
        assert result.analysis_run_id == SOLUTION
    else:
        command = graph.analyses.create_material_solution_with_pinned_preset.call_args.args[0]
        assert command.base_analysis_run_id == BASE
        assert command.idempotency_key == "material-solution:" + task.task_id
    assert solution.state == state and old.solution_analysis_run_id == SOLUTION
    assert task.solution_analysis_run_id is None


def test_inherited_analysis_for_other_item_is_rejected_before_new_execution(monkeypatch):
    graph, task, _old, base, _solution = case(monkeypatch)
    base.canonical_request["source"]["item_revision_id"] = "itemrev_" + "9" * 32
    with pytest.raises(ValueError, match="ITEM_SOURCE_MISMATCH"):
        graph.advance_item_analysis(task_id=task.task_id, item_revision_id=ITEM, operator_id=ACTOR)
    graph.analyses.create_with_pinned_preset.assert_not_called()


@pytest.mark.parametrize("state,lease", [("RUNNING", None), ("FAILED", "held-lease")])
def test_failed_label_cannot_override_a_live_workflow_or_unreconciled_lease(state, lease):
    row = MaterialLearningTaskRecord(
        task_id="materialtask_" + "a" * 32, workflow_id="workflow_" + "b" * 32
    )
    workflow = SimpleNamespace(workflow_id=row.workflow_id, state=state)
    session = SimpleNamespace(scalars=lambda _query: (workflow,), scalar=lambda _query: lease)
    with pytest.raises(MaterialLearningSourceError, match="RECONCILIATION_REQUIRED"):
        _quiescent_failed_workflows(session, (row,))
