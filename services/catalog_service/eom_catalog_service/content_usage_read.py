"""Indexed union of current and printed usage, one row per exact occurrence.

Three bounded SQL projections (count, keys, representatives) replace history/item
scans. Membership is indexed by Item/source; JSON is only the small target value.
Print repetitions aggregate separately from location count. No artifact bytes.
"""

from eom_catalog_contracts.content_usage import (
    ContentUsageCount,
    ContentUsageCursor,
    ContentUsageLocation,
    ContentUsagePage,
    ContentUsageSummary,
    ReadContentUsage,
    ReadContentUsageSummary,
)
from eom_catalog_contracts.curated_document_slots import (
    CuratedSlot,
    ResolvedCuratedSlot,
    logical_slot_target_key,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, PermissionKey
from sqlalchemy import (
    Integer,
    String,
    and_,
    column,
    func,
    literal,
    or_,
    select,
    tuple_,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import Subquery

from eom_catalog_service.content_planning_access import ContentPlanningError
from eom_catalog_service.content_usage_identity import content_usage_identity_matches
from eom_catalog_service.content_usage_projection import content_usage_rows
from eom_catalog_service.curated_document_slot_models import CuratedDocumentAssemblySlotRecord
from eom_catalog_service.curated_document_slot_resolution import resolve_curated_slots


def _usage_locations(
    session: Session, query: ReadContentUsage, actor: ActorContext
) -> tuple[Subquery, Subquery, dict[tuple[str, str], set[int]]]:
    requests = tuple(
        CuratedSlot(
            placement_id=f"placement_{index:032x}",
            position=index + 1,
            target=target,
            points_milli=None,
            display_number=None,
            note="",
            copied_from=None,
        )
        for index, target in enumerate(query.targets)
    )
    resolve_curated_slots(session, requests, actor)
    matches = content_usage_identity_matches(session, query.targets, actor)
    source_ids = [key for kind, key in matches if kind == "SOURCE"]
    item_ids = [key for kind, key in matches if kind == "ITEM"]
    if PermissionKey.CONTENT_INTAKE_READ not in actor.permissions:
        source_ids = []
    slots = CuratedDocumentAssemblySlotRecord
    uses = content_usage_rows(
        or_(slots.source_id.in_(source_ids), slots.item_id.in_(item_ids)),
        query.academic_year,
    )
    key_names = ("edition_id", "year_key", "form_id", "placement_id", "target")
    keys = [uses.c[name] for name in key_names]
    grouped = (
        select(
            *keys,
            func.max(uses.c.is_current).label("is_current"),
            func.count(func.distinct(uses.c.print_id)).label("print_count"),
            func.max(uses.c.print_id).label("sample_print_id"),
        )
        .group_by(*keys)
        .subquery("locations")
    )
    return uses, grouped, matches


def read_content_usage(
    session: Session, query: ReadContentUsage, actor: ActorContext
) -> ContentUsagePage:
    uses, grouped, matches = _usage_locations(session, query, actor)
    key_names = ("edition_id", "year_key", "form_id", "placement_id", "target")
    keys = [uses.c[name] for name in key_names]
    total = session.scalar(select(func.count()).select_from(grouped)) or 0
    statement = (
        select(grouped).order_by(*(grouped.c[name] for name in key_names)).limit(query.limit + 1)
    )
    if query.after is not None:
        cursor = query.after
        statement = statement.where(
            tuple_(*(grouped.c[name] for name in key_names))
            > tuple_(
                literal(cursor.edition_id),
                literal(cursor.year_key),
                literal(cursor.form_id),
                literal(cursor.placement_id),
                literal(cursor.target.model_dump(mode="json"), type_=JSONB),
            )
        )
    found = session.execute(statement).mappings().all()
    page = found[: query.limit]
    locations = []
    if page:
        page_keys = or_(
            *(
                and_(
                    *(
                        uses.c[name]
                        == (literal(row[name], type_=JSONB) if name == "target" else row[name])
                        for name in key_names
                    )
                )
                for row in page
            )
        )
        ranked = (
            select(
                uses,
                func.row_number()
                .over(
                    partition_by=keys,
                    order_by=(
                        uses.c.is_current.desc(),
                        uses.c.recorded_at.desc(),
                        uses.c.revision_id.desc(),
                    ),
                )
                .label("rn"),
            )
            .where(page_keys)
            .subquery("representatives")
        )
        chosen = (
            session.execute(
                select(ranked)
                .where(ranked.c.rn == 1)
                .order_by(*(ranked.c[name] for name in key_names))
            )
            .mappings()
            .all()
        )
        if len(chosen) != len(page):
            raise ContentPlanningError("CONTENT_USAGE_CHANGED")
        resolved_slots = tuple(ResolvedCuratedSlot.model_validate(row["slot"]) for row in chosen)
        if (
            resolve_curated_slots(
                session, tuple(slot.selection() for slot in resolved_slots), actor
            )
            != resolved_slots
        ):
            raise ContentPlanningError("CONTENT_SLOT_POINTER_INVALID")
        for row, aggregate, slot in zip(chosen, page, resolved_slots, strict=True):
            key = logical_slot_target_key(slot.target)
            indices = matches.get(key, set()) if key is not None else set()
            locations.append(
                ContentUsageLocation(
                    **{
                        name: row[name]
                        for name in (
                            "edition_id",
                            "deliverable_id",
                            "revision_id",
                            "content_title",
                            "edition_label",
                            "academic_year",
                            "section_id",
                            "section_label",
                            "form_id",
                            "placement_id",
                            "position",
                        )
                    },
                    target=slot.target,
                    currently_placed=bool(aggregate["is_current"]),
                    print_count=aggregate["print_count"],
                    sample_print_record_id=aggregate["sample_print_id"],
                    matched_target_indices=tuple(sorted(indices)),
                )
            )
    next_cursor = (
        ContentUsageCursor.model_validate({name: page[-1][name] for name in key_names})
        if len(found) > query.limit
        else None
    )
    return ContentUsagePage(
        query_sha256=content_sha256(query.model_dump(mode="json")),
        total_locations=total,
        rows=tuple(locations),
        next_after=next_cursor,
    )


def read_content_usage_summary(
    session: Session, query: ReadContentUsageSummary, actor: ActorContext
) -> ContentUsageSummary:
    """One aggregate query for visible targets; no per-item history scans or body reads."""
    selection = ReadContentUsage(
        query_kind="USAGE",
        targets=query.targets,
        academic_year=query.academic_year,
        after=None,
        limit=200,
    )
    _, locations, matches = _usage_locations(session, selection, actor)
    aliases = values(
        column("kind", String),
        column("identity", String),
        column("target_index", Integer),
        name="requested_aliases",
    ).data(
        tuple(
            (kind, identity, index)
            for (kind, identity), indices in matches.items()
            for index in sorted(indices)
        )
    )
    target = locations.c.target
    condition = or_(
        and_(aliases.c.kind == "SOURCE", target["source_id"].astext == aliases.c.identity),
        and_(aliases.c.kind == "ITEM", target["item_id"].astext == aliases.c.identity),
    )
    statement = (
        select(
            aliases.c.target_index,
            func.count(),
            func.count().filter(
                locations.c.edition_id == query.edition_id,
            ),
        )
        .select_from(locations.join(aliases, condition))
        .group_by(aliases.c.target_index)
    )
    counts = {index: (total, current) for index, total, current in session.execute(statement)}
    return ContentUsageSummary(
        query_sha256=content_sha256(query.model_dump(mode="json")),
        rows=tuple(
            ContentUsageCount(
                target_index=index,
                total_locations=counts.get(index, (0, 0))[0],
                edition_locations=counts.get(index, (0, 0))[1],
                other_locations=counts.get(index, (0, 0))[0] - counts.get(index, (0, 0))[1],
            )
            for index in range(len(query.targets))
        ),
    )
