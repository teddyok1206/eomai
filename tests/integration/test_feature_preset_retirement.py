"""Preset cleanup and current-feature reads in a marker-guarded disposable DB."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_api.services.control_plane_adapter import ControlPlaneAdapter
from eom_catalog_service.creative_cohort_execution import CreativeCohortExecutionService
from eom_identifiers import content_sha256
from eom_orchestrator import preset_retirement as retirement
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError, record_execution_preset_revision
from eom_workflow_runner.models import WorkflowInstanceRecord
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_preset_model_validation_persistence import (
    _enqueue,
)
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_preset_model_validation_persistence import (
    seed as seed,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def scope(guarded_engine, seed, monkeypatch):
    monkeypatch.setattr(retirement, "OBSOLETE_PRESET_KEYS", frozenset({seed["key"]}))
    with Session(guarded_engine) as session, session.begin():
        base = session.get(ExecutionPresetRevisionRecord, seed["base"])
        draft = session.get(ExecutionPresetRevisionRecord, seed["draft"])
        plan = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.preset_revision_id == seed["base"]
            )
        )
        workflow = session.get(WorkflowInstanceRecord, plan.workflow_id)
        workflow.state = "FAILED"  # Disposable historical fixture, never runtime repair.
        return {
            "current_pins": (
                retirement.PresetRevisionToRemove(
                    seed["key"], base.preset_revision_id, base.content_sha256
                ),
            ),
            "unused_revisions": (
                retirement.PresetRevisionToRemove(
                    seed["key"], draft.preset_revision_id, draft.content_sha256
                ),
            ),
            "operator_id": seed["actor"],
            "changed_at": datetime.now(UTC),
        }


def test_retire_preserves_history_and_deletes_only_unused_draft(guarded_engine, seed, scope):
    with Session(guarded_engine) as session, session.begin():
        before = dict(session.get(ExecutionPresetRevisionRecord, seed["base"]).canonical_document)
        result = retirement.retire_obsolete_presets(session, **scope)
        assert result.deleted_revision_ids == (seed["draft"],)
    with Session(guarded_engine) as session, session.begin():
        assert session.get(ExecutionPresetRevisionRecord, seed["draft"]) is None
        assert session.get(ExecutionPresetRevisionRecord, seed["base"]).canonical_document == before
        assert session.get(ExecutionPresetRecord, seed["preset"]).state == "RETIRED"
        replay = retirement.retire_obsolete_presets(session, **scope)
        assert replay.already_deleted_ids == (seed["draft"],)
        rows = list(
            session.scalars(
                select(ExecutionPresetRevisionRecord).where(
                    ExecutionPresetRevisionRecord.preset_id == seed["preset"],
                    ExecutionPresetRevisionRecord.state == "DEPRECATED",
                )
            )
        )
        assert len(rows) == 1


def test_retirement_keeps_frozen_cohort_history_readable_but_not_new_admission(
    guarded_engine, seed, scope
):
    with Session(guarded_engine) as session, session.begin():
        row = session.get(ExecutionPresetRevisionRecord, seed["base"])
        before = deepcopy(row.canonical_document)
        pin = SimpleNamespace(
            preset_id=row.preset_id,
            preset_revision_id=row.preset_revision_id,
            sha256=row.content_sha256,
        )
        history = SimpleNamespace(
            cohort_id="previous",
            extraction_preset=pin,
            analysis_preset=pin,
            extraction_preset_key=seed["key"],
            analysis_preset_key=seed["key"],
            capacity_policy_revision_id=before["capacity_policy_revision_id"],
        )
        retirement.retire_obsolete_presets(session, **scope)
    # Fresh sessions model startup after retirement, rather than an ORM identity-map hit.
    for _ in range(2):
        with Session(guarded_engine) as session:
            restarted = object.__new__(CreativeCohortExecutionService)
            restarted.scope = SimpleNamespace(cohort_id="current")
            restarted._require_scope_pins(session, history)
            assert (
                session.get(ExecutionPresetRevisionRecord, seed["base"]).canonical_document
                == before
            )
            restarted.scope = history
            with pytest.raises(ValueError, match="CREATIVE_COHORT_PRESET_PIN_MISMATCH"):
                restarted._require_scope_pins(session, history)


@pytest.mark.parametrize("error", ["hash", "reference", "busy", "current", "scope"])
def test_cleanup_fails_closed_and_keeps_settings(guarded_engine, seed, scope, error):
    if error == "hash":
        old = scope["current_pins"][0]
        scope["current_pins"] = (
            retirement.PresetRevisionToRemove(
                old.preset_key, old.revision_id, "sha256:" + "0" * 64
            ),
        )
    elif error == "busy":
        with Session(guarded_engine) as session, session.begin():
            plan = session.scalar(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.preset_revision_id == seed["base"]
                )
            )
            session.get(WorkflowInstanceRecord, plan.workflow_id).state = "RUNNING"
    elif error == "current":
        scope["unused_revisions"] = scope["current_pins"]
    elif error == "scope":
        scope["current_pins"] *= 2
    with pytest.raises(ControlPlaneError), Session(guarded_engine) as session, session.begin():
        if error == "reference":
            _enqueue(session, seed)
        retirement.retire_obsolete_presets(session, **scope)
    with Session(guarded_engine) as session:
        assert session.get(ExecutionPresetRecord, seed["preset"]).state == "ACTIVE"
        assert session.get(ExecutionPresetRevisionRecord, seed["draft"]) is not None


def test_concurrent_cleanup_is_replay_not_duplicate_deprecation(guarded_engine, seed, scope):
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=10)
        with Session(guarded_engine) as session, session.begin():
            return retirement.retire_obsolete_presets(session, **scope)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(len(v.deleted_revision_ids) for v in results) == 1
    assert sum(len(v.already_deleted_ids) for v in results) == 1


def test_unreferenced_old_release_deletion_and_rollback_restore_triggers(
    guarded_engine, seed, scope
):
    with Session(guarded_engine) as session, session.begin():
        value = deepcopy(
            session.get(ExecutionPresetRevisionRecord, seed["base"]).canonical_document
        )
        value.update(preset_revision_id="execpresetrev_" + uuid4().hex, revision_number=3)
        value["content_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "content_sha256"}
        )
        row = record_execution_preset_revision(
            session, preset_key=seed["key"], document=value, created_by=seed["actor"]
        )
        pin = retirement.PresetRevisionToRemove(
            seed["key"], row.preset_revision_id, row.content_sha256
        )
    scope["unused_revisions"] += (pin,)
    with (
        pytest.raises(RuntimeError, match="interrupt"),
        Session(guarded_engine) as session,
        session.begin(),
    ):
        result = retirement.retire_obsolete_presets(session, **scope)
        assert pin.revision_id in result.deleted_revision_ids
        raise RuntimeError("interrupt before commit")
    with Session(guarded_engine) as session, session.begin():
        assert session.get(ExecutionPresetRevisionRecord, pin.revision_id) is not None
        assert session.get(ExecutionPresetRecord, seed["preset"]).state == "ACTIVE"
        enabled = (
            session.execute(
                text(
                    "SELECT tgenabled FROM pg_trigger WHERE tgname IN "
                    "('execution_preset_revisions_immutable',"
                    "'execution_preset_role_policies_immutable')"
                )
            )
            .scalars()
            .all()
        )
        assert enabled == ["O", "O"]
        result = retirement.retire_obsolete_presets(session, **scope)
        assert pin.revision_id in result.deleted_revision_ids


def test_current_projection_retains_new_draft_with_bounded_queries(guarded_engine, seed):
    adapter = object.__new__(ControlPlaneAdapter)
    adapter.sessions = sessionmaker(guarded_engine)
    queries = []

    def count(_connection, _cursor, statement, *_args):
        queries.append(statement)

    event.listen(guarded_engine, "before_cursor_execute", count)
    try:
        rows = adapter.list_presets(preset_keys=frozenset({seed["key"]}), current_only=True)
    finally:
        event.remove(guarded_engine, "before_cursor_execute", count)
    assert len(rows) == 1
    assert {v.preset_revision_id for v in rows[0].revisions} == {seed["base"], seed["draft"]}
    assert len(queries) == 3
    assert "JOIN execution_preset_revisions" in queries[1]
