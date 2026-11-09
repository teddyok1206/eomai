"""Atomic-edit planning and print-scope cases taken from the workbook design."""

from __future__ import annotations

from copy import deepcopy

import pytest
from eom_catalog_contracts.content_planning import ContentEditionCompositionV1
from eom_catalog_contracts.content_planning_edits import SaveContentSections, SectionSlotChange
from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    CuratedSlot,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.content_planning_layout import (
    ContentPlanningConflict,
    SectionSlotState,
    copy_assembly_slots,
    plan_slot_changes,
    select_print_scope,
)
from eom_identifiers import content_sha256
from pydantic import ValidationError

from tests.unit.content_planning_fixtures import SHA, TIME, composition, identifier, section, slot


def state(number: int, positions: tuple[int, ...]) -> SectionSlotState:
    return SectionSlotState(
        section_id=identifier("section", number),
        assembly_revision_id=identifier("assemblyrev", number),
        manifest_sha256=SHA,
        placements=tuple(
            CuratedSlot.model_validate(
                {
                    **slot(n),
                    "position": index,
                }
            )
            for index, n in enumerate(positions, 1)
        ),
    )


def change(before: SectionSlotState, placements: tuple[CuratedSlot, ...]) -> SectionSlotChange:
    return SectionSlotChange(
        section_id=before.section_id,
        before_assembly_revision_id=before.assembly_revision_id,
        before_manifest_sha256=before.manifest_sha256,
        placements=placements,
    )


def test_cross_section_swap_uses_two_final_arrays_without_losing_either_target() -> None:
    first, second = state(1, (1,)), state(2, (2,))
    owners = {
        identifier("placement", 1): first.section_id,
        identifier("placement", 2): second.section_id,
    }
    changes = (change(first, second.placements), change(second, first.placements))
    command = SaveContentSections(
        change_kind="SAVE_SECTIONS",
        expected_revision_id=identifier("delivrev"),
        expected_sha256=SHA,
        changes=changes,
    )
    validate_contract("content-planning-edit-v1", command.model_dump(mode="json"))
    result = plan_slot_changes(
        {first.section_id: first, second.section_id: second}, changes, owners
    )
    assert len(result.changed_sections) == 2
    assert result.moved == tuple(sorted(owners))
    assert result.added == result.removed == result.replaced == ()
    assert first.placements[0].placement_id == identifier("placement", 1)


def test_move_requires_source_section_in_same_atomic_edit() -> None:
    first, second = state(1, (1,)), state(2, (2,))
    with pytest.raises(ContentPlanningConflict, match="CONTENT_MOVE_SOURCE_NOT_INCLUDED"):
        plan_slot_changes(
            {first.section_id: first},
            (change(first, second.placements),),
            {identifier("placement", 2): second.section_id},
        )


def test_repeated_item_does_not_collapse_distinct_occurrences() -> None:
    before = state(1, (1,))
    placements = state(1, (1, 2, 3)).placements
    result = plan_slot_changes({before.section_id: before}, (change(before, placements),), {})
    assert result.added == (identifier("placement", 2), identifier("placement", 3))
    assert len(result.changed_sections[0].placements) == 3
    assert len({row.target.item_id for row in placements}) == 1


def test_same_save_is_no_change_and_old_snapshot_is_unchanged() -> None:
    before = state(1, (1, 2))
    result = plan_slot_changes(
        {before.section_id: before}, (change(before, before.placements),), {}
    )
    assert result.is_no_change
    assert result.added == result.removed == result.moved == result.replaced == ()


def test_old_pointer_and_duplicate_occurrence_are_rejected() -> None:
    before = state(1, (1,))
    stale = change(before, before.placements).model_copy(
        update={"before_manifest_sha256": "sha256:" + "b" * 64}
    )
    with pytest.raises(ContentPlanningConflict, match="CONTENT_SECTION_REVISION_STALE"):
        plan_slot_changes({before.section_id: before}, (stale,), {})
    second = state(2, (2,))
    with pytest.raises(ContentPlanningConflict, match="CONTENT_PLACEMENT_DUPLICATE"):
        plan_slot_changes(
            {before.section_id: before, second.section_id: second},
            (change(before, before.placements), change(second, before.placements)),
            {},
        )


def test_replacement_and_removal_are_distinct_events() -> None:
    before = state(1, (1, 2))
    changed = CuratedSlot.model_validate(
        {
            **before.placements[0].model_dump(mode="json"),
            "target": {"placement_kind": "EMPTY"},
        }
    )
    result = plan_slot_changes({before.section_id: before}, (change(before, (changed,)),), {})
    assert result.removed == (identifier("placement", 2),)
    assert result.replaced == (identifier("placement", 1),)
    assert result.moved == ()


