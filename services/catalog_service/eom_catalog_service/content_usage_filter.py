"""Read-only semi/anti-join applied before the existing Item/source pagination."""

from typing import Literal

from eom_catalog_contracts.content_usage_filter import ContentUsageFilter
from sqlalchemy import ColumnElement, or_, select, true

from eom_catalog_service.content_usage_projection import content_usage_rows
from eom_catalog_service.creative_source_registration import creative_registration_pairs
from eom_catalog_service.external_item_models import ExternalItemSourceRecord
from eom_catalog_service.models import ItemRevisionRecord


def content_usage_condition(
    query: ContentUsageFilter, *, target_kind: Literal["ITEM", "SOURCE"]
) -> ColumnElement[bool]:
    used = content_usage_rows(true(), query.academic_year)
    lineage = creative_registration_pairs().subquery("usage_lineage")
    owner: type[ItemRevisionRecord] | type[ExternalItemSourceRecord]
    if target_kind == "ITEM":
        owner = ItemRevisionRecord
        identity = ItemRevisionRecord.item_id
        direct, related, alias, alias_identity = (
            used.c.item_id,
            used.c.source_id,
            lineage.c.source_id,
            lineage.c.item_id,
        )
    else:
        owner = ExternalItemSourceRecord
        identity = ExternalItemSourceRecord.source_id
        direct, related, alias, alias_identity = (
            used.c.source_id,
            used.c.item_id,
            lineage.c.item_id,
            lineage.c.source_id,
        )
    condition = or_(
        direct == identity,
        related.in_(select(alias).where(alias_identity == identity).correlate(owner)),
    )
    exists = select(used.c.placement_id).where(condition).correlate(owner).exists()
    return exists if query.state == "USED" else ~exists
