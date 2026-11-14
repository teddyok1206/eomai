"""Bounded native scheduling/publication only; no model, DB, NAS or live role."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_native_intake import MaterialNativeLearningIntakeManifest
from eom_catalog_service import material_learning_processing as owner
from eom_catalog_service import material_learning_store as store
from eom_catalog_service.material_learning_coordinator import MaterialProcessingContext
from eom_catalog_service.material_learning_models import MaterialLearningTaskRecord
from eom_workflow.material_learning_state import (
    TASK_TRANSITIONS,
    TERMINAL_MATERIAL_TASK_STATES,
)


def task(number, state="PUBLISHING", kind="QUESTION", *, run="run-synthetic"):
    return MaterialLearningTaskRecord(
        task_id=f"materialtask_{number:032x}",
        run_id=run,
        ordinal=number,
        attempt=1,
        task_kind=kind,
        state=state,
        item_revision_id=f"itemrev_{number:032x}",
        analysis_run_id=f"analysisrun_{1000 + number:032x}",
        solution_analysis_run_id=f"analysisrun_{2000 + number:032x}",
    )


def context(*, native=True):
    # This unit needs only the discriminator, not an input/authority fixture.
    intake = MaterialNativeLearningIntakeManifest.model_construct() if native else None
    return MaterialProcessingContext("run-synthetic", "operator-synthetic", intake, None)


class WindowSession:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    def scalars(self, query):
        self.queries.append(query)
        return iter(self.rows[: query._limit_clause.value])


def select_task(monkeypatch, rows, *, native=True):
    service = object.__new__(owner.MaterialLearningProcessingService)
    monkeypatch.setattr(owner, "next_material_task", lambda *_: rows[0] if rows else None)
    session = WindowSession(rows)
    return service._processing_task(session, context(native=native)), session


@pytest.mark.parametrize("state", ("PENDING", "READY", "RUNNING", "ANALYZING", "GRAPH_READY"))
def test_native_accepted_publication_does_not_block_next_checkpoint(monkeypatch, state):
    rows = [task(1), task(2, state)]
    selected, session = select_task(monkeypatch, rows)
    assert selected is rows[1]
    assert len(session.queries) == 1


def test_terminal_questions_consume_original_window_not_more_than_25(monkeypatch):
    rows = [task(number) for number in range(1, 27)]
    for row, state in zip(rows[1:5], sorted(TERMINAL_MATERIAL_TASK_STATES), strict=True):
        row.state = state
    rows[-1].state = "PENDING"
    selected, session = select_task(monkeypatch, rows)
    assert selected is rows[0]  # Flush before observing the 26th question.
    assert session.queries[0]._limit_clause.value == 25
    sql = str(session.queries[0])
    assert "material_learning_tasks.run_id =" in sql
    assert "material_learning_tasks.ordinal >=" in sql
    assert "ORDER BY material_learning_tasks.ordinal" in sql
    assert "state NOT IN" not in sql and "task_kind =" not in sql


@pytest.mark.parametrize("state", ("PENDING", "COMPLETED", "FAILED"))
def test_explanation_is_a_barrier_even_when_terminal(monkeypatch, state):
    rows = [task(1), task(2, state, "EXPLANATION"), task(3, "PENDING")]
    selected, _ = select_task(monkeypatch, rows)
    assert selected is rows[0]


def test_native_last_short_window_flushes_and_never_revives_old_tasks(monkeypatch):
    rows = [task(5), task(6, "FAILED"), task(7, "COMPLETED")]
    selected, _ = select_task(monkeypatch, rows)
    assert selected is rows[0]
    assert [row.state for row in rows] == ["PUBLISHING", "FAILED", "COMPLETED"]


@pytest.mark.parametrize(
    "native,kind,state",
    (
        (False, "QUESTION", "PUBLISHING"),
        (True, "EXPLANATION", "PUBLISHING"),
        (True, "QUESTION", "GRAPH_READY"),
    ),
)
def test_other_inputs_and_ready_graphs_keep_original_next_task(monkeypatch, native, kind, state):
    rows = [task(1, state, kind), task(2, "PENDING")]
    selected, session = select_task(monkeypatch, rows, native=native)
    assert selected is rows[0] and not session.queries


@pytest.mark.parametrize("limit", (0, -1, True))
def test_window_rejects_invalid_limit_before_query(limit):
    session = WindowSession([])
    with pytest.raises(store.MaterialLearningStorageError, match="WINDOW_INVALID"):
        store.material_question_processing_window(session, task(1), limit=limit)
    assert not session.queries


def test_window_requires_the_original_first_row():
    with pytest.raises(store.MaterialLearningStorageError, match="WINDOW_CHANGED"):
        store.material_question_processing_window(WindowSession([task(2)]), task(1), limit=25)


def analyses_for(rows):
    return [
        NS(
            analysis_run_id=identity,
            state="ACCEPTED",
            item_revision_id=row.item_revision_id,
            predecessor_analysis_run_id=row.analysis_run_id if public else None,
            accepted_result_sha256="sha256:" + ("2" if public else "1") * 64,
        )
        for row in rows
        for identity, public in ((row.analysis_run_id, False), (row.solution_analysis_run_id, True))
    ]


def checkpoint_case(monkeypatch, count=1):
    rows = tuple(task(i) for i in range(1, count + 1))
    analyses = analyses_for(rows)
    session = Mock()
    session.scalars.return_value = analyses
    histories = {
        row.task_id: NS(analysis_owner=lambda *, solution=False, original=row: original)
        for row in rows
    }
    monkeypatch.setattr(owner, "read_material_task_histories", lambda *_: histories)
    service = object.__new__(owner.MaterialLearningProcessingService)
    return service, session, rows, analyses


@pytest.mark.parametrize("count", (1, 25))
def test_exact_base_and_public_metadata_are_read_in_one_indexed_batch(monkeypatch, count):
    service, session, rows, _ = checkpoint_case(monkeypatch, count)
    result = service._question_graph_checkpoints(session, rows)
    assert len(result) == count
    assert [entry.task_id for entry in result] == [row.task_id for row in rows]
    assert [entry.solution_analysis_run_id for entry in result] == [
        row.solution_analysis_run_id for row in rows
    ]
    session.scalars.assert_called_once()
    assert "knowledge_analysis_runs.analysis_run_id IN" in str(session.scalars.call_args.args[0])


@pytest.mark.parametrize(
    "fault",
    (
        "public_state",
        "base_state",
        "public_item",
        "base_item",
        "public_predecessor",
        "public_hash",
        "base_hash",
        "missing_public",
    ),
)
def test_checkpoint_rejects_unaccepted_or_mismatched_public_solution(monkeypatch, fault):
    service, session, rows, analyses = checkpoint_case(monkeypatch)
    base, public = analyses
    if fault == "public_state":
        public.state = "RUNNING"
    elif fault == "base_state":
        base.state = "REJECTED"
    elif fault == "public_item":
        public.item_revision_id = "other-item"
    elif fault == "base_item":
        base.item_revision_id = "other-item"
    elif fault == "public_predecessor":
        public.predecessor_analysis_run_id = "other-base"
    elif fault == "public_hash":
        public.accepted_result_sha256 = None
    elif fault == "base_hash":
        base.accepted_result_sha256 = None
    else:
        session.scalars.return_value = [base]
    with pytest.raises(ValueError, match="BATCH_ANALYSIS_NOT_ACCEPTED"):
        service._question_graph_checkpoints(session, rows)


def test_inherited_original_analysis_pins_are_not_written_into_successor(monkeypatch):
    service, session, rows, analyses = checkpoint_case(monkeypatch)
    original = task(99)
    original.item_revision_id = rows[0].item_revision_id
    rows[0].analysis_run_id = rows[0].solution_analysis_run_id = None
    analyses[0].analysis_run_id = original.analysis_run_id
    analyses[1].analysis_run_id = original.solution_analysis_run_id
    analyses[1].predecessor_analysis_run_id = original.analysis_run_id
    monkeypatch.setattr(
        owner,
        "read_material_task_histories",
        lambda *_: {rows[0].task_id: NS(analysis_owner=lambda *, solution=False: original)},
    )
    result = service._question_graph_checkpoints(session, rows)
    assert result[0].analysis_run_id == original.analysis_run_id
    assert rows[0].analysis_run_id is None and rows[0].solution_analysis_run_id is None


def test_one_publication_for_25_reports_and_replay_after_link_interruption(monkeypatch):
    service, session, rows, _ = checkpoint_case(monkeypatch, 25)
    checkpoints = service._question_graph_checkpoints(session, rows)
    service.sessions = lambda: nullcontext(WindowSession(rows))
    service.coordinator = Mock()
    service.coordinator.maintain_claim.side_effect = lambda _: nullcontext()
    service.graph = Mock()
    service.graph.publish_items.return_value = "graph-revision-synthetic"
    service._pin_question_graph_batch = Mock(
        side_effect=[RuntimeError("synthetic interruption"), None]
    )
    service._question_graph_checkpoints = Mock(return_value=checkpoints)
    claim = NS(run_id="run-synthetic")
    with pytest.raises(RuntimeError, match="interruption"):
        service._publish_native_questions(claim, context(), rows[0])
    observed = service._publish_native_questions(claim, context(), rows[0])
    assert observed.phase == "GRAPH_READY"
    assert service.graph.publish_items.call_count == 2
    assert (
        service.graph.publish_items.call_args_list[0]
        == service.graph.publish_items.call_args_list[1]
    )
    assert len(service.graph.publish_items.call_args.kwargs["targets"]) == 25
    service.graph.advance_item_analysis.assert_not_called()
    service.graph.advance_item_solution.assert_not_called()
    assert all(row.state == "PUBLISHING" for row in rows)  # No ad-hoc state mutation.


def test_terminal_set_is_derived_from_the_existing_state_machine():
    assert {
        state.value for state, targets in TASK_TRANSITIONS.items() if not targets
    } == TERMINAL_MATERIAL_TASK_STATES
