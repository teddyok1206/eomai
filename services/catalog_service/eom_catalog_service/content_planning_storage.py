"""Catalog-owned Edition/Form snapshots; all writes use the caller's transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from eom_catalog_contracts.content_planning import (
    ContentEditionCompositionV1,
    ContentFormPointer,
    ContentSectionStructure,
)
from eom_catalog_contracts.curated_document_slots import CuratedDocumentAssemblyManifestV2
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import content_sha256
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_planning_models import (
    CONTENT_PRODUCT_REVISION_SEQUENCE,
    ContentEditionRecord,
    ContentEditionRevisionFormRecord,
    ContentEditionRevisionRecord,
    ContentFormMembershipRecord,
    ContentFormRevisionCompositionRecord,
    ContentPlanningEventRecord,
)
from eom_catalog_service.legacy_usage_models import (
    AssessmentFormRecord,
    AssessmentFormRevisionRecord,
)
from eom_catalog_service.models import DeliverableRecord, DeliverableRevisionRecord


def new_content_id(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


def load_content_edition(
    session: Session, edition_id: str, *, for_update: bool = False
) -> ContentEditionRecord:
    statement = (
        select(ContentEditionRecord)
        .join(
            DeliverableRecord,
            DeliverableRecord.deliverable_id == ContentEditionRecord.deliverable_id,
        )
        .where(
            ContentEditionRecord.edition_id == edition_id,
            DeliverableRecord.lifecycle_state.not_in(("CANCELLED", "ARCHIVED")),
        )
    )
    if for_update:
        statement = statement.with_for_update(of=ContentEditionRecord)
    edition = session.scalar(statement)
    if edition is None or edition.lifecycle_state != "ACTIVE":
        raise ContentPlanningError("CONTENT_EDITION_NOT_FOUND")
    return edition


def _form_hash(
    row: AssessmentFormRevisionRecord, detail: ContentFormRevisionCompositionRecord
) -> str:
    """Hash of the canonical small Form value, not an independently stored copy."""
    return content_sha256(
        {
            "form_id": row.assessment_form_id,
            "form_revision_id": row.assessment_form_revision_id,
            "revision_number": row.revision_number,
            "previous_revision_id": row.previous_revision_id,
            "deliverable_revision_id": row.deliverable_revision_id,
            "edition_id": detail.edition_id,
            "section_id": detail.section_id,
            "ordinal": row.ordinal,
            "label": row.display_label,
            "assembly_id": detail.assembly_id,
            "assembly_revision_id": detail.assembly_revision_id,
            "manifest_sha256": detail.manifest_sha256,
            "placement_count": detail.placement_count,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat().replace("+00:00", "Z"),
        }
    )


@dataclass(frozen=True)
class PlannedFormRevision:
    row: AssessmentFormRevisionRecord
    detail: ContentFormRevisionCompositionRecord
    pointer: ContentFormPointer
    is_new: bool


def plan_form_revision(
    *,
    edition: ContentEditionRecord,
    edition_revision_id: str,
    section: ContentSectionStructure,
    assembly: CuratedDocumentAssemblyManifestV2,
    previous: ContentFormPointer | None,
    prior: AssessmentFormRevisionRecord | None,
    actor_id: str,
    created_at: datetime,
) -> PlannedFormRevision:
    if previous is not None and (prior is None or prior.revision_sha256 != previous.form_sha256):
        raise ContentPlanningError("CONTENT_FORM_POINTER_INVALID")
    form_id = new_content_id("form") if previous is None else previous.form_id
    row = AssessmentFormRevisionRecord(
        assessment_form_id=form_id,
        assessment_form_revision_id=new_content_id("formrev"),
        revision_number=1 if prior is None else prior.revision_number + 1,
        previous_revision_id=None if prior is None else prior.assessment_form_revision_id,
        deliverable_revision_id=edition_revision_id,
        ordinal=section.ordinal,
        display_label=section.label,
        assessment_assembly_revision_id=None,
        revision_state="DRAFT",
        created_by=actor_id,
        created_at=created_at,
    )
    detail = ContentFormRevisionCompositionRecord(
        assessment_form_id=form_id,
        assessment_form_revision_id=row.assessment_form_revision_id,
        edition_id=edition.edition_id,
        section_id=section.section_id,
        assembly_id=assembly.assembly_id,
        assembly_revision_id=assembly.assembly_revision_id,
        manifest_sha256=assembly.manifest_sha256,
        placement_count=len(assembly.placements),
    )
    row.revision_sha256 = _form_hash(row, detail)
    pointer = ContentFormPointer(
        form_id=form_id,
        form_revision_id=row.assessment_form_revision_id,
        form_sha256=row.revision_sha256,
        assembly_id=assembly.assembly_id,
        assembly_revision_id=assembly.assembly_revision_id,
        manifest_sha256=assembly.manifest_sha256,
        placement_count=len(assembly.placements),
    )
    return PlannedFormRevision(row, detail, pointer, previous is None)


def store_edition_revision(
    session: Session,
    *,
    edition: ContentEditionRecord,
    composition: ContentEditionCompositionV1,
    forms: tuple[PlannedFormRevision, ...],
    command_kind: str,
    change_summary: dict[str, object],
) -> None:
    """Parent first, then detail and exact leaf index, then the one mutable head."""
    value = composition.model_dump(mode="json")
    validate_contract("content-edition-composition-v1", value)
    session.add(
        DeliverableRevisionRecord(
            deliverable_revision_id=composition.deliverable_revision_id,
            deliverable_id=edition.deliverable_id,
            revision_number=session.scalar(select(CONTENT_PRODUCT_REVISION_SEQUENCE.next_value())),
            state="DRAFT",
            metadata_json=value,
            metadata_sha256=content_sha256(value),
            created_at=composition.created_at,
        )
    )
    session.flush()
    session.add(
        ContentEditionRevisionRecord(
            deliverable_revision_id=composition.deliverable_revision_id,
            deliverable_id=edition.deliverable_id,
            edition_id=edition.edition_id,
            revision_number=composition.revision_number,
            previous_revision_id=composition.previous_revision_id,
            academic_year=composition.academic_year,
            composition_sha256=composition.composition_sha256,
        )
    )
    session.flush()
    for form in forms:
        if form.is_new:
            session.add(
                AssessmentFormRecord(
                    assessment_form_id=form.pointer.form_id,
                    deliverable_id=edition.deliverable_id,
                    form_key=form.pointer.form_id,
                    lifecycle_state="ACTIVE",
                    created_by=composition.created_by,
                    created_at=composition.created_at,
                )
            )
    session.flush()
    for form in forms:
        if form.is_new:
            session.add(
                ContentFormMembershipRecord(
                    assessment_form_id=form.pointer.form_id,
                    deliverable_id=edition.deliverable_id,
                    edition_id=edition.edition_id,
                    assembly_id=form.pointer.assembly_id,
                )
            )
        session.add(form.row)
    session.flush()
    session.add_all(form.detail for form in forms)
    session.flush()
    # Head updates are batched after the immutable revisions exist.
    if forms:
        aggregates = {
            row.assessment_form_id: row
            for row in session.scalars(
                select(AssessmentFormRecord).where(
                    AssessmentFormRecord.assessment_form_id.in_(
                        tuple(form.pointer.form_id for form in forms)
                    )
                )
            )
        }
        for form in forms:
            aggregates[form.pointer.form_id].current_revision_id = form.pointer.form_revision_id
    leaves = [section for section in composition.sections if section.form is not None]
    for order, section in enumerate(leaves, 1):
        assert section.form is not None
        session.add(
            ContentEditionRevisionFormRecord(
                deliverable_revision_id=composition.deliverable_revision_id,
                edition_id=edition.edition_id,
                section_id=section.section_id,
                assessment_form_revision_id=section.form.form_revision_id,
                leaf_order=order,
            )
        )
    session.add(
        ContentPlanningEventRecord(
            edition_id=edition.edition_id,
            sequence=composition.revision_number,
            command_kind=command_kind,
            before_revision_id=composition.previous_revision_id,
            after_revision_id=composition.deliverable_revision_id,
            change_summary=change_summary,
            actor_id=composition.created_by,
            created_at=composition.created_at,
        )
    )
    session.flush()
    edition.current_revision_id = composition.deliverable_revision_id
    edition.lock_version += 1
    session.flush()


def read_edition_revision(
    session: Session, edition: ContentEditionRecord, revision_id: str
) -> ContentEditionCompositionV1:
    record = session.get(DeliverableRevisionRecord, revision_id)
    detail = session.get(ContentEditionRevisionRecord, revision_id)
    if record is None or detail is None or detail.edition_id != edition.edition_id:
        raise ContentPlanningError("CONTENT_REVISION_NOT_FOUND")
    try:
        composition = ContentEditionCompositionV1.model_validate(record.metadata_json)
    except ValueError as exc:
        raise ContentPlanningError("CONTENT_REVISION_POINTER_INVALID") from exc
    if (
        record.deliverable_id != edition.deliverable_id
        or detail.deliverable_id != edition.deliverable_id
        or composition.deliverable_revision_id != revision_id
        or composition.deliverable_id != edition.deliverable_id
        or composition.edition_id != edition.edition_id
        or composition.composition_sha256 != detail.composition_sha256
        or composition.revision_number != detail.revision_number
        or composition.previous_revision_id != detail.previous_revision_id
        or composition.academic_year != detail.academic_year
        or record.metadata_sha256 != content_sha256(record.metadata_json)
    ):
        raise ContentPlanningError("CONTENT_REVISION_POINTER_INVALID")
    leaves = [section for section in composition.sections if section.form is not None]
    index = session.scalars(
        select(ContentEditionRevisionFormRecord)
        .where(ContentEditionRevisionFormRecord.deliverable_revision_id == revision_id)
        .order_by(ContentEditionRevisionFormRecord.leaf_order)
    ).all()
    if len(index) != len(leaves):
        raise ContentPlanningError("CONTENT_SECTION_INDEX_INVALID")
    for order, (section, row) in enumerate(zip(leaves, index, strict=True), 1):
        assert section.form is not None
        if (
            row.edition_id != edition.edition_id
            or row.section_id != section.section_id
            or row.assessment_form_revision_id != section.form.form_revision_id
            or row.leaf_order != order
        ):
            raise ContentPlanningError("CONTENT_SECTION_INDEX_INVALID")
    if leaves:
        by_id = {section.form.form_revision_id: section for section in leaves if section.form}
        rows = session.execute(
            select(AssessmentFormRevisionRecord, ContentFormRevisionCompositionRecord)
            .join(
                ContentFormRevisionCompositionRecord,
                ContentFormRevisionCompositionRecord.assessment_form_revision_id
                == AssessmentFormRevisionRecord.assessment_form_revision_id,
            )
            .where(AssessmentFormRevisionRecord.assessment_form_revision_id.in_(tuple(by_id)))
        ).all()
        if len(rows) != len(by_id):
            raise ContentPlanningError("CONTENT_FORM_POINTER_INVALID")
        for form, binding in rows:
            section = by_id[form.assessment_form_revision_id]
            pointer = section.form
            assert pointer is not None
            if (
                binding.edition_id != edition.edition_id
                or binding.section_id != section.section_id
                or binding.assessment_form_id != pointer.form_id
                or form.assessment_form_id != pointer.form_id
                or form.revision_sha256 != pointer.form_sha256
                or form.revision_sha256 != _form_hash(form, binding)
                or binding.assembly_id != pointer.assembly_id
                or binding.assembly_revision_id != pointer.assembly_revision_id
                or binding.manifest_sha256 != pointer.manifest_sha256
                or binding.placement_count != pointer.placement_count
                or form.display_label != section.label
                or form.ordinal != section.ordinal
            ):
                raise ContentPlanningError("CONTENT_FORM_POINTER_INVALID")
    return composition
