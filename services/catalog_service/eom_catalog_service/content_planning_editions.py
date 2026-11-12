"""Edition use-case composition, reusing curated/Form owners in one transaction."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_catalog_contracts.content_planning import (
    ContentEditionCompositionV1,
    ContentSection,
    ContentSectionStructure,
)
from eom_catalog_contracts.content_planning_commands import CreatePlannedContent
from eom_catalog_contracts.content_planning_edits import SaveContentSections, SaveContentStructure
from eom_catalog_contracts.curated_document_slots import (
    CuratedDocumentAssemblyManifestV2,
    CuratedSlot,
    ResolvedCuratedSlot,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_layout import SectionSlotState, plan_slot_changes
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentEditionRevisionFormRecord,
    ContentFormRevisionCompositionRecord,
)
from eom_catalog_service.content_planning_storage import (
    new_content_id,
    plan_form_revision,
    store_edition_revision,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord
from eom_catalog_service.curated_document_slot_origins import validate_slot_origins
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import (
    CuratedSlotRevisionWrite,
    append_curated_slot_revisions,
    read_curated_slot_revisions,
)
from eom_catalog_service.legacy_usage_models import AssessmentFormRevisionRecord
from eom_catalog_service.models import DeliverableRecord


def create_planned_content(
    session: Session,
    command: CreatePlannedContent,
    actor: ActorContext,
    *,
    content_key: str | None = None,
    initial_slots: dict[str, tuple[CuratedSlot, ...]] | None = None,
) -> tuple[ContentEditionRecord, ContentEditionCompositionV1]:
    """Create a product and its complete first edition in the caller's transaction."""
    product_id = new_content_id("deliverable")
    product = DeliverableRecord(
        deliverable_id=product_id,
        deliverable_key=content_key or "content-planning:" + product_id,
        deliverable_type=command.content_type,
        title=command.content_title,
        edition="CONTENT_PLANNING",
        lifecycle_state="IN_PRODUCTION",
        created_by=actor.actor_id,
    )
    session.add(product)
    session.flush()
    return create_edition_snapshot(
        session,
        product=product,
        edition_label=command.edition_label,
        academic_year=command.academic_year,
        structures=command.sections,
        actor=actor,
        command_kind=command.command_kind,
        copied_slots=initial_slots,
    )


def create_edition_snapshot(
    session: Session,
    *,
    product: DeliverableRecord,
    edition_label: str,
    academic_year: int | None,
    structures: tuple[ContentSectionStructure, ...],
    actor: ActorContext,
    command_kind: str,
    copied_slots: dict[str, tuple[CuratedSlot, ...]] | None = None,
    copied_from_revision_id: str | None = None,
) -> tuple[ContentEditionRecord, ContentEditionCompositionV1]:
    now = datetime.now(UTC)
    edition_id = new_content_id("edition")
    edition = ContentEditionRecord(
        edition_id=edition_id,
        deliverable_id=product.deliverable_id,
        edition_key=edition_id,
        lifecycle_state="ACTIVE",
        lock_version=1,
        created_by=actor.actor_id,
        created_at=now,
    )
    session.add(edition)
    session.flush()
    composition = _commit_composition(
        session,
        edition=edition,
        product=product,
        previous=None,
        structures=structures,
        changed_slots=copied_slots or {},
        existing_manifests={},
        edition_label=edition_label,
        academic_year=academic_year,
        actor=actor,
        now=now,
        command_kind=command_kind,
        summary={
            "copied_from_revision_id": copied_from_revision_id,
            "section_count": len(structures),
        },
    )
    return edition, composition


