"""Shared SQL current/printed occurrence projection; no mutable usage cache."""

from typing import Any

from sqlalchemy import ColumnElement, Select, String, and_, cast, func, literal, select, union_all
from sqlalchemy.sql import Subquery

from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentEditionRevisionFormRecord,
    ContentEditionRevisionRecord,
    ContentFormRevisionCompositionRecord,
)
from eom_catalog_service.content_print_models import (
    ContentPrintEventRecord,
    ContentPrintRecord,
    ContentPrintScopeRecord,
)
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord
from eom_catalog_service.legacy_usage_models import AssessmentFormRevisionRecord
from eom_catalog_service.models import DeliverableRevisionRecord


def content_usage_rows(
    target_condition: ColumnElement[bool], academic_year: int | str | None
) -> Subquery:
    s, f = CuratedDocumentAssemblySlotRecord, ContentFormRevisionCompositionRecord
    leaf, edition, revision = (
        ContentEditionRevisionFormRecord,
        ContentEditionRecord,
        ContentEditionRevisionRecord,
    )
    p, ps, pe = ContentPrintRecord, ContentPrintScopeRecord, ContentPrintEventRecord
    d, form = DeliverableRevisionRecord, AssessmentFormRevisionRecord
    columns = (
        s.item_id.label("item_id"),
        s.source_id.label("source_id"),
        f.edition_id.label("edition_id"),
        func.coalesce(revision.academic_year, 0).label("year_key"),
        f.assessment_form_id.label("form_id"),
        s.placement_id.label("placement_id"),
        s.canonical_slot["target"].label("target"),
        revision.academic_year.label("academic_year"),
        revision.deliverable_id.label("deliverable_id"),
        revision.deliverable_revision_id.label("revision_id"),
        d.metadata_json["content_title"].as_string().label("content_title"),
        d.metadata_json["edition_label"].as_string().label("edition_label"),
        f.section_id.label("section_id"),
        form.display_label.label("section_label"),
        s.position.label("position"),
        s.canonical_slot.label("slot"),
    )

    def base(*extra: ColumnElement[Any]) -> Select[tuple[Any, ...]]:
        return (
            select(*columns, *extra)
            .select_from(s)
            .join(f, f.assembly_revision_id == s.assembly_revision_id)
            .join(form, form.assessment_form_revision_id == f.assessment_form_revision_id)
            .where(target_condition)
        )

    current = (
        base(
            literal(1).label("is_current"),
            cast(literal(None), String).label("print_id"),
            d.created_at.label("recorded_at"),
        )
        .join(
            leaf,
            and_(
                leaf.assessment_form_revision_id == f.assessment_form_revision_id,
                leaf.edition_id == f.edition_id,
            ),
        )
        .join(
            edition,
            and_(
                edition.edition_id == leaf.edition_id,
                edition.current_revision_id == leaf.deliverable_revision_id,
            ),
        )
        .join(revision, revision.deliverable_revision_id == leaf.deliverable_revision_id)
        .join(d, d.deliverable_revision_id == revision.deliverable_revision_id)
    )
    printed = (
        base(
            literal(0).label("is_current"),
            p.print_record_id.label("print_id"),
            p.recorded_at.label("recorded_at"),
        )
        .join(ps, ps.assessment_form_revision_id == f.assessment_form_revision_id)
        .join(p, p.print_record_id == ps.print_record_id)
        .join(revision, revision.deliverable_revision_id == p.deliverable_revision_id)
        .join(d, d.deliverable_revision_id == revision.deliverable_revision_id)
        .where(~select(pe.print_record_id).where(pe.print_record_id == p.print_record_id).exists())
    )
    if academic_year != "ALL":
        current = current.where(revision.academic_year == academic_year)
        printed = printed.where(revision.academic_year == academic_year)
    return union_all(current, printed).subquery("content_uses")
