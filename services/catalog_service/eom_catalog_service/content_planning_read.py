"""Bounded Catalog read projections over the canonical content revision indexes."""

from __future__ import annotations

from eom_catalog_contracts.content_delivery import ReadContentDeliveries
from eom_catalog_contracts.content_planning_queries import (
    ContentEditionEntry,
    ContentEditionList,
    ContentEditionView,
    ContentHistoryEntry,
    ContentHistoryPage,
    ContentPlanningQuery,
    ContentPlanningQueryResult,
    ContentSectionPage,
    ContentSlotLabel,
    ListContentEditions,
    ListPlannedContents,
    PlannedContentEntry,
    PlannedContentList,
    ReadContentEdition,
    ReadContentHistory,
    ReadContentSection,
)
from eom_catalog_contracts.content_print_views import ReadContentPrints
from eom_catalog_contracts.content_usage import (
    ReadContentUsage,
    ReadContentUsageSummary,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.curated_document_slots import (
    RegisteredSlotTarget,
    ResolvedCuratedSlot,
    ResolvedExternalSlotTarget,
)
from eom_catalog_contracts.validation import validate_contract
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eom_catalog_service.content_delivery_read import read_content_deliveries
from eom_catalog_service.content_planning_access import (
    ContentPlanningError,
    authorize_content_planning,
)
from eom_catalog_service.content_planning_models import (
    ContentEditionRecord,
    ContentPlanningEventRecord,
)
from eom_catalog_service.content_planning_storage import load_content_edition, read_edition_revision
from eom_catalog_service.content_print_records import read_content_prints
from eom_catalog_service.content_prior_usage_read import read_prior_content_usage
from eom_catalog_service.content_usage_read import read_content_usage, read_content_usage_summary
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.curated_document_slot_store import read_curated_slot_revisions
from eom_catalog_service.models import (
    ContentIntakeSourceFileRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemRevisionRecord,
)


def query_content_planning(
    session: Session, query: ContentPlanningQuery, actor: ActorContext
) -> ContentPlanningQueryResult:
    authorized = authorize_content_planning(session, actor, PermissionKey.DELIVERABLE_READ)
    match query:
        case ListPlannedContents():
            result: ContentPlanningQueryResult = _contents(session, query)
        case ListContentEditions():
            result = _editions(session, query)
        case ReadContentEdition():
            edition = load_content_edition(
                session, query.edition_id, include_archived=query.revision_id is not None
            )
            revision_id = query.revision_id or edition.current_revision_id
            if revision_id is None or edition.current_revision_id is None:
                raise ContentPlanningError("CONTENT_REVISION_NOT_FOUND")
            result = ContentEditionView(
                composition=read_edition_revision(session, edition, revision_id),
                current_revision_id=edition.current_revision_id,
            )
        case ReadContentSection():
            result = _section(session, query, authorized)
        case ReadContentHistory():
            load_content_edition(session, query.edition_id, include_archived=True)
            result = _history(session, query)
        case ReadContentPrints():
            result = read_content_prints(session, query)
        case ReadContentUsage():
            result = read_content_usage(session, query, authorized)
        case ReadContentUsageSummary():
            result = read_content_usage_summary(session, query, authorized)
        case ReadPriorContentUsage():
            result = read_prior_content_usage(session, query, authorized)
        case ReadContentDeliveries():
            result = read_content_deliveries(session, query)
    validate_contract("content-planning-query-result-v1", result.model_dump(mode="json"))
    return result


def _contents(session: Session, query: ListPlannedContents) -> PlannedContentList:
    product, edition = DeliverableRecord, ContentEditionRecord
    statement = (
        select(
            product.deliverable_id,
            product.title,
            product.deliverable_type,
            func.count(edition.edition_id),
        )
        .join(edition, edition.deliverable_id == product.deliverable_id)
        .where(
            edition.lifecycle_state == "ACTIVE",
            product.lifecycle_state.not_in(("CANCELLED", "ARCHIVED")),
        )
        .group_by(product.deliverable_id)
        .order_by(product.deliverable_id)
        .limit(query.limit + 1)
    )
    if query.after_id:
        statement = statement.where(product.deliverable_id > query.after_id)
    if query.text.strip():
        statement = statement.where(product.title.icontains(query.text.strip(), autoescape=True))
    rows = session.execute(statement).all()
    return PlannedContentList(
        rows=tuple(
            PlannedContentEntry(
                deliverable_id=key,
                title=title,
                content_type=kind,
                edition_count=count,
            )
            for key, title, kind, count in rows[: query.limit]
        ),
        next_id=rows[query.limit - 1][0] if len(rows) > query.limit else None,
    )


def _editions(session: Session, query: ListContentEditions) -> ContentEditionList:
    edition, revision = ContentEditionRecord, DeliverableRevisionRecord
    statement = (
        select(
            edition.edition_id,
            edition.deliverable_id,
            revision.deliverable_revision_id,
            revision.metadata_json["composition_sha256"].as_string(),
            revision.metadata_json["edition_label"].as_string(),
            revision.metadata_json["academic_year"].as_integer(),
            func.jsonb_array_length(revision.metadata_json["sections"]),
        )
        .join(revision, revision.deliverable_revision_id == edition.current_revision_id)
        .join(DeliverableRecord, DeliverableRecord.deliverable_id == edition.deliverable_id)
        .where(
            edition.deliverable_id == query.deliverable_id,
            edition.lifecycle_state == "ACTIVE",
            DeliverableRecord.lifecycle_state.not_in(("CANCELLED", "ARCHIVED")),
        )
        .order_by(edition.edition_id)
        .limit(query.limit + 1)
    )
    if query.after_id:
        statement = statement.where(edition.edition_id > query.after_id)
    rows = session.execute(statement).all()
    return ContentEditionList(
        rows=tuple(
            ContentEditionEntry(
                edition_id=key,
                deliverable_id=product,
                revision_id=revision_id,
                composition_sha256=digest,
                edition_label=label,
                academic_year=year,
                section_count=count,
            )
            for key, product, revision_id, digest, label, year, count in rows[: query.limit]
        ),
        next_id=rows[query.limit - 1][0] if len(rows) > query.limit else None,
    )


def _section(
    session: Session, query: ReadContentSection, actor: ActorContext
) -> ContentSectionPage:
    edition = load_content_edition(session, query.edition_id, include_archived=True)
    composition = read_edition_revision(session, edition, query.revision_id)
    if composition.composition_sha256 != query.composition_sha256:
        raise ContentPlanningError("CONTENT_EDITION_REVISION_STALE")
    section = next(
        (row for row in composition.sections if row.section_id == query.section_id), None
    )
    if section is None or section.form is None:
        raise ContentPlanningError("CONTENT_SECTION_NOT_FOUND")
    manifest = read_curated_slot_revisions(session, (section.form,))[
        section.form.assembly_revision_id
    ]
    page = manifest.placements[query.after_position : query.after_position + query.limit]
    if resolve_curated_slots(session, tuple(slot.selection() for slot in page), actor) != page:
        raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
    next_position = (
        page[-1].position if page and page[-1].position < len(manifest.placements) else None
    )
    return ContentSectionPage(
        edition_id=query.edition_id,
        revision_id=query.revision_id,
        composition_sha256=query.composition_sha256,
        section_id=query.section_id,
        form=section.form,
        rows=page,
        labels=_slot_labels(session, page),
        next_position=next_position,
        total=len(manifest.placements),
    )


def _slot_labels(
    session: Session, slots: tuple[ResolvedCuratedSlot, ...]
) -> tuple[ContentSlotLabel, ...]:
    """At most two indexed metadata reads per page after pointer authorization."""
    item_ids = {
        row.target.item_revision_id for row in slots if isinstance(row.target, RegisteredSlotTarget)
    }
    file_ids = {
        row.target.source_file_id
        for row in slots
        if isinstance(row.target, ResolvedExternalSlotTarget)
    }
    items: dict[str, dict[str, object]] = (
        {
            key: metadata
            for key, metadata in session.execute(
                select(ItemRevisionRecord.item_revision_id, ItemRevisionRecord.metadata_json).where(
                    ItemRevisionRecord.item_revision_id.in_(item_ids)
                )
            ).all()
        }
        if item_ids
        else {}
    )
    files: dict[str, str] = (
        {
            key: filename
            for key, filename in session.execute(
                select(
                    ContentIntakeSourceFileRecord.source_file_id,
                    ContentIntakeSourceFileRecord.original_filename,
                ).where(ContentIntakeSourceFileRecord.source_file_id.in_(file_ids))
            ).all()
        }
        if file_ids
        else {}
    )
    labels = []
    for row in slots:
        target, title, number = row.target, "빈 자리", None
        if isinstance(target, ResolvedExternalSlotTarget):
            number = target.external_number
            filename = files.get(target.source_file_id)
            if filename is None:
                raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
            title = f"{number} · {filename}"
        elif isinstance(target, RegisteredSlotTarget):
            metadata = items.get(target.item_revision_id)
            if metadata is None:
                raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
            candidate = metadata.get("external_number")
            if (
                isinstance(candidate, str)
                and len(candidate) == 5
                and candidate.isascii()
                and candidate.isdigit()
            ):
                number = candidate
            candidate = metadata.get("title")
            title = (
                candidate.strip()
                if isinstance(candidate, str) and candidate.strip()
                else (
                    f"고유번호 {number}"
                    if number
                    else "기출 문항"
                    if target.placement_kind == "PAST_EXAM_ITEM_REVISION"
                    else "등록 문항"
                )
            )
        labels.append(
            ContentSlotLabel(
                placement_id=row.placement_id, title=title[:512], external_number=number
            )
        )
    return tuple(labels)


def _history(session: Session, query: ReadContentHistory) -> ContentHistoryPage:
    model = ContentPlanningEventRecord
    statement = (
        select(model)
        .where(model.edition_id == query.edition_id)
        .order_by(model.sequence.desc())
        .limit(query.limit + 1)
    )
    if query.before_sequence is not None:
        statement = statement.where(model.sequence < query.before_sequence)
    rows = session.scalars(statement).all()
    return ContentHistoryPage(
        edition_id=query.edition_id,
        rows=tuple(
            ContentHistoryEntry(
                sequence=row.sequence,
                command_kind=row.command_kind,
                before_revision_id=row.before_revision_id,
                after_revision_id=row.after_revision_id,
                created_by=row.actor_id,
                created_at=row.created_at,
            )
            for row in rows[: query.limit]
        ),
        next_sequence=rows[query.limit - 1].sequence if len(rows) > query.limit else None,
    )