def save_edition_snapshot(
    session: Session,
    *,
    edition: ContentEditionRecord,
    product: DeliverableRecord,
    current: ContentEditionCompositionV1,
    edit: SaveContentSections | SaveContentStructure,
    actor: ActorContext,
) -> ContentEditionCompositionV1:
    if (
        edit.expected_revision_id != current.deliverable_revision_id
        or edit.expected_sha256 != current.composition_sha256
    ):
        raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
    structures = tuple(
        ContentSectionStructure.model_validate(section.model_dump(exclude={"form"}))
        for section in current.sections
    )
    current_sections = {section.section_id: section for section in current.sections}
    if isinstance(edit, SaveContentStructure):
        retained = {section.section_id for section in edit.sections}
        removed = set(current_sections) - retained
        # Explicit confirmation prevents deleting a populated subtree accidentally.
        if set(edit.confirmed_removed_sections) != removed:
            raise ContentPlanningError("CONTENT_SECTION_REMOVAL_CONFIRMATION_REQUIRED")
        if any(
            section.section_id in current_sections
            and section.kind != current_sections[section.section_id].kind
            for section in edit.sections
        ):
            raise ContentPlanningError("CONTENT_SECTION_KIND_IMMUTABLE")
        if (
            structures == edit.sections
            and current.edition_label == edit.edition_label
            and current.academic_year == edit.academic_year
        ):
            return current
        changed_leaves = tuple(
            current_sections[section.section_id].form
            for section in edit.sections
            if section.kind == "FORM"
            and section.section_id in current_sections
            and (
                section.label != current_sections[section.section_id].label
                or section.ordinal != current_sections[section.section_id].ordinal
            )
        )
        manifests = read_curated_slot_revisions(
            session, tuple(pointer for pointer in changed_leaves if pointer is not None)
        )
        return _commit_composition(
            session,
            edition=edition,
            product=product,
            previous=current,
            structures=edit.sections,
            changed_slots={},
            existing_manifests=manifests,
            edition_label=edit.edition_label,
            academic_year=edit.academic_year,
            actor=actor,
            now=datetime.now(UTC),
            command_kind="SAVE_STRUCTURE",
            summary={"removed_sections": sorted(removed), "section_count": len(edit.sections)},
        )
    requested = {change.section_id for change in edit.changes}
    if not requested <= current_sections.keys() or any(
        current_sections[key].form is None for key in requested
    ):
        raise ContentPlanningError("CONTENT_SECTION_NOT_FOUND")
    pointers = tuple(
        section.form
        for section in current.sections
        if section.section_id in requested and section.form is not None
    )
    manifests = read_curated_slot_revisions(session, pointers)
    before = {}
    for section in current.sections:
        if section.section_id not in requested:
            continue
        assert section.form is not None
        manifest = manifests[section.form.assembly_revision_id]
        before[section.section_id] = SectionSlotState(
            section.section_id,
            manifest.assembly_revision_id,
            manifest.manifest_sha256,
            tuple(slot.selection() for slot in manifest.placements),
        )
    submitted_ids = tuple(
        slot.placement_id for change in edit.changes for slot in change.placements
    )
    slots = CuratedDocumentAssemblySlotRecord
    forms = ContentFormRevisionCompositionRecord
    leaves = ContentEditionRevisionFormRecord
    owner_rows = (
        session.execute(
            select(slots.placement_id, leaves.section_id)
            .join(forms, forms.assembly_revision_id == slots.assembly_revision_id)
            .join(leaves, leaves.assessment_form_revision_id == forms.assessment_form_revision_id)
            .where(
                leaves.deliverable_revision_id == current.deliverable_revision_id,
                slots.placement_id.in_(submitted_ids),
            )
        ).all()
        if submitted_ids
        else []
    )
    owners = {placement_id: section_id for placement_id, section_id in owner_rows}
    if len(owners) != len(owner_rows):
        raise ContentPlanningError("CONTENT_PLACEMENT_INTEGRITY_INVALID")
    delta = plan_slot_changes(before, edit.changes, owners)
    if delta.is_no_change:
        return current
    # A retained occurrence's provenance cannot be rewritten by a client.
    old_by_id = {slot.placement_id: slot for state in before.values() for slot in state.placements}
    for change in edit.changes:
        for slot in change.placements:
            old = old_by_id.get(slot.placement_id)
            if old is not None and old.copied_from != slot.copied_from:
                raise ContentPlanningError("CONTENT_COPY_ORIGIN_IMMUTABLE")

    validate_slot_origins(
        session,
        tuple(
            slot
            for change in edit.changes
            for slot in change.placements
            if slot.placement_id not in old_by_id
        ),
        actor,
    )
    return _commit_composition(
        session,
        edition=edition,
        product=product,
        previous=current,
        structures=structures,
        changed_slots={change.section_id: change.placements for change in delta.changed_sections},
        existing_manifests=manifests,
        edition_label=current.edition_label,
        academic_year=current.academic_year,
        actor=actor,
        now=datetime.now(UTC),
        command_kind="SAVE_SECTIONS",
        summary={
            "sections": [change.section_id for change in delta.changed_sections],
            "added": len(delta.added),
            "removed": len(delta.removed),
            "moved": len(delta.moved),
            "replaced": len(delta.replaced),
        },
    )


