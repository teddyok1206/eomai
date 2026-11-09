"""Canonical source-to-Item registration relation, shared by Catalog read projections."""

from typing import Any

from eom_catalog_contracts.creative_source_lineage import CREATIVE_REGISTRATION_KEY_PREFIX
from sqlalchemy import and_, literal, select

from eom_catalog_service.external_item_models import (
    ExternalItemImportRecord,
    ExternalItemSourceRecord,
    ExternalItemSourceRevisionRecord,
)
from eom_catalog_service.models import ItemRecord, ItemRevisionRecord


def creative_registration_source_condition() -> Any:
    """Correlate exact source revision; never infer equivalence from the filename."""
    metadata = ItemRevisionRecord.metadata_json
    return and_(
        ItemRevisionRecord.registration_key
        == literal(CREATIVE_REGISTRATION_KEY_PREFIX) + ExternalItemSourceRecord.source_id,
        metadata["source_kind"].as_string() == "CREATIVE",
        metadata["source_id"].as_string() == ExternalItemSourceRecord.source_id,
        metadata["source_revision_id"].as_string() == ExternalItemSourceRevisionRecord.revision_id,
        metadata["external_number"].as_string() == ExternalItemSourceRecord.external_number,
    )


def creative_registration_pairs() -> Any:
    source, revision, item = (
        ExternalItemSourceRecord,
        ExternalItemSourceRevisionRecord,
        ItemRevisionRecord,
    )
    return (
        select(source.source_id, item.item_id)
        .join(revision, revision.source_id == source.source_id)
        .join(item, creative_registration_source_condition())
        .join(ItemRecord, ItemRecord.item_id == item.item_id)
        .join(ExternalItemImportRecord, ExternalItemImportRecord.import_id == revision.import_id)
        .where(
            ItemRecord.lifecycle_state == "ACTIVE",
            item.revision_state != "RETIRED",
            item.metadata_json["import_id"].as_string() == revision.import_id,
            ExternalItemImportRecord.state == "COMPLETED",
        )
        .distinct()
    )
