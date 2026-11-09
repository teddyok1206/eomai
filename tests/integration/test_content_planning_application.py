"""Actual application transactions/RBAC/replay in guarded disposable PostgreSQL.

The empty placements here isolate editor persistence from independent source/Graph
admission. They are not evidence of HWPX rendering or live browser acceptance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
from eom_catalog_contracts.content_planning import (
    ContentEditionCompositionV1,
    ContentSectionStructure,
)
from eom_catalog_contracts.content_planning_commands import (
    CopyContentEdition,
    CreateContentEdition,
    CreatePlannedContent,
    EditContentEdition,
)
from eom_catalog_contracts.content_planning_edits import (
    SaveContentSections,
    SaveContentStructure,
    SectionSlotChange,
)
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import ContentPlanningConflict
from eom_catalog_service.content_planning_models import (
    ContentPlanningEventRecord,
)
from eom_catalog_service.content_planning_service import ContentPlanningService
from eom_catalog_service.curated_document_assembly_models import (
    CuratedDocumentAssemblyRevisionRecord,
)
from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyService
from eom_identity_service.models import OperatorRecord, OperatorRoleAssignmentRecord, RoleRecord
from eom_identity_service.repository import seed_builtin_rbac
from eom_operator_identity import ActorContext, ActorSource, ActorType
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from tests.unit.content_planning_fixtures import slot
from tests.unit.test_content_planning_workbook_reference import _indices
from tests.unit.test_content_planning_workbook_reference import workbook as workbook

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def ident(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


def key() -> str:
    return "planning-test:" + uuid4().hex


@dataclass(frozen=True)
class Planning:
    service: ContentPlanningService
    editor: ActorContext
    peer: ActorContext
    viewer: ActorContext
    editor_assignment: str


@pytest.fixture
def planning(creative_engine):
    actors, assignments = [], []
    with Session(creative_engine) as session, session.begin():
        seed_builtin_rbac(session)
        session.flush()
        roles = {row.role_key: row.role_id for row in session.scalars(select(RoleRecord))}
        for role in ("EDITOR", "EDITOR", "VIEWER"):
            operator_id = ident("operator")
            session.add(
                OperatorRecord(
                    operator_id=operator_id,
                    username=operator_id,
                    normalized_username=operator_id,
                    display_name="Synthetic content editor",
                    status="ACTIVE",
                    must_change_password=False,
                    created_by="content-planning-test",
                )
            )
            session.flush()
            assignment = ident("oprole")
            session.add(
                OperatorRoleAssignmentRecord(
                    operator_role_assignment_id=assignment,
                    operator_id=operator_id,
                    role_id=roles[role],
                    assigned_by="test",
                    assigned_at=datetime.now(UTC),
                )
            )
            actors.append(
                ActorContext(
                    actor_type=ActorType.OPERATOR,
                    operator_id=operator_id,
                    session_id=ident("apisession"),
                    request_id="content-test",
                    authentication_time=datetime.now(UTC),
                    permissions=frozenset(),
                    source=ActorSource.APPLICATION_API,
                )
            )
            assignments.append(assignment)
    return Planning(ContentPlanningService(creative_engine), *actors, assignments[0])


def creation(count: int = 2) -> CreatePlannedContent:
    return CreatePlannedContent(
        command_kind="CREATE_CONTENT",
        content_title="학교별 맞춤 시험지",
        content_type="OTHER",
        edition_label="첫 판",
        academic_year=2027,
        sections=tuple(
            ContentSectionStructure(
                section_id=ident("section"),
                parent_id=None,
                kind="FORM",
                ordinal=i,
                label=f"{i}회차",
                numbering="RESET_PER_SECTION",
            )
            for i in range(1, count + 1)
        ),
    )


def create(planning: Planning, count: int = 2):
    return planning.service.execute(
        creation(count), actor=planning.editor, idempotency_key=key()
    ).composition


def change(
    composition: ContentEditionCompositionV1, selections: dict[int, tuple[CuratedSlot, ...]]
):
    changes = []
    for index, placements in selections.items():
        section = composition.sections[index]
        assert section.form is not None
        changes.append(
            SectionSlotChange(
                section_id=section.section_id,
                before_assembly_revision_id=section.form.assembly_revision_id,
                before_manifest_sha256=section.form.manifest_sha256,
                placements=placements,
            )
        )
    return EditContentEdition(
        command_kind="EDIT_EDITION",
        edition_id=composition.edition_id,
        edit=SaveContentSections(
            change_kind="SAVE_SECTIONS",
            expected_revision_id=composition.deliverable_revision_id,
            expected_sha256=composition.composition_sha256,
            changes=tuple(changes),
        ),
    )


def slots(count: int) -> tuple[CuratedSlot, ...]:
    return tuple(
        CuratedSlot.model_validate(
            {**slot(i, target={"placement_kind": "EMPTY"}), "placement_id": ident("placement")}
        )
        for i in range(1, count + 1)
    )


def test_read_pages_pin_saved_revision_and_history_does_not_repeat(planning):
    from eom_catalog_contracts.content_planning_queries import (
        ListContentEditions,
        ReadContentHistory,
        ReadContentSection,
    )

    original = create(planning)
    saved = planning.service.execute(
        change(original, {0: slots(240)}), actor=planning.editor, idempotency_key=key()
    ).composition
    planning.service.execute(
        change(saved, {0: slots(12)}), actor=planning.peer, idempotency_key=key()
    )
    query = ReadContentSection(
        query_kind="READ_SECTION",
        edition_id=saved.edition_id,
        revision_id=saved.deliverable_revision_id,
        composition_sha256=saved.composition_sha256,
        section_id=saved.sections[0].section_id,
        after_position=0,
        limit=200,
    )
    first = planning.service.query(query, actor=planning.viewer)
    second = planning.service.query(
        query.model_copy(update={"after_position": first.next_position}), actor=planning.viewer
    )
    assert first.total == second.total == 240
    assert [row.position for row in first.rows + second.rows] == list(range(1, 241))
    assert second.next_position is None
    editions = planning.service.query(
        ListContentEditions(
            query_kind="LIST_EDITIONS", deliverable_id=saved.deliverable_id, limit=10, after_id=None
        ),
        actor=planning.viewer,
    )
    assert editions.rows[0].revision_id != saved.deliverable_revision_id
    history = ReadContentHistory(
        query_kind="HISTORY", edition_id=saved.edition_id, limit=2, before_sequence=None
    )
    page1 = planning.service.query(history, actor=planning.viewer)
    page2 = planning.service.query(
        history.model_copy(update={"before_sequence": page1.next_sequence}), actor=planning.viewer
    )
    assert len(page1.rows) == 2 and len(page2.rows) == 1
    assert len({row.sequence for row in page1.rows + page2.rows}) == 3


def test_archived_product_is_not_readable_through_edition_pointer(creative_engine, planning):
    from eom_catalog_contracts.content_planning_queries import (
        ListContentEditions,
        ReadContentEdition,
    )
    from eom_catalog_service.models import DeliverableRecord

    saved = create(planning)
    with Session(creative_engine) as session, session.begin():
        session.get(DeliverableRecord, saved.deliverable_id).lifecycle_state = "ARCHIVED"
    with pytest.raises(ContentPlanningError, match="CONTENT_EDITION_NOT_FOUND"):
        planning.service.query(
            ReadContentEdition(
                query_kind="READ_EDITION", edition_id=saved.edition_id, revision_id=None
            ),
            actor=planning.viewer,
        )
    listed = planning.service.query(
        ListContentEditions(
            query_kind="LIST_EDITIONS", deliverable_id=saved.deliverable_id, after_id=None, limit=10
        ),
        actor=planning.viewer,
    )
    assert listed.rows == ()


def section(planning, composition, index=0):
    return planning.service.read_section(
        composition.edition_id,
        composition.sections[index].section_id,
        revision_id=composition.deliverable_revision_id,
        composition_sha256=composition.composition_sha256,
        actor=planning.peer,
    )


def test_twenty_rounds_share_content_but_not_private_assembly_list(creative_engine, planning):
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(creative_engine, "before_cursor_execute", capture)
    try:
        composition = create(planning, 20)
        read = planning.service.read(composition.edition_id, actor=planning.viewer)
    finally:
        event.remove(creative_engine, "before_cursor_execute", capture)
    assert read == composition
    assert len(read.sections) == 20
    # No per-section read loop: twenty rounds stay below this fixed query bound.
    assert len(statements) <= 20
    library = CuratedDocumentAssemblyService(creative_engine, Mock())
    entries, cursor = library.list_recent_titled(actor=planning.editor)
    assert entries == () and cursor is None


def test_1200_occurrences_exact_replay_and_no_change_does_not_add_history(
    creative_engine, planning
):
    original = create(planning)
    request, request_key = change(original, {0: slots(1200)}), key()
    first = planning.service.execute(request, actor=planning.editor, idempotency_key=request_key)
    assert len(section(planning, first.composition).placements) == 1200
    later = planning.service.execute(
        change(first.composition, {1: slots(1)}), actor=planning.peer, idempotency_key=key()
    ).composition
    replay = planning.service.execute(request, actor=planning.editor, idempotency_key=request_key)
    assert replay.replayed and replay.composition == first.composition
    assert replay.current_revision_id == later.deliverable_revision_id
    unchanged = planning.service.execute(
        change(
            later, {1: tuple(item.selection() for item in section(planning, later, 1).placements)}
        ),
        actor=planning.peer,
        idempotency_key=key(),
    )
    assert unchanged.disposition == "NO_CHANGE"
    assert unchanged.composition == later
    with Session(creative_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ContentPlanningEventRecord)
                .where(ContentPlanningEventRecord.edition_id == original.edition_id)
            )
            == 3
        )


def test_copy_previous_edition_preserves_original_and_gives_new_occurrences(planning):
    original = create(planning)
    original = planning.service.execute(
        change(original, {0: slots(3)}), actor=planning.editor, idempotency_key=key()
    ).composition
    old_slots = section(planning, original).placements
    copied = planning.service.execute(
        CopyContentEdition(
            command_kind="COPY_EDITION",
            source_edition_id=original.edition_id,
            source_revision_id=original.deliverable_revision_id,
            source_sha256=original.composition_sha256,
            edition_label="다음 해",
            academic_year=2028,
        ),
        actor=planning.peer,
        idempotency_key=key(),
    ).composition
    new_slots = section(planning, copied).placements
    assert (
        copied.deliverable_id == original.deliverable_id
        and copied.edition_id != original.edition_id
    )
    assert copied.academic_year == 2028 and original.academic_year == 2027
    assert {item.placement_id for item in old_slots}.isdisjoint(
        item.placement_id for item in new_slots
    )
    assert [item.copied_from.placement_id for item in new_slots] == [
        item.placement_id for item in old_slots
    ]
    assert planning.service.read(original.edition_id, actor=planning.editor) == original


def test_atomic_move_requires_both_arrays_and_preserves_position_identity(planning):
    current = create(planning)
    first, second = slots(1), slots(1)
    current = planning.service.execute(
        change(current, {0: first, 1: second}), actor=planning.editor, idempotency_key=key()
    ).composition
    with pytest.raises(ContentPlanningConflict, match="CONTENT_MOVE_SOURCE_NOT_INCLUDED"):
        planning.service.execute(
            change(current, {1: first}), actor=planning.peer, idempotency_key=key()
        )
    swapped = planning.service.execute(
        change(current, {0: second, 1: first}), actor=planning.peer, idempotency_key=key()
    ).composition
    assert section(planning, swapped).placements[0].placement_id == second[0].placement_id
    assert section(planning, swapped, 1).placements[0].placement_id == first[0].placement_id
    assert section(planning, current).placements[0].placement_id == first[0].placement_id


def test_same_key_race_replays_but_distinct_competing_edit_is_stale(planning):
    current = create(planning)
    command, shared_key = change(current, {0: slots(1)}), key()
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=10)
        return planning.service.execute(command, actor=planning.editor, idempotency_key=shared_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: submit(), range(2)))
    assert sorted(row.replayed for row in results) == [False, True]
    assert results[0].composition == results[1].composition
    with pytest.raises(ContentPlanningError, match="CONTENT_EDITION_REVISION_STALE"):
        planning.service.execute(
            change(current, {1: slots(1)}), actor=planning.peer, idempotency_key=key()
        )


def test_failure_after_writing_rows_rolls_back_then_same_key_can_finish(
    creative_engine, planning, monkeypatch
):
    from eom_catalog_service import content_planning_service as module

    current = create(planning)
    command, retry_key = change(current, {0: slots(2)}), key()
    original = module.save_edition_snapshot

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic interruption before receipt commit")

    with Session(creative_engine) as session:
        before = session.scalar(
            select(func.count()).select_from(CuratedDocumentAssemblyRevisionRecord)
        )
    with monkeypatch.context() as patch:
        patch.setattr(module, "save_edition_snapshot", interrupted)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            planning.service.execute(command, actor=planning.editor, idempotency_key=retry_key)
    assert planning.service.read(current.edition_id, actor=planning.editor) == current
    with Session(creative_engine) as session:
        assert (
            session.scalar(select(func.count()).select_from(CuratedDocumentAssemblyRevisionRecord))
            == before
        )
    assert (
        planning.service.execute(
            command, actor=planning.editor, idempotency_key=retry_key
        ).disposition
        == "SAVED"
    )


def test_actual_roles_are_rechecked_even_for_replay(creative_engine, planning):
    request, request_key = creation(), key()
    with pytest.raises(ContentPlanningError, match="PERMISSION_DENIED"):
        planning.service.execute(request, actor=planning.viewer, idempotency_key=key())
    saved = planning.service.execute(request, actor=planning.editor, idempotency_key=request_key)
    with Session(creative_engine) as session, session.begin():
        session.get(
            OperatorRoleAssignmentRecord, planning.editor_assignment
        ).revoked_at = datetime.now(UTC)
    with pytest.raises(ContentPlanningError, match="PERMISSION_DENIED"):
        planning.service.execute(request, actor=planning.editor, idempotency_key=request_key)
    assert (
        planning.service.read(saved.composition.edition_id, actor=planning.peer)
        == saved.composition
    )


def test_structure_revision_and_new_edition_do_not_relabel_history(planning):
    current = create(planning)
    structures = [
        ContentSectionStructure.model_validate(row.model_dump(exclude={"form"}))
        for row in current.sections
    ]
    structures[0] = structures[0].model_copy(update={"label": "새 이름"})
    edited = planning.service.execute(
        EditContentEdition(
            command_kind="EDIT_EDITION",
            edition_id=current.edition_id,
            edit=SaveContentStructure(
                change_kind="SAVE_STRUCTURE",
                expected_revision_id=current.deliverable_revision_id,
                expected_sha256=current.composition_sha256,
                edition_label="수정판",
                academic_year=2028,
                sections=tuple(structures),
                confirmed_removed_sections=(),
            ),
        ),
        actor=planning.peer,
        idempotency_key=key(),
    ).composition
    assert edited.sections[0].label == "새 이름"
    assert (
        planning.service.read(
            current.edition_id, revision_id=current.deliverable_revision_id, actor=planning.viewer
        )
        == current
    )
    assert edited.sections[1].form == current.sections[1].form
    added = planning.service.execute(
        CreateContentEdition(
            command_kind="CREATE_EDITION",
            deliverable_id=current.deliverable_id,
            edition_label="추가판",
            academic_year=2028,
            sections=(),
        ),
        actor=planning.peer,
        idempotency_key=key(),
    ).composition
    assert added.edition_id != current.edition_id and added.sections == ()


@pytest.mark.parametrize(
    "sheet,columns,total",
    [
        ("27_모의 배치", ("H",), 1120),
        ("27_E기적", ("F", "L", "R", "X", "AD", "AJ"), 1200),
    ],
)
def test_private_workbook_counts_drive_real_storage_without_importing_its_items(
    planning,
    workbook,
    sheet,
    columns,
    total,
):
    indices = _indices(workbook[sheet], columns)
    assert len(indices) == total
    # Exact old Earth-science content is not authorized for import. Reuse only
    # the actual layout count with synthetic EMPTY positions, never fake Items.
    current = create(planning, 1)
    saved = planning.service.execute(
        change(current, {0: slots(len(indices))}), actor=planning.editor, idempotency_key=key()
    ).composition
    assert len(section(planning, saved).placements) == total