def test_copy_pins_original_revision_but_assigns_new_occurrence_identity() -> None:
    body = {
        "schema_version": "curated-document-assembly-manifest/2.0",
        "assembly_id": identifier("assembly"),
        "assembly_revision_id": identifier("assemblyrev"),
        "revision_number": 1,
        "previous_revision_id": None,
        "selection_sha256": SHA,
        "placements": [slot(1), slot(2)],
        "created_by": identifier("operator"),
        "created_at": TIME,
    }
    body["manifest_sha256"] = content_sha256(body)
    source = CuratedDocumentAssemblyManifestV2.model_validate(body)
    copied = copy_assembly_slots(source, (identifier("placement", 3), identifier("placement", 4)))
    assert copied[0].target == source.placements[0].target
    assert copied[0].copied_from.placement_id == source.placements[0].placement_id
    assert copied[0].copied_from.manifest_sha256 == source.manifest_sha256
    assert copied[0].placement_id != source.placements[0].placement_id
    with pytest.raises(ContentPlanningConflict):
        copy_assembly_slots(source, (identifier("placement", 1), identifier("placement", 4)))


def test_printed_first_round_scope_does_not_change_when_second_round_changes() -> None:
    rows = [section(1), section(2, 2)]
    first = ContentEditionCompositionV1.model_validate(composition(rows))
    changed_rows = deepcopy(rows)
    changed_rows[1]["form"]["form_revision_id"] = identifier("formrev", 20)
    changed_rows[1]["form"]["manifest_sha256"] = "sha256:" + "b" * 64
    changed = ContentEditionCompositionV1.model_validate(
        composition(
            changed_rows,
            deliverable_revision_id=identifier("delivrev", 2),
            revision_number=2,
            previous_revision_id=identifier("delivrev"),
        )
    )
    selection = (identifier("section", 1),)
    before = select_print_scope(first, selection)
    after = select_print_scope(changed, selection)
    assert before == after
    assert first.composition_sha256 != changed.composition_sha256


def test_continuous_numbering_includes_preceding_unselected_form() -> None:
    rows = [
        {**section(1), "kind": "GROUP", "form": None, "numbering": "CONTINUE_WITHIN_GROUP"},
        section(2, 1, 1),
        section(3, 2, 1),
    ]
    first = ContentEditionCompositionV1.model_validate(composition(rows))
    before = select_print_scope(first, (identifier("section", 3),))
    assert before.forms[0].start_number == 21
    changed_rows = deepcopy(rows)
    changed_rows[1]["form"]["placement_count"] = 21
    changed = ContentEditionCompositionV1.model_validate(composition(changed_rows))
    after = select_print_scope(changed, (identifier("section", 3),))
    assert after.forms[0].start_number == 22
    assert before.scope_sha256 != after.scope_sha256


def test_group_and_leaf_selection_deduplicates_forms_in_content_order() -> None:
    rows = [{**section(1), "kind": "GROUP", "form": None}, section(2, 1, 1), section(3, 2, 1)]
    value = ContentEditionCompositionV1.model_validate(composition(rows))
    scope = select_print_scope(value, (identifier("section", 3), identifier("section", 1)))
    assert [row.section_id for row in scope.forms] == [
        identifier("section", 2),
        identifier("section", 3),
    ]
    assert [row.start_number for row in scope.forms] == [1, 1]
    validate_contract("content-print-scope-v1", scope.model_dump(mode="json"))


def test_empty_form_only_blocks_selected_scope_and_not_other_finished_round() -> None:
    rows = [section(1), section(2, 2)]
    rows[1]["form"]["placement_count"] = 0
    value = ContentEditionCompositionV1.model_validate(composition(rows))
    assert select_print_scope(value, (identifier("section", 1),)).forms
    with pytest.raises(ContentPlanningConflict, match="CONTENT_PRINT_EMPTY_SECTION"):
        select_print_scope(value, (identifier("section", 2),))


@pytest.mark.parametrize(
    "selection", [(), (identifier("section", 9),), (identifier("section"),) * 2]
)
def test_invalid_print_selection_never_falls_back_to_latest_or_entire_edition(selection) -> None:
    value = ContentEditionCompositionV1.model_validate(composition())
    with pytest.raises(ContentPlanningConflict):
        select_print_scope(value, selection)


def test_10000_sections_use_iterative_tree_and_bounded_scope() -> None:
    value = ContentEditionCompositionV1.model_validate(
        composition([section(index, index) for index in range(1, 10001)])
    )
    scope = select_print_scope(value, (identifier("section", 10000),))
    assert len(scope.forms) == 1
    assert scope.forms[0].start_number == 1


def test_depth_limit_fails_without_recursion_overflow() -> None:
    rows = []
    for number in range(1, 66):
        rows.append(
            {
                **section(number, 1, None if number == 1 else number - 1),
                "kind": "GROUP",
                "form": None,
            }
        )
    with pytest.raises(ValidationError, match="64 levels"):
        ContentEditionCompositionV1.model_validate(composition(rows))
