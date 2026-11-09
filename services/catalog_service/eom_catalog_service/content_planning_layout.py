"""Pure edition layout rules: occurrence edits and exact selected print scopes.

No database, file, rendering or network operations occur here. The application
owner supplies immutable snapshots and performs authorization and atomic commit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from eom_catalog_contracts.content_planning import (
    ContentEditionCompositionV1,
    ContentPrintScopeV1,
    ContentScopedForm,
    ContentSectionPathEntry,
)
from eom_catalog_contracts.content_planning_edits import SectionSlotChange
from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    CuratedSlot,
    SlotCopyOrigin,
)
from eom_identifiers import content_sha256


class ContentPlanningConflict(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SectionSlotState:
    section_id: str
    assembly_revision_id: str
    manifest_sha256: str
    placements: tuple[CuratedSlot, ...]


@dataclass(frozen=True)
class ContentSlotDelta:
    changed_sections: tuple[SectionSlotChange, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    moved: tuple[str, ...]
    replaced: tuple[str, ...]

    @property
    def is_no_change(self) -> bool:
        return not self.changed_sections


def plan_slot_changes(
    before: Mapping[str, SectionSlotState],
    changes: tuple[SectionSlotChange, ...],
    current_owners: Mapping[str, str],
) -> ContentSlotDelta:
    """O(changed placements) plus indexed current ownership, no sequential mutation.

    The owner locks the Edition and supplies only affected manifests. current_owners
    is the indexed lookup of submitted occurrence IDs, not a full history scan.
    """

    sections = {change.section_id for change in changes}
    if len(sections) != len(changes):
        raise ContentPlanningConflict("CONTENT_SECTION_CHANGE_DUPLICATE")
    old: dict[str, tuple[str, CuratedSlot]] = {}
    new: dict[str, tuple[str, CuratedSlot]] = {}
    changed: list[SectionSlotChange] = []
    for change in changes:
        state = before.get(change.section_id)
        if state is None:
            raise ContentPlanningConflict("CONTENT_SECTION_NOT_FOUND")
        if (
            state.assembly_revision_id != change.before_assembly_revision_id
            or state.manifest_sha256 != change.before_manifest_sha256
        ):
            raise ContentPlanningConflict("CONTENT_SECTION_REVISION_STALE")
        for slot in state.placements:
            if slot.placement_id in old:
                raise ContentPlanningConflict("CONTENT_PLACEMENT_INTEGRITY_INVALID")
            old[slot.placement_id] = (change.section_id, slot)
        for slot in change.placements:
            if slot.placement_id in new:
                raise ContentPlanningConflict("CONTENT_PLACEMENT_DUPLICATE")
            owner = current_owners.get(slot.placement_id)
            if owner is not None and owner not in sections:
                raise ContentPlanningConflict("CONTENT_MOVE_SOURCE_NOT_INCLUDED")
            new[slot.placement_id] = (change.section_id, slot)
        if state.placements != change.placements:
            changed.append(change)
    old_ids, new_ids = set(old), set(new)
    retained = old_ids & new_ids
    return ContentSlotDelta(
        changed_sections=tuple(changed),
        added=tuple(sorted(new_ids - old_ids)),
        removed=tuple(sorted(old_ids - new_ids)),
        moved=tuple(
            sorted(
                key
                for key in retained
                if old[key][0] != new[key][0] or old[key][1].position != new[key][1].position
            )
        ),
        replaced=tuple(sorted(key for key in retained if old[key][1].target != new[key][1].target)),
    )


def copy_assembly_slots(
    source: CuratedDocumentAssemblyManifestV2,
    new_placement_ids: tuple[str, ...],
    *,
    selected_placement_ids: tuple[str, ...] | None = None,
) -> tuple[CuratedSlot, ...]:
    """Copy only pinned values. UUID generation belongs to the application owner."""

    old_ids = {slot.placement_id for slot in source.placements}
    selected = old_ids if selected_placement_ids is None else set(selected_placement_ids)
    if selected_placement_ids is not None and (
        not selected or len(selected) != len(selected_placement_ids) or not selected <= old_ids
    ):
        raise ContentPlanningConflict("CONTENT_COPY_SELECTION_INVALID")
    slots = tuple(slot for slot in source.placements if slot.placement_id in selected)
    if (
        len(new_placement_ids) != len(slots)
        or len(set(new_placement_ids)) != len(new_placement_ids)
        or old_ids & set(new_placement_ids)
    ):
        raise ContentPlanningConflict("CONTENT_COPY_PLACEMENT_ID_INVALID")
    result: list[CuratedSlot] = []
    for position, (slot, new_id) in enumerate(zip(slots, new_placement_ids, strict=True), 1):
        origin = SlotCopyOrigin(
            assembly_id=source.assembly_id,
            assembly_revision_id=source.assembly_revision_id,
            manifest_sha256=source.manifest_sha256,
            placement_id=slot.placement_id,
        )
        result.append(
            CuratedSlot.model_validate(
                {
                    **slot.selection().model_dump(mode="json"),
                    "placement_id": new_id,
                    "position": position,
                    "copied_from": origin.model_dump(mode="json"),
                }
            )
        )
    return tuple(result)


def select_print_scope(
    composition: ContentEditionCompositionV1, selected_section_ids: tuple[str, ...]
) -> ContentPrintScopeV1:
    """Expand groups in canonical order, including preceding numbering context.

    A continuing group numbers all descendant Forms as one stream. Without such a
    group, a continuing Form shares its parent's stream; reset Forms start at one.
    The bounded-depth path tuples cost at most 64 entries per section, not recursion.
    """

    selected = set(selected_section_ids)
    if not selected or len(selected) != len(selected_section_ids):
        raise ContentPlanningConflict("CONTENT_PRINT_SELECTION_INVALID")
    if not selected <= {section.section_id for section in composition.sections}:
        raise ContentPlanningConflict("CONTENT_SECTION_NOT_FOUND")
    paths: dict[str | None, tuple[ContentSectionPathEntry, ...]] = {None: ()}
    enabled: dict[str | None, bool] = {None: False}
    streams: dict[str | None, str | None] = {None: None}
    next_number: dict[str | None, int] = {}
    forms: list[ContentScopedForm] = []
    for section in composition.sections:
        path = (
            *paths[section.parent_id],
            ContentSectionPathEntry(section_id=section.section_id, label=section.label),
        )
        paths[section.section_id] = path
        include = enabled[section.parent_id] or section.section_id in selected
        enabled[section.section_id] = include
        stream = streams[section.parent_id]
        if (
            stream is None
            and section.kind == "GROUP"
            and section.numbering == "CONTINUE_WITHIN_GROUP"
        ):
            stream = section.section_id
        streams[section.section_id] = stream
        if section.form is None:
            continue
        continuing = stream is not None or section.numbering == "CONTINUE_WITHIN_GROUP"
        if stream is None:
            stream = section.parent_id
        start = next_number.get(stream, 1) if continuing else 1
        if continuing:
            next_number[stream] = start + section.form.placement_count
        if include:
            if section.form.placement_count == 0:
                raise ContentPlanningConflict("CONTENT_PRINT_EMPTY_SECTION")
            forms.append(
                ContentScopedForm(
                    section_id=section.section_id,
                    path=path,
                    form=section.form,
                    numbering="CONTINUE_WITHIN_GROUP" if continuing else "RESET_PER_SECTION",
                    start_number=start,
                )
            )
    if not forms:
        raise ContentPlanningConflict("CONTENT_PRINT_EMPTY_SELECTION")
    body = {
        "schema_version": "content-print-scope/1.0",
        "deliverable_id": composition.deliverable_id,
        "edition_id": composition.edition_id,
        "content_title": composition.content_title,
        "edition_label": composition.edition_label,
        "academic_year": composition.academic_year,
        "forms": [form.model_dump(mode="json") for form in forms],
    }
    return ContentPrintScopeV1.model_validate({**body, "scope_sha256": content_sha256(body)})
