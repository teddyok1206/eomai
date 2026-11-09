"""Official shelving, CAS/replay and preserved usage in guarded disposable DB."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event, local

import pytest
from eom_catalog_contracts.content_lifecycle import (
    ChangeContentLifecycle,
    ContentLifecycleTarget,
    EditionLifecycleTarget,
    ListContentLifecycle,
    ReadContentLifecycle,
)
from eom_catalog_contracts.content_planning_queries import ReadContentEdition, ReadContentHistory
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_models import ContentPlanningCommandReceiptRecord
from eom_catalog_service.content_planning_service import ContentPlanningService
from eom_catalog_service.models import DeliverableRecord
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tests.integration.test_content_planning_application import change, create, key, slots
from tests.integration.test_content_planning_application import planning as planning
from tests.integration.test_content_planning_runtime_role import catalog_role as catalog_role
from tests.integration.test_content_print_application import command, filled, history
from tests.integration.test_content_usage_read import query_for

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def read(planning, saved, kind="CONTENT"):
    target = (
        ContentLifecycleTarget(target_kind="CONTENT", target_id=saved.deliverable_id)
        if kind == "CONTENT"
        else EditionLifecycleTarget(target_kind="EDITION", target_id=saved.edition_id)
    )
    return planning.service.lifecycle.execute(
        ReadContentLifecycle(action_kind="READ_LIFECYCLE", target=target), actor=planning.viewer
    )


def mutation(entry, state="ARCHIVED"):
    return ChangeContentLifecycle(
        action_kind="CHANGE_LIFECYCLE",
        target=entry.target,
        expected_version=entry.version,
        expected_state=entry.lifecycle_state,
        desired_state=state,
        reason="시험 보관/복원",
    )


@pytest.mark.parametrize("kind", ["CONTENT", "EDITION"])
def test_archive_restore_preserves_current_and_printed_usage_and_exact_history(
    creative_engine, planning, kind
):
    saved = filled(planning, creative_engine)
    printed = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    before = read(planning, saved, kind)
    request_key, archive = key(), mutation(before.entry)
    result = planning.service.lifecycle.execute(
        archive, actor=planning.editor, idempotency_key=request_key
    )
    replay = planning.service.lifecycle.execute(
        archive, actor=planning.editor, idempotency_key=request_key
    )
    assert replay.replayed and replay.entry == result.entry
    assert result.entry.lifecycle_state == "ARCHIVED"
    assert (
        planning.service.query(query_for(planning, saved), actor=planning.viewer).total_locations
        == 2
    )
    assert history(planning, saved).rows[0].record == printed.record
    old = planning.service.query(
        ReadContentEdition(
            query_kind="READ_EDITION",
            edition_id=saved.edition_id,
            revision_id=saved.deliverable_revision_id,
        ),
        actor=planning.viewer,
    )
    assert old.composition == saved
    events = planning.service.query(
        ReadContentHistory(
            query_kind="HISTORY", edition_id=saved.edition_id, before_sequence=None, limit=50
        ),
        actor=planning.viewer,
    )
    assert events.rows
    with pytest.raises(ContentPlanningError, match="CONTENT_EDITION_NOT_FOUND"):
        planning.service.execute(
            change(saved, {0: slots(1)}), actor=planning.editor, idempotency_key=key()
        )
    restored = planning.service.lifecycle.execute(
        mutation(result.entry, "ACTIVE"), actor=planning.editor, idempotency_key=key()
    )
    assert restored.entry.lifecycle_state == "ACTIVE"
    assert planning.service.read(saved.edition_id, actor=planning.viewer) == saved
    assert len(read(planning, saved, kind).events) == 2


def test_restore_retains_original_product_state_not_assumed_planned(creative_engine, planning):
    saved = create(planning)
    with Session(creative_engine) as session, session.begin():
        session.get(DeliverableRecord, saved.deliverable_id).lifecycle_state = "RELEASED"
    archived = planning.service.lifecycle.execute(
        mutation(read(planning, saved).entry), actor=planning.editor, idempotency_key=key()
    )
    planning.service.lifecycle.execute(
        mutation(archived.entry, "ACTIVE"), actor=planning.editor, idempotency_key=key()
    )
    with Session(creative_engine) as session:
        assert session.get(DeliverableRecord, saved.deliverable_id).lifecycle_state == "RELEASED"


def test_no_change_is_not_an_event_and_changed_body_cannot_reuse_key(planning):
    saved = create(planning)
    before = read(planning, saved)
    request_key = key()
    result = planning.service.lifecycle.execute(
        mutation(before.entry, "ACTIVE"), actor=planning.editor, idempotency_key=request_key
    )
    assert result.disposition == "NO_CHANGE" and result.entry == before.entry
    assert read(planning, saved).events == ()
    with pytest.raises(ContentPlanningError, match="CONTENT_IDEMPOTENCY_CONFLICT"):
        planning.service.lifecycle.execute(
            mutation(before.entry), actor=planning.editor, idempotency_key=request_key
        )


def test_two_operators_one_lifecycle_transition_and_same_key_replay(planning):
    saved = create(planning)
    command = mutation(read(planning, saved).entry)
    barrier = Barrier(2)

    def invoke(actor):
        barrier.wait(timeout=10)
        try:
            return planning.service.lifecycle.execute(
                command, actor=actor, idempotency_key=key()
            ).disposition
        except ContentPlanningError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, (planning.editor, planning.peer)))
    assert sorted(outcomes) == ["CHANGED", "CONTENT_LIFECYCLE_STALE"]
    assert len(read(planning, saved).events) == 1


def test_viewer_cannot_archive_and_parent_must_be_restored_before_child(planning):
    saved = create(planning)
    target = mutation(read(planning, saved).entry)
    with pytest.raises(ContentPlanningError, match="PERMISSION_DENIED"):
        planning.service.lifecycle.execute(target, actor=planning.viewer, idempotency_key=key())
    child = read(planning, saved, "EDITION").entry
    planning.service.lifecycle.execute(target, actor=planning.editor, idempotency_key=key())
    with pytest.raises(ContentPlanningError, match="CONTENT_PARENT_ARCHIVED"):
        planning.service.lifecycle.execute(
            mutation(child), actor=planning.editor, idempotency_key=key()
        )


def test_bounded_archive_list_not_n_plus_one(creative_engine, planning):
    saved = create(planning)
    archived = planning.service.lifecycle.execute(
        mutation(read(planning, saved).entry), actor=planning.editor, idempotency_key=key()
    )
    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper().startswith("SELECT"):
            statements.append(sql)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        page = planning.service.lifecycle.execute(
            ListContentLifecycle(
                action_kind="LIST_LIFECYCLE",
                target_kind="CONTENT",
                deliverable_id=None,
                lifecycle_state="ARCHIVED",
                after_id=None,
                limit=100,
            ),
            actor=planning.viewer,
        )
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert archived.entry in page.rows
    assert len(statements) <= 4


def test_edition_archive_cas_detects_an_intervening_placement_save(planning):
    saved = create(planning)
    before = read(planning, saved, "EDITION")
    newer = planning.service.execute(
        change(saved, {0: slots(1)}), actor=planning.peer, idempotency_key=key()
    )
    with pytest.raises(ContentPlanningError, match="CONTENT_LIFECYCLE_STALE"):
        planning.service.lifecycle.execute(
            mutation(before.entry), actor=planning.editor, idempotency_key=key()
        )
    assert planning.service.read(saved.edition_id, actor=planning.viewer) == newer.composition


def test_limited_runtime_role_can_archive_read_history_and_restore(catalog_role, planning):
    limited = replace(planning, service=ContentPlanningService(catalog_role))
    saved = create(limited)
    archived = limited.service.lifecycle.execute(
        mutation(read(limited, saved).entry), actor=limited.editor, idempotency_key=key()
    )
    assert len(read(limited, saved).events) == 1
    restored = limited.service.lifecycle.execute(
        mutation(archived.entry, "ACTIVE"), actor=limited.editor, idempotency_key=key()
    )
    assert restored.entry.lifecycle_state == "ACTIVE"


def test_archive_and_save_overlap_uses_product_then_edition_lock_order(creative_engine, planning):
    saved = create(planning)
    archive = mutation(read(planning, saved, "EDITION").entry)
    edit = change(saved, {0: slots(1)})
    product_locked, save_entered = Event(), Event()
    context = local()
    save_locks = []

    def before(_connection, _cursor, sql, _parameters, _context, _many):
        statement = sql.upper()
        if getattr(context, "operation", None) == "save" and "FOR " in statement:
            save_locks.append(statement)
            if "FOR SHARE" in statement and "DELIVERABLES" in statement:
                save_entered.set()

    def after(_connection, _cursor, sql, _parameters, _context, _many):
        if (
            getattr(context, "operation", None) == "archive"
            and not product_locked.is_set()
            and "FOR UPDATE" in sql.upper()
            and "DELIVERABLES" in sql.upper()
        ):
            # The archive really holds the DB Product lock before the edit tries
            # to enter. No timing sleep is used to manufacture concurrency.
            product_locked.set()
            assert save_entered.wait(timeout=10), "edit never entered its Product lock"

    def archive_now():
        context.operation = "archive"
        return planning.service.lifecycle.execute(
            archive, actor=planning.editor, idempotency_key=key()
        )

    def save_now():
        context.operation = "save"
        assert product_locked.wait(timeout=10), "archive never acquired its Product lock"
        try:
            planning.service.execute(edit, actor=planning.peer, idempotency_key=key())
            return "SAVED"
        except ContentPlanningError as exc:
            return exc.code

    event.listen(creative_engine, "before_cursor_execute", before)
    event.listen(creative_engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            archived, edited = pool.submit(archive_now), pool.submit(save_now)
            assert archived.result(timeout=20).disposition == "CHANGED"
            assert edited.result(timeout=20) == "CONTENT_EDITION_NOT_FOUND"
    finally:
        event.remove(creative_engine, "before_cursor_execute", before)
        event.remove(creative_engine, "after_cursor_execute", after)
    assert "FOR SHARE" in save_locks[0] and "DELIVERABLES" in save_locks[0]
    assert (
        planning.service.read(
            saved.edition_id, actor=planning.viewer, revision_id=saved.deliverable_revision_id
        )
        == saved
    )
    assert len(read(planning, saved, "EDITION").events) == 1


def test_same_key_concurrent_archive_has_one_event_and_one_receipt(creative_engine, planning):
    saved = create(planning)
    archive, request_key = mutation(read(planning, saved).entry), key()
    barrier = Barrier(2)

    def invoke(_index):
        barrier.wait(timeout=10)
        return planning.service.lifecycle.execute(
            archive, actor=planning.editor, idempotency_key=request_key
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, (0, 1)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].entry == results[1].entry
    assert len(read(planning, saved).events) == 1
    with Session(creative_engine) as session:
        receipts = session.scalar(
            select(func.count())
            .select_from(ContentPlanningCommandReceiptRecord)
            .where(
                ContentPlanningCommandReceiptRecord.actor_id == planning.editor.actor_id,
                ContentPlanningCommandReceiptRecord.command_kind == "CHANGE_LIFECYCLE",
                ContentPlanningCommandReceiptRecord.idempotency_key == request_key,
            )
        )
    assert receipts == 1
