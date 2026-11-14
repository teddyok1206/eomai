"""Typed internal recovery boundary; no real actor/Artifact/DB/model operations."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_service import material_registered_base_recovery as owner


def target_case(monkeypatch):
    previous_run = NS(
        run_id="oldrun",
        state="FAILED",
        material_revision_id="revision",
        created_by="actor",
        attempt=2,
    )
    run = NS(
        run_id="newrun",
        state="PROCESSING",
        predecessor_run_id="oldrun",
        material_revision_id="revision",
        created_by="actor",
        attempt=3,
    )
    previous = NS(
        task_id="oldtask",
        run_id="oldrun",
        state="FAILED",
        task_kind="QUESTION",
        error_code="REGISTERED_ITEM_SOLUTION_ANCHOR_INVALID",
        unit_key="unit",
        ordinal=3,
        attempt=2,
    )
    task = NS(
        task_id="newtask",
        run_id="newrun",
        predecessor_task_id="oldtask",
        state="REGISTERED",
        task_kind="QUESTION",
        unit_key="unit",
        ordinal=3,
        attempt=3,
        analysis_run_id=None,
        solution_analysis_run_id=None,
        graph_snapshot_revision_id=None,
    )
    for field in (
        "input_artifact_id",
        "input_artifact_revision_id",
        "input_sha256",
        "output_artifact_id",
        "output_artifact_revision_id",
        "output_sha256",
        "item_revision_id",
    ):
        setattr(task, field, "pinned-" + field)
        setattr(previous, field, "pinned-" + field)
    revision = NS(material_id="material", material_revision_id="revision", created_by="actor")
    material = NS(lifecycle_state="ACTIVE", current_revision_id="revision", created_by="actor")
    rows = {
        "newtask": task,
        "oldtask": previous,
        "newrun": run,
        "oldrun": previous_run,
        "material": material,
    }
    session = Mock()
    session.get.side_effect = lambda _model, identity: rows[identity]
    session.scalar.side_effect = lambda *_: next(values)
    values = iter((revision, run, task, "official-sequence-one-event"))
    monkeypatch.setattr(owner, "authorize_material_learning", Mock())
    command = owner.CreateMaterialBaseRecoveryCommand("newtask", "oldbase", "actor")
    return session, command, task, run, previous, previous_run, revision, material


def test_linked_task_creation_uses_existing_revision_run_lock_scope(monkeypatch):
    session, command, task, run, previous, *_ = target_case(monkeypatch)
    before = deepcopy(vars(previous))
    assert owner.lock_material_base_recovery_target(session, command) == (task, run, previous)
    assert vars(previous) == before
    assert session.scalar.call_count == 4
    owner.authorize_material_learning.assert_called_once_with(session, "actor")


@pytest.mark.parametrize("state", ("PUBLISHING", "GRAPH_READY", "COMPLETED"))
def test_already_owned_analysis_replay_allows_new_public_and_graph_pins(monkeypatch, state):
    session, command, task, run, previous, *_ = target_case(monkeypatch)
    task.state = state
    task.analysis_run_id = "exact-new-analysis"
    task.solution_analysis_run_id = "exact-new-public-analysis"
    task.graph_snapshot_revision_id = "exact-new-graph"
    run.state = "COMPLETED_WITH_EXCEPTIONS"
    assert owner.lock_material_base_recovery_target(session, command) == (task, run, previous)


@pytest.mark.parametrize(
    "fault",
    (
        "event",
        "parent_state",
        "previous_error",
        "different_item",
        "different_output",
        "different_attempt",
        "ordinary_lineage",
        "public_before_creation",
        "graph_before_creation",
        "new_cancelled",
        "revoked_material",
        "wrong_actor",
    ),
)
def test_new_recovery_cannot_override_ineligible_or_unrelated_task_scope(monkeypatch, fault):
    session, command, task, run, previous, previous_run, revision, material = target_case(
        monkeypatch
    )
    if fault == "event":
        session.scalar.side_effect = iter((revision, run, task, None))
    elif fault == "parent_state":
        previous_run.state = "PROCESSING"
    elif fault == "previous_error":
        previous.error_code = "UNRELATED_ERROR"
    elif fault == "different_item":
        task.item_revision_id = "different-item"
    elif fault == "different_output":
        task.output_sha256 = "different-output"
    elif fault == "different_attempt":
        task.attempt += 1
    elif fault == "ordinary_lineage":
        run.predecessor_run_id = "unrelated-run"
    elif fault == "public_before_creation":
        task.solution_analysis_run_id = "prior-public"
    elif fault == "graph_before_creation":
        task.graph_snapshot_revision_id = "prior-graph"
    elif fault == "new_cancelled":
        run.state = "CANCELLED"
    elif fault == "revoked_material":
        material.lifecycle_state = "RETIRED"
    else:
        run.created_by = "another-actor"
    with pytest.raises(ValueError, match=r"^MATERIAL_REGISTERED_BASE_RECOVERY_SCOPE_INVALID$"):
        owner.lock_material_base_recovery_target(session, command)


@pytest.mark.parametrize("explicit_scope", (False, True))
def test_graph_advance_repairs_accepted_history_only_for_explicit_combined_successor(
    monkeypatch, explicit_scope
):
    from eom_catalog_service import material_graph_learning as graph_owner
    from eom_catalog_service.material_learning_models import MaterialLearningTaskRecord

    current = NS(task_id="new-task", run_id="new-run", item_revision_id="same-item")
    previous = NS(
        task_id="old-task",
        state="FAILED",
        error_code="REGISTERED_ITEM_SOLUTION_ANCHOR_INVALID",
        analysis_run_id="old-base",
    )
    accepted = NS(
        analysis_run_id="old-base",
        state="ACCEPTED",
        canonical_request={"source": {"item_revision_id": "same-item"}},
    )
    session = Mock()
    session.get.side_effect = lambda model, _key: (
        current if model is MaterialLearningTaskRecord else accepted
    )
    session.scalar.return_value = "explicit-event" if explicit_scope else None
    monkeypatch.setattr(
        graph_owner, "resolve_completed_material_task", Mock(return_value=NS(work="work"))
    )
    monkeypatch.setattr(
        graph_owner,
        "read_material_task_histories",
        Mock(
            return_value={
                current.task_id: NS(analysis_owner=lambda: previous),
            }
        ),
    )
    service = object.__new__(graph_owner.MaterialGraphLearningService)
    service.sessions = lambda: nullcontext(session)
    service.artifacts = Mock()
    service.sources = Mock()
    service.analyses = Mock()
    new = NS(analysis_run_id="new-base", state="QUEUED")
    service.analyses.create_material_base_recovery.return_value = new
    service._advance = Mock(return_value="new-progress")
    service._reconcile = Mock(return_value="accepted-history")
    result = service.advance_item_analysis(
        task_id=current.task_id, item_revision_id=current.item_revision_id, operator_id="actor"
    )
    if explicit_scope:
        assert result == "new-progress"
        service.analyses.create_material_base_recovery.assert_called_once_with(
            owner.CreateMaterialBaseRecoveryCommand("new-task", "old-base", "actor")
        )
        service._advance.assert_called_once_with(new, "actor")
        service._reconcile.assert_not_called()
    else:
        assert result == "accepted-history"
        service.analyses.create_material_base_recovery.assert_not_called()
        service._reconcile.assert_called_once_with("old-base", "actor")
    service.analyses.create_with_pinned_preset.assert_not_called()