def _commit_composition(
    session: Session,
    *,
    edition: ContentEditionRecord,
    product: DeliverableRecord,
    previous: ContentEditionCompositionV1 | None,
    structures: tuple[ContentSectionStructure, ...],
    changed_slots: dict[str, tuple[CuratedSlot, ...]],
    existing_manifests: dict[str, CuratedDocumentAssemblyManifestV2],
    edition_label: str,
    academic_year: int | None,
    actor: ActorContext,
    now: datetime,
    command_kind: str,
    summary: dict[str, object],
) -> ContentEditionCompositionV1:
    old = {} if previous is None else {section.section_id: section for section in previous.sections}
    revision_id = new_content_id("delivrev")
    # One resolution pass for the complete edit, so duplicate targets are resolved once.
    all_changed = tuple(slot for slots in changed_slots.values() for slot in slots)
    resolved = resolve_curated_slots(session, all_changed, actor)
    resolved_by_id = {slot.placement_id: slot for slot in resolved}
    writes = []
    assemblies: dict[str, str] = {}
    for section in structures:
        if section.kind != "FORM":
            continue
        prior = old.get(section.section_id)
        if prior is not None and section.section_id not in changed_slots:
            assert prior.form is not None
            assemblies[section.section_id] = prior.form.assembly_id
            continue
        previous_manifest = (
            None
            if prior is None or prior.form is None
            else existing_manifests[prior.form.assembly_revision_id]
        )
        assembly_id = (
            new_content_id("assembly")
            if previous_manifest is None
            else previous_manifest.assembly_id
        )
        placements: tuple[ResolvedCuratedSlot, ...] = tuple(
            resolved_by_id[slot.placement_id] for slot in changed_slots.get(section.section_id, ())
        )
        writes.append(
            CuratedSlotRevisionWrite(
                assembly_id,
                new_content_id("assemblyrev"),
                previous_manifest,
                section.label,
                placements,
            )
        )
        assemblies[section.section_id] = assembly_id
    appended = append_curated_slot_revisions(
        session, tuple(writes), actor_id=actor.actor_id, created_at=now
    )
    need_forms = [
        section
        for section in structures
        if section.kind == "FORM"
        and (
            section.section_id not in old
            or section.section_id in changed_slots
            or section.label != old[section.section_id].label
            or section.ordinal != old[section.section_id].ordinal
        )
    ]
    prior_ids = tuple(
        pointer.form_revision_id
        for section in need_forms
        if section.section_id in old and (pointer := old[section.section_id].form) is not None
    )
    prior_rows = (
        {
            row.assessment_form_revision_id: row
            for row in session.scalars(
                select(AssessmentFormRevisionRecord).where(
                    AssessmentFormRevisionRecord.assessment_form_revision_id.in_(prior_ids)
                )
            )
        }
        if prior_ids
        else {}
    )
    plans = {}
    for section in need_forms:
        prior_section = old.get(section.section_id)
        prior_pointer = None if prior_section is None else prior_section.form
        manifest = appended.get(assemblies[section.section_id])
        if manifest is None:
            assert prior_pointer is not None
            manifest = existing_manifests[prior_pointer.assembly_revision_id]
        plans[section.section_id] = plan_form_revision(
            edition=edition,
            edition_revision_id=revision_id,
            section=section,
            assembly=manifest,
            previous=prior_pointer,
            prior=None if prior_pointer is None else prior_rows.get(prior_pointer.form_revision_id),
            actor_id=actor.actor_id,
            created_at=now,
        )
    sections = tuple(
        ContentSection(
            **section.model_dump(),
            form=None
            if section.kind == "GROUP"
            else (
                plans[section.section_id].pointer
                if section.section_id in plans
                else old[section.section_id].form
            ),
        )
        for section in structures
    )
    value = {
        "schema_version": "content-edition-composition/1.0",
        "deliverable_id": product.deliverable_id,
        "edition_id": edition.edition_id,
        "deliverable_revision_id": revision_id,
        "revision_number": 1 if previous is None else previous.revision_number + 1,
        "previous_revision_id": None if previous is None else previous.deliverable_revision_id,
        "content_title": product.title,
        "content_type": product.deliverable_type,
        "edition_label": edition_label,
        "academic_year": academic_year,
        "sections": [section.model_dump(mode="json") for section in sections],
        "created_by": actor.actor_id,
        "created_at": now.isoformat().replace("+00:00", "Z"),
    }
    value["composition_sha256"] = content_sha256(value)
    composition = ContentEditionCompositionV1.model_validate(value)
    store_edition_revision(
        session,
        edition=edition,
        composition=composition,
        forms=tuple(plans.values()),
        command_kind=command_kind,
        change_summary=summary,
    )
    return composition
