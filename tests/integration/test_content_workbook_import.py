"""Real workbook Artifact, import transactions and source admission on disposable PostgreSQL.

Synthetic source pointers do not claim historical document bytes or live rendering.
The proposal preserves workbook bytes in the test Artifact store, never in DB rows.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from xml.etree import ElementTree as ET

import pytest
from eom_catalog_contracts.content_planning_queries import ReadContentSection
from eom_catalog_contracts.content_usage import ReadContentUsage
from eom_catalog_contracts.content_workbook_import import PrepareContentWorkbookRequest
from eom_catalog_contracts.curated_document_slots import ExternalSlotTarget
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentPlanningCommandReceiptRecord,
)
from eom_catalog_service.content_print_models import ContentPrintRecord
from eom_catalog_service.content_workbook_import_service import ContentWorkbookImportService
from eom_catalog_service.content_workbook_reader import read_content_workbook
from eom_catalog_service.content_workbook_resolution import resolve_workbook_rows
from eom_catalog_service.external_item_models import (
    ExternalItemEditionDocumentRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import (
    ContentIntakeBatchRecord,
    ContentIntakeSourceFileRecord,
    DeliverableRecord,
)
from eom_catalog_service.settings import CatalogSettings
from eom_identity_service.models import OperatorRoleAssignmentRecord
from eom_operator_identity import ActorContext
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tests.integration.content_planning_sources import add_source
from tests.integration.test_content_planning_application import change, ident, key, slots
from tests.integration.test_content_planning_application import planning as planning
from tests.unit.test_content_workbook_reader import _book, _cell, _change

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def unused_numbers(engine, count=2):
    with Session(engine) as session:
        used = set(session.scalars(select(ExternalItemSourceRecord.external_number)))
    result = tuple(str(number) for number in range(99999, 10000, -1) if str(number) not in used)
    assert len(result) >= count
    return result[:count]


def filled_workbook(tmp_path, numbers, *, title="합성 교재", printed=True, groups=False):
    directory = tmp_path / ident("workbook")
    directory.mkdir()

    def metadata(root: ET.Element) -> None:
        _cell(root, "B2", title)
        if not printed:
            _cell(root, "B6", "확인 필요")
            _cell(root, "B7", None)

    def rows(root: ET.Element) -> None:
        for row_number in range(2, max(5, len(numbers) + 2)):
            for column in "ABCDEF":
                _cell(root, f"{column}{row_number}", None)
        for row_number, number in enumerate(numbers, 2):
            _cell(root, f"D{row_number}", number)
        _cell(root, "C2", "문항 1")
        _cell(root, "E2", "2.125", numeric=True)
        _cell(root, "F2", "사용자가 기입한 메모")
        if groups:
            for row_number in range(2, len(numbers) + 2):
                _cell(root, f"A{row_number}", "상권")
                _cell(root, f"B{row_number}", "1회" if row_number < 4 else "2회")

    def mutate(parts: dict[str, bytes]) -> None:
        _change(parts, 1, metadata)
        _change(parts, 2, rows)

    return _book(directory, mutate)


def request(
    path: Path,
    actor: ActorContext,
    *,
    request_key: str | None = None,
    filename: str = "입력.xlsx",
) -> PrepareContentWorkbookRequest:
    assert actor.session_id is not None and actor.authentication_time is not None
    return PrepareContentWorkbookRequest(
        actor_id=actor.actor_id,
        session_id=actor.session_id,
        request_id=ident("request"),
        authentication_time=actor.authentication_time,
        original_filename=filename,
        content_length=path.stat().st_size,
        sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        idempotency_key=request_key or key(),
    )


@pytest.fixture
def importer(creative_engine, tmp_path):
    staging, nas = tmp_path / "staging", tmp_path / "artifact-store"
    staging.mkdir()
    nas.mkdir()
    return ContentWorkbookImportService(
        creative_engine, CatalogSettings(staging_root=staging, nas_artifact_root=nas)
    )


@pytest.fixture
def prepared(creative_engine, planning, importer, tmp_path):
    numbers = unused_numbers(creative_engine)
    targets = tuple(add_source(creative_engine, number) for number in numbers)
    path = filled_workbook(tmp_path, (numbers[0], numbers[1], numbers[0]), groups=True)
    command = request(path, planning.editor)
    preview = importer.prepare(path, command, planning.editor)
    assert preview.can_commit
    return preview, path, command, targets


def product_count(engine, sha):
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(DeliverableRecord)
            .where(DeliverableRecord.deliverable_key == "excel-import-v1:" + sha[7:])
        )


def test_one_source_shared_by_two_editions_is_not_a_number_collision(
    creative_engine, planning, importer, tmp_path
):
    number = unused_numbers(creative_engine, 1)[0]
    target = add_source(creative_engine, number)
    with Session(creative_engine) as session, session.begin():
        final = session.scalar(
            select(ExternalItemEditionDocumentRecord).where(
                ExternalItemEditionDocumentRecord.source_revision_id
                == target["source_revision_id"],
                ExternalItemEditionDocumentRecord.edition == 3,
            )
        )
        assert final is not None
        session.add(
            ExternalItemEditionDocumentRecord(
                edition_document_id=ident("extitemdoc"),
                source_revision_id=final.source_revision_id,
                edition=2,
                match_status=final.match_status,
                source_file_id=final.source_file_id,
                document_sha256=final.document_sha256,
            )
        )
    path = filled_workbook(tmp_path, (number,))
    preview = importer.prepare(path, request(path, planning.editor), planning.editor)
    assert preview.can_commit and preview.rows[0].resolution.target is not None
    assert preview.rows[0].resolution.target.edition == 3


def test_real_prepare_commit_read_print_and_usage_preserve_occurrences(
    creative_engine, planning, importer, prepared
):
    preview, path, command, targets = prepared
    assert (preview.total_rows, preview.matched_rows, preview.duplicate_uses) == (3, 3, 1)
    first_page = importer.read(preview.proposal, actor=planning.editor, limit=2)
    last_page = importer.read(preview.proposal, actor=planning.editor, offset=2, limit=2)
    assert first_page.next_offset == 2 and last_page.next_offset is None
    assert tuple(row.row.row_number for row in first_page.rows + last_page.rows) == (2, 3, 4)
    saved = importer.commit(preview.proposal, actor=planning.editor, idempotency_key=key())
    assert saved.disposition == "IMPORTED" and not saved.replayed
    assert saved.current_revision_id == saved.composition.deliverable_revision_id
    assert saved.print_record_id is not None
    assert [section.label for section in saved.composition.sections] == ["상권", "1회", "2회"]
    forms = [section for section in saved.composition.sections if section.kind == "FORM"]
    pages = [
        planning.service.query(
            ReadContentSection(
                query_kind="READ_SECTION",
                edition_id=saved.composition.edition_id,
                revision_id=saved.composition.deliverable_revision_id,
                composition_sha256=saved.composition.composition_sha256,
                section_id=section.section_id,
                after_position=0,
                limit=100,
            ),
            actor=planning.viewer,
        )
        for section in forms
    ]
    placements = tuple(row for page in pages for row in page.rows)
    assert len({row.placement_id for row in placements}) == 3
    assert [row.target.source_id for row in placements] == [
        targets[0]["source_id"],
        targets[1]["source_id"],
        targets[0]["source_id"],
    ]
    assert placements[0].display_number == "문항 1"
    assert placements[0].points_milli == 2125
    assert placements[0].note == "사용자가 기입한 메모"
    usage = planning.service.query(
        ReadContentUsage(
            query_kind="USAGE",
            targets=tuple(ExternalSlotTarget(**target) for target in targets),
            academic_year=2026,
            after=None,
            limit=100,
        ),
        actor=planning.viewer,
    )
    assert len(usage.rows) == 3
    assert all(row.currently_placed and row.print_count == 1 for row in usage.rows)
    with Session(creative_engine) as session:
        printed = session.get(ContentPrintRecord, saved.print_record_id)
        assert printed is not None
        assert printed.canonical_record["printed_on"] == "2026-01-02"
        assert printed.canonical_record["output"] is None
        receipts = session.scalars(
            select(ContentPlanningCommandReceiptRecord).where(
                ContentPlanningCommandReceiptRecord.actor_id == planning.editor.actor_id,
            )
        ).all()
        assert len(receipts) == 2
        for receipt in receipts:
            encoded = json.dumps(receipt.result_pointer, ensure_ascii=False)
            assert len(encoded) < 3000
            assert "사용자가 기입한 메모" not in encoded and "workbook_bytes" not in encoded
    assert product_count(creative_engine, command.sha256) == 1
    assert path.read_bytes().startswith(b"PK")


@pytest.mark.parametrize("different_actors", [False, True])
def test_same_file_concurrent_commit_creates_one_product_and_print(
    creative_engine, planning, importer, prepared, different_actors
):
    preview, path, command, _ = prepared
    second_actor = planning.peer if different_actors else planning.editor
    second_preview = (
        importer.prepare(path, request(path, second_actor), second_actor)
        if different_actors
        else preview
    )
    if different_actors:
        assert preview.proposal != second_preview.proposal
    shared_key, barrier = key(), Barrier(2)

    def submit(pair):
        actor, proposal = pair
        barrier.wait(timeout=20)
        return importer.commit(proposal, actor=actor, idempotency_key=shared_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                submit,
                (
                    (planning.editor, preview.proposal),
                    (second_actor, second_preview.proposal),
                ),
            )
        )
    assert len({result.composition.edition_id for result in results}) == 1
    assert len({result.print_record_id for result in results}) == 1
    assert {result.disposition for result in results} == {"IMPORTED", "ALREADY_IMPORTED"}
    assert product_count(creative_engine, command.sha256) == 1
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentEditionRecord)
                .where(ContentEditionRecord.deliverable_id == results[0].composition.deliverable_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentPrintRecord)
                .where(ContentPrintRecord.edition_id == results[0].composition.edition_id)
            )
            == 1
        )


def test_same_commit_key_different_files_conflicts_and_rolls_back_loser(
    creative_engine, planning, importer, prepared, tmp_path
):
    first, _, first_command, _ = prepared
    numbers = tuple(row.row.external_number for row in first.rows)
    path = filled_workbook(tmp_path, numbers, title="다른 교재")
    second = importer.prepare(path, request(path, planning.editor), planning.editor)
    barrier, shared_key = Barrier(2), key()

    def submit(preview):
        barrier.wait(timeout=20)
        try:
            return importer.commit(
                preview.proposal, actor=planning.editor, idempotency_key=shared_key
            )
        except ContentPlanningError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(submit, (first, second)))
    assert sum(result == "CONTENT_IDEMPOTENCY_CONFLICT" for result in results) == 1
    assert sum(not isinstance(result, str) for result in results) == 1
    assert (
        product_count(creative_engine, first_command.sha256)
        + product_count(creative_engine, second.workbook_sha256)
    ) == 1


def test_unresolved_rows_explicitly_block_commit_without_partial_product(
    creative_engine, planning, importer, tmp_path
):
    missing, ambiguous, unavailable = unused_numbers(creative_engine, 3)
    add_source(creative_engine, ambiguous)
    add_source(creative_engine, ambiguous)
    target = add_source(creative_engine, unavailable)
    with Session(creative_engine) as session, session.begin():
        source = session.get(ExternalItemSourceRecord, target["source_id"])
        assert source is not None
        source.current_revision_id = None
    path = filled_workbook(tmp_path, (missing, ambiguous, unavailable))
    preview = importer.prepare(path, request(path, planning.editor), planning.editor)
    assert [row.resolution.status for row in preview.rows] == [
        "MISSING",
        "AMBIGUOUS",
        "UNAVAILABLE",
    ]
    assert not preview.can_commit and preview.unresolved_rows == 3
    with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_UNRESOLVED"):
        importer.commit(preview.proposal, actor=planning.editor, idempotency_key=key())
    assert product_count(creative_engine, preview.workbook_sha256) == 0


def test_proposal_owner_hash_and_metadata_are_checked(planning, importer, prepared):
    preview, _, _, _ = prepared
    for action in (
        lambda pointer: importer.read(pointer, actor=planning.peer),
        lambda pointer: importer.commit(pointer, actor=planning.peer, idempotency_key=key()),
    ):
        with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_PROPOSAL_OWNER_MISMATCH"):
            action(preview.proposal)
    for changes in (
        {"sha256": "sha256:" + "0" * 64},
        {"schema_ref": "eom://schemas/content-planning/other/1.0"},
        {"member_path": "source/original.xlsx"},
    ):
        with pytest.raises(ContentPlanningError, match="CONTENT_WORKBOOK_PROPOSAL_INVALID"):
            importer.read(preview.proposal.model_copy(update=changes), actor=planning.editor)


@pytest.mark.parametrize("committed", [False, True])
def test_permission_revocation_blocks_initial_commit_and_replay(
    creative_engine, planning, importer, prepared, committed
):
    preview, _, _, _ = prepared
    command_key = key()
    if committed:
        importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    with Session(creative_engine) as session, session.begin():
        assignment = session.get(OperatorRoleAssignmentRecord, planning.editor_assignment)
        session.delete(assignment)
    with pytest.raises(ContentPlanningError, match="CONTENT_PLANNING_PERMISSION_DENIED"):
        importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    with pytest.raises(ContentPlanningError, match="CONTENT_PLANNING_PERMISSION_DENIED"):
        importer.read(preview.proposal, actor=planning.editor)
    assert product_count(creative_engine, preview.workbook_sha256) == int(committed)


@pytest.mark.parametrize("committed", [False, True])
def test_source_revocation_blocks_commit_and_replay_without_rewriting_saved_history(
    creative_engine, planning, importer, tmp_path, committed
):
    # Seed a not-yet-accepted Intake source. Accepted source evidence cannot be
    # rewritten even in this disposable DB; rejection is valid before acceptance.
    def initial_pending(session, _context, _instances):
        for record in session.new:
            if isinstance(record, ContentIntakeBatchRecord):
                record.state = "NEEDS_DECISION"

    number = unused_numbers(creative_engine, 1)[0]
    event.listen(Session, "before_flush", initial_pending)
    try:
        target = add_source(creative_engine, number)
    finally:
        event.remove(Session, "before_flush", initial_pending)
    path = filled_workbook(tmp_path, (number,))
    preview = importer.prepare(path, request(path, planning.editor), planning.editor)
    assert preview.can_commit
    command_key = key()
    if committed:
        importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    with Session(creative_engine) as session, session.begin():
        batch = session.scalar(
            select(ContentIntakeBatchRecord)
            .join(ContentIntakeSourceFileRecord)
            .join(
                ExternalItemSourceRevisionRecord,
                ExternalItemSourceRevisionRecord.selected_source_file_id
                == ContentIntakeSourceFileRecord.source_file_id,
            )
            .where(ExternalItemSourceRevisionRecord.revision_id == target["source_revision_id"])
        )
        assert batch is not None
        batch.state = "REJECTED"
    with pytest.raises(ValueError, match="CURATED_SOURCE_STALE"):
        importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    assert product_count(creative_engine, preview.workbook_sha256) == int(committed)


def test_prepare_replay_keeps_frozen_pins_even_when_current_source_selection_changes(
    creative_engine, planning, importer, prepared
):
    preview, path, command, targets = prepared
    with Session(creative_engine) as session, session.begin():
        source = session.get(ExternalItemSourceRecord, targets[0]["source_id"])
        assert source is not None
        source.current_revision_id = None
    replay = importer.prepare(path, command, planning.editor)
    assert replay == preview
    changed = command.model_copy(update={"original_filename": "changed.xlsx"})
    with pytest.raises(ContentPlanningError, match="CONTENT_IDEMPOTENCY_CONFLICT"):
        importer.prepare(path, changed, planning.editor)


def test_replay_returns_import_revision_without_rolling_back_later_user_edits(
    planning, importer, prepared
):
    preview, _, _, _ = prepared
    command_key = key()
    first = importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    # The first section is a group, while the next one owns the actual slots.
    changed = planning.service.execute(
        change(first.composition, {1: slots(1)}), actor=planning.peer, idempotency_key=key()
    ).composition
    replay = importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    assert replay.replayed and replay.composition == first.composition
    assert replay.current_revision_id == changed.deliverable_revision_id


def test_print_failure_rolls_back_content_and_receipt_then_same_request_can_retry(
    creative_engine, planning, importer, prepared, monkeypatch
):
    preview, _, _, _ = prepared
    command_key = key()
    original = importer.prints.record_in_transaction

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic interruption after print INSERT")

    with monkeypatch.context() as patch:
        patch.setattr(importer.prints, "record_in_transaction", interrupted)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            importer.commit(preview.proposal, actor=planning.editor, idempotency_key=command_key)
    assert product_count(creative_engine, preview.workbook_sha256) == 0
    with Session(creative_engine) as session:
        assert (
            session.get(
                ContentPlanningCommandReceiptRecord,
                (
                    planning.editor.actor_id,
                    "COMMIT_CONTENT_WORKBOOK",
                    command_key,
                ),
            )
            is None
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentPrintRecord)
                .where(ContentPrintRecord.recorded_by == planning.editor.actor_id)
            )
            == 0
        )
    recovered = importer.commit(
        preview.proposal, actor=planning.editor, idempotency_key=command_key
    )
    assert recovered.disposition == "IMPORTED" and recovered.print_record_id is not None


@pytest.mark.parametrize("distinct", [False, True])
def test_401_rows_use_bounded_batched_queries_not_one_query_per_occurrence(
    creative_engine, tmp_path, distinct
):
    if distinct:
        numbers = unused_numbers(creative_engine, 401)
    else:
        numbers = unused_numbers(creative_engine, 2)
        for number in numbers:
            add_source(creative_engine, number)
        numbers = tuple(numbers[i % 2] for i in range(401))
    document = read_content_workbook(filled_workbook(tmp_path, numbers))
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        with Session(creative_engine) as session:
            resolved = resolve_workbook_rows(session, document)
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert len(resolved) == 401
    assert {row.status for row in resolved} == ({"MISSING"} if distinct else {"MATCHED"})
    # One namespace scan, ceil(unique_numbers/200) indexed lookups, and one
    # metadata admission query per <=200 matched unique sources (not per use).
    assert len(statements) == (4 if distinct else 3)
    assert sum("external_number IN" in sql for sql in statements) == (3 if distinct else 1)
