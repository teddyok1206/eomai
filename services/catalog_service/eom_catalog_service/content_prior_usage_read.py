"""Read old usage ledgers without inventing an academic year or a Graph pin.

Two indexed Item membership queries, a bounded UNION/keyset page and one batched
revision lookup. Historical rows remain in their owning ledgers, not copied into
the new print log. The caller supplies freshly authorized operator permissions.
"""

from eom_catalog_contracts.content_usage import (
    PriorUsageCursor,
    PriorUsageLocation,
    PriorUsagePage,
    ReadPriorContentUsage,
)
from eom_catalog_contracts.curated_document_slots import CuratedSlot
from eom_catalog_contracts.item_origin import OriginItemRevisionPointer
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import String, literal, select, tuple_, union_all
from sqlalchemy.orm import Session

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_usage_identity import content_usage_identity_matches
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots
from eom_catalog_service.legacy_usage_models import UsageRecordV1Record
from eom_catalog_service.models import (
    DeliverableRecord,
    ItemRecord,
    ItemRevisionRecord,
    UsageRecord,
)


def read_prior_content_usage(
    session: Session, query: ReadPriorContentUsage, actor: ActorContext
) -> PriorUsagePage:
    if PermissionKey.USAGE_READ not in actor.permissions:
        raise ContentPlanningError("CONTENT_PLANNING_PERMISSION_DENIED")
    resolve_curated_slots(
        session,
        tuple(
            CuratedSlot(
                placement_id=f"placement_{i:032x}",
                position=i + 1,
                target=target,
                points_milli=None,
                display_number=None,
                note="",
                copied_from=None,
            )
            for i, target in enumerate(query.targets)
        ),
        actor,
    )
    identities = content_usage_identity_matches(session, query.targets, actor)
    item_ids = [value for kind, value in identities if kind == "ITEM"]
    parts = []
    for ledger, model, section, position, publication in (
        (
            "USAGE",
            UsageRecord,
            UsageRecord.section,
            UsageRecord.sequence,
            literal(None, type_=String),
        ),
        (
            "LEGACY_USAGE_V1",
            UsageRecordV1Record,
            UsageRecordV1Record.section_key,
            UsageRecordV1Record.position,
            UsageRecordV1Record.publication_revision_id,
        ),
    ):
        parts.append(
            select(
                literal(ledger).label("ledger"),
                model.usage_record_id,
                model.deliverable_id,
                model.deliverable_revision_id,
                DeliverableRecord.title,
                section.label("section"),
                position.label("position"),
                model.item_id,
                model.item_revision_id,
                model.recorded_at,
                publication.label("publication_revision_id"),
            )
            .join(DeliverableRecord, DeliverableRecord.deliverable_id == model.deliverable_id)
            .join(ItemRevisionRecord, ItemRevisionRecord.item_revision_id == model.item_revision_id)
            .where(ItemRevisionRecord.item_id.in_(item_ids))
        )
    uses = union_all(*parts).subquery("prior_usage")
    order = (uses.c.ledger, uses.c.usage_record_id)
    statement = select(uses).order_by(*order).limit(query.limit + 1)
    if query.after is not None:
        statement = statement.where(
            tuple_(*order)
            > tuple_(literal(query.after.ledger), literal(query.after.usage_record_id))
        )
    found = session.execute(statement).mappings().all()
    page = found[: query.limit]
    revisions = (
        {
            row.item_revision_id: row
            for row in session.execute(
                select(
                    ItemRevisionRecord.item_revision_id,
                    ItemRevisionRecord.item_id,
                    ItemRevisionRecord.manifest_sha256,
                    ItemRevisionRecord.revision_state,
                    ItemRecord.lifecycle_state,
                )
                .join(ItemRecord, ItemRecord.item_id == ItemRevisionRecord.item_id)
                .where(
                    ItemRevisionRecord.item_revision_id.in_(
                        {row["item_revision_id"] for row in page}
                    )
                )
            )
        }
        if page
        else {}
    )
    rows = []
    for row in page:
        revision = revisions.get(row["item_revision_id"])
        if (
            revision is None
            or revision.item_id != row["item_id"]
            or revision.lifecycle_state != "ACTIVE"
            or revision.revision_state not in ("APPROVED", "SUPERSEDED")
        ):
            raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
        rows.append(
            PriorUsageLocation(
                **{
                    key: value
                    for key, value in row.items()
                    if key not in ("item_id", "item_revision_id")
                },
                target=OriginItemRevisionPointer(
                    item_id=revision.item_id,
                    item_revision_id=revision.item_revision_id,
                    item_manifest_sha256=revision.manifest_sha256,
                ),
            )
        )
    return PriorUsagePage(
        query_sha256=content_sha256(query.model_dump(mode="json")),
        rows=tuple(rows),
        next_after=(
            PriorUsageCursor(ledger=rows[-1].ledger, usage_record_id=rows[-1].usage_record_id)
            if len(found) > query.limit
            else None
        ),
    )
