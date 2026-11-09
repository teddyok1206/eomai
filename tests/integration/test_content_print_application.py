"""Print facts/correction concurrency, exact scopes, rollback and source permission."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from eom_catalog_contracts.content_print_commands import RecordContentPrint, VoidContentPrint
from eom_catalog_contracts.content_print_views import ReadContentPrints
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_print_models import ContentPrintEventRecord, ContentPrintRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.integration.content_planning_sources import add_source
from tests.integration.test_content_planning_application import change, create, ident, key, slots
from tests.integration.test_content_planning_application import planning as planning
from tests.unit.content_planning_fixtures import slot

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def filled(planning, engine, count=2):
    original = create(planning)
    target = add_source(engine)
    placements = tuple(
        CuratedSlot.model_validate({**slot(i, target=target), "placement_id": ident("placement")})
        for i in range(1, count + 1)
    )
    saved = planning.service.execute(
        change(original, {0: placements}), actor=planning.editor, idempotency_key=key()
    ).composition
    return saved


def command(saved, *, intent="INITIAL", predecessor=None):
    return RecordContentPrint(
        command_kind="RECORD_PRINT",
        edition_id=saved.edition_id,
        revision_id=saved.deliverable_revision_id,
        composition_sha256=saved.composition_sha256,
        section_ids=(saved.sections[0].section_id,),
        intent=intent,
        predecessor_print_record_id=predecessor,
        printed_on=None,
        note="사용자 인쇄 확인",
    )


def history(planning, saved):
    return planning.service.query(
        ReadContentPrints(
            query_kind="PRINTS", edition_id=saved.edition_id, before_id=None, limit=100
        ),
        actor=planning.viewer,
    )


def test_partial_print_matches_after_unrelated_form_edit_then_marks_actual_change(
    creative_engine, planning
):
    saved = filled(planning, creative_engine)
    printed = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    changed = planning.service.execute(
        change(saved, {1: slots(3)}), actor=planning.peer, idempotency_key=key()
    ).composition
    assert history(planning, changed).rows[0].matches_current_scope
    changed = planning.service.execute(
        change(changed, {0: slots(2)}), actor=planning.peer, idempotency_key=key()
    ).composition
    record = history(planning, changed).rows[0]
    assert not record.matches_current_scope and record.state == "ACTIVE"
    assert record.record == printed.record and record.record.output is None


def test_same_request_and_two_operators_make_one_initial_fact(creative_engine, planning):
    saved = filled(planning, creative_engine)
    request = command(saved)
    barrier = Barrier(2)

    def submit(actor):
        barrier.wait(timeout=10)
        return planning.service.prints.execute(request, actor=actor, idempotency_key=key())

    with ThreadPoolExecutor(max_workers=2) as executor:
        replies = tuple(executor.map(submit, (planning.editor, planning.peer)))
    assert len({row.record.print_record_id for row in replies}) == 1
    assert {row.disposition for row in replies} == {"RECORDED", "ALREADY_RECORDED"}
    reprint = command(saved, intent="REPRINT", predecessor=replies[0].record.print_record_id)
    request_key = key()
    a = planning.service.prints.execute(reprint, actor=planning.editor, idempotency_key=request_key)
    b = planning.service.prints.execute(reprint, actor=planning.editor, idempotency_key=request_key)
    assert b.replayed and a.record == b.record and a.record != replies[0].record
    assert len(history(planning, saved).rows) == 2


def test_void_and_correction_do_not_rewrite_facts(creative_engine, planning):
    saved = filled(planning, creative_engine)
    first = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    corrected = planning.service.prints.execute(
        command(saved, intent="CORRECTION", predecessor=first.record.print_record_id),
        actor=planning.peer,
        idempotency_key=key(),
    )
    rows = {entry.record.print_record_id: entry for entry in history(planning, saved).rows}
    assert rows[first.record.print_record_id].state == "CORRECTED"
    assert (
        rows[first.record.print_record_id].replacement_print_record_id
        == corrected.record.print_record_id
    )
    assert rows[first.record.print_record_id].record == first.record
    void = VoidContentPrint(
        command_kind="VOID_PRINT",
        edition_id=saved.edition_id,
        print_record_id=corrected.record.print_record_id,
        record_sha256=corrected.record.record_sha256,
        reason="인쇄일 오입력",
    )
    request_key = key()
    planning.service.prints.execute(void, actor=planning.editor, idempotency_key=request_key)
    replay = planning.service.prints.execute(
        void, actor=planning.editor, idempotency_key=request_key
    )
    assert replay.replayed and replay.record == corrected.record
    with pytest.raises(ContentPlanningError, match="CONTENT_PRINT_ALREADY_CLOSED"):
        planning.service.prints.execute(void, actor=planning.peer, idempotency_key=key())
    with pytest.raises(ContentPlanningError, match="CONTENT_PRINT_EXPLICIT_REPRINT_REQUIRED"):
        planning.service.prints.execute(command(saved), actor=planning.peer, idempotency_key=key())


def test_blank_positions_cannot_be_printed_and_viewer_cannot_create_fact(creative_engine, planning):
    original = create(planning)
    saved = planning.service.execute(
        change(original, {0: slots(1)}), actor=planning.editor, idempotency_key=key()
    ).composition
    with pytest.raises(ContentPlanningError, match="CONTENT_PRINT_UNFILLED_PLACEMENTS"):
        planning.service.prints.execute(
            command(saved), actor=planning.editor, idempotency_key=key()
        )
    with pytest.raises(ContentPlanningError, match="CONTENT_PLANNING_PERMISSION_DENIED"):
        planning.service.prints.execute(
            command(saved), actor=planning.viewer, idempotency_key=key()
        )
    assert history(planning, saved).rows == ()


def test_correction_interrupt_rolls_back_new_fact_and_terminal_event(
    creative_engine, planning, monkeypatch
):
    import eom_catalog_service.content_print_records as owner

    saved = filled(planning, creative_engine)
    first = planning.service.prints.execute(
        command(saved), actor=planning.editor, idempotency_key=key()
    )
    request = command(saved, intent="CORRECTION", predecessor=first.record.print_record_id)
    request_key, real_validation = key(), owner.validate_contract

    def fail_after_write(name, value):
        if name == "content-print-result-v1":
            raise RuntimeError("synthetic stop before commit")
        return real_validation(name, value)

    with monkeypatch.context() as patch:
        patch.setattr(owner, "validate_contract", fail_after_write)
        with pytest.raises(RuntimeError, match="synthetic stop"):
            planning.service.prints.execute(
                request, actor=planning.editor, idempotency_key=request_key
            )
    with Session(creative_engine) as session:
        assert session.get(ContentPrintEventRecord, (first.record.print_record_id, 1)) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentPrintRecord)
                .where(ContentPrintRecord.edition_id == saved.edition_id)
            )
            == 1
        )
    result = planning.service.prints.execute(
        request, actor=planning.editor, idempotency_key=request_key
    )
    assert result.disposition == "RECORDED" and not result.replayed
